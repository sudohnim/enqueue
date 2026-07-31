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
"""

from __future__ import annotations

from .. import config, db
from . import rerank
from .score import score_all


def apply_lens(lens: str, judge_top: int | None = None, score_cap: int | None = None) -> dict:
    """Split the whole library into `related` and `other` for this lens.

    `judge_top` overrides the default; `model_calls` reports how many
    judgments were actually made (cache hits cost nothing), and never exceeds
    `judge_top` no matter how big the library is. `score_cap` bounds the
    stage-one search window; when it caps the search below the chunk count,
    `coverage` is `partial` and the wall must not label the second section as
    not related (D3).
    """
    top = config.LENS_JUDGE_TOP if judge_top is None else judge_top
    threshold = config.LENS_SCORE_THRESHOLD

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
    finally:
        conn.close()

    # Stage one: rank the whole library, no model calls. The coverage label
    # mirrors the window rule in score_all: a window narrower than the chunk
    # count means some chunks were never searched, and that must be said.
    scores = score_all(lens, cap=score_cap)
    window = chunk_count if score_cap is None else min(score_cap, chunk_count)
    coverage = "complete" if window >= chunk_count else "partial"
    ranked = [
        (aid, score)
        for aid, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        # D2: pins stay pinned, above both sections. A topic view is temporary
        # and must not disturb deliberate pins, so pinned artifacts are not
        # sorted into related or other, and are not judged - their bucket is
        # irrelevant, and judging them would spend model calls on a shelf that
        # does not move.
        if aid not in pinned_ids
    ]

    # Stage two: judge only the top of the ranking.
    judged_rows = ranked[:top]
    candidates = [
        {"artifact_id": aid, "title": titles.get(aid, "?")} for aid, _score in judged_rows
    ]
    result = rerank.rerank(lens, candidates, keep=top)

    belongs = {r["artifact_id"]: r for r in result["relevant"]}
    rejected = {r["artifact_id"] for r in result["rejected"]}
    failed = set(result["failed_ids"])
    judged = belongs.keys() | rejected | failed

    related_judged: list[dict] = []
    related_unjudged: list[dict] = []
    other: list[dict] = []

    for aid, score in ranked:
        entry = {
            "artifact_id": aid,
            "title": titles.get(aid, "?"),
            "score": score,
            "judged": aid in judged,
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
            # The model said no. The model's word outranks the score: a strong
            # score on the wrong artifact does not make it related.
            other.append(entry)
        elif aid in failed:
            # The judgment call failed; D3 says no judgment happened, so this
            # artifact is bucketed by score and carries no placard.
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

    # The pinned shelf, above both sections (D2). They were not judged; they
    # carry the same shape so the client renders one kind of entry, minus the
    # placard fields a judgment would have added.
    pinned = [
        {
            "artifact_id": aid,
            "title": titles.get(aid, "?"),
            "score": scores.get(aid, 0.0),
            "judged": False,
        }
        for aid in pinned_ids
    ]

    return {
        "lens": lens,
        "threshold": threshold,
        "coverage": coverage,
        "scored_count": len([s for s in scores.values() if s > 0]),
        "total_count": len(scores),
        "judged": len(judged),
        "judged_count": len(judged),
        "model_calls": result["considered"] - result["hits"],
        "related": related_judged + related_unjudged,
        "other": other,
        "pinned": pinned,
    }
