"""Vaulting and un-vaulting an artifact (VAULT.3 + VAULT.4 helpers).

Vaulting encrypts an artifact's sensitive content AT REST with the PIN-derived
vault key and drops it from the retrieval index, then flips `vaulted_at` so every
live surface (which filters `vaulted_at IS NULL`, VAULT.4) stops showing it. The
encrypted fields ride the normal snapshot/blob sync as opaque ciphertext, so other
devices - and the relay - hold only vault-ciphertext and cannot read it without
the PIN, even though they have the library DEK. Un-vaulting reverses both: decrypt
in place, then re-index.

Protected at rest: `artifacts.body`, `artifacts.title`, every `annotations.text`,
every `page_text.text`, and the blob file (image/pdf/file bytes). Left in clear so
sync + LWW + dedupe still work: `id`, `content_hash`, timestamps, `kind`, and
`vaulted_at` itself.

The vault must be UNLOCKED (`vault.key()`); callers gate the UI on that and the
API returns 409 when it is locked.
"""

from __future__ import annotations

import base64
import contextlib

from . import crypto, db, vault
from .sync.client import push_artifact


def _seal(key: bytes, plaintext: str | None) -> str | None:
    if plaintext is None:
        return None
    return base64.b64encode(crypto.encrypt(plaintext.encode("utf-8"), key)).decode("ascii")


def _open(key: bytes, sealed: str | None) -> str | None:
    if sealed is None:
        return None
    return crypto.decrypt(base64.b64decode(sealed), key).decode("utf-8")


def try_open(key: bytes, value: str | None) -> str | None:
    """Decrypt `value` if it is our vault-ciphertext, else return None.

    The secretbox authentication tag is a reliable discriminator: `crypto.decrypt`
    succeeds only on bytes this key actually sealed, so plaintext (which is not valid
    base64 + a valid poly1305 tag) fails and we return None. This lets a surface
    detect a still-sealed field WITHOUT a `vaulted_at` flag - which is exactly the
    orphan state a partial un-vault can leave behind (encrypted bytes, flag cleared).
    """
    if not value:
        return None
    try:
        return crypto.decrypt(base64.b64decode(value), key).decode("utf-8")
    except Exception:  # noqa: BLE001 - any failure means "not our ciphertext"
        return None


def _blob_file(content_hash: str | None):
    from . import config

    if not content_hash:
        return None
    path = config.BLOB_DIR / content_hash
    return path if path.exists() else None


def _vacuum() -> None:
    # VACUUM cannot run inside a transaction; use a fresh short-lived connection.
    conn = db.get_conn()
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()


def _drop_from_index(artifact_id: str) -> None:
    # Same de-index as trash: a vaulted artifact must not surface as a citation or
    # search hit. Derived rows are rebuildable, so they are dropped, not filtered.
    with contextlib.suppress(Exception):  # noqa: BLE001 - derived data, safe to leave
        from .index.store import get_store

        store = get_store()
        store.drop_artifact(store.CHUNKS, artifact_id)
        store.drop_artifact(store.FACETS, artifact_id)
        store.drop_artifact(store.ENTITIES, artifact_id)


