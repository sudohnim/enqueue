"""Curate: turn a lens into a room.

expand -> candidates -> rerank -> synthesise. The first three find the artifacts; the
last one is where an exhibit stops being a filtered list and becomes a thinking surface.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .. import db
from ..prompts import SYNTHESIS
from ..providers.base import get_provider
from ..schemas import Exhibit
from .candidates import candidates as get_candidates
from .expand import expand
from .rerank import rerank


def _synthesise(lens: str, kept: list[dict]) -> Exhibit | None:
    if not kept:
        return Exhibit(
            suggested_name=lens,
            through_line="Nothing in the collection speaks to this yet.",
            thin=True,
            thin_reason="No artifact survived reranking.",
        )

    body = "\n\n".join(
        f"[{k['artifact_id']}] {k['title']}\n  placard: {k['placard']}\n  evidence: {k['evidence']}"
        for k in kept
    )
    try:
        return get_provider().complete(
            system=SYNTHESIS,
            user=f"Theme: {lens}\n\nThe room:\n\n{body}",
            response_model=Exhibit,
            context={"kept_artifact_ids": [k["artifact_id"] for k in kept], "lens": lens},
        )
    except Exception:  # noqa: BLE001 - a room without synthesis still beats no room
        return None


def curate(lens: str, keep: int = 15, pool: int = 150, save: bool = False) -> dict:
    queries = expand(lens)
    pool_rows = get_candidates(queries, limit=pool)
    reranked = rerank(lens, pool_rows, keep=keep)
    exhibit = _synthesise(lens, reranked["kept"])

    result = {
        "lens": lens,
        "expansions": len(queries),
        "candidates": len(pool_rows),
        "considered": reranked["considered"],
        "rejected": reranked["rejected"],
        "failed": reranked["failed"],
        "kept": reranked["kept"],
        "exhibit": exhibit.model_dump() if exhibit else None,
        "saved_id": None,
    }

    if save and exhibit:
        result["saved_id"] = _save(lens, exhibit, reranked["kept"])
    return result


def _save(lens: str, exhibit: Exhibit, kept: list[dict]) -> str:
    exhibit_id = str(uuid.uuid4())
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO exhibits (id, name, theme, through_line, thin, thin_reason, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                exhibit_id,
                exhibit.suggested_name,
                lens,  # immutable: reshaping means a new exhibit
                exhibit.through_line,
                int(exhibit.thin),
                exhibit.thin_reason,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        for rank, k in enumerate(kept):
            conn.execute(
                "INSERT INTO exhibit_members (exhibit_id, artifact_id, placard, evidence,"
                " strength, rank, origin) VALUES (?,?,?,?,?,?,'generated')",
                (
                    exhibit_id,
                    k["artifact_id"],
                    k["placard"],
                    k["evidence"],
                    k["strength"],
                    rank,
                ),
            )
    return exhibit_id
