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
    # What the search understood as filters ("PDFs · saved last month"), for the header.
    from .. import tags
    from ..retrieve import filters
    from ..retrieve.candidates import _quoted_phrase

    free, _ = tags.parse_tags(q)
    understood = filters.parse(free)[1].label if _quoted_phrase(free) is None else ""
    try:
        from .. import events

        events.emit("search", f'"{q}" -> {len(hits)} hits')
    except Exception:  # noqa: BLE001
        pass
    return {"query": q, "hits": hits, "filters": understood}


@router.get("/titles")
def titles() -> dict:
    """Every live artifact's id, title and kind, newest touch first: what the search
    bar matches typed names against in the page (static/js/suggest.js), so naming a
    thing costs no search. No index, no embedding, no model."""
    from .. import db

    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, title, kind FROM artifacts WHERE title IS NOT NULL AND title != ''"
            " AND deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL"
            " ORDER BY updated_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return {"titles": [dict(r) for r in rows]}
