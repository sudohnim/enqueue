"""Settings: the three-layer config, the Keychain API key, greeting, secrets.

Reads and writes the engine's configuration, stores the provider key in the
macOS Keychain (never in settings.json), serves the wall greeting, and reports
credential-scan hits.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import threading

from .. import db, greeting, keyring, keyring_file, settings
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


class KeyringInit(BaseModel):
    force: bool = False


class KeyringUnlock(BaseModel):
    recovery_phrase: str


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
    # BACKFILL.2: Auto-backfill on first sync-enable (guarded by one-shot flag).
    # Only runs when DEK is loaded (keyring unlocked) and backfill hasn't run yet.
    if keyring_file.load_dek_from_keychain() is not None:
        if not settings.get("sync_backfill_done"):
            def _bg():
                from ..sync.client import push_all
                count = push_all()
                print(f"[sync] auto-backfill pushed {count} artifacts", flush=True)
            threading.Thread(target=_bg, daemon=True).start()
            settings.update({"sync_backfill_done": True})
    return settings.sync_state()


@router.post("/settings/sync/push-all")
def sync_push_all() -> dict:
    """BACKFILL.1: Push all non-deleted, non-local artifacts to the relay.

    Iterates every artifact in the local DB, pushes its snapshot (and blob if any)
    to the relay. Idempotent: relay returns 409 for already-present objects.
    Returns the number of artifacts successfully pushed (201 responses).

    Runs in a background thread so the request returns immediately. The sync
    worker's lifecycle events (sync-started/sync-done/sync-error) track progress.
    """
    from ..sync.client import push_all

    def _bg():
        count = push_all()
        print(f"[sync] backfill pushed {count} artifacts", flush=True)

    threading.Thread(target=_bg, daemon=True).start()
    return {"started": True, "message": "full-library push started in background"}


@router.delete("/settings/sync-secret")
def forget_sync_secret() -> dict:
    keyring.sync_secret_clear()
    return settings.sync_state()


@router.post("/settings/keyring-init")
def keyring_init(req: KeyringInit) -> dict:
    # A legacy (pre-QR.1 two-slot) keyring cannot be carried forward: the new
    # format drops the password slot, so such a file is re-initialized in place
    # with a fresh DEK and recovery phrase (the UI confirms this first). A
    # current-format keyring still refuses re-init unless force=true.
    if keyring_file.is_initialized() and not req.force and not keyring_file.is_legacy():
        raise HTTPException(
            status_code=409,
            detail=(
                "A keyring already exists. Re-initializing would orphan the "
                "current DEK and all synced data. If you are certain, pass "
                "`force=true`, but understand this is irreversible."
            ),
        )
    phrase = keyring_file.initialize()
    return {
        "recovery_phrase": phrase,
        "message": (
            "Write this down. It is the only way to recover your library if "
            "you lose access to this device. It will never be shown again."
        ),
    }


@router.post("/settings/keyring-unlock")
def keyring_unlock(req: KeyringUnlock) -> dict:
    """Unlock the sync keyring in memory with the recovery phrase.

    The recovery phrase is never logged or written to disk. On success the sync
    worker resumes pushing/pulling; on a wrong phrase it is refused with a
    human error and the keyring stays locked. If there is no keyring to unlock,
    the request is refused with a pointer to initialize one.
    """
    if not keyring_file.is_initialized():
        raise HTTPException(
            status_code=409,
            detail=(
                "There is no sync keyring to unlock. Initialize sync on the " "Sync tab first."
            ),
        )
    try:
        keyring_file.unlock_with_recovery(req.recovery_phrase)
    except keyring_file.UnlockError as exc:
        raise HTTPException(
            status_code=403,
            detail=(
                "That recovery phrase did not unlock the sync keyring. Please "
                "check it and try again - the keyring stays locked."
            ),
        ) from exc
    return {"ok": True, "message": "sync keyring unlocked"}


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
