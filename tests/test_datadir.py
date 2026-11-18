"""The library's folder moved from ~/.enqueue-poc to Application Support (datadir.py):
once, as one rename, with a link left at the old name, and never over another library."""

from __future__ import annotations

import pytest

from enqueue import datadir


def _library(at):
    at.mkdir(parents=True)
    (at / "enqueue.db").write_text("db")
    (at / "blobs").mkdir()
    (at / "blobs" / "abc").write_text("blob")
    return at


def test_the_old_folder_moves_and_its_name_still_leads_there(tmp_path):
    old = _library(tmp_path / ".enqueue-poc")
    new = tmp_path / "Library" / "Application Support" / "Enqueue"

    said = datadir.move_legacy(old, new)

    assert said.startswith("moved the library")
    assert (new / "enqueue.db").read_text() == "db"
    assert (new / "blobs" / "abc").read_text() == "blob"
    assert old.is_symlink() and (old / "enqueue.db").read_text() == "db"
    assert datadir.move_legacy(old, new) == "", "only once"


def test_pointers_written_to_the_new_folder_first_are_kept(tmp_path):
    old = _library(tmp_path / ".enqueue-poc")
    (old / "repo").write_text("/old/repo")
    new = tmp_path / "AppSupport" / "Enqueue"
    new.mkdir(parents=True)
    (new / "repo").write_text("/new/repo")  # bin/launch wrote it before the engine ran

    datadir.move_legacy(old, new)

    assert (new / "repo").read_text() == "/new/repo"
    assert (new / "enqueue.db").exists()


def test_two_libraries_are_never_merged(tmp_path):
    old = _library(tmp_path / ".enqueue-poc")
    new = _library(tmp_path / "AppSupport" / "Enqueue")
    (new / "enqueue.db").write_text("the other one")

    with pytest.raises(datadir.BothHoldLibraries):
        datadir.move_legacy(old, new)

    assert (old / "enqueue.db").read_text() == "db" and not old.is_symlink()
    assert (new / "enqueue.db").read_text() == "the other one"


def test_nothing_to_move(tmp_path):
    assert datadir.move_legacy(tmp_path / "missing", tmp_path / "new") == ""


def test_empty_folders_in_the_new_place_do_not_block_the_move(tmp_path):
    old = _library(tmp_path / ".enqueue-poc")
    new = tmp_path / "AppSupport" / "Enqueue"
    (new / "blobs").mkdir(parents=True)  # made before anything was saved there
    (new / "repo").write_text("/new/repo")

    said = datadir.move_legacy(old, new)

    assert said.startswith("moved the library")
    assert (new / "blobs" / "abc").read_text() == "blob"
    assert (new / "repo").read_text() == "/new/repo"


def test_a_shipped_app_moves_the_library_through_every_former_home(tmp_path, monkeypatch):
    poc, support, group = tmp_path / ".enqueue-poc", tmp_path / "Support", tmp_path / "Group"
    support.mkdir()
    (support / "enqueue.db").write_text("library")
    poc.symlink_to(support, target_is_directory=True)
    monkeypatch.setattr(datadir, "FORMER", [poc, support])

    said = datadir.move_legacy(target=group)

    assert (group / "enqueue.db").read_text() == "library"
    assert support.is_symlink() and (support / "enqueue.db").read_text() == "library"
    assert (poc / "enqueue.db").read_text() == "library"
    assert str(group) in said
    assert datadir.move_legacy(target=group) == ""


def test_a_shipped_app_keeps_the_library_in_the_app_group():
    import os
    import subprocess
    import sys

    def data_dir(channel: str) -> str:
        env = {k: v for k, v in os.environ.items() if k not in ("ENQ_DATA_DIR", "ENQ_CHANNEL")}
        if channel:
            env["ENQ_CHANNEL"] = channel
        code = "from enqueue import config; print(config.DATA_DIR)"
        return subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
        ).stdout.strip()

    if sys.platform != "darwin":
        return
    assert data_dir("mas").endswith("Group Containers/572NMYL3ZG.com.sudohnim.enqueue/Enqueue")
    assert data_dir("dmg") == data_dir("mas")
    assert data_dir("").endswith("Application Support/Enqueue")


def test_a_former_folder_the_sandbox_will_not_move_is_left_and_said(tmp_path, monkeypatch):
    old, new = tmp_path / "Support", tmp_path / "Group"
    old.mkdir()
    (old / "enqueue.db").write_text("library")
    monkeypatch.setattr(datadir, "FORMER", [old])
    monkeypatch.setattr(datadir, "LEFT_BEHIND", [])

    def refuse(*_):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(datadir.os, "rename", refuse)
    said = datadir.move_legacy(target=new)

    assert "left" in said and datadir.LEFT_BEHIND == [old]
    assert (old / "enqueue.db").exists()


def test_an_unused_library_in_the_new_place_makes_way_for_the_real_one(tmp_path):
    from enqueue.sqlite import connect

    old, new = tmp_path / "Support", tmp_path / "Group"
    old.mkdir()
    (old / "enqueue.db").write_text("library")
    new.mkdir()
    conn = connect(str(new / "enqueue.db"))
    conn.execute("CREATE TABLE artifacts (id TEXT)")
    conn.commit()
    conn.close()

    said = datadir.move_legacy(old, new)

    assert (new / "enqueue.db").read_text() == "library"
    assert "unused" in said and len(list(tmp_path.glob("Group.unused-*"))) == 1


def test_a_used_library_in_the_new_place_still_blocks_the_move(tmp_path):
    from enqueue.sqlite import connect

    old, new = tmp_path / "Support", tmp_path / "Group"
    old.mkdir()
    (old / "enqueue.db").write_text("library")
    new.mkdir()
    conn = connect(str(new / "enqueue.db"))
    conn.execute("CREATE TABLE artifacts (id TEXT)")
    conn.execute("INSERT INTO artifacts VALUES ('a')")
    conn.commit()
    conn.close()

    with pytest.raises(datadir.BothHoldLibraries):
        datadir.move_legacy(old, new)


def test_a_named_data_folder_never_takes_the_real_library(tmp_path, monkeypatch):
    old = tmp_path / "Application Support" / "Enqueue"
    old.mkdir(parents=True)
    (old / "enqueue.db").write_text("real")
    monkeypatch.setattr(datadir, "FORMER", [old])
    monkeypatch.setattr(datadir.config, "DATA_DIR", tmp_path / "scratch")
    monkeypatch.setenv("ENQ_DATA_DIR", str(tmp_path / "scratch"))
    assert datadir.move_legacy() == ""
    assert (old / "enqueue.db").read_text() == "real"
