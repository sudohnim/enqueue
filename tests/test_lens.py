"""The two-stage lens: bounded cost, whole-library coverage.

Stage one scores everything for free; stage two judges only the top of the
ranking. The tests pin the invariants: every artifact lands in exactly one
bucket, only judged artifacts carry placards, and model calls never scale
with the library size.
"""

from __future__ import annotations

import threading

import pytest

from enqueue import config, db, notes
from enqueue.index.store import get_store
from enqueue.ingest import chunk as chunk_mod
from enqueue.retrieve import lens, rerank
from enqueue.schemas import Judgment, Verdict

_PLACARD = "The claim outlasts the occasion that produced it."

# The lens is a near-verbatim quote of _BODY_A, so A ranks first and is the
# one artifact judged with judge_top=1.
_BODY_A = "Hydroponics feeds the city from a rooftop where the soil never was."
_BODY_B = "The commons is what we share, and sharing is what keeps it common."
_BODY_C = "Train stations have their own acoustics and their own clocks."
_BODY_D = "The garden was designed by someone who understood colour better than most."
_BODY_E = "A lens is a question the library answers at full strength."


@pytest.fixture
def scored_store(store, monkeypatch):
    qdrant = store / "qdrant"
    qdrant.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "QDRANT_PATH", qdrant)
    get_store.cache_clear()
    s = get_store()
    s.ensure()
    return s


def _chunk_and_index(scored_store, artifact_id: str) -> None:
    conn = db.get_conn()
    try:
        chunk_mod.chunk_artifact(conn, artifact_id)
        conn.commit()
    finally:
        conn.close()
    scored_store.upsert_chunks()


class _Scripted:
    """One judgment per artifact, looked up by id (thread-safe)."""

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
        reply = self.by_id[aid]
        if isinstance(reply, Exception):
            raise reply
        return reply


def _judgment(aid: str, verdict: Verdict) -> Judgment:
    if verdict is Verdict.BELONGS:
        return Judgment(
            artifact_id=aid,
            verdict=verdict,
            strength=5,
            placard=_PLACARD,
            evidence="Hydroponics feeds the city from a rooftop",
        )
    return Judgment(
        artifact_id=aid,
        verdict=verdict,
        strength=1,
        placard="Nothing in it advances the theme the room was built around.",
    )


def _make_library(store, bodies: list[str]) -> dict[str, dict]:
    """Create notes, chunk and index them, return id -> note dict."""
    notes_out = {}
    for body in bodies:
        note = notes.create(body)
        notes_out[note["artifact"]["id"]] = note["artifact"]
        _chunk_and_index(store, note["artifact"]["id"])
    return notes_out


