"""Candidate generation: search both layers, roll up to artifacts.

At POC scale this returns nearly the whole corpus, which is correct and expected.
Recall is trivially high when the candidate pool is the collection, so the number
that matters here is the ranking after rerank, not this stage. Do not add filtering
to make the count look better.

`candidates` rolls chunk and facet hits up to one entry per artifact, which is
what the rerank stage needs. `search_results` is the same rollup shaped for the
/search surface: one row per artifact (an artifact cannot occupy every result
slot), with a snippet, fused chunk + facet scores, and the matched-facet marker.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from functools import lru_cache
from sqlite3 import OperationalError

from .. import config, db
from ..index.store import get_store

# R.7 fuzzy branch: minimum SequenceMatcher ratio for a candidate to count as
# a one-edit typo match, and the score a fuzzy hit carries. The score is modest
# - below a strong lexical hit (a dual-branch rank-1 hit is 2/(k+1), ~0.033 at
# k=60) but above a single-branch rank-1 hit (1/(k+1), ~0.016), which is all a
# typo query can muster - so a fuzzy match wins the merge only when the
# hybrid's answer was itself weak. 0.02 is the old 0.6 on the k=1 scale,
# rescaled when RRF moved to the canonical k=60 (Phase M.5g).
FUZZY_RATIO = 0.75
FUZZY_BASE_SCORE = 0.02


# R.8 recency weighting: a free-text hit's score is multiplied by
# 1 + RECENCY_WEIGHT * exp(-age_days / RECENCY_TAU_DAYS), so a note touched
# today scores 1.5x and one from 180 days ago is unchanged. The decay is a
# small nudge, not a filter: relevance still dominates (a weak fresh hit
# cannot outrank a strong old one), and the golden-set eval is unaffected
# because a freshly seeded corpus is uniformly "now".
RECENCY_WEIGHT = 0.5
RECENCY_TAU_DAYS = 30


def _age_days(updated_at: str) -> float:
    """Days since `updated_at`, clamped at zero.

    The column is written two ways across the codebase - sqlite's
    `datetime('now')` (UTC, "YYYY-MM-DD HH:MM:SS") and ISO with a timezone
    offset - so both parse here; an unparseable value counts as age zero
    (never penalize a row the clock cannot date).
    """
    try:
        dt = datetime.fromisoformat(updated_at.replace(" ", "T"))
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)


def _recency_score(score: float, age_days: float) -> float:
    """The R.8 time-decay multiplier applied to a free-text hit score."""
    return score * (1.0 + RECENCY_WEIGHT * math.exp(-age_days / RECENCY_TAU_DAYS))


# R.9 opt-in cross-encoder rerank: re-score the top fused candidates against
# the query with BAAI/bge-reranker-base and order by that score. Off by
# default (config.SEARCH_RERANK); the fused hybrid must win this on its own.
_RERANK_MODEL = "BAAI/bge-reranker-base"
_RERANK_WINDOW = 30
# A missing/failed reranker score sorts below every real score.
_RERANK_LAST = -math.inf


@lru_cache(maxsize=1)
def _cross_encoder():
    """The shared cross-encoder model, loaded once per process.

    Imported lazily so the flag-off path never constructs a model, and tests
    can stub this function instead of downloading a gigabyte. CPU providers
    only, deliberately: the embedding model already holds a CoreML context,
    and a second CoreML model in the same process leaks contexts until the
    OS kills the process (verified empirically - SIGKILL, "Context leak
    detected"). The reranker is an occasional opt-in pass over ~30 documents,
    so CPU is not the hot path.
    """
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(model_name=_RERANK_MODEL, providers=["CPUExecutionProvider"])


def _rerank(q: str, fused: list[dict]) -> list[dict]:
    """Re-order fused candidates by cross-encoder relevance, score descending.

    The stable sort keeps the fused order for ties, and a score of None (the
    model refused or the text was empty) sorts last rather than first, so a
    reranker hiccup can scramble the ranking only of the artifacts it actually
    judged. A hard failure (model load, inference error) degrades to the fused
    order unchanged - reranking is an enhancement, never a gate.
    """
    if not fused:
        return fused
    conn = db.get_conn()
    try:
        texts = [artifact_text(conn, h["artifact_id"]) for h in fused]
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


def _fuzzy_ratio(query: str, candidate: str) -> float:
    """Best of whole-string and best-word-window similarity (R.7).

    One-edit typos ("copper" vs "chopper") score high on the whole string;
    a query that is a few words of a longer candidate scores high on its best
    window ("growing food" inside "the technique of growing food without
    soil"). Windows slide by word, so the shorter text never has to align to
    word boundaries it does not have.
    """
    ql, cl = query.lower(), candidate.lower()
    best = SequenceMatcher(None, ql, cl).ratio()
    q_words = ql.split()
    c_words = cl.split()
    n = len(q_words)
    if n and len(c_words) > n:
        for i in range(len(c_words) - n + 1):
            best = max(best, SequenceMatcher(None, ql, " ".join(c_words[i : i + n])).ratio())
    return best


def _fuzzy_hits(query: str, limit: int) -> list[dict]:
    """Short-field fuzzy candidates: titles, entity names, current annotations.

    The trigram branch covers substrings, not one-edit typos: "copper" and
    "chopper" share too few trigrams for FTS5 to see. Fuzzy matching over the
    whole corpus's chunk text is too slow, so this branch is scoped to the
    short fields a name lives in: artifact titles, `entities.entity` values,
    and current annotation texts (same NOT EXISTS filter as R.2a). The corpus
    is hundreds to low thousands of rows, so scoring every candidate stays
    single-digit milliseconds.

    Returns one entry per artifact with a best ratio at or above FUZZY_RATIO,
    carrying the matched text as the snippet source.
    """
    q = query.strip()
    if len(q) < 3:
        return []
    conn = db.get_conn()
    try:
        rows = conn.execute("SELECT id, title FROM artifacts WHERE deleted_at IS NULL").fetchall()
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
    """Record aid's best (ratio, matched-text) pair for a candidate string."""
    ratio = _fuzzy_ratio(q, text)
    if ratio >= FUZZY_RATIO and (aid not in best or ratio > best[aid][0]):
        best[aid] = (ratio, text)


def _merge_fuzzy(results: list[dict], fuzzy: list[dict], limit: int) -> list[dict]:
    """Merge the fuzzy branch into the hybrid rollup (R.7).

    The fuzzy branch explains why an artifact matches a one-edit typo the
    lexical and semantic branches cannot cleanly claim. It wins the merge
    only when its score beats the hybrid's - a strong lexical hit (a title
    at 10x bm25, a dual-branch rank 1) keeps its own explanation, while a
    weak dense-only hit yields to "fuzzy". A fuzzy-only artifact is added
    and ranks by its fuzzy score.
    """
    if not fuzzy:
        return results
    by_aid = {h["artifact_id"]: h for h in results}
    conn = db.get_conn()
    try:
        for f in fuzzy:
            aid = f["artifact_id"]
            if aid in by_aid:
                if f["score"] > by_aid[aid]["score"]:
                    by_aid[aid] = {**by_aid[aid], "score": f["score"], "why": "fuzzy"}
            else:
                row = conn.execute(
                    "SELECT title, kind FROM artifacts WHERE id = ?", (aid,)
                ).fetchone()
                if row is None:
                    continue
                by_aid[aid] = {
                    "score": f["score"],
                    "artifact_id": aid,
                    "title": row["title"],
                    "kind": row["kind"],
                    "why": "fuzzy",
                    "snippet": " ".join(f["matched"].split())[:200],
                }
    finally:
        conn.close()
    return sorted(by_aid.values(), key=lambda h: h["score"], reverse=True)[:limit]


# R.10 exact-needle escape hatch: a free-text query wrapped in double quotes
# is a phrase needle, not a bag of tokens. The phrase match runs against both
# FTS chunk tables and pins its artifacts above every hybrid answer.


def _quoted_phrase(free_text: str) -> str | None:
    """The phrase inside `free_text` when it is one double-quoted phrase.

    R.10's escape hatch: `"tony tony chopper"` means the exact phrase, in
    order, verbatim - which the hybrid's token search is not. Only a query
    that is ENTIRELY one quoted phrase activates the branch; a quote in the
    middle of free text is a literal character, not a needle.
    """
    if len(free_text) >= 2 and free_text.startswith('"') and free_text.endswith('"'):
        inner = free_text[1:-1]
        if inner.strip():
            return inner
    return None


def _exact_phrase_hits(phrase: str, limit: int) -> list[dict]:
    """Artifacts containing `phrase` verbatim, in order, with `why="exact"`.

    A phrase query against both FTS chunk tables: the unicode61 table sees
    the exact token sequence, the trigram table sees the same sequence as
    contiguous trigrams, so it also catches a phrase sitting inside a longer
    token run ("tony tony" inside "Xtony tonyY") - the substring corner the
    token-based table cannot see. The two tokenizers agree on adjacency;
    unioning them is the point. A database that has not rebuilt since the
    trigram table was added has no `fts_chunks_tri` yet, so that table is
    skipped and the unicode61 branch still answers.
    """
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
            " WHERE c.id IN (SELECT value FROM json_each(?)) AND a.deleted_at IS NULL",
            (json.dumps(list(chunk_scores)),),
        ).fetchall()
        # One row per artifact, carrying its best matching chunk as the snippet.
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
            }
            for h in ranked
        ]
    finally:
        conn.close()


