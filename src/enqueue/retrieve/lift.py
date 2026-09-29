"""Query lifting: rewrite a search into facet-style claims before matching facets.

Facets are abstract claims ("Structures last by yielding under stress rather than
resisting it."); searches are short topics ("software that degrades gracefully").
The two sit in different registers, so their embeddings meet poorly. The search
model restates the query as 2-4 claims in the facets' own register, each of which
also searches the facet index (retrieve/candidates.py). One model call per distinct
query and search model, cached in `derived_values` (scope 'query_lift').

Fail-soft: any failure means no lifts, and search runs exactly as it would have.
"""

from __future__ import annotations

import json
from sqlite3 import OperationalError

from pydantic import BaseModel

from .. import db

MAX_CLAIMS = 4
# Queries shorter than this are names or titles, which the lexical legs handle.
MIN_WORDS = 3


class _RawLift(BaseModel):
    claims: list[str]


def _read(query: str, model: str) -> list[str] | None:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT value FROM derived_values WHERE scope = 'query_lift' AND subject = ?"
            " AND attribute = 'claims' AND model_version = ?",
            (query, model),
        ).fetchone()
    except OperationalError:
        return None
    finally:
        conn.close()
    return json.loads(row["value"]) if row else None


def store(query: str, model: str, claims: list[str]) -> None:
    """Cache the claims for (query, model). Also how the eval preloads its fixture."""
    with db.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO derived_values"
            " (scope, subject, attribute, value, grounded, source, model_version, created_at)"
            " VALUES ('query_lift', ?, 'claims', ?, 0, 'model', ?, ?)",
            (query, json.dumps(claims), model, db.now()),
        )


def _clean(claims: list[str]) -> list[str]:
    out = []
    for c in claims:
        c = " ".join((c or "").split())
        if 4 <= len(c.split()) <= 30 and c not in out:
            out.append(c)
    return out[:MAX_CLAIMS]


def lift(query: str) -> list[str]:
    """Facet-style claims for `query`, from cache or one search-model call. [] on failure."""
    from ..prompts import QUERY_LIFT
    from ..providers.base import get_provider

    query = " ".join(query.split())
    if len(query.split()) < MIN_WORDS:
        return []
    try:
        provider = get_provider(role="search")
        model = provider.model
    except Exception:  # noqa: BLE001 - lifting is an enhancement, never a gate
        return []
    cached = _read(query, model)
    if cached is not None:
        return cached
    try:
        raw = provider.complete(system=QUERY_LIFT, user=query, response_model=_RawLift)
    except Exception:  # noqa: BLE001 - no lifts; search proceeds unchanged
        return []
    claims = _clean(raw.claims)
    store(query, model, claims)
    return claims


def enabled_for_search() -> bool:
    """Whether /search lifts queries (the `search_lift` setting). Chat always does."""
    from .. import settings

    return str(settings.get("search_lift")).lower() in ("on", "true", "1")
