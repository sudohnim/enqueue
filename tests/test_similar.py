"""More like this: live items closest to an artifact, from its passages' neighbours."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from enqueue import db
from enqueue.retrieve import passage_links

SHARED = "Wedging clay pushes trapped air out before the piece meets the kiln's heat."


@pytest.fixture
def sqlite_store(store, monkeypatch):
    from enqueue import config
    from enqueue.index.store import get_store

    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    s = get_store()
    s.ensure()
    yield s
    get_store.cache_clear()


def _note(aid: str, title: str, passages: list[str]) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, status, created_at,"
            " updated_at) VALUES (?, 'note', ?, 'x', ?, 'ok', ?, ?)",
            (aid, title, aid, db.now(), db.now()),
        )
        for i, text in enumerate(passages):
            conn.execute(
                "INSERT INTO chunks (id, artifact_id, ordinal, text, chunker)"
                " VALUES (?, ?, ?, ?, 'test')",
                (f"{aid}-{i}", aid, i, text),
            )


def test_similar_returns_the_other_note_first_and_not_itself(sqlite_store):
    _note("a", "Studio notes", ["# Studio notes\n\n" + SHARED])
    _note("b", "Clay basics", ["Clay basics\n\n" + SHARED])
    _note("c", "Sailing", ["Reef the mainsail before the squall arrives."])
    sqlite_store.upsert_chunks()

    hits = passage_links.similar_items("a")

    assert hits[0]["artifact_id"] == "b"
    assert "a" not in [h["artifact_id"] for h in hits]
    assert hits[0]["title"] == "Clay basics"
    assert SHARED[:20] in hits[0]["snippet"]


def test_the_endpoint_serves_them(sqlite_store):
    from enqueue.api.app import create_app

    _note("a", "Studio notes", [SHARED])
    _note("b", "Clay basics", [SHARED])
    sqlite_store.upsert_chunks()

    body = TestClient(create_app()).get("/artifacts/a/similar").json()

    assert body["hits"][0]["title"] == "Clay basics"
