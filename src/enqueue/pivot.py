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

from . import db  # noqa: F401 - used by later phases (run)
from . import derive  # noqa: F401 - used by run() (P4.2)
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
