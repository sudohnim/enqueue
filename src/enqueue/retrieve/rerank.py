"""Rerank, and generate the placard while doing it.

The placard is produced here rather than in a separate call because the model has
already had to articulate why the artifact qualifies. Asking again would be both
wasteful and a chance to drift from the reasoning that earned the judgment.

Bounded concurrency, not sequential. A full evaluation is a judgment per artifact per
lens, and sequential turns that into hours, which produces an evaluation nobody runs.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress

from .. import config, db
from ..prompts import RERANK
from ..providers.base import get_provider
from ..schemas import Judgment, Verdict
from . import judgments
from .candidates import artifact_text


def _judge(lens: str, candidate: dict, text: str) -> Judgment | None:
    # A cached judgment is the whole point of Phase 8: the same lens, artifact
    # and model are not judged twice. Rebuilding the Judgment from the row
    # re-runs the validators, which is also the staleness check - an artifact
    # edited since the row was written no longer contains the evidence
    # verbatim, so the cached row is invalid and the artifact is judged fresh.
    cached = judgments.get(lens, candidate["artifact_id"])
    if cached is not None:
        # Rebuilding through model_validate re-runs the validators, with the
        # current artifact text as context. That is also the staleness check:
        # an artifact edited since the row was written no longer contains the
        # evidence verbatim, the rebuild fails, and the artifact is judged
        # fresh. The lens is deliberately absent from the context: the
        # lens-word placard gate is a fresh-judgment quality rule, not a
        # staleness signal, and a row that was accepted for this lens once is
        # not stale just because it shares a common word with the lens.
        try:
            return Judgment.model_validate(
                {
                    "artifact_id": candidate["artifact_id"],
                    "verdict": Verdict.BELONGS if cached["belongs"] else Verdict.NO,
                    "strength": cached["strength"],
                    "placard": cached["placard"],
                    "evidence": cached["evidence"],
                },
                context={"artifact_text": text},
            )
        except Exception:  # noqa: BLE001 - a stale row is a cache miss, not a failure
            return _judge_fresh(lens, candidate, text)
    return _judge_fresh(lens, candidate, text)


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
    return judgment


def rerank(lens: str, candidates: list[dict], keep: int = 15) -> dict:
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
    failed_ids = [
        candidate["artifact_id"]
        for candidate, judgment in zip(candidates, judgments, strict=True)
        if judgment is None
    ]

    for judgment in judgments:
        if judgment is None:
            continue
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
    return {
        "kept": belongs[:keep],
        # Everything that passed, before the cutoff threw the tail away. The wall's
        # topic view needs the whole passing list, not just the top of it.
        "relevant": belongs,
        "rejected": rejected,
        "rejected_count": len(rejected),
        "failed_ids": failed_ids,
        "failed": len(failed_ids),
        "considered": len(candidates),
    }
