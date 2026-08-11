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
    result = pivot.run(req.spec)

    conn = db.get_conn()
    try:
        ids = [aid for group in result["groups"] for aid in group["artifact_ids"]]
        wall: dict[str, dict] = {}
        if ids:
            rows = conn.execute(
                f"SELECT {_ARTIFACT_COLUMNS} FROM artifacts"
                " WHERE id IN (SELECT value FROM json_each(?))",
                (json.dumps(ids),),
            ).fetchall()
            with_image = _link_images(conn, [row["id"] for row in rows if row["kind"] == "link"])
            with_tags = _wall_tags(conn, [row["id"] for row in rows])
            for row in rows:
                wall[row["id"]] = _wall_item(conn, row, with_image, with_tags)
    finally:
        conn.close()

    for group in result["groups"]:
        group["items"] = [wall.get(aid, {}) for aid in group["artifact_ids"]]
    return result


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
