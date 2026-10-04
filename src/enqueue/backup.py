"""Backups into a folder a cloud drive syncs (Proton Drive, by design).

The live library stays where it is (`~/.enqueue-poc`). A SQLite database in WAL mode
is three files written together, and a sync client that uploads whichever it sees
mid-write keeps a torn copy; a File Provider drive may also turn a quiet file into a
cloud-only placeholder under the engine. So the drive never holds the live files.
It holds backups: a consistent copy of the database made with `VACUUM INTO`, written
under a temporary name and renamed into place only once it is whole, so the drive
only ever sees complete files.

What a backup holds (`<backup_dir>/Enqueue Backup/`):

- `library/enqueue-YYYY-MM-DD.db` - one per day, the latest kept 7 days, then one per
  week for 4 more. The search index tables are emptied in the copy and its recorded
  embedding version cleared: they are derived, they are most of the file, and a
  restored library rebuilds them on its first start (index/bootstrap.py).
- `blobs/` - the original files, content-addressed, so only new ones are copied.
- `settings.json`, `keyring.json` (the sync key, wrapped under the recovery phrase -
  useless without it), and `manifest.json` describing the latest backup.

The API key stays in the Keychain and is never backed up. Vaulted items stay
encrypted in the copy exactly as they are on disk.

A backup runs once a day (when something changed since the last one), when the engine
shuts down cleanly, and on demand. Restoring (`restore`) never overwrites: the current
library is moved aside first.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config

FOLDER = "Enqueue Backup"
KEEP_DAILY = 7
KEEP_WEEKLY = 4
EVERY = timedelta(hours=24)

_lock = threading.Lock()
_running = threading.Event()


class BackupError(RuntimeError):
    """A backup or restore could not be done; the message says why, for a person."""


# ---- where -----------------------------------------------------------------------


def proton_drive_folders() -> list[str]:
    """The Proton Drive folders this Mac syncs (macOS File Provider locations).

    A folder with a date in parentheses is one macOS kept from an older account
    session; the live one is listed first.
    """
    root = Path.home() / "Library" / "CloudStorage"
    try:
        found = [p for p in root.iterdir() if p.is_dir() and p.name.startswith("ProtonDrive")]
    except OSError:
        return []
    return [str(p) for p in sorted(found, key=lambda p: ("(" in p.name, p.name))]


def configured_dir() -> Path | None:
    """The folder backups go into, or None when backups are off."""
    from . import settings

    raw = str(settings.get("backup_dir") or "").strip()
    return Path(raw).expanduser() / FOLDER if raw else None


def _state_path() -> Path:
    return config.DATA_DIR / "backup.json"


def last() -> dict | None:
    """The last backup this engine made, as recorded beside the library."""
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def status() -> dict:
    target = configured_dir()
    backups = []
    if target is not None:
        for f in sorted((target / "library").glob("enqueue-*.db"), reverse=True):
            try:
                backups.append({"file": f.name, "bytes": f.stat().st_size})
            except OSError:
                continue
    return {
        "dir": str(target.parent) if target else "",
        "folder": str(target) if target else "",
        "detected": proton_drive_folders(),
        "running": _running.is_set(),
        "last": last(),
        "backups": backups,
    }


# ---- making one ------------------------------------------------------------------


def _change_stamp() -> str:
    """A fingerprint of everything a person writes, to skip a backup when nothing changed."""
    from . import db

    conn = db.get_conn()
    try:
        parts = []
        for sql in (
            "SELECT COUNT(*), MAX(updated_at) FROM artifacts",
            "SELECT COUNT(*), MAX(created_at) FROM artifact_versions",
            "SELECT COUNT(*), MAX(created_at) FROM annotations",
            "SELECT COUNT(*), MAX(updated_at) FROM chats",
            "SELECT COUNT(*) FROM saved_pivots",
            "SELECT COUNT(*) FROM tags",
        ):
            try:
                parts.append(repr(tuple(conn.execute(sql).fetchone())))
            except sqlite3.Error:
                parts.append("-")
        return "|".join(parts)
    finally:
        conn.close()


def _vec_conn(path: Path) -> sqlite3.Connection:
    """A connection with sqlite-vec loaded: the vec0 index tables need it to be touched."""
    import sqlite_vec

    conn = sqlite3.connect(str(path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def _slim(path: Path) -> None:
    """Empty the derived search index in a copy, and check the copy is sound."""
    from .index.store_sqlite import _DDL

    conn = _vec_conn(path)
    try:
        for drop, create in _DDL.values():
            conn.execute(drop)
            conn.execute(create)
        # A missing version is what makes the engine rebuild the index on start.
        conn.execute("DELETE FROM index_meta WHERE key = 'embed_version'")
        conn.commit()
        conn.execute("VACUUM")
        ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise BackupError(f"the backup copy failed its integrity check ({ok})")
    finally:
        conn.close()


def _copy_atomic(src: Path, dst: Path) -> None:
    tmp = dst.with_name("." + dst.name + ".partial")
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def _mirror_blobs(dst: Path) -> int:
    """Copy original files the backup does not have yet. They never change once written."""
    dst.mkdir(parents=True, exist_ok=True)
    copied = 0
    if not config.BLOB_DIR.exists():
        return 0
    for f in config.BLOB_DIR.iterdir():
        if not f.is_file():
            continue
        target = dst / f.name
        try:
            if target.exists() and target.stat().st_size == f.stat().st_size:
                continue
        except OSError:
            pass
        _copy_atomic(f, target)
        copied += 1
    return copied


def _keep(days: list[date], today: date) -> set[date]:
    """Which daily backups to keep: the newest KEEP_DAILY, then the newest of each of
    the KEEP_WEEKLY weeks before them."""
    newest = sorted(days, reverse=True)
    keep = set(newest[:KEEP_DAILY])
    weeks: dict[tuple[int, int], date] = {}
    for d in newest[KEEP_DAILY:]:
        week = d.isocalendar()[:2]
        if week not in weeks and len(weeks) < KEEP_WEEKLY:
            weeks[week] = d
    keep.update(weeks.values())
    return keep


def _prune(library: Path, today: date) -> int:
    by_day = {}
    for f in library.glob("enqueue-*.db"):
        try:
            by_day[date.fromisoformat(f.stem.removeprefix("enqueue-"))] = f
        except ValueError:
            continue
    keep = _keep(list(by_day), today)
    gone = 0
    for d, f in by_day.items():
        if d not in keep:
            f.unlink(missing_ok=True)
            gone += 1
    return gone


def _schema_version() -> str:
    from . import db

    conn = db.get_conn()
    try:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        return row[0] if row else ""
    except sqlite3.Error:
        return ""
    finally:
        conn.close()


def run(reason: str = "manual", force: bool = True) -> dict:
    """Make a backup now. `force=False` skips it when nothing changed since the last one."""
    from . import events

    target = configured_dir()
    if target is None:
        raise BackupError("backups are off: choose a backup folder in Settings first")
    if not target.parent.exists():
        raise BackupError(f"the backup folder {target.parent} is not there (is the drive running?)")
    if not _lock.acquire(blocking=False):
        return {"skipped": "a backup is already running"}
    _running.set()
    started = time.monotonic()
    try:
        stamp = _change_stamp()
        prev = last() or {}
        if not force and prev.get("stamp") == stamp and prev.get("folder") == str(target):
            return {"skipped": "nothing changed since the last backup"}

        library = target / "library"
        library.mkdir(parents=True, exist_ok=True)
        today = date.today()
        final = library / f"enqueue-{today.isoformat()}.db"
        partial = library / f".enqueue-{today.isoformat()}.db.partial"
        partial.unlink(missing_ok=True)

        # One consistent snapshot of the live database, writers and all (WAL).
        src = _vec_conn(config.DB_PATH)
        try:
            src.execute("VACUUM INTO ?", (str(partial),))
        finally:
            src.close()
        try:
            _slim(partial)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        os.replace(partial, final)

        blobs = _mirror_blobs(target / "blobs")
        for name in ("settings.json", "keyring.json"):
            src_file = config.DATA_DIR / name
            if src_file.exists():
                _copy_atomic(src_file, target / name)
        pruned = _prune(library, today)

        size = final.stat().st_size
        now = datetime.now(timezone.utc).isoformat()
        manifest = {
            "created_at": now,
            "file": f"library/{final.name}",
            "bytes": size,
            "schema": _schema_version(),
            "embed_version": config.EMBED_VERSION,
            "index_included": False,
            "reason": reason,
        }
        tmp = target / ".manifest.json.partial"
        tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        os.replace(tmp, target / "manifest.json")

        record = {
            "at": now,
            "file": str(final),
            "bytes": size,
            "folder": str(target),
            "stamp": stamp,
            "reason": reason,
            "seconds": round(time.monotonic() - started, 1),
        }
        tmp = _state_path().with_name(".backup.json.partial")
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(tmp, _state_path())
        events.emit(
            "backup",
            f"backed up to {target.parent.name} ({size // 1_000_000} MB)",
            data={**record, "blobs_copied": blobs, "pruned": pruned},
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return record
    finally:
        _running.clear()
        _lock.release()


def run_quietly(reason: str, force: bool = False) -> None:
    """A backup nobody is waiting on: failures are logged, never raised."""
    from . import events

    if configured_dir() is None:
        return
    try:
        run(reason, force=force)
    except Exception as exc:  # noqa: BLE001 - background work reports, never raises
        events.emit("backup.failed", f"backup did not run: {exc}", data={"reason": reason})


def run_soon(reason: str = "manual", force: bool = True) -> None:
    threading.Thread(
        target=run_quietly, args=(reason, force), name="enqueue-backup", daemon=True
    ).start()


def start_scheduler() -> None:
    """Back up once a day, when something changed. First look a few minutes after start
    so a backup never competes with the startup index work."""

    def loop() -> None:
        time.sleep(300)
        while True:
            prev = last()
            due = True
            if prev:
                try:
                    due = datetime.now(timezone.utc) - datetime.fromisoformat(prev["at"]) >= EVERY
                except (KeyError, ValueError):
                    due = True
            if due:
                run_quietly("daily")
            time.sleep(3600)

    threading.Thread(target=loop, name="enqueue-backup-schedule", daemon=True).start()


# ---- restoring -------------------------------------------------------------------


def _engine_running() -> bool:
    try:
        with socket.create_connection((config.API_HOST, config.API_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def restore(source: str | os.PathLike) -> dict:
    """Put a backup in place as the library. The engine must be stopped.

    `source` is a backup folder (its newest backup is used) or one `.db` file in it.
    The current library is moved aside, never deleted, to `before-restore-<time>/`.
    The search index is rebuilt by the engine on its next start.
    """
    if _engine_running():
        raise BackupError("stop Enqueue first (the engine is running on 127.0.0.1:8787)")
    src = Path(source).expanduser()
    if src.is_dir():
        folder = src / FOLDER if (src / FOLDER).is_dir() else src
        files = sorted((folder / "library").glob("enqueue-*.db"))
        if not files:
            raise BackupError(f"no backups found in {folder}")
        db_file = files[-1]
    elif src.is_file():
        db_file = src
        folder = src.parent.parent
    else:
        raise BackupError(f"{src} does not exist")

    try:
        check = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        try:
            ok = check.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            check.close()
    except sqlite3.DatabaseError as exc:
        ok = str(exc)
    if ok != "ok":
        raise BackupError(f"{db_file.name} is damaged ({ok}); pick an older backup")

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    moved_to = None
    live = [config.DB_PATH.with_name(config.DB_PATH.name + s) for s in ("", "-wal", "-shm")]
    if any(p.exists() for p in live):
        moved_to = config.DATA_DIR / (
            "before-restore-" + datetime.now().strftime("%Y-%m-%d-%H%M%S")
        )
        moved_to.mkdir()
        for p in live:
            if p.exists():
                shutil.move(str(p), moved_to / p.name)

    shutil.copy2(db_file, config.DB_PATH)
    restored_blobs = 0
    if (folder / "blobs").is_dir():
        config.BLOB_DIR.mkdir(parents=True, exist_ok=True)
        for f in (folder / "blobs").iterdir():
            if f.is_file() and not (config.BLOB_DIR / f.name).exists():
                shutil.copy2(f, config.BLOB_DIR / f.name)
                restored_blobs += 1
    # Settings and the wrapped sync key only fill a gap (a new Mac); a library being
    # rolled back keeps the ones it has.
    for name in ("settings.json", "keyring.json"):
        if (folder / name).exists() and not (config.DATA_DIR / name).exists():
            shutil.copy2(folder / name, config.DATA_DIR / name)
    return {
        "restored": str(db_file),
        "blobs": restored_blobs,
        "previous_library": str(moved_to) if moved_to else None,
    }
