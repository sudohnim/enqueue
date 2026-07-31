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
    """One judgment per artifact, looked up by id.

    Rerank judges candidates on a thread pool, so a list that is popped in
    completion order would race: the worker that picks a candidate second can
    call `complete` first, and the scripted replies would land on the wrong
    artifacts. Keying by artifact id (which the prompt always carries) makes
    the script deterministic no matter the scheduling.
    """

    def __init__(self, by_id):
        self.by_id = by_id
        self.calls = 0

    def complete(self, system, user, response_model, context=None, max_retries=None):
        self.calls += 1
        aid = _artifact_id(user)
        reply = self.by_id[aid]
        if isinstance(reply, Exception):
            raise reply
        return reply


def _artifact_id(user: str) -> str:
    for line in user.splitlines():
        if line.startswith("Artifact id: "):
            return line.removeprefix("Artifact id: ")
    raise AssertionError(f"no artifact id in prompt: {user!r}")


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
    def test_every_considered_artifact_is_accounted_for(self, store, quiet_queue, monkeypatch):
        # store: rerank now writes judgments to the cache, and the cache must
        # never touch the real library's database during a test.
        candidates = _candidates(6)
        provider = _Scripted(
            {
                "a000": _judgment("a000", Verdict.BELONGS),
                "a001": _judgment("a001", Verdict.NO, reason="about something else"),
                "a002": Exception("the model fell over"),
                "a003": _judgment("a003", Verdict.ADJACENT, reason="tangentially related"),
                "a004": _judgment("a004", Verdict.BELONGS),
                "a005": Exception("the model fell over"),
            }
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

    def test_kept_is_the_top_of_relevant(self, store, quiet_queue, monkeypatch):
        candidates = _candidates(4)
        provider = _Scripted(
            {
                "a000": _judgment("a000", Verdict.BELONGS),
                "a001": _judgment("a001", Verdict.BELONGS),
                "a002": _judgment("a002", Verdict.BELONGS),
                "a003": _judgment("a003", Verdict.BELONGS),
            }
        )
        monkeypatch.setattr(rerank, "get_provider", lambda: provider)

        out = rerank.rerank("any lens", candidates, keep=2)
        assert len(out["relevant"]) == 4
        assert len(out["kept"]) == 2
        assert out["rejected_count"] == 0
        assert out["failed_ids"] == []

    def test_rejected_still_carries_the_reason_when_absent(self, store, quiet_queue, monkeypatch):
        candidates = _candidates(1)
        provider = _Scripted({"a000": _judgment("a000", Verdict.NO, reason=None)})
        monkeypatch.setattr(rerank, "get_provider", lambda: provider)

        out = rerank.rerank("any lens", candidates, keep=2)
        assert out["rejected"] == [{"artifact_id": "a000", "reason": None}]
