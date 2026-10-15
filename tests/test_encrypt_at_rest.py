"""The library encrypted at rest (db.encrypt_library, db.connect): only once the recovery
kit is saved, readable by the engine and search afterwards, and by nothing else."""

from __future__ import annotations

import sqlite3

import pytest

from enqueue import backup, config, db, libkey, notes, settings


def _write_index_row():
    conn = backup._vec_conn(config.DB_PATH)
    try:
        conn.execute(
            "INSERT INTO fts_chunks (chunk_id, title, text) VALUES ('c1', 't', 'cormorant')"
        )
        conn.commit()
    finally:
        conn.close()


def test_nothing_is_encrypted_before_the_kit_is_saved(store, quiet_queue):
    notes.create(body="a note")
    assert db.encrypt_library() == ""
    assert not db.is_encrypted()


def test_an_encrypted_library_reads_as_before_and_as_noise_without_the_key(store, quiet_queue):
    aid = notes.create(body="the cormorant dives at dawn")["artifact"]["id"]
    _write_index_row()
    libkey.get()
    libkey.mark_kit_saved()

    said = db.encrypt_library()

    assert said.startswith("encrypted the library")
    assert db.is_encrypted()
    raw = config.DB_PATH.read_bytes()
    assert b"cormorant" not in raw and not raw.startswith(db.PLAIN_HEADER)
    # The engine reads it as before, index included.
    assert notes.get(aid)["artifact"]["body"] == "the cormorant dives at dawn"
    conn = backup._vec_conn(config.DB_PATH)
    try:
        hit = conn.execute("SELECT text FROM fts_chunks WHERE fts_chunks MATCH 'cormorant'")
        assert hit.fetchone()[0] == "cormorant"
    finally:
        conn.close()
    # Anything without the key reads nothing.
    plain = sqlite3.connect(config.DB_PATH)
    with pytest.raises(sqlite3.DatabaseError):
        plain.execute("SELECT COUNT(*) FROM artifacts").fetchone()
    plain.close()
    assert db.encrypt_library() == "", "once"


def test_an_encrypted_library_is_backed_up_and_restored_on_a_new_mac(
    store, quiet_queue, tmp_path, monkeypatch
):
    folder = tmp_path / "Drive"
    folder.mkdir()
    real = settings.get
    monkeypatch.setattr(
        settings, "get", lambda name: str(folder) if name == "backup_dir" else real(name)
    )
    notes.create(body="kept through a new Mac")
    libkey.get()
    libkey.mark_kit_saved()
    db.encrypt_library()
    backup.run("test")
    kit = libkey.kit(libkey.get())

    # A new Mac: no key, no library.
    monkeypatch.setattr(backup, "_engine_running", lambda: False)
    monkeypatch.setattr(libkey, "_load", lambda: None)
    adopted = []
    monkeypatch.setattr(libkey, "adopt", adopted.append)
    config.DB_PATH.unlink()
    backup.restore(folder, kit=kit)

    assert db.is_encrypted(), "it stays encrypted, under the same key"
    conn = db.connect(key=libkey.derive(adopted[0], "disk"))
    try:
        assert conn.execute("SELECT body FROM artifacts").fetchone()[0] == "kept through a new Mac"
    finally:
        conn.close()
