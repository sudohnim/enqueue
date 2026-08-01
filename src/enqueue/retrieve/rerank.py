"""Rerank, and generate the placard while doing it.

The placard is produced here rather than in a separate call because the model has
already had to articulate why the artifact qualifies. Asking again would be both
wasteful and a chance to drift from the reasoning that earned the judgment.

Bounded concurrency, not sequential. A full evaluation is a judgment per artifact per
lens, and sequential turns that into hours, which produces an evaluation nobody runs.

The pooled result is cached keyed on the lens, the sorted candidate id list, and the
artifacts' `updated_at` signatures, so re-applying an unchanged lens to an unchanged
pool costs nothing, while an edit (which bumps `updated_at`) makes the next call
rebuild. The per-artifact judgment cache already makes re-judging cheap; this cache
skips the pool assembly and sorting on top of it. Bounded to a small LRU.
"""

from __future__ import annotations

import copy
import json
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress

from .. import config, db
from ..prompts import RERANK
from ..providers.base import get_provider
from ..schemas import Judgment, Verdict
from . import judgments
from .candidates import artifact_text

# Bounded pooled-result cache. key = (lens, sorted (id, updated_at) pairs).
_RERANK_CACHE_MAX = 32
_rerank_cache: OrderedDict[tuple, dict] = OrderedDict()


def _pool_signature(candidates: list[dict]) -> tuple[tuple[str, str], ...]:
    """(artifact_id, updated_at) per candidate, sorted.

    `updated_at` moves on every content change, so a pool that was edited is a
    different key and the pooled result is never served stale. The ids are
    sorted so two calls with the same pool in a different order hit the same
    entry.
    """
    ids = [c["artifact_id"] for c in candidates]
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, updated_at FROM artifacts" " WHERE id IN (SELECT value FROM json_each(?))",
            (json.dumps(ids),),
        ).fetchall()
        by_id = {r["id"]: r["updated_at"] for r in rows}
    finally:
        conn.close()
    return tuple(sorted((aid, by_id.get(aid, "")) for aid in ids))


def _cache_get(key: tuple) -> dict | None:
    if key not in _rerank_cache:
        return None
    _rerank_cache.move_to_end(key)
    return copy.deepcopy(_rerank_cache[key])


def _cache_put(key: tuple, result: dict) -> None:
    _rerank_cache[key] = copy.deepcopy(result)
    _rerank_cache.move_to_end(key)
    while len(_rerank_cache) > _RERANK_CACHE_MAX:
        _rerank_cache.popitem(last=False)


def _cache_clear() -> None:
    _rerank_cache.clear()


def _judge(lens: str, candidate: dict, text: str) -> tuple[Judgment | None, bool]:
    """A judgment for one artifact, plus whether it came from the cache.

    The boolean lets callers count actual model calls (the cost budget of the
    two-stage lens) without guessing from the judgment itself.
    """
    # A cached judgment is the whole point of Phase 8: the same lens, artifact
    # and model are not judged twice. Rebuilding the Judgment from the row
    # re-runs the validators, with the current artifact text as context. That
    # is also the staleness check: an artifact edited since the row was
    # written no longer contains the evidence verbatim, the rebuild fails,
    # and the artifact is judged fresh. The lens is deliberately absent from
    # the context: the lens-word placard gate is a fresh-judgment quality
    # rule, not a staleness signal, and a row that was accepted for this lens
    # once is not stale just because it shares a common word with the lens.
    cached = judgments.get(lens, candidate["artifact_id"])
    if cached is not None:
        try:
            return (
                Judgment.model_validate(
                    {
                        "artifact_id": candidate["artifact_id"],
                        "verdict": Verdict.BELONGS if cached["belongs"] else Verdict.NO,
                        "strength": cached["strength"],
                        "placard": cached["placard"],
                        "evidence": cached["evidence"],
                    },
                    context={"artifact_text": text},
                ),
                True,
            )
        except Exception:  # noqa: BLE001 - a stale row is a cache miss, not a failure
            pass
    return _judge_fresh(lens, candidate, text), False


