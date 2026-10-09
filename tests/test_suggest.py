"""The name matcher behind the search candidates (static/js/suggest.js).

It is browser code shared by the desktop and the phone, so its cases live in
tests/js/suggest.js and run under node, like the markdown round trip.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent / "js" / "suggest.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_typed_names_find_their_artifacts():
    run = subprocess.run(
        ["node", str(SCRIPT)], capture_output=True, text=True, timeout=60, check=False
    )
    assert run.returncode == 0, run.stdout + run.stderr
