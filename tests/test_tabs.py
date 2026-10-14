"""Tabs inside a note (static/js/tabs.js), kept as marker lines in the markdown.

Browser code shared by the desktop and the phone, so its cases live in tests/js/tabs.js
and run under node.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent / "js" / "tabs.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_tabs_are_kept_in_the_notes_own_text():
    run = subprocess.run(
        ["node", str(SCRIPT)], capture_output=True, text=True, timeout=60, check=False
    )
    assert run.returncode == 0, run.stdout + run.stderr
