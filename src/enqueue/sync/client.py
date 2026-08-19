"""The relay client: push snapshot objects (SYNC.4).

In the plaintext prototype the object is the canonical-JSON snapshot (E2E.md
Section 1); after SYNC.8 it is the same snapshot encrypted, and this push code
is unchanged except for the one wrap call. The object is PUT under this
device's namespace with a name that is stable for a given artifact, so
re-pushing an unchanged snapshot is a no-op (the relay returns 409).
"""

from __future__ import annotations

import httpx

from .. import config, crypto, db, keyring, keyring_file, settings
from . import device_id
from .guard import assert_local_relay
from .snapshot import apply_pulled_snapshot, deserialize, read_artifact_snapshot, serialize


def _relay_url() -> str:
    return (settings.get("sync_relay_url") or "").strip()


def _secret() -> str:
    return keyring.sync_secret_get() or ""


def _cursor_path():
    return config.DATA_DIR / "sync_cursor"


def _read_cursor() -> int:
    try:
        return int(_cursor_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _write_cursor(cursor: int) -> None:
    path = _cursor_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(cursor), encoding="utf-8")


def push_artifact(artifact_id: str) -> None:
    """PUT one artifact's snapshot to the relay, when sync is configured.

    A push failure never breaks the local edit: it is reported and the snapshot
    is simply retried on the next push. Local-only artifacts never leave.
    """
    url = _relay_url()
    if not url:
        return
    assert_local_relay(url)

    conn = db.get_conn()
    try:
        snapshot = read_artifact_snapshot(conn, artifact_id)
    finally:
        conn.close()
    if snapshot is None:
        return
    if snapshot["artifact"].get("local_only"):
        return

    dek = keyring_file.dek()
    if dek is None:
        return  # the keyring is locked; sync is paused, not failing

    # Stamp this device's id (E2E.md Phase E4), serialize, and encrypt at the
    # relay boundary (SYNC.8). The relay stores and streams these bytes as-is.
    snapshot["artifact"]["_device_id"] = device_id()
    data = crypto.encrypt(serialize(snapshot), dek)

    name = f"dev/{device_id()}/artifacts/{artifact_id}.enc"
    headers = {
        "Authorization": f"Bearer {_secret()}",
        "Content-Type": "application/octet-stream",
    }
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.put(
                f"{url.rstrip('/')}/sync/object/{name}", content=data, headers=headers
            )
    except httpx.HTTPError as exc:
        # The relay is unreachable. Report and move on; the local edit already landed.
        print(f"[sync] push failed for {artifact_id}: {exc}", flush=True)
        return
    # 201 = stored, 409 = already present (idempotent no-op). Anything else is a
    # real error worth surfacing, but never fatal to the edit.
    if resp.status_code not in (201, 409):
        print(f"[sync] push rejected for {artifact_id}: {resp.status_code}", flush=True)
        return

    # Push the file blob for captures (E2E.md E5: blobs are fetched on demand by the
    # reader/thumbnails). The blob name is HMAC(content_hash, DEK), so it reveals
    # nothing about the content; the bytes are encrypted like the snapshot.
    kind = snapshot["artifact"].get("kind")
    content_hash = snapshot["artifact"].get("content_hash")
    if kind in ("image", "pdf", "file") and content_hash:
        blob_path = config.BLOB_DIR / content_hash
        if blob_path.exists():
            blob_name = crypto.blob_name(content_hash, dek)
            blob_data = crypto.encrypt(blob_path.read_bytes(), dek)
            try:
                with httpx.Client(timeout=60) as client:
                    bresp = client.put(
                        f"{url.rstrip('/')}/sync/object/blobs/{blob_name}",
                        content=blob_data,
                        headers=headers,
                    )
                if bresp.status_code not in (201, 409):
                    print(
                        f"[sync] blob push rejected for {artifact_id}: {bresp.status_code}",
                        flush=True,
                    )
            except httpx.HTTPError as exc:
                print(f"[sync] blob push failed for {artifact_id}: {exc}", flush=True)

    # Record that this device wrote the row, so the local LWW key matches what
    # other devices apply - both ends then converge to byte-identical state.
    with db.transaction() as conn:
        conn.execute("UPDATE artifacts SET _device_id = ? WHERE id = ?", (device_id(), artifact_id))


