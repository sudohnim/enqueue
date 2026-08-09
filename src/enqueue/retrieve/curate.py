"""Curate: turn a lens into a room.

expand -> candidates -> rerank -> synthesise. The first three find the artifacts; the
last one is where a room stops being a filtered list and becomes a thinking surface.
The room is ephemeral: /curate returns it, and nothing is persisted here. Saved
groupings (saved_pivots) are the only persistent grouping concept.
"""

from __future__ import annotations

from ..prompts import SYNTHESIS
from ..providers.base import get_provider
from ..schemas import Room
from .candidates import candidates as get_candidates
from .expand import expand
from .rerank import rerank


def _synthesise(lens: str, kept: list[dict]) -> tuple[Room | None, str | None]:
    """Return the room and, if it could not be made, the reason.

    Swallowing the reason produced a room with a null name and no through line and
    nothing anywhere saying why. The synthesis failing is a fact about the model, and
    the person is the one who has to act on it.
    """
    if not kept:
        return (
            Room(
                suggested_name=lens,
                through_line="Nothing in the collection speaks to this yet.",
                thin=True,
                thin_reason="No artifact survived reranking.",
            ),
            None,
        )

    body = "\n\n".join(
        f"[{k['artifact_id']}] {k['title']}\n  placard: {k['placard']}\n  evidence: {k['evidence']}"
        for k in kept
    )
    try:
        return (
            get_provider().complete(
                system=SYNTHESIS,
                user=f"Theme: {lens}\n\nThe room:\n\n{body}",
                response_model=Room,
                context={"kept_artifact_ids": [k["artifact_id"] for k in kept], "lens": lens},
            ),
            None,
        )
    except Exception as exc:  # noqa: BLE001 - a room without synthesis still beats no room
        return None, f"{type(exc).__name__}: {exc}"[:300]


def curate(lens: str, keep: int = 15, pool: int = 150) -> dict:
    queries = expand(lens)
    pool_rows = get_candidates(queries, limit=pool)
    reranked = rerank(lens, pool_rows, keep=keep)
    room, synthesis_error = _synthesise(lens, reranked["kept"])

    return {
        "synthesis_error": synthesis_error,
        "lens": lens,
        "expansions": len(queries),
        "candidates": len(pool_rows),
        "considered": reranked["considered"],
        "rejected": reranked["rejected"],
        "rejected_count": reranked["rejected_count"],
        "relevant": reranked["relevant"],
        "failed": reranked["failed"],
        "failed_ids": reranked["failed_ids"],
        "kept": reranked["kept"],
        "room": room.model_dump() if room else None,
    }
