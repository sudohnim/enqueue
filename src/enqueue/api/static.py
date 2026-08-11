"""Static pages and the health endpoint: the shell, the capture overlay, and fonts.

These are the routes the desktop shell and the browser hit before any API call.
`/` and `/capture` are the two windows; `/health` is what the shell polls while
the engine boots.
"""

from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, Response

# nosemgrep: python.lang.compatibility.python37.python37-compatibility-importlib2
from importlib import resources

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
    return FileResponse(target)


@router.get("/", response_class=HTMLResponse)
def home() -> str:
    return resources.files("enqueue").joinpath("static/home.html").read_text(encoding="utf-8")


@router.get("/capture", response_class=HTMLResponse)
def capture_window() -> str:
    return resources.files("enqueue").joinpath("static/capture.html").read_text(encoding="utf-8")


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
