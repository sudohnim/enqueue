"""Pivot: group a subset of the library by a computed attribute.

A pivot is a short pipeline of `derive` primitives - `extract` reads an
attribute from one artifact's content (grounded), `enrich` infers it from
another value using world knowledge (not grounded), `field` reads it straight
from the artifact's own row (zero model calls, the most grounded of the
three) - ending in a group key, then a plain code-level group-by. The model
does only the per-item judgments; ordinary code does the selecting, caching,
grouping, and rendering. The library never groups itself in one giant prompt.

Nothing here is hardcoded to a domain. The subset, the attribute names, the
instructions, and the group key are parameters that arrive at runtime. Every
derived value carries its `grounded` flag through `derive` and into the
response, so an inferred value is never dressed as the user's data.
"""

from __future__ import annotations

import re
from collections import defaultdict

from pydantic import BaseModel

from . import db, derive, fields  # noqa: F401 - db for later phases; derive used by run()
from .providers.base import get_provider  # the planner's one model call

MAX_PIVOT_ARTIFACTS = 200


class PivotError(Exception):
    """A request that could not be turned into a runnable pivot spec.

    The message is a sentence the UI can show (P5.1 maps it to a 400), so it
    must read like a message to a person, not a traceback.
    """


class _PlannedStep(BaseModel):
    op: str  # 'extract' reads the note; 'enrich' infers from a prior value; 'field' reads a stored column
    attribute: str
    instruction: str


class _PlannedSubset(BaseModel):
    kind: str  # 'search', 'tags', or 'ids'
    value: str


class _PlannedSpec(BaseModel):
    subset: _PlannedSubset
    steps: list[_PlannedStep]
    group_by: str
    bucketize: bool = False
    bucketize_instruction: str = ""


def resolve_subset(subset: dict) -> tuple[list[str], bool]:
    """Return the artifact ids matched by a subset spec, capped at MAX_PIVOT_ARTIFACTS.

    A subset is a plain dict: {"kind": "search" | "tags" | "ids", "value": ...}.
    The three kinds select different sources, but every one comes back as a flat
    list of artifact ids:

      search  the artifact search surface (one row per artifact)
      tags    artifacts carrying ALL of the comma-separated tag names
      ids     a literal comma- or whitespace-separated id list

    The result is capped: when more than MAX_PIVOT_ARTIFACTS artifacts match,
    the first MAX_PIVOT_ARTIFACTS are returned and the boolean records that the
    subset was truncated, so run() can report `truncated: true` to the client.
    """
    kind = subset["kind"]
    value = subset["value"]

    if kind == "ids":
        ids = [part for part in re.split(r"[, ]+", value.strip()) if part]
    elif kind == "tags":
        from . import tags

        names = [tags.normalize(name) for name in value.split(",") if name.strip()]
        ids = sorted(tags.ids_with_all(names))
    elif kind == "search":
        from .retrieve import candidates

        # Ask for one more than the cap so truncation is observable.
        results = candidates.search_results(value, limit=MAX_PIVOT_ARTIFACTS + 1)
        ids = [r["artifact_id"] for r in results]
    else:
        raise ValueError(f"unknown subset kind: {kind!r}")

    truncated = len(ids) > MAX_PIVOT_ARTIFACTS
    return ids[:MAX_PIVOT_ARTIFACTS], truncated


def _affirmative(value: str) -> bool:
    """Read a filter judgment as keep-or-drop. A `filter` step asks the model a
    yes/no ("is this a book"); the reply is kept when it is affirmative and
    dropped otherwise. An empty answer ("I do not know") drops - a filter keeps
    only what it can positively affirm, never what it merely failed to rule out."""
    head = value.strip().lower()
    return head.startswith("yes") or head in ("true", "1", "y")