def vault_artifact(artifact_id: str) -> dict:
    """Encrypt the artifact's content at rest and take it out of every live view."""
    key = vault.key()  # raises VaultError if locked
    now = db.now()
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT body, title, content_hash, vaulted_at FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        if row["vaulted_at"]:
            return {"id": artifact_id, "vaulted_at": row["vaulted_at"], "already": True}

        conn.execute(
            "UPDATE artifacts SET body = ?, title = ?, vaulted_at = ?, updated_at = ? WHERE id = ?",
            (_seal(key, row["body"]), _seal(key, row["title"]), now, now, artifact_id),
        )
        for a in conn.execute(
            "SELECT id, text FROM annotations WHERE artifact_id = ?", (artifact_id,)
        ).fetchall():
            conn.execute(
                "UPDATE annotations SET text = ? WHERE id = ?", (_seal(key, a["text"]), a["id"])
            )
        for pt in conn.execute(
            "SELECT page, text FROM page_text WHERE artifact_id = ?", (artifact_id,)
        ).fetchall():
            conn.execute(
                "UPDATE page_text SET text = ? WHERE artifact_id = ? AND page = ?",
                (_seal(key, pt["text"]), artifact_id, pt["page"]),
            )
        # The edit history keeps prior plaintext bodies - seal those too, or the
        # vault leaks through artifact_versions.
        for v in conn.execute(
            "SELECT id, body FROM artifact_versions WHERE artifact_id = ?", (artifact_id,)
        ).fetchall():
            conn.execute(
                "UPDATE artifact_versions SET body = ? WHERE id = ?",
                (_seal(key, v["body"]), v["id"]),
            )

        # Encrypt the blob file in place (image/pdf/file). content_hash stays the
        # PLAINTEXT hash (the dedupe/identity key); the bytes on disk become
        # vault-ciphertext and get_blob decrypts them while the vault is unlocked.
        blob = _blob_file(row["content_hash"])
        if blob is not None:
            blob.write_bytes(crypto.encrypt(blob.read_bytes(), key))
        # Drop the rebuildable chunks so retrieval can never cite a vaulted note.
        conn.execute("DELETE FROM chunks WHERE artifact_id = ?", (artifact_id,))

    # VACUUM (outside the transaction) rewrites the DB file so the freed pages that
    # still hold the pre-encryption plaintext are purged from disk, not just
    # unlinked - without this the old body lingers in the file's freelist.
    _vacuum()
    _drop_from_index(artifact_id)
    push_artifact(artifact_id)
    return {"id": artifact_id, "vaulted_at": now, "already": False}


def decrypt_in_place(conn, artifact_id: str, key: bytes) -> bool:
    """Decrypt every field of an artifact that is still vault-ciphertext and clear
    `vaulted_at`, WITHOUT re-indexing or pushing (the caller owns the transaction and
    the sync). Flag-agnostic: it decrypts by trying `try_open` on each field, so it
    also repairs an ORPHAN - encrypted bytes whose `vaulted_at` was already cleared by
    an earlier partial un-vault. Returns True if anything was decrypted.

    Used when a vaulted item leaves the vault by being deleted/restored: the trash and
    restore must hold and return the plaintext original, not opaque ciphertext.
    """
    touched = False

    def dec(value):
        nonlocal touched
        opened = try_open(key, value)
        if opened is not None:
            touched = True
            return opened
        return value

    row = conn.execute(
        "SELECT body, title, content_hash FROM artifacts WHERE id = ?", (artifact_id,)
    ).fetchone()
    if row is None:
        return False
    conn.execute(
        "UPDATE artifacts SET body = ?, title = ?, vaulted_at = NULL WHERE id = ?",
        (dec(row["body"]), dec(row["title"]), artifact_id),
    )
    for a in conn.execute(
        "SELECT id, text FROM annotations WHERE artifact_id = ?", (artifact_id,)
    ).fetchall():
        conn.execute("UPDATE annotations SET text = ? WHERE id = ?", (dec(a["text"]), a["id"]))
    for pt in conn.execute(
        "SELECT page, text FROM page_text WHERE artifact_id = ?", (artifact_id,)
    ).fetchall():
        conn.execute(
            "UPDATE page_text SET text = ? WHERE artifact_id = ? AND page = ?",
            (dec(pt["text"]), artifact_id, pt["page"]),
        )
    for v in conn.execute(
        "SELECT id, body FROM artifact_versions WHERE artifact_id = ?", (artifact_id,)
    ).fetchall():
        conn.execute(
            "UPDATE artifact_versions SET body = ? WHERE id = ?", (dec(v["body"]), v["id"])
        )
    # The blob: decrypt only if it actually opens with the vault key.
    blob = _blob_file(row["content_hash"])
    if blob is not None:
        raw = blob.read_bytes()
        with contextlib.suppress(Exception):  # noqa: BLE001 - not our ciphertext -> leave as is
            plain = crypto.decrypt(raw, key)
            blob.write_bytes(plain)
            touched = True
    return touched


