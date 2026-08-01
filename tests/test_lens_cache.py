"""The lens judgment cache: same topic, same artifact, same model -> no second call.

Phase 8. The cache is keyed by a normalized lens hash plus artifact id plus
model version. The tests prove the normalization, the zero-call replay, the
re-judge on model change, and the stale-row fallthrough when an artifact is
edited after a judgment was cached.
"""

from __future__ import annotations

import threading

from enqueue import config, db, notes
from enqueue.retrieve import judgments, rerank
from enqueue.schemas import Judgment, Verdict

_BELONGS_PLACARD = "The claim outlasts the occasion that produced it."
_BELONGS_EVIDENCE = "a joint that moves outlasts one that does not"
_REJECT_PLACARD = "Nothing in it advances the theme the room was built around."
_BODY = "a joint that moves outlasts one that does not. The wall flexes or it cracks."


class _Scripted:
    """One judgment per artifact, looked up by id.

    Rerank judges candidates on a thread pool; a script consumed in call order
    would race. The prompt always carries "Artifact id: ...", so keying by id
    is deterministic under any scheduling.
    """

    def __init__(self, by_id):
        self.by_id = by_id
        self.calls = 0
        self._lock = threading.Lock()

    def complete(self, system, user, response_model, context=None, max_retries=None):
        with self._lock:
            self.calls += 1
        for line in user.splitlines():
            if line.startswith("Artifact id: "):
                aid = line.removeprefix("Artifact id: ")
                break
        else:
            raise AssertionError(f"no artifact id in prompt: {user!r}")
        script = self.by_id[aid]
        reply = script.pop(0) if isinstance(script, list) else script
        if isinstance(reply, Exception):
            raise reply
        return reply


def _judgment(aid: str, verdict: Verdict) -> Judgment:
    if verdict is Verdict.BELONGS:
        return Judgment(
            artifact_id=aid,
            verdict=verdict,
            strength=4,
            placard=_BELONGS_PLACARD,
            evidence=_BELONGS_EVIDENCE,
        )
    return Judgment(
        artifact_id=aid,
        verdict=verdict,
        strength=1,
        placard=_REJECT_PLACARD,
        reason="does not belong",
    )


def _candidates(aid: str) -> list[dict]:
    return [{"artifact_id": aid, "title": "Artifact"}]


class TestLensKey:
    def test_spelling_differences_collapse(self):
        a = judgments.lens_key("  How   Do We  SHARE the commons? ")
        b = judgments.lens_key("how do we share the commons?")
        assert a == b
        assert judgments.lens_key("") == judgments.lens_key("   ")

    def test_different_lenses_differ(self):
        assert judgments.lens_key("what is antifragility") != judgments.lens_key("what is a lens")


class TestCacheReplay:
    def test_second_run_makes_zero_model_calls(self, store, quiet_queue, monkeypatch):
        note = notes.create(_BODY)
        aid = note["artifact"]["id"]
        provider = _Scripted({aid: _judgment(aid, Verdict.BELONGS)})
        monkeypatch.setattr(rerank, "get_provider", lambda: provider)

        first = rerank.rerank("joints that move", _candidates(aid), keep=2)
        second = rerank.rerank("joints that move", _candidates(aid), keep=2)

        assert provider.calls == 1
        assert first["kept"][0]["artifact_id"] == aid
        assert second["kept"] == first["kept"]
        assert judgments.stats() == {"rows": 1, "lenses": 1}

    def test_pool_order_does_not_defeat_the_result_cache(self, store, quiet_queue, monkeypatch):
        # The same pool presented in a different order is the same key: the
        # pooled result is served without a second round of model calls.
        note_a = notes.create(_BODY)
        note_b = notes.create(_BODY + " Pinned to the wall it stays.")
        aid_a = note_a["artifact"]["id"]
        aid_b = note_b["artifact"]["id"]
        provider = _Scripted(
            {
                aid_a: _judgment(aid_a, Verdict.BELONGS),
                aid_b: _judgment(aid_b, Verdict.BELONGS),
            }
        )
        monkeypatch.setattr(rerank, "get_provider", lambda: provider)

        pool = [{"artifact_id": aid_a, "title": "A"}, {"artifact_id": aid_b, "title": "B"}]
        first = rerank.rerank("joints that move", pool, keep=2)
        second = rerank.rerank("joints that move", list(reversed(pool)), keep=2)

        assert provider.calls == 2  # both judgments came from the first run
        assert {r["artifact_id"] for r in second["relevant"]} == {aid_a, aid_b}
        assert first["hits"] == 0 and second["hits"] == 2

    def test_model_change_rejudges(self, store, quiet_queue, monkeypatch):
        note = notes.create(_BODY)
        aid = note["artifact"]["id"]
        provider = _Scripted({aid: _judgment(aid, Verdict.BELONGS)})
        monkeypatch.setattr(rerank, "get_provider", lambda: provider)

        rerank.rerank("joints that move", _candidates(aid), keep=2)
        monkeypatch.setattr(config, "LLM_MODEL", "a-different-model")
        rerank.rerank("joints that move", _candidates(aid), keep=2)

        # Two rows: one per model version, and both model calls happened.
        assert provider.calls == 2
        assert judgments.stats()["rows"] == 2

    def test_edited_artifact_is_judged_fresh(self, store, quiet_queue, monkeypatch):
        note = notes.create(_BODY)
        aid = note["artifact"]["id"]
        # The same artifact is judged twice in this test: once fresh, then
        # again after the edit. The first reply belongs, the second does not.
        provider = _Scripted({aid: [_judgment(aid, Verdict.BELONGS), _judgment(aid, Verdict.NO)]})
        monkeypatch.setattr(rerank, "get_provider", lambda: provider)

        rerank.rerank("joints that move", _candidates(aid), keep=2)

        # Edit the artifact so the cached evidence is no longer verbatim: the
        # stale row must fall through to a fresh judgment, not be served.
        conn = db.get_conn()
        try:
            conn.execute(
                "UPDATE artifacts SET body = ? WHERE id = ?",
                ("the draft is retracted and rewritten", aid),
            )
            conn.commit()
        finally:
            conn.close()

        out = rerank.rerank("joints that move", _candidates(aid), keep=2)
        assert provider.calls == 2
        assert out["rejected_count"] == 1

    def test_clear(self, store, quiet_queue, monkeypatch):
        note = notes.create(_BODY)
        aid = note["artifact"]["id"]
        monkeypatch.setattr(
            rerank, "get_provider", lambda: _Scripted({aid: _judgment(aid, Verdict.BELONGS)})
        )

        rerank.rerank("joints that move", _candidates(aid), keep=2)
        assert judgments.stats()["rows"] == 1
        assert judgments.clear() == 1
        assert judgments.stats() == {"rows": 0, "lenses": 0}
