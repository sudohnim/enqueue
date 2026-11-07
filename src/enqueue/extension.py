"""The browser extension's connect code: what lets it save into the library.

A browser extension's requests carry its own origin (chrome-extension://...), which the
origin guard refuses. With the connect code in `X-Enqueue-Key` it may reach the capture
routes and nothing else. No website can send that origin, and the code is shown only in
Settings on this Mac. Kept in the Keychain; a new code ends the old one.
"""

from __future__ import annotations

import hmac
import re
import secrets

from . import keyring

SERVICE = "enqueue-extension-key"
ORIGINS = ("chrome-extension://", "moz-extension://", "safari-web-extension://")
# What an extension may do: save a page, a link, words, a picture, and a note about it.
ROUTES = re.compile(
    r"^/(extension/check|capture/link|capture/upload|notes"
    r"|artifacts/[0-9a-f-]{36}/(annotations|tags))$"
)


def code() -> str | None:
    return keyring._get(SERVICE)


def new_code() -> str:
    value = "enq-" + secrets.token_urlsafe(18)
    keyring._set(SERVICE, value, noun="code")
    return value


def allows(origin: str, path: str, presented: str | None) -> bool:
    """Whether an extension's state-changing request may pass the origin guard."""
    if not origin.lower().startswith(ORIGINS) or not presented or not ROUTES.match(path):
        return False
    expected = code()
    return bool(expected) and hmac.compare_digest(presented.encode(), expected.encode())