def unvault_artifact(artifact_id: str) -> dict:
    """Decrypt the artifact back and rebuild its index rows."""
    from .ingest import queue as ingest_queue

    key = vault.key()
    now = db.now()
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT body, title, content_hash, vaulted_at FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        if not row["vaulted_at"]:
            return {"id": artifact_id, "already_out": True}

        conn.execute(
            "UPDATE artifacts SET body = ?, title = ?, vaulted_at = NULL, updated_at = ? WHERE id = ?",
            (_open(key, row["body"]), _open(key, row["title"]), now, artifact_id),
        )
        for a in conn.execute(
            "SELECT id, text FROM annotations WHERE artifact_id = ?", (artifact_id,)
        ).fetchall():
            conn.execute(
                "UPDATE annotations SET text = ? WHERE id = ?", (_open(key, a["text"]), a["id"])
            )
        for pt in conn.execute(
            "SELECT page, text FROM page_text WHERE artifact_id = ?", (artifact_id,)
        ).fetchall():
            conn.execute(
                "UPDATE page_text SET text = ? WHERE artifact_id = ? AND page = ?",
                (_open(key, pt["text"]), artifact_id, pt["page"]),
            )
        for v in conn.execute(
            "SELECT id, body FROM artifact_versions WHERE artifact_id = ?", (artifact_id,)
        ).fetchall():
            conn.execute(
                "UPDATE artifact_versions SET body = ? WHERE id = ?",
                (_open(key, v["body"]), v["id"]),
            )

        blob = _blob_file(row["content_hash"])
        if blob is not None:
            blob.write_bytes(crypto.decrypt(blob.read_bytes(), key))

    ingest_queue.submit(artifact_id)  # rebuild chunks/facets/entities
    push_artifact(artifact_id)
    return {"id": artifact_id, "restored": True}


def listing() -> dict:
    """The vault's artifacts, shaped exactly like a wall item so the same card
    renders them: decrypted title + a decrypted excerpt, plus the display fields.
    Requires the vault unlocked."""
    key = vault.key()
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, kind, title, body, source_url, content_hash, filename, mime,"
            " created_at, updated_at, local_only, status, pinned"
            " FROM artifacts WHERE vaulted_at IS NOT NULL AND deleted_at IS NULL"
            " ORDER BY updated_at DESC"
        ).fetchall()
    finally:
        conn.close()
    items = []
    for row in rows:
        item = dict(row)
        item["title"] = _open(key, row["title"])
        body = _open(key, row["body"]) or ""
        # The wall's `excerpt` is the first slice of the body; match it.
        item["excerpt"] = " ".join(body.split())[:280]
        item.pop("body", None)
        items.append(item)
    return {"items": items}


def get(artifact_id: str) -> dict:
    """One vaulted artifact, decrypted, for the vault reader. Requires unlock."""
    key = vault.key()
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
    finally:
        conn.close()
    if row is None or not row["vaulted_at"]:
        raise KeyError(artifact_id)
    art = dict(row)
    art["title"] = _open(key, row["title"])
    art["body"] = _open(key, row["body"])
    return {"artifact": art}


def blob_bytes(artifact_id: str) -> tuple[bytes, str, str] | None:
    """Decrypted (mime, filename) blob for a vaulted artifact. Requires unlock."""
    key = vault.key()
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT content_hash, mime, filename, vaulted_at FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None or not row["vaulted_at"]:
        return None
    blob = _blob_file(row["content_hash"])
    if blob is None:
        return None
    raw = crypto.decrypt(blob.read_bytes(), key)
    return raw, row["mime"] or "application/octet-stream", row["filename"] or artifact_id
