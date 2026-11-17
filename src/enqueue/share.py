"""Shared notes: a read-only web link to one note, which the relay cannot read.

A share follows the note: each change to a shared note reaches the link once the edits
pause for QUIET_S (`follow`, called by every ingest run), so a reader who reloads sees the
note as it is now. The copy is sealed here with AES-256-GCM, stored on the sync relay (`PUT /share/<id>`, in the
library's own space) and opened in a browser by the viewer the relay serves at
`/s/<id>`. The key rides the link after `#`, which a browser never sends to a server.
With a passphrase, the key that seals is PBKDF2 of the passphrase salted with the link's
key, so the link alone opens nothing.

The sealed bytes: `ENQS`, a format byte (1), a flags byte (1 = needs a passphrase), a
12-byte nonce, then the AES-GCM ciphertext of `{"v", "title", "body", "shared_at"}` with
the first 18 bytes as its associated data. `static/js/share.js` reads exactly this.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import logging
import secrets
import threading
import unicodedata
from datetime import datetime, timedelta, timezone

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import db, keyring, settings

MAGIC = b"ENQS"
FORMAT = 1
NEEDS_PASSPHRASE = 1
PBKDF2_ROUNDS = 600_000
EXPIRES = {"1d": timedelta(days=1), "1w": timedelta(weeks=1), "never": None}
# Seconds a shared note must be left alone before its link takes the new text.
QUIET_S = 3.0
_bases: dict[str, str] = {}
_timers: dict[str, threading.Timer] = {}
_timers_lock = threading.Lock()
log = logging.getLogger(__name__)


class ShareError(Exception):
    """A share that cannot be made or changed; the message is for the person. `code`
    is `pro` when the plan does not include sharing."""

    def __init__(self, message: str, code: str = "", status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def seal_key(link_key: bytes, passphrase: str | None) -> bytes:
    if not passphrase:
        return link_key
    word = unicodedata.normalize("NFC", passphrase).encode()
    return hashlib.pbkdf2_hmac("sha256", word, link_key, PBKDF2_ROUNDS, 32)


def seal(key: bytes, payload: dict, passphrase: bool) -> bytes:
    head = MAGIC + bytes([FORMAT, NEEDS_PASSPHRASE if passphrase else 0]) + os.urandom(12)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return head + AESGCM(key).encrypt(head[6:], body, head)


def open_sealed(key: bytes, data: bytes) -> dict:
    head = data[:18]
    return json.loads(AESGCM(key).decrypt(head[6:], data[18:], head))


def _relay() -> tuple[str, str]:
    url = (settings.get("sync_relay_url") or "").strip().rstrip("/")
    secret = keyring.sync_secret_get() or ""
    if not url or not secret:
        raise ShareError(
            "Turn on sync first: a shared note is kept on your sync relay.", "sync", 409
        )
    return url, secret


def _base(relay: str) -> str:
    """Where this relay's shared links point: its own SHARE_BASE_URL, else itself."""
    if relay not in _bases:
        try:
            got = httpx.get(f"{relay}/health", timeout=10).json().get("share_base") or ""
        except (httpx.HTTPError, ValueError):
            return relay
        _bases[relay] = got.rstrip("/") or relay
    return _bases[relay]


def _call(method: str, path: str, **kw) -> httpx.Response:
    relay, secret = _relay()
    try:
        r = httpx.request(
            method,
            f"{relay}{path}",
            headers={"Authorization": f"Bearer {secret}"},
            timeout=30,
            **kw,
        )
    except httpx.HTTPError as exc:
        raise ShareError("Could not reach your sync relay. Try again.", status=503) from exc
    if r.status_code == 402:
        raise ShareError("Sharing notes is part of Enqueue Pro.", "pro", 402)
    if r.status_code == 413:
        raise ShareError("Your sync storage is full.", status=413)
    if r.status_code >= 400 and not (method == "DELETE" and r.status_code == 404):
        raise ShareError(f"The relay refused the share ({r.status_code}).", status=502)
    return r


