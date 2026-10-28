"""Settings: the three-layer config, the Keychain API key, greeting, secrets.

Reads and writes the engine's configuration, stores the provider key in the
macOS Keychain (never in settings.json), serves the wall greeting, and reports
credential-scan hits.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import threading

from .. import config, db, greeting, keyring, keyring_file, preview, settings
from ..providers import pause
from ..sync.enable import enable

router = APIRouter()


@router.get("/settings")
def read_settings() -> dict:
    return {
        "settings": settings.all_settings(),
        "storage": settings.storage(),
        "backends": settings.backends(),
        "sync": settings.sync_state(),
        # What this copy of Enqueue can do: the Mac app ships without the preview
        # browser, so its setting is not offered there.
        "features": {"preview_browser": preview.browser_available()},
    }


@router.get("/settings/models")
def service_models(backend: str) -> dict:
    """The models an online service serves, for the pickers: `chat` answer in text,
    `vision` (when known) also read pictures. Fetched now when none is kept; empty
    when the service has no list or cannot be reached (then anything may be typed)."""
    from .. import catalog

    listing = catalog.get(backend) or {}
    chat, vision = catalog.suggest(backend, listing)
    return {
        "backend": backend,
        "chat": listing.get("chat", []),
        "vision": listing.get("vision"),
        "known": bool(listing),
        "suggested": chat,
        "suggested_vision": vision,
    }


@router.get("/settings/local")
def local_status() -> dict:
    """Ollama on this Mac: installed, running, its models, what to download."""
    from .. import local_model

    return local_model.status()


@router.post("/settings/local/start")
def local_start() -> dict:
    from .. import local_model

    if not local_model.start():
        raise HTTPException(status_code=409, detail="Ollama is not installed on this Mac.")
    return {"started": True}


class LocalPull(BaseModel):
    model: str


@router.post("/settings/local/pull")
def local_pull(req: LocalPull) -> dict:
    from .. import local_model

    try:
        local_model.pull(req.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return local_model.status()


@router.delete("/settings/local/pull")
def local_pull_cancel() -> dict:
    from .. import local_model

    local_model.cancel()
    return local_model.status()


class KeyringInit(BaseModel):
    force: bool = False


class SyncJoin(BaseModel):
    relay_url: str
    secret: str
    recovery_phrase: str


class PairClaim(BaseModel):
    relay_url: str
    pairing_id: str
    phrase: str


class SettingsUpdate(BaseModel):
    changes: dict


class ApiKey(BaseModel):
    key: str
    backend: str | None = None  # a service picked but not saved yet; else the chosen one


@router.put("/settings/api-key")
def store_api_key(req: ApiKey) -> dict:
    """Put the key in the macOS Keychain. It is never written to settings.json.

    The body is not logged and the value is never returned: what comes back is only
    whether a key now exists and its last four characters.
    """

    try:
        if req.backend is not None and req.backend not in config.BACKENDS:
            raise ValueError(f"no service named {req.backend!r}")
        keyring.set(req.key, req.backend)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    # The key is part of the config the phone needs to run chat; propagate it
    # (E2E-encrypted) the same way a settings change is propagated.
    settings._resync_to_relay()
    # A usage limit belonged to the old key: stop waiting it out.
    pause.lift("new API key")
    return settings.api_key_state(req.backend)


@router.delete("/settings/api-key")
def forget_api_key(backend: str | None = None) -> dict:
    if backend is not None and backend not in config.BACKENDS:
        raise HTTPException(status_code=400, detail=f"no service named {backend!r}")
    keyring.clear(backend)
    settings._resync_to_relay()
    pause.lift("API key removed")
    return settings.api_key_state(backend)


class SyncSecret(BaseModel):
    secret: str
    # The relay the secret is for, when the page knows it (sync setup): checked first.
    relay_url: str | None = None


def _relay_refuses(url: str, secret: str) -> bool:
    """Whether the relay at `url` answers that it does not know this secret.

    A relay that serves several libraries (relay/storage.py) only opens the ones it
    issued, so a made-up secret would be stored here and every sync would then fail
    in the background. Unreachable is not a refusal: setup may happen offline.
    """
    import httpx

    try:
        resp = httpx.get(
            f"{url.rstrip('/')}/sync/objects",
            params={"since": 2**62},
            headers={"Authorization": f"Bearer {secret}"},
            timeout=10,
        )
    except httpx.HTTPError:
        return False
    return resp.status_code == 401


@router.put("/settings/sync-secret")
def store_sync_secret(req: SyncSecret) -> dict:
    """Put the per-library sync secret in the macOS Keychain (SYNC.3).

    Like the API key: never written to settings.json, and the value is never
    returned - only whether one now exists and its hint.
    """
    if req.relay_url and _relay_refuses(req.relay_url, req.secret):
        raise HTTPException(
            status_code=400,
            detail="That relay doesn't know this password. Use the one its owner gave you"
            " (a shared relay only opens libraries it set up).",
        )
    try:
        enable(req.secret)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return settings.sync_state()


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


@router.post("/settings/sync/join")
def sync_join(req: SyncJoin) -> dict:
    """Join an existing library on a NEW device using its recovery phrase (multi-device).

    The setup walk mints a fresh keyring (a new DEK), which is right for a first device
    but wrong for a second one - a new DEK cannot read the first device's data. This
    joins instead: point at the same relay, authenticate with the same secret, pull the
    library's encrypted keyring, and import the shared DEK with the recovery phrase.
    After it succeeds the sync worker pulls the existing library down.

    Refused when this device already has its own keyring - joining would orphan that
    DEK and everything sealed under it. Reset sync first to replace deliberately.
    """
    from ..sync.client import pull, pull_keyring

    if keyring_file.is_initialized():
        raise HTTPException(
            status_code=409,
            detail=(
                "This device already has a sync keyring. Joining another library would "
                "orphan it and everything encrypted under its key. Reset sync on this "
                "device first if you mean to replace it."
            ),
        )
    relay = (req.relay_url or "").strip()
    if not relay:
        raise HTTPException(status_code=400, detail="A relay URL is required to join a library.")

    # Relay + secret first: pulling the keyring is an authenticated GET against them.
    settings.update({"sync_relay_url": relay})
    try:
        keyring.sync_secret_set(req.secret)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None

    if not pull_keyring():
        raise HTTPException(
            status_code=404,
            detail=(
                "Could not fetch the library keyring from the relay. Check the relay URL "
                "and secret, and that the other device has finished setting up sync."
            ),
        )
    try:
        keyring_file.unlock_with_recovery(req.recovery_phrase)
    except keyring_file.UnlockError as exc:
        # Leave the pulled keyring in place so a retry with the correct phrase works.
        raise HTTPException(
            status_code=403,
            detail=(
                "That recovery phrase did not unlock the library keyring. Check it and "
                "try again."
            ),
        ) from exc

    # A joined device already has the whole library upstream, so there is nothing to
    # back-fill from here - mark it done and pull the existing data down instead.
    settings.update({"sync_backfill_done": True})

    # Sync was configured just now, after boot, so the boot-time worker start no-op'd.
    # Start it here or the joined device would not auto-sync until an app restart.
    from ..sync.worker import start as start_sync_worker

    start_sync_worker()

    def _bg():
        result = pull()
        print(f"[sync] join pull applied {result.get('pulled', 0)} snapshots", flush=True)

    threading.Thread(target=_bg, daemon=True).start()
    return settings.sync_state()


@router.post("/settings/sync/pair/offer")
def sync_pair_offer() -> dict:
    """MAIN device: stage a one-time pairing on the relay and return the id + phrase to
    show the user. Requires sync fully set up here (PAIR.1)."""
    from ..sync import pairing

    try:
        return pairing.create_offer()
    except pairing.PairingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/settings/sync/pair/claim")
def sync_pair_claim(req: PairClaim) -> dict:
    """NEW device: claim a pairing offer with the relay URL, pairing id, and phrase, then
    import the key and pull the library (PAIR.1). Refused if this device already has a
    keyring."""
    from ..sync import pairing

    try:
        return pairing.claim_offer(req.relay_url, req.pairing_id, req.phrase)
    except pairing.PairingError as exc:
        # 409 for the "already initialized" refusal, 400 for everything else the user can fix.
        code = 409 if "already has a sync keyring" in str(exc) else 400
        raise HTTPException(status_code=code, detail=str(exc)) from None


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