def pull() -> dict:
    """List changed objects since the cursor, download and apply snapshots (SYNC.5).

    Skips this device's own namespace (its snapshots are already local). Each
    incoming snapshot goes through `apply_snapshot`, whose LWW no-op check drops
    anything stale, so the pull is idempotent and safe to rerun. The cursor is
    persisted so a restart does not re-download the whole relay.
    """
    url = _relay_url()
    if not url:
        return {"pulled": 0}
    assert_local_relay(url)

    base = url.rstrip("/")
    headers = {"Authorization": f"Bearer {_secret()}"}
    cursor = _read_cursor()
    mine = f"dev/{device_id()}/"
    dek = keyring_file.dek()
    if dek is None:
        return {"pulled": 0}  # the keyring is locked; sync is paused

    with httpx.Client(timeout=30) as client:
        listing = client.get(f"{base}/sync/objects", params={"since": cursor}, headers=headers)
        if listing.status_code != 200:
            return {"pulled": 0, "error": listing.status_code}
        new_cursor = listing.json()["cursor"]

        pulled = 0
        for obj in listing.json()["objects"]:
            name = obj["name"]
            if name.startswith(mine):
                continue
            if not (name.startswith("dev/") and name.endswith(".enc")):
                continue  # blobs are fetched on demand (SYNC.8/E5), not pulled here
            resp = client.get(f"{base}/sync/object/{name}", headers=headers)
            if resp.status_code != 200:
                continue
            snapshot = deserialize(crypto.decrypt(resp.content, dek))
            with db.transaction() as conn:
                apply_pulled_snapshot(conn, snapshot)
            pulled += 1

    _write_cursor(new_cursor)
    return {"pulled": pulled}


