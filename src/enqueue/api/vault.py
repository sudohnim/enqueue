"""Vault + Events HTTP surface (VAULT.5 / VAULT.6, desktop).

The desktop UI drives the vault through here: set up / unlock / lock the vault,
vault or un-vault an artifact, and read the vaulted set (decrypted only while
unlocked). `/events` backs the decoy Events tab. Wrong-PIN attempts are rate
limited with an escalating delay so on-device guessing is slow without ever hard
locking out the real owner (who has no recovery path by design).
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from .. import events, vault, vaultops

router = APIRouter()

# Escalating backoff on wrong PIN: after a few misses each further attempt waits
# longer, capped. In-memory, per-process; a restart clears it. Never a hard
# lockout - the owner has no recovery, so permanent lockout would be data loss.
_fail_count = 0
_next_allowed = 0.0
_BACKOFF = [0, 0, 0, 1, 2, 5, 10, 20, 30]


class PinBody(BaseModel):
    pin: str


class ChangePinBody(BaseModel):
    old: str
    new: str


@router.get("/events")
def get_events(limit: int = 100) -> dict:
    return {"events": events.recent(limit)}


@router.get("/vault/status")
def vault_status() -> dict:
    wait = max(0.0, _next_allowed - time.monotonic())
    return {"setup": vault.is_setup(), "unlocked": vault.is_unlocked(), "retry_in": round(wait, 1)}


@router.post("/vault/setup")
def vault_setup(body: PinBody) -> dict:
    try:
        vault.setup(body.pin)
    except vault.VaultError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    # Sync the wrap so other devices unlock with the same PIN (VAULT.2b).
    try:
        from ..sync.client import push_vault_meta

        push_vault_meta()
    except Exception:  # noqa: BLE001 - a vault works locally without the sync
        pass
    return {"setup": True, "unlocked": True}


@router.post("/vault/unlock")
def vault_unlock(body: PinBody) -> dict:
    global _fail_count, _next_allowed
    now = time.monotonic()
    if now < _next_allowed:
        raise HTTPException(status_code=429, detail="try again shortly")
    try:
        vault.unlock(body.pin)
    except vault.VaultError:
        _fail_count += 1
        delay = _BACKOFF[min(_fail_count, len(_BACKOFF) - 1)]
        _next_allowed = now + delay
        # Deliberately vague: never reveal whether a vault even exists.
        raise HTTPException(status_code=403, detail="incorrect") from None
    _fail_count = 0
    _next_allowed = 0.0
    return {"unlocked": True}


@router.post("/vault/lock")
def vault_lock() -> dict:
    vault.lock()
    return {"unlocked": False}


@router.post("/vault/change-pin")
def vault_change_pin(body: ChangePinBody) -> dict:
    # Only reachable from the unlocked vault UI; still re-checks the old PIN.
    if not vault.is_unlocked():
        raise HTTPException(status_code=409, detail="vault is locked")
    try:
        vault.change_pin(body.old, body.new)
    except vault.VaultError as e:
        raise HTTPException(status_code=403, detail=str(e)) from None
    try:
        from ..sync.client import push_vault_meta

        push_vault_meta()
    except Exception:  # noqa: BLE001
        pass
    return {"changed": True}


def _require_unlocked() -> None:
    if not vault.is_unlocked():
        raise HTTPException(status_code=409, detail="vault is locked")


@router.get("/vault")
def vault_listing() -> dict:
    _require_unlocked()
    return vaultops.listing()


@router.get("/vault/{artifact_id}")
def vault_get(artifact_id: str) -> dict:
    _require_unlocked()
    try:
        return vaultops.get(artifact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="not in the vault") from None


@router.get("/vault/{artifact_id}/blob")
def vault_blob(artifact_id: str):
    _require_unlocked()
    found = vaultops.blob_bytes(artifact_id)
    if found is None:
        raise HTTPException(status_code=404, detail="no blob") from None
    data, mime, filename = found
    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/artifacts/{artifact_id}/vault")
def do_vault(artifact_id: str) -> dict:
    _require_unlocked()
    try:
        return vaultops.vault_artifact(artifact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such artifact") from None


@router.post("/artifacts/{artifact_id}/unvault")
def do_unvault(artifact_id: str) -> dict:
    _require_unlocked()
    try:
        return vaultops.unvault_artifact(artifact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such artifact") from None
