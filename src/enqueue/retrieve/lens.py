"""The two-stage lens: bounded cost, whole-library coverage.

Stage one (`score_all`) ranks every artifact with vector + keyword search and
no model calls. Stage two takes the top `judge_top` by score and gets a
judgment for each, reusing the Phase 8 cache. Everything below the slice is
bucketed by the score threshold alone. The cost of a lens is therefore
bounded by `judge_top` model calls, never by the library size.

Every non-deleted, non-pinned artifact ends up in exactly one bucket:
`related` (judged belonging, or unjudged above threshold) or `other`. A
judgment that failed is not a judgment: that artifact is marked
`judged: false` and bucketed by score (decision D3 - never claim a judgment
that did not happen). Pinned artifacts stay pinned, above both sections
(decision D2); they are not bucketed and not judged.

`apply_lens` is the synchronous form: stage two runs to completion before
anything is returned. `split_and_judge` is the streaming form: the split
comes out as soon as stage one finishes, then placards arrive judgment by
judgment, so the person sees the two sections before the model has spoken.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator

from .. import config, db
from ..schemas import Verdict
from . import rerank
from .score import score_all

log = logging.getLogger(__name__)


def _clamp_top(judge_top: int | None) -> int:
    """The number of judgments this application may ask for.

    Judge Top is a person asking for more: \"check more of the wall\". The cap
    bounds one request so a single ask cannot spend the library's entire
    judgment budget; raising it is a config decision.
    """
    top = config.LENS_JUDGE_TOP if judge_top is None else judge_top
    return min(top, config.LENS_JUDGE_TOP_MAX)


def _library_shape() -> tuple[dict[str, str], int, set[str]]:
    conn = db.get_conn()
    try:
        titles = {
            r["id"]: r["title"]
            for r in conn.execute("SELECT id, title FROM artifacts WHERE deleted_at IS NULL")
        }
        chunk_count = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
        pinned_ids = {
            r["id"]
            for r in conn.execute(
                "SELECT id FROM artifacts WHERE deleted_at IS NULL AND pinned = 1"
            )
        }
        return titles, chunk_count, pinned_ids
    finally:
        conn.close()


def _ranked(scores: dict[str, float], pinned_ids: set[str]) -> list[tuple[str, float]]:
    return [
        (aid, score)
        for aid, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        # D2: pins stay pinned, above both sections. A topic view is temporary
        # and must not disturb deliberate pins, so pinned artifacts are not
        # sorted into related or other, and are not judged - their bucket is
        # irrelevant, and judging them would spend model calls on a shelf that
        # does not move.
        if aid not in pinned_ids
    ]


def _buckets(
    ranked: list[tuple[str, float]],
    belongs: dict[str, dict],
    rejected: set[str],
    failed: set[str],
    threshold: float,
    titles: dict[str, str],
    scores: dict[str, float],
    pinned_ids: set[str],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Split the ranked library into related, other, and pinned.

    The bucketing rule is the same for the synchronous and the streaming
    paths: a judged-belongs artifact is related with its placard; a
    rejected artifact is other - the model's word outranks the score, a
    strong score on the wrong artifact does not make it related; a failed
    judgment is not a judgment (D3), so that artifact is bucketed by score
    and carries no placard; everything else is related above the threshold,
    other below it.
    """
    related_judged: list[dict] = []
    related_unjudged: list[dict] = []
    other: list[dict] = []

    for aid, score in ranked:
        entry = {
            "artifact_id": aid,
            "title": titles.get(aid, "?"),
            "score": score,
            "judged": aid in belongs or aid in rejected or aid in failed,
        }
        if aid in belongs:
            entry.update(
                {
                    "strength": belongs[aid]["strength"],
                    "placard": belongs[aid]["placard"],
                    "evidence": belongs[aid]["evidence"],
                }
            )
            related_judged.append(entry)
        elif aid in rejected:
            other.append(entry)
        elif aid in failed:
            entry["judged"] = False
            (related_unjudged if score > threshold else other).append(entry)
        elif score > threshold:
            related_unjudged.append(entry)
        else:
            other.append(entry)

    # Related: judged items first, strongest placard first; then unjudged
    # above-threshold items, best score first. Other: score descending, so
    # near-misses appear first.
    related_judged.sort(key=lambda e: e["strength"], reverse=True)
    related_unjudged.sort(key=lambda e: e["score"], reverse=True)
    other.sort(key=lambda e: e["score"], reverse=True)

    pinned = [
        {
            "artifact_id": aid,
            "title": titles.get(aid, "?"),
            "score": scores.get(aid, 0.0),
            "judged": False,
        }
        for aid in pinned_ids
    ]
    return related_judged + related_unjudged, other, pinned


