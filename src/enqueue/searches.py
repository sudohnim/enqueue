"""A local record of searches: what was asked and what came back. Never synced."""

from __future__ import annotations

import json
import logging

from . import db

log = logging.getLogger(__name__)
KEEP_DAYS = 180


def record(query: str, hits: list[dict], source: str) -> None:
    """Store one search. Never raises into the caller."""
    try:
        ids = [h.get("artifact_id") for h in hits if h.get("artifact_id")][:10]
        loose = sum(1 for h in hits if h.get("loose"))
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO searches (query, hits, loose, source, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (query.strip(), json.dumps(ids), loose, source, db.now()),
            )
    except Exception:  # noqa: BLE001
        log.exception("could not record a search")


def prune() -> None:
    with db.transaction() as conn:
        conn.execute(
            "DELETE FROM searches WHERE created_at < datetime('now', ?)",
            (f"-{KEEP_DAYS} days",),
        )
