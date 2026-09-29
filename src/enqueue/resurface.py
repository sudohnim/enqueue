"""Resurfacing: one older note brought back to the wall each day.

Search only finds what a person remembers to look for; this brings back what they
forgot. The pick is an artifact saved at least MIN_AGE_DAYS ago and not opened in
the last QUIET_DAYS. It prefers one linked (the `related` table) to something saved
in the last RECENT_DAYS, so the note comes back when it bears on current work;
otherwise it is a stable pick for the day. The same day always returns the same
note, so the wall does not reshuffle on every visit. No model call.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone

from . import db

MIN_AGE_DAYS = 14
QUIET_DAYS = 14
RECENT_DAYS = 7
# The strongest links are rotated through, one per day, so a single strong pair does
# not hold the slot for a week.
ROTATE = 3


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def pick(today: date | None = None) -> dict | None:
    """{"id", "reason"} for today's note, or None when nothing qualifies.

    `reason` is {"kind": "related", "via_id", "via_title"} or {"kind": "saved",
    "created_at"}.
    """
    today = today or datetime.now(timezone.utc).date()
    conn = db.get_conn()
    try:
        live = "deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL"
        candidates = [
            r["id"]
            for r in conn.execute(
                f"SELECT id FROM artifacts WHERE {live} AND created_at <= ?"
                " AND id NOT IN (SELECT artifact_id FROM opens WHERE opened_at >= ?)",
                (_cutoff(MIN_AGE_DAYS), _cutoff(QUIET_DAYS)),
            )
        ]
        if not candidates:
            return None
        linked = conn.execute(
            "SELECT r.related_id AS id, a.id AS via_id, a.title AS via_title, r.score"
            " FROM related r JOIN artifacts a ON a.id = r.artifact_id"
            " WHERE a.deleted_at IS NULL AND a.vaulted_at IS NULL AND a.embedded_at IS NULL"
            " AND a.created_at >= ?"
            " AND r.related_id IN (SELECT value FROM json_each(?))"
            " ORDER BY r.score DESC, r.related_id",
            (_cutoff(RECENT_DAYS), json.dumps(candidates)),
        ).fetchall()
        created = {
            r["id"]: r["created_at"]
            for r in conn.execute(
                "SELECT id, created_at FROM artifacts WHERE id IN (SELECT value FROM json_each(?))",
                (json.dumps(candidates),),
            )
        }
    finally:
        conn.close()

    seen: dict[str, dict] = {}
    for r in linked:
        seen.setdefault(r["id"], dict(r))
    top = list(seen.values())[:ROTATE]
    if top:
        chosen = top[today.toordinal() % len(top)]
        return {
            "id": chosen["id"],
            "reason": {
                "kind": "related",
                "via_id": chosen["via_id"],
                "via_title": chosen["via_title"],
            },
        }
    day = today.isoformat()
    chosen_id = min(candidates, key=lambda aid: hashlib.sha1(f"{day}:{aid}".encode()).digest())
    return {"id": chosen_id, "reason": {"kind": "saved", "created_at": created[chosen_id]}}