def run(spec: dict) -> dict:
    """Execute a pivot spec end to end.

    The spec is a plain dict (see the plan): a subset, a chain of steps whose
    first op is `extract` or `field` and whose later ops are `enrich`, a
    group_by attribute, and an optional bucketize pass. The model does only
    the per-item judgments through `derive`; selecting, caching, grouping, and
    rendering are ordinary code. The library is never grouped in one giant
    prompt.

    The call budget is the plan's bounded shape: `extract` runs per artifact
    (cached per artifact), `field` reads each artifact's own row (a free SQL
    read, never cached), and `enrich` runs once per DISTINCT current value
    (cached per value), never once per artifact. Every `derive` result is
    cached - `extract` and `enrich` so a re-run pays for model calls only for
    artifacts or values never seen before (resumable and cheap on re-run),
    `field` by nature of being a read. A run whose only step is a `field`
    makes no model calls at all.

    The final key can be the empty string - an artifact whose derived value was
    "none found" - and it is never dropped or hidden: it becomes the '' bucket,
    rendered as "not determined" by the UI (rule 2, and the bucketize pass
    never sees it, so the model cannot merge it away).
    """
    ids, truncated = resolve_subset(spec["subset"])

    steps = spec["steps"]
    if not steps:
        raise ValueError("a pivot spec needs at least one step")

    # The first step fills the key map. An extract is one judgment per
    # artifact; a field is the same loop with zero model calls - a SQL read
    # straight off each artifact's own row.
    key_of: dict[str, str] = {}
    first = steps[0]
    if first["op"] == "field":
        for artifact_id in ids:
            key_of[artifact_id] = derive.field(artifact_id, first["attribute"])["value"]
    else:
        for artifact_id in ids:
            key_of[artifact_id] = derive.extract(
                artifact_id, first["attribute"], first["instruction"]
            )["value"]

    # The working set shrinks as `filter` steps prune it; `enrich` remaps the key
    # of whatever survives. Downstream (bucketize, grouping) sees only `kept`.
    kept = list(ids)
    any_inference = False
    for step in steps[1:]:
        any_inference = True
        if step["op"] == "filter":
            # One yes/no judgment per DISTINCT current value (deduped, world
            # knowledge, so it reuses enrich's per-value cache): "is this a
            # book", "is this fiction". Keep only the artifacts whose current
            # value is judged in. The group key is untouched - a filter prunes
            # the set, it does not change what the survivors group by. The
            # membership is inferred, so the whole run reports ungrounded.
            verdict = {
                value: _affirmative(
                    derive.enrich(value, step["attribute"], step["instruction"])["value"]
                )
                for value in sorted({key_of[aid] for aid in kept})
            }
            kept = [aid for aid in kept if verdict.get(key_of[aid], False)]
            continue

        # enrich: one call per DISTINCT current value among the survivors.
        remap = {
            value: derive.enrich(value, step["attribute"], step["instruction"])["value"]
            for value in sorted({key_of[aid] for aid in kept})
        }
        for artifact_id in kept:
            # A user correction on this artifact wins over the inferred value
            # (rule 2: the director beats the curator). The move control writes
            # scope='artifact' on the group attribute, so the enrich step must
            # consult that cache too, not only the per-value one.
            corrected = derive._read("artifact", artifact_id, step["attribute"])
            if corrected is not None and corrected["source"] == "user":
                key_of[artifact_id] = corrected["value"]
            else:
                key_of[artifact_id] = remap.get(key_of[artifact_id], "")

    if spec.get("bucketize"):
        mapping = derive.bucketize(
            [key for key in sorted({key_of[aid] for aid in kept}) if key],
            spec.get("bucketize_instruction", ""),
        )
        for artifact_id in kept:
            key_of[artifact_id] = mapping.get(key_of[artifact_id], key_of[artifact_id])

    grouped: dict[str, list[str]] = defaultdict(list)
    for artifact_id in kept:
        grouped[key_of[artifact_id]].append(artifact_id)

    groups = [
        {"key": key, "artifact_ids": artifact_ids, "grounded": not any_inference}
        for key, artifact_ids in grouped.items()
    ]
    groups.sort(key=lambda group: len(group["artifact_ids"]), reverse=True)

    return {"groups": groups, "truncated": truncated, "group_by": spec["group_by"]}


