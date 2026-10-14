"""What changed between two versions of a note (static/js/diff.js).

Browser code shared by the desktop and the phone, so its cases live in tests/js/diff.js
and run under node, like the markdown round trip.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent / "js" / "diff.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_changes_are_marked_inside_the_notes_own_shape():
    run = subprocess.run(
        ["node", str(SCRIPT)], capture_output=True, text=True, timeout=60, check=False
    )
    assert run.returncode == 0, run.stdout + run.stderr
