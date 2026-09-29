"""Maintenance writes: re-chunk, regenerate facets, rebuild the search index.

The "look at everything again" endpoints - invoked from the admin surface and
by tests. Nothing here edits authored content.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..index import bootstrap
from ..ingest import chunk as chunk_mod
from ..ingest import facets as facets_mod
from ..ingest import queue as ingest_queue

router = APIRouter()


# ------------------------------------------------------------------------ derived


@router.post("/chunk")
def rebuild_chunks() -> dict:
    return chunk_mod.chunk_all()


@router.post("/facet-gate")
def facet_gate() -> dict:
    return facets_mod.apply_eligibility_gate()


class FacetRequest(BaseModel):
    limit: int | None = None
    redo: bool = False
    stale_only: bool = False


@router.post("/facets")
def generate_facets(req: FacetRequest) -> dict:
    """Queue the summary refresh on the ingest worker and return at once.

    It used to run the whole library inside this request: hours of model calls that a
    restart killed (and `redo` then started over), off the worker, unindexed and unsynced.
    Queued, each artifact is regenerated only if stale (or forced with `redo`), indexed,
    synced, retried on a transient failure, and resumed at the next startup.
    `limit` and `stale_only` are accepted for older callers; stale is now the default.
    """
    return {"queued": ingest_queue.queue_summary_refresh(redo=req.redo)}


@router.post("/index")
def build_index() -> dict:
    # Rebuild synchronously through the lifecycle: search is blocked for the
    # duration and re-enabled only after the version is written.
    # On the ingest worker's thread, between two artifacts: a rebuild racing ingest
    # for the database failed with "database is locked" and left search blocked.
    return ingest_queue.run_exclusive(bootstrap.rebuild_now)


@router.post("/reprocess")
def reprocess() -> dict:
    """Re-read, re-chunk, and re-index everything. Nothing authored is touched."""
    return {"queued": ingest_queue.submit_all()}


@router.post("/reprocess-images")
def reprocess_images() -> dict:
    """Re-queue every image for the vision describe step (K.11).

    The catch-up for images captured before the vision step existed: each one
    without a description gets one, then flows through chunk, facet, and index
    like any other artifact.
    """
    return {"queued": ingest_queue.submit_images()}
