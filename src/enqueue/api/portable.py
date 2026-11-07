"""Bringing notes in from other apps (importer.py) and taking the library out (export.py)."""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import export, importer

router = APIRouter()


class _Path(BaseModel):
    path: str


@router.get("/import")
def import_status() -> dict:
    return importer.state()


@router.post("/import", status_code=202)
def import_start(body: _Path) -> dict:
    """Import a folder or a zip on a background thread; GET /import shows it land."""
    try:
        return importer.start(body.path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


_export: dict = {"state": "idle"}
_export_lock = threading.Lock()


@router.get("/export")
def export_status() -> dict:
    with _export_lock:
        return dict(_export)


@router.post("/export", status_code=202)
def export_start(body: _Path) -> dict:
    """Write the library as plain files into `path` (export.py) on a background thread;
    GET /export shows it land. Running it again updates only what changed."""
    target = Path(body.path).expanduser()
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"{target} is not a folder")
    with _export_lock:
        if _export.get("state") == "running":
            raise HTTPException(status_code=409, detail="an export is already running")
        _export.clear()
        _export.update(state="running", path=str(target / "Enqueue"))

    def run() -> None:
        try:
            done = export.export(target / "Enqueue")
            with _export_lock:
                _export.update(state="done", items=done["artifacts"])
        except Exception as exc:  # noqa: BLE001 - the page shows why
            with _export_lock:
                _export.update(state="failed", error=str(exc)[:300])

    threading.Thread(target=run, name="export", daemon=True).start()
    return export_status()


@router.get("/extension")
def extension_status() -> dict:
    """Whether a browser extension connect code exists (never the code itself)."""
    from .. import extension

    return {"connected": extension.code() is not None}


@router.post("/extension/code")
def extension_code() -> dict:
    """A new connect code, to show once. A POST, so only the engine's own page gets it."""
    from .. import extension

    return {"code": extension.new_code()}


@router.post("/extension/check")
def extension_check() -> dict:
    """The extension's test of its code: the guard already checked it to get here."""
    return {"ok": True}
