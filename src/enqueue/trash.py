"""Deleting, and the delay that makes it safe.

The product's promise is that nothing expires on its own. That still holds: nothing
here removes an artifact because it got old, or unread, or unloved. This is the one
case the collection previously could not express, which is *you deciding* something
does not belong in it.

Two steps and a window, never one keystroke:

  delete    the row is marked and leaves every surface. Its derived rows go with it,
            so it stops being retrievable, quotable, and curatable immediately.
  restore   within the window, it comes back and is re-ingested from the original.
  purge     after the window, the bytes go. This is the only destructive operation in
            the product and it is the only one that needs a real confirmation.

The blob is content-addressed and shared by every artifact with the same bytes, so it
is only unlinked when the last artifact referencing it is purged. Deleting one of two
identical uploads must not empty the other.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone

from . import config, db
from .sync.client import push_artifact


def _now() -> datetime:
    return datetime.now(timezone.utc)


def retention_days() -> int:
    from . import settings

    try:
        days = int(settings.get("trash_days"))
    except (TypeError, ValueError):
        days = 30
    # Zero would mean "purge on delete", which is the one-keystroke loss this exists
    # to prevent. A day is the floor.
    return max(1, days)


def delete(artifact_id: str) -> dict:
    """Mark an artifact deleted and take it out of retrieval immediately."""
    now = _now().isoformat()
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT deleted_at FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        if row["deleted_at"]:
            return {"id": artifact_id, "deleted_at": row["deleted_at"], "already": True}

        conn.execute("UPDATE artifacts SET deleted_at = ? WHERE id = ?", (now, artifact_id))
        # Derived rows are rebuildable, so they are dropped rather than filtered. A
        # deleted artifact must not be able to come back as a citation.
        conn.execute("DELETE FROM chunks WHERE artifact_id = ?", (artifact_id,))

    _drop_from_index(artifact_id)
    push_artifact(artifact_id)
    return {"id": artifact_id, "deleted_at": now, "already": False}


def restore(artifact_id: str) -> dict:
    """Put it back, and rebuild everything that was dropped."""
    from .ingest import queue as ingest_queue

    with db.transaction() as conn:
        row = conn.execute(
            "SELECT deleted_at FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        conn.execute("UPDATE artifacts SET deleted_at = NULL WHERE id = ?", (artifact_id,))

    ingest_queue.submit(artifact_id)
    push_artifact(artifact_id)
    return {"id": artifact_id, "restored": True}


def listing() -> dict:
    """What is in the trash, and how long each thing has left."""
    days = retention_days()
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, kind, title, source_url, filename, created_at, deleted_at"
            " FROM artifacts WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC"
        ).fetchall()
    finally:
        conn.close()

    out = []
    for row in rows:
        item = dict(row)
        try:
            gone = datetime.fromisoformat(row["deleted_at"]) + timedelta(days=days)
            item["purges_at"] = gone.isoformat()
            item["days_left"] = max(0, (gone - _now()).days)
        except ValueError:
            item["purges_at"] = None
            item["days_left"] = days
        out.append(item)
    return {"items": out, "retention_days": days}


def _drop_from_index(artifact_id: str) -> None:
    # The row is already gone from SQLite; a failure here changes nothing.
    with contextlib.suppress(Exception):  # noqa: BLE001 - derived data, safe to leave
        from .index.store import get_store

        store = get_store()
        store.drop_artifact(store.CHUNKS, artifact_id)
        store.drop_artifact(store.FACETS, artifact_id)
        store.drop_artifact(store.ENTITIES, artifact_id)


def purge(artifact_id: str) -> dict:
    """Destroy one artifact for good. The only irreversible operation here."""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT content_hash, deleted_at FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        if not row["deleted_at"]:
            raise ValueError("that artifact is not in the trash")

        for table in (
            "chat_citations",
            "chunks",
            "page_text",
            "facets",
            "entities",
            "facet_skips",
            "secret_hits",
            "link_previews",
            "annotations",
            "artifact_tags",
            "artifact_versions",
        ):
            column = "artifact_id"
            # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query,python.lang.security.audit.formatted-sql-query.formatted-sql-query
            conn.execute(f"DELETE FROM {table} WHERE {column} = ?", (artifact_id,))
        # A tag the purged artifact was the last user of has nothing left to
        # reference it; drop the orphan so the cloud never lists a dead tag.
        conn.execute(
            "DELETE FROM tags WHERE NOT EXISTS ("
            "  SELECT 1 FROM artifact_tags WHERE tag_id = tags.id"
            ")"
        )
        conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))

        # Content-addressed blobs are shared. Unlink only when nothing else points at
        # these bytes, or deleting one of two identical uploads empties the other.
        still_used = conn.execute(
            "SELECT 1 FROM artifacts WHERE content_hash = ? LIMIT 1", (row["content_hash"],)
        ).fetchone()

    if not still_used:
        blob = config.BLOB_DIR / row["content_hash"]
        with contextlib.suppress(OSError):
            blob.unlink(missing_ok=True)

    _drop_from_index(artifact_id)
    # Purge is local-only and final; no relay push.
    return {"id": artifact_id, "purged": True}


def empty() -> dict:
    """Purge everything in the trash regardless of how long it has left."""
    conn = db.get_conn()
    try:
        ids = [
            r["id"] for r in conn.execute("SELECT id FROM artifacts WHERE deleted_at IS NOT NULL")
        ]
    finally:
        conn.close()

    gone = 0
    for artifact_id in ids:
        try:
            purge(artifact_id)
            gone += 1
        except (KeyError, ValueError):
            continue
    return {"purged": gone}


def purge_expired() -> dict:
    """Purge everything past its window. Called at startup and on demand."""
    cutoff = (_now() - timedelta(days=retention_days())).isoformat()
    conn = db.get_conn()
    try:
        ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM artifacts WHERE deleted_at IS NOT NULL AND deleted_at < ?",
                (cutoff,),
            )
        ]
    finally:
        conn.close()

    for artifact_id in ids:
        try:
            purge(artifact_id)
        except (KeyError, ValueError):
            continue
    return {"purged": len(ids)}
