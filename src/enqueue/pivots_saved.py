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


# ---- views arranged by hand ---------------------------------------------------------
# A manual view is the same saved view (one concept, one table), with no recipe: its
# spec is just `{"manual": true}` and its frozen result IS the arrangement - headers in
# the person's order, each with its artifacts in the person's order. Nothing ever
# recomputes it and no model is involved; the page sends the whole layout back after
# every change (`set_layout`), which keeps one write path for add, reorder, rename,
# move and delete.

MANUAL_SPEC = {"manual": True, "subset": {"kind": "ids", "value": ""}, "steps": []}
MAX_HEADER = 120


def is_manual(spec: dict | None) -> bool:
    return bool(spec and spec.get("manual"))


def _clean_layout(groups: list[dict]) -> list[dict]:
    """A layout as stored: header names trimmed and unique, each artifact under one
    header only (its first), order kept. An empty header is kept - it is a header the
    person made and has not filled yet."""
    out: list[dict] = []
    names: set[str] = set()
    placed: set[str] = set()
    for group in groups or []:
        key = " ".join(str(group.get("key") or "").split())[:MAX_HEADER]
        if key.casefold() in names:
            raise ValueError(f'two headers are both called "{key or "Unsorted"}"')
        names.add(key.casefold())
        ids = []
        for aid in group.get("artifact_ids") or []:
            if isinstance(aid, str) and aid and aid not in placed:
                placed.add(aid)
                ids.append(aid)
        out.append({"key": key, "artifact_ids": ids})
    return out


def save_manual(name: str, groups: list[dict] | None = None) -> str:
    """Create a view arranged by hand, optionally starting from an arrangement (the
    groups of another view, to take it over by hand). Returns the new id."""
    name = name.strip()
    if not name:
        raise ValueError("a saved view needs a name")
    pivot_id = str(uuid.uuid4())
    result = {
        "manual": True,
        "truncated": False,
        "group_by": "",
        "groups": _clean_layout(groups or []),
    }
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO saved_pivots (id, name, spec_json, created_at, result_json, result_at)"
            " VALUES (?,?,?,?,?,?)",
            (pivot_id, name[:120], json.dumps(MANUAL_SPEC), db.now(), json.dumps(result), db.now()),
        )
    _resync_pivots()
    return pivot_id


def set_layout(pivot_id: str, groups: list[dict]) -> dict:
    """Replace a manual view's whole arrangement. KeyError for an unknown view,
    ValueError for a view that is not arranged by hand or a layout with two headers
    of the same name."""
    layout = _clean_layout(groups)
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT spec_json FROM saved_pivots WHERE id = ?", (pivot_id,)
        ).fetchone()
        if row is None:
            raise KeyError(pivot_id)
        try:
            spec = json.loads(row["spec_json"])
        except (TypeError, ValueError):
            spec = {}
        if not is_manual(spec):
            raise ValueError("only a view arranged by hand has a layout to set")
        result = {"manual": True, "truncated": False, "group_by": "", "groups": layout}
        conn.execute(
            "UPDATE saved_pivots SET result_json = ?, result_at = ? WHERE id = ?",
            (json.dumps(result), db.now(), pivot_id),
        )
    _resync_pivots()
    return result


def manual_membership(artifact_id: str) -> list[dict]:
    """The hand-arranged views holding this artifact, as `{id, name}` (for the
    artifact page's Views row; recipe views answer that from their spec)."""
    return [
        {"id": saved["id"], "name": saved["name"]}
        for saved in all_specs()
        if artifact_id in saved.get("manual_ids", ())
    ]


