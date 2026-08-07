"""Derived values for the pivot engine.

A pivot groups artifacts by an attribute the model computes. An attribute has
three ways to be produced: `extract` reads it from one artifact's content
(grounded), `enrich` infers it from another value using world knowledge
(not grounded), and `field` reads it straight from the artifact's own row -
its kind, the site it came from, when it was saved - with zero model calls
and a `grounded` flag that is always true, because the value is literally the
user's stored data. `extract` and `enrich` results are cached in
`derived_values` so a pivot re-run pays for model calls only for artifacts or
values never seen before; a `field` read is never cached, because it is a
free SQL read and caching would risk serving a stale label after the row
changes.

Two rules from the plan hold here:

1. Nothing is hardcoded to a domain. Attribute names, instructions, and values
   are parameters that arrive at runtime.
2. An inferred value is never dressed as the user's data. Every derived value
   carries a `grounded` flag: true when it came from the artifact's own content,
   false when it came from the model's world knowledge. The flag travels with
   the value everywhere.

A user correction (`source='user'`) always wins over a model row on read.
"""

from __future__ import annotations

import json  # noqa: F401 - used by later phases (prompt payloads)
import uuid  # noqa: F401 - used by later phases
from datetime import datetime, timezone

from pydantic import BaseModel

from . import db
from .providers.base import get_provider  # noqa: F401 - used by later phases


class _One(BaseModel):
    value: str  # the derived value, or "" when there is none


class _Buckets(BaseModel):
    mapping: dict[str, str]  # raw value -> canonical bucket name


def _now() -> str:
    """Return the current time as an ISO-8601 UTC string."""
    return datetime.now(timezone.utc).isoformat()


def _read(scope: str, subject: str, attribute: str) -> dict | None:
    """Return the cached derived value, or None when nothing is cached.

    The cache can hold two rows for one (scope, subject, attribute): the model's
    guess and a user correction. The correction always wins (rule 2: the
    director beats the curator), so it is preferred on read.

    Returns {"value", "grounded", "source"}. The read connection is closed in a
    finally, whatever happens.
    """
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT value, grounded, source FROM derived_values"
            " WHERE scope = ? AND subject = ? AND attribute = ?"
            " ORDER BY CASE source WHEN 'user' THEN 0 ELSE 1 END"
            " LIMIT 1",
            (scope, subject, attribute),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {"value": row["value"], "grounded": bool(row["grounded"]), "source": row["source"]}


def _write(
    scope: str,
    subject: str,
    attribute: str,
    value: str,
    grounded: bool,
    source: str,
    model_version: str,
) -> None:
    """Store a derived value, replacing any row for the same cache key.

    INSERT OR REPLACE keys on (scope, subject, attribute, source), so a user
    correction and a model row for the same key never coexist: writing one
    replaces the other. The write and its commit happen inside one
    db.transaction().
    """
    with db.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO derived_values"
            " (scope, subject, attribute, value, grounded, source, model_version, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                scope,
                subject,
                attribute,
                value,
                1 if grounded else 0,
                source,
                model_version,
                _now(),
            ),
        )


def extract(artifact_id: str, attribute: str, instruction: str) -> dict:
    """Derive one attribute from ONE artifact's content. Grounded.

    Cache-first: a row for ('artifact', artifact_id, attribute) is returned
    without a model call, so a re-run pays only for artifacts never seen before
    and a user correction always wins (rule 2). Otherwise the artifact text is
    read, the model pulls the attribute from it, and the result is cached under
    source='model'. A model failure returns an empty value with the error and is
    never cached: the caller can handle it and a wrong value is never written
    down as if it had been read.
    """
    attribute = attribute.strip().lower()
    cached = _read("artifact", artifact_id, attribute)
    if cached is not None:
        return cached

    from .prompts import EXTRACT_ATTRIBUTE
    from .retrieve.candidates import artifact_text

    conn = db.get_conn()
    try:
        text = artifact_text(conn, artifact_id, max_words=400)
    finally:
        conn.close()

    try:
        provider = get_provider()
        result = provider.complete(
            system=EXTRACT_ATTRIBUTE.format(
                attribute=attribute, instruction=instruction, text=text
            ),
            user="",
            response_model=_One,
        )
    except Exception as exc:  # noqa: BLE001 - the caller reports and continues
        return {"value": "", "grounded": True, "source": "model", "error": str(exc)}

    value = result.value
    _write(
        "artifact",
        artifact_id,
        attribute,
        value,
        grounded=True,
        source="model",
        model_version=provider.model,
    )
    return {"value": value, "grounded": True, "source": "model"}


