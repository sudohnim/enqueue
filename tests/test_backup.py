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


def _opened(copy: Path) -> Path:
    """A sealed backup opened back to a database file, for looking inside it."""
    from enqueue import libkey

    out = copy.with_name("opened.db")
    backup._open_to(copy, libkey.derive(libkey.get(), "backup"), out)
    return out


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
    copy = target / "library" / f"enqueue-{date.today().isoformat()}.db.enc"
    assert Path(record["file"]) == copy and copy.exists()
    t = _tables(_opened(copy))
    assert t["notes"] == 1 and t["integrity"] == "ok"
    # The index is derived and most of the file: emptied, and its version cleared so a
    # restored library rebuilds it on first start.
    assert t["fts_chunks"] == 0 and t["vec_chunks"] == 0 and t["embed_version"] is None
    assert len(list((target / "files").iterdir())) == 1
    assert (target / "settings.json.enc").exists()
    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest["file"] == f"library/{copy.name}" and manifest["index_included"] is False
    assert manifest["encrypted"] is True
    # Nothing half-written is ever left where the drive could upload it, and the plain
    # working copy never left the library's folder.
    assert not list(target.rglob("*.partial"))
    assert not (config.DATA_DIR / ".backup-work").exists()
    # The live library keeps its index.
    live = backup._vec_conn(config.DB_PATH)
    assert live.execute("SELECT COUNT(*) FROM fts_chunks").fetchone()[0] == 1
    live.close()


def test_nothing_in_the_drive_can_be_read(drive):
    """Zero-knowledge: no word of a note, no original file, no file name, in any file."""
    notes.create(body="the pin to the safe is under the blue vase")
    config.BLOB_DIR.mkdir(parents=True, exist_ok=True)
    (config.BLOB_DIR / "deadbeef00").write_bytes(b"passport scan bytes")
    settings.settings_path().write_text('{"llm_model": "secret-model-name"}', encoding="utf-8")
    backup.run("test")
    every = b"".join(f.read_bytes() for f in (drive / backup.FOLDER).rglob("*") if f.is_file())
    names = " ".join(f.name for f in (drive / backup.FOLDER).rglob("*"))
    for words in (b"blue vase", b"passport scan", b"secret-model-name", b"SQLite format"):
        assert words not in every
    assert "deadbeef00" not in names


def test_the_first_sealed_backup_removes_the_plain_ones(drive):
    target = drive / backup.FOLDER
    (target / "library").mkdir(parents=True)
    (target / "library" / "enqueue-2026-10-01.db").write_bytes(b"old plain copy")
    (target / "blobs").mkdir()
    (target / "blobs" / "abc").write_bytes(b"old plain file")
    (target / "settings.json").write_text("{}")
    notes.create(body="a note")

    record = backup.run("test")

    assert not (target / "library" / "enqueue-2026-10-01.db").exists()
    assert not (target / "blobs").exists() and not (target / "settings.json").exists()
    assert Path(record["file"]).exists()


def test_a_cut_short_or_changed_backup_is_refused(drive, tmp_path):
    from enqueue import libkey

    notes.create(body="a note")
    copy = Path(backup.run("test")["file"])
    key = libkey.derive(libkey.get(), "backup")
    data = copy.read_bytes()
    short = tmp_path / "short.db.enc"
    short.write_bytes(data[: len(data) // 2])
    with pytest.raises(backup.BackupError):
        backup._open_to(short, key, tmp_path / "out.db")
    changed = tmp_path / "changed.db.enc"
    changed.write_bytes(data[:100] + bytes([data[100] ^ 1]) + data[101:])
    with pytest.raises(backup.BackupError, match="damaged"):
        backup._open_to(changed, key, tmp_path / "out.db")


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


def test_a_new_mac_opens_a_backup_with_the_recovery_kit(drive, monkeypatch):
    from enqueue import libkey

    notes.create(body="the note in the backup")
    config.BLOB_DIR.mkdir(parents=True, exist_ok=True)
    (config.BLOB_DIR / "abc123").write_bytes(b"an original file")
    backup.run("test")
    kit = libkey.kit(libkey.get())
    old_id = libkey.key_id(libkey.get())
    monkeypatch.setattr(backup, "_engine_running", lambda: False)
    # A new Mac: no library key, no library, no files.
    monkeypatch.setattr(libkey, "_load", lambda: None)
    adopted = []
    monkeypatch.setattr(libkey, "adopt", adopted.append)
    config.DB_PATH.unlink()
    (config.BLOB_DIR / "abc123").unlink()

    with pytest.raises(backup.Locked):
        backup.restore(drive)
    other = libkey.kit(bytes(32))
    with pytest.raises(backup.BackupError, match="different library"):
        backup.restore(drive, kit=other)
    result = backup.restore(drive, kit=kit.lower().replace("-", " "))

    conn = sqlite3.connect(config.DB_PATH)
    try:
        bodies = [r[0] for r in conn.execute("SELECT body FROM artifacts")]
    finally:
        conn.close()
    assert bodies == ["the note in the backup"]
    assert (config.BLOB_DIR / "abc123").read_bytes() == b"an original file"
    assert result["blobs"] == 1
    assert [libkey.key_id(k) for k in adopted] == [old_id], "the Mac keeps the backup's key"


def test_the_recovery_kit_reads_back_and_catches_typos():
    from enqueue import libkey

    key = bytes(range(32))
    kit = libkey.kit(key)
    assert len(kit.replace("-", "")) == 56
    assert libkey.from_kit(kit) == key
    assert libkey.from_kit(kit.lower().replace("0", "o")) == key
    typo = ("Z" if kit[0] != "Z" else "Y") + kit[1:]
    with pytest.raises(libkey.KitError, match="typo"):
        libkey.from_kit(typo)
    with pytest.raises(libkey.KitError, match="56"):
        libkey.from_kit(kit[:-5])


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
