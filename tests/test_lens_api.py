"""The lens endpoint: ephemeral, paged, pins stay pinned (D2).

POST /lens splits the wall for a topic without leaving a trace: no exhibit is
written, no updated_at moves, no artifact changes. Pinned artifacts stay on
their shelf above both sections and are not bucketed.
"""

from __future__ import annotations


import pytest

from enqueue import config, db, notes
from enqueue.api import LensRequest, apply_lens_view
from enqueue.index.store import get_store
from enqueue.ingest import chunk as chunk_mod
from enqueue.retrieve import rerank
from enqueue.schemas import Judgment, Verdict

_BODY_A = "Hydroponics feeds the city from a rooftop where the soil never was."
_BODY_B = "The commons is what we share, and sharing is what keeps it common."
_BODY_C = "Train stations have their own acoustics and their own clocks."
_PLACARD = "The claim outlasts the occasion that produced it."


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


def _scripted_for(arts: list[str], monkeypatch, verdict: Verdict = Verdict.BELONGS) -> None:
    class _Scripted:
        def __init__(self, by_id):
            self.by_id = by_id

        def complete(self, system, user, response_model, context=None, max_retries=None):
            for line in user.splitlines():
                if line.startswith("Artifact id: "):
                    aid = line.removeprefix("Artifact id: ")
                    break
            else:
                raise AssertionError(f"no artifact id in prompt: {user!r}")
            return self.by_id[aid]

    by_id = {
        aid: Judgment(
            artifact_id=aid,
            verdict=verdict,
            strength=4,
            placard=_PLACARD,
            evidence="Hydroponics feeds the city from a rooftop",
        )
        for aid in arts
    }
    monkeypatch.setattr(rerank, "get_provider", lambda: _Scripted(by_id))


def _make_library(store, bodies: list[str]) -> list[dict]:
    arts = []
    for body in bodies:
        note = notes.create(body)
        arts.append(note["artifact"])
        _chunk_and_index(store, note["artifact"]["id"])
    return arts


class TestLensEndpoint:
    def test_ephemeral_leaves_updated_at_unchanged(self, store, quiet_queue, scored_store, monkeypatch):
        arts = _make_library(scored_store, [_BODY_A, _BODY_B, _BODY_C])
        _scripted_for([a["id"] for a in arts], monkeypatch=monkeypatch)
        before = {a["id"]: a["updated_at"] for a in arts}

        apply_lens_view(LensRequest(lens="hydroponics feeds the city from a rooftop", judge_top=1))

        conn = db.get_conn()
        try:
            after = {
                r["id"]: r["updated_at"]
                for r in conn.execute("SELECT id, updated_at FROM artifacts")
            }
        finally:
            conn.close()
        assert after == before

    def test_ephemeral_writes_no_exhibits(self, store, quiet_queue, scored_store, monkeypatch):
        arts = _make_library(scored_store, [_BODY_A, _BODY_B, _BODY_C])
        _scripted_for([a["id"] for a in arts], monkeypatch=monkeypatch)

        apply_lens_view(LensRequest(lens="hydroponics feeds the city from a rooftop", judge_top=1))

        conn = db.get_conn()
        try:
            n = conn.execute("SELECT COUNT(*) AS n FROM exhibits").fetchone()["n"]
        finally:
            conn.close()
        assert n == 0

    def test_pinned_stay_pinned_above_both_sections(self, store, quiet_queue, scored_store, monkeypatch):
        arts = _make_library(scored_store, [_BODY_A, _BODY_B, _BODY_C])
        pinned_id = arts[1]["id"]  # the commons note, deliberately unrelated
        conn = db.get_conn()
        try:
            conn.execute("UPDATE artifacts SET pinned = 1 WHERE id = ?", (pinned_id,))
            conn.commit()
        finally:
            conn.close()
        _scripted_for([a["id"] for a in arts], monkeypatch=monkeypatch)

        out = apply_lens_view(LensRequest(lens="hydroponics feeds the city from a rooftop", judge_top=1))

        pinned_ids = {e["artifact_id"] for e in out["pinned"]}
        assert pinned_id in pinned_ids
        assert pinned_id not in {e["artifact_id"] for e in out["related"]}
        assert pinned_id not in {e["artifact_id"] for e in out["other"]}

    def test_entries_carry_wall_fields(self, store, quiet_queue, scored_store, monkeypatch):
        arts = _make_library(scored_store, [_BODY_A])
        _scripted_for([a["id"] for a in arts], monkeypatch=monkeypatch)

        out = apply_lens_view(LensRequest(lens="hydroponics feeds the city from a rooftop", judge_top=1))
        entry = out["related"][0]
        # The wall fields the client renders, with no second call.
        for field in ("id", "kind", "title", "excerpt", "created_at", "updated_at", "pinned"):
            assert field in entry, field
        assert entry["kind"] == "note"
        assert entry["pinned"] == 0

    def test_paging_reports_more(self, store, quiet_queue, scored_store, monkeypatch):
        arts = _make_library(scored_store, [_BODY_A, _BODY_B, _BODY_C])
        _scripted_for([a["id"] for a in arts], monkeypatch=monkeypatch)

        out = apply_lens_view(LensRequest(lens="hydroponics feeds the city from a rooftop", judge_top=1, limit=2, offset=0))
        assert len(out["related"]) + len(out["other"]) == 2
        assert out["related_total"] + out["other_total"] == 3
        assert out["related_more"] or out["other_more"]
