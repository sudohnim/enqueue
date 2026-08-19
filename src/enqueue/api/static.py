"""Static pages and the health endpoint: the shell, the capture overlay, and fonts.

These are the routes the desktop shell and the browser hit before any API call.
`/` and `/capture` are the two windows; `/health` is what the shell polls while
the engine boots.
"""

from __future__ import annotations

import os
import re

# nosemgrep: python.lang.compatibility.python37.python37-compatibility-importlib2
from importlib import resources

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response

from .. import db

router = APIRouter()


font_dir = resources.files("enqueue").joinpath("static/fonts")
static_dir = resources.files("enqueue").joinpath("static")


@router.get("/fonts/{name:path}")
async def serve_font(name: str) -> Response:
    font_path = os.path.join(str(font_dir), name)
    if not os.path.isfile(font_path):
        raise HTTPException(status_code=404, detail="font not found") from None
    return FileResponse(font_path, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.get("/static/{name:path}")
async def serve_static(name: str) -> Response:
    # The one static asset the pages reference by path (eyeball.png, N.14). The
    # guard keeps the route honest: only real files inside the static dir, never
    # a ".." escape or a directory listing.
    target = os.path.realpath(os.path.join(str(static_dir), name))
    if not os.path.isfile(target) or not target.startswith(str(static_dir) + os.sep):
        raise HTTPException(status_code=404, detail="no such static file") from None
    # no-cache, not no-store: the WebView still gets a 304 when nothing changed
    # (FileResponse sends ETag/Last-Modified), but it must revalidate every time,
    # so an edited css/js/png is never served stale from the desktop cache. This is
    # what made a new icons.js + eye-only.png load while the old pill.css lingered.
    return FileResponse(target, headers={"Cache-Control": "no-cache"})


_ASSET_REF = re.compile(r'(?P<attr>href|src)="(?P<path>/static/[^"?]+\.(?:css|js))"')


def _bust(html: str) -> str:
    """Append `?v=<file mtime>` to every /static css/js reference in the page.

    The desktop WebView caches assets heuristically and will not even re-request an
    unversioned `/static/css/pill.css` after an edit, so a `no-cache` header on the
    asset route never gets a chance to apply. Making the URL change when the file
    changes is the only thing the cache cannot defeat: a new mtime is a new URL, a
    guaranteed miss. Only the referenced file's URL changes, so unchanged assets
    still hit the cache.
    """

    def repl(m: re.Match[str]) -> str:
        path = m.group("path")
        fp = os.path.join(str(static_dir), path[len("/static/") :])
        try:
            version = int(os.path.getmtime(fp))
        except OSError:
            return m.group(0)
        return f'{m.group("attr")}="{path}?v={version}"'

    return _ASSET_REF.sub(repl, html)


_NO_CACHE = {"Cache-Control": "no-cache"}


@router.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    html = resources.files("enqueue").joinpath("static/home.html").read_text(encoding="utf-8")
    return HTMLResponse(_bust(html), headers=_NO_CACHE)


@router.get("/capture", response_class=HTMLResponse)
def capture_window() -> HTMLResponse:
    html = resources.files("enqueue").joinpath("static/capture.html").read_text(encoding="utf-8")
    return HTMLResponse(_bust(html), headers=_NO_CACHE)


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "artifacts": db.count("artifacts"),
        "versions": db.count("artifact_versions"),
        "chunks": db.count("chunks"),
        "facets": db.count("facets"),
        "chats": db.count("chats"),
    }
