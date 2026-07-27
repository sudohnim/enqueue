"""SQLite access, and the migration that brings the file up to date.

The runtime talks to SQLite through `sqlite3`. Alembic exists only to evolve the
schema: it is a build-time tool that happens to run at startup, not a second way to
query. Nothing below this line uses SQLAlchemy.

Migrations run once per process, before the first connection is handed out.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from importlib import resources
from typing import Iterator

from . import config

# The revision a database created by the pre-migration `schema.sql` already matches.
# Such a file is stamped at this revision rather than replayed, because replaying it
# would try to CREATE tables that are already there.
BASELINE = "0001"

_migrated = False
_lock = threading.Lock()


def _alembic_config():
    """Build the Alembic config in code, so nothing depends on the process's cwd.

    The engine is started by a desktop shell from an arbitrary directory, so an
    `alembic.ini` found by relative path would work in development and fail once
    the app is bundled.
    """
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(resources.files("enqueue").joinpath("migrations")))
    return cfg


def _tables() -> set[str]:
    if not config.DB_PATH.exists():
        return set()
    conn = sqlite3.connect(config.DB_PATH)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def migrate() -> None:
    """Bring the database to head. Safe to call repeatedly and from either client."""
    from alembic import command

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.BLOB_DIR.mkdir(parents=True, exist_ok=True)

    cfg = _alembic_config()
    tables = _tables()
    if "artifacts" in tables and "alembic_version" not in tables:
        command.stamp(cfg, BASELINE)
    command.upgrade(cfg, "head")


def _ensure_migrated() -> None:
    global _migrated
    if _migrated:
        return
    with _lock:
        if _migrated:
            return
        migrate()
        _migrated = True


def get_conn() -> sqlite3.Connection:
    """Open the database, migrating it first if this process has not yet."""
    _ensure_migrated()

    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def count(table: str) -> int:
    if not table.isidentifier():
        raise ValueError(f"unsafe table name: {table!r}")
    conn = get_conn()
    try:
        return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
    finally:
        conn.close()


def reset_migration_state() -> None:
    """Forget that this process migrated. Only tests need this, when they repoint
    `config.DB_PATH` at a fresh directory."""
    global _migrated
    _migrated = False