class TestApplyLens:
    def test_every_artifact_in_exactly_one_bucket(self, store, quiet_queue, scored_store, monkeypatch):
        arts = _make_library(scored_store, [_BODY_A, _BODY_B, _BODY_C, _BODY_D, _BODY_E])
        provider = _Scripted({a["id"]: _judgment(a["id"], Verdict.BELONGS) for a in arts.values()})
        monkeypatch.setattr(rerank, "get_provider", lambda: provider)

        out = lens.apply_lens("hydroponics feeds the city from a rooftop", judge_top=1)

        ids = {a["id"] for a in arts.values()}
        assert len(out["related"]) + len(out["other"]) == len(ids)
        assert {e["artifact_id"] for e in out["related"]} | {
            e["artifact_id"] for e in out["other"]
        } == ids
        assert {e["artifact_id"] for e in out["related"]} & {
            e["artifact_id"] for e in out["other"]
        } == set()

    def test_judged_carry_placards_unjudged_never(self, store, quiet_queue, scored_store, monkeypatch):
        arts = _make_library(scored_store, [_BODY_A, _BODY_B])
        a_id = arts.pop(next(iter(arts)))
        # Rebuild a deterministic map: judge only the hydroponics note.
        by_id = {}
        for art in arts.values():
            by_id[art["id"]] = _judgment(art["id"], Verdict.NO)
        by_id[a_id["id"]] = _judgment(a_id["id"], Verdict.BELONGS)
        monkeypatch.setattr(rerank, "get_provider", lambda: _Scripted(by_id))

        out = lens.apply_lens("hydroponics feeds the city from a rooftop", judge_top=1)

        for entry in out["related"] + out["other"]:
            if entry["artifact_id"] == a_id["id"]:
                assert entry["judged"] is True
                assert "placard" in entry
                assert entry["placard"] == _PLACARD
            else:
                assert entry["judged"] is False
                assert "placard" not in entry

    def test_model_calls_never_exceed_judge_top(self, store, quiet_queue, scored_store, monkeypatch):
        arts = _make_library(scored_store, [_BODY_A, _BODY_B, _BODY_C, _BODY_D, _BODY_E])
        provider = _Scripted({a["id"]: _judgment(a["id"], Verdict.BELONGS) for a in arts.values()})
        monkeypatch.setattr(rerank, "get_provider", lambda: provider)

        out = lens.apply_lens("hydroponics feeds the city from a rooftop", judge_top=2)
        assert out["model_calls"] == 2

    def test_second_run_of_same_lens_costs_nothing(self, store, quiet_queue, scored_store, monkeypatch):
        arts = _make_library(scored_store, [_BODY_A, _BODY_B, _BODY_C])
        provider = _Scripted({a["id"]: _judgment(a["id"], Verdict.BELONGS) for a in arts.values()})
        monkeypatch.setattr(rerank, "get_provider", lambda: provider)

        first = lens.apply_lens("hydroponics feeds the city from a rooftop", judge_top=1)
        second = lens.apply_lens("hydroponics feeds the city from a rooftop", judge_top=1)

        assert first["model_calls"] == 1
        assert second["model_calls"] == 0

    def test_rejected_goes_to_other_even_above_threshold(self, store, quiet_queue, scored_store, monkeypatch):
        # The two strongest matches both get judged; the model rejects both.
        # The model's word outranks the score, so even a high-scoring rejected
        # artifact lands in `other`, never in `related`.
        arts = _make_library(scored_store, [_BODY_A, _BODY_D, _BODY_E])
        provider = _Scripted(
            {a["id"]: _judgment(a["id"], Verdict.NO) for a in arts.values()}
        )
        monkeypatch.setattr(rerank, "get_provider", lambda: provider)

        out = lens.apply_lens("hydroponics feeds the city from a rooftop", judge_top=2)
        assert out["judged"] == 2
        assert all(e["judged"] for e in out["other"][:2])
        assert all(e["judged"] is False for e in out["related"])


class TestCoverage:
    def test_uncapped_run_reports_complete(self, store, quiet_queue, scored_store, monkeypatch):
        arts = _make_library(scored_store, [_BODY_A, _BODY_B, _BODY_C])
        monkeypatch.setattr(
            rerank, "get_provider", lambda: _Scripted({a["id"]: _judgment(a["id"], Verdict.NO) for a in arts.values()})
        )

        out = lens.apply_lens("hydroponics feeds the city from a rooftop", judge_top=1)

        assert out["coverage"] == "complete"
        assert out["total_count"] == 3
        assert out["judged_count"] == 1
        assert out["scored_count"] >= 1
        assert out["total_count"] == len(out["related"]) + len(out["other"])

    def test_capped_run_reports_partial(self, store, quiet_queue, scored_store, monkeypatch):
        arts = _make_library(scored_store, [_BODY_A, _BODY_B, _BODY_C, _BODY_D, _BODY_E])
        monkeypatch.setattr(
            rerank, "get_provider", lambda: _Scripted({a["id"]: _judgment(a["id"], Verdict.NO) for a in arts.values()})
        )

        # A window of 2 chunks cannot cover a library with more chunks than
        # that: coverage must say partial, never complete.
        out = lens.apply_lens("hydroponics feeds the city from a rooftop", judge_top=1, score_cap=2)
        assert out["coverage"] == "partial"
        assert out["total_count"] == 5