def _pin_exact(
    exact: list[dict], results: list[dict], limit: int, tag_ids: set[str] | None = None
) -> list[dict]:
    """Prepend R.10 exact-phrase hits above the hybrid results, deduped.

    An artifact that also reached the hybrid keeps only its exact
    presentation, pinned on top; the hybrid copy is dropped so one artifact
    never occupies two slots. When the query carries tag filters, an exact
    hit outside the tag set is dropped like any other non-tagged hit.
    """
    if tag_ids:
        exact = [h for h in exact if h["artifact_id"] in tag_ids]
    pinned = list(exact)
    seen = {h["artifact_id"] for h in pinned}
    for h in results:
        if h["artifact_id"] not in seen:
            pinned.append(h)
    return pinned[:limit]


def _log_sub_queries(queries: list[str]) -> None:
    """Make the cost of expansion visible in the engine log.

    A lens expands into several sub-queries; each one searches both
    collections and both branches. The count is the multiplier on retrieval
    cost, so it is printed once per search rather than hidden.
    """
    if len(queries) > 1:
        print(f"[search] {len(queries)} sub-queries (query expansion)", flush=True)


def hit_is_stale(conn, hit: dict, cache: dict) -> bool:
    """Whether a model-written hit no longer describes the artifact it belongs to.

    A facet is written from a body by a model, and an entity line is extracted
    from a body by a model, and both are current only while body and model still
    match. `body_version` is the artifact_versions row the hit was built against
    (I2.1/I2.2), so any body edit makes every old facet and entity stale
    instantly - a timestamp comparison, no model call. `model_version` is the
    provider that wrote it; a model switch makes old rows stale until a targeted
    refresh regenerates them (I2.4). A hit that cannot prove it was built from
    the current body must not win a slot: a wrong concept hit costs more trust
    than a missed one.

    `cache` maps artifact_id to (current_body_version, current_model), so a
    request with several sub-queries pays for each artifact once.
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
                get_provider(local_only=bool(row["local_only"])).model,
            )
    current = cache[aid]
    if current is None:
        return True
    body_version, model = current
    return hit.get("body_version") != body_version or hit.get("model_version") != model


def candidates(
    queries: list[str], limit: int = 150, per_query: int = 40, prefetch: int = 100
) -> list[dict]:
    """Artifact ids ordered by best hit across all three collections.

    Facet and entity hits are weighted by their trust score, so an abstraction
    that keeps winning matches the director then ejects quietly stops pulling
    artifacts in. Entity hits are the name-side of the same gap: a question
    phrased in the world's vocabulary reaches an artifact through its enriched
    one-line fact.

    `prefetch` widens the per-branch window the store searches before fusion. The
    default keeps ordinary retrieval unchanged; whole-library scoring raises it so
    that every chunk is actually searched (otherwise a chunk beyond the fixed
    window is silently never seen, which would make a "complete" coverage label a
    lie).
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
            for hit in store.search(store.CHUNKS, query, limit=per_query, prefetch=prefetch):
                aid = hit["artifact_id"]
                if hit["score"] > best[aid]:
                    best[aid] = hit["score"]
                    why[aid] = "chunk"

            for hit in store.search(store.FACETS, query, limit=per_query, prefetch=prefetch):
                # A facet built from an older body or by an older model no longer
                # describes the artifact; drop it rather than let it win a slot.
                if hit_is_stale(conn, hit, cache):
                    continue
                aid = hit["artifact_id"]
                try:
                    trust = float(hit.get("trust") or 0.5)
                except (TypeError, ValueError):  # noqa: PERF203 - a bad trust value is data rot
                    trust = 0.5
                score = hit["score"] * trust * 2.0
                if score > best[aid]:
                    best[aid] = score
                    why[aid] = f"facet L{hit.get('level')}"
                    facet_id = hit.get("facet_id")
                    if facet_id:
                        matched_facet[aid] = facet_id

            for hit in store.search(store.ENTITIES, query, limit=per_query, prefetch=prefetch):
                # Same provenance discipline as facets: an entity line extracted
                # from an older body or by an older model is dropped.
                if hit_is_stale(conn, hit, cache):
                    continue
                aid = hit["artifact_id"]
                try:
                    trust = float(hit.get("trust") or 0.5)
                except (TypeError, ValueError):  # noqa: PERF203 - a bad trust value is data rot
                    trust = 0.5
                score = hit["score"] * trust * 2.0
                if score > best[aid]:
                    best[aid] = score
                    why[aid] = "entity"

        ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:limit]

        out = []
        for aid, score in ranked:
            row = conn.execute("SELECT title FROM artifacts WHERE id = ?", (aid,)).fetchone()
            if row is None:
                continue
            out.append(
                {
                    "artifact_id": aid,
                    "title": row["title"],
                    "score": score,
                    "why": why.get(aid),
                    "matched_facet_id": matched_facet.get(aid),
                }
            )
        return out
    finally:
        conn.close()


