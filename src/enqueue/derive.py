"""Derived values for the pivot engine.

A pivot groups artifacts by an attribute the model computes. An attribute has
two ways to be produced: `extract` reads it from one artifact's content
(grounded), and `enrich` infers it from another value using world knowledge
(not grounded). Every derived value is cached in `derived_values` so a pivot
re-run pays for model calls only for artifacts or values never seen before.

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
