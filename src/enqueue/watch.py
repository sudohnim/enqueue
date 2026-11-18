"""Folders the person asked Enqueue to watch: each new file in one is kept.

Only files that appear after a folder was added are taken. Files that were there
before stay as they are; the person brings those in with an import."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from . import capture, db, settings

log = logging.getLogger(__name__)
SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".md", ".txt"}
MAX_BYTES = 25 * 1024 * 1024
PER_SCAN = 25
EVERY_S = 600
SETTLE_S = 60


def folders() -> list[Path]:
    raw = str(settings.get("watch_dirs") or "")
    return [Path(line.strip()).expanduser() for line in raw.splitlines() if line.strip()]


def _row(source: str, external_id: str):
    conn = db.get_conn()
    try:
        return conn.execute(
            "SELECT stamp FROM source_items WHERE source = ? AND external_id = ?",
            (source, external_id),
        ).fetchone()
    finally:
        conn.close()


def _keep(source: str, external_id: str, stamp: str, artifact_id: str | None) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO source_items (source, external_id, stamp, artifact_id)"
            " VALUES (?, ?, ?, ?)",
            (source, external_id, stamp, artifact_id),
        )


def _since(folder: Path, now: float) -> float:
    """When watching of this folder began. The first look records it."""
    row = _row("watch-folder", str(folder))
    if row is not None:
        return float(row["stamp"])
    _keep("watch-folder", str(folder), str(now), None)
    return now


def begin(now: float | None = None) -> None:
    """Watching a folder begins when it is added, not at the next look."""
    now = time.time() if now is None else now
    for folder in folders():
        _since(folder, now)


def scan(now: float | None = None) -> dict:
    """Take up to PER_SCAN new files. Returns how many were taken."""
    now = time.time() if now is None else now
    taken = 0
    for folder in folders():
        if not folder.is_dir():
            continue
        since = _since(folder, now)
        for f in sorted(folder.iterdir()):
            if taken >= PER_SCAN:
                return {"taken": taken}
            try:
                if not f.is_file() or f.name.startswith("."):
                    continue
                if f.suffix.lower() not in SUFFIXES:
                    continue
                st = f.stat()
                if st.st_size == 0 or st.st_size > MAX_BYTES:
                    continue
                # A file moved in keeps its old modified time; its change time is new.
                if max(st.st_mtime, st.st_ctime) < since or now - st.st_mtime < SETTLE_S:
                    continue
                stamp = f"{int(st.st_mtime)}:{st.st_size}"
                row = _row("watch", str(f))
                if row is not None and row["stamp"] == stamp:
                    continue
                out = capture.upload(f.read_bytes(), f.name, background=True)
                _keep("watch", str(f), stamp, out.get("id"))
                taken += 1
            except Exception:  # noqa: BLE001 - one bad file never stops the rest
                log.exception("could not keep %s", f.name)
    return {"taken": taken}


def start() -> None:
    """Look every EVERY_S seconds, for as long as the engine runs."""

    def loop() -> None:
        time.sleep(120)
        while True:
            try:
                scan()
            except Exception:  # noqa: BLE001 - the watcher must outlive one bad look
                log.exception("watch scan failed")
            time.sleep(EVERY_S)

    threading.Thread(target=loop, name="watch-folders", daemon=True).start()
