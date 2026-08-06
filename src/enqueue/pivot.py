"""Pivot: group a subset of the library by a computed attribute.

A pivot is a short pipeline of `derive` primitives - `extract` reads an
attribute from one artifact's content (grounded), `enrich` infers it from
another value using world knowledge (not grounded) - ending in a group key,
then a plain code-level group-by. The model does only the per-item judgments;
ordinary code does the selecting, caching, grouping, and rendering. The
library never groups itself in one giant prompt.

Nothing here is hardcoded to a domain. The subset, the attribute names, the
instructions, and the group key are parameters that arrive at runtime. Every
derived value carries its `grounded` flag through `derive` and into the
response, so an inferred value is never dressed as the user's data.
"""

from __future__ import annotations

import re
from collections import defaultdict

from . import db, derive  # noqa: F401 - db for later phases; derive used by run()
from .providers.base import get_provider  # noqa: F401 - used by the planner (P4.4)

MAX_PIVOT_ARTIFACTS = 200


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


def run(spec: dict) -> dict:
    """Execute a pivot spec end to end.

    The spec is a plain dict (see the plan): a subset, a chain of steps whose
    first op is always `extract` and whose later ops are `enrich`, a group_by
    attribute, and an optional bucketize pass. The model does only the per-item
    judgments through `derive`; selecting, caching, grouping, and rendering are
    ordinary code. The library is never grouped in one giant prompt.

    The call budget is the plan's bounded shape: `extract` runs per artifact
    (cached per artifact), `enrich` runs once per DISTINCT current value
    (cached per value), never once per artifact. Every `derive` result is
    cached, so re-running the same spec makes model calls only for artifacts or
    values never seen before (resumable and cheap on re-run).

    The final key can be the empty string - an artifact whose derived value was
    "none found" - and it is never dropped or hidden: it becomes the '' bucket,
    rendered as "not determined" by the UI (rule 2, and the bucketize pass
    never sees it, so the model cannot merge it away).
    """
    ids, truncated = resolve_subset(spec["subset"])

    steps = spec["steps"]
    if not steps:
        raise ValueError("a pivot spec needs at least one step")

    # The first step is always an extract: one judgment per artifact.
    key_of: dict[str, str] = {}
    first = steps[0]
    for artifact_id in ids:
        key_of[artifact_id] = derive.extract(artifact_id, first["attribute"], first["instruction"])[
            "value"
        ]

    any_enrich = False
    for step in steps[1:]:
        any_enrich = True
        # One enrich call per DISTINCT current value: the per-value cache keeps
        # the call count bounded when many artifacts share a value.
        remap = {
            value: derive.enrich(value, step["attribute"], step["instruction"])["value"]
            for value in sorted({key_of[artifact_id] for artifact_id in ids})
        }
        for artifact_id in ids:
            key_of[artifact_id] = remap.get(key_of[artifact_id], "")

    if spec.get("bucketize"):
        mapping = derive.bucketize(
            [key for key in sorted(set(key_of.values())) if key],
            spec.get("bucketize_instruction", ""),
        )
        for artifact_id in ids:
            key_of[artifact_id] = mapping.get(key_of[artifact_id], key_of[artifact_id])

    grouped: dict[str, list[str]] = defaultdict(list)
    for artifact_id in ids:
        grouped[key_of[artifact_id]].append(artifact_id)

    groups = [
        {"key": key, "artifact_ids": artifact_ids, "grounded": not any_enrich}
        for key, artifact_ids in grouped.items()
    ]
    groups.sort(key=lambda group: len(group["artifact_ids"]), reverse=True)

    return {"groups": groups, "truncated": truncated, "group_by": spec["group_by"]}
