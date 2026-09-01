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

from pydantic import BaseModel

from .. import config, db
from ..index.store import get_store
from ..providers.base import get_provider

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


# Q.3 relevance floor, two-tier gray-zone gate (Minh's DECISION after the
# Q.4 block-out): a single dense threshold cannot separate the real matches
# from the strongest gibberish neighbors - the eval proved the weakest real
# matches (cosine ~0.518) sit below the strongest gibberish neighbors
# (~0.668), so no constant divides them. The floor is therefore a judgment
# on the raw legs with TWO bars on the true-cosine scale (Q.2b), leaving a
# gray zone between them that the gray-zone judge (Q.3b) decides:
#
# - Any result with a lexical hit survives regardless of its dense score:
#   FTS5 keyword (unicode61, with prefix recall) / fuzzy / exact-phrase, and
#   the FTS5 KEYWORD branch of a facet or entity (Q.7). The trigram leg is a
#   recall net only - a trigram-only hit faces the gate on its dense
#   similarity (Minh's DECISION: a 3-character substring overlap like "pie"
#   inside "pieces" is noise, not a real word match; partial words are
#   already covered by the keyword prefix query). A facet/entity DENSE-only
#   hit is likewise a semantic neighbor, not a lexical leg, and faces the
#   gate below.
# - Without a lexical hit: `dense_similarity >= KEEP_ABOVE` is clearly
#   relevant, keep without asking; `dense_similarity < DROP_BELOW` is
#   clearly irrelevant, drop without asking; in between is the gray zone,
#   kept or dropped on one model judgment (Q.3b).
#
# These two bars are start values for the eval in PLAN Phase Q.4 to calibrate
# against the corpus - they are not guessed final answers. Q.4 shrinks the
# gray zone as far as it can while keeping all 42 real-match queries passing
# and pushing Nothing-OK toward 8/8.
KEEP_ABOVE = 0.75
DROP_BELOW = 0.45


def _floor_verdict(hit: dict) -> str:
    """The two-tier keep decision for one hit: "keep", "drop", or "gray".

    A hit with any lexical leg is always kept. Without one, the dense
    similarity is judged against the two bars: at or above `KEEP_ABOVE` is
    clearly relevant, below `DROP_BELOW` is clearly irrelevant, and the
    strip in between is the gray zone where the judge (Q.3b) decides.
    """
    if hit.get("had_lexical_hit"):
        return "keep"
    sim = hit.get("dense_similarity", 0.0)
    if sim >= KEEP_ABOVE:
        return "keep"
    if sim < DROP_BELOW:
        return "drop"
    return "gray"


def _apply_floor(query: str, hits: list[dict]) -> list[dict]:
    """The Q.3 two-tier gate over a ranked list, survivor order preserved.

    Keeps lexical-leg and clearly-close hits, drops clearly-far ones, and
    sends the gray zone to the judge (Q.3b) in one batched call. Survivors
    keep their relative order - the floor removes non-matches, it never
    reorders matches. A gray-zone hit whose artifact the judge did not keep
    is removed; if the judge is unavailable it keeps everything (fail-open).
    """
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


# ---- Q.3b: the gray-zone judge -------------------------------------------
#
# The two bars leave a strip - DROP_BELOW <= dense_similarity < KEEP_ABOVE
# with no lexical hit - that the eval proved no constant can split from the
# real matches. One model judgment decides those candidates per search: the
# query and each item as `[{kind}] {title}\n{snippet}` go to the provider in
# one batched call, and each comes back as {id, relevant}. Three hard rules:
# fail-open (a raising or malformed call keeps every candidate it did not
# clearly judge - the gate's error budget is a small honest leak, never the
# silent loss of a real note), cached per (query, artifact_id, model_version)
# so a re-run of the same search costs nothing, and only the gray zone ever
# reaches this code, so most searches make zero model calls.


class _GrayZoneVerdict(BaseModel):
    id: str  # the artifact_id of the judged candidate
    relevant: bool  # whether it genuinely matches the query


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

A genuine match has real topical overlap with the query - it actually bears on
what was asked. An item about a different subject that only happens to sit
nearby in vector space is NOT a match. When in doubt, prefer "not relevant": a
missed note costs nothing, while a confident wall of unrelated notes is the
failure this gate exists to stop.

Return one verdict per item, echoing the exact [id:...] shown above.
"""


def _judge_cache_read(query: str, artifact_id: str, model_version: str) -> bool | None:
    """The cached gray-zone verdict for (query, artifact), or None when absent.

    A verdict is a property of the query and the artifact text, not of the
    bars, so it stays valid as Q.4 moves them: this cache is only consulted
    for a candidate that is gray on the current run, and it was written the
    last time the same (query, artifact) was judged. Scoped to the judge's
    model_version so a backend switch never serves another model's opinions.
    A missing `derived_values` table (pre-0012 DB) reads as "no cache".
    """
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
    """Record the verdict for (query, artifact) under the judge's model."""
    with db.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO derived_values"
            " (scope, subject, attribute, value, grounded, source, model_version, created_at)"
            " VALUES ('gray_judge', ?, ?, ?, 1, 'model', ?, ?)",
            (query, artifact_id, "1" if relevant else "0", model_version, db.now()),
        )


