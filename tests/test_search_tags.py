"""Tag filters in search: `#tag` and `tag:word` are filters, not text to rank.

A pure tag query must never touch the index (that is the whole point of the
fast path), and a mixed query must keep only hits that both match the free
text and carry the tag. A plain query has to come back byte-identical.
"""

from __future__ import annotations

import pytest

from enqueue import config, db, tags
from enqueue.index.store import get_store
from enqueue.retrieve.candidates import search_results

_BODY = "A city can feed itself from its rooftops, one tray of greens at a time."


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


class TestParseTags:
    def test_mixed_query(self):
        assert tags.parse_tags("kubernetes #work tag:urgent") == ("kubernetes", ["work", "urgent"])

    def test_pure_tag_query(self):
        assert tags.parse_tags("#work") == ("", ["work"])
        assert tags.parse_tags("tag:urgent") == ("", ["urgent"])

    def test_plain_query_has_no_tags(self):
        assert tags.parse_tags("plain query") == ("plain query", [])

    def test_names_are_normalized(self):
        assert tags.parse_tags("#Work tag:URGENT") == ("", ["work", "urgent"])

    def test_a_bare_prefix_is_not_a_tag(self):
        assert tags.parse_tags("#") == ("#", [])
        assert tags.parse_tags("tag:") == ("tag:", [])
        # With the space, "#" is one bare token and "Work" is free text.
        assert tags.parse_tags("#  Work") == ("# Work", [])


class TestPureTagQuery:
    def test_returns_exactly_the_tagged_artifacts(self, store, quiet_queue):
        conn = db.get_conn()
        try:
            _note(conn, "a1", "First", "One.")
            _note(conn, "a2", "Second", "Two.")
            _note(conn, "a3", "Third", "Three.")
            conn.commit()
        finally:
            conn.close()
        tags.add("a1", "work")
        tags.add("a2", "work")

        hits = search_results("#work")
        assert {h["artifact_id"] for h in hits} == {"a1", "a2"}
        for h in hits:
            assert h["why"] == "tag"
            assert h["score"] == 0.0

    def test_no_artifacts_carry_the_tag(self, store, quiet_queue):
        assert search_results("#nothing-here") == []

    def test_tag_prefix_syntax(self, store, quiet_queue):
        conn = db.get_conn()
        try:
            _note(conn, "a1", "First", "One.")
            conn.commit()
        finally:
            conn.close()
        tags.add("a1", "work")

        hits = search_results("tag:work")
        assert [h["artifact_id"] for h in hits] == ["a1"]


class TestMixedQuery:
    def test_keeps_only_hits_that_match_and_carry_the_tag(self, sqlite_store):
        conn = db.get_conn()
        try:
            _note(conn, "a1", "Rooftop farming", _BODY)
            _chunk(conn, "c1", "a1", 0, _BODY)
            _note(conn, "a2", "Rooftop feeding", _BODY)
            _chunk(conn, "c2", "a2", 0, _BODY)
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()
        tags.add("a1", "work")

        hits = search_results("rooftops #work")
        assert [h["artifact_id"] for h in hits] == ["a1"]


class TestPlainQueryUnaffected:
    def test_untagged_matches_still_rank(self, sqlite_store):
        conn = db.get_conn()
        try:
            _note(conn, "a1", "Rooftop farming", _BODY)
            _chunk(conn, "c1", "a1", 0, _BODY)
            _note(conn, "a2", "Rooftop feeding", _BODY)
            _chunk(conn, "c2", "a2", 0, _BODY)
            conn.commit()
        finally:
            conn.close()
        sqlite_store.upsert_chunks()

        hits = search_results("rooftops")
        assert {h["artifact_id"] for h in hits} == {"a1", "a2"}
