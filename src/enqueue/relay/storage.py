"""The relay's byte store and change feed, one space per library.

The relay is a dumb byte store. It keeps objects keyed by name, a monotonic
cursor that advances on every successful write, and the change feed that both
list-changed-since and the SSE stream read. It parses none of the bytes and can
decrypt nothing; the object name is the only metadata it ever sees.

One relay serves many libraries. A library is known only by the hash of its relay
secret (`library_id`): every object, cursor and change belongs to one library, and
nothing one library does is visible to another, not even how often it writes. The
relay never stores a secret, only its hash, so a copy of the relay's database lets
no one in.
"""

from __future__ import annotations

import hashlib
import secrets as _secrets
import sqlite3
import threading
import time
from pathlib import Path


def library_id(secret: str) -> str:
    """The library a relay secret opens: its SHA-256, hex. A secret is 32 random bytes
    (or a long passphrase), so the hash needs no salt and no stretching."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def new_secret() -> str:
    """A fresh relay secret: 32 random bytes, URL-safe."""
    return _secrets.token_urlsafe(32)


class LibraryFull(Exception):
    """A write would take a library past its storage limit."""


class RelayStorage:
    """Disk-backed object store with a monotonic change cursor per library.

    Objects live as BLOBs in a SQLite file under `data_dir`, keyed by
    (library, name). A library's cursor is `MAX(cursor)` over its own objects, so it
    survives a restart and says nothing about other libraries. Writes are UPSERTs: a
    second PUT of an existing name overwrites the bytes and assigns a fresh (higher)
    cursor, so the object moves to the head of the change feed and any device whose
    cursor already passed the old position re-pulls the update (MOBFIX.5).

    `default_quota` is each library's storage limit in bytes (0 = none) unless the
    library has its own. A relay that ran before libraries existed keeps its objects:
    they move into `legacy_library` (the library of the secret it was started with) the
    first time this opens its file.
    """

    def __init__(self, data_dir: Path, legacy_library: str | None = None, default_quota: int = 0):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self.data_dir / "relay.db"
        self._lock = threading.Lock()
        self.default_quota = default_quota
        self._init_db(legacy_library)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self, legacy_library: str | None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS libraries ("
                " id TEXT PRIMARY KEY,"
                " label TEXT NOT NULL DEFAULT '',"
                " created_at REAL NOT NULL,"
                " revoked_at REAL,"
                " quota_bytes INTEGER,"
                " used_bytes INTEGER NOT NULL DEFAULT 0)"
            )
            columns = {r["name"] for r in conn.execute("PRAGMA table_info(objects)")}
            if columns and "library" not in columns:
                # A relay from before libraries: its objects belong to the one library
                # it served, the secret it is started with now.
                if not legacy_library:
                    raise RuntimeError(
                        "this relay holds objects from before libraries existed; start it"
                        " with the secret those devices use (RELAY_SECRET) to keep them"
                    )
                conn.execute("ALTER TABLE objects RENAME TO objects_single")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS objects ("
                " library TEXT NOT NULL,"
                " name TEXT NOT NULL,"
                " data BLOB NOT NULL,"
                " cursor INTEGER NOT NULL,"
                " PRIMARY KEY (library, name))"
            )
            # The change feed filters+orders by cursor within a library on every pull;
            # index it so it is a range scan instead of a full table scan (SYNC.2).
            conn.execute("DROP INDEX IF EXISTS idx_objects_cursor")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_objects_library_cursor"
                " ON objects(library, cursor)"
            )
            if legacy_library:
                self._register(conn, legacy_library, "first library")
            # Also finishes a move a crash interrupted: the old table is only dropped
            # once every row is in the new one.
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'objects_single'"
            ).fetchone():
                if not legacy_library:
                    raise RuntimeError("start the relay with RELAY_SECRET to finish moving it")
                conn.execute(
                    "INSERT OR IGNORE INTO objects (library, name, data, cursor)"
                    " SELECT ?, name, data, cursor FROM objects_single",
                    (legacy_library,),
                )
                conn.execute("DROP TABLE objects_single")
                self._recount(conn, legacy_library)

    # ---- libraries -------------------------------------------------------------

    def _register(self, conn, library: str, label: str) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO libraries (id, label, created_at) VALUES (?, ?, ?)",
            (library, label, time.time()),
        )

    def _recount(self, conn, library: str) -> None:
        conn.execute(
            "UPDATE libraries SET used_bytes ="
            " (SELECT COALESCE(SUM(length(data)), 0) FROM objects WHERE library = ?)"
            " WHERE id = ?",
            (library, library),
        )

    def add_library(self, label: str = "", quota_bytes: int | None = None) -> tuple[str, str]:
        """Make a library and return `(library_id, secret)`. The secret is shown once:
        the relay keeps only its hash."""
        secret = new_secret()
        lid = library_id(secret)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO libraries (id, label, created_at, quota_bytes) VALUES (?,?,?,?)",
                (lid, label, time.time(), quota_bytes),
            )
        return lid, secret

    def revoke_library(self, library: str) -> bool:
        """Refuse the library's secret from now on. Its objects stay until deleted."""
        with self._lock, self._connect() as conn:
            return (
                conn.execute(
                    "UPDATE libraries SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                    (time.time(), library),
                ).rowcount
                > 0
            )

    def libraries(self) -> list[dict]:
        with self._connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT id, label, created_at, revoked_at, quota_bytes, used_bytes,"
                    " (SELECT COUNT(*) FROM objects o WHERE o.library = l.id) AS objects"
                    " FROM libraries l ORDER BY created_at"
                )
            ]

    def library_for(self, secret: str) -> str | None:
        """The live library a secret opens, or None."""
        lid = library_id(secret)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM libraries WHERE id = ? AND revoked_at IS NULL", (lid,)
            ).fetchone()
        return row["id"] if row else None

    # ---- objects ---------------------------------------------------------------

    def _max_cursor(self, conn: sqlite3.Connection, library: str) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(cursor), 0) AS c FROM objects WHERE library = ?", (library,)
        ).fetchone()
        return row["c"]

    def put(self, library: str, name: str, data: bytes) -> tuple[int, int]:
        """Store or overwrite an object, returning `(cursor, size)`.

        UPSERT by name: an overwrite replaces the bytes AND takes a fresh cursor
        at the head of the change feed, so `list_changed(since)` re-surfaces the
        object to a device that already pulled past its old position. Object
        names carry the writer's device prefix (`dev/{device}/...`), so an
        overwrite only ever replaces that device's own older snapshot.
        Raises LibraryFull when the write would take the library past its limit.
        """
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT used_bytes, quota_bytes FROM libraries WHERE id = ?", (library,)
            ).fetchone()
            old = conn.execute(
                "SELECT length(data) AS n FROM objects WHERE library = ? AND name = ?",
                (library, name),
            ).fetchone()
            used = (row["used_bytes"] if row else 0) - (old["n"] if old else 0) + len(data)
            quota = row["quota_bytes"] if row and row["quota_bytes"] is not None else None
            quota = self.default_quota if quota is None else quota
            if quota and used > quota:
                raise LibraryFull(f"library is full ({quota} bytes)")
            cursor = self._max_cursor(conn, library) + 1
            conn.execute(
                "INSERT INTO objects (library, name, data, cursor) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(library, name) DO UPDATE SET data = excluded.data,"
                " cursor = excluded.cursor",
                (library, name, data, cursor),
            )
            conn.execute("UPDATE libraries SET used_bytes = ? WHERE id = ?", (used, library))
            return cursor, len(data)

    def delete(self, library: str, name: str) -> bool:
        """Remove an object (a device clearing its own superseded copies). Devices that
        already pulled it keep what they applied; the change feed simply no longer
        lists it."""
        with self._lock, self._connect() as conn:
            gone = (
                conn.execute(
                    "DELETE FROM objects WHERE library = ? AND name = ?", (library, name)
                ).rowcount
                > 0
            )
            if gone:
                self._recount(conn, library)
            return gone

    def get(self, library: str, name: str) -> bytes | None:
        """Return the stored bytes, or None when the name is absent."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM objects WHERE library = ? AND name = ?", (library, name)
            ).fetchone()
            return bytes(row["data"]) if row is not None else None

    def list_changed(self, library: str, since: int) -> tuple[list[dict], int]:
        """Every object of the library with cursor > `since`, plus the new cursor."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name, length(data) AS size FROM objects"
                " WHERE library = ? AND cursor > ? ORDER BY cursor",
                (library, since),
            ).fetchall()
            cursor = self._max_cursor(conn, library)
            return [{"name": r["name"], "size": r["size"]} for r in rows], cursor
