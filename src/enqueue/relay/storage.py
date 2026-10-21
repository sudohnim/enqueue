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

Where the bytes live is the one thing that differs between relays. A self-hosted relay
keeps them in the SQLite file. The hosted one keeps them in Cloudflare R2
(relay/blobs.py) and the SQLite file holds only the index: name, cursor, size and the
R2 key. The semantics are the same either way.
"""

from __future__ import annotations

from contextlib import contextmanager

import hashlib
import logging
import secrets as _secrets
import sqlite3
import threading
import time
from pathlib import Path

from .blobs import BlobStore, BlobStoreError

log = logging.getLogger("enqueue.relay.storage")


def library_id(secret: str) -> str:
    """The library a relay secret opens: its SHA-256, hex. A secret is 32 random bytes
    (or a long passphrase), so the hash needs no salt and no stretching."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def new_secret() -> str:
    """A fresh relay secret: 32 random bytes, URL-safe."""
    return _secrets.token_urlsafe(32)


class LibraryFull(Exception):
    """A write would take a library past its storage limit."""


class LibraryRevoked(Exception):
    """A write reached a library that was revoked while it was on its way."""


class RelayStorage:
    """Disk-backed object store with a monotonic change cursor per library.

    Objects are rows in a SQLite file under `data_dir`, keyed by (library, name),
    with their size and cursor. The bytes are in the row (`data`), or, with a blob
    store (R2), under the row's `blob_key` and the row's `data` is empty. A blob key is
    `<library>/<sha256 of the name>/<random>`: a fresh one per write, so a new copy is
    uploaded beside the old one, the row is switched to it in one transaction, and only
    then is the old one deleted. A reader never meets half an object, and two writes of
    one name cannot leave the row describing one copy and pointing at the other. A library's cursor is `MAX(cursor)` over its own objects, so it
    survives a restart and says nothing about other libraries. Writes are UPSERTs: a
    second PUT of an existing name overwrites the bytes and assigns a fresh (higher)
    cursor, so the object moves to the head of the change feed and any device whose
    cursor already passed the old position re-pulls the update (MOBFIX.5).

    `default_quota` is each library's storage limit in bytes (0 = none) unless the
    library has its own. A relay that ran before libraries existed keeps its objects:
    they move into `legacy_library` (the library of the secret it was started with) the
    first time this opens its file.

    Revoking a library deletes what it holds, in the file and in the blob store. Bytes
    still in the file when a blob store is first configured are moved there by
    `move_to_blob_store` (resumable, each copy read back before its row lets go of it);
    `start_upkeep` runs that and finishes any purge a failure interrupted.
    """

    def __init__(
        self,
        data_dir: Path,
        legacy_library: str | None = None,
        default_quota: int = 0,
        blobs: BlobStore | None = None,
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self.data_dir / "relay.db"
        self._lock = threading.Lock()
        self.default_quota = default_quota
        self.blobs = blobs
        self._upkeep: threading.Thread | None = None
        self._init_db(legacy_library)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _open(self):
        """A connection for one block: committed (or rolled back) and then CLOSED.

        `with conn:` on a sqlite connection only commits; it never closes, so every
        block left its connection to the garbage collector. Freed that way it closes
        inside dealloc, holding the GIL while it waits on SQLite's file lock, and when
        another thread held that lock and needed the GIL, the whole engine froze
        (2026-10-20: the Mac app stuck, every request hanging, 0% CPU)."""
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self, legacy_library: str | None) -> None:
        with self._lock, self._open() as conn:
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
            # The index columns added for a blob store: the size (so nothing has to read
            # the bytes to count them) and where the bytes are when not in `data`.
            columns = {r["name"] for r in conn.execute("PRAGMA table_info(objects)")}
            if "size" not in columns:
                conn.execute("ALTER TABLE objects ADD COLUMN size INTEGER")
            if "blob_key" not in columns:
                conn.execute("ALTER TABLE objects ADD COLUMN blob_key TEXT")
            lib_columns = {r["name"] for r in conn.execute("PRAGMA table_info(libraries)")}
            if "purged_at" not in lib_columns:
                # When a revoked library's objects were deleted (NULL: not yet).
                conn.execute("ALTER TABLE libraries ADD COLUMN purged_at REAL")
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
            conn.execute("UPDATE objects SET size = length(data) WHERE size IS NULL")
            if legacy_library:
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
            " (SELECT COALESCE(SUM(size), 0) FROM objects WHERE library = ?)"
            " WHERE id = ?",
            (library, library),
        )

    def add_library(self, label: str = "", quota_bytes: int | None = None) -> tuple[str, str]:
        """Make a library and return `(library_id, secret)`. The secret is shown once:
        the relay keeps only its hash."""
        secret = new_secret()
        lid = library_id(secret)
        with self._lock, self._open() as conn:
            conn.execute(
                "INSERT INTO libraries (id, label, created_at, quota_bytes) VALUES (?,?,?,?)",
                (lid, label, time.time(), quota_bytes),
            )
        return lid, secret

    def add_account_library(self, label: str = "", quota_bytes: int | None = None) -> str:
        """Make a library for a signed-in account (relay/accounts.py) and return its id.
        It has no secret at all: only the account's device tokens open it."""
        lid = library_id(new_secret())  # the id of a secret nobody is ever given
        with self._lock, self._open() as conn:
            conn.execute(
                "INSERT INTO libraries (id, label, created_at, quota_bytes) VALUES (?,?,?,?)",
                (lid, label, time.time(), quota_bytes),
            )
        return lid

    def set_quota(self, library: str, quota_bytes: int | None) -> None:
        """A library's own storage limit (None: the relay's default). Lowering it below
        what the library holds refuses new writes; nothing stored is removed."""
        with self._lock, self._open() as conn:
            conn.execute(
                "UPDATE libraries SET quota_bytes = ? WHERE id = ?", (quota_bytes, library)
            )

    def used_bytes(self, library: str) -> int:
        with self._open() as conn:
            row = conn.execute(
                "SELECT used_bytes FROM libraries WHERE id = ?", (library,)
            ).fetchone()
            return int(row["used_bytes"] or 0) if row else 0

    def is_live(self, library: str) -> bool:
        with self._open() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM libraries WHERE id = ? AND revoked_at IS NULL", (library,)
                ).fetchone()
                is not None
            )

    def revoke_library(self, library: str) -> bool:
        """Refuse the library's secret from now on and delete everything it holds: its
        rows here and its bytes in the blob store. Cannot be undone. A blob store that
        fails leaves the library marked unpurged, and `purge_revoked` finishes it."""
        with self._lock, self._open() as conn:
            revoked = (
                conn.execute(
                    "UPDATE libraries SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                    (time.time(), library),
                ).rowcount
                > 0
            )
        if revoked:
            self._purge(library)
        return revoked

    def _purge(self, library: str) -> bool:
        """Delete a revoked library's objects, rows first (so nothing points at bytes
        that are going), then every key under its prefix (so a copy orphaned by an
        earlier failure goes too). True once both are gone."""
        with self._lock, self._open() as conn:
            conn.execute("DELETE FROM objects WHERE library = ?", (library,))
            conn.execute("UPDATE libraries SET used_bytes = 0 WHERE id = ?", (library,))
        if self.blobs is not None:
            try:
                gone = self.blobs.delete_prefix(f"{library}/")
            except BlobStoreError:
                log.exception("could not delete revoked library %s from R2", library[:12])
                return False
            log.info("deleted %d objects of revoked library %s from R2", gone, library[:12])
        with self._lock, self._open() as conn:
            conn.execute("UPDATE libraries SET purged_at = ? WHERE id = ?", (time.time(), library))
        return True

    def purge_revoked(self) -> int:
        """Finish deleting every revoked library not yet purged (one revoked before
        revoking deleted anything, or one whose blob store purge failed)."""
        with self._open() as conn:
            pending = [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM libraries WHERE revoked_at IS NOT NULL AND purged_at IS NULL"
                )
            ]
        return sum(1 for library in pending if self._purge(library))

    def libraries(self) -> list[dict]:
        with self._open() as conn:
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
        with self._open() as conn:
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

    def _room(self, conn: sqlite3.Connection, library: str, name: str, size: int) -> int:
        """What the library will hold once `name` is `size` bytes; LibraryFull when that
        is past its limit, LibraryRevoked when it is gone."""
        row = conn.execute(
            "SELECT used_bytes, quota_bytes, revoked_at FROM libraries WHERE id = ?", (library,)
        ).fetchone()
        if row is not None and row["revoked_at"] is not None:
            raise LibraryRevoked("library was revoked")
        old = conn.execute(
            "SELECT size FROM objects WHERE library = ? AND name = ?", (library, name)
        ).fetchone()
        used = (row["used_bytes"] if row else 0) - ((old["size"] or 0) if old else 0) + size
        quota = row["quota_bytes"] if row and row["quota_bytes"] is not None else None
        quota = self.default_quota if quota is None else quota
        if quota and used > quota:
            raise LibraryFull(f"library is full ({quota} bytes)")
        return used

    @staticmethod
    def _new_key(library: str, name: str) -> str:
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
        return f"{library}/{digest}/{_secrets.token_hex(8)}"

    def _drop_blob(self, key: str | None) -> None:
        """Delete a copy nothing points at any more. A failure only leaves an orphan
        (storage, not data); a revoke's prefix purge still finds it."""
        if key is None or self.blobs is None:
            return
        try:
            self.blobs.delete(key)
        except BlobStoreError:
            log.warning("left an orphaned copy in R2 under %s", key.split("/", 1)[0][:12])

    def put(self, library: str, name: str, data: bytes) -> tuple[int, int]:
        """Store or overwrite an object, returning `(cursor, size)`.

        UPSERT by name: an overwrite replaces the bytes AND takes a fresh cursor
        at the head of the change feed, so `list_changed(since)` re-surfaces the
        object to a device that already pulled past its old position. Object
        names carry the writer's device prefix (`dev/{device}/...`), so an
        overwrite only ever replaces that device's own older snapshot.
        Raises LibraryFull when the write would take the library past its limit,
        BlobStoreError when the blob store cannot take the bytes (nothing changes).
        """
        size = len(data)
        key = None
        if self.blobs is not None:
            # Refuse a full library before uploading anything, then upload outside the
            # lock (the slow part), then check again as the row is switched.
            with self._open() as conn:
                self._room(conn, library, name, size)
            key = self._new_key(library, name)
            self.blobs.put(key, data)
        try:
            with self._lock, self._open() as conn:
                used = self._room(conn, library, name, size)
                old = conn.execute(
                    "SELECT blob_key FROM objects WHERE library = ? AND name = ?",
                    (library, name),
                ).fetchone()
                cursor = self._max_cursor(conn, library) + 1
                conn.execute(
                    "INSERT INTO objects (library, name, data, cursor, size, blob_key)"
                    " VALUES (?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(library, name) DO UPDATE SET data = excluded.data,"
                    " cursor = excluded.cursor, size = excluded.size,"
                    " blob_key = excluded.blob_key",
                    (library, name, b"" if key else data, cursor, size, key),
                )
                conn.execute("UPDATE libraries SET used_bytes = ? WHERE id = ?", (used, library))
        except BaseException:
            self._drop_blob(key)
            raise
        self._drop_blob(old["blob_key"] if old else None)
        return cursor, size

    def delete(self, library: str, name: str) -> bool:
        """Remove an object (a device clearing its own superseded copies). Devices that
        already pulled it keep what they applied; the change feed simply no longer
        lists it."""
        with self._lock, self._open() as conn:
            old = conn.execute(
                "SELECT blob_key FROM objects WHERE library = ? AND name = ?", (library, name)
            ).fetchone()
            if old is None:
                return False
            conn.execute("DELETE FROM objects WHERE library = ? AND name = ?", (library, name))
            self._recount(conn, library)
        self._drop_blob(old["blob_key"])
        return True

    def get(self, library: str, name: str) -> bytes | None:
        """Return the stored bytes, or None when the name is absent."""
        for _ in range(3):
            with self._open() as conn:
                row = conn.execute(
                    "SELECT data, size, blob_key FROM objects WHERE library = ? AND name = ?",
                    (library, name),
                ).fetchone()
            if row is None:
                return None
            if row["blob_key"] is None:
                return bytes(row["data"])
            if self.blobs is None:
                raise BlobStoreError("this object is in R2 and R2 is not configured")
            data = self.blobs.get(row["blob_key"])
            if data is not None:
                if len(data) != row["size"]:
                    raise BlobStoreError("the stored copy is not the size it was written at")
                return data
            # Overwritten or deleted between reading the row and fetching its copy:
            # read the row again.
        raise BlobStoreError("the stored copy is missing")

    def list_changed(self, library: str, since: int) -> tuple[list[dict], int]:
        """Every object of the library with cursor > `since`, plus the new cursor."""
        with self._open() as conn:
            rows = conn.execute(
                "SELECT name, size FROM objects"
                " WHERE library = ? AND cursor > ? ORDER BY cursor",
                (library, since),
            ).fetchall()
            cursor = self._max_cursor(conn, library)
            return [{"name": r["name"], "size": r["size"]} for r in rows], cursor

    # ---- moving bytes into the blob store --------------------------------------

    def move_to_blob_store(self) -> int:
        """Move every object whose bytes are still in the file into the blob store, one
        at a time, and return how many moved.

        Each copy is uploaded, read back and compared before its row lets go of the
        bytes, and the row is switched only if no write replaced it meanwhile (else the
        copy is dropped: the new write already went to the blob store). Safe to stop at
        any point and run again; a stop costs at most one orphaned copy. Revoked
        libraries are skipped (their purge deletes them). Raises BlobStoreError at the
        first copy that fails, leaving the rest for the next run."""
        if self.blobs is None:
            return 0
        moved, last = 0, 0
        while True:
            with self._open() as conn:
                row = conn.execute(
                    "SELECT o.rowid AS rid, o.library, o.name, o.cursor, o.data FROM objects o"
                    " LEFT JOIN libraries l ON l.id = o.library"
                    " WHERE o.blob_key IS NULL AND o.rowid > ? AND l.revoked_at IS NULL"
                    " ORDER BY o.rowid LIMIT 1",
                    (last,),
                ).fetchone()
            if row is None:
                break
            last = row["rid"]
            data = bytes(row["data"])
            key = self._new_key(row["library"], row["name"])
            self.blobs.put(key, data)
            if self.blobs.get(key) != data:
                self._drop_blob(key)
                raise BlobStoreError("a copy read back from the blob store did not match")
            with self._lock, self._open() as conn:
                switched = conn.execute(
                    "UPDATE objects SET blob_key = ?, data = x'', size = ?"
                    " WHERE rowid = ? AND cursor = ? AND blob_key IS NULL",
                    (key, len(data), row["rid"], row["cursor"]),
                ).rowcount
            if not switched:
                self._drop_blob(key)
                continue
            moved += 1
            if moved % 500 == 0:
                log.info("moved %d objects into R2 so far", moved)
        if moved:
            log.info("moved %d objects into R2; compacting the index file", moved)
            try:
                with self._lock:
                    conn = self._connect()
                    try:
                        conn.execute("VACUUM")
                    finally:
                        conn.close()
            except sqlite3.Error:
                log.exception("could not compact the relay's index file")
        return moved

    def start_upkeep(self) -> threading.Thread:
        """In the background: finish purges a failure interrupted, then move bytes still
        in the file into the blob store. Once per process; a failure waits for the next
        start, and the relay serves throughout (from the file, until a row moves)."""
        if self._upkeep is not None:
            return self._upkeep

        def run() -> None:
            try:
                self.purge_revoked()
                self.move_to_blob_store()
            except Exception:  # noqa: BLE001 - upkeep never takes the relay down
                log.exception("relay storage upkeep stopped; it runs again at the next start")

        self._upkeep = threading.Thread(target=run, name="relay-upkeep", daemon=True)
        self._upkeep.start()
        return self._upkeep
