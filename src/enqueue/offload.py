"""Originals not opened for a while live on the relay only (track C, C4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import blobstore


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
