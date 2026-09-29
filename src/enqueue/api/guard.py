"""Only this machine's own pages may talk to the engine.

Binding to 127.0.0.1 keeps other machines out, but not other websites: a page the
person has open can send requests to 127.0.0.1:8787 itself, and with DNS rebinding
(its own hostname re-resolved to 127.0.0.1) it can also read the answers. That page
could then read the whole library, or point the model backend at its own server so
every later ingest sends it the person's notes.

Two checks close that:

- **Host**: a rebinding page's requests carry its own hostname. Only a loopback name
  (`127.0.0.1`, `localhost`, `::1`) is served; anything else gets 421.
- **Origin**: a page on another site can still send a form or `fetch` without reading
  the reply. A request that changes something must come from one of the engine's own
  origins (`config.ALLOWED_ORIGINS`, port included, so another local server is refused
  too), or carry no Origin at all (the CLI, the desktop shell's health check, curl);
  a foreign one gets 403.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .. import config

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _hostname(value: str) -> str:
    """The host name in a Host header or an origin, without port or IPv6 brackets."""
    netloc = value if "//" in value else "//" + value
    try:
        return (urlsplit(netloc).hostname or "").lower()
    except ValueError:
        return ""


class LocalOnlyGuard:
    """ASGI middleware enforcing the Host and Origin rules above."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        allowed = config.ALLOWED_HOSTS  # read per request, so tests can extend them
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}

        if _hostname(headers.get("host", "")) not in allowed:
            await PlainTextResponse("Unknown host.", status_code=421)(scope, receive, send)
            return

        origin = headers.get("origin")
        if (
            scope["method"] not in SAFE_METHODS
            and origin is not None
            and origin.rstrip("/").lower() not in config.ALLOWED_ORIGINS
        ):
            await PlainTextResponse("Cross-site request refused.", status_code=403)(
                scope, receive, send
            )
            return

        await self.app(scope, receive, send)
