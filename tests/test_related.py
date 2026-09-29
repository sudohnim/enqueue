"""Related artifacts: links between notes whose facets make the same point."""

from __future__ import annotations

import pytest

from enqueue import db
from enqueue.ingest import related
from enqueue.retrieve import candidates as cand

SHARED = "Structures last by yielding under stress rather than resisting it."


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


def _note(aid: str, statement: str, model: str | None = None) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, status, created_at,"
            " updated_at) VALUES (?, 'note', ?, 'x', ?, 'ok', ?, ?)",
            (aid, f"Note {aid}", aid, db.now(), db.now()),
        )
        conn.execute(
            "INSERT INTO facets (id, artifact_id, level, statement, model_version, trust)"
            " VALUES (?, ?, 3, ?, ?, 0.5)",
            (f"f-{aid}", aid, statement, model or cand._get_model(False)),
        )


def _links(aid: str) -> list[str]:
    conn = db.get_conn()
    try:
        return [r["id"] for r in related.for_artifact(conn, aid)]
    finally:
        conn.close()


def test_links_are_found_and_stored_both_ways(sqlite_store):
    _note("a", SHARED)
    _note("b", SHARED)
    sqlite_store.upsert_facets()

    assert related.compute("a") >= 1
    assert "b" in _links("a")
    assert "a" in _links("b")  # the older note gains the link too
    assert "a" not in _links("a")


def test_stale_facets_never_link(sqlite_store):
    _note("a", SHARED)
    _note("old", SHARED, model="a-retired-model")
    sqlite_store.upsert_facets()

    related.compute("a")

    assert "old" not in _links("a")


def test_recompute_replaces_links(sqlite_store):
    _note("a", SHARED)
    _note("b", SHARED)
    sqlite_store.upsert_facets()
    related.compute("a")
    with db.transaction() as conn:
        conn.execute("DELETE FROM facets WHERE artifact_id = 'b'")
    sqlite_store.upsert_facets()

    related.compute("a")

    assert _links("a") == [] and _links("b") == []


def test_trashed_notes_are_hidden_and_purge_removes_both_directions(sqlite_store):
    from enqueue import trash

    _note("a", SHARED)
    _note("b", SHARED)
    sqlite_store.upsert_facets()
    related.compute("a")

    trash.delete("b")
    assert "b" not in _links("a")

    trash.purge("b")
    conn = db.get_conn()
    try:
        left = conn.execute(
            "SELECT COUNT(*) AS n FROM related WHERE artifact_id = 'b' OR related_id = 'b'"
        ).fetchone()["n"]
    finally:
        conn.close()
    assert left == 0


def test_artifact_detail_carries_related(sqlite_store):
    from fastapi.testclient import TestClient

    from enqueue.api.app import create_app

    _note("a", SHARED)
    _note("b", SHARED)
    sqlite_store.upsert_facets()
    related.compute("a")

    body = TestClient(create_app()).get("/artifacts/a").json()

    assert [r["id"] for r in body["related"]] == ["b"]
    assert set(body["related"][0]) == {"id", "title", "kind", "score", "via"}


def _entity(aid: str, name: str, model: str | None = None) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO entities (id, artifact_id, entity, fact, model_version, trust)"
            " VALUES (?, ?, ?, 'a fact', ?, 0.5)",
            (f"e-{aid}-{name}", aid, name, model or cand._get_model(False)),
        )


def test_notes_that_name_the_same_thing_are_linked_with_the_name(sqlite_store):
    _note("a", "Kilns reward patience.")
    _note("b", "Markets punish haste.")
    _entity("a", "Nassim Taleb")
    _entity("b", "nassim taleb ")
    sqlite_store.upsert_facets()

    related.compute("a")

    conn = db.get_conn()
    try:
        links = related.for_artifact(conn, "b")
    finally:
        conn.close()
    assert [(r["id"], r["via"]) for r in links] == [("a", "Nassim Taleb")]


def test_common_names_and_stale_entities_link_nothing(sqlite_store):
    _note("a", "One.")
    _entity("a", "Google")
    _entity("a", "Old Name", model="a-retired-model")
    for i in range(related.MENTION_MAX_SHARED):
        _note(f"o{i}", f"Other {i}.")
        _entity(f"o{i}", "Google")
    _note("z", "Two.")
    _entity("z", "Old Name")
    sqlite_store.upsert_facets()

    related.compute("a")

    conn = db.get_conn()
    try:
        links = related.for_artifact(conn, "a")
    finally:
        conn.close()
    assert [r["via"] for r in links if r["via"]] == []
