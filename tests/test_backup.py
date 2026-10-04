"""Backups into a cloud drive's folder (backup.py) and restoring from one."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from enqueue import backup, config, notes, settings


@pytest.fixture
def drive(store, quiet_queue, tmp_path, monkeypatch):
    """A stand-in for the Proton Drive folder, chosen in Settings."""
    folder = tmp_path / "ProtonDrive"
    folder.mkdir()
    real = settings.get
    monkeypatch.setattr(
        settings, "get", lambda name: str(folder) if name == "backup_dir" else real(name)
    )
    return folder


def _tables(path: Path) -> dict:
    conn = backup._vec_conn(path)
    try:
        return {
            "notes": conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0],
            "vec_chunks": conn.execute("SELECT COUNT(*) FROM vec_chunks").fetchone()[0],
            "fts_chunks": conn.execute("SELECT COUNT(*) FROM fts_chunks").fetchone()[0],
            "embed_version": conn.execute(
                "SELECT value FROM index_meta WHERE key = 'embed_version'"
            ).fetchone(),
            "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0],
        }
    finally:
        conn.close()


def test_a_backup_holds_the_library_without_the_search_index(drive):
    notes.create(body="Tram 28 runs past the cathedral; go early")
    (config.BLOB_DIR).mkdir(parents=True, exist_ok=True)
    (config.BLOB_DIR / "abc123").write_bytes(b"an original file")
    settings.settings_path().write_text("{}", encoding="utf-8")
    from enqueue.index.store import get_store

    get_store.cache_clear()
    conn = backup._vec_conn(config.DB_PATH)
    conn.execute(
        "INSERT INTO fts_chunks (chunk_id, title, text) VALUES ('c1', 't', 'indexed text')"
    )
    conn.commit()
    conn.close()

    record = backup.run("test")

    target = drive / backup.FOLDER
    copy = target / "library" / f"enqueue-{date.today().isoformat()}.db"
    assert Path(record["file"]) == copy and copy.exists()
    t = _tables(copy)
    assert t["notes"] == 1 and t["integrity"] == "ok"
    # The index is derived and most of the file: emptied, and its version cleared so a
    # restored library rebuilds it on first start.
    assert t["fts_chunks"] == 0 and t["vec_chunks"] == 0 and t["embed_version"] is None
    assert (target / "blobs" / "abc123").read_bytes() == b"an original file"
    assert (target / "settings.json").exists()
    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest["file"] == f"library/{copy.name}" and manifest["index_included"] is False
    # Nothing half-written is ever left where the drive could upload it.
    assert not list(target.rglob("*.partial"))
    # The live library keeps its index.
    live = backup._vec_conn(config.DB_PATH)
    assert live.execute("SELECT COUNT(*) FROM fts_chunks").fetchone()[0] == 1
    live.close()


def test_nothing_changed_means_no_new_backup(drive):
    notes.create(body="a note worth keeping")
    backup.run("first")
    assert "skipped" in backup.run("daily", force=False)
    notes.create(body="something new")
    assert "skipped" not in backup.run("daily", force=False)


def test_a_failed_backup_leaves_no_partial_file(drive, monkeypatch):
    notes.create(body="a note")

    def broken(path):
        raise backup.BackupError("integrity check failed")

    monkeypatch.setattr(backup, "_slim", broken)
    with pytest.raises(backup.BackupError):
        backup.run("test")
    library = drive / backup.FOLDER / "library"
    assert list(library.iterdir()) == []


def test_backups_off_says_so(store):
    with pytest.raises(backup.BackupError, match="choose a backup folder"):
        backup.run("test")


def test_retention_keeps_a_week_of_days_and_four_weeks_before():
    today = date(2026, 10, 1)
    days = [today - timedelta(days=i) for i in range(60)]
    keep = backup._keep(days, today)
    assert set(days[:7]) <= keep
    older = sorted(keep - set(days[:7]))
    assert len(older) == 4
    assert len({d.isocalendar()[:2] for d in older}) == 4


def test_restore_sets_the_current_library_aside(drive, monkeypatch):
    notes.create(body="the note in the backup")
    backup.run("test")
    notes.create(body="written after the backup")
    monkeypatch.setattr(backup, "_engine_running", lambda: False)

    result = backup.restore(drive)

    moved = Path(result["previous_library"])
    assert (moved / "enqueue.db").exists()  # never deleted
    conn = sqlite3.connect(config.DB_PATH)
    try:
        bodies = [r[0] for r in conn.execute("SELECT body FROM artifacts")]
    finally:
        conn.close()
    assert bodies == ["the note in the backup"]


def test_restore_refuses_while_the_engine_runs(drive, monkeypatch):
    notes.create(body="a note")
    backup.run("test")
    monkeypatch.setattr(backup, "_engine_running", lambda: True)
    with pytest.raises(backup.BackupError, match="stop Enqueue first"):
        backup.restore(drive)


def test_restore_refuses_a_damaged_backup(drive, monkeypatch, tmp_path):
    bad = tmp_path / "enqueue-2026-01-01.db"
    bad.write_bytes(b"not a database at all, just bytes" * 100)
    monkeypatch.setattr(backup, "_engine_running", lambda: False)
    with pytest.raises(backup.BackupError, match="damaged"):
        backup.restore(bad)
