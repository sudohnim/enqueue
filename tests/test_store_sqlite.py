"""The sqlite-vec store: same contract as Qdrant, one file instead of a directory.

The store is exercised exactly as the app uses it: the migration builds the
schema, chunk rows come from `chunk_artifact` or direct inserts, and the
store's own connection reads and writes the index inside the same SQLite
file. The input-sanitization cases are the ones the plan calls out - quote
characters, bare boolean words, hyphens, prefix stars, empty text, and a
500-character string must all search without error.
"""

from __future__ import annotations

import pytest
from enqueue.index.store import get_store
from enqueue.index.store_sqlite import SqliteVecStore
from enqueue.ingest import chunk as chunk_mod

from enqueue import config, db

# Texts are deliberately disjoint topics so dense retrieval can separate them.
_BODY_A = "Hydroponics feeds the city from a rooftop where the soil never was."
_BODY_B = "The commons is what we share, and sharing is what keeps it common."
_RARE = "The word ziggurat appears nowhere else in the library."


@pytest.fixture
def sqlite_store(store, monkeypatch):
    """The sqlite-vec store, resolved through the factory, on a temp database."""
    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    yield get_store()
    get_store.cache_clear()


def _artifact(conn, artifact_id: str, title: str, body: str) -> None:
    conn.execute(
        "INSERT INTO artifacts (id, kind, title, body, content_hash, status,"
        " created_at, updated_at) VALUES (?, 'note', ?, ?, ?, 'ok',"
        " datetime('now'), datetime('now'))",
        (artifact_id, title, body, artifact_id + "_hash"),
    )


def _chunk(conn, chunk_id: str, artifact_id: str, ordinal: int, text: str) -> None:
    conn.execute(
        "INSERT INTO chunks (id, artifact_id, ordinal, text, chunker)"
        " VALUES (?, ?, ?, ?, 'test')",
        (chunk_id, artifact_id, ordinal, text),
    )


def _facet(conn, facet_id: str, artifact_id: str, level: int, statement: str, trust: float) -> None:
    conn.execute(
        "INSERT INTO facets (id, artifact_id, level, statement, model_version, trust)"
        " VALUES (?, ?, ?, ?, 'test-model', ?)",
        (facet_id, artifact_id, level, statement, trust),
    )


def _write(conn) -> None:
    conn.commit()


def _make_two_artifact_library(store) -> None:
    conn = db.get_conn()
    try:
        _artifact(conn, "a1", "Hydroponics", _BODY_A)
        _artifact(conn, "a2", "The Commons", _BODY_B)
        _chunk(conn, "c1", "a1", 0, _BODY_A)
        _chunk(conn, "c2", "a2", 0, _BODY_B)
        _write(conn)
    finally:
        conn.close()
    store.upsert_chunks()


class TestFactory:
    def test_get_store_resolves_sqlite_vec(self, store, monkeypatch):
        monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
        get_store.cache_clear()
        assert isinstance(get_store(), SqliteVecStore)
        get_store.cache_clear()

    def test_unknown_backend_raises(self, store, monkeypatch):
        monkeypatch.setattr(config, "VECTOR_STORE", "nope")
        get_store.cache_clear()
        with pytest.raises(ValueError, match="VECTOR_STORE"):
            get_store()
        get_store.cache_clear()


class TestEnsureAndCounts:
    def test_ensure_creates_all_tables_and_is_idempotent(self, sqlite_store):
        sqlite_store.ensure()
        sqlite_store.ensure()
        counts = sqlite_store.counts()
        assert set(counts) == {"chunks", "facets", "fts_chunks", "fts_facets"}
        assert all(v == 0 for v in counts.values())

    def test_counts_before_ensure_is_none_for_missing_tables(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "DATA_DIR", tmp_path)
        monkeypatch.setattr(config, "DB_PATH", tmp_path / "fresh.db")
        monkeypatch.setattr(config, "BLOB_DIR", tmp_path / "blobs")
        db.reset_migration_state()
        try:
            counts = SqliteVecStore().counts()
            assert counts["chunks"] is None
            assert counts["facets"] is None
        finally:
            db.reset_migration_state()

    def test_reset_drops_and_recreates(self, sqlite_store):
        _make_two_artifact_library(sqlite_store)
        assert sqlite_store.counts()["chunks"] == 2
        sqlite_store.reset(sqlite_store.CHUNKS)
        counts = sqlite_store.counts()
        assert counts["chunks"] == 0
        assert counts["fts_chunks"] == 0
        sqlite_store.upsert_chunks()
        assert sqlite_store.counts()["chunks"] == 2


