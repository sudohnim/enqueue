"""Backups into a cloud drive's folder (backup.py): status, and back up now."""

from __future__ import annotations

from fastapi import APIRouter

from .. import backup

router = APIRouter()


@router.get("/backup")
def backup_status() -> dict:
    return backup.status()


@router.post("/backup", status_code=202)
def backup_now() -> dict:
    """Start a backup on a background thread; GET /backup shows it land."""
    if backup.configured_dir() is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail="choose a backup folder in Settings first")
    backup.run_soon("manual", force=True)
    return {"started": True}