def listing() -> list[dict]:
    """Every saved view, newest first, without the spec.

    The list is for choosing, so it carries only what a row shows - name and
    when it was saved. The spec is fetched by `get` when a view is opened.
    """
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, name, created_at,"
            " COALESCE(json_extract(spec_json, '$.manual'), 0) AS manual"
            " FROM saved_pivots ORDER BY created_at DESC"
        ).fetchall()
        return [{**dict(row), "manual": bool(row["manual"])} for row in rows]
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

    The `removed` map (which group each removed card came from) is carried over from
    the previous result, so a Rebuild does not forget where a card goes back to.
    """
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT result_json FROM saved_pivots WHERE id = ?", (pivot_id,)
        ).fetchone()
        if row is not None and row["result_json"] and "removed" not in result:
            try:
                kept = json.loads(row["result_json"]).get("removed")
            except (TypeError, ValueError):
                kept = None
            if kept:
                result = {**result, "removed": kept}
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
    call). The removal is also written down, in two places: the spec's `excluded_ids`
    (so a Rebuild keeps the card out, and the view's Removed shelf lists it) and the
    result's `removed` map of id -> the group it left (so `restore_to_result` can put
    it back where it was). Before this a removal lived only in the frozen groups: the
    shelf could not show it, Restore had nothing to undo, and a Rebuild brought every
    removed card back. Empty groups are pruned. Returns the updated structure, or None
    when the view has no cache yet (it must be opened once to materialize before it
    can be edited). `result_at` is left as it was - an edit is not a recompute.
    """
    drop = set(artifact_ids)
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT result_json, spec_json FROM saved_pivots WHERE id = ?", (pivot_id,)
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
        removed = dict(result.get("removed") or {})
        # A header in a hand-arranged view is the person's, filled or not: emptying it
        # does not delete it.
        keep_empty = bool(result.get("manual"))
        for group in result.get("groups", []):
            kept = []
            for aid in group.get("artifact_ids", []):
                if aid in drop:
                    removed[aid] = group.get("key") or ""
                else:
                    kept.append(aid)
            if kept or keep_empty:
                group["artifact_ids"] = kept
                groups.append(group)
        result["groups"] = groups
        result["removed"] = removed
        try:
            spec = json.loads(row["spec_json"])
        except (TypeError, ValueError):
            spec = {}
        excluded = list(spec.get("excluded_ids") or [])
        excluded.extend(aid for aid in artifact_ids if aid in removed and aid not in excluded)
        spec["excluded_ids"] = excluded
        conn.execute(
            "UPDATE saved_pivots SET result_json = ?, spec_json = ? WHERE id = ?",
            (json.dumps(result), json.dumps(spec), pivot_id),
        )
    _resync_pivots()
    return result


def restore_to_result(pivot_id: str, artifact_ids: list[str], place=None) -> dict | None:
    """Put removed artifacts back into a locked view, each in the group it left.

    The reverse of `remove_from_result`, also without a recompute: the id leaves the
    spec's `excluded_ids`, and joins the group recorded for it in the result's
    `removed` map. An exclusion older than that map (or one whose group a Rebuild
    dissolved) has no recorded group; `place(artifact_id)` supplies one - the caller
    passes a cache-only placement, so nothing here ever calls a model - and "" (shown
    as "Not determined") is the fallback. Returns the updated structure, or None when
    the view has no cache yet.
    """
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT result_json, spec_json FROM saved_pivots WHERE id = ?", (pivot_id,)
        ).fetchone()
        if row is None:
            raise KeyError(pivot_id)
        if not row["result_json"]:
            return None
        try:
            result = json.loads(row["result_json"])
            spec = json.loads(row["spec_json"])
        except (TypeError, ValueError):
            return None
        groups = result.get("groups", [])
        removed = dict(result.get("removed") or {})
        present = {aid for g in groups for aid in (g.get("artifact_ids") or [])}
        for aid in artifact_ids:
            key = removed.pop(aid, None)
            if aid in present:
                continue
            if key is None:
                key = (place(aid) if place else "") or ""
            target = next((g for g in groups if (g.get("key") or "") == key), None)
            if target is None:
                target = {"key": key, "artifact_ids": []}
                groups.append(target)
            target.setdefault("artifact_ids", []).append(aid)
            present.add(aid)
        back = set(artifact_ids)
        spec["excluded_ids"] = [a for a in (spec.get("excluded_ids") or []) if a not in back]
        result["groups"] = groups
        result["removed"] = removed
        conn.execute(
            "UPDATE saved_pivots SET result_json = ?, spec_json = ? WHERE id = ?",
            (json.dumps(result), json.dumps(spec), pivot_id),
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
            "SELECT result_json, spec_json FROM saved_pivots WHERE id = ?", (pivot_id,)
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
        # Adding back something that was removed ends its exclusion, or the next
        # Rebuild would drop it again.
        try:
            spec = json.loads(row["spec_json"])
        except (TypeError, ValueError):
            spec = None
        if spec is not None and artifact_id in (spec.get("excluded_ids") or []):
            spec["excluded_ids"] = [a for a in spec["excluded_ids"] if a != artifact_id]
            conn.execute(
                "UPDATE saved_pivots SET spec_json = ? WHERE id = ?",
                (json.dumps(spec), pivot_id),
            )
        if artifact_id in (result.get("removed") or {}):
            result["removed"].pop(artifact_id)
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
            "SELECT id, name, spec_json, created_at,"
            # Only a hand-arranged view's arrangement is read here: it IS that view's
            # membership, and reading it in the same query keeps this at one.
            " CASE WHEN json_extract(spec_json, '$.manual') = 1 THEN result_json END"
            "   AS layout_json"
            " FROM saved_pivots ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    out = []
    for row in rows:
        data = dict(row)
        raw = data.pop("spec_json")
        layout = data.pop("layout_json")
        try:
            data["spec"] = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if is_manual(data["spec"]):
            try:
                groups = json.loads(layout).get("groups") or [] if layout else []
            except (TypeError, ValueError):
                groups = []
            data["manual_ids"] = {aid for g in groups for aid in g.get("artifact_ids") or []}
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
