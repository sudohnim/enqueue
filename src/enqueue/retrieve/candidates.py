"""Search: hybrid retrieval rolled up to one row per artifact.

`candidates` ranks artifact ids across chunks, facets and entities. `search_results`
is the /search surface. Design notes: AGENTS.md "Retrieval architecture".
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from functools import lru_cache
from sqlite3 import OperationalError

from pydantic import BaseModel

from .. import config, db
from ..index.store import get_store
from ..providers.base import get_provider

# R.7 fuzzy leg: min SequenceMatcher ratio for a typo match, and its score (RRF k=60 scale).
FUZZY_RATIO = 0.75
FUZZY_BASE_SCORE = 0.02

# R.8 recency: score * (1 + RECENCY_WEIGHT * exp(-age_days / RECENCY_TAU_DAYS)).
RECENCY_WEIGHT = 0.5
RECENCY_TAU_DAYS = 30

# Q.3 relevance floor bars, on the true-cosine scale. Between them is the gray zone.
KEEP_ABOVE = 0.75
DROP_BELOW = 0.45


def _floor_verdict(hit: dict) -> str:
    """ "keep", "drop", or "gray" for one hit under the Q.3 floor."""
    if hit.get("had_lexical_hit"):
        return "keep"
    sim = hit.get("dense_similarity", 0.0)
    if sim >= KEEP_ABOVE:
        return "keep"
    if sim < DROP_BELOW:
        return "drop"
    return "gray"


def _apply_floor(query: str, hits: list[dict]) -> list[dict]:
    """Drop floor failures, judge the gray zone in one call. Order is preserved."""
    gray = [h for h in hits if _floor_verdict(h) == "gray"]
    kept_gray = judge_gray_zone(query, gray) if gray else None
    out = []
    for h in hits:
        verdict = _floor_verdict(h)
        if verdict == "drop":
            continue
        if verdict == "gray" and kept_gray is not None and h["artifact_id"] not in kept_gray:
            continue
        out.append(h)
    return out


class _GrayZoneVerdict(BaseModel):
    id: str  # artifact_id
    relevant: bool


class _GrayZoneResponse(BaseModel):
    verdicts: list[_GrayZoneVerdict]


_GRAY_JUDGE_SYSTEM = """\
You are the gate on a person's own second brain: they searched what they saved,
and the vector index returned the items below because they sit near the query.
For each one, say whether it GENUINELY matches the query or is only loosely /
coincidentally similar.

The query, then each saved item as:

{index}. [id:{id}] [{kind}] {title}
{snippet}

Some items also list `facets` - one-line abstractions of what the item is about,
written from its full text. They are the most reliable signal of subject: a book
note whose facets are all about leadership and debt does not match a query about
language models, however the snippet reads. Weigh the facets over the raw snippet.

A genuine match has real topical overlap with the query - it actually bears on
what was asked. An item about a different subject that only happens to sit
nearby in vector space is NOT a match. When in doubt, prefer "not relevant": a
missed note costs nothing, while a confident wall of unrelated notes is the
failure this gate exists to stop.