def search_results(q: str, limit: int = 20) -> list[dict]:
    """One result per artifact for the /search surface.

    Chunk and facet hits are rolled up to artifact ids (a facet hit weighted
    by trust) and deduplicated, so one artifact cannot occupy every result
    slot: six chunks of one note come back as one row. The snippet is the
    text of the best matching chunk; a facet-only match shows the artifact
    face instead.

    Tags are a filter, not text to rank: `#work` or `tag:work` tokens in the
    query become an exact id filter, never an embedding. A query that is
    only tags skips the index entirely and reads straight from SQLite.

    R.10: a free-text query that is entirely one double-quoted phrase
    (`"tony tony chopper"`) is an exact needle, not a bag of tokens: the
    phrase match runs against both FTS tables and pins its hits above every
    hybrid answer with `why="exact"`.
    """
    from .. import tags

    free_text, tag_names = tags.parse_tags(q)
    tag_ids = tags.ids_with_all(tag_names) if tag_names else set()

    # R.10: the exact-phrase escape hatch, computed before the hybrid so its
    # hits can be pinned on top. Only a query that is ENTIRELY one quoted
    # phrase activates it; quotes in the middle of free text are literal
    # characters. The hybrid below searches the bare phrase, so the quotes
    # never leak into the embedding or the tokenizer.
    phrase = _quoted_phrase(free_text)
    query_text = phrase if phrase is not None else free_text
    exact = _exact_phrase_hits(query_text, limit) if phrase is not None else []

    # Empty query, no tags: "everything". There is no text to rank and no set to
    # filter, and the embedding store cannot answer an empty vector (knn rejects
    # k larger than its max), so read the library directly, newest touch first.
    # This is what a request to "group everything I have saved" plans into.
    if not free_text and not tag_ids:
        return _all_results(limit)

    # Pure tag query: no embedding, no store search. Roughly 1 ms.
    if not free_text and tag_ids:
        return _results_for_ids(tag_ids, limit)

    if tag_ids:
        # Mixed: hybrid search on the free text, then keep only tagged hits. The
        # filter runs on a wider window than `limit` and truncates afterward -
        # filtering the top `limit` first would drop a tagged match that ranked just
        # past the cutoff, so "kubernetes #work" could miss a work-tagged kubernetes
        # note purely because plain "kubernetes" outranked it. Tags are a filter, so
        # the R.9 rerank stage does not apply here: the free text is ranked, then
        # the tag set is carved out of that ranking.
        tagged = [h for h in _hybrid_results(query_text, limit * 5) if h["artifact_id"] in tag_ids]
        ranked = tagged[:limit]

    elif config.SEARCH_RERANK:
        # R.9: re-score a wider fused window than the final limit, so the
        # reranker can promote a candidate that ranked just past the cutoff.
        window = max(limit, _RERANK_WINDOW)
        fused = _merge_fuzzy(
            _hybrid_results(query_text, window), _fuzzy_hits(query_text, window), window
        )
        ranked = _rerank(query_text, fused)[:limit]

    else:
        ranked = _merge_fuzzy(
            _hybrid_results(query_text, limit), _fuzzy_hits(query_text, limit), limit
        )

    # R.10: the exact needle outranks every hybrid answer, deduped so one
    # artifact never occupies two slots. With no exact hits this is a no-op.
    if exact:
        ranked = _pin_exact(exact, ranked, limit, tag_ids)
    return ranked


