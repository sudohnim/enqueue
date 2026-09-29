"""Passage connections: per passage, the other notes that say something close."""

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


def test_a_passage_links_to_the_note_that_says_the_same(sqlite_store):
    _note("a", "Studio notes", ["# Studio notes\n\n" + SHARED, "Invoices are due on Fridays."])
    _note("b", "Clay basics", [SHARED])
    _note("c", "Sailing", ["Reef the mainsail before the squall arrives."])
    sqlite_store.upsert_chunks()

    found = passage_links.for_artifact("a")

    assert [p["ordinal"] for p in found] == [0]
    assert found[0]["excerpt"].startswith("Wedging clay")
    assert [link["id"] for link in found[0]["links"]] == ["b"]


def test_trashed_notes_are_not_connections(sqlite_store):
    from enqueue import trash

    _note("a", "Studio notes", [SHARED])
    _note("b", "Clay basics", [SHARED])
    sqlite_store.upsert_chunks()
    trash.delete("b")

    assert passage_links.for_artifact("a") == []


def test_the_endpoint_serves_them(sqlite_store):
    from enqueue.api.app import create_app

    _note("a", "Studio notes", [SHARED])
    _note("b", "Clay basics", [SHARED])
    sqlite_store.upsert_chunks()

    body = TestClient(create_app()).get("/artifacts/a/connections").json()

    assert body["passages"][0]["links"][0]["title"] == "Clay basics"
