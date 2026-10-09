"""Which words of a search count, and which index rows a search may see.

Three regressions found on a real library:
- a question's filler words ("what", "the", "about") matched as substrings and let
  unrelated passages past the relevance floor in chat;
- the keyword leg required every word of a question, filler included, so a question
  in plain language had no keyword hits at all;
- a full index rebuild indexed the summaries of trashed and vaulted artifacts.
"""

from __future__ import annotations

import pytest
from enqueue.index.store import get_store
from enqueue.index.store_sqlite import _content_terms, _fts_query, _trigram_query

from enqueue import chats, config, db


@pytest.fixture
def sqlite_store(store, monkeypatch):
    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    s = get_store()
    s.ensure()
    yield s
    get_store.cache_clear()


def _note(conn, aid: str, title: str, body: str, deleted: bool = False) -> None:
    conn.execute(
        "INSERT INTO artifacts (id, kind, title, body, content_hash, status,"
        " created_at, updated_at, deleted_at) VALUES (?, 'note', ?, ?, ?, 'ok',"
        " datetime('now'), datetime('now'), ?)",
        (aid, title, body, aid + "_hash", "2026-01-01T00:00:00" if deleted else None),
    )
    conn.execute(
        "INSERT INTO chunks (id, artifact_id, ordinal, text, chunker)"
        " VALUES (?, ?, 0, ?, 'test')",
        ("c_" + aid, aid, body),
    )


def _library(sqlite_store) -> None:
    conn = db.get_conn()
    try:
        _note(conn, "a1", "Rooftop farms", "What the city eats is about to grow on rooftops.")
        _note(conn, "a2", "Temples", "The word ziggurat appears nowhere else in the library.")
        _note(conn, "a3", "Commons", "Sharing is what keeps the commons common.")
        conn.commit()
    finally:
        conn.close()
    sqlite_store.upsert_chunks()


class TestContentTerms:
    def test_filler_words_are_dropped(self):
        assert _content_terms("What did I save about the ziggurat?") == ["ziggurat?"]

    def test_a_short_search_is_a_name_and_keeps_every_word(self):
        assert _content_terms("the good life") == ["the", "good", "life"]

    def test_a_search_made_only_of_filler_keeps_its_words(self):
        assert _content_terms("what is it about") == ["what", "is", "it", "about"]

    def test_bare_punctuation_is_not_a_word(self):
        assert _content_terms("rooftops - 2024") == ["rooftops", "2024"]

    def test_queries_are_built_from_content_words(self):
        assert _fts_query("what about the ziggurat") == '"ziggurat"*'
        assert _trigram_query("what about the ziggurat") == '"ziggurat"'


class TestKeywordLeg:
    def test_a_plain_language_question_has_keyword_hits(self, sqlite_store):
        _library(sqlite_store)

        legs = sqlite_store.search_legs(sqlite_store.CHUNKS, "what did I save about the ziggurat?")

        assert [h["artifact_id"] for h in legs["keyword"]] == ["a2"]

    def test_every_content_word_must_be_in_the_passage(self, sqlite_store):
        _library(sqlite_store)

        apart = sqlite_store.search_legs(sqlite_store.CHUNKS, "is there a ziggurat on rooftops")
        together = sqlite_store.search_legs(sqlite_store.CHUNKS, "is the commons about sharing")

        assert apart["keyword"] == []
        assert [h["artifact_id"] for h in together["keyword"]] == ["a3"]


class TestChatFloor:
    def test_filler_words_do_not_carry_a_passage_past_the_floor(
        self, sqlite_store, quiet_queue, monkeypatch
    ):
        """ "what ... the ... about" sits inside a1 as substrings. That is not a match:
        with the judge ruling nothing relevant, the answer must be fed nothing."""
        from enqueue.retrieve import candidates as cand

        _library(sqlite_store)
        monkeypatch.setattr(cand, "judge_gray_zone", lambda question, hits: set())

        found = chats.passages("what is the quantum flux capacitor about", "library", None)

        assert found == [], f"filler words must not ground an answer, got {found}"

    def test_judged_passages_are_fed_in_ranked_order(self, sqlite_store, quiet_queue, monkeypatch):
        from enqueue.retrieve import candidates as cand

        _library(sqlite_store)
        monkeypatch.setattr(
            cand, "judge_gray_zone", lambda question, hits: {h["artifact_id"] for h in hits}
        )

        found = chats.passages("growing food in the city", "library", None)

        assert found and found[0]["artifact_id"] == "a1"


class TestHiddenArtifacts:
    def _with_trashed(self, sqlite_store) -> None:
        conn = db.get_conn()
        try:
            _note(conn, "live", "Kilns", "Cone six firing notes.")
            _note(conn, "gone", "Glazes", "Celadon over porcelain.", deleted=True)
            for aid in ("live", "gone"):
                conn.execute(
                    "INSERT INTO facets (id, artifact_id, level, statement, model_version, trust)"
                    " VALUES (?, ?, 1, ?, 'test-model', 0.5)",
                    ("f_" + aid, aid, f"A summary line of {aid}."),
                )
                conn.execute(
                    "INSERT INTO entities (id, artifact_id, entity, fact, model_version, trust)"
                    " VALUES (?, ?, ?, ?, 'test-model', 0.5)",
                    ("e_" + aid, aid, aid, f"A fact about {aid}."),
                )
            conn.commit()
        finally:
            conn.close()

    def test_a_rebuild_leaves_out_trashed_artifacts(self, sqlite_store):
        self._with_trashed(sqlite_store)

        sqlite_store.upsert_facets()
        sqlite_store.upsert_entities()

        counts = sqlite_store.counts()
        assert (counts["facets"], counts["fts_facets"]) == (1, 1)
        assert (counts["entities"], counts["fts_entities"]) == (1, 1)

    def test_prune_removes_rows_of_trashed_artifacts(self, sqlite_store):
        self._with_trashed(sqlite_store)
        conn = db.get_conn()
        try:  # indexed while live, trashed by a path that left the index alone
            conn.execute("UPDATE artifacts SET deleted_at = NULL WHERE id = 'gone'")
            conn.commit()
            sqlite_store.upsert_facets()
            sqlite_store.upsert_entities()
            conn.execute("UPDATE artifacts SET deleted_at = '2026-01-01' WHERE id = 'gone'")
            conn.commit()
        finally:
            conn.close()
        assert sqlite_store.counts()["facets"] == 2

        removed = sqlite_store.prune_orphans()

        counts = sqlite_store.counts()
        assert removed["facets"] == 1 and removed["entities"] == 1
        assert (counts["facets"], counts["fts_facets"]) == (1, 1)
        assert (counts["entities"], counts["fts_entities"]) == (1, 1)