def _hybrid_results(q: str, limit: int = 20) -> list[dict]:
    """The chunk + facet + entity rollup for a free-text query."""
    store = get_store()
    # A wider per-branch window than the final limit, so the dedup rolls up
    # from enough chunk, facet, and entity hits to rank fairly.
    per_query = limit * 3
    prefetch = max(100, limit * 5)
    chunk_hits = store.search(store.CHUNKS, q, limit=per_query, prefetch=prefetch)
    facet_hits = store.search(store.FACETS, q, limit=per_query, prefetch=prefetch)
    entity_hits = store.search(store.ENTITIES, q, limit=per_query, prefetch=prefetch)

    conn = db.get_conn()
    cache: dict = {}
    best: dict[str, dict] = {}
    for hit in chunk_hits:
        aid = hit["artifact_id"]
        if aid not in best or hit["score"] > best[aid]["score"]:
            best[aid] = {"score": hit["score"], "chunk_id": hit["chunk_id"], "why": "chunk"}
    for hit in facet_hits:
        # A facet built from an older body or by an older model no longer
        # describes the artifact; drop it rather than let it win a slot.
        if hit_is_stale(conn, hit, cache):
            continue
        aid = hit["artifact_id"]
        try:
            trust = float(hit.get("trust") or 0.5)
        except (TypeError, ValueError):  # noqa: PERF203 - a bad trust value is data rot
            trust = 0.5
        score = hit["score"] * trust * 2.0
        if aid not in best or score > best[aid]["score"]:
            best[aid] = {"score": score, "chunk_id": None, "why": f"facet L{hit.get('level')}"}
    for hit in entity_hits:
        # Same provenance discipline as the facets branch: a line extracted from
        # an older body or by an older model is dropped rather than shown.
        if hit_is_stale(conn, hit, cache):
            continue
        aid = hit["artifact_id"]
        try:
            trust = float(hit.get("trust") or 0.5)
        except (TypeError, ValueError):  # noqa: PERF203 - a bad trust value is data rot
            trust = 0.5
        score = hit["score"] * trust * 2.0
        if aid not in best or score > best[aid]["score"]:
            best[aid] = {
                "score": score,
                "chunk_id": None,
                "entity": (hit.get("entity"), hit.get("fact")),
                "why": "entity",
            }

    # R.8 recency: one batched fetch of the ranked artifacts' touch times,
    # then multiply before the final sort so a fresh artifact can overtake a
    # stale one with the same base score. The decay keeps relevance dominant.
    rows = conn.execute(
        "SELECT id, updated_at FROM artifacts" " WHERE id IN (SELECT value FROM json_each(?))",
        (json.dumps(sorted(best)),),
    ).fetchall()
    age = {row["id"]: _age_days(row["updated_at"]) for row in rows}
    for aid, info in best.items():
        info["score"] = _recency_score(info["score"], age.get(aid, 0.0))

    ranked = sorted(best.items(), key=lambda kv: kv[1]["score"], reverse=True)[:limit]

    try:
        out = []
        for aid, info in ranked:
            if info["chunk_id"]:
                row = conn.execute(
                    "SELECT a.title, a.kind, c.text AS snippet FROM chunks c"
                    " JOIN artifacts a ON a.id = c.artifact_id WHERE c.id = ?",
                    (info["chunk_id"],),
                ).fetchone()
                if row is None:
                    continue
                title, kind, snippet = row["title"], row["kind"], row["snippet"]
            else:
                row = conn.execute(
                    "SELECT title, kind FROM artifacts WHERE id = ?", (aid,)
                ).fetchone()
                if row is None:
                    continue
                title, kind = row["title"], row["kind"]
                # An entity-only match shows the enriched line that bridged the
                # vocabulary gap - "Theodore Roosevelt - 26th US President..." -
                # which explains the match better than the artifact's face.
                fact = (info.get("entity") or (None, None))[1]
                snippet = fact or artifact_text(conn, aid, max_words=40)
            out.append(
                {
                    "score": round(info["score"], 4),
                    "artifact_id": aid,
                    "title": title,
                    "kind": kind,
                    "why": info["why"],
                    "snippet": " ".join(snippet.split())[:200],
                }
            )
        return out
    finally:
        conn.close()


