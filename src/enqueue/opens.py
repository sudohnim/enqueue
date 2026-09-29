"""Opens: a record of which artifact was opened, from where, and for which search.

Local only, never synced. The real-search eval (eval_real.py) reads the search
opens as labelled examples; nothing here ever raises into the caller.
"""

from __future__ import annotations

import logging

from . import db

log = logging.getLogger(__name__)

SOURCES = ("search", "wall", "related", "chat", "other")


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