def plan(request: str) -> dict:
    """Turn a natural-language request into a runnable pivot spec.

    One model call: the planner reads the request and returns the whole spec -
    the subset, the step chain (extract reads from the note, field reads a
    stored column, enrich infers from world knowledge), the group_by attribute,
    and the bucketize settings. The model decides all of it; this function
    parses the reply and validates that run() can execute it.

    A plan that cannot be run - no steps, an unknown subset kind or op, an
    inference step leading the chain, or a group_by that is not the last step's
    attribute - raises PivotError with a sentence the UI can show, and so does a
    failed model call. Nothing domain-specific is assumed: the request, the
    attributes, and the instructions are all runtime parameters.
    """
    request = request.strip()
    if not request:
        raise PivotError("Tell me what to group and how, and I will plan it.")

    from .prompts import PIVOT_PLAN

    # get_provider() reads settings; it cannot fail per-request, but it must not
    # run inside the try or a failure there would leave `provider` unbound for
    # the corrective pass below.
    provider = get_provider()
    try:
        result = provider.complete(
            system=PIVOT_PLAN.format(request=request, fields=_fields_block()),
            user="",
            response_model=_PlannedSpec,
        )
    except Exception as exc:  # noqa: BLE001 - a failed plan is reported, not crashed
        # A model that could not hold the format gets one corrective pass: tell it
        # exactly what failed validation and let it try again. The first attempt
        # already ran instructor's own retries, so a second failure is a real limit,
        # not bad luck. Every other failure - endpoint down, key rejected, a host
        # that is not a model - is reported as-is.
        if not _plan_validation_failure(exc):
            raise PivotError(
                f"I could not turn that request into a grouping plan "
                f"({type(exc).__name__}: {exc})."
            ) from exc
        try:
            result = provider.complete(
                system=(
                    PIVOT_PLAN.format(request=request, fields=_fields_block())
                    + "\n\nYour previous reply did not match the required JSON shape:\n"
                    + str(exc)[:400]
                    + "\n\nReply again with the complete JSON object, every field a "
                    "non-empty string, no commentary."
                ),
                user="",
                response_model=_PlannedSpec,
            )
        except Exception as retry_exc:  # noqa: BLE001 - same translation
            raise PivotError(
                f"I could not turn that request into a grouping plan "
                f"({type(retry_exc).__name__}: {retry_exc})."
            ) from retry_exc

    spec = result.model_dump()

    # Canonical attribute names: the derive cache keys on lowercased attributes.
    for step in spec["steps"]:
        step["attribute"] = step["attribute"].strip().lower()

    # A 'field' reads a real column; the readable fields are a closed registry. When
    # the model labels an attribute that is NOT a registered field as a 'field' - a
    # weak model will call "fiction or non-fiction" or "genre" a field because it
    # sounds like a property - it cannot be a column read, so it is an inference:
    # coerce it to 'enrich'. This is semantics-preserving and more honest, not less
    # (a fake-grounded field becomes an honestly ungrounded enrich), and it turns a
    # flaky reject into a working grouping. A coerced first step becomes an enrich
    # lead, which the block below then grounds with a prepended read.
    for step in spec["steps"]:
        if step["op"] == "field" and step["attribute"] not in fields.FIELDS:
            step["op"] = "enrich"

    # A model that skips the extract step plans a chain that reads nothing from
    # the note: every value would be inferred from world knowledge, and the first
    # step would be rejected by _validate_plan. Rather than fail the request,
    # ground the chain deterministically - prepend the one read every chain
    # needs (rule 1), pulling the note's own tags/topics as the natural input for
    # the enrich that follows. No extra model call: this is structure, not
    # inference. The enrich step still marks the groups ungrounded, so the UI
    # still discloses that the grouping is inferred (rule 2).
    if spec["steps"] and spec["steps"][0]["op"] == "enrich":
        spec["steps"].insert(
            0,
            {
                "op": "extract",
                "attribute": "tags",
                "instruction": (
                    "From the note's own text, list the tags or key topics it mentions."
                ),
            },
        )

    # The group key is, by construction, whatever the last step computes: run() groups
    # on those values and never reads `group_by` except as a label. A model that names a
    # different group_by than its own last step is not wrong about anything runnable, so
    # this is derived rather than trusted. It removes a whole class of "groups by X but
    # the last step computes Y" failures on requests that would otherwise run fine.
    if spec["steps"]:
        spec["group_by"] = spec["steps"][-1]["attribute"]

    _validate_plan(spec)
    return spec


