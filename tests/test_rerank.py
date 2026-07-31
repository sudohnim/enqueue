"""Rerank: nothing a judgment decided is dropped without being counted.

The conservation law is the whole point of the Phase 6 change: every candidate
either belongs (relevant), is rejected (with a reason), or failed to judge
(failed_ids). The three lists must partition `considered`, and the old integer
fields keep their meaning for callers that read them.
"""

from __future__ import annotations

from enqueue.retrieve import rerank
from enqueue.schemas import Judgment, Verdict


class _Scripted:
    """One judgment per call, in the order rerank asks for them."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def complete(self, system, user, response_model, context=None, max_retries=None):
        self.calls += 1
        reply = self.script.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _judgment(artifact_id: str, verdict: Verdict, reason: str | None = None) -> Judgment:
    if verdict is Verdict.BELONGS:
        return Judgment(
            artifact_id=artifact_id,
            verdict=verdict,
            strength=4,
            placard="The claim outlasts the occasion that produced it.",
            evidence="a joint that moves outlasts one that does not",
        )
    return Judgment(
        artifact_id=artifact_id,
        verdict=verdict,
        strength=1,
        placard="Nothing in it advances the theme the room was built around.",
        reason=reason,
    )


def _candidates(n: int) -> list[dict]:
    return [{"artifact_id": f"a{i:03d}", "title": f"Artifact {i}"} for i in range(n)]


class TestConservation:
    def test_every_considered_artifact_is_accounted_for(self, monkeypatch):
        candidates = _candidates(6)
        provider = _Scripted(
            [
                _judgment("a000", Verdict.BELONGS),
                _judgment("a001", Verdict.NO, reason="about something else"),
                Exception("the model fell over"),
                _judgment("a003", Verdict.ADJACENT, reason="tangentially related"),
                _judgment("a004", Verdict.BELONGS),
                Exception("the model fell over"),
            ]
        )
        monkeypatch.setattr(rerank, "get_provider", lambda: provider)

        out = rerank.rerank("any lens", candidates, keep=2)

        assert out["considered"] == 6
        assert out["failed"] == 2
        assert len(out["failed_ids"]) == 2
        assert out["failed_ids"] == ["a002", "a005"]
        assert out["rejected_count"] == 2
        assert [r["artifact_id"] for r in out["rejected"]] == ["a001", "a003"]
        assert out["rejected"][0]["reason"] == "about something else"
        assert out["rejected"][1]["reason"] == "tangentially related"
        assert [r["artifact_id"] for r in out["relevant"]] == ["a000", "a004"]
        # keep truncation still applies to `kept` only; `relevant` is the full pass list
        assert [r["artifact_id"] for r in out["kept"]] == ["a000", "a004"]
        assert len(out["relevant"]) + out["rejected_count"] + len(out["failed_ids"]) == 6

    def test_kept_is_the_top_of_relevant(self, monkeypatch):
        candidates = _candidates(4)
        provider = _Scripted(
            [
                _judgment("a000", Verdict.BELONGS),
                _judgment("a001", Verdict.BELONGS),
                _judgment("a002", Verdict.BELONGS),
                _judgment("a003", Verdict.BELONGS),
            ]
        )
        monkeypatch.setattr(rerank, "get_provider", lambda: provider)

        out = rerank.rerank("any lens", candidates, keep=2)
        assert len(out["relevant"]) == 4
        assert len(out["kept"]) == 2
        assert out["rejected_count"] == 0
        assert out["failed_ids"] == []

    def test_rejected_still_carries_the_reason_when_absent(self, monkeypatch):
        candidates = _candidates(1)
        provider = _Scripted([_judgment("a000", Verdict.NO, reason=None)])
        monkeypatch.setattr(rerank, "get_provider", lambda: provider)

        out = rerank.rerank("any lens", candidates, keep=2)
        assert out["rejected"] == [{"artifact_id": "a000", "reason": None}]
