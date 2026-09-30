"""Model re-ranking: the search model reads the top results and puts the best first.

Fusion ranks by where each leg placed a hit, never by whether it answers the query;
a model reading the query next to each candidate's title, snippet and facets judges
fit far better (Anthropic's contextual-retrieval study measured its biggest single
gain from this step). One search-model call per distinct (query, candidate set,
model), cached in `derived_values` (scope 'model_rank'). Opt-in through the
`search_model_rank` setting, because it adds a model round trip to a search.

Fail-open: any failure, or an id the model leaves out, keeps the fused order.
"""

from __future__ import annotations

import hashlib
import json
from sqlite3 import OperationalError

from pydantic import BaseModel

from .. import db

# How many fused results the model reads. Anything below keeps its fused order.
WINDOW = 20


class _RawOrder(BaseModel):
    ids: list[str]


def _key(ids: list[str]) -> str:
    return hashlib.sha1(json.dumps(sorted(ids)).encode()).hexdigest()[:16]


def _read(query: str, key: str, model: str) -> list[str] | None:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT value FROM derived_values WHERE scope = 'model_rank' AND subject = ?"
            " AND attribute = ? AND model_version = ?",
            (query, key, model),
        ).fetchone()
    except OperationalError:
        return None
    finally:
        conn.close()
    return json.loads(row["value"]) if row else None


def _store(query: str, key: str, model: str, ids: list[str]) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO derived_values"
            " (scope, subject, attribute, value, grounded, source, model_version, created_at)"
            " VALUES ('model_rank', ?, ?, ?, 0, 'model', ?, ?)",
            (query, key, json.dumps(ids), model, db.now()),
        )


def apply_order(hits: list[dict], ids: list[str]) -> list[dict]:
    """`hits` re-ordered by `ids`: named hits first in that order, the rest after in
    their original order. Ids that are not in `hits` are ignored."""
    by_id = {h["artifact_id"]: h for h in hits}
    first = [by_id[i] for i in dict.fromkeys(ids) if i in by_id]
    named = {h["artifact_id"] for h in first}
    return first + [h for h in hits if h["artifact_id"] not in named]


def _prompt(query: str, hits: list[dict]) -> str:
    from .candidates import _facets_for_judge

    facets = _facets_for_judge([h["artifact_id"] for h in hits])
    blocks = []
    for h in hits:
        block = f"[id:{h['artifact_id']}] [{h.get('kind', 'artifact')}] {h.get('title') or ''}"
        if h.get("snippet"):
            block += f"\n{h['snippet']}"
        if facets.get(h["artifact_id"]):
            block += "\nfacets: " + " | ".join(facets[h["artifact_id"]][:6])
        blocks.append(block)
    return f"Query: {query}\n\nSaved items:\n\n" + "\n\n".join(blocks)


def order(query: str, hits: list[dict]) -> list[dict]:
    """The top WINDOW of `hits` in the search model's order, the rest unchanged."""
    from ..prompts import MODEL_RANK
    from ..providers.base import get_provider

    head, tail = hits[:WINDOW], hits[WINDOW:]
    try:
        provider = get_provider(role="search")
        model = provider.model
    except Exception:  # noqa: BLE001 - ranking is an enhancement, never a gate
        return hits
    # A remote model never sees a local-only artifact (privacy.py): those keep their
    # places, and the model orders the rest around them.
    from .. import privacy

    shown = privacy.shareable(head, provider)
    if len(shown) < 2:
        return hits
    query = " ".join(query.split())
    ids = [h["artifact_id"] for h in shown]
    key = _key(ids)
    cached = _read(query, key, model)
    if cached is None:
        try:
            raw = provider.complete(
                system=MODEL_RANK, user=_prompt(query, shown), response_model=_RawOrder
            )
        except Exception:  # noqa: BLE001 - the fused order stands
            return hits
        cached = [i for i in dict.fromkeys(raw.ids) if i in ids]
        _store(query, key, model, cached)
    ranked = iter(apply_order(shown, cached))
    kept = {h["artifact_id"] for h in shown}
    return [next(ranked) if h["artifact_id"] in kept else h for h in head] + tail


def enabled() -> bool:
    """Whether /search re-ranks with the search model (the `search_model_rank` setting)."""
    from .. import settings

    return str(settings.get("search_model_rank")).lower() in ("on", "true", "1")
