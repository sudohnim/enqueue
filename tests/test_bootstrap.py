"""Startup index bootstrap: the cutover's "no manual reindex" promise.

A fresh install and an upgrade from the Qdrant era both reach `enq serve`
with chunks in SQLite but no sqlite-vec index and no recorded embedding
version. `ensure_index` builds both collections once, then is a no-op.

Phase 20 steps 3 and 4 turn the "verify a fresh install" and "verify an
existing install upgrades" checkboxes into the assertions below: the index
ends up built, the embed version is recorded, search works, and the source
chunks are untouched (no data loss).

Phase 21 adds the version-mismatch case: an index built by an older model
must rebuild and block search until it does.
"""

from __future__ import annotations

import sqlite3
import threading
import time

import sqlite_vec
from fastapi.testclient import TestClient

from enqueue import api, config, db
from enqueue.index import bootstrap
from enqueue.index.store import get_store


def _seed_one_chunked_artifact() -> None:
    """Insert an artifact, one chunk, and one facet, the qdrant-era shape.

    Nothing is written to the vec/fts tables: that is the pre-cutover state,
    where chunks and facets live in SQLite but the sqlite-vec index is empty.
    """
    conn = db.get_conn()
    try:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, status,"
            " created_at, updated_at) VALUES ('a1', 'note', 'Hydroponics',"
            " 'A city can feed itself from its rooftops.', 'h1', 'ok',"
            " datetime('now'), datetime('now'))"
        )
        conn.execute(
            "INSERT INTO chunks (id, artifact_id, ordinal, text, chunker)"
            " VALUES ('c1', 'a1', 0, 'A city can feed itself from its rooftops.', 'test')"
        )
        conn.execute(
            "INSERT INTO facets (id, artifact_id, level, statement, model_version, trust)"
            " VALUES ('f1', 'a1', 3, 'Rooftops can feed a city.', 'test-model', 0.8)"
        )
        conn.commit()
    finally:
        conn.close()


def _chunk_count() -> int:
    conn = db.get_conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    finally:
        conn.close()


def test_fresh_install_builds_index_with_no_manual_reindex(store, monkeypatch, capsys):
    """Step 3: a brand-new database has zero chunks and no embed version.

    `ensure_index` builds an empty index, records the version, and search runs
    without error (returning nothing, because there is nothing to find). A
    second call is a no-op.
    """
    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()

    assert bootstrap.needs_reindex() is True
    assert bootstrap.read_embed_version() is None

    progress: list[tuple[int, int]] = []

    def _progress(indexed: int, total: int) -> None:
        progress.append((indexed, total))

    ran = bootstrap.ensure_index(on_progress=_progress)
    assert ran is True

    # The version is now recorded; an empty library still has a valid index.
    assert bootstrap.read_embed_version() == config.EMBED_VERSION
    counts = get_store().counts()
    assert counts["chunks"] == 0
    assert counts["facets"] == 0
    assert get_store().search(get_store().CHUNKS, "anything") == []

    # Idempotent: a second call does no work.
    ran_again = bootstrap.ensure_index(on_progress=_progress)
    assert ran_again is False
    get_store.cache_clear()


def test_existing_install_upgrades_with_no_data_loss(store, monkeypatch):
    """Step 4: a qdrant-era install has chunks in SQLite but no sqlite-vec index.

    `ensure_index` builds the index from the existing chunks (the qdrant
    directory is never consulted), search finds the artifact, and the source
    chunk rows are unchanged in SQLite.
    """
    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()

    _seed_one_chunked_artifact()
    chunk_rows_before = _chunk_count()
    assert chunk_rows_before == 1

    # The pre-cutover state: the vec tables exist (migration 0010) but hold
    # nothing, and no embed version is recorded.
    assert bootstrap.read_embed_version() is None
    assert get_store().counts()["chunks"] == 0

    ran = bootstrap.ensure_index()
    assert ran is True

    # The index now holds the chunk and the facet, built from the rows that
    # were already there.
    counts = get_store().counts()
    assert counts["chunks"] == 1
    assert counts["fts_chunks"] == 1
    assert counts["facets"] == 1
    assert counts["fts_facets"] == 1
    assert bootstrap.read_embed_version() == config.EMBED_VERSION

    # Search finds the artifact, fused from the dense and keyword branches.
    store_obj = get_store()
    hits = store_obj.search(store_obj.CHUNKS, "rooftop city food", limit=5)
    assert hits[0]["artifact_id"] == "a1"

    # The source chunks are untouched: nothing the person saved was lost or
    # rewritten to migrate the index.
    assert _chunk_count() == chunk_rows_before
    get_store.cache_clear()


def test_needs_reindex_false_after_a_version_is_recorded(store, monkeypatch):
    """Once built, `needs_reindex` is False and `ensure_index` skips the work."""
    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    _seed_one_chunked_artifact()

    assert bootstrap.ensure_index() is True
    # The recorded version is the "index exists" signal: once it matches the
    # running model, no rebuild is needed and `ensure_index` is a no-op.
    assert bootstrap.needs_reindex() is False
    assert bootstrap.ensure_index() is False
    get_store.cache_clear()


