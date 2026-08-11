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
    return facets_mod.generate_all(limit=req.limit, redo=req.redo, stale_only=req.stale_only)


@router.post("/index")
def build_index() -> dict:
    # Rebuild synchronously through the lifecycle: search is blocked for the
    # duration and re-enabled only after the version is written.
    return bootstrap.rebuild_now()


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
