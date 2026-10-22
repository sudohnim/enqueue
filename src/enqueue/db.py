"""SQLite access, and the migration that brings the file up to date.

The runtime talks to SQLite through SQLCipher's driver (sqlite.py), and every
connection comes from `connect`: a library encrypted at rest (any file whose first
bytes are not SQLite's plain header) is keyed with the disk key, derived from the
library key (libkey.py). `encrypt_library` turns a plain library into an encrypted one
at the engine's start, once the person has saved the recovery kit, since without the
kit a lost Keychain would lose the library itself. The runtime talks to SQLite through `sqlite3`. Alembic exists only to evolve the
schema: it is a build-time tool that happens to run at startup, not a second way to
query. Nothing below this line uses SQLAlchemy.

Migrations run once per process, before the first connection is handed out.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import resources

from . import config
from . import sqlite as sqlite3

# The revision a database created by the pre-migration `schema.sql` already matches.
# Such a file is stamped at this revision rather than replayed, because replaying it
# would try to CREATE tables that are already there.
BASELINE = "0001"

_migrated = False
_lock = threading.Lock()


def now() -> str:
    """The one clock: UTC now, ISO-8601. Every caller reads time from here."""
    return datetime.now(timezone.utc).isoformat()


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


PLAIN_HEADER = b"SQLite format 3\x00"


def is_encrypted(path=None) -> bool:
    """Whether a database file is encrypted: it has bytes, and they do not start with
    SQLite's plain header."""
    path = path or config.DB_PATH
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return False
    return bool(head) and head != PLAIN_HEADER


def disk_key() -> bytes | None:
    from . import libkey

    root = libkey.get(create=False)
    return libkey.derive(root, "disk") if root is not None else None


# Opening and closing a connection, one thread at a time. SQLite's own file locks
# (findReusableFd on open, unixLock in sqlite3WalClose on close) deadlocked when one
# thread opened the library while another closed it under load: both waited on the same
# inode mutex forever, one of them holding Python's global lock, so the whole engine
# froze, `/health` included (2026-10-22; reproduced every time by a throwaway engine
# under capture + search load). Both take microseconds, so a Python lock costs nothing,
# and a thread waiting on it gives the GIL back.
_OPEN_CLOSE = threading.Lock()


class _Connection(sqlite3.Connection):
    def close(self) -> None:
        with _OPEN_CLOSE:
            super().close()

    def __del__(self) -> None:
        # A connection dropped without close() is closed here, under the same lock,
        # rather than by the C finalizer outside it.
        try:
            self.close()
        except Exception:  # noqa: BLE001 - never raise from a finalizer
            pass


def connect(path=None, *, timeout: float = 10, key: bytes | None = None, readonly=False):
    """Open a database file; an encrypted one with `key` (default: this library's disk
    key). Refuses an encrypted file it has no key for, rather than reading noise."""
    path = path or config.DB_PATH
    target = f"file:{path}?mode=ro" if readonly else str(path)
    with _OPEN_CLOSE:
        conn = sqlite3.connect(target, timeout=timeout, uri=readonly, factory=_Connection)
    if is_encrypted(path):
        key = key or disk_key()
        if key is None:
            conn.close()
            raise sqlite3.DatabaseError(
                "the library is encrypted and this Mac does not have its key: restore it"
                " with the recovery kit (enq restore)"
            )
        conn.execute(f"PRAGMA key = \"x'{key.hex()}'\"")
    return conn


def _load_vec(conn) -> None:
    import sqlite_vec

    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)


_COUNTED = ("artifacts", "artifact_versions", "annotations", "chats", "chat_messages", "chunks")


