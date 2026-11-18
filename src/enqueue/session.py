"""The engine's session token: made at start, kept in DATA_DIR/session (0600).

The shell, the CLI and the scripts read the file and send the token. A process
that cannot read the data folder cannot call the engine.
"""

from __future__ import annotations

import hmac
import os
import secrets

from . import config

_token = ""


def path():
    return config.DATA_DIR / "session"


def start() -> str:
    """Make this run's token and write it for the engine's own clients."""
    global _token
    _token = secrets.token_urlsafe(32)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(path(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(_token)
    return _token


def read() -> str:
    """The token a client sends: the running engine's, read from its file."""
    try:
        return path().read_text().strip()
    except OSError:
        return ""


def ok(presented: str | None) -> bool:
    return bool(presented and _token) and hmac.compare_digest(presented.encode(), _token.encode())
