"""The markdown renderer and the editor's serializer must round-trip a note unchanged.

md.js is browser code, so the cases live in tests/js/md_roundtrip.js and run under node
(with a minimal DOM for md()'s output). A mismatch there is a note that changes shape
when it is opened and saved: an empty bullet splitting a list, blank lines appearing
between lines typed on the phone, a numbered list restarting at 1.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent / "js" / "md_roundtrip.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_markdown_round_trips_unchanged():
    run = subprocess.run(
        ["node", str(SCRIPT)], capture_output=True, text=True, timeout=60, check=False
    )
    assert run.returncode == 0, run.stdout + run.stderr
