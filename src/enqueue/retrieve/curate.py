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


def _synthesise(lens: str, kept: list[dict]) -> tuple[Exhibit | None, str | None]:
    """Return the exhibit and, if it could not be made, the reason.

    Swallowing the reason produced a room with a null name and no through line and
    nothing anywhere saying why. The synthesis failing is a fact about the model, and
    the person is the one who has to act on it.
    """
    if not kept:
        return (
            Exhibit(
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
                response_model=Exhibit,
                context={"kept_artifact_ids": [k["artifact_id"] for k in kept], "lens": lens},
            ),
            None,
        )
    except Exception as exc:  # noqa: BLE001 - a room without synthesis still beats no room
        return None, f"{type(exc).__name__}: {exc}"[:300]


def curate(lens: str, keep: int = 15, pool: int = 150, save: bool = False) -> dict:
    queries = expand(lens)
    pool_rows = get_candidates(queries, limit=pool)
    reranked = rerank(lens, pool_rows, keep=keep)
    exhibit, synthesis_error = _synthesise(lens, reranked["kept"])

    result = {
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
        "exhibit": exhibit.model_dump() if exhibit else None,
        "saved_id": None,
    }

    if save and exhibit:
        result["saved_id"] = _save(lens, exhibit, reranked["kept"])
    return result


def save(lens: str, exhibit: dict, kept: list[dict]) -> str:
    """Keep a room that has already been built.

    Revalidated with the same context the generating call used, because the payload
    made the round trip through a client and is no longer trusted to be what the
    model returned.
    """
    checked = Exhibit.model_validate(
        exhibit,
        context={"kept_artifact_ids": [k["artifact_id"] for k in kept], "lens": lens},
    )
    return _save(lens, checked, kept)


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
                1 if exhibit.thin else 0,
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


def add_member(exhibit_id: str, artifact_id: str) -> bool:
    """Add one artifact to an exhibit by hand (the drawer's "Add to grouping").

    Idempotent: an artifact that is already a member (and not ejected) is a no-op
    that returns False. An ejected member is re-admitted with a fresh rank and the
    current title as its placard. Raises KeyError for an unknown exhibit and
    ValueError for an unknown artifact.
    """
    with db.transaction() as conn:
        exhibit = conn.execute("SELECT id FROM exhibits WHERE id = ?", (exhibit_id,)).fetchone()
        if exhibit is None:
            raise KeyError(exhibit_id)
        artifact = conn.execute(
            "SELECT title FROM artifacts WHERE id = ? AND deleted_at IS NULL",
            (artifact_id,),
        ).fetchone()
        if artifact is None:
            raise ValueError(artifact_id)
        existing = conn.execute(
            "SELECT ejected_at FROM exhibit_members" " WHERE exhibit_id = ? AND artifact_id = ?",
            (exhibit_id, artifact_id),
        ).fetchone()
        if existing is not None and existing["ejected_at"] is None:
            return False  # already a member; nothing to do
        next_rank = conn.execute(
            "SELECT COALESCE(MAX(rank), -1) + 1 FROM exhibit_members WHERE exhibit_id = ?",
            (exhibit_id,),
        ).fetchone()[0]
        if existing is not None:
            conn.execute(
                "UPDATE exhibit_members SET ejected_at = NULL, origin = 'added',"
                " rank = ?, placard = ? WHERE exhibit_id = ? AND artifact_id = ?",
                (next_rank, artifact["title"], exhibit_id, artifact_id),
            )
        else:
            conn.execute(
                "INSERT INTO exhibit_members (exhibit_id, artifact_id, placard, evidence,"
                " strength, rank, origin) VALUES (?,?,?, '', 0, ?, 'added')",
                (exhibit_id, artifact_id, artifact["title"], next_rank),
            )
    return True


def rename_exhibit(
    exhibit_id: str, name: str | None = None, through_line: str | None = None
) -> dict:
    """Rename an exhibit (and optionally rewrite its through line), returning the row.

    The name is trimmed; an empty or whitespace-only name is a ValueError and an
    unknown exhibit is a KeyError, mirroring add_member. The theme is immutable
    and is never touched here - only the display name and the through line move.
    """
    if name is not None:
        name = name.strip()
        if not name:
            raise ValueError("name cannot be empty")
    with db.transaction() as conn:
        row = conn.execute("SELECT id FROM exhibits WHERE id = ?", (exhibit_id,)).fetchone()
        if row is None:
            raise KeyError(exhibit_id)
        if name is not None:
            conn.execute("UPDATE exhibits SET name = ? WHERE id = ?", (name, exhibit_id))
        if through_line is not None:
            conn.execute(
                "UPDATE exhibits SET through_line = ? WHERE id = ?",
                (through_line or None, exhibit_id),
            )
        updated = conn.execute("SELECT * FROM exhibits WHERE id = ?", (exhibit_id,)).fetchone()
        return dict(updated)


def eject_member(exhibit_id: str, artifact_id: str) -> None:
    """Soft-delete one member of an exhibit (the chip X in the drawer).

    The row stays (the PK is (exhibit_id, artifact_id)) but carries ejected_at,
    which every read filters on; a later add_member re-admits it under a fresh rank.
    """
    with db.transaction() as conn:
        exhibit = conn.execute("SELECT id FROM exhibits WHERE id = ?", (exhibit_id,)).fetchone()
        if exhibit is None:
            raise KeyError(exhibit_id)
        conn.execute(
            "UPDATE exhibit_members SET ejected_at = ?"
            " WHERE exhibit_id = ? AND artifact_id = ? AND ejected_at IS NULL",
            (datetime.now(timezone.utc).isoformat(), exhibit_id, artifact_id),
        )


def quick_create(name: str, artifact_id: str | None = None) -> str:
    """A hand-made exhibit: a name, optionally seeded with one artifact.

    The theme is immutable and is the lens that produced the room; a hand-made
    grouping has no lens, so the theme is the name itself. Raises ValueError for
    an empty name or an unknown artifact.
    """
    name = name.strip()
    if not name:
        raise ValueError("name is required")
    exhibit_id = str(uuid.uuid4())
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO exhibits (id, name, theme, through_line, thin, thin_reason,"
            " created_at) VALUES (?,?,?,NULL,0,NULL,?)",
            (exhibit_id, name, name, datetime.now(timezone.utc).isoformat()),
        )
        if artifact_id is not None:
            artifact = conn.execute(
                "SELECT title FROM artifacts WHERE id = ? AND deleted_at IS NULL",
                (artifact_id,),
            ).fetchone()
            if artifact is None:
                raise ValueError(artifact_id)
            conn.execute(
                "INSERT INTO exhibit_members (exhibit_id, artifact_id, placard, evidence,"
                " strength, rank, origin) VALUES (?,?,?, '', 0, 0, 'added')",
                (exhibit_id, artifact_id, artifact["title"]),
            )
    return exhibit_id
