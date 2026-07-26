"""SQLite access. The schema is applied on every connection, idempotently."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from importlib import resources
from typing import Iterator

from . import config

_SCHEMA_APPLIED = False


def _schema_sql() -> str:
    return resources.files("enqueue").joinpath("schema.sql").read_text(encoding="utf-8")


def get_conn() -> sqlite3.Connection:
    """Open the database, creating directories and applying the schema if needed."""
    global _SCHEMA_APPLIED

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.BLOB_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    if not _SCHEMA_APPLIED:
        conn.executescript(_schema_sql())
        conn.commit()
        _SCHEMA_APPLIED = True

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