Return one verdict per item, echoing the exact [id:...] shown above.
"""


def _facets_for_judge(artifact_ids: list[str]) -> dict[str, list[str]]:
    """Facet statements per artifact, for the gray-zone judge prompt."""
    if not artifact_ids:
        return {}
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT artifact_id, statement FROM facets"
            " WHERE artifact_id IN (SELECT value FROM json_each(?))"
            " ORDER BY level",
            (json.dumps(artifact_ids),),
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, list[str]] = {}
    for row in rows:
        out.setdefault(row["artifact_id"], []).append(row["statement"])
    return out


def _judge_cache_read(query: str, artifact_id: str, model_version: str) -> bool | None:
    """Cached gray-zone verdict, or None. A missing derived_values table reads as no cache."""
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT value FROM derived_values"
            " WHERE scope = 'gray_judge' AND subject = ? AND attribute = ?"
            " AND source = 'model' AND model_version = ?",
            (query, artifact_id, model_version),
        ).fetchone()
    except OperationalError:
        return None
    finally:
        conn.close()
    if row is None:
        return None
    return row["value"] == "1"


def _judge_cache_write(query: str, artifact_id: str, relevant: bool, model_version: str) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO derived_values"
            " (scope, subject, attribute, value, grounded, source, model_version, created_at)"
            " VALUES ('gray_judge', ?, ?, ?, 1, 'model', ?, ?)",
            (query, artifact_id, "1" if relevant else "0", model_version, db.now()),
        )


def judge_gray_zone(query: str, candidates: list[dict]) -> set[str]:
    """Q.3b: one batched model call over gray-zone hits. Returns the kept artifact ids.

    Fail-open: a provider error, or an item the answer does not cover, is kept.
    """
    if not candidates:
        return set()
    try:
        provider = get_provider(role="search")
        model_version = provider.model
    except Exception:  # noqa: BLE001 - fail-open is the contract
        return {h["artifact_id"] for h in candidates}

    kept: set[str] = set()
    unjudged: list[dict] = []
    for hit in candidates:
        aid = hit["artifact_id"]
        cached = _judge_cache_read(query, aid, model_version)
        if cached:
            kept.add(aid)
        elif cached is None:
            unjudged.append(hit)
    if not unjudged:
        return kept

    facets_by_aid = _facets_for_judge([h["artifact_id"] for h in unjudged])
    lines = []
    for idx, hit in enumerate(unjudged, 1):
        block = (
            f"{idx}. [id:{hit['artifact_id']}] [{hit.get('kind', 'artifact')}] {hit['title']}\n"
            f"{hit['snippet']}"
        )
        facets = facets_by_aid.get(hit["artifact_id"])
        if facets:
            block += "\nfacets: " + " | ".join(facets)
        lines.append(block)
    user = f"Query: {query}\n\nSaved items to judge:\n\n" + "\n\n".join(lines)

    try:
        result = provider.complete(
            system=_GRAY_JUDGE_SYSTEM,
            user=user,
            response_model=_GrayZoneResponse,
        )
        verdicts = result.verdicts if result is not None else []
        covered: set[str] = set()
        by_aid = {h["artifact_id"]: h for h in unjudged}
        for verdict in verdicts:
            if verdict.id not in by_aid:
                continue  # not in the batch: ignore, never cache
            covered.add(verdict.id)
            _judge_cache_write(query, verdict.id, verdict.relevant, model_version)
            if verdict.relevant:
                kept.add(verdict.id)
        kept.update(aid for aid in by_aid if aid not in covered)
    except Exception:  # noqa: BLE001 - fail-open is the contract
        kept.update(h["artifact_id"] for h in unjudged)
    return kept


def _age_days(updated_at: str) -> float:
    """Days since `updated_at`, clamped at zero. Accepts sqlite and ISO formats."""
    try:
        dt = datetime.fromisoformat(updated_at.replace(" ", "T"))
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)


def _recency_score(score: float, age_days: float) -> float:
    return score * (1.0 + RECENCY_WEIGHT * math.exp(-age_days / RECENCY_TAU_DAYS))


# R.9 opt-in cross-encoder rerank (config.SEARCH_RERANK).
_RERANK_MODEL = "BAAI/bge-reranker-base"
_RERANK_WINDOW = 30
_RERANK_LAST = -math.inf


@lru_cache(maxsize=1)
def _cross_encoder():
    """The shared cross-encoder, loaded lazily. CPU only: see AGENTS.md (CoreML leak)."""
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(model_name=_RERANK_MODEL, providers=["CPUExecutionProvider"])


def _rerank(q: str, fused: list[dict]) -> list[dict]:
    """Re-order by cross-encoder score. Any failure keeps the fused order."""
    if not fused:
        return fused
    conn = db.get_conn()
    try:
        batched = artifact_texts(conn, [h["artifact_id"] for h in fused])
        texts = [batched[h["artifact_id"]] for h in fused]
    finally:
        conn.close()
    try:
        scores = list(_cross_encoder().rerank(q, texts))
    except Exception:  # noqa: BLE001 - a reranker failure degrades to the fused order
        return fused
    ordered = sorted(
        zip(fused, scores, strict=True),
        key=lambda fs: fs[1] if fs[1] is not None else _RERANK_LAST,
        reverse=True,
    )
    return [f for f, _ in ordered]


def _fuzzy_ratio(query: str, candidate: str, floor: float = 0.0) -> float:
    """Best SequenceMatcher ratio over the whole string and each query-length word window.

    Comparisons whose cheap upper bound (length, shared characters) cannot reach
    `floor` or beat the best so far are skipped. The result is exact at or above
    `floor`; below it, it only stays below. floor=0 is always exact.
    """
    ql, cl = query.lower(), candidate.lower()
    q_len = len(ql)
    q_chars = Counter(ql)
    best = 0.0

    def consider(text: str) -> None:
        nonlocal best
        total = q_len + len(text)
        if not total:
            best = max(best, 1.0)
            return
        bar = max(best, floor)
        if 2.0 * min(q_len, len(text)) / total < bar:
            return
        shared = sum((q_chars & Counter(text)).values())
        if 2.0 * shared / total < bar:
            return
        best = max(best, SequenceMatcher(None, ql, text).ratio())

    consider(cl)
    q_words = ql.split()
    c_words = cl.split()
    n = len(q_words)
    if n and len(c_words) > n:
        for i in range(len(c_words) - n + 1):
            consider(" ".join(c_words[i : i + n]))
    return best


def _fuzzy_hits(query: str, limit: int) -> list[dict]:
    """R.7: typo matches over titles, entity names and current annotations.

    A full Python scan, so callers gate it behind `_needs_fuzzy`.
    """
    q = query.strip()
    if len(q) < 3:
        return []
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, title FROM artifacts"
            " WHERE deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL"
        ).fetchall()
        erows = conn.execute("SELECT artifact_id, entity FROM entities").fetchall()
        arows = conn.execute(
            "SELECT artifact_id, text FROM annotations a"
            " WHERE NOT EXISTS (SELECT 1 FROM annotations b WHERE b.supersedes_id = a.id)"
        ).fetchall()
    finally:
        conn.close()

    best: dict[str, tuple[float, str]] = {}
    for row in rows:
        _fuzzy_update(best, row["id"], row["title"], q)
    for row in erows:
        _fuzzy_update(best, row["artifact_id"], row["entity"], q)
    for row in arows:
        _fuzzy_update(best, row["artifact_id"], row["text"], q)

    ranked = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)[:limit]
    return [
        {
            "artifact_id": aid,
            "score": FUZZY_BASE_SCORE * ratio,
            "why": "fuzzy",
            "matched": matched,
        }
        for aid, (ratio, matched) in ranked
    ]


def _fuzzy_update(best: dict[str, tuple[float, str]], aid: str, text: str, q: str) -> None:
    ratio = _fuzzy_ratio(q, text, floor=FUZZY_RATIO)
    if ratio >= FUZZY_RATIO and (aid not in best or ratio > best[aid][0]):
        best[aid] = (ratio, text)


def _merge_fuzzy(results: list[dict], fuzzy: list[dict], limit: int) -> list[dict]:
    """Merge fuzzy hits into the hybrid rollup. A fuzzy hit wins only when it scores higher."""
    if not fuzzy:
        return results
    by_aid = {h["artifact_id"]: h for h in results}
    missing = [f["artifact_id"] for f in fuzzy if f["artifact_id"] not in by_aid]
    meta: dict = {}
    if missing:
        conn = db.get_conn()
        try:
            meta = {
                r["id"]: r
                for r in conn.execute(
                    "SELECT id, title, kind FROM artifacts"
                    " WHERE id IN (SELECT value FROM json_each(?))"
                    " AND deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL",
                    (json.dumps(missing),),
                ).fetchall()
            }
        finally:
            conn.close()
    for f in fuzzy:
        aid = f["artifact_id"]
        if aid in by_aid:
            if f["score"] > by_aid[aid]["score"]:
                by_aid[aid] = {**by_aid[aid], "score": f["score"], "why": "fuzzy"}
        else:
            row = meta.get(aid)
            if row is None:
                continue
            # A fuzzy match is a lexical hit for the floor; it has no dense reading.
            by_aid[aid] = {
                "score": f["score"],
                "artifact_id": aid,
                "title": row["title"],
                "kind": row["kind"],
                "why": "fuzzy",
                "snippet": " ".join(f["matched"].split())[:200],
                "dense_similarity": 0.0,
                "had_lexical_hit": True,
            }
    return sorted(by_aid.values(), key=lambda h: h["score"], reverse=True)[:limit]


def _needs_fuzzy(hybrid: list[dict]) -> bool:
    """Run the fuzzy leg only when the hybrid found nothing confident (PERF.1)."""
    return not any(
        h.get("had_lexical_hit") or h.get("dense_similarity", 0.0) >= KEEP_ABOVE for h in hybrid
    )


def _quoted_phrase(free_text: str) -> str | None:
    """R.10: the phrase when the whole query is one double-quoted phrase, else None."""
    if len(free_text) >= 2 and free_text.startswith('"') and free_text.endswith('"'):
        inner = free_text[1:-1]
        if inner.strip():
            return inner
    return None


def _word_form(text: str) -> str:
    """Lowercase words joined by single spaces: punctuation and spacing drop out,
    as they do for the FTS tokenizers."""
    return " ".join(re.findall(r"\w+", text.lower()))


def _exact_phrase_hits(phrase: str, limit: int) -> list[dict]:
    """R.10: artifacts containing `phrase` verbatim, via both FTS chunk tables."""
    query = f'"{phrase.replace(chr(34), chr(34) * 2)}"'
    conn = db.get_conn()
    try:
        chunk_scores: dict[str, float] = {}
        for table in ("fts_chunks", "fts_chunks_tri"):
            try:
                rows = conn.execute(
                    f"SELECT chunk_id AS id, bm25({table}) AS raw FROM {table}"
                    f" WHERE {table} MATCH ? ORDER BY bm25({table}) LIMIT ?",
                    (query, limit),
                ).fetchall()
            except OperationalError:
                continue
            for row in rows:
                score = -row["raw"]
                if row["id"] not in chunk_scores or score > chunk_scores[row["id"]]:
                    chunk_scores[row["id"]] = score
        if not chunk_scores:
            return []
        rows = conn.execute(
            "SELECT c.id, c.artifact_id, c.text, a.title, a.kind FROM chunks c"
            " JOIN artifacts a ON a.id = c.artifact_id"
            " WHERE c.id IN (SELECT value FROM json_each(?))"
            " AND a.deleted_at IS NULL AND a.vaulted_at IS NULL AND a.embedded_at IS NULL",
            (json.dumps(list(chunk_scores)),),
        ).fetchall()
        # The keyword table also indexes each chunk's model-written context; an exact
        # match must be in the chunk's own words, or it is not the verbatim needle.
        needle = _word_form(phrase)
        rows = [r for r in rows if needle in _word_form(r["text"])]
        by_artifact: dict[str, dict] = {}
        for row in rows:
            prev = by_artifact.get(row["artifact_id"])
            if prev is None or chunk_scores[row["id"]] > chunk_scores[prev["chunk_id"]]:
                by_artifact[row["artifact_id"]] = {
                    "chunk_id": row["id"],
                    "score": chunk_scores[row["id"]],
                    "artifact_id": row["artifact_id"],
                    "title": row["title"],
                    "kind": row["kind"],
                    "text": row["text"],
                }
        ranked = sorted(by_artifact.values(), key=lambda h: h["score"], reverse=True)[:limit]
        return [
            {
                "score": round(h["score"], 4),
                "artifact_id": h["artifact_id"],
                "title": h["title"],
                "kind": h["kind"],
                "why": "exact",
                "snippet": " ".join(h["text"].split())[:200],
                "dense_similarity": 0.0,
                "had_lexical_hit": True,
            }
            for h in ranked
        ]
    finally:
        conn.close()


def _pin_exact(
    exact: list[dict], results: list[dict], limit: int, tag_ids: set[str] | None = None
) -> list[dict]:
    """Put exact-phrase hits on top, deduped, honoring the tag filter."""
    if tag_ids:
        exact = [h for h in exact if h["artifact_id"] in tag_ids]
    pinned = list(exact)
    seen = {h["artifact_id"] for h in pinned}
    for h in results:
        if h["artifact_id"] not in seen:
            pinned.append(h)
    return pinned[:limit]


def _log_sub_queries(queries: list[str]) -> None:
    if len(queries) > 1:
        print(f"[search] {len(queries)} sub-queries (query expansion)", flush=True)


def hit_is_stale(conn, hit: dict, cache: dict) -> bool:
    """Whether a facet/entity hit was built from an older body or a different summary model.

    `cache` maps artifact_id to (current_body_version, current_model).
    """
    aid = hit["artifact_id"]
    if aid not in cache:
        row = conn.execute(
            "SELECT local_only,"
            " (SELECT MAX(created_at) FROM artifact_versions v"
            "  WHERE v.artifact_id = artifacts.id) AS body_version"
            " FROM artifacts WHERE id = ?",
            (aid,),
        ).fetchone()
        if row is None:
            cache[aid] = None
        else:
            from ..providers.base import get_provider

            cache[aid] = (
                row["body_version"],
                get_provider(local_only=bool(row["local_only"]), summarize=True).model,
            )
    current = cache[aid]
    if current is None:
        return True
    body_version, model = current
    return hit.get("body_version") != body_version or hit.get("model_version") != model


def _get_model(local_only: bool) -> str:
    """The SUMMARY model a facet/entity would be written with now (not the chat model)."""
    from .. import config, settings
    from ..providers.base import get_provider

    # Through get_provider first so tests can mock it.
    try:
        provider = get_provider(local_only=local_only, summarize=True)
        return provider.model
    except Exception:  # noqa: BLE001 - fall back to the raw settings read below
        pass
    if local_only:
        return config.LLM_MODEL
    return settings.get("summarize_model") or settings.get("llm_model") or config.LLM_MODEL


def _prefetch_staleness(conn, cache, ids) -> None:
    """Fill the `hit_is_stale` cache for unseen ids in one query (P.2c)."""
    unseen = list(dict.fromkeys(aid for aid in ids if aid not in cache))
    if not unseen:
        return
    rows = conn.execute(
        "SELECT id, local_only,"
        " (SELECT MAX(created_at) FROM artifact_versions v"
        "  WHERE v.artifact_id = artifacts.id) AS body_version"
        " FROM artifacts WHERE id IN (SELECT value FROM json_each(?))",
        (json.dumps(unseen),),
    ).fetchall()
    found = {row["id"]: row for row in rows}

    providers: dict[bool, str] = {}

    for aid in unseen:
        row = found.get(aid)
        if row is None:
            cache[aid] = None
            continue
        local_only = bool(row["local_only"])
        if local_only not in providers:
            providers[local_only] = _get_model(local_only)
        cache[aid] = (row["body_version"], providers[local_only])


def _weighted_hits(conn, hits, cache):
    """Yield (hit, score * trust * 2.0) for each non-stale facet/entity hit."""
    for hit in hits:
        if hit_is_stale(conn, hit, cache):
            continue
        try:
            trust = float(hit.get("trust") or 0.5)
        except (TypeError, ValueError):  # noqa: PERF203 - a bad trust value is data rot
            trust = 0.5
        yield hit, hit["score"] * trust * 2.0


def candidates(
    queries: list[str], limit: int = 150, per_query: int = 40, prefetch: int = 100
) -> list[dict]:
    """Artifact ids ranked by their best chunk, facet or entity hit across `queries`.

    Raise `prefetch` for whole-library coverage; otherwise hits past the window are unseen.
    """
    _log_sub_queries(queries)
    best: dict[str, float] = defaultdict(float)
    why: dict[str, str] = {}
    matched_facet: dict[str, str] = {}

    store = get_store()
    conn = db.get_conn()
    cache: dict = {}
    try:
        for query in queries:
            chunk_hits = store.search(store.CHUNKS, query, limit=per_query, prefetch=prefetch)
            facet_hits = store.search(store.FACETS, query, limit=per_query, prefetch=prefetch)
            entity_hits = store.search(store.ENTITIES, query, limit=per_query, prefetch=prefetch)
            _prefetch_staleness(
                conn,
                cache,
                [h["artifact_id"] for h in chunk_hits + facet_hits + entity_hits],
            )
            for hit in chunk_hits:
                aid = hit["artifact_id"]
                if hit["score"] > best[aid]:
                    best[aid] = hit["score"]
                    why[aid] = "chunk"

            for hit, score in _weighted_hits(conn, facet_hits, cache):
                aid = hit["artifact_id"]
                if score > best[aid]:
                    best[aid] = score
                    why[aid] = f"facet L{hit.get('level')}"
                    facet_id = hit.get("facet_id")
                    if facet_id:
                        matched_facet[aid] = facet_id

            for hit, score in _weighted_hits(conn, entity_hits, cache):
                aid = hit["artifact_id"]
                if score > best[aid]:
                    best[aid] = score
                    why[aid] = "entity"

        ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:limit]

        titles: dict[str, str] = {}
        if ranked:
            rows = conn.execute(
                "SELECT id, title FROM artifacts"
                " WHERE id IN (SELECT value FROM json_each(?))"
                " AND deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL",
                (json.dumps([aid for aid, _ in ranked]),),
            ).fetchall()
            titles = {row["id"]: row["title"] for row in rows}

        out = []
        for aid, score in ranked:
            title = titles.get(aid)
            if title is None:
                continue
            out.append(
                {
                    "artifact_id": aid,
                    "title": title,
                    "score": score,
                    "why": why.get(aid),
                    "matched_facet_id": matched_facet.get(aid),
                }
            )
        return out
    finally:
        conn.close()


def search_results(q: str, limit: int = 20) -> list[dict]:
    """One row per artifact for /search.

    `#tag` / `tag:x` tokens are an exact filter, never embedded. A query that is
    entirely one "quoted phrase" pins exact matches on top (R.10).
    """
    from .. import tags

    from . import lift

    free_text, tag_names = tags.parse_tags(q)
    tag_ids = tags.ids_with_all(tag_names) if tag_names else set()

    phrase = _quoted_phrase(free_text)
    query_text = phrase if phrase is not None else free_text
    exact = _exact_phrase_hits(query_text, limit) if phrase is not None else []

    # No text, no tags: the whole library, newest first (the vector store rejects empty queries).
    if not free_text and not tag_ids:
        return _all_results(limit)

    if not free_text and tag_ids:
        return _results_for_ids(tag_ids, limit)

    lifts = lift.lift(query_text) if phrase is None and lift.enabled_for_search() else []

    if tag_ids:
        # Filter a wider window so a tagged hit just past `limit` is not lost. No rerank here.
        tagged = [
            h for h in _hybrid_results(query_text, limit * 5, lifts) if h["artifact_id"] in tag_ids
        ]
        tagged = _apply_floor(query_text, tagged)
        ranked = tagged[:limit]

    elif config.SEARCH_RERANK:
        window = max(limit, _RERANK_WINDOW)
        hybrid = _hybrid_results(query_text, window, lifts)
        fuzzy = _fuzzy_hits(query_text, window) if _needs_fuzzy(hybrid) else []
        fused = _merge_fuzzy(hybrid, fuzzy, window)
        # Floor before rerank so gibberish never spends the reranker.
        fused = _apply_floor(query_text, fused)
        ranked = _rerank(query_text, fused)[:limit]

    else:
        hybrid = _hybrid_results(query_text, limit, lifts)
        fuzzy = _fuzzy_hits(query_text, limit) if _needs_fuzzy(hybrid) else []
        fused = _merge_fuzzy(hybrid, fuzzy, limit)
        ranked = _apply_floor(query_text, fused)

    if exact:
        ranked = _pin_exact(exact, ranked, limit, tag_ids)
    return ranked


def _hybrid_results(q: str, limit: int = 20, lifts: list[str] | None = None) -> list[dict]:
    """Chunk + facet + entity rollup for a free-text query, with per-leg floor signals.

    `lifts` (retrieve/lift.py) are facet-style restatements of the query; each also
    searches the facet index. Their dense similarity feeds the floor; they are never a
    lexical leg, because they are model-written text, not the person's words.
    """
    store = get_store()
    per_query = limit * 3
    prefetch = max(100, limit * 5)
    legs = {
        name: store.search_legs(name, q, limit=per_query, prefetch=prefetch)
        for name in (store.CHUNKS, store.FACETS, store.ENTITIES)
    }
    chunk_hits = legs[store.CHUNKS]["fused"]
    facet_hits = legs[store.FACETS]["fused"]
    entity_hits = legs[store.ENTITIES]["fused"]
    lift_legs = [
        store.search_legs(store.FACETS, claim, limit=per_query, prefetch=prefetch)
        for claim in lifts or []
    ]
    for ll in lift_legs:
        facet_hits = facet_hits + ll["fused"]

    # Floor signals (Q.2/Q.7): best raw cosine per artifact from the dense legs, and
    # lexical = a chunk/facet/entity KEYWORD hit. Trigram is recall only, not lexical.
    dense_sims: dict[str, float] = {}
    lexical_aids: set[str] = set()
    for hit in legs[store.CHUNKS]["dense"][:per_query]:
        aid = hit["artifact_id"]
        if hit["score"] > dense_sims.get(aid, 0.0):
            dense_sims[aid] = hit["score"]
    for hit in legs[store.CHUNKS]["keyword"][:per_query]:
        lexical_aids.add(hit["artifact_id"])
    for name in (store.FACETS, store.ENTITIES):
        for hit in legs[name]["dense"][:per_query]:
            aid = hit["artifact_id"]
            if hit["score"] > dense_sims.get(aid, 0.0):
                dense_sims[aid] = hit["score"]
        for hit in legs[name]["keyword"][:per_query]:
            lexical_aids.add(hit["artifact_id"])
    for ll in lift_legs:
        for hit in ll["dense"][:per_query]:
            aid = hit["artifact_id"]
            if hit["score"] > dense_sims.get(aid, 0.0):
                dense_sims[aid] = hit["score"]

    conn = db.get_conn()
    cache: dict = {}
    _prefetch_staleness(
        conn,
        cache,
        [h["artifact_id"] for h in chunk_hits + facet_hits + entity_hits],
    )
    best: dict[str, dict] = {}
    for hit in chunk_hits:
        aid = hit["artifact_id"]
        if aid not in best or hit["score"] > best[aid]["score"]:
            best[aid] = {"score": hit["score"], "chunk_id": hit["chunk_id"], "why": "chunk"}
    for hit, score in _weighted_hits(conn, facet_hits, cache):
        aid = hit["artifact_id"]
        if aid not in best or score > best[aid]["score"]:
            best[aid] = {"score": score, "chunk_id": None, "why": f"facet L{hit.get('level')}"}
    for hit, score in _weighted_hits(conn, entity_hits, cache):
        aid = hit["artifact_id"]
        if aid not in best or score > best[aid]["score"]:
            best[aid] = {
                "score": score,
                "chunk_id": None,
                "entity": (hit.get("entity"), hit.get("fact")),
                "why": "entity",
            }

    rows = conn.execute(
        "SELECT id, updated_at FROM artifacts" " WHERE id IN (SELECT value FROM json_each(?))",
        (json.dumps(sorted(best)),),
    ).fetchall()
    age = {row["id"]: _age_days(row["updated_at"]) for row in rows}
    for aid, info in best.items():
        info["score"] = _recency_score(info["score"], age.get(aid, 0.0))

    ranked = sorted(best.items(), key=lambda kv: kv[1]["score"], reverse=True)[:limit]

    try:
        chunk_rows: dict[str, tuple[str, str, str]] = {}
        by_chunk = [info["chunk_id"] for aid, info in ranked if info["chunk_id"]]
        if by_chunk:
            rows = conn.execute(
                "SELECT c.id AS chunk_id, a.title, a.kind, c.text AS snippet"
                " FROM chunks c JOIN artifacts a ON a.id = c.artifact_id"
                " WHERE c.id IN (SELECT value FROM json_each(?))"
                " AND a.deleted_at IS NULL AND a.vaulted_at IS NULL AND a.embedded_at IS NULL",
                (json.dumps(by_chunk),),
            ).fetchall()
            chunk_rows = {
                row["chunk_id"]: (row["title"], row["kind"], row["snippet"]) for row in rows
            }

        face_rows: dict[str, tuple[str, str]] = {}
        by_face = [aid for aid, info in ranked if not info["chunk_id"]]
        if by_face:
            rows = conn.execute(
                "SELECT id, title, kind FROM artifacts"
                " WHERE id IN (SELECT value FROM json_each(?))"
                " AND deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL",
                (json.dumps(by_face),),
            ).fetchall()
            face_rows = {row["id"]: (row["title"], row["kind"]) for row in rows}

        # Entity-only hits without a stored fact show the artifact's opening text.
        entity_aids = [
            aid
            for aid, info in ranked
            if not info["chunk_id"] and not (info.get("entity") or (None, None))[1]
        ]
        texts = artifact_texts(conn, entity_aids, max_words=40)

        out = []
        for aid, info in ranked:
            if info["chunk_id"]:
                row = chunk_rows.get(info["chunk_id"])
                if row is None:
                    continue
                title, kind, snippet = row
            else:
                face = face_rows.get(aid)
                if face is None:
                    continue
                title, kind = face
                fact = (info.get("entity") or (None, None))[1]
                snippet = fact or texts.get(aid, "")
            out.append(
                {
                    "score": round(info["score"], 4),
                    "artifact_id": aid,
                    "title": title,
                    "kind": kind,
                    "why": info["why"],
                    "snippet": " ".join(snippet.split())[:200],
                    "dense_similarity": round(dense_sims.get(aid, 0.0), 6),
                    "had_lexical_hit": aid in lexical_aids,
                }
            )
        return out
    finally:
        conn.close()


def _results_for_ids(ids: set[str], limit: int = 20) -> list[dict]:
    """Pure `#tag` query: the tagged set, newest touch first, constant score."""
    if not ids:
        return []
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, title, kind FROM artifacts"
            " WHERE id IN (SELECT value FROM json_each(?))"
            " AND deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL"
            " ORDER BY updated_at DESC LIMIT ?",
            (json.dumps(sorted(ids)), limit),
        ).fetchall()
        texts = artifact_texts(conn, [row["id"] for row in rows], max_words=40)
        out = []
        for row in rows:
            snippet = texts[row["id"]]
            out.append(
                {
                    "score": 0.0,
                    "artifact_id": row["id"],
                    "title": row["title"],
                    "kind": row["kind"],
                    "why": "tag",
                    "snippet": " ".join(snippet.split())[:200],
                }
            )
        return out
    finally:
        conn.close()


def _all_results(limit: int = 20) -> list[dict]:
    """Empty query: every artifact, newest touch first, constant score."""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, title, kind FROM artifacts"
            " WHERE deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL"
            " ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        texts = artifact_texts(conn, [row["id"] for row in rows], max_words=40)
        out = []
        for row in rows:
            snippet = texts[row["id"]]
            out.append(
                {
                    "score": 0.0,
                    "artifact_id": row["id"],
                    "title": row["title"],
                    "kind": row["kind"],
                    "why": "all",
                    "snippet": " ".join(snippet.split())[:200],
                }
            )
        return out
    finally:
        conn.close()


def artifact_texts(conn, ids, max_words: int = 1200) -> dict[str, str]:
    """Text per artifact in two queries: the body, else its chunks joined (P.2d)."""
    unique = list(dict.fromkeys(ids))
    if not unique:
        return {}
    bodies: dict[str, str] = {}
    for row in conn.execute(
        "SELECT id, body FROM artifacts" " WHERE id IN (SELECT value FROM json_each(?))",
        (json.dumps(unique),),
    ):
        bodies[row["id"]] = row["body"] or ""
    need = [aid for aid in unique if not bodies.get(aid, "").strip()]
    chunks: dict[str, list[str]] = {}
    if need:
        for row in conn.execute(
            "SELECT artifact_id, text FROM chunks"
            " WHERE artifact_id IN (SELECT value FROM json_each(?))"
            " ORDER BY artifact_id, ordinal",
            (json.dumps(need),),
        ):
            chunks.setdefault(row["artifact_id"], []).append(row["text"])
    out = {}
    for aid in unique:
        text = bodies.get(aid, "")
        if not text.strip():
            text = "\n\n".join(chunks.get(aid, []))
        words = text.split()
        if len(words) > max_words:
            text = " ".join(words[:max_words])
        out[aid] = text
    return out


def artifact_text(conn, artifact_id: str, max_words: int = 1200) -> str:
    """A note's body, or a capture's chunks."""
    return artifact_texts(conn, [artifact_id], max_words)[artifact_id]