def _note(conn, artifact_id: str):
    row = conn.execute(
        "SELECT id, kind, title, body, local_only, vaulted_at, deleted_at, purged_at"
        " FROM artifacts WHERE id = ?",
        (artifact_id,),
    ).fetchone()
    if row is None or row["purged_at"]:
        raise ShareError("No such note.", status=404)
    if row["kind"] != "note":
        raise ShareError("Only notes can be shared.")
    if row["local_only"]:
        raise ShareError("This note is kept on this Mac only, so it cannot be shared.")
    if row["vaulted_at"]:
        raise ShareError("A note in the vault cannot be shared.")
    if row["deleted_at"]:
        raise ShareError("This note is in the trash.")
    return row


def _hash(row) -> str:
    return hashlib.sha256(f"{row['title'] or ''}\n{row['body'] or ''}".encode()).hexdigest()


def _upload(row, share) -> str:
    """Seal the note as it is now and store it under the share's id. Returns the time."""
    shared_at = db.now()
    payload = {"v": 1, "title": row["title"] or "", "body": row["body"] or ""}
    payload["shared_at"] = shared_at
    data = seal(_unb64(share["seal_key"]), payload, bool(share["passphrase"]))
    params = {}
    if share["expires_at"]:
        params["expires_at"] = datetime.fromisoformat(share["expires_at"]).timestamp()
    _call("PUT", f"/share/{share['share_id']}", content=data, params=params)
    return shared_at


def _expired(share) -> bool:
    at = share["expires_at"]
    return bool(at) and datetime.fromisoformat(at) <= datetime.now(timezone.utc)


def _touch(conn, artifact_id: str) -> None:
    """A new date, so the share's start or end wins on the other devices."""
    conn.execute("UPDATE artifacts SET updated_at = ? WHERE id = ?", (db.now(), artifact_id))


def _push(artifact_id: str) -> None:
    from .sync.client import push_artifact

    push_artifact(artifact_id)


