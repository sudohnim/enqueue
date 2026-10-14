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
from pathlib import Path

from . import config

LEGACY = Path.home() / ".enqueue-poc"

# What the desktop shell and bin/launch may already have written to the new folder
# before the engine's first start there: one-line pointers, not library data.
_POINTERS = {"repo", "capture-position"}


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
    """Move the library from its old folder to `config.DATA_DIR`, once. Returns what
    happened, as a sentence for the engine's log ("" when there was nothing to do).

    Raises BothHoldLibraries, and changes nothing, when both folders hold files: merging
    two would be a guess, and either could be the real one. Empty folders (a `blobs/` made
    before anything was saved) are not files."""
    old = legacy or LEGACY
    new = target or config.DATA_DIR
    if old.is_symlink() or not old.is_dir() or old.resolve() == new.resolve():
        return ""
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
    return f"moved the library from {old} to {new}"
