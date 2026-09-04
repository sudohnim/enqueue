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

from . import config, db, vault, vaultops
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
            "SELECT deleted_at, vaulted_at FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        if row["deleted_at"]:
            return {"id": artifact_id, "deleted_at": row["deleted_at"], "already": True}

        # A vaulted item leaves the vault by being deleted: decrypt it out first so the
        # trash holds the readable original (and restore brings back a normal note),
        # never opaque ciphertext. It needs the vault unlocked - which it is, since the
        # delete is invoked from inside the open vault. When unlocked we also heal any
        # orphan (encrypted bytes whose flag was already cleared) in the same pass.
        if row["vaulted_at"] and not vault.is_unlocked():
            raise ValueError("Unlock the vault to delete a vaulted item.")
        if vault.is_unlocked():
            vaultops.decrypt_in_place(conn, artifact_id, vault.key())

        # Bump updated_at so the tombstone snapshot has a NEWER LWW key than the live
        # snapshot, ensuring the phone's apply_snapshot picks up the tombstone (MOBFIX.5).
        conn.execute(
            "UPDATE artifacts SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (now, now, artifact_id),
        )
        # Derived rows are rebuildable, so they are dropped rather than filtered. A
        # deleted artifact must not be able to come back as a citation.
        conn.execute("DELETE FROM chunks WHERE artifact_id = ?", (artifact_id,))

    _drop_from_index(artifact_id)
    push_artifact(artifact_id)
    return {"id": artifact_id, "deleted_at": now, "already": False}


def restore(artifact_id: str) -> dict:
    """Put it back, and rebuild everything that was dropped."""
    from .ingest import queue as ingest_queue

    now = _now().isoformat()
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT deleted_at, vaulted_at FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        # Restore returns the ORIGINAL. If the trashed content is still vault-ciphertext
        # (a vaulted item deleted before this decrypt-on-delete existed, or an orphan),
        # decrypt it back to a normal note - which needs the vault unlocked.
        if row["vaulted_at"] and not vault.is_unlocked():
            raise ValueError("Unlock the vault to restore this item.")
        if vault.is_unlocked():
            vaultops.decrypt_in_place(conn, artifact_id, vault.key())
        # Bump updated_at so the un-tombstone snapshot has a NEWER LWW key (MOBFIX.5).
        conn.execute(
            "UPDATE artifacts SET deleted_at = NULL, updated_at = ? WHERE id = ?",
            (now, artifact_id),
        )

    ingest_queue.submit(artifact_id)
    push_artifact(artifact_id)
    return {"id": artifact_id, "restored": True}


def listing() -> dict:
    """What is in the trash, and how long each thing has left."""
    days = retention_days()
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, kind, title, source_url, filename, created_at, deleted_at, vaulted_at"
            " FROM artifacts WHERE deleted_at IS NOT NULL AND purged_at IS NULL"
            " ORDER BY deleted_at DESC"
        ).fetchall()
    finally:
        conn.close()

    unlocked = vault.is_unlocked()
    key = vault.key() if unlocked else None
    out = []
    for row in rows:
        item = dict(row)
        # Never show raw vault-ciphertext. Decrypt to the real title when the vault is
        # open (also catches orphans via the auth tag); otherwise show a neutral label.
        if unlocked:
            opened = vaultops.try_open(key, row["title"])
            if opened is not None:
                item["title"] = opened
        elif row["vaulted_at"]:
            item["title"] = "Locked note"
        item.pop("vaulted_at", None)
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
    """Destroy one artifact for good, as a TOMBSTONE so the delete propagates.

    A hard-deleted row has no state to snapshot, so a peer could never learn the
    artifact is gone. Instead the row is KEPT with `purged_at` set and its content
    stripped, and pushed like any other change - other devices apply the tombstone
    and strip their own copy. The tombstone keeps `deleted_at` set, so every
    `deleted_at IS NULL` query already treats it as gone; only the trash views add
    `purged_at IS NULL` to hide the tombstone itself.
    """
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
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query
            conn.execute(
                f"DELETE FROM {table} WHERE {column} = ?", (artifact_id,)
            )  # table names are hardcoded tuple
        # A tag the purged artifact was the last user of has nothing left to
        # reference it; drop the orphan so the cloud never lists a dead tag.
        conn.execute(
            "DELETE FROM tags WHERE NOT EXISTS ("
            "  SELECT 1 FROM artifact_tags WHERE tag_id = tags.id"
            ")"
        )
        # Tombstone the artifact: keep the row (so the purge can sync) but strip its
        # body and stamp purged_at. updated_at is bumped so LWW carries it to peers.
        # content_hash is left as-is: it is NOT NULL on this schema, and a snapshot that
        # nulled it would crash the peer's apply on the same constraint. The row is
        # excluded from every view, so the dangling hash is harmless.
        now = db.now()
        conn.execute(
            "UPDATE artifacts SET purged_at = ?, updated_at = ?, body = NULL WHERE id = ?",
            (now, now, artifact_id),
        )

        # Content-addressed blobs are shared. Unlink only when NO OTHER artifact points
        # at these bytes (this tombstone still carries the hash, so exclude it by id).
        still_used = conn.execute(
            "SELECT 1 FROM artifacts WHERE content_hash = ? AND id != ? LIMIT 1",
            (row["content_hash"], artifact_id),
        ).fetchone()

    if row["content_hash"] and not still_used:
        blob = config.BLOB_DIR / row["content_hash"]
        with contextlib.suppress(OSError):
            blob.unlink(missing_ok=True)

    _drop_from_index(artifact_id)
    # Propagate the tombstone so other devices drop their copy too.
    try:
        from .sync.client import push_artifact

        push_artifact(artifact_id)
    except Exception:  # noqa: BLE001 - a sync hiccup must not fail the local purge
        pass
    return {"id": artifact_id, "purged": True}


def empty() -> dict:
    """Purge everything in the trash regardless of how long it has left."""
    conn = db.get_conn()
    try:
        ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM artifacts WHERE deleted_at IS NOT NULL AND purged_at IS NULL"
            )
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
                "SELECT id FROM artifacts WHERE deleted_at IS NOT NULL AND purged_at IS NULL"
                " AND deleted_at < ?",
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
