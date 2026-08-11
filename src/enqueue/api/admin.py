"""Engine diagnostics and queue control: /doctor, /index/counts, /ingest/wait.

A separate surface from write.py because these answer questions about the
engine itself rather than changing the library.
"""

from __future__ import annotations

from fastapi import APIRouter

from .. import config, db
from ..index import bootstrap
from ..index.store import get_store

router = APIRouter()


@router.post("/ingest/wait")
def ingest_wait(timeout: float = 60.0) -> dict:
    """Block until the ingest queue is drained. For scripts and tests, not the UI."""
    return {"idle": ingest_queue.wait_idle(timeout)}


@router.get("/index/counts")
def index_counts() -> dict:
    return get_store().counts()


@router.get("/doctor")
def doctor() -> dict:
    """Index health: counts, embedding version, and chunks-table sync.

    A diagnostic for the cutover. `index_in_sync` is true when the search
    index holds exactly as many chunk rows as the chunks table (the trash
    path deletes a chunk row and drops its index point together, so a synced
    index stays synced across deletes). `embed_version_current` is true when
    the recorded version matches the running embedding model. `healthy` is
    both. The raw `index_counts` cover all six index tables, so an FTS,
    facets, or entities drift is visible even when the chunks count matches.
    """
    index_counts = get_store().counts()
    chunk_count = db.count("chunks")
    embed_version = bootstrap.read_embed_version()
    index_chunks = index_counts.get("chunks")
    in_sync = index_chunks is not None and index_chunks == chunk_count
    version_current = embed_version == config.EMBED_VERSION
    index_state = bootstrap.index_state()
    state_ready = index_state["state"] == "ready"
    conn = db.get_conn()
    try:
        images_without_body = conn.execute(
            "SELECT COUNT(*) AS n FROM artifacts"
            " WHERE kind = 'image' AND deleted_at IS NULL AND (body IS NULL OR body = '')"
        ).fetchone()["n"]
    finally:
        conn.close()
    return {
        "artifact_count": db.count("artifacts"),
        "chunk_count": chunk_count,
        "images_without_body": images_without_body,
        "facet_count": db.count("facets"),
        "index_counts": index_counts,
        "embed_version": embed_version,
        "embed_version_current": version_current,
        "index_state": index_state["state"],
        "index_progress": index_state["progress"],
        "index_in_sync": in_sync,
        "healthy": in_sync and version_current and state_ready,
    }
