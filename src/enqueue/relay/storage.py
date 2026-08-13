"""The relay's byte store and change feed.

The relay is a dumb byte store. It keeps objects keyed by name, a monotonic
cursor that advances on every successful write, and the change feed that both
list-changed-since and the SSE stream read. It parses none of the bytes and can
decrypt nothing; the object name is the only metadata it ever sees.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class ObjectConflict(Exception):
    """A PUT of a name that already exists. Write-by-unique-name."""


class RelayStorage:
    """Disk-backed object store with a monotonic change cursor.

    Objects live as BLOBs in a SQLite file under `data_dir`, keyed by name.
    The cursor is `MAX(cursor)` over the objects table, so it survives a
    restart. Writes are write-by-unique-name: a second PUT of an existing name
    raises `ObjectConflict` and leaves the stored object untouched.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self.data_dir / "relay.db"
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS objects ("
                " name TEXT PRIMARY KEY,"
                " data BLOB NOT NULL,"
                " cursor INTEGER NOT NULL)"
            )

    def _max_cursor(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT COALESCE(MAX(cursor), 0) AS c FROM objects").fetchone()
        return row["c"]

    def put(self, name: str, data: bytes) -> tuple[int, int]:
        """Store an object, returning `(cursor, size)`. Raises ObjectConflict."""
        with self._lock, self._connect() as conn:
            if conn.execute("SELECT 1 FROM objects WHERE name = ?", (name,)).fetchone():
                raise ObjectConflict(name)
            cursor = self._max_cursor(conn) + 1
            conn.execute(
                "INSERT INTO objects (name, data, cursor) VALUES (?, ?, ?)",
                (name, data, cursor),
            )
            return cursor, len(data)

    def get(self, name: str) -> bytes | None:
        """Return the stored bytes, or None when the name is absent."""
        with self._connect() as conn:
            row = conn.execute("SELECT data FROM objects WHERE name = ?", (name,)).fetchone()
            return bytes(row["data"]) if row is not None else None

    def list_changed(self, since: int) -> tuple[list[dict], int]:
        """Every object with cursor > `since`, plus the new cursor to pass next."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name, length(data) AS size FROM objects"
                " WHERE cursor > ? ORDER BY cursor",
                (since,),
            ).fetchall()
            cursor = self._max_cursor(conn)
            return [{"name": r["name"], "size": r["size"]} for r in rows], cursor
