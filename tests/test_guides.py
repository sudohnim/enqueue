"""The guides behind the ? marks in Settings (static/js/guides.js).

Browser code shared by the desktop and the phone, so its cases live in
tests/js/guides.js and run under node, like the name matcher.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent / "js" / "guides.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_guides_are_whole_and_found_by_how_people_ask():
    run = subprocess.run(
        ["node", str(SCRIPT)], capture_output=True, text=True, timeout=60, check=False
    )
    assert run.returncode == 0, run.stdout + run.stderr