def encrypt_library() -> str:
    """Encrypt a plain library in place, once, at the engine's start (before anything
    opens it). Only when the recovery kit is saved. Exports into a keyed copy, checks
    the copy (integrity, and the same row counts), then puts it in the original's place.
    Returns a sentence for the log, "" when there was nothing to do."""
    import os

    from . import libkey

    path = config.DB_PATH
    if not path.exists() or is_encrypted(path) or not libkey.kit_saved():
        return ""
    key = disk_key()
    tmp = path.with_name(".enqueue.encrypting.db")
    tmp.unlink(missing_ok=True)
    src = sqlite3.connect(str(path), timeout=30)
    try:
        _load_vec(src)
        src.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before = {t: src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in _COUNTED}
        src.execute(f"ATTACH DATABASE ? AS enc KEY \"x'{key.hex()}'\"", (str(tmp),))
        src.execute("SELECT sqlcipher_export('enc')")
        src.execute("DETACH DATABASE enc")
    finally:
        src.close()
    check = connect(tmp, key=key)
    try:
        _load_vec(check)
        ok = check.execute("PRAGMA integrity_check").fetchone()[0]
        after = {t: check.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in _COUNTED}
    finally:
        check.close()
    if ok != "ok" or after != before:
        tmp.unlink(missing_ok=True)
        raise sqlite3.DatabaseError(f"the encrypted copy did not check out ({ok}); left as it was")
    for suffix in ("-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    return f"encrypted the library at rest ({sum(before.values())} rows checked)"


def _tables() -> set[str]:
    if not config.DB_PATH.exists():
        return set()
    conn = connect()
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def _migrate_unlocked() -> None:
    """Bring the database to head, assuming the migration lock is held."""
    from alembic import command

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.BLOB_DIR.mkdir(parents=True, exist_ok=True)

    cfg = _alembic_config()
    tables = _tables()
    if "artifacts" in tables and "alembic_version" not in tables:
        command.stamp(cfg, BASELINE)
    command.upgrade(cfg, "head")


def restrict_permissions() -> int:
    """Make the library readable by its owner only. Returns how many paths changed.

    The data folder, the database and the blobs were created with the default mode,
    which lets every other account on the machine read every note. The folder is the
    gate (0700: nobody else can reach anything inside it); the files in it are closed
    too (0600), so a copy of one made elsewhere does not start out world-readable.
    SQLite gives its -wal and -shm files the database's mode, so they follow.
    """
    import contextlib
    import stat

    changed = 0

    def close(path, mode: int) -> None:
        nonlocal changed
        with contextlib.suppress(OSError):
            if stat.S_IMODE(path.stat().st_mode) != mode:
                path.chmod(mode)
                changed += 1

    root = config.DATA_DIR
    if not root.is_dir():
        return 0
    close(root, 0o700)
    for entry in root.iterdir():
        close(entry, 0o700 if entry.is_dir() else 0o600)
    return changed


def migrate() -> None:
    """Bring the database to head. Safe to call repeatedly and from either client.

    The lock lives here, not only in `_ensure_migrated`, because tests repoint
    `config.DB_PATH` and call `migrate` directly while the ingest worker thread may
    be migrating the same fresh file at the same moment. Two alembic upgrades on one
    file used to race to a segmentation fault.
    """
    with _lock:
        _migrate_unlocked()


def _ensure_migrated() -> None:
    global _migrated
    if _migrated:
        return
    with _lock:
        if _migrated:
            return
        _migrate_unlocked()
        _migrated = True


def set_wal(conn: sqlite3.Connection) -> None:
    """Switch the database file to WAL mode, tolerating momentary contention.

    WAL is a property of the file, not the connection, but switching to it needs
    an exclusive lock that SQLite does not queue behind the busy timeout: if
    another connection (the ingest worker, the answer worker, a request thread)
    holds the database at that instant, the PRAGMA throws SQLITE_BUSY instead
    of waiting. A retry that eventually wins is correct, because once the file
    is WAL the PRAGMA is a no-op that cannot contend. Anything that is not a
    lock error is re-raised immediately - a real failure must not be hidden.
    """
    for _ in range(200):
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
            time.sleep(0.05)
    # The last attempt is the honest one: a database that stays locked forever
    # raises, rather than looping silently.
    conn.execute("PRAGMA journal_mode = WAL")


def get_conn() -> sqlite3.Connection:
    """Open the database, migrating it first if this process has not yet."""
    _ensure_migrated()

    conn = connect()
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    set_wal(conn)
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
