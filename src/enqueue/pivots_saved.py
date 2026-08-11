"""Saved views: a named pivot spec you can re-open and re-run.

A saved view stores the *spec* (the arrangement's recipe: subset, steps,
group_by), not a frozen snapshot of the result. Re-running is live - a note
captured after the view was saved lands in its group the next time the
view is opened. That is the right shape for a growing library: the
arrangement stays true as the collection changes, rather than aging into a
screenshot of what it used to hold.

The spec is stored as JSON exactly as `pivot.run` eats it, so opening a saved
view is a plain `pivot.run(spec)` with no re-planning. No model call
happens in this module; it is storage over the `saved_pivots` table (0013).
"""

from __future__ import annotations

import json
import uuid

from . import db


def save(name: str, spec: dict) -> str:
    """Store a spec under a name, returning the new id.

    The name is what the person will scan a list by, so it must be present; the
    spec is trusted to be a runnable pivot spec (the caller took it from a turn
    that already ran).
    """
    name = name.strip()
    if not name:
        raise ValueError("a saved view needs a name")
    pivot_id = str(uuid.uuid4())
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO saved_pivots (id, name, spec_json, created_at) VALUES (?,?,?,?)",
            (pivot_id, name[:120], json.dumps(spec), db.now()),
        )
    return pivot_id


def listing() -> list[dict]:
    """Every saved view, newest first, without the spec.

    The list is for choosing, so it carries only what a row shows - name and
    when it was saved. The spec is fetched by `get` when a view is opened.
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
    """One saved view with its spec parsed back to a dict, ready for pivot.run."""
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
    raw = out.pop("spec_json")
    try:
        out["spec"] = json.loads(raw)
    except (TypeError, ValueError) as exc:
        # The spec is written by save()/json.dumps, so a row that does not parse
        # is corruption, not a format we do not know. Fail loudly and readably
        # rather than 500ing on a JSONDecodeError the client cannot place.
        raise ValueError(f"saved view {pivot_id} has a corrupt spec") from exc
    return out


def update_spec(pivot_id: str, spec: dict) -> dict:
    """Replace the stored spec of a saved view, returning the updated row.

    This is how the exclude/include actions (L.6b/L.6c) persist: they read the
    stored spec, adjust `excluded_ids` / `included_ids`, and write it back so
    the next re-run sees the new membership. An unknown view is a KeyError;
    the spec is trusted to be runnable (the caller read it from storage).
    """
    with db.transaction() as conn:
        row = conn.execute("SELECT id FROM saved_pivots WHERE id = ?", (pivot_id,)).fetchone()
        if row is None:
            raise KeyError(pivot_id)
        conn.execute(
            "UPDATE saved_pivots SET spec_json = ? WHERE id = ?",
            (json.dumps(spec), pivot_id),
        )
        updated = conn.execute(
            "SELECT id, name, created_at FROM saved_pivots WHERE id = ?", (pivot_id,)
        ).fetchone()
        return dict(updated)


def rename(pivot_id: str, name: str) -> dict:
    """Rename a saved view, returning the updated row.

    The name is trimmed; an empty or whitespace-only name is a ValueError and an
    unknown view is a KeyError, mirroring `save`. Only the display name
    moves - the spec is the arrangement and is never touched here.
    """
    name = name.strip()
    if not name:
        raise ValueError("a saved view needs a name")
    with db.transaction() as conn:
        row = conn.execute("SELECT id FROM saved_pivots WHERE id = ?", (pivot_id,)).fetchone()
        if row is None:
            raise KeyError(pivot_id)
        conn.execute("UPDATE saved_pivots SET name = ? WHERE id = ?", (name[:120], pivot_id))
        updated = conn.execute(
            "SELECT id, name, created_at FROM saved_pivots WHERE id = ?", (pivot_id,)
        ).fetchone()
        return dict(updated)


def delete(pivot_id: str) -> None:
    """Forget a saved view. Idempotent: deleting one already gone is not an error."""
    with db.transaction() as conn:
        conn.execute("DELETE FROM saved_pivots WHERE id = ?", (pivot_id,))