def info(artifact_id: str) -> dict:
    """Whether the note is shared, its link, and whether it changed since."""
    conn = db.get_conn()
    try:
        share = conn.execute(
            "SELECT * FROM shares WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        if share is not None and _expired(share):
            conn.execute("DELETE FROM shares WHERE artifact_id = ?", (artifact_id,))
            conn.commit()
            share = None
        if share is None:
            return {"shared": False}
        row = conn.execute(
            "SELECT title, body FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
    finally:
        conn.close()
    try:
        base = _base(_relay()[0])
    except ShareError:
        base = ""
    return {
        "shared": True,
        "url": f"{base}/s/{share['share_id']}#{share['link_key']}" if base else None,
        "expires_at": share["expires_at"],
        "shared_at": share["shared_at"],
        "passphrase": bool(share["passphrase"]),
        # Behind: the link lacks the latest edit and no send is waiting (one failed).
        "changed": row is not None
        and _hash(row) != share["shared_hash"]
        and artifact_id not in _timers,
    }


def create(artifact_id: str, expires: str = "never", passphrase: str | None = None) -> dict:
    """Share a note: a new link, sealed as the note is now."""
    if expires not in EXPIRES:
        raise ShareError("Choose 1 day, 1 week or never.")
    conn = db.get_conn()
    try:
        row = _note(conn, artifact_id)
    finally:
        conn.close()
    stop(artifact_id)
    link_key = secrets.token_bytes(32)
    span = EXPIRES[expires]
    now = datetime.now(timezone.utc)
    share = {
        "share_id": _b64(secrets.token_bytes(16)),
        "link_key": _b64(link_key),
        "seal_key": _b64(seal_key(link_key, passphrase)),
        "passphrase": 1 if passphrase else 0,
        "expires_at": (now + span).isoformat() if span else None,
    }
    shared_at = _upload(row, share)
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO shares (artifact_id, share_id, link_key, seal_key, passphrase,"
            " expires_at, created_at, shared_at, shared_hash) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                artifact_id,
                share["share_id"],
                share["link_key"],
                share["seal_key"],
                share["passphrase"],
                share["expires_at"],
                shared_at,
                shared_at,
                _hash(row),
            ),
        )
        _touch(conn, artifact_id)
    _push(artifact_id)
    return info(artifact_id)


def follow(artifact_id: str) -> None:
    """A note changed: when it is shared and differs from its link's copy, send the new
    text once the edits pause. Cheap when the note is not shared."""
    conn = db.get_conn()
    try:
        share = conn.execute(
            "SELECT shared_hash FROM shares WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        row = (
            conn.execute(
                "SELECT title, body FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
            if share
            else None
        )
    finally:
        conn.close()
    if row is None or _hash(row) == share["shared_hash"]:
        return
    with _timers_lock:
        old = _timers.pop(artifact_id, None)
        if old is not None:
            old.cancel()
        timer = threading.Timer(QUIET_S, _follow_now, (artifact_id,))
        timer.daemon = True
        _timers[artifact_id] = timer
        timer.start()


def _follow_now(artifact_id: str) -> None:
    with _timers_lock:
        _timers.pop(artifact_id, None)
    try:
        update(artifact_id)
    except ShareError as exc:
        # The share dialog shows the link as behind and offers to send it again.
        log.info("shared note %s not updated: %s", artifact_id, exc)


def update(artifact_id: str) -> dict:
    """Replace the shared copy with the note as it is now; the link stays the same."""
    conn = db.get_conn()
    try:
        row = _note(conn, artifact_id)
        share = conn.execute(
            "SELECT * FROM shares WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
    finally:
        conn.close()
    if share is None or _expired(share):
        raise ShareError("This note is not shared.", status=404)
    shared_at = _upload(row, share)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE shares SET shared_at = ?, shared_hash = ? WHERE artifact_id = ?",
            (shared_at, _hash(row), artifact_id),
        )
    # No new date: the other devices take the copy's hash on an equal key.
    _push(artifact_id)
    return info(artifact_id)


def stop(artifact_id: str) -> None:
    """Stop sharing: the relay forgets the copy and the link opens nothing."""
    conn = db.get_conn()
    try:
        share = conn.execute(
            "SELECT share_id FROM shares WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
    finally:
        conn.close()
    if share is None:
        return
    _call("DELETE", f"/share/{share['share_id']}")
    with db.transaction() as conn:
        conn.execute("DELETE FROM shares WHERE artifact_id = ?", (artifact_id,))
        _touch(conn, artifact_id)
    _push(artifact_id)


def stop_quietly(artifact_id: str) -> None:
    """Stop sharing a note that is going (trash, vault, purge); a relay that cannot be
    reached leaves the row, and the next try or the link's expiry finishes it."""
    try:
        stop(artifact_id)
    except ShareError:
        pass


def forget_later(artifact_id: str) -> None:
    """Stop sharing in the background: the trash and the vault do not wait on the relay."""
    threading.Thread(target=stop_quietly, args=(artifact_id,), daemon=True).start()


def retry_stops() -> int:
    """Stop every share whose note is gone, trashed, vaulted or kept on this Mac only:
    one that could not reach the relay when it went, or one trashed on the phone."""
    conn = db.get_conn()
    try:
        ids = [
            r["artifact_id"]
            for r in conn.execute(
                "SELECT s.artifact_id FROM shares s LEFT JOIN artifacts a"
                " ON a.id = s.artifact_id WHERE a.id IS NULL OR a.deleted_at IS NOT NULL"
                " OR a.vaulted_at IS NOT NULL OR a.local_only = 1"
            )
        ]
    finally:
        conn.close()
    for aid in ids:
        stop_quietly(aid)
    return len(ids)
