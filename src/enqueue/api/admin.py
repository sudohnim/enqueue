"""Engine diagnostics and queue control: /doctor, /index/counts, /ingest/wait.

A separate surface from write.py because these answer questions about the
engine itself rather than changing the library.
"""

from __future__ import annotations

from fastapi import APIRouter

from .. import config, db
from ..index import bootstrap
from ..index.store import get_store
from ..ingest import queue as ingest_queue

router = APIRouter()


@router.post("/eval/real")
def eval_real(update_baseline: bool = False) -> dict:
    """Score the searches this person ran against the live library (eval_real.py)."""
    from .. import eval_real as real

    return real.check(update_baseline=update_baseline)


@router.post("/ingest/wait")
def ingest_wait(timeout: float = 60.0) -> dict:
    """Block until the ingest queue is drained. For scripts and tests, not the UI."""
    return {"idle": ingest_queue.wait_idle(timeout)}


@router.post("/summaries/backfill")
def summaries_backfill() -> dict:
    """Queue a summary for every artifact that still lacks one. Manual kick.

    Same DB-derived, backoff-respecting backfill the engine runs at startup - exposed so
    it can be re-run after the model comes back from an outage/quota without waiting for a
    restart. Returns how many artifacts were queued (0 when everything is summarized or
    already owed a retry).
    """
    return {"queued": ingest_queue.backfill_summaries()}


@router.get("/index/counts")
def index_counts() -> dict:
    return get_store().counts()


@router.get("/doctor")
def doctor() -> dict:
    """Index health: counts, embedding version, and chunks-table sync.

    A diagnostic for the cutover. `index_in_sync` is true when the search
    index holds exactly one row per chunk of a live, searchable artifact
    (`indexable_chunk_count`): vaulted and embedded artifacts keep their chunks
    but are never indexed, so `chunk_count` alone would read as drift. `embed_version_current` is true when
    the recorded version matches the running embedding model. `healthy` is
    both. The raw `index_counts` cover all six index tables, so an FTS,
    facets, or entities drift is visible even when the chunks count matches.
    """
    store = get_store()
    index_counts = store.counts()
    chunk_count = db.count("chunks")
    indexable = store.expected_chunks()
    embed_version = bootstrap.read_embed_version()
    index_chunks = index_counts.get("chunks")
    in_sync = index_chunks is not None and index_chunks == indexable
    version_current = embed_version == config.EMBED_VERSION
    index_state = bootstrap.index_state()
    state_ready = index_state["state"] == "ready"
    conn = db.get_conn()
    try:
        images_without_body = conn.execute(
            "SELECT COUNT(*) AS n FROM artifacts"
            " WHERE kind = 'image' AND deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL AND (body IS NULL OR body = '')"
        ).fetchone()["n"]
    finally:
        conn.close()
    return {
        "artifact_count": db.count("artifacts"),
        "chunk_count": chunk_count,
        "indexable_chunk_count": indexable,
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
