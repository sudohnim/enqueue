"""Rerank, and generate the placard while doing it.

The placard is produced here rather than in a separate call because the model has
already had to articulate why the artifact qualifies. Asking again would be both
wasteful and a chance to drift from the reasoning that earned the judgment.

Bounded concurrency, not sequential. A full evaluation is a judgment per artifact per
lens, and sequential turns that into hours, which produces an evaluation nobody runs.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from .. import config, db
from ..prompts import RERANK
from ..providers.base import get_provider
from ..schemas import Judgment, Verdict
from .candidates import artifact_text


def _judge(lens: str, candidate: dict, text: str) -> Judgment | None:
    # Retries come from config, and are low. A failed judgment is a dropped candidate,
    # not a crisis, and on the placeholder model the validators fail often enough that
    # extra attempts turn ten candidates into thirty-odd calls for nothing.
    try:
        return get_provider().complete(
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


def rerank(lens: str, candidates: list[dict], keep: int = 15) -> dict:
    conn = db.get_conn()
    try:
        texts = {c["artifact_id"]: artifact_text(conn, c["artifact_id"]) for c in candidates}
    finally:
        conn.close()

    with ThreadPoolExecutor(max_workers=config.RERANK_CONCURRENCY) as pool:
        judgments = list(pool.map(lambda c: _judge(lens, c, texts[c["artifact_id"]]), candidates))

    by_id = {c["artifact_id"]: c for c in candidates}
    belongs, rejected, failed = [], 0, 0

    for judgment in judgments:
        if judgment is None:
            failed += 1
            continue
        if judgment.verdict is not Verdict.BELONGS:
            rejected += 1
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
        "rejected": rejected,
        "failed": failed,
        "considered": len(candidates),
    }
