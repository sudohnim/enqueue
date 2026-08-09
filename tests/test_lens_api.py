"""The lens endpoint: ephemeral, paged, pins stay pinned (D2).

POST /lens splits the wall for a topic without leaving a trace: no room is
written, no updated_at moves, no artifact changes. Pinned artifacts stay on
their shelf above both sections and are not bucketed.
"""

from __future__ import annotations

import pytest

from enqueue import db, notes
from enqueue.api import LensRequest, _consume_lens
from enqueue.index.store import get_store
from enqueue.ingest import chunk as chunk_mod
from enqueue.retrieve import rerank
from enqueue.schemas import Judgment, Room, Verdict

_BODY_A = "Hydroponics feeds the city from a rooftop where the soil never was."
_BODY_B = "The commons is what we share, and sharing is what keeps it common."
_BODY_C = "Train stations have their own acoustics and their own clocks."
_PLACARD = "The claim outlasts the occasion that produced it."


@pytest.fixture
def scored_store(store):
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
    def test_ephemeral_leaves_updated_at_unchanged(
        self, store, quiet_queue, scored_store, monkeypatch
    ):
        arts = _make_library(scored_store, [_BODY_A, _BODY_B, _BODY_C])
        _scripted_for([a["id"] for a in arts], monkeypatch=monkeypatch)
        before = {a["id"]: a["updated_at"] for a in arts}

        _consume_lens(LensRequest(lens="hydroponics feeds the city from a rooftop", judge_top=1))

        conn = db.get_conn()
        try:
            after = {
                r["id"]: r["updated_at"]
                for r in conn.execute("SELECT id, updated_at FROM artifacts")
            }
        finally:
            conn.close()
        assert after == before

    def test_pinned_stay_pinned_above_both_sections(
        self, store, quiet_queue, scored_store, monkeypatch
    ):
        arts = _make_library(scored_store, [_BODY_A, _BODY_B, _BODY_C])
        pinned_id = arts[1]["id"]  # the commons note, deliberately unrelated
        conn = db.get_conn()
        try:
            conn.execute("UPDATE artifacts SET pinned = 1 WHERE id = ?", (pinned_id,))
            conn.commit()
        finally:
            conn.close()
        _scripted_for([a["id"] for a in arts], monkeypatch=monkeypatch)

        out = _consume_lens(
            LensRequest(lens="hydroponics feeds the city from a rooftop", judge_top=1)
        )

        pinned_ids = {e["artifact_id"] for e in out["pinned"]}
        assert pinned_id in pinned_ids
        assert pinned_id not in {e["artifact_id"] for e in out["related"]}
        assert pinned_id not in {e["artifact_id"] for e in out["other"]}

    def test_entries_carry_wall_fields(self, store, quiet_queue, scored_store, monkeypatch):
        arts = _make_library(scored_store, [_BODY_A])
        _scripted_for([a["id"] for a in arts], monkeypatch=monkeypatch)

        out = _consume_lens(
            LensRequest(lens="hydroponics feeds the city from a rooftop", judge_top=1)
        )
        entry = out["related"][0]
        # The wall fields the client renders, with no second call.
        for field in ("id", "kind", "title", "excerpt", "created_at", "updated_at", "pinned"):
            assert field in entry, field
        assert entry["kind"] == "note"
        assert entry["pinned"] == 0

    def test_paging_reports_more(self, store, quiet_queue, scored_store, monkeypatch):
        arts = _make_library(scored_store, [_BODY_A, _BODY_B, _BODY_C])
        _scripted_for([a["id"] for a in arts], monkeypatch=monkeypatch)

        out = _consume_lens(
            LensRequest(
                lens="hydroponics feeds the city from a rooftop", judge_top=1, limit=2, offset=0
            )
        )
        assert len(out["related"]) + len(out["other"]) == 2
        assert out["related_total"] + out["other_total"] == 3
        assert out["related_more"] or out["other_more"]


class TestLensStreamingHttp:
    def test_endpoint_streams_split_before_judgments(
        self, store, quiet_queue, scored_store, monkeypatch
    ):
        # The HTTP contract: POST /lens is a text/event-stream whose first
        # event is the split. The client opens the wall before the model
        # finishes judging.
        from fastapi.testclient import TestClient

        from enqueue.api import app

        arts = _make_library(scored_store, [_BODY_A, _BODY_B, _BODY_C])
        _scripted_for([a["id"] for a in arts], monkeypatch=monkeypatch)

        with TestClient(app) as client:
            resp = client.post(
                "/lens",
                json={"lens": "hydroponics feeds the city from a rooftop", "judge_top": 1},
            )
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            first, *rest = resp.text.split("data: ")[1:]
            import json as _json

            split = _json.loads(first.strip())
            assert split["stage"] == "split"
            assert len(split["judging"]) == 1
            assert any(
                e["stage"] == "done" for e in (_json.loads(r.strip()) for r in rest if r.strip())
            )


class TestCurateHttp:
    """POST /curate returns the synthesized room and writes nothing.

    The curate flow is ephemeral by design: the room is the response payload and
    there is no save path, so the response carries no saved_id.
    """

    def test_curate_returns_room_and_writes_nothing(
        self, store, quiet_queue, scored_store, monkeypatch
    ):
        from fastapi.testclient import TestClient

        from enqueue.api import app
        from enqueue.retrieve import curate as curate_mod
        from enqueue.retrieve import expand as expand_mod
        from enqueue.retrieve import rerank

        arts = _make_library(scored_store, [_BODY_A, _BODY_B, _BODY_C])

        class _Scripted:
            def complete(self, system, user, response_model, context=None, max_retries=None):
                if response_model is Room:
                    return Room(
                        suggested_name="The rooftop commons",
                        through_line="The city feeds itself from what it shares.",
                    )
                for line in user.splitlines():
                    if line.startswith("Artifact id: "):
                        aid = line.removeprefix("Artifact id: ")
                        break
                else:
                    raise AssertionError(f"no artifact id in prompt: {user!r}")
                return Judgment(
                    artifact_id=aid,
                    verdict=Verdict.BELONGS,
                    strength=4,
                    placard=_PLACARD,
                    evidence="Hydroponics feeds the city from a rooftop",
                )

        # Each stage imports get_provider into its own module, so the stub has
        # to replace all three bindings the curate flow calls through.
        for mod in (rerank, expand_mod, curate_mod):
            monkeypatch.setattr(mod, "get_provider", lambda: _Scripted())

        with TestClient(app) as client:
            resp = client.post(
                "/curate",
                json={"lens": "hydroponics feeds the city from a rooftop", "keep": 2, "pool": 50},
            )
            assert resp.status_code == 200
            body = resp.json()
            # No persistence path exists, so there is nothing to report as saved.
            assert "saved_id" not in body
            room = body["room"]
            assert room["suggested_name"] == "The rooftop commons"
            assert room["through_line"] == "The city feeds itself from what it shares."
            assert len(body["kept"]) == 2
            kept_ids = [k["artifact_id"] for k in body["kept"]]
            assert set(kept_ids) <= {a["id"] for a in arts}