def test_stale_embed_version_needs_rebuild(store, monkeypatch):
    """A recorded version that no longer matches EMBED_VERSION needs a rebuild.

    This is the Phase 21 shape: the index exists but was built by an older
    model, so its results would differ from another device's. `needs_reindex`
    says rebuild, search is blocked, and `ensure_index` rebuilds and records
    the new version.
    """
    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    _seed_one_chunked_artifact()
    assert bootstrap.ensure_index() is True

    conn = db.get_conn()
    try:
        conn.execute(
            "UPDATE index_meta SET value = ? WHERE key = 'embed_version'",
            ("bge-base-en-v1.5-old",),
        )
        conn.commit()
    finally:
        conn.close()

    assert bootstrap.needs_reindex() is True
    assert bootstrap.search_allowed() is False  # state ready but version stale

    assert bootstrap.ensure_index() is True  # the rebuild ran
    assert bootstrap.read_embed_version() == config.EMBED_VERSION
    assert bootstrap.needs_reindex() is False
    assert bootstrap.search_allowed() is True
    get_store.cache_clear()


def test_phase21_stale_index_blocks_search_then_recovers(store, monkeypatch):
    """Start the app with a stale index: search is blocked and a rebuild runs.

    The serve() startup path detects the version mismatch, blocks /search
    with the required message, rebuilds in the background, and re-enables
    search only after the new version is written. The rebuild is gated on an
    event so the blocked-state assertions cannot race the fast rebuild.
    """
    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    _seed_one_chunked_artifact()
    assert bootstrap.ensure_index() is True

    # Pretend the index was built by an older embedding model.
    conn = db.get_conn()
    try:
        conn.execute(
            "UPDATE index_meta SET value = ? WHERE key = 'embed_version'",
            ("bge-base-en-v1.5-old",),
        )
        conn.commit()
    finally:
        conn.close()

    release = threading.Event()
    real_rebuild = bootstrap.rebuild_index

    def _gated(store_obj):
        assert release.wait(15)
        return real_rebuild(store_obj)

    monkeypatch.setattr(bootstrap, "rebuild_index", _gated)

    api._bootstrap_index()  # the serve() startup path

    assert bootstrap.needs_reindex() is True
    assert bootstrap.search_allowed() is False

    with TestClient(api.app) as client:
        resp = client.get("/search?q=rooftop")
        assert resp.status_code == 503
        assert resp.json()["detail"] == ("Updating your search index. This will take a moment.")

        release.set()
        deadline = time.time() + 30
        while time.time() < deadline:
            resp = client.get("/search?q=rooftop")
            if resp.status_code == 200:
                break
            time.sleep(0.05)
        assert resp.status_code == 200
        assert resp.json()["hits"][0]["artifact_id"] == "a1"

    assert bootstrap.read_embed_version() == config.EMBED_VERSION
    assert bootstrap.search_allowed() is True
    get_store.cache_clear()


def test_remove_legacy_qdrant_dir_deletes_once(store, monkeypatch):
    """The cutover deletes the old qdrant-local directory, once, with a report."""
    legacy = config.DATA_DIR / "qdrant-local"
    (legacy / "collection").mkdir(parents=True)
    (legacy / "collection" / "0.db").write_bytes(b"x" * 100)
    (legacy / "meta.json").write_text("{}", encoding="utf-8")

    report = bootstrap.remove_legacy_qdrant_dir()
    assert report is not None
    assert report["files"] == 2
    assert report["bytes"] == 102
    assert not legacy.exists()

    # Nothing left to remove on the next run: the cleanup is one-time.
    assert bootstrap.remove_legacy_qdrant_dir() is None


def test_bootstrap_is_safe_when_vec_tables_are_absent(store, monkeypatch):
    """An adopted database that predates migration 0010 has no vec tables.

    This is the edge of the upgrade path: the store's `ensure()` recreates the
    tables, the rebuild runs, and the version is recorded. Nothing about a
    missing index blocks startup.
    """
    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    _seed_one_chunked_artifact()

    conn = sqlite3.connect(config.DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    try:
        conn.execute("DROP TABLE IF EXISTS vec_chunks")
        conn.execute("DROP TABLE IF EXISTS vec_facets")
        conn.execute("DROP TABLE IF EXISTS fts_chunks")
        conn.execute("DROP TABLE IF EXISTS fts_facets")
        conn.execute("DELETE FROM index_meta WHERE key = 'embed_version'")
        conn.commit()
    finally:
        conn.close()
    db.reset_migration_state()

    assert bootstrap.ensure_index() is True
    counts = get_store().counts()
    assert counts["chunks"] == 1
    assert bootstrap.read_embed_version() == config.EMBED_VERSION
    get_store.cache_clear()