def _results_for_ids(ids: set[str], limit: int = 20) -> list[dict]:
    """A pure `#tag` query: results straight from the tag filter, newest touch first.

    There is no relevance to rank by - the person asked for a set, so the set
    is ordered by the same last-touch clock as the wall. Score is constant
    because nothing was matched, only filtered.
    """
    if not ids:
        return []
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, title, kind FROM artifacts"
            " WHERE id IN (SELECT value FROM json_each(?))"
            " AND deleted_at IS NULL"
            " ORDER BY updated_at DESC LIMIT ?",
            (json.dumps(sorted(ids)), limit),
        ).fetchall()
        out = []
        for row in rows:
            snippet = artifact_text(conn, row["id"], max_words=40)
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
    """The "everything" query: every artifact, newest touch first.

    Same shape as `_results_for_ids` - score is constant because nothing was
    matched, only listed. The wall clock order gives a grouping request that
    spans the whole library a stable, useful order to work from.
    """
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, title, kind FROM artifacts"
            " WHERE deleted_at IS NULL"
            " ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for row in rows:
            snippet = artifact_text(conn, row["id"], max_words=40)
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


def artifact_text(conn, artifact_id: str, max_words: int = 1200) -> str:
    """The text a judgment reads. A note has a body; a capture has its chunks."""
    row = conn.execute("SELECT body FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
    text = (row["body"] if row else None) or ""
    if not text.strip():
        chunks = conn.execute(
            "SELECT text FROM chunks WHERE artifact_id = ? ORDER BY ordinal", (artifact_id,)
        ).fetchall()
        text = "\n\n".join(c["text"] for c in chunks)
    words = text.split()
    return text if len(words) <= max_words else " ".join(words[:max_words])