def push_settings() -> None:
    """PUT the settings object to the relay (MOB2.9)."""
    url = _relay_url()
    if not url:
        return
    assert_local_relay(url)

    dek = keyring_file.dek()
    if dek is None:
        return

    # Load current settings from local config
    cfg = settings.load()
    s = {
        "llm_backend": cfg.get("llm_backend", "ollama"),
        "llm_model": cfg.get("llm_model", "llama3.1:8b"),
        "llm_url": cfg.get("llm_url", ""),
        "auto_preview": cfg.get("auto_preview", True),
        "trash_days": cfg.get("trash_days", "30"),
        "updated_at": "",  # will be filled by caller
    }
    import datetime

    s["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    data = crypto.encrypt(serialize(s), dek)
    timestamp = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
    name = f"lib/settings/{timestamp}-{device_id()}.enc"
    headers = {
        "Authorization": f"Bearer {_secret()}",
        "Content-Type": "application/octet-stream",
    }
    headers = {
        "Authorization": f"Bearer {_secret()}",
        "Content-Type": "application/octet-stream",
    }
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.put(
                f"{_relay_url().rstrip('/')}/sync/object/{name}", content=data, headers=headers
            )
        if resp.status_code not in (201, 409):
            print(f"[sync] settings push rejected: {resp.status_code}", flush=True)
    except httpx.HTTPError as exc:
        print(f"[sync] settings push failed: {exc}", flush=True)


def pull_settings() -> None:
    """Pull the latest settings object from the relay and apply it (MOB2.9)."""
    url = _relay_url()
    if not url:
        return
    assert_local_relay(url)

    dek = keyring_file.dek()
    if dek is None:
        return

    base = url.rstrip("/")
    headers = {"Authorization": f"Bearer {_secret()}"}
    cursor = _read_cursor()

    with httpx.Client(timeout=30) as client:
        listing = client.get(f"{base}/sync/objects", params={"since": cursor}, headers=headers)
        if listing.status_code != 200:
            return
        new_cursor = listing.json()["cursor"]

        for obj in listing.json()["objects"]:
            name = obj["name"]
            if not name.startswith("lib/settings/"):
                continue
            resp = client.get(f"{base}/sync/object/{name}", headers=headers)
            if resp.status_code != 200:
                continue
            s = deserialize(crypto.decrypt(resp.content, dek))
            if "updated_at" in s:
                with db.transaction() as conn:
                    for key, val in s.items():
                        if key in (
                            "llm_backend",
                            "llm_model",
                            "llm_url",
                            "auto_preview",
                            "trash_days",
                        ):
                            conn.execute(
                                "UPDATE settings SET value = ? WHERE key = ?",
                                (str(val), key),
                            )


def push_keyring() -> None:
    """PUT the keyring.json to the relay as lib/keyring.enc (MOB2.10).

    The keyring.json already contains the DEK wrapped twice (password-KEK and
    recovery-KEK). It does NOT contain the plaintext DEK, so it's safe to
    store on the relay without additional encryption.
    """
    url = _relay_url()
    if not url:
        return
    assert_local_relay(url)

    keyring_path = config.DATA_DIR / "keyring.json"
    if not keyring_path.exists():
        return

    keyring_bytes = keyring_path.read_bytes()

    name = "lib/keyring.enc"
    headers = {
        "Authorization": f"Bearer {_secret()}",
        "Content-Type": "application/octet-stream",
    }
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.put(
                f"{url.rstrip('/')}/sync/object/{name}", content=keyring_bytes, headers=headers
            )
        if resp.status_code not in (201, 409):
            print(f"[sync] keyring push rejected: {resp.status_code}", flush=True)
    except httpx.HTTPError as exc:
        print(f"[sync] keyring push failed: {exc}", flush=True)


def push_all() -> int:
    """FULL.1: Push all non-deleted, non-local artifacts to the relay.

    Iterates every artifact in the local DB, pushes its snapshot (and blob if any)
    to the relay. Idempotent: relay returns 409 for already-present objects.
    Returns the number of artifacts successfully pushed (201 responses).
    """
    url = _relay_url()
    if not url:
        return 0
    assert_local_relay(url)

    dek = keyring_file.dek()
    if dek is None:
        return 0  # keyring locked; nothing to push

    conn = db.get_conn()
    try:
        # Get all non-deleted, non-local artifacts
        rows = conn.execute(
            """SELECT id FROM artifacts 
            WHERE deleted_at IS NULL AND local_only = 0
            ORDER BY updated_at DESC"""
        ).fetchall()
        artifact_ids = [row[0] for row in rows]
    finally:
        conn.close()

    pushed = 0
    for artifact_id in artifact_ids:
        # Reuse the existing push logic but track 201 responses
        conn = db.get_conn()
        try:
            snapshot = read_artifact_snapshot(db.get_conn(), artifact_id)
        finally:
            pass  # read_artifact_snapshot closes its own conn
        if snapshot is None:
            continue
        if snapshot["artifact"].get("local_only"):
            continue

        snapshot["artifact"]["_device_id"] = device_id()
        from .snapshot import serialize
        data = crypto.encrypt(serialize(snapshot), dek)

        name = f"dev/{device_id()}/artifacts/{artifact_id}.enc"
        headers = {
            "Authorization": f"Bearer {_secret()}",
            "Content-Type": "application/octet-stream",
        }
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.put(
                    f"{_relay_url().rstrip('/')}/sync/object/{name}", content=data, headers=headers
                )
        except httpx.HTTPError:
            continue
        if resp.status_code == 201:
            pushed += 1
        elif resp.status_code != 409:
            continue

        # Push blob if present
        kind = snapshot["artifact"].get("kind")
        content_hash = snapshot["artifact"].get("content_hash")
        if kind in ("image", "pdf", "file") and content_hash:
            blob_path = config.BLOB_DIR / content_hash
            if blob_path.exists():
                blob_name = crypto.blob_name(content_hash, dek)
                blob_data = crypto.encrypt(blob_path.read_bytes(), dek)
                try:
                    with httpx.Client(timeout=60) as client:
                        bresp = client.put(
                            f"{_relay_url().rstrip('/')}/sync/object/blobs/{blob_name}",
                            content=blob_data, headers=headers
                        )
                except httpx.HTTPError:
                    pass  # blob push failure is non-fatal
                if bresp.status_code not in (201, 409):
                    pass  # blob push failure is non-fatal

    return pushed