class TestRebuilds:
    def test_upsert_twice_leaves_counts_unchanged(self, sqlite_store):
        _make_two_artifact_library(sqlite_store)
        first = sqlite_store.counts()
        sqlite_store.upsert_chunks()
        second = sqlite_store.counts()
        assert first == second
        assert first["chunks"] == 2
        assert first["fts_chunks"] == 2

    def test_upsert_facets(self, sqlite_store):
        conn = db.get_conn()
        try:
            _artifact(conn, "a1", "Hydroponics", _BODY_A)
            _facet(conn, "f1", "a1", 3, "A city can feed itself from its rooftops.", 0.8)
            _facet(conn, "f2", "a1", 1, "The soil never was.", 0.4)
            _write(conn)
        finally:
            conn.close()
        sqlite_store.upsert_facets()
        counts = sqlite_store.counts()
        assert counts["facets"] == 2
        assert counts["fts_facets"] == 2

    def test_deleted_artifacts_are_dropped_from_the_rebuild(self, sqlite_store):
        conn = db.get_conn()
        try:
            _artifact(conn, "a1", "Hydroponics", _BODY_A)
            _artifact(conn, "a2", "The Commons", _BODY_B)
            _chunk(conn, "c1", "a1", 0, _BODY_A)
            _chunk(conn, "c2", "a2", 0, _BODY_B)
            _write(conn)
        finally:
            conn.close()
        sqlite_store.upsert_chunks()
        assert sqlite_store.counts()["chunks"] == 2

        conn = db.get_conn()
        try:
            conn.execute("UPDATE artifacts SET deleted_at = datetime('now') WHERE id = 'a1'")
            _write(conn)
        finally:
            conn.close()
        sqlite_store.upsert_chunks()
        counts = sqlite_store.counts()
        assert counts["chunks"] == 1
        assert counts["fts_chunks"] == 1


class TestSearch:
    def test_search_dense_ranks_the_right_artifact_first(self, sqlite_store):
        _make_two_artifact_library(sqlite_store)
        hits = sqlite_store.search_dense(sqlite_store.CHUNKS, _BODY_A, limit=5)
        assert hits
        assert hits[0]["chunk_id"] == "c1"
        assert hits[0]["artifact_id"] == "a1"
        assert hits[0]["score"] > 0

    def test_keyword_finds_a_rare_term_in_the_indexed_text(self, sqlite_store):
        conn = db.get_conn()
        try:
            _artifact(conn, "a1", "Rare word", _RARE)
            _chunk(conn, "c1", "a1", 0, _RARE)
            _write(conn)
        finally:
            conn.close()
        sqlite_store.upsert_chunks()
        hits = sqlite_store.search(sqlite_store.CHUNKS, "ziggurat", limit=5)
        assert any(h["chunk_id"] == "c1" for h in hits)

    def test_title_is_prepended_for_indexing_only(self, sqlite_store):
        """A name that appears only in the title still finds the chunk."""
        conn = db.get_conn()
        try:
            _artifact(conn, "a1", "Epictetus", "The true man is revealed during difficult times.")
            _chunk(conn, "c1", "a1", 0, "The true man is revealed during difficult times.")
            _write(conn)
        finally:
            conn.close()
        sqlite_store.upsert_chunks()
        hits = sqlite_store.search(sqlite_store.CHUNKS, "Epictetus", limit=5)
        assert hits and hits[0]["chunk_id"] == "c1"
        # The stored chunk text is untouched by indexing.
        conn = db.get_conn()
        try:
            text = conn.execute("SELECT text FROM chunks WHERE id = 'c1'").fetchone()["text"]
        finally:
            conn.close()
        assert "Epictetus" not in text

    def test_facet_hits_carry_level_and_trust(self, sqlite_store):
        conn = db.get_conn()
        try:
            _artifact(conn, "a1", "Hydroponics", _BODY_A)
            _facet(conn, "f1", "a1", 3, "A city can feed itself from its rooftops.", 0.8)
            _write(conn)
        finally:
            conn.close()
        sqlite_store.upsert_facets()
        hits = sqlite_store.search(sqlite_store.FACETS, "rooftops", limit=5)
        assert hits and hits[0]["facet_id"] == "f1"
        assert hits[0]["level"] == 3
        assert hits[0]["trust"] == 0.8

    def test_three_character_prefix_finds_the_longer_word(self, sqlite_store):
        """Phase 22: FTS5 prefix matching makes partial words findable."""
        conn = db.get_conn()
        try:
            _artifact(conn, "a1", "Hydroponics", _BODY_A)
            _chunk(conn, "c1", "a1", 0, _BODY_A)
            _write(conn)
        finally:
            conn.close()
        sqlite_store.upsert_chunks()
        # "hyd" is a prefix of "hydroponics": a 3-character partial word matches.
        hits = sqlite_store.search(sqlite_store.CHUNKS, "hyd", limit=5)
        assert hits and hits[0]["chunk_id"] == "c1"
        # The full word still matches, with the prefix star outside the quotes.
        hits_full = sqlite_store.search(sqlite_store.CHUNKS, "hydroponics", limit=5)
        assert hits_full and hits_full[0]["chunk_id"] == "c1"

    @pytest.mark.parametrize(
        "text",
        ['"', "AND", "foo-bar", "NEAR", "*", "", "x" * 500],
    )
    def test_literal_strings_search_without_error(self, sqlite_store, text):
        _make_two_artifact_library(sqlite_store)
        sqlite_store.search(sqlite_store.CHUNKS, text, limit=5)
        sqlite_store.search(sqlite_store.FACETS, text, limit=5)