def _judge_fresh(lens: str, candidate: dict, text: str) -> Judgment | None:
    # Retries come from config, and are low. A failed judgment is a dropped candidate,
    # not a crisis, and on the placeholder model the validators fail often enough that
    # extra attempts turn ten candidates into thirty-odd calls for nothing.
    try:
        judgment = get_provider().complete(
            system=RERANK,
            user=(
                f"Theme: {lens}\n\n"
                f"Artifact id: {candidate['artifact_id']}\n"
                f"Title: {candidate['title']}\n\n"
                f"{text}"
            ),
            response_model=Judgment,
            context={"artifact_text": text, "lens": lens},
        )
    except Exception:  # noqa: BLE001 - a failed judgment is a dropped candidate
        return None

    # Write-through. The judgment succeeded; a failure to remember it must not
    # turn a good judgment into a dropped candidate.
    with suppress(Exception):  # noqa: BLE001 - cache write failures are not judgment failures
        judgments.put(
            lens,
            judgment.artifact_id,
            judgment.verdict is Verdict.BELONGS,
            judgment.strength,
            judgment.placard,
            judgment.evidence,
        )
        # A fresh judgment means the artifact changed or was never judged;
        # any pooled result built from this pool is stale now.
        _cache_clear()
    return judgment


def judge_one(lens: str, candidate: dict) -> tuple[Judgment | None, bool]:
    """A single judgment for one candidate, for streaming applications.

    Same cache-first, write-through path as the pooled rerank, one artifact at
    a time so a caller can surface placards as they arrive.
    """
    conn = db.get_conn()
    try:
        text = artifact_text(conn, candidate["artifact_id"])
    finally:
        conn.close()
    return _judge(lens, candidate, text)


def rerank(lens: str, candidates: list[dict], keep: int = 15) -> dict:
    key = (lens, _pool_signature(candidates))
    cached = _cache_get(key)
    if cached is not None:
        # Re-validate before serving. An edit that did not change the key
        # (raw SQL, or any other path that skips the updated_at bump) and a
        # model switch must re-judge, not get the old pooled result. `_judge`
        # costs nothing for rows that still validate; a stale row falls
        # through to the normal path below, which re-judges it exactly once.
        conn = db.get_conn()
        try:
            texts = {c["artifact_id"]: artifact_text(conn, c["artifact_id"]) for c in candidates}
        finally:
            conn.close()
        if all(_judge(lens, c, texts[c["artifact_id"]])[1] for c in candidates):
            cached["hits"] = len(candidates)
            return cached
        _cache_clear()  # stale pool; rebuild below

    conn = db.get_conn()
    try:
        texts = {c["artifact_id"]: artifact_text(conn, c["artifact_id"]) for c in candidates}
    finally:
        conn.close()

    with ThreadPoolExecutor(max_workers=config.RERANK_CONCURRENCY) as pool:
        judgments = list(pool.map(lambda c: _judge(lens, c, texts[c["artifact_id"]]), candidates))

    by_id = {c["artifact_id"]: c for c in candidates}
    belongs: list[dict] = []
    rejected: list[dict] = []
    hits = 0
    failed_ids = [
        candidate["artifact_id"]
        for candidate, (judgment, _cached) in zip(candidates, judgments, strict=True)
        if judgment is None
    ]

    for judgment, from_cache in judgments:
        if judgment is None:
            continue
        if from_cache:
            hits += 1
        if judgment.verdict is not Verdict.BELONGS:
            rejected.append(
                {
                    "artifact_id": judgment.artifact_id,
                    "reason": judgment.reason,
                }
            )
            continue
        candidate = by_id.get(judgment.artifact_id)
        belongs.append(
            {
                "artifact_id": judgment.artifact_id,
                "title": candidate["title"] if candidate else "?",
                "strength": judgment.strength,
                "placard": judgment.placard,
                "evidence": judgment.evidence,
                "matched_facet_id": judgment.matched_facet_id
                or (candidate or {}).get("matched_facet_id"),
            }
        )

    belongs.sort(key=lambda j: j["strength"], reverse=True)
    result = {
        "kept": belongs[:keep],
        # Everything that passed, before the cutoff threw the tail away. The wall's
        # topic view needs the whole passing list, not just the top of it.
        "relevant": belongs,
        "rejected": rejected,
        "rejected_count": len(rejected),
        "failed_ids": failed_ids,
        "failed": len(failed_ids),
        # Judgments served from the cache. considered - hits is the number of
        # model calls actually made, which is the cost budget of the two-stage lens.
        "hits": hits,
        "considered": len(candidates),
    }
    _cache_put(key, result)
    return result
