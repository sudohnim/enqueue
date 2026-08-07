"""Saved groupings: a named pivot spec you can re-open and re-run.

A saved grouping stores the *spec* (the arrangement's recipe: subset, steps,
group_by), not a frozen snapshot of the result. Re-running is live - a note
captured after the grouping was saved lands in its group the next time the
grouping is opened. That is the right shape for a growing library: the
arrangement stays true as the collection changes, rather than aging into a
screenshot of what it used to hold.

The spec is stored as JSON exactly as `pivot.run` eats it, so opening a saved
grouping is a plain `pivot.run(spec)` with no re-planning. No model call
happens in this module; it is storage over the `saved_pivots` table (0013).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from . import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save(name: str, spec: dict) -> str:
    """Store a spec under a name, returning the new id.

    The name is what the person will scan a list by, so it must be present; the
    spec is trusted to be a runnable pivot spec (the caller took it from a turn
    that already ran).
    """
    name = name.strip()
    if not name:
        raise ValueError("a saved grouping needs a name")
    pivot_id = str(uuid.uuid4())
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO saved_pivots (id, name, spec_json, created_at) VALUES (?,?,?,?)",
            (pivot_id, name[:120], json.dumps(spec), _now()),
        )
    return pivot_id


def listing() -> list[dict]:
    """Every saved grouping, newest first, without the spec.

    The list is for choosing, so it carries only what a row shows - name and
    when it was saved. The spec is fetched by `get` when a grouping is opened.
    """
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, name, created_at FROM saved_pivots ORDER BY created_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get(pivot_id: str) -> dict:
    """One saved grouping with its spec parsed back to a dict, ready for pivot.run."""
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT id, name, spec_json, created_at FROM saved_pivots WHERE id = ?",
            (pivot_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise KeyError(pivot_id)
    out = dict(row)
    out["spec"] = json.loads(out.pop("spec_json"))
    return out


def delete(pivot_id: str) -> None:
    """Forget a saved grouping. Idempotent: deleting one already gone is not an error."""
    with db.transaction() as conn:
        conn.execute("DELETE FROM saved_pivots WHERE id = ?", (pivot_id,))
