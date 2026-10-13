"""The AI summary can be switched off for one artifact (the Details panel).

Off is the person's decision: no model reads the artifact again, what the model had
written goes, and what the person wrote stays. Nothing but the switch turns it back on.
"""

from __future__ import annotations

import pytest

from enqueue import config, db, notes
from enqueue.ingest import facets
from enqueue.ingest import queue as q


class _Model:
    model = "test-model"
    base_url = "http://127.0.0.1:11434/v1"

    def __init__(self):
        self.calls = 0

    def complete(self, *a, **k):
        self.calls += 1
        raise RuntimeError("no model in this test")


BODY = "Squats five by five, then rows and a long walk. " * 20


@pytest.fixture
def model(store, quiet_queue, monkeypatch):
    from enqueue.index.store import get_store
    from enqueue.ingest import context, entities, source
    from enqueue.providers import base

    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    get_store().ensure()
    fake = _Model()
    for module in (facets, entities, context, source, base):
        monkeypatch.setattr(module, "get_provider", lambda *a, **k: fake, raising=False)
    monkeypatch.setattr(q, "run_exclusive", lambda fn, **k: fn())
    yield fake
    get_store.cache_clear()


def _lines(aid: str) -> list[str]:
    return [f["statement"] for f in notes.get(aid)["facets"]]


def _machine_line(aid: str, statement: str) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO facets (id, artifact_id, level, statement, model_version, trust,"
            " body_version, edited) VALUES (?,?,?,?,?,?,?,0)",
            ("f-" + statement[:8], aid, 1, statement, "test-model", 0.5, db.now()),
        )


def test_off_keeps_the_model_away_and_the_words_searchable(model):
    aid = notes.create(body=BODY)["artifact"]["id"]
    facets.set_summary(aid, False)

    result = q.process(aid)

    assert result["chunks"] >= 1
    assert model.calls == 0
    detail = notes.get(aid)
    assert detail["summary_off"] is True
    assert detail["summary_generating"] is False
    assert detail["summary_waiting"] is False


def test_off_removes_the_models_lines_and_keeps_yours(model):
    aid = notes.create(body=BODY)["artifact"]["id"]
    _machine_line(aid, "A strength routine built on compound lifts.")
    facets.add_facet(aid, "My workout log.", 1)

    facets.set_summary(aid, False)

    assert _lines(aid) == ["My workout log."]


def test_off_survives_the_gate_and_a_regenerate(model):
    aid = notes.create(body=BODY)["artifact"]["id"]
    facets.set_summary(aid, False)

    facets.apply_eligibility_gate()
    answer = facets.regenerate(aid)

    assert notes.get(aid)["summary_off"] is True
    assert answer["count"] == 0
    assert model.calls == 0


def test_on_sends_it_back_to_be_read(model, quiet_queue):
    aid = notes.create(body=BODY)["artifact"]["id"]
    facets.set_summary(aid, False)
    quiet_queue.clear()

    facets.set_summary(aid, True)

    assert notes.get(aid)["summary_off"] is False
    assert quiet_queue == [aid]
    q.process(aid)
    assert model.calls > 0


def test_the_switch_over_the_api(model):
    from fastapi.testclient import TestClient

    from enqueue.api.app import create_app

    aid = notes.create(body=BODY)["artifact"]["id"]
    client = TestClient(create_app())

    off = client.put(f"/artifacts/{aid}/summary", json={"on": False})
    assert off.status_code == 200 and off.json()["summary_off"] is True
    on = client.put(f"/artifacts/{aid}/summary", json={"on": True})
    assert on.json()["summary_off"] is False
    assert client.put("/artifacts/nope/summary", json={"on": False}).status_code == 404
