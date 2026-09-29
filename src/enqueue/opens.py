"""Opens: a record of which artifact was opened, from where, and for which search.

Local only, never synced. The real-search eval (eval_real.py) reads the search
opens as labelled examples, and search ranking reads them as a usage signal
(`usage_boost`); nothing here ever raises into the caller.
"""

from __future__ import annotations

import json
import logging
import math

from . import db

log = logging.getLogger(__name__)

SOURCES = ("search", "wall", "related", "resurface", "chat", "other")


def record(artifact_id: str, source: str, query: str | None = None, rank: int | None = None):
    """Store one open. A search open carries its query and the result's 1-based rank."""
    if source not in SOURCES:
        source = "other"
    query = (query or "").strip() or None
    if source != "search":
        query, rank = None, None
    try:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO opens (artifact_id, source, query, rank, opened_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (artifact_id, source, query, rank, db.now()),
            )
    except Exception:  # noqa: BLE001 - a lost open must never break opening
        log.exception("could not record an open")


# Usage boost: score * (1 + USAGE_WEIGHT * use / (use + USAGE_HALF)), where `use` is
# the decayed count of opens and chat citations plus PIN_USE for a pinned artifact.
# It saturates (at most 1 + USAGE_WEIGHT, half of it at USAGE_HALF uses) and fades
# with USAGE_TAU_DAYS, so a note used a lot once does not stay on top for good, and
# it stays below the recency boost (1.5x) so relevance still decides.
USAGE_WEIGHT = 0.2
USAGE_HALF = 3.0
USAGE_TAU_DAYS = 90.0
PIN_USE = 3.0


def usage_boost(conn, artifact_ids: list[str]) -> dict[str, float]:
    """Multiplier per artifact from how it has been used. Unused artifacts are absent."""
    from .retrieve.candidates import _age_days

    if not artifact_ids:
        return {}
    ids = json.dumps(sorted(set(artifact_ids)))
    rows = conn.execute(
        "SELECT artifact_id, opened_at AS at FROM opens"
        " WHERE artifact_id IN (SELECT value FROM json_each(?))"
        " UNION ALL"
        " SELECT c.artifact_id, m.created_at FROM chat_citations c"
        " JOIN chat_messages m ON m.id = c.message_id"
        " WHERE c.artifact_id IN (SELECT value FROM json_each(?))",
        (ids, ids),
    ).fetchall()
    pinned = conn.execute(
        "SELECT id FROM artifacts WHERE pinned = 1 AND id IN (SELECT value FROM json_each(?))",
        (ids,),
    ).fetchall()
    use: dict[str, float] = {r["id"]: PIN_USE for r in pinned}
    for r in rows:
        weight = math.exp(-_age_days(r["at"]) / USAGE_TAU_DAYS)
        use[r["artifact_id"]] = use.get(r["artifact_id"], 0.0) + weight
    return {aid: 1.0 + USAGE_WEIGHT * u / (u + USAGE_HALF) for aid, u in use.items()}
