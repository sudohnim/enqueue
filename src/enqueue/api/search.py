"""Search: the dense+FTS5 rollup over the whole library, one route."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..index import bootstrap
from ..retrieve.candidates import search_results

router = APIRouter()


# ------------------------------------------------------------------------- search


@router.get("/search")
def search(q: str, limit: int = 20) -> dict:
    if not bootstrap.search_allowed():
        # The index is missing, rebuilding, or built with a different embedding
        # version. Serving results now would silently differ from another
        # device's results (Phase 21): block instead, and never fall back.
        raise HTTPException(
            status_code=503,
            detail="Updating your search index. This will take a moment.",
        )
    # Chunk and facet hits rolled up to one row per artifact (deduplicated),
    # so an artifact whose six chunks match does not occupy every slot.
    hits = search_results(q, limit=limit)
    try:
        from .. import events

        events.emit("search", f'"{q}" -> {len(hits)} hits')
    except Exception:  # noqa: BLE001
        pass
    return {"query": q, "hits": hits}