def apply_lens(lens: str, judge_top: int | None = None, score_cap: int | None = None) -> dict:
    """Split the whole library into `related` and `other` for this lens.

    `judge_top` overrides the default; `model_calls` reports how many
    judgments were actually made (cache hits cost nothing), and never exceeds
    `judge_top` no matter how big the library is. `score_cap` bounds the
    stage-one search window; when it caps the search below the chunk count,
    `coverage` is `partial` and the wall must not label the second section as
    not related (D3).
    """
    t0 = time.time()
    top = _clamp_top(judge_top)
    threshold = config.LENS_SCORE_THRESHOLD

    titles, chunk_count, pinned_ids = _library_shape()

    # Stage one: rank the whole library, no model calls. The coverage label
    # mirrors the window rule in score_all: a window narrower than the chunk
    # count means some chunks were never searched, and that must be said.
    scores = score_all(lens, cap=score_cap)
    stage_one = time.time() - t0
    window = chunk_count if score_cap is None else min(score_cap, chunk_count)
    coverage = "complete" if window >= chunk_count else "partial"
    ranked = _ranked(scores, pinned_ids)

    # Stage two: judge only the top of the ranking.
    judged_rows = ranked[:top]
    candidates = [
        {"artifact_id": aid, "title": titles.get(aid, "?")} for aid, _score in judged_rows
    ]
    result = rerank.rerank(lens, candidates, keep=top)

    belongs = {r["artifact_id"]: r for r in result["relevant"]}
    rejected = {r["artifact_id"] for r in result["rejected"]}
    failed = set(result["failed_ids"])

    related, other, pinned = _buckets(
        ranked, belongs, rejected, failed, threshold, titles, scores, pinned_ids
    )

    model_calls = result["considered"] - result["hits"]
    total = time.time() - t0
    log.info(
        "lens applied lens=%r stage_one=%.3fs total=%.3fs model_calls=%d cache_hits=%d "
        "coverage=%s artifacts=%d",
        lens,
        stage_one,
        total,
        model_calls,
        result["hits"],
        coverage,
        len(scores),
    )
    return {
        "lens": lens,
        "threshold": threshold,
        "coverage": coverage,
        "scored_count": len([s for s in scores.values() if s > 0]),
        "total_count": len(scores),
        "judged_count": len(belongs) + len(rejected) + len(failed),
        "model_calls": model_calls,
        "judge_top": top,
        "judge_top_cap": config.LENS_JUDGE_TOP_MAX,
        "related": related,
        "other": other,
        "pinned": pinned,
    }


def split_and_judge(
    lens: str, judge_top: int | None = None, score_cap: int | None = None
) -> Iterator[dict]:
    """Stream a lens application: split first, placards as they arrive.

    Yields three kinds of events. `split` arrives as soon as stage one
    finishes, with both sections already bucketed by score and every
    candidate marked `judged: false`; the person sees the wall immediately,
    and `judging` names the artifacts a judgment is coming for. `judgment`
    events follow, one per artifact in rank order, carrying the placard and
    the final placement (`verdict` is belongs, no, or failed); `from_cache`
    distinguishes a replay (instant) from a real model call. `done` closes
    with the totals.
    """
    t0 = time.time()
    top = _clamp_top(judge_top)
    threshold = config.LENS_SCORE_THRESHOLD

    titles, chunk_count, pinned_ids = _library_shape()
    scores = score_all(lens, cap=score_cap)
    stage_one = time.time() - t0
    window = chunk_count if score_cap is None else min(score_cap, chunk_count)
    coverage = "complete" if window >= chunk_count else "partial"
    ranked = _ranked(scores, pinned_ids)

    # The split as it stands without any judgment: the model has not spoken,
    # so every artifact is bucketed by score and every candidate says
    # judged: false.
    judged_rows = ranked[:top]
    related, other, pinned = _buckets(
        ranked, {}, set(), set(), threshold, titles, scores, pinned_ids
    )
    yield {
        "stage": "split",
        "lens": lens,
        "threshold": threshold,
        "coverage": coverage,
        "scored_count": len([s for s in scores.values() if s > 0]),
        "total_count": len(scores),
        "judged_count": 0,
        "model_calls": 0,
        "cache_hits": 0,
        "judge_top": top,
        "judge_top_cap": config.LENS_JUDGE_TOP_MAX,
        "judging": [aid for aid, _score in judged_rows],
        "judge_total": len(judged_rows),
        "related": related,
        "other": other,
        "pinned": pinned,
    }

    model_calls = 0
    cache_hits = 0
    judged = 0
    for aid, _score in judged_rows:
        candidate = {"artifact_id": aid, "title": titles.get(aid, "?")}
        judgment, from_cache = rerank.judge_one(lens, candidate)
        if from_cache:
            cache_hits += 1
        else:
            model_calls += 1
        if judgment is None:
            verdict = "failed"
            fields: dict = {}
        else:
            verdict = "belongs" if judgment.verdict is Verdict.BELONGS else "no"
            fields = {
                "strength": judgment.strength,
                "placard": judgment.placard,
                "evidence": judgment.evidence,
            }
        judged += 1
        yield {
            "stage": "judgment",
            "artifact_id": aid,
            "verdict": verdict,
            "judged": verdict != "failed",
            "from_cache": from_cache,
            "judged_so_far": judged,
            "judge_total": len(judged_rows),
            **fields,
        }

    total = time.time() - t0
    log.info(
        "lens streamed lens=%r stage_one=%.3fs total=%.3fs model_calls=%d cache_hits=%d "
        "coverage=%s artifacts=%d",
        lens,
        stage_one,
        total,
        model_calls,
        cache_hits,
        coverage,
        len(scores),
    )
    yield {
        "stage": "done",
        "lens": lens,
        "coverage": coverage,
        "scored_count": len([s for s in scores.values() if s > 0]),
        "total_count": len(scores),
        "judged_count": judged,
        "model_calls": model_calls,
        "cache_hits": cache_hits,
        "judge_top": top,
        "judge_top_cap": config.LENS_JUDGE_TOP_MAX,
    }