class TestLifecycle:
    def test_index_artifact_replaces_in_place(self, sqlite_store):
        _make_two_artifact_library(sqlite_store)
        assert sqlite_store.counts()["chunks"] == 2

        conn = db.get_conn()
        try:
            conn.execute("UPDATE chunks SET text = ? WHERE id = 'c1'", (_RARE,))
            _write(conn)
        finally:
            conn.close()

        indexed = sqlite_store.index_artifact("a1")
        assert indexed == 1
        # Same row count, but the re-embedded chunk now ranks for the new text.
        assert sqlite_store.counts()["chunks"] == 2
        hits = sqlite_store.search_dense(sqlite_store.CHUNKS, _RARE, limit=5)
        assert hits and hits[0]["chunk_id"] == "c1"

    def test_index_artifact_with_no_chunks_returns_zero(self, sqlite_store):
        assert sqlite_store.index_artifact("nope") == 0

    def test_drop_artifact_removes_both_tables(self, sqlite_store):
        _make_two_artifact_library(sqlite_store)
        sqlite_store.drop_artifact(sqlite_store.CHUNKS, "a1")
        counts = sqlite_store.counts()
        assert counts["chunks"] == 1
        assert counts["fts_chunks"] == 1
        hits = sqlite_store.search(sqlite_store.CHUNKS, _BODY_A, limit=5)
        assert all(h["artifact_id"] != "a1" for h in hits)

    def test_drop_artifact_facets(self, sqlite_store):
        conn = db.get_conn()
        try:
            _artifact(conn, "a1", "Hydroponics", _BODY_A)
            _facet(conn, "f1", "a1", 3, "A city can feed itself from its rooftops.", 0.8)
            _facet(conn, "f2", "a1", 1, "The soil never was.", 0.4)
            _write(conn)
        finally:
            conn.close()
        sqlite_store.upsert_facets()
        sqlite_store.drop_artifact(sqlite_store.FACETS, "a1")
        counts = sqlite_store.counts()
        assert counts["facets"] == 0
        assert counts["fts_facets"] == 0

    def test_write_embed_version_is_idempotent(self, sqlite_store):
        sqlite_store.write_embed_version()
        sqlite_store.write_embed_version()
        conn = db.get_conn()
        try:
            value = conn.execute(
                "SELECT value FROM index_meta WHERE key = 'embed_version'"
            ).fetchone()["value"]
        finally:
            conn.close()
        assert value == config.EMBED_VERSION


class TestChunkedRoundTrip:
    """The queue's real path: chunk_artifact, then index the whole artifact."""

    def test_chunked_artifact_is_searchable(self, sqlite_store):
        conn = db.get_conn()
        try:
            _artifact(conn, "a1", "Hydroponics", _BODY_A + "\n\n" + _BODY_B)
            _write(conn)
        finally:
            conn.close()

        conn = db.get_conn()
        try:
            made = chunk_mod.chunk_artifact(conn, "a1")
            conn.commit()
        finally:
            conn.close()
        assert made >= 1

        indexed = sqlite_store.index_artifact("a1")
        assert indexed == made
        hits = sqlite_store.search(sqlite_store.CHUNKS, "hydroponics", limit=5)
        assert hits and hits[0]["artifact_id"] == "a1"
