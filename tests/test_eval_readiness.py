"""Engine-aware readiness of the eval commands.

The eval tests cover the per-engine readiness gate that replaced the
hardcoded "test Qdrant directory exists" check: an engine whose vec tables
are missing refuses to eval, and a built sqlite-vec index runs queries.
(The `enq reindex` command this file used to test was deleted in M.3 - it
touched the database directly and duplicated `enq index`; the idempotent
rebuild contract it asserted is covered by test_bootstrap and
test_store_sqlite.)
"""

from __future__ import annotations

import sqlite3

import pytest
import sqlite_vec
import typer

from enqueue import cli, config, db
from enqueue.index.store import get_store


def _point_evals_at(tmp_path):
    """Redirect the eval command's evals/ paths to a scratch directory."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(cli, "EVALS_DIR", tmp_path)
    monkeypatch.setattr(cli, "QUERIES_PATH", tmp_path / "queries.yaml")
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
