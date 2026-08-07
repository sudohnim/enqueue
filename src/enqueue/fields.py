"""The `field` op: attributes read straight from an artifact's own row.

A pivot can produce an attribute three ways. `extract` reads it from the
artifact's text (one model call per artifact, grounded), `enrich` infers it
from a prior value (one model call per distinct value, not grounded), and
`field` reads it from the artifact's own structured metadata - its kind, the
site it came from, when it was saved. `field` is the third: zero model calls,
the most grounded of the three, because it is literally the user's stored
data.

The rule this module exists to serve: a `field` reads only what the row
already holds - it never invents. The set of readable fields is a fixed
registry of real columns and trivial derivations of them (a URL's host, a
timestamp's month). No field guesses, infers, or calls a model; a request for
an attribute not in the registry is not a `field` step, and the planner falls
back to `extract`/`enrich`. `field` is the grounded floor of the pivot engine
exactly as `answer` is the grounded floor of the dispatcher.

Nothing here hardcodes a domain vocabulary: the *values* come from the data,
never from this module. A resolver returning "" is legal and becomes the
"not determined" bucket downstream, exactly like an empty extract - it is
never dropped.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Field:
    """One attribute the engine can read straight off an artifact row.

    `describe` is the one line the planner prompt shows the model. `resolve`
    maps one artifact row to its label: pure, model-free, and total - any
    row yields a string, "" meaning "not determined". The resolver never
    raises: a missing url or a malformed timestamp reads as "" or a best
    effort, and the caller groups whatever comes back.
    """

    name: str
    describe: str
    resolve: Callable[[Mapping[str, object]], str]


def _resolve_kind(row: Mapping[str, object]) -> str:
    """note | link | pdf | image | file - the artifact's own kind column."""
    return str(row["kind"])


def _resolve_source(row: Mapping[str, object]) -> str:
    """The host of source_url; "" when the row has no url."""
    url = row["source_url"]
    if not url:
        return ""
    return urlsplit(str(url)).hostname or ""


def _resolve_captured(row: Mapping[str, object]) -> str:
    """The YYYY-MM month the artifact was saved, from created_at."""
    return str(row["created_at"])[:7]


def _resolve_title(row: Mapping[str, object]) -> str:
    """The artifact's own title - the one place a named work (a book, a paper)
    is identified. It is a column, not an inference, so reading it is a `field`,
    not an `extract`: the value is the user's stored data, no model needed. It is
    the grounded seed for an `enrich` chain about the named thing - title to
    author, author to region - where the world knowledge lives in enrich, never
    here (a `title` field reads the title, it never infers anything from it)."""
    return str(row["title"] or "")


# The registry is the source of truth for readable field names. Nothing else
# in the planner or run() names a field specially: a fourth field (file size,
# page-count buckets) is one entry here and one line in derive.field's SELECT,
# nothing more. The *values* are the data's own; only the read is listed.
FIELDS: dict[str, Field] = {
    "kind": Field(
        name="kind",
        describe="what kind of thing it is (note, link, pdf, image, file)",
        resolve=_resolve_kind,
    ),
    "source": Field(
        name="source",
        describe="the website a link or file came from",
        resolve=_resolve_source,
    ),
    "captured": Field(
        name="captured",
        describe="the month it was saved",
        resolve=_resolve_captured,
    ),
    "title": Field(
        name="title",
        describe="the title of the thing - the name of a book, paper, or page. "
        "Read this (do not extract) when grouping by a property of the named "
        "work itself (its author, origin, era), then enrich from it.",
        resolve=_resolve_title,
    ),
}
