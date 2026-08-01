"""enq reindex, and the engine-aware readiness of the eval commands.

The reindex contract: rebuild both collections from the chunks and facets
tables already in SQLite, never touch Qdrant, print progress every 500 rows,
be safe to re-run (no duplicated rows), and record the embedding version when
done. The eval tests cover the per-engine readiness gate that replaced the
hardcoded "test Qdrant directory exists" check.
"""

from __future__ import annotations

import sqlite3

import pytest
import sqlite_vec
import typer

from enqueue import cli, config, db
from enqueue.index.store import get_store


def _seed_library() -> None:
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


def test_reindex_twice_is_identical(store, monkeypatch, capsys):
    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    _seed_library()
    get_store.cache_clear()

    cli.reindex()
    first = get_store().counts()
    out = capsys.readouterr().out
    assert "Reindexing chunks" in out
    assert "1/1 rows" in out
    assert "Index rebuilt; embedding version recorded." in out

    cli.reindex()
    second = get_store().counts()
    assert first == second
    assert first["chunks"] == 1
    assert first["fts_chunks"] == 1
    assert first["facets"] == 1
    assert first["fts_facets"] == 1

    conn = db.get_conn()
    try:
        value = conn.execute("SELECT value FROM index_meta WHERE key = 'embed_version'").fetchone()[
            "value"
        ]
    finally:
        conn.close()
    assert value == config.EMBED_VERSION


def _point_evals_at(tmp_path):
    """Redirect the eval command's evals/ paths to a scratch directory."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(cli, "EVALS_DIR", tmp_path)
    monkeypatch.setattr(cli, "QUERIES_PATH", tmp_path / "queries.yaml")
    monkeypatch.setattr(cli, "RESULTS_DIR", tmp_path / "results")
    return monkeypatch


def _scratch_evals(tmp_path, with_index: bool) -> None:
    test_dir = tmp_path / "test-data"
    test_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "queries.yaml").write_text("queries: []\n", encoding="utf-8")
    (test_dir / "blobs").mkdir(exist_ok=True)

    from enqueue import db as db_mod

    db_mod.reset_migration_state()
    cfg = _db_config(test_dir)
    cfg.DB_PATH = test_dir / "enqueue.db"
    cfg.DATA_DIR = test_dir
    cfg.BLOB_DIR = test_dir / "blobs"
    db_mod.migrate()
    if not with_index:
        # An adopted database that predates the index migration has no vec
        # tables: counts() reports None for them, which is the readiness fail.
        # Dropping a vec0 table also needs the extension loaded.
        conn = sqlite3.connect(cfg.DB_PATH)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        try:
            conn.execute("DROP TABLE IF EXISTS vec_chunks")
            conn.execute("DROP TABLE IF EXISTS vec_facets")
            conn.execute("DROP TABLE IF EXISTS fts_chunks")
            conn.execute("DROP TABLE IF EXISTS fts_facets")
            conn.commit()
        finally:
            conn.close()
    db_mod.reset_migration_state()


def _db_config(test_dir):
    from enqueue import config as cfg

    return cfg


def test_eval_refuses_an_engine_without_an_index(tmp_path, store, monkeypatch):
    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    _scratch_evals(tmp_path, with_index=False)
    evals_patch = _point_evals_at(tmp_path)

    with pytest.raises(typer.Exit):
        cli.eval(engine="sqlite-vec")
    out = evals_patch  # keep the patch alive until after the call
    assert out  # silence linters; the patch is only needed for cleanup
    get_store.cache_clear()


def test_eval_runs_against_a_sqlite_vec_test_index(tmp_path, store, monkeypatch, capsys):
    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    _scratch_evals(tmp_path, with_index=True)
    evals_patch = _point_evals_at(tmp_path)

    cli.eval(engine="sqlite-vec")
    out = capsys.readouterr().out
    assert "Loaded 0 queries" in out
    assert "test index not found" not in out
    assert evals_patch  # silence linters
    get_store.cache_clear()
