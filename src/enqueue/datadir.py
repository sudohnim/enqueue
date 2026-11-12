"""Where the library lives, and moving it there from where it used to live.

The library (database, blobs, settings, keyring file, backup state) lives in one
folder, `config.DATA_DIR`: `~/Library/Application Support/Enqueue` on a Mac, the place
a Mac app keeps what it owns, out of sight of the home folder. It used to be
`~/.enqueue-poc`, named for the proof of concept.

`move_legacy()` moves the old folder to the new place the first time the engine starts
after the change, before anything opens a file in it. Both are in the home folder, so
it is one rename on one disk: instant, nothing copied, nothing that can be half done.
The old name is then left as a link to the new folder, so anything that still reaches
for `~/.enqueue-poc` (an older desktop shell, a script, muscle memory) lands in the
library rather than in an empty folder. The Keychain entries (API key, sync key) are
named, not filed, and do not move.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from . import config

LEGACY = config.REAL_HOME / ".enqueue-poc"
# Where a library has lived before, oldest first: the proof of concept's folder, then
# Application Support, which the App Store sandbox cannot reach. A shipped app moves it
# into the app group, where the .dmg and the App Store build both find it.
FORMER = [LEGACY, config.REAL_HOME / "Library" / "Application Support" / "Enqueue"]

# What the desktop shell and bin/launch may already have written to the new folder
# before the engine's first start there: one-line pointers, not library data.
_POINTERS = {"repo", "capture-position"}


# A former folder the App Store sandbox would not let this engine move (the library of
# the downloaded app, still in Application Support), for Settings to say so (setup.py).
LEFT_BEHIND: list[Path] = []


class BothHoldLibraries(RuntimeError):
    """The old folder and the new one both hold files; the engine must not start on either
    until the person says which is the library."""


def _empty_tree(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink() and all(_empty_tree(p) for p in path.iterdir())


def _remove_empty(path: Path) -> None:
    for p in list(path.iterdir()):
        _remove_empty(p)
    path.rmdir()


def move_legacy(legacy: Path | None = None, target: Path | None = None) -> str:
    """Move the library from where it lived before (`FORMER`, or `legacy`) to
    `config.DATA_DIR`. Returns what happened ("" when there was nothing to do)."""
    new = target or config.DATA_DIR
    froms = [legacy] if legacy else [p for p in FORMER if p != new]
    said = []
    for old in froms:
        try:
            said.append(_move(old, new))
        except PermissionError:
            # The App Store sandbox sees the folder but may not open it. Start on the
            # app group's library; the downloaded app moves the old one there.
            LEFT_BEHIND.append(old)
            said.append(f"left {old} where it is: this app may not open it")
    return "; ".join(filter(None, said))


def _move(old: Path, new: Path) -> str:
    """Move one former folder to `new`, once. Returns what happened, as a sentence for
    the engine's log ("" when there was nothing to do).

    Raises BothHoldLibraries, and changes nothing, when both folders hold files: merging
    two would be a guess, and either could be the real one. Empty folders (a `blobs/` made
    before anything was saved) are not files."""
    if old.is_symlink() or not old.is_dir() or old.resolve() == new.resolve():
        return ""
    os.listdir(old)  # PermissionError under the App Store sandbox: the caller leaves it
    set_aside = ""
    if new.exists() and _unused_library(new):
        # A library the App Store build made before the downloaded app moved the real
        # one here: nothing was ever saved in it, so it makes way, kept beside it.
        aside = new.with_name(f"{new.name}.unused-{int(time.time())}")
        os.rename(new, aside)
        set_aside = f" (set the unused {new} aside as {aside.name})"
    if new.exists():
        extra = {p.name for p in new.iterdir() if p.name not in _POINTERS and not _empty_tree(p)}
        if extra:
            raise BothHoldLibraries(
                f"not moving {old} to {new}: both hold files ({', '.join(sorted(extra))[:80]})."
                " Keep the one that is your library and move the other aside."
            )
        # Only pointers in the new folder: they go into the library being moved, newer
        # than any copy of theirs in it, and the empty folder makes way for the rename.
        for name in _POINTERS:
            src = new / name
            if src.exists():
                os.replace(src, old / name)
        for p in list(new.iterdir()):
            _remove_empty(p)
        new.rmdir()
    new.parent.mkdir(parents=True, exist_ok=True)
    os.rename(old, new)
    try:
        old.symlink_to(new, target_is_directory=True)
    except OSError:
        pass  # the library moved; the link is a courtesy
    new.chmod(0o700)
    return f"moved the library from {old} to {new}{set_aside}"


def _unused_library(folder: Path) -> bool:
    """Whether `folder` holds a library nothing was ever saved in: a database with no
    artifacts and no original files. Anything that cannot be read is not unused."""
    db = folder / "enqueue.db"
    if not db.is_file() or any((folder / "blobs").glob("*")):
        return False
    from .sqlite import connect

    try:
        conn = connect(f"file:{db}?mode=ro", uri=True)
        try:
            return conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - encrypted, damaged or odd: keep it, say both hold
        return False