def judge_gray_zone(query: str, candidates: list[dict]) -> set[str]:
    """One batched model call deciding the gray-zone candidates (Q.3b).

    `candidates` holds hits with no lexical leg whose dense similarity sits in
    [DROP_BELOW, KEEP_ABOVE) - the strip only the judge may split. Returns the
    set of artifact ids judged genuinely relevant to `query`.

    Fail-open by contract: if the provider raises, or its answer is malformed
    or does not cover an item, that item is kept. Verdicts are cached per
    (query, artifact_id, model_version) in `derived_values` (scope
    'gray_judge'), so re-running the same search makes no new call.
    """
    if not candidates:
        return set()
    try:
        provider = get_provider()
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

    lines = [
        f"{idx}. [id:{hit['artifact_id']}] [{hit.get('kind', 'artifact')}] {hit['title']}\n{hit['snippet']}"
        for idx, hit in enumerate(unjudged, 1)
    ]
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
                continue  # an id that was not in the batch: ignore, never cache
            covered.add(verdict.id)
            _judge_cache_write(query, verdict.id, verdict.relevant, model_version)
            if verdict.relevant:
                kept.add(verdict.id)
        # Fail-open for anything the response did not cover.
        kept.update(aid for aid in by_aid if aid not in covered)
    except Exception:  # noqa: BLE001 - fail-open is the contract
        kept.update(h["artifact_id"] for h in unjudged)
    return kept


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
    and current annotation texts (same NOT EXISTS filter as R.2a). Even so it
    loads every one of those rows into Python and runs SequenceMatcher over all
    of them, so it is the most expensive leg per query. The corpus is hundreds to
    low thousands of rows, so a run stays single-digit milliseconds - but it is
    not free, which is why callers gate it behind `_needs_fuzzy` (PERF.1) and
    only reach here when the hybrid leg produced no strong hit.

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
    # Title/kind for the fuzzy-only hits (those not already in the hybrid rollup) are
    # fetched in ONE json_each query instead of a SELECT per hit (PERF.5).
    missing = [f["artifact_id"] for f in fuzzy if f["artifact_id"] not in by_aid]
    meta: dict = {}
    if missing:
        conn = db.get_conn()
        try:
            meta = {
                r["id"]: r
                for r in conn.execute(
                    "SELECT id, title, kind FROM artifacts"
                    " WHERE id IN (SELECT value FROM json_each(?))",
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
            # Q.2: a fuzzy-only hit IS a lexical hit (it's a one-edit typo over a
            # short lexical field - title, entity name, annotation text), so the
            # relevance floor treats it as such. There is no dense-similarity reading
            # here: the branch never queries the dense store. The 0.0 below matches the
            # Q.3 convention - the floor checks `had_lexical_hit` first.
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
    """Whether the fuzzy branch is worth running for this query (PERF.1).

    `_fuzzy_hits` is a full O(N) Python scan over titles/entities/annotations - the
    worst per-query cost in the pipeline. It only rescues a one-edit typo the lexical
    and dense legs missed, so it is pointless when the hybrid already found a confident
    answer: any lexical hit, or a dense match at/above KEEP_ABOVE. An empty or all-weak
    hybrid (the shape a typo produces) is exactly when fuzzy earns its cost.
    """
    return not any(
        h.get("had_lexical_hit") or h.get("dense_similarity", 0.0) >= KEEP_ABOVE
        for h in hybrid
    )


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
                # Q.2: an exact-phrase match IS a lexical hit. The floor (Q.3)
                # never drops a pinned exact match.
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


def _get_model(local_only: bool) -> str:
    """Get the model string for staleness checks.

    Reads directly from settings/config - no provider construction.
    Can be mocked by tests via enqueue.providers.base.get_provider mock.
    """
    from .. import settings, config
    from ..providers.base import get_provider

    # Try to get from provider first (allows test mocking)
    try:
        provider = get_provider(local_only=local_only)
        return provider.model
    except Exception:
        pass
    # Fallback: read directly from settings
    from .. import config, settings
    return config.LLM_MODEL if local_only else (settings.get("llm_model") or config.LLM_MODEL)


def _prefetch_staleness(conn, cache, ids) -> None:
    """Fill the staleness cache for unseen artifact ids in one query (P.2c).

    `hit_is_stale` needs each candidate artifact's body_version and provider
    model; per-hit probes are one SELECT each. Batching turns the request's
    probes into a single json_each query, and every later probe is a dict
    read. Model strings read from get_provider (mockable) or settings fallback.
    Providers are deduped by local_only - the model string is the same
    for the whole shelf, and constructing a provider client per artifact was
    pure waste.
    """
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

    # Model strings via _get_model (mockable via get_provider mock)
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
    """Trust-weight a batch of model-written hits, dropping the stale ones.

    Facets and entities are written from a body by a model, so a hit is only
    current while body and model still match - `hit_is_stale` enforces that
    provenance discipline, and a hit that cannot prove it was built from the
    current body must not win a slot. The trust score (0..1) multiplies the
    raw store score, and the 2.0 factor keeps a strong facet/entity match
    competitive with a chunk match of the same raw score: a model's write is
    worth more than a token overlap.

    Yields (hit, weighted_score) for every hit that is not stale, so each of
    the four call sites only decides where the weighted score goes.
    """
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
            chunk_hits = store.search(store.CHUNKS, query, limit=per_query, prefetch=prefetch)
            facet_hits = store.search(store.FACETS, query, limit=per_query, prefetch=prefetch)
            entity_hits = store.search(store.ENTITIES, query, limit=per_query, prefetch=prefetch)
            # One staleness query for the whole sub-query's candidates, so a
            # request that fans out into several sub-queries pays once per
            # distinct artifact (P.2c).
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

        # Candidate titles in one query rather than one SELECT per ranked id
        # (P.2a). A ranked id that is not in the titles map (a row deleted
        # between search and fetch) is dropped, exactly as the per-row miss was.
        titles: dict[str, str] = {}
        if ranked:
            rows = conn.execute(
                "SELECT id, title FROM artifacts" " WHERE id IN (SELECT value FROM json_each(?))",
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
        # Q.3: the relevance floor still applies - a tag-filtered result that
        # matches no real lexical leg is dropped (below DROP_BELOW outright,
        # or in the gray zone and the Q.3b judge says no), even if its tag
        # set looks right.
        tagged = _apply_floor(query_text, tagged)
        ranked = tagged[:limit]

    elif config.SEARCH_RERANK:
        # R.9: re-score a wider fused window than the final limit, so the
        # reranker can promote a candidate that ranked just past the cutoff.
        window = max(limit, _RERANK_WINDOW)
        hybrid = _hybrid_results(query_text, window)
        fuzzy = _fuzzy_hits(query_text, window) if _needs_fuzzy(hybrid) else []
        fused = _merge_fuzzy(hybrid, fuzzy, window)
        # Q.3: the floor reads the per-leg signals from _hybrid_results /
        # _merge_fuzzy. The wider window means we floor before the reranker
        # so a gibberish query cannot waste the reranker's budget.
        fused = _apply_floor(query_text, fused)
        ranked = _rerank(query_text, fused)[:limit]

    else:
        hybrid = _hybrid_results(query_text, limit)
        fuzzy = _fuzzy_hits(query_text, limit) if _needs_fuzzy(hybrid) else []
        fused = _merge_fuzzy(hybrid, fuzzy, limit)
        # Q.3: drop result that has no lexical hit AND whose dense similarity
        # is below DROP_BELOW (or sits in the gray zone and the Q.3b judge
        # says no). A query left with zero kept results returns [] - the
        # honest "nothing found".
        ranked = _apply_floor(query_text, fused)

    # R.10: the exact needle outranks every hybrid answer, deduped so one
    # artifact never occupies two slots. Exact-phrase hits pass the floor by
    # construction (had_lexical_hit=True); an exact hit whose artifact is
    # outside the tag set is dropped like any other non-tagged hit. With no
    # exact hits this is a no-op.
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

    # Q.2: per-leg signal at the fusion point. The relevance floor (Q.3) judges
    # raw legs, not the fused RRF score - a real query has at least one strong
    # leg (lexical hit or close dense neighbor), a gibberish query has no
    # lexical hit AND its nearest neighbor is far. We thread two flags per
    # candidate through to the output: `dense_similarity` (the best cosine
    # similarity the dense branch produced for this artifact, 0.0 if none)
    # and `had_lexical_hit` (True if a real lexical leg - chunk keyword /
    # fuzzy / exact-phrase, or the FTS5 KEYWORD branch of a facet or entity
    # - hit it). Ranking is unchanged - these flags only join the result
    # dict.
    #
    # `chunk_hits` etc. carry the FUSED RRF score, not raw cosine similarity;
    # we ask the store directly for the dense leg so the floor can read the
    # actual nearest-neighbor distance for each artifact. Same query budget
    # as R.6's recall net - one extra sqlite-vec knn per call.
    #
    # Lexical legs are scored separately so a dense-only match (no keyword /
    # facet / entity hit) does not count as lexical. The fused
    # `chunk_hits` list is what got ranked and surfaced, but it can be
    # entirely dense-only - calling every artifact in it "lexical" would
    # make the Q.3 floor useless.
    dense_sims: dict[str, float] = {}
    lexical_aids: set[str] = set()
    dense_chunk_hits = store.search_dense(store.CHUNKS, q, limit=per_query)
    for hit in dense_chunk_hits:
        aid = hit["artifact_id"]
        if hit["score"] > dense_sims.get(aid, 0.0):
            dense_sims[aid] = hit["score"]
    keyword_chunk_hits = store.search_keyword(store.CHUNKS, q, limit=per_query)
    for hit in keyword_chunk_hits:
        lexical_aids.add(hit["artifact_id"])
    # Q.7 (Minh's DECISION): the trigram leg stays a RECALL leg, not a
    # lexical bypass. Trigram matches 3-character substrings - "pie" finds
    # "pieces" and "piety", "pecan" finds "pecans" - which is noise at the
    # floor's bar, not a real word match. Partial-word recall is already
    # covered by the keyword branch (its FTS5 prefix query: "sourd"* finds
    # the token "sourdough"). A trigram-only hit still surfaces the
    # candidate through the fused `chunk_hits` above, but it now clears the
    # two-tier gate on its own `dense_similarity` like any other dense-only
    # hit (keep >= KEEP_ABOVE, drop < DROP_BELOW, gray zone -> judge).

    # Q.7: a facet/entity hit is a lexical leg ONLY when it matched on its
    # FTS5 keyword branch. Both collections fuse a keyword branch and a
    # dense (vec) branch, and `store.search` does not say which leg a hit
    # rode in on - treating every fused facet/entity hit as lexical let a
    # weak semantic neighbor bypass the floor. The live leak: "pecan pie
    # recipes" surfaced the "Party of the People" note through an entity
    # vector at 0.409 cosine, below DROP_BELOW, exempted only because the
    # entity hit was mislabelled a lexical leg. So the keyword branch is
    # read per collection and its hits set `had_lexical_hit`, while the
    # dense branch feeds `dense_sims` - a dense-only facet/entity hit
    # carries its own best cosine and faces the two-tier gate exactly like
    # a chunk dense hit.
    for dense_hits in (
        store.search_dense(store.FACETS, q, limit=per_query),
        store.search_dense(store.ENTITIES, q, limit=per_query),
    ):
        for hit in dense_hits:
            aid = hit["artifact_id"]
            if hit["score"] > dense_sims.get(aid, 0.0):
                dense_sims[aid] = hit["score"]
    for name in (store.FACETS, store.ENTITIES):
        for hit in store.search_keyword(name, q, limit=per_query):
            lexical_aids.add(hit["artifact_id"])

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
        # P.2b: the snippet/title fetches were one SELECT per result. Now the
        # chunk-snippet rows come back in one query, the bare artifact faces in
        # a second, and the entity-only body/chunk reads in one batched pair -
        # a constant number of queries for the whole result list.
        chunk_rows: dict[str, tuple[str, str, str]] = {}
        by_chunk = [info["chunk_id"] for aid, info in ranked if info["chunk_id"]]
        if by_chunk:
            rows = conn.execute(
                "SELECT c.id AS chunk_id, a.title, a.kind, c.text AS snippet"
                " FROM chunks c JOIN artifacts a ON a.id = c.artifact_id"
                " WHERE c.id IN (SELECT value FROM json_each(?))",
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
                " WHERE id IN (SELECT value FROM json_each(?))",
                (json.dumps(by_face),),
            ).fetchall()
            face_rows = {row["id"]: (row["title"], row["kind"]) for row in rows}

        # An entity-only match without a stored fact shows the artifact's own
        # opening text; those reads batch into two queries for all of them.
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
                # An entity-only match shows the enriched line that bridged the
                # vocabulary gap - "Theodore Roosevelt - 26th US President..." -
                # which explains the match better than the artifact's face.
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
                    # Q.2: per-leg signals at the fusion point. The relevance
                    # floor (Q.3) reads these to drop gibberish-query hits.
                    "dense_similarity": round(dense_sims.get(aid, 0.0), 6),
                    "had_lexical_hit": aid in lexical_aids,
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
    """Batched artifact_text: all bodies in one query, all chunk text in one more (P.2d).

    A rollup of N candidates used to cost 2N queries (one body probe, one
    chunk probe per text-less artifact). The batch reads every body in one
    json_each query and every missing body's chunks in a second, returning
    the same per-id text the per-artifact function would, in `ids` order with
    duplicates dropped.
    """
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
    """The text a judgment reads. A note has a body; a capture has its chunks."""
    return artifact_texts(conn, [artifact_id], max_words)[artifact_id]