def _fields_block() -> str:
    """The readable-field registry rendered the way the planner prompt wants it.

    Mirrors the assistant router's `_skills_block`: one `- name: describe` line
    per entry, so the model sees exactly the names it may use in a `field` step.
    """
    return "\n".join(f"- {name}: {field.describe}" for name, field in fields.FIELDS.items())


def _validate_plan(spec: dict) -> None:
    """Reject a planned spec that run() could not execute, with a UI sentence."""
    steps = spec["steps"]
    if not steps:
        raise PivotError("The plan came back with no steps, so there is nothing to group by.")
    if spec["subset"]["kind"] not in ("search", "tags", "ids"):
        raise PivotError(
            f"The plan selects the notes with '{spec['subset']['kind']}', "
            "which is not a selection I know how to run."
        )
    # A plan that selects by id but names none groups nothing - the model reached
    # for 'ids' as a placeholder and left it empty. 'Everything' is a search with
    # an empty value, not an empty id list, so this is a plan to reject, not run.
    if spec["subset"]["kind"] == "ids" and not spec["subset"]["value"].strip():
        raise PivotError(
            "The plan selects the notes by id but names none, so there is nothing to group."
        )
    for index, step in enumerate(steps):
        if step["op"] not in ("extract", "enrich", "field", "filter"):
            raise PivotError(
                f"Step {index + 1} of the plan uses '{step['op']}', "
                "which is not a step I know how to run."
            )
        if step["op"] == "field" and step["attribute"] not in fields.FIELDS:
            # A field reads only what the row already holds. An attribute that is
            # not in the registry cannot be read straight off the record, so the
            # plan is rejected rather than guessed (the planner falls back to
            # extract/enrich for it on a re-plan).
            raise PivotError(
                f"The plan reads a field '{step['attribute']}' I do not know how "
                "to read straight from your items."
            )
        if step["op"] in ("enrich", "filter") and index == 0:
            raise PivotError(
                "The plan starts by working from a value it has not read yet, but the "
                "first step has to read the value from the item itself: extract it from "
                "the text, or read a stored field."
            )
    # A `filter` prunes the set, it does not produce a group key, so it can never be the
    # last step - the last step is what the groups are keyed by. When the model ends on a
    # filter, drop it: the step before it holds the real grouping attribute, and dropping
    # a trailing filter is more useful than refusing the whole plan.
    while len(steps) > 1 and steps[-1]["op"] == "filter":
        steps.pop()
    spec["group_by"] = steps[-1]["attribute"]
    # `group_by` now equals the last non-filter step's attribute, always runnable.
    assert spec["group_by"] == steps[-1]["attribute"], "group_by must equal the last step"


def _plan_validation_failure(exc: Exception) -> bool:
    """True when a plan call failed because the model's reply did not validate.

    The provider wraps every failure in ProviderError, translating the cause to a
    sentence; the cause chain still carries the pydantic ValidationError that
    distinguishes "the model answered in the wrong shape" from "the endpoint is
    down". Only the former gets a corrective retry.
    """
    from pydantic import ValidationError

    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, ValidationError):
            return True
        cause = cause.__cause__
    return False
