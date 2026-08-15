"""Settings: the three-layer config, the Keychain API key, greeting, secrets.

Reads and writes the engine's configuration, stores the provider key in the
macOS Keychain (never in settings.json), serves the wall greeting, and reports
credential-scan hits.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, greeting, keyring, settings
from ..sync.client import push_keyring

router = APIRouter()


@router.get("/settings")
def read_settings() -> dict:
    return {
        "settings": settings.all_settings(),
        "storage": settings.storage(),
        "backends": settings.backends(),
        "sync": settings.sync_state(),
    }


class SettingsUpdate(BaseModel):
    changes: dict


class ApiKey(BaseModel):
    key: str


@router.put("/settings/api-key")
def store_api_key(req: ApiKey) -> dict:
    """Put the key in the macOS Keychain. It is never written to settings.json.

    The body is not logged and the value is never returned: what comes back is only
    whether a key now exists and its last four characters.
    """

    try:
        keyring.set(req.key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return settings.api_key_state()


@router.delete("/settings/api-key")
def forget_api_key() -> dict:

    keyring.clear()
    return settings.api_key_state()


class SyncSecret(BaseModel):
    secret: str


@router.put("/settings/sync-secret")
def store_sync_secret(req: SyncSecret) -> dict:
    """Put the per-library sync secret in the macOS Keychain (SYNC.3).

    Like the API key: never written to settings.json, and the value is never
    returned - only whether one now exists and its hint.
    """
    try:
        keyring.sync_secret_set(req.secret)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    # After sync secret is configured, push the encrypted keyring to the relay
    # so mobile devices can pull it during pairing (MOB2.10).
    push_keyring()
    return settings.sync_state()


@router.delete("/settings/sync-secret")
def forget_sync_secret() -> dict:
    keyring.sync_secret_clear()
    return settings.sync_state()


@router.patch("/settings")
def write_settings(req: SettingsUpdate) -> dict:
    try:
        return {"settings": settings.update(req.changes), "storage": settings.storage()}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.get("/greeting")
def get_greeting() -> dict:
    """The wall's greeting for the current four-hour bucket, cached or fallback.

    Never blocks on the model: a missing phrase returns the time-based fallback
    and starts a background generation for the bucket.
    """
    return greeting.get()


@router.get("/secrets")
def secret_report() -> dict:
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT a.id, a.title, s.kind, s.line, s.excerpt FROM secret_hits s"
            " JOIN artifacts a ON a.id = s.artifact_id ORDER BY a.title"
        ).fetchall()
        return {"count": len(rows), "hits": [dict(r) for r in rows]}
    finally:
        conn.close()
