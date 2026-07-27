"""Migrations, and the one case that is easy to get catastrophically wrong.

A database that predates migrations already has the baseline shape. Replaying the
baseline against it would fail; dropping and recreating it would destroy everything
the person has ever saved. It has to be adopted instead.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from importlib import resources

import pytest

from enqueue import config, db


def _baseline():
    """Load revision 0001 by path. Its filename is not a Python identifier, because
    Alembic sorts revisions by filename and readable ordering is worth more here than
    importability."""
    path = resources.files("enqueue").joinpath("migrations/versions/0001_baseline.py")
    spec = importlib.util.spec_from_file_location("baseline", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


baseline = _baseline()


def head() -> str:
    """The newest revision, read from the migration scripts themselves."""
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(db._alembic_config()).get_current_head()


def tables(path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def test_fresh_database_reaches_head(store):
    assert {"artifacts", "chats", "chat_topics", "link_previews"} <= tables(config.DB_PATH)
    conn = sqlite3.connect(config.DB_PATH)
    try:
        assert conn.execute("SELECT * FROM alembic_version").fetchone()[0] == head()
    finally:
        conn.close()


def test_migrating_twice_is_a_no_op(store):
    before = tables(config.DB_PATH)
    db.migrate()
    assert tables(config.DB_PATH) == before


def test_a_pre_migration_database_is_adopted_not_rebuilt(tmp_path, monkeypatch):
    """The upgrade path for anyone who ran this before Alembic existed."""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    for statement in baseline.TABLES:
        conn.execute(statement)
    conn.execute(
        "INSERT INTO artifacts (id, kind, title, body, content_hash, created_at,"
        " updated_at, local_only, status) VALUES ('a','note','Kept','still here','h',"
        "'2026-01-01','2026-01-01',0,'ok')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(config, "BLOB_DIR", tmp_path / "blobs")
    db.reset_migration_state()
    db.migrate()

    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT body FROM artifacts WHERE id='a'").fetchone()[0] == "still here"
        # Compared against the real head rather than a literal, so adding a revision
        # does not require editing this test to keep it passing.
        assert conn.execute("SELECT * FROM alembic_version").fetchone()[0] == head()
        assert "chats" in tables(path)
    finally:
        conn.close()
    db.reset_migration_state()


def test_a_capture_can_never_hold_a_body(store):
    """The invariant is the database's, not the application's."""
    conn = db.get_conn()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO artifacts (id, kind, title, body, content_hash, created_at,"
                " updated_at, local_only, status) VALUES ('x','pdf','A paper','edited',"
                "'h2','2026-01-01','2026-01-01',0,'ok')"
            )
    finally:
        conn.close()
