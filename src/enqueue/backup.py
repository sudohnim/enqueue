"""Backups into a folder a cloud drive syncs (Proton Drive, by design).

The live library stays where it is (`config.DATA_DIR`). A SQLite database in WAL mode
is three files written together, and a sync client that uploads whichever it sees
mid-write keeps a torn copy; a File Provider drive may also turn a quiet file into a
cloud-only placeholder under the engine. So the drive never holds the live files.
It holds backups: a consistent copy of the database made with `VACUUM INTO`, written
under a temporary name and renamed into place only once it is whole, so the drive
only ever sees complete files.

Every file a backup puts in the drive is encrypted with the library key (libkey.py;
the `backup` key derived from it), so the drive, and whoever runs it, holds nothing
readable. The plain copy is made in the library's own folder, sealed into the drive,
and opened again to check it before it counts. The way back on a new Mac is the
recovery kit (`restore(..., kit=...)`).

What a backup holds (`<backup_dir>/Enqueue Backup/`):

- `library/enqueue-YYYY-MM-DD.db.enc` - one per day, the latest kept 7 days, then one
  per week for 4 more. The search index tables are emptied in the copy and its
  recorded embedding version cleared: they are derived, they are most of the file,
  and a restored library rebuilds them on its first start (index/bootstrap.py).
- `files/` - the original files, each sealed with its name inside and named by a keyed
  hash of it (the `backup-names` key), so the drive cannot match a file to a known one
  and only new ones are copied.
- `settings.json.enc`, `keyring.json.enc`, and `manifest.json` (not encrypted: the
  format, which key opens the backup, the date and size of the latest).

An encrypted file is the stream format of libsodium's secretstream (XChaCha20-Poly1305
in 1 MiB chunks, the last one tagged final, so a cut-short file is refused) behind a
37-byte header: `ENQB`, the format byte, the 8-byte key id, the stream header.

The first encrypted backup removes what older versions left in the clear (the `.db`
copies, `blobs/`, `settings.json`, `keyring.json`), once it has checked its own copy.
The API key stays in the Keychain and is never backed up. Vaulted items stay sealed
in the copy exactly as they are on disk.

A backup runs once a day (when something changed since the last one), when the engine
shuts down cleanly, and on demand. Restoring (`restore`) never overwrites: the current
library is moved aside first.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import shutil
import socket
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from nacl.bindings import (
    crypto_secretstream_xchacha20poly1305_init_pull,
    crypto_secretstream_xchacha20poly1305_init_push,
    crypto_secretstream_xchacha20poly1305_pull,
    crypto_secretstream_xchacha20poly1305_push,
    crypto_secretstream_xchacha20poly1305_state,
    crypto_secretstream_xchacha20poly1305_TAG_FINAL,
    crypto_secretstream_xchacha20poly1305_TAG_MESSAGE,
)
from nacl.exceptions import CryptoError

from . import config, db, libkey
from . import sqlite as sqlite3

log = logging.getLogger("enqueue.backup")

FOLDER = "Enqueue Backup"
MAGIC = b"ENQB"
FORMAT = 1
CHUNK = 1 << 20
_SEALED = ("settings.json", "keyring.json")
KEEP_DAILY = 7
KEEP_WEEKLY = 4
EVERY = timedelta(hours=24)

_lock = threading.Lock()
_running = threading.Event()


class BackupError(RuntimeError):
    """A backup or restore could not be done; the message says why, for a person."""


class Locked(BackupError):
    """The backup is locked with a key this Mac does not have: the recovery kit opens it."""


# ---- sealing -----------------------------------------------------------------------


def _keys() -> tuple[bytes, bytes, str]:
    key = libkey.get()
    return libkey.derive(key, "backup"), libkey.derive(key, "backup-names"), libkey.key_id(key)


def _header(kid: str) -> bytes:
    return MAGIC + bytes([FORMAT]) + bytes.fromhex(kid)


def _seal(src: Path, dst: Path, key: bytes, kid: str, prefix: bytes = b"") -> None:
    """Encrypt `src` (after `prefix`) into `dst`, through a partial file, so the drive
    only ever sees a whole one."""
    tmp = dst.with_name("." + dst.name + ".partial")
    state = crypto_secretstream_xchacha20poly1305_state()
    ad = _header(kid)
    with open(src, "rb") as f, open(tmp, "wb") as out:
        out.write(ad + crypto_secretstream_xchacha20poly1305_init_push(state, key))
        pending = prefix + f.read(max(0, CHUNK - len(prefix)))
        while True:
            nxt = f.read(CHUNK)
            tag = (
                crypto_secretstream_xchacha20poly1305_TAG_MESSAGE
                if nxt
                else crypto_secretstream_xchacha20poly1305_TAG_FINAL
            )
            out.write(crypto_secretstream_xchacha20poly1305_push(state, pending, ad, tag))
            if not nxt:
                break
            pending = nxt
    os.replace(tmp, dst)


def _key_id_of(path: Path) -> str:
    with open(path, "rb") as f:
        head = f.read(13)
    if len(head) < 13 or head[:4] != MAGIC or head[4] != FORMAT:
        raise BackupError(f"{path.name} is not an Enqueue backup file")
    return head[5:13].hex()


def _open(path: Path, key: bytes):
    """The plaintext of a sealed file, chunk by chunk. Refuses a wrong key, a changed
    byte, and a file cut short."""
    state = crypto_secretstream_xchacha20poly1305_state()
    with open(path, "rb") as f:
        ad = f.read(13)
        crypto_secretstream_xchacha20poly1305_init_pull(state, f.read(24), key)
        while True:
            chunk = f.read(CHUNK + 17)
            if not chunk:
                raise BackupError(f"{path.name} is cut short; pick an older backup")
            try:
                plain, tag = crypto_secretstream_xchacha20poly1305_pull(state, chunk, ad)
            except CryptoError:
                raise BackupError(f"{path.name} is damaged; pick an older backup") from None
            yield plain
            if tag == crypto_secretstream_xchacha20poly1305_TAG_FINAL:
                return


def _open_to(path: Path, key: bytes, dst: Path) -> bytes:
    """Decrypt `path` into `dst`; returns the first line when the file carries a name
    (sealed originals do), else b""."""
    first = None
    name = b""
    with open(dst, "wb") as out:
        for plain in _open(path, key):
            if first is None:
                first = plain
                if path.parent.name == "files":
                    name, _, plain = plain.partition(b"\n")
            out.write(plain)
    return name


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
        for f in sorted((target / "library").glob("enqueue-*.db.enc"), reverse=True):
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
        # Backups are locked with the library key; the kit is the way back to it.
        "kit_saved": libkey.kit_saved(),
        "library_encrypted": db.is_encrypted(),
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


def _vec_conn(path: Path, key: bytes | None = None) -> sqlite3.Connection:
    """A connection with sqlite-vec loaded: the vec0 index tables need it to be touched.
    An encrypted library (db.connect) stays encrypted in its copy, under the same key;
    the copy is sealed again on top of that."""
    conn = db.connect(path, key=key)
    db._load_vec(conn)
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


def _mirror_blobs(dst: Path, key: bytes, names: bytes, kid: str) -> int:
    """Seal original files the backup does not have yet. They never change once written,
    and each is named by a keyed hash of its own name."""
    dst.mkdir(parents=True, exist_ok=True)
    copied = 0
    if not config.BLOB_DIR.exists():
        return 0
    for f in config.BLOB_DIR.iterdir():
        if not f.is_file():
            continue
        target = dst / hmac.new(names, f.name.encode(), hashlib.sha256).hexdigest()[:40]
        if target.exists():
            continue
        _seal(f, target, key, kid, prefix=f.name.encode() + b"\n")
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
    for f in library.glob("enqueue-*.db.enc"):
        try:
            by_day[date.fromisoformat(f.name.removeprefix("enqueue-").removesuffix(".db.enc"))] = f
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

        key, names, kid = _keys()
        library = target / "library"
        library.mkdir(parents=True, exist_ok=True)
        today = date.today()
        final = library / f"enqueue-{today.isoformat()}.db.enc"

        # The plain copy is made beside the live library, never in the drive: one
        # consistent snapshot (writers and all, WAL), slimmed, then sealed into the
        # drive and opened again to check it.
        work = config.DATA_DIR / ".backup-work"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(mode=0o700)
        try:
            plain = work / "enqueue.db"
            src = _vec_conn(config.DB_PATH)
            try:
                src.execute("VACUUM INTO ?", (str(plain),))
            finally:
                src.close()
            _slim(plain)
            _seal(plain, final, key, kid)
            check = work / "check.db"
            _open_to(final, key, check)
            if _quick_check(check) != "ok":
                final.unlink(missing_ok=True)
                raise BackupError("the sealed backup did not open back to a sound copy")
        finally:
            shutil.rmtree(work, ignore_errors=True)

        blobs = _mirror_blobs(target / "files", key, names, kid)
        for name in _SEALED:
            src_file = config.DATA_DIR / name
            if src_file.exists():
                _seal(src_file, target / (name + ".enc"), key, kid)
        pruned = _prune(library, today)
        cleared = _clear_plaintext(target)

        size = final.stat().st_size
        now = datetime.now(timezone.utc).isoformat()
        manifest = {
            "format": 2,
            "encrypted": True,
            "key_id": kid,
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
            data={**record, "blobs_copied": blobs, "pruned": pruned, "plaintext_removed": cleared},
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return record
    finally:
        _running.clear()
        _lock.release()


def _quick_check(path: Path, key: bytes | None = None) -> str:
    try:
        conn = db.connect(path, key=key, readonly=True)
        try:
            return conn.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return str(exc)


def _clear_plaintext(target: Path) -> int:
    """Remove what backups from before encryption left readable in the drive. Runs only
    after a sealed backup has been checked, so the folder is never without one."""
    gone = 0
    for f in (target / "library").glob("enqueue-*.db"):
        f.unlink(missing_ok=True)
        gone += 1
    old = target / "blobs"
    if old.is_dir():
        gone += sum(1 for f in old.iterdir() if f.is_file())
        shutil.rmtree(old, ignore_errors=True)
    for name in _SEALED:
        if (target / name).exists():
            (target / name).unlink()
            gone += 1
    return gone


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
                # Drafts are thinned on the same daily beat (drafts.py), after the
                # copy, so a backup holds them as they were before thinning.
                try:
                    from . import drafts

                    drafts.thin()
                except Exception:  # noqa: BLE001 - never stop the scheduler
                    pass
            # Something shiny (shiny.py) chooses the day's sets and writes the first
            # one's words once a day, on this hourly beat; it keeps its own day stamp.
            try:
                from . import shiny

                shiny.prepare()
            except Exception:  # noqa: BLE001 - never stop the scheduler
                log.exception("something shiny could not be prepared")
            # The search index's daily upkeep (ingest/queue.py), on this hourly beat
            # whether or not backups are on; it keeps its own once-a-day stamp.
            try:
                from .ingest import queue as ingest_queue

                ingest_queue.compact_index_if_due()
            except Exception:  # noqa: BLE001 - never stop the scheduler
                log.exception("index compaction failed")
            time.sleep(3600)

    threading.Thread(target=loop, name="enqueue-backup-schedule", daemon=True).start()


# ---- restoring -------------------------------------------------------------------


def _live_port() -> int:
    """The port a running engine is on: the one it recorded, else the default.

    A restore must refuse while the engine runs, so it checks the recorded port, not
    only 8787, or it could overwrite a live library.
    """
    try:
        recorded = (config.DATA_DIR / "port").read_text().strip()
        if recorded.isdigit():
            return int(recorded)
    except OSError:
        pass
    return config.API_PORT


def _engine_running() -> bool:
    try:
        with socket.create_connection((config.API_HOST, _live_port()), timeout=0.5):
            return True
    except OSError:
        return False


def restore(source: str | os.PathLike, kit: str | None = None) -> dict:
    """Put a backup in place as the library. The engine must be stopped.

    `source` is a backup folder (its newest backup is used) or one file in it. A backup
    opens with this Mac's library key, or with the recovery kit (`kit`) on any other;
    a backup from before encryption (a plain `.db`) restores as it is. The current
    library is moved aside, never deleted, to `before-restore-<time>/`. A library
    restored with its kit keeps that key from then on (libkey.adopt). The search index
    is rebuilt by the engine on its next start.
    """
    if _engine_running():
        raise BackupError(
            f"stop Enqueue first (the engine is running on {config.API_HOST}:{_live_port()})"
        )
    src = Path(source).expanduser()
    if src.is_dir():
        folder = src / FOLDER if (src / FOLDER).is_dir() else src
        files = sorted((folder / "library").glob("enqueue-*.db.enc")) or sorted(
            (folder / "library").glob("enqueue-*.db")
        )
        if not files:
            raise BackupError(f"no backups found in {folder}")
        db_file = files[-1]
    elif src.is_file():
        db_file = src
        folder = src.parent.parent
    else:
        raise BackupError(f"{src} does not exist")

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = adopt = None
    if db_file.name.endswith(".enc"):
        kid = _key_id_of(db_file)
        mine = libkey.get(create=False)
        if mine is not None and libkey.key_id(mine) == kid:
            root = mine
        elif kit:
            root = libkey.from_kit(kit)
            if libkey.key_id(root) != kid:
                raise BackupError("that recovery kit is for a different library")
            adopt = root
        else:
            raise Locked(
                "this backup is locked with its library's key, which this Mac does not"
                " have: the recovery kit opens it"
            )
        key = libkey.derive(root, "backup")
        incoming = config.DATA_DIR / ".restore.partial"
        try:
            _open_to(db_file, key, incoming)
        except BackupError:
            incoming.unlink(missing_ok=True)
            raise
    else:
        incoming = db_file

    ok = _quick_check(incoming, key=libkey.derive(adopt, "disk") if adopt else None)
    if ok != "ok":
        if incoming != db_file:
            incoming.unlink(missing_ok=True)
        raise BackupError(f"{db_file.name} is damaged ({ok}); pick an older backup")

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

    if incoming == db_file:
        shutil.copy2(db_file, config.DB_PATH)
    else:
        os.replace(incoming, config.DB_PATH)
    db.forget_readers()
    restored_blobs = 0
    config.BLOB_DIR.mkdir(parents=True, exist_ok=True)
    if key is not None and (folder / "files").is_dir():
        for f in (folder / "files").iterdir():
            if not f.is_file() or f.name.startswith("."):
                continue
            tmp = config.BLOB_DIR / ".restoring"
            name = _open_to(f, key, tmp).decode("utf-8", "replace")
            dest = config.BLOB_DIR / Path(name).name
            if name and not dest.exists():
                os.replace(tmp, dest)
                restored_blobs += 1
            else:
                tmp.unlink(missing_ok=True)
    if (folder / "blobs").is_dir():
        for f in (folder / "blobs").iterdir():
            if f.is_file() and not (config.BLOB_DIR / f.name).exists():
                shutil.copy2(f, config.BLOB_DIR / f.name)
                restored_blobs += 1
    # Settings and the wrapped sync key only fill a gap (a new Mac); a library being
    # rolled back keeps the ones it has.
    for name in _SEALED:
        here = config.DATA_DIR / name
        if here.exists():
            continue
        if key is not None and (folder / (name + ".enc")).exists():
            _open_to(folder / (name + ".enc"), key, here)
        elif (folder / name).exists():
            shutil.copy2(folder / name, here)
    if adopt is not None:
        libkey.adopt(adopt)
    return {
        "restored": str(db_file),
        "blobs": restored_blobs,
        "previous_library": str(moved_to) if moved_to else None,
    }
