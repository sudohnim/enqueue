"""Originals not opened for a while live on the relay only (track C, C4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from . import blobstore, crypto, db, events, keyring_file, settings
from .sync import client as sync_client


def candidates(conn, days: int, relay: str) -> list[dict]:
    """Live pdf, image and file artifacts whose original may leave this Mac."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT a.id, a.kind, a.content_hash FROM artifacts a"
        " JOIN blob_relay r ON r.content_hash = a.content_hash AND r.relay = ?"
        " WHERE a.deleted_at IS NULL AND a.vaulted_at IS NULL AND a.embedded_at IS NULL"
        " AND a.local_only = 0 AND a.pinned = 0 AND a.kind IN ('pdf', 'image', 'file')"
        " AND a.updated_at < ?"
        " AND NOT EXISTS (SELECT 1 FROM opens o WHERE o.artifact_id = a.id"
        "                 AND o.opened_at >= ?)"
        " AND (a.kind != 'image' OR EXISTS (SELECT 1 FROM thumbs t"
        "                                   WHERE t.artifact_id = a.id))",
        (relay.rstrip("/"), since, since),
    ).fetchall()
    return [dict(r) for r in rows if blobstore.exists(r["content_hash"])]


def on_relay(content_hash: str) -> bool:
    """True only when the relay holds these exact sealed bytes for this blob."""
    url = sync_client._relay_url()
    if not url:
        return False
    dek = keyring_file.dek() or keyring_file.load_dek_from_keychain()
    if dek is None:
        return False
    name = crypto.blob_name(content_hash, dek)
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.head(
                f"{url.rstrip('/')}/sync/object/blobs/{name}",
                headers={"Authorization": f"Bearer {sync_client._secret()}"},
            )
    except Exception:  # noqa: BLE001 - an unreachable relay is "not here", never fatal
        return False
    if resp.status_code != 200:
        return False
    try:
        size = int(resp.headers["X-Object-Size"])
    except (KeyError, ValueError):
        return False
    return size == len(crypto.seal_payload(blobstore.read(content_hash), dek))


def run(limit: int = 200) -> dict:
    """Let go of originals the relay holds byte for byte. Off by default."""
    if settings.get("offload_originals") != "on":
        return {"freed": 0, "bytes": 0}
    url = sync_client._relay_url()
    if not url:
        return {"freed": 0, "bytes": 0}
    if keyring_file.dek() is None and keyring_file.load_dek_from_keychain() is None:
        return {"freed": 0, "bytes": 0}
    conn = db.get_conn()
    try:
        rows = candidates(conn, int(settings.get("offload_after_days")), url)[:limit]
    finally:
        conn.close()
    total = 0
    count = 0
    for row in rows:
        content_hash = row["content_hash"]
        if on_relay(content_hash):
            total += blobstore.size(content_hash)
            blobstore.remove(content_hash)
            count += 1
    if count:
        mb = total / (1024 * 1024)
        events.emit(
            "storage.offloaded",
            f"{count} files, {mb:.1f} MB",
            data={"count": count, "bytes": total},
        )
    return {"freed": count, "bytes": total}


def report() -> dict:
    """Space originals use on this Mac, and how much the relay could take."""
    url = sync_client._relay_url()
    ready = bool(url and sync_client._secret())
    conn = db.get_conn()
    try:
        local_rows = conn.execute(
            "SELECT content_hash FROM artifacts"
            " WHERE deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL"
            "   AND content_hash IS NOT NULL"
        ).fetchall()
        candidate_rows = candidates(conn, int(settings.get("offload_after_days")), url)
    finally:
        conn.close()
    local_bytes = 0
    local_count = 0
    for row in local_rows:
        digest = row["content_hash"]
        if blobstore.exists(digest):
            local_bytes += blobstore.size(digest)
            local_count += 1
    could_free_bytes = sum(blobstore.size(row["content_hash"]) for row in candidate_rows)
    return {
        "local_bytes": local_bytes,
        "local_count": local_count,
        "could_free_bytes": could_free_bytes,
        "could_free_count": len(candidate_rows),
        "ready": ready,
    }
