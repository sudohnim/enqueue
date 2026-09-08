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
import threading
import uuid

from . import db


def _resync_pivots() -> None:
    """Best-effort push of the saved views to the relay so the mobile client's
    Custom mode reflects a create/edit/rename/delete without a full backfill.

    Runs on a daemon thread (resolve_subset can be slow for a search subset) and
    swallows everything: a sync hiccup must never break saving a view locally.
    """

    def _run() -> None:
        try:
            from .sync.client import push_pivots

            push_pivots()
        except Exception:  # noqa: BLE001 - never surface a sync error to the caller
            pass

    threading.Thread(target=_run, daemon=True).start()


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
    _resync_pivots()
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
    """One saved view with its spec parsed back to a dict, ready for pivot.run.

    Also carries the cached group structure (`result`, `result_at`) when the view
    has been run before - the caller serves that instantly and refreshes in the
    background. `result` is None when the cache is empty (never run, or invalidated
    by a spec edit); a corrupt cache is treated as empty rather than fatal.
    """
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT id, name, spec_json, created_at, result_json, result_at"
            " FROM saved_pivots WHERE id = ?",
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
    result_raw = out.pop("result_json", None)
    out["result"] = None
    if result_raw:
        try:
            out["result"] = json.loads(result_raw)
        except (TypeError, ValueError):
            out["result"] = None  # a corrupt cache just means "recompute"
    return out


def set_result(pivot_id: str, result: dict) -> None:
    """Cache a view's computed group structure (from pivot.run, `items` stripped).

    Idempotent overwrite. A missing view is a no-op: the view may have been deleted
    between a run and this write, and a lost cache is never worth an error.
    """
    with db.transaction() as conn:
        conn.execute(
            "UPDATE saved_pivots SET result_json = ?, result_at = ? WHERE id = ?",
            (json.dumps(result), db.now(), pivot_id),
        )


def clear_result(conn, pivot_id: str) -> None:
    """Invalidate a view's cached result (on a spec edit) within the caller's txn."""
    conn.execute(
        "UPDATE saved_pivots SET result_json = NULL, result_at = NULL WHERE id = ?",
        (pivot_id,),
    )


def remove_from_result(pivot_id: str, artifact_ids: list[str]) -> dict | None:
    """Drop artifacts from a locked view's materialized result, in place.

    A saved view is locked: its groups are the frozen `result_json`, not a live re-run,
    so removing a card edits that stored structure directly (no recompute, no model
    call) instead of adding to `excluded_ids` and re-running the spec. Empty groups are
    pruned. Returns the updated structure, or None when the view has no cache yet (it
    must be opened once to materialize before it can be edited). `result_at` is left as
    it was - an edit is not a recompute.
    """
    drop = set(artifact_ids)
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT result_json FROM saved_pivots WHERE id = ?", (pivot_id,)
        ).fetchone()
        if row is None:
            raise KeyError(pivot_id)
        if not row["result_json"]:
            return None
        try:
            result = json.loads(row["result_json"])
        except (TypeError, ValueError):
            return None
        groups = []
        for group in result.get("groups", []):
            kept = [aid for aid in group.get("artifact_ids", []) if aid not in drop]
            if kept:
                group["artifact_ids"] = kept
                groups.append(group)
        result["groups"] = groups
        conn.execute(
            "UPDATE saved_pivots SET result_json = ? WHERE id = ?",
            (json.dumps(result), pivot_id),
        )
    _resync_pivots()
    return result


def add_to_result(pivot_id: str, artifact_id: str, group_key: str) -> dict | None:
    """Add an artifact to a locked view's materialized result, under `group_key`.

    Edits the frozen structure in place (no recompute): the artifact joins the group
    with that key, a new group is created if none has it, and adding one already present
    anywhere is a no-op. Returns the updated structure, or None when the view has no
    cache yet. The caller computes `group_key` (a free field read, or "" when the
    grouping is model-based and cannot be placed without a Rebuild).
    """
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT result_json FROM saved_pivots WHERE id = ?", (pivot_id,)
        ).fetchone()
        if row is None:
            raise KeyError(pivot_id)
        if not row["result_json"]:
            return None
        try:
            result = json.loads(row["result_json"])
        except (TypeError, ValueError):
            return None
        groups = result.get("groups", [])
        if any(artifact_id in (g.get("artifact_ids") or []) for g in groups):
            return result  # already in the view
        target = next((g for g in groups if (g.get("key") or "") == (group_key or "")), None)
        if target is None:
            target = {"key": group_key or "", "artifact_ids": []}
            groups.append(target)
        target.setdefault("artifact_ids", []).append(artifact_id)
        result["groups"] = groups
        conn.execute(
            "UPDATE saved_pivots SET result_json = ? WHERE id = ?",
            (json.dumps(result), pivot_id),
        )
    _resync_pivots()
    return result


def all_specs() -> list[dict]:
    """Every saved view with its spec, in one query (P.2e).

    The artifact detail endpoint checks membership against every spec; a
    per-view `get()` was one SELECT per saved view. A row whose spec does not
    parse is skipped - the same silent omission the per-view loop produced - so
    one corrupt row never breaks the artifact page.
    """
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, name, spec_json, created_at FROM saved_pivots" " ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    out = []
    for row in rows:
        data = dict(row)
        raw = data.pop("spec_json")
        try:
            data["spec"] = json.loads(raw)
        except (TypeError, ValueError):
            continue
        out.append(data)
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
        # The membership changed, so the cached grouping is stale - drop it so the
        # next open recomputes rather than serving the pre-edit result.
        clear_result(conn, pivot_id)
        updated = conn.execute(
            "SELECT id, name, created_at FROM saved_pivots WHERE id = ?", (pivot_id,)
        ).fetchone()
        result = dict(updated)
    _resync_pivots()
    return result


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
        result = dict(updated)
    _resync_pivots()
    return result


def delete(pivot_id: str) -> None:
    """Forget a saved view. Idempotent: deleting one already gone is not an error."""
    with db.transaction() as conn:
        conn.execute("DELETE FROM saved_pivots WHERE id = ?", (pivot_id,))
    _resync_pivots()
