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
