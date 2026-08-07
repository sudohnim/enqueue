"""The /search rollup: one row per artifact, chunk + facet fusion.

Phase 22. Search used to return raw chunk hits, so six chunks of one note
occupied six result slots and a facet-only match had no row at all. The
rollup turns chunk and facet hits into one ranked row per artifact (an
artifact cannot occupy every slot), and the /doctor gate means the endpoint
is only reachable when the index is current.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from enqueue import config, db
from enqueue.api import app
from enqueue.index import bootstrap
from enqueue.index.store import get_store
from enqueue.retrieve.candidates import search_results

_BODY = "A city can feed itself from its rooftops, one tray of greens at a time."
_UNRELATED = "The ziggurat of Ur stood in the desert, season after season."


@pytest.fixture
def sqlite_store(store, monkeypatch):
    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    s = get_store()
    s.ensure()
    yield s
    get_store.cache_clear()


def _note(conn, aid, title, body):
    conn.execute(
        "INSERT INTO artifacts (id, kind, title, body, content_hash, status,"
        " created_at, updated_at) VALUES (?, 'note', ?, ?, ?, 'ok',"
        " datetime('now'), datetime('now'))",
        (aid, title, body, aid + "_hash"),
    )


def _chunk(conn, cid, aid, ordinal, text):
    conn.execute(
        "INSERT INTO chunks (id, artifact_id, ordinal, text, chunker)"
        " VALUES (?, ?, ?, ?, 'test')",
        (cid, aid, ordinal, text),
    )


def _facet(conn, fid, aid, level, statement, trust):
    conn.execute(
        "INSERT INTO facets (id, artifact_id, level, statement, model_version, trust)"
        " VALUES (?, ?, ?, ?, 'test-model', ?)",
        (fid, aid, level, statement, trust),
    )


class TestDedup:
    def test_six_chunks_of_one_artifact_return_it_once(self, sqlite_store):
        # One artifact whose six chunks all match the query; a second that
        # does not. The rollup must emit a1 exactly once, ranked first.
        conn = db.get_conn()
        try:
            _note(conn, "a1", "Rooftop farming", _BODY)
            for i in range(6):
                _chunk(conn, f"c{i}", "a1", i, _BODY)
            _note(conn, "a2", "The Ur dig", _UNRELATED)
            _chunk(conn, "c9", "a2", 0, _UNRELATED)
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        hits = search_results("rooftops", limit=20)
        ids = [h["artifact_id"] for h in hits]
        assert ids.count("a1") == 1, f"a1 appeared {ids.count('a1')} times: {ids}"
        assert ids[0] == "a1"
        assert hits[0]["why"] == "chunk"
        assert "rooftops" in hits[0]["snippet"].lower()

    def test_snippet_comes_from_the_best_chunk(self, sqlite_store):
        # The winning chunk's own text is the snippet, not a shorter chunk.
        conn = db.get_conn()
        try:
            _note(conn, "a1", "Rooftop farming", _BODY)
            _chunk(conn, "c1", "a1", 0, _BODY)
            _chunk(
                conn,
                "c2",
                "a1",
                1,
                "Rooftops and rooftops and rooftops: the city grows its greens above the street.",
            )
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        hits = search_results("rooftops", limit=20)
        assert hits[0]["artifact_id"] == "a1"
        assert "street" in hits[0]["snippet"].lower()


class TestFusion:
    def test_facet_only_match_still_returns_a_row(self, sqlite_store):
        # a2's chunks never mention the query, but its facet does: the facet
        # hit must surface the artifact, not disappear in the rollup.
        conn = db.get_conn()
        try:
            _note(conn, "a1", "Rooftop farming", _BODY)
            _chunk(conn, "c1", "a1", 0, _BODY)
            _note(conn, "a2", "Trade routes", "Goods moved along the river, season by season.")
            _chunk(conn, "c2", "a2", 0, "Goods moved along the river, season by season.")
            _facet(conn, "f1", "a2", 3, "Ziggurats rose above the mud-brick cities.", 0.9)
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()
        sqlite_store.upsert_facets()

        hits = search_results("ziggurat", limit=20)
        a2 = [h for h in hits if h["artifact_id"] == "a2"]
        assert a2, "a facet-only match must not vanish from search results"
        assert a2[0]["why"].startswith("facet")
        # Facet-only rows show the artifact face, not a chunk.
        assert "river" in a2[0]["snippet"].lower()


class TestSearchEndpoint:
    def test_endpoint_returns_deduplicated_rows(self, sqlite_store):
        conn = db.get_conn()
        try:
            _note(conn, "a1", "Rooftop farming", _BODY)
            for i in range(6):
                _chunk(conn, f"c{i}", "a1", i, _BODY)
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()
        # The /search gate: the index must be current before it answers.
        assert bootstrap.ensure_index()

        with TestClient(app) as client:
            resp = client.get("/search", params={"q": "rooftops"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "rooftops"
        ids = [h["artifact_id"] for h in body["hits"]]
        assert ids.count("a1") == 1

    def test_empty_query_returns_everything(self, sqlite_store):
        # An empty query means "everything", newest touch first. The embedding
        # store cannot answer an empty vector, and a request to group the whole
        # library plans into search(""), so the empty query reads the library
        # directly instead of crashing (or matching nothing).
        conn = db.get_conn()
        try:
            _note(conn, "a1", "Rooftop farming", _BODY)
            _note(conn, "a2", "The ziggurat", _UNRELATED)
            conn.commit()
        finally:
            conn.close()

        hits = search_results("")

        assert {h["artifact_id"] for h in hits} == {"a1", "a2"}
        assert all(h["why"] == "all" for h in hits)