def enrich(input_value: str, attribute: str, instruction: str) -> dict:
    """Derive one attribute from a VALUE using world knowledge. Not grounded.

    Same shape as extract but the subject is the exact input value string and the
    scope is 'value', so the cache is per value rather than per artifact: many
    artifacts that share one input value cost one lookup, not many. The result is
    never grounded (rule 2): the value came from the model's knowledge of the
    world, not from the artifact's content, and that distinction travels with it.

    An empty input value returns an empty, ungrounded result without a model
    call. A model failure returns an empty, ungrounded value with the error and
    is never cached.
    """
    if not input_value:
        return {"value": "", "grounded": False}

    attribute = attribute.strip().lower()
    cached = _read("value", input_value, attribute)
    if cached is not None:
        return cached

    from .prompts import ENRICH_ATTRIBUTE

    try:
        provider = get_provider()
        result = provider.complete(
            system=ENRICH_ATTRIBUTE.format(
                attribute=attribute, instruction=instruction, value=input_value
            ),
            user="",
            response_model=_One,
        )
    except Exception as exc:  # noqa: BLE001 - the caller reports and continues
        return {"value": "", "grounded": False, "source": "model", "error": str(exc)}

    value = result.value
    _write(
        "value",
        input_value,
        attribute,
        value,
        grounded=False,
        source="model",
        model_version=provider.model,
    )
    return {"value": value, "grounded": False, "source": "model"}


# The metadata columns the field registry may read. `body` is deliberately
# excluded: a field read must stay a cheap SQL read, and pulling every note's
# markdown to read its kind would miss the entire point of the op. A new field
# that reads a column already listed here is a one-entry registry add; a field
# on a column not listed adds it to the SELECT in the same change.


def field(artifact_id: str, field_name: str) -> dict:
    """Read one attribute straight from the artifact's own row. Grounded.

    The value is the user's stored data, so this is the most grounded read the
    engine has - but a user correction still wins (rule 2: the director beats
    the curator), exactly as it does for extract and enrich. Nothing is cached:
    a field read is a free SQL read, and caching would risk serving a stale
    label after the row changes.

    An unknown field_name raises KeyError. The planner's validation is supposed
    to prevent it reaching here; this is the belt, not the braces.
    """
    from . import fields

    attribute = field_name.strip().lower()
    corrected = _read("artifact", artifact_id, attribute)
    if corrected is not None and corrected["source"] == "user":
        return {"value": corrected["value"], "grounded": True, "source": "field"}

    if attribute not in fields.FIELDS:
        raise KeyError(attribute)

    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT kind, title, source_url, mime, filename, created_at, updated_at,"
            " local_only, status, pages FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        # A stale index id (an artifact deleted after the subset was resolved) has
        # no row to read. It reads as empty - the "not determined" bucket - rather
        # than raising, so one dangling id never crashes a whole pivot run.
        return {"value": "", "grounded": True, "source": "field"}

    return {
        "value": fields.FIELDS[attribute].resolve(row),
        "grounded": True,
        "source": "field",
    }


def bucketize(values: list[str], instruction: str) -> dict:
    """Collapse many raw values into fewer canonical buckets.

    De-duplicates and sorts the values; with zero or one distinct values the
    mapping is the identity. Otherwise the model groups them once, per the
    instruction, and the result is NOT cached: this is one call whose input set
    changes between pivots. Every distinct value maps to a bucket, defaulting to
    itself when the model omits it, so downstream grouping never hits a missing
    key. On model failure the identity map is returned with an 'error' key set,
    so a slow or wrong model never crashes a pivot.
    """
    distinct = sorted(set(values))
    if len(distinct) <= 1:
        return {value: value for value in distinct}

    from .prompts import BUCKETIZE

    try:
        provider = get_provider()
        result = provider.complete(
            system=BUCKETIZE.format(instruction=instruction, values="\n".join(distinct)),
            user="",
            response_model=_Buckets,
        )
    except Exception as exc:  # noqa: BLE001 - the caller reports and continues
        mapping = {value: value for value in distinct}
        mapping["error"] = str(exc)
        return mapping

    mapping = dict(result.mapping)
    for value in distinct:
        mapping.setdefault(value, value)
    return mapping


def override(scope: str, subject: str, attribute: str, value: str) -> dict:
    """Write a user correction for a derived value. source='user', model_version=''.

    This is how a wrong value gets fixed. The user's value is written with
    source='user', which always wins over the model row on read (rule 2: the
    director beats the curator). The grounded flag is carried over unchanged from
    the model row being corrected (or defaults to grounded when no model row
    exists): the user is correcting the value, not the provenance, so whether the
    original came from the artifact's content or from world knowledge stays
    honest.

    Returns the stored row.
    """
    attribute = attribute.strip().lower()

    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT grounded FROM derived_values"
            " WHERE scope = ? AND subject = ? AND attribute = ? AND source = 'model'",
            (scope, subject, attribute),
        ).fetchone()
    finally:
        conn.close()
    grounded = bool(row["grounded"]) if row is not None else True

    _write(
        scope,
        subject,
        attribute,
        value,
        grounded=grounded,
        source="user",
        model_version="",
    )

    conn = db.get_conn()
    try:
        stored = conn.execute(
            "SELECT scope, subject, attribute, value, grounded, source, model_version, created_at"
            " FROM derived_values WHERE scope = ? AND subject = ? AND attribute = ? AND source = 'user'",
            (scope, subject, attribute),
        ).fetchone()
    finally:
        conn.close()
    if stored is None:  # pragma: no cover - the write above just happened
        raise RuntimeError("override did not persist")
    return {
        "scope": stored["scope"],
        "subject": stored["subject"],
        "attribute": stored["attribute"],
        "value": stored["value"],
        "grounded": bool(stored["grounded"]),
        "source": stored["source"],
        "model_version": stored["model_version"],
        "created_at": stored["created_at"],
    }
