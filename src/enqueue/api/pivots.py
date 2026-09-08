"""Pivots: the natural-language planner, live runs, and saved groupings.

Turn an "organize ..." request into a spec, run it against the library, and
persist named arrangements that re-run live as the library grows.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, derive, pivot, pivots_saved
from .wall import _ARTIFACT_COLUMNS, _link_images, _wall_item, _wall_tags

router = APIRouter()


class PivotPlanRequest(BaseModel):
    request: str


@router.post("/pivot/plan")
def plan_pivot(req: PivotPlanRequest) -> dict:
    """Turn a natural-language request into a pivot spec, in one planner call.

    The returned spec is a plain dict the client can send straight back to
    POST /pivot/run. A request the planner cannot turn into a runnable spec
    comes back as a 400 with a sentence the UI can show, never a traceback.
    """
    try:
        return {"spec": pivot.plan(req.request)}
    except pivot.PivotError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


class PivotRunRequest(BaseModel):
    spec: dict


def _hydrate(result: dict) -> dict:
    """Fill each group's `items` with the current wall cards for its artifact_ids.

    Cards are always read fresh here (titles/state can have changed since a cached
    grouping was computed), so only the expensive grouping is ever cached, never the
    cards. Mutates and returns `result`.
    """
    conn = db.get_conn()
    try:
        ids = [aid for group in result["groups"] for aid in group["artifact_ids"]]
        wall: dict[str, dict] = {}
        if ids:
            # Only live artifacts hydrate: a locked view keeps its frozen membership,
            # but an artifact trashed/vaulted/embedded since it was built simply drops
            # out of the display (and returns if restored) without recomputing groups.
            rows = conn.execute(
                f"SELECT {_ARTIFACT_COLUMNS} FROM artifacts"
                " WHERE id IN (SELECT value FROM json_each(?))"
                " AND deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL",
                (json.dumps(ids),),
            ).fetchall()
            with_image = _link_images(conn, [row["id"] for row in rows if row["kind"] == "link"])
            with_tags = _wall_tags(conn, [row["id"] for row in rows])
            for row in rows:
                wall[row["id"]] = _wall_item(conn, row, with_image, with_tags)
    finally:
        conn.close()
    for group in result["groups"]:
        group["items"] = [wall[aid] for aid in group["artifact_ids"] if aid in wall]
    return result


def _strip_items(result: dict) -> dict:
    """The cacheable shell of a run: the group structure without hydrated cards.

    Cards are re-hydrated on every serve, so caching them would both bloat the row
    and let a stale title linger. Only keys + artifact_ids + the run's flags persist.
    """
    return {
        **{k: v for k, v in result.items() if k != "groups"},
        "groups": [{k: v for k, v in group.items() if k != "items"} for group in result["groups"]],
    }


@router.post("/pivot/run")
def run_pivot(req: PivotRunRequest) -> dict:
    """Run a pivot spec and return each group's cards, no second round trip.

    The groups come back exactly as pivot.run produced them (key, artifact_ids,
    grounded, largest first) with each group's artifact_ids hydrated into wall
    items so the client renders cards without a second call. `grounded` and
    `truncated` stay in the response: an enrich step means the grouping uses
    the assistant's knowledge rather than the notes' own text, and a truncated
    subset means the largest groups may not be the complete picture.
    """
    return _hydrate(pivot.run(req.spec))


@router.get("/pivots/{pivot_id}/open")
def open_pivot(pivot_id: str) -> dict:
    """Open a saved view, fast: serve the cached grouping when there is one, else run.

    A view with an `extract`/`enrich` step pays for model judgments on every full run;
    caching the group structure makes a re-open instant. The first open (or one after a
    spec edit) computes and fills the cache; later opens serve it. Either way the cards
    are hydrated fresh, and `cached` tells the client whether to fire a background
    /refresh to pick up new artifacts. `result_at` is when the cache was computed.
    """
    try:
        saved = pivots_saved.get(pivot_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such saved view") from None
    cached = saved.get("result")
    if cached is not None:
        # `stale` gates the client's background refresh: only re-run (paying model
        # calls again) when the library actually changed since the cache was built.
        # Nothing new -> serve the cache and stop, so a re-open costs nothing.
        conn = db.get_conn()
        try:
            latest = conn.execute("SELECT MAX(updated_at) FROM artifacts").fetchone()[0]
        finally:
            conn.close()
        result_at = saved.get("result_at")
        stale = not result_at or (latest is not None and latest > result_at)
        return {
            "id": saved["id"],
            "name": saved["name"],
            "spec": saved["spec"],
            "result": _hydrate(cached),
            "cached": True,
            "stale": stale,
            "result_at": result_at,
        }
    result = pivot.run(saved["spec"])
    pivots_saved.set_result(pivot_id, _strip_items(result))
    return {
        "id": saved["id"],
        "name": saved["name"],
        "spec": saved["spec"],
        "result": _hydrate(result),
        "cached": False,
        "result_at": None,
    }


@router.post("/pivots/{pivot_id}/refresh")
def refresh_pivot(pivot_id: str) -> dict:
    """Re-run a saved view's spec and replace its cached grouping, returning the fresh
    result. The client fires this in the background after serving a cached open, so a
    view stays live (new artifacts land in it) without making the open itself wait.
    """
    try:
        saved = pivots_saved.get(pivot_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such saved view") from None
    result = pivot.run(saved["spec"])
    pivots_saved.set_result(pivot_id, _strip_items(result))
    return {
        "id": saved["id"],
        "name": saved["name"],
        "spec": saved["spec"],
        "result": _hydrate(result),
        "cached": False,
        "result_at": None,
    }


class PivotRemoveRequest(BaseModel):
    artifact_ids: list[str]


@router.post("/pivots/{pivot_id}/remove")
def remove_from_pivot(pivot_id: str, req: PivotRemoveRequest) -> dict:
    """Remove artifacts from a locked view by editing its materialized result.

    A saved view is a frozen arrangement: removing a card drops it from the stored
    groups (no re-run, no model call, no "Removed" shelf), so a re-open shows exactly
    what was left. The artifact itself is untouched - it still lives on the wall. 404
    when the view is unknown; 409 when it has never been opened (nothing materialized
    yet to edit).
    """
    try:
        result = pivots_saved.remove_from_result(pivot_id, req.artifact_ids)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such saved view") from None
    if result is None:
        raise HTTPException(
            status_code=409, detail="open the view once before editing it"
        ) from None
    return {"result": _hydrate(result)}


class PivotAddRequest(BaseModel):
    artifact_id: str


@router.post("/pivots/{pivot_id}/add")
def add_to_pivot(pivot_id: str, req: PivotAddRequest) -> dict:
    """Add an artifact to a locked view without recomputing it.

    A plain field grouping (e.g. by kind) places the artifact by reading its own row -
    no model call. A model-based grouping cannot be placed without re-running, so the
    artifact drops into the "not determined" group until the next Rebuild sorts it. 404
    on an unknown view, 409 when it has never been opened (nothing to add into yet).
    """
    try:
        saved = pivots_saved.get(pivot_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such saved view") from None
    spec = saved["spec"]
    group_by = spec.get("group_by")
    attr = group_by.get("attribute") if isinstance(group_by, dict) else None
    steps = spec.get("steps") or []
    key = ""
    if attr and (not steps or steps[0].get("op") == "field"):
        try:
            key = derive.field(req.artifact_id, attr)["value"]
        except Exception:  # noqa: BLE001 - a bad field read just lands it in "" (undetermined)
            key = ""
    result = pivots_saved.add_to_result(pivot_id, req.artifact_id, key)
    if result is None:
        raise HTTPException(
            status_code=409, detail="open the view once before editing it"
        ) from None
    return {"result": _hydrate(result)}


class PivotAddableRequest(BaseModel):
    spec: dict


@router.post("/pivot/addable")
def pivot_addable(req: PivotAddableRequest) -> dict:
    """The artifacts a pivot could still take in (N.3a/N.3b add flow).

    The picker must offer only artifacts the view does not already contain: a
    run covers its subset's matches minus exclusions plus inclusions, so an
    artifact already covered is a no-op add (the client used to list the whole
    library and every pick of a covered artifact toasted "already in this
    view" - real, but useless). This resolves the covered set without running
    the step chain (pure SQL, no model calls) and returns the rest. A view
    whose subset covers everything comes back empty, and the picker says
    "Nothing left to add." instead of pretending a pick would do something.
    """
    spec = req.spec
    try:
        ids, _ = pivot.resolve_subset(spec.get("subset") or {"kind": "search", "value": ""})
    except (KeyError, ValueError):
        # A stale or hand-built spec must not 500 the picker; treat it as
        # covering nothing so the view stays addable.
        ids = []
    excluded = set(spec.get("excluded_ids") or [])
    included = set(spec.get("included_ids") or [])
    in_view = set(ids) - excluded | included

    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, title FROM artifacts"
            " WHERE kind != 'chat' ORDER BY updated_at DESC LIMIT 200"
        ).fetchall()
    finally:
        conn.close()
    return {
        "items": [
            {"id": row["id"], "title": row["title"]} for row in rows if row["id"] not in in_view
        ]
    }


class DerivedOverrideRequest(BaseModel):
    scope: str
    subject: str
    attribute: str
    value: str


@router.post("/derived/override")
def derived_override(req: DerivedOverrideRequest) -> dict:
    """Write a user correction for a derived value and return the stored row.

    The correction is stored with source='user', which always wins over the
    model row on read (rule 2: the director beats the curator), so re-running
    the same pivot shows the corrected value. This is how a misfiled item gets
    moved to the right group; it must stay visible because a misfiled item is
    otherwise invisible.
    """
    return derive.override(req.scope, req.subject, req.attribute, req.value)


class SavePivotRequest(BaseModel):
    name: str
    spec: dict


@router.post("/pivots")
def save_pivot(req: SavePivotRequest) -> dict:
    """Save a grouping under a name and return its id.

    The spec is the arrangement's recipe, stored as-is; opening it later re-runs
    it live (POST /pivot/run), so the grouping stays true as the library grows
    rather than freezing into a snapshot. A missing name is a 400, not a 500.
    """
    try:
        return {"id": pivots_saved.save(req.name, req.spec)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/pivots")
def list_pivots() -> dict:
    """Every saved grouping, newest first, name and date only (no spec)."""
    return {"items": pivots_saved.listing()}


@router.get("/pivots/{pivot_id}")
def get_pivot(pivot_id: str) -> dict:
    """One saved grouping with its spec, ready to send to POST /pivot/run."""
    try:
        return pivots_saved.get(pivot_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No saved grouping by that id.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


class PivotRename(BaseModel):
    name: str


@router.patch("/pivots/{pivot_id}")
def rename_pivot(pivot_id: str, req: PivotRename) -> dict:
    """Rename a saved grouping (the pencil beside its name in the custom wall).

    The name is trimmed and must not be empty; the spec (the arrangement) is
    untouched. 404 on an unknown grouping, 400 on an empty name.
    """
    try:
        updated = pivots_saved.rename(pivot_id, req.name)
    except KeyError:
        raise HTTPException(status_code=404, detail="No saved grouping by that id.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"pivot": updated}


@router.delete("/pivots/{pivot_id}")
def delete_pivot(pivot_id: str) -> dict:
    """Forget a saved grouping. Idempotent: deleting one already gone still 200s."""
    pivots_saved.delete(pivot_id)
    return {"deleted": pivot_id}


class PivotExclude(BaseModel):
    artifact_id: str
    undo: bool = False


@router.post("/pivots/{pivot_id}/exclude")
def exclude_pivot_artifact(pivot_id: str, req: PivotExclude) -> dict:
    """Exclude (or, with undo, restore) one artifact in a saved grouping.

    A saved grouping is a computed pivot: its members are whatever the spec
    produces over the current library, so removing a card means excluding its id
    from the spec. This reads the stored spec, appends `artifact_id` to
    `excluded_ids` (or removes it when `undo` is true), and saves it back; the
    next re-run of the grouping leaves the artifact out. The artifact itself is
    never touched - it still lives on the wall and in the library.
    """
    try:
        saved = pivots_saved.get(pivot_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No saved grouping by that id.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    spec = saved["spec"]
    excluded = [aid for aid in (spec.get("excluded_ids") or []) if aid != req.artifact_id]
    if not req.undo:
        excluded.append(req.artifact_id)
    spec["excluded_ids"] = excluded
    pivots_saved.update_spec(pivot_id, spec)
    return {"pivot_id": pivot_id, "excluded_ids": excluded}


class PivotExcludeMany(BaseModel):
    artifact_ids: list[str]
    undo: bool = False


@router.post("/pivots/{pivot_id}/exclude-many")
def exclude_pivot_artifacts(pivot_id: str, req: PivotExcludeMany) -> dict:
    """Exclude (or, with undo, restore) several artifacts in one write (P.3b).

    The same read-modify-write as the single-artifact exclude, batched: every
    id in the list is appended to `excluded_ids` (or removed when `undo` is
    true) in one request, so removing a whole group is one round trip instead
    of one POST per artifact. Duplicate ids in the list collapse.
    """
    try:
        saved = pivots_saved.get(pivot_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No saved grouping by that id.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    ids = list(dict.fromkeys(req.artifact_ids))
    spec = saved["spec"]
    excluded = [aid for aid in (spec.get("excluded_ids") or []) if aid not in ids]
    if not req.undo:
        excluded.extend(ids)
    spec["excluded_ids"] = excluded
    pivots_saved.update_spec(pivot_id, spec)
    return {"pivot_id": pivot_id, "excluded_ids": excluded}


class PivotInclude(BaseModel):
    artifact_id: str
    undo: bool = False


@router.post("/pivots/{pivot_id}/include")
def include_pivot_artifact(pivot_id: str, req: PivotInclude) -> dict:
    """Force (or, with undo, un-force) one artifact into a saved grouping.

    A saved grouping's subset filters the library, so an artifact that does not
    match the subset can only appear by being forced in. This reads the stored
    spec, appends `artifact_id` to `included_ids` (or removes it when `undo` is
    true), and saves it back; the next re-run of the grouping places the
    artifact into whichever group its group_by attribute resolves to. The
    artifact is never copied or moved - it just joins this arrangement too.
    """
    try:
        saved = pivots_saved.get(pivot_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No saved grouping by that id.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    spec = saved["spec"]
    included = [aid for aid in (spec.get("included_ids") or []) if aid != req.artifact_id]
    if not req.undo:
        included.append(req.artifact_id)
    spec["included_ids"] = included
    pivots_saved.update_spec(pivot_id, spec)
    return {"pivot_id": pivot_id, "included_ids": included}
