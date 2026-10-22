"""Enqueue sync: signing this Mac in to the hosted relay with Google or Apple.

The other way to sync is a relay of your own and its password (Settings > Phone). With
Enqueue sync there is no password to paste: the person signs in, the relay gives this
Mac a device token of its own (relay/accounts.py), and that token is what the sync
client sends where it would send a relay's password. Each phone or computer linked
later gets a token of its own the same way, so any one of them can be cancelled.

Signing in opens nothing. The library is encrypted under a key that reaches a new
device only from this Mac's QR code or the recovery kit; the relay, and whoever runs
it, holds an account, device tokens and ciphertext.

The sign-in runs in the person's own browser, which comes back to this engine:
- Google: the "Desktop app" flow with PKCE, back to `/account/google/callback` on this
  engine; the one-time code goes to the relay, which holds the client secret.
- Apple: the web flow (the Services ID), which posts to the relay. The relay sends the
  browser back to `/account/apple/done` here with a one-time code, never the session.
Both come back with the `state` this module made, so a page that sends the browser to
those addresses on its own finishes nothing.

What is kept: the relay's refresh token in the Keychain (`enqueue-account-session`),
the device token as the sync secret (`enqueue-sync-secret`), and who is signed in
(email, provider, name, this Mac's device id) in settings.json.

A Mac already syncing through a relay of its own can switch: the same sign-in, then the
library, under the same key, is pushed whole into the account's library, the pull
starts from the beginning there, and the phone is asked to scan a new code (until it
does, it keeps the old relay and its old copy). The old library stays on the old relay
until whoever runs it removes it (`enq relay-admin revoke`).
"""

from __future__ import annotations

import base64
import hashlib
import json
import platform
import secrets
import subprocess
import threading
import time
from urllib.parse import urlencode

import httpx

from . import config, keyring, keyring_file, settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
APPLE_AUTH_URL = "https://appleid.apple.com/auth/authorize"
PENDING_TTL_S = 10 * 60

_lock = threading.Lock()
# state -> what is needed to finish that sign-in. One at a time is all a person does,
# but an abandoned tab must not block a second try, so these simply expire.
_pending: dict[str, dict] = {}
# How the last sign-in went, for the page waiting on it: idle, waiting, done, failed.
_progress: dict = {"state": "idle", "error": None}
_access: dict = {"token": None, "until": 0.0}


class AccountError(Exception):
    """A sign-in or account action that did not work, said for the person."""


def _client() -> httpx.Client:
    return httpx.Client(base_url=config.HOSTED_RELAY_URL, timeout=20)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _device_name() -> str:
    """The name the person gave this Mac (System Settings > General > About), the one
    they will recognise under Devices. The host name is the network's idea of it
    ("macbookair.lan"), and only the fallback."""
    try:
        done = subprocess.run(
            ["/usr/sbin/scutil", "--get", "ComputerName"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        name = done.stdout.strip() if done.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        name = ""
    if not name:
        name = platform.node().split(".")[0].replace("-", " ").strip()
    return (name or "Mac")[:100]


def _detail(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("detail") or resp.status_code)
    except ValueError:
        return str(resp.status_code)


# ---- signing in --------------------------------------------------------------------


def begin(provider: str, refresh: bool = False) -> str:
    """The address to open in the browser to sign in with `provider`.

    `refresh` is the same sign-in for a Mac already signed in, to bring the account's
    name and picture up to date (they only come inside the provider's sign-in token):
    the session is renewed, and the device, its token and sync stay as they are."""
    if provider not in ("google", "apple"):
        raise AccountError("Sign in with Google or Apple.")
    # No key yet is fine: signing in decides whether this Mac joins the account's library
    # (approved from a device that holds the key) or makes its first key (_adopt).
    if keyring_file.is_initialized() and keyring_file.load_dek_from_keychain() is None:
        raise AccountError("This Mac's library key is locked. Unlock sync first, then sign in.")
    if refresh:
        if not signed_in() or provider != settings.get("account_provider"):
            raise AccountError("Sign in first.")
    elif signed_in():
        raise AccountError("This Mac is already signed in to Enqueue sync.")
    state = secrets.token_urlsafe(24)
    entry = {"provider": provider, "at": time.time(), "refresh": refresh}
    if provider == "google":
        verifier = secrets.token_urlsafe(64)
        entry["verifier"] = verifier
        entry["redirect_uri"] = f"{config.API_URL}/account/google/callback"
        url = (
            GOOGLE_AUTH_URL
            + "?"
            + urlencode(
                {
                    "client_id": config.GOOGLE_DESKTOP_CLIENT_ID,
                    "redirect_uri": entry["redirect_uri"],
                    "response_type": "code",
                    "scope": "openid email profile",
                    "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()),
                    "code_challenge_method": "S256",
                    "state": state,
                    "prompt": "select_account",
                }
            )
        )
    else:
        handback = {"r": f"{config.API_URL}/account/apple/done", "n": state}
        url = (
            APPLE_AUTH_URL
            + "?"
            + urlencode(
                {
                    "client_id": config.APPLE_SERVICES_ID,
                    "redirect_uri": f"{config.HOSTED_RELAY_URL}/auth/apple/callback",
                    "response_type": "code id_token",
                    "response_mode": "form_post",
                    "scope": "name email",
                    "state": _b64url(json.dumps(handback).encode()),
                }
            )
        )
    with _lock:
        now = time.time()
        for key in [k for k, v in _pending.items() if now - v["at"] > PENDING_TTL_S]:
            del _pending[key]
        _pending[state] = entry
        _progress.update(state="waiting", error=None)
    return url


def _take(state: str | None, provider: str) -> dict:
    with _lock:
        entry = _pending.pop(state or "", None)
    if entry is None or entry["provider"] != provider or time.time() - entry["at"] > PENDING_TTL_S:
        raise AccountError("This sign-in was not started here, or took too long. Try again.")
    return entry


def _fail(message: str) -> None:
    with _lock:
        _progress.update(state="failed", error=message)


def finish_google(code: str | None, state: str | None, error: str | None = None) -> None:
    try:
        entry = _take(state, "google")
        if error or not code:
            raise AccountError("Sign-in was cancelled.")
        with _client() as http:
            resp = http.post(
                "/auth/google/desktop",
                json={
                    "code": code,
                    "code_verifier": entry["verifier"],
                    "redirect_uri": entry["redirect_uri"],
                },
            )
        if resp.status_code != 200:
            raise AccountError(f"Google sign-in failed ({_detail(resp)}).")
        _adopt(resp.json(), refresh=entry.get("refresh", False))
    except AccountError as exc:
        _fail(str(exc))
        raise
    except httpx.HTTPError as exc:
        _fail("Enqueue sync could not be reached. Check the connection and try again.")
        raise AccountError(str(exc)) from exc


def finish_apple(handoff: str | None, state: str | None, error: str | None = None) -> None:
    try:
        entry = _take(state, "apple")
        if error or not handoff:
            raise AccountError("Sign-in was cancelled.")
        with _client() as http:
            resp = http.post("/auth/handoff", json={"code": handoff})
        if resp.status_code != 200:
            raise AccountError(f"Apple sign-in failed ({_detail(resp)}).")
        _adopt(resp.json(), refresh=entry.get("refresh", False))
    except AccountError as exc:
        _fail(str(exc))
        raise
    except httpx.HTTPError as exc:
        _fail("Enqueue sync could not be reached. Check the connection and try again.")
        raise AccountError(str(exc)) from exc


def _adopt(pair: dict, refresh: bool = False) -> None:
    """Keep the session, get this Mac a device token, and start syncing with it."""
    from .sync.enable import enable

    if refresh:
        _refresh_profile(pair)
        return

    # Already syncing through a relay of its own: this sign-in moves the library.
    switching = bool((settings.get("sync_relay_url") or "").strip()) and not signed_in()
    keyring.session_set(pair["refresh_token"])
    _remember_access(pair["access_token"])
    who = pair.get("account") or {}
    _keep_picture(who.get("picture"))
    with _client() as http:
        resp = http.post(
            "/account/devices",
            json={"name": _device_name(), "kind": "computer"},
            headers=_bearer(pair["access_token"]),
        )
    if resp.status_code != 201:
        raise AccountError(f"Enqueue sync could not add this Mac ({_detail(resp)}).")
    device = resp.json()
    token = device["relay_token"]
    # What the account's library already is decides what this Mac does next: a library
    # with a key is joined (approved from a device that holds it), never given a second
    # key; a Mac with a key of its own may only join the library that key opens.
    from .sync import join

    try:
        theirs = join.relay_keyring(token, config.HOSTED_RELAY_URL)
    except join.JoinError as exc:
        _drop_device(device["device_id"], pair["access_token"])
        raise AccountError(str(exc)) from None
    mine = keyring_file.is_initialized()
    if mine and theirs is not None:
        local = (config.DATA_DIR / "keyring.json").read_bytes()
        if not join.same_library(local, theirs):
            _drop_device(device["device_id"], pair["access_token"])
            raise AccountError(
                "This account already has a library, and this Mac holds the key to a "
                "different one. To join the account's library, start sync over on this "
                "Mac (Settings, Sync, More options), then sign in again."
            )
    settings.update(
        {
            "account_id": who.get("id") or "",
            "account_email": who.get("email") or "",
            "account_name": who.get("display_name") or "",
            "account_provider": who.get("provider") or "",
            "account_device_id": device["device_id"],
        }
    )
    if not mine:
        # No key here: hold the pass, and either ask to join or make the first key.
        keyring.sync_secret_set(token)
        settings.update({"sync_relay_url": config.HOSTED_RELAY_URL})
        if theirs is not None:
            with _lock:
                _progress.update(state="join", error=None)
            try:
                join.start()
            except join.JoinError as exc:
                with _lock:
                    _progress.update(state="join", error=str(exc))
            return
        with _lock:
            _progress.update(state="needs_key", error=None)
        return
    if switching:
        _move_library(token)
    else:
        enable(token, config.HOSTED_RELAY_URL)
    with _lock:
        _progress.update(state="done", error=None)


def _drop_device(device_id: str, access: str) -> None:
    """Cancel a device a sign-in just made and could not use."""
    try:
        with _client() as http:
            http.delete(f"/account/devices/{device_id}", headers=_bearer(access))
    except httpx.HTTPError:
        pass


def finish_new_library() -> None:
    """After the first key is made on this Mac (the account had none): start syncing."""
    from .sync.enable import enable

    token = keyring.sync_secret_get()
    if not token or not signed_in():
        raise AccountError("Sign in to Enqueue sync first.")
    if not keyring_file.is_initialized():
        raise AccountError("Make the library's key first.")
    enable(token, config.HOSTED_RELAY_URL)
    with _lock:
        _progress.update(state="done", error=None)


def joined() -> None:
    """The approval landed (sync/join.py): sign-in is complete."""
    with _lock:
        if _progress.get("state") == "join":
            _progress.update(state="done", error=None)


def _refresh_profile(pair: dict) -> None:
    """A second sign-in on a signed-in Mac: new session, fresh name and picture, same
    device. It must be the same account: another one would leave this Mac's token
    opening one library while it showed someone else."""
    who = pair.get("account") or {}
    mine = settings.get("account_id")
    if (who.get("id") != mine) if mine else (who.get("email") != settings.get("account_email")):
        with _client() as http:
            http.post("/auth/logout", json={"refresh_token": pair["refresh_token"]})
        raise AccountError("That's a different account. Sign in with the one this Mac uses.")
    old = keyring.session_get()
    keyring.session_set(pair["refresh_token"])
    _remember_access(pair["access_token"])
    if old:
        try:
            with _client() as http:
                http.post("/auth/logout", json={"refresh_token": old})
        except httpx.HTTPError:
            pass
    settings.update(
        {"account_name": who.get("display_name") or "", "account_id": who.get("id") or ""}
    )
    _keep_picture(who.get("picture"))
    with _lock:
        _progress.update(state="done", error=None)


def _move_library(token: str) -> None:
    """Point this Mac at the account's library and push everything into it.

    The account's library is new and empty: the pull starts from its beginning, the
    whole library goes up once (artifacts, views, conversations, settings, the vault's
    wrap; the keyring goes up as the password is stored), and the phone is told to scan
    a new code. Nothing is removed from the old relay.
    """
    from .sync import client as sync_client
    from .sync import worker as sync_worker
    from .sync.enable import enable

    sync_client._cursor_path().unlink(missing_ok=True)
    # enable() would push the artifacts alone; the switch pushes everything, once.
    settings.update({"sync_backfill_done": True, "account_relink_phone": True})
    enable(token, config.HOSTED_RELAY_URL)
    sync_worker.restart()

    def _push() -> None:
        from . import events

        pushed = sync_client.push_everything()
        events.emit("sync.moved", f"moved to Enqueue sync: {pushed} items", {"pushed": pushed})

    threading.Thread(target=_push, name="enqueue-sync-move", daemon=True).start()


# ---- the picture ---------------------------------------------------------------

PICTURE_MAX_BYTES = 1024 * 1024
_PICTURE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def _picture_files() -> list:
    return [config.DATA_DIR / f"account-picture.{ext}" for ext in _PICTURE_TYPES.values()]


def picture_file():
    """This account's picture as kept on this Mac, or None (Apple sends none)."""
    return next((f for f in _picture_files() if f.exists()), None)


def _keep_picture(url: str | None) -> None:
    """Fetch the provider's picture once and keep it here, so the page shows it without
    asking Google for it every time. Best effort: a failure just leaves the initial."""
    if not url or not url.startswith("https://"):
        return
    try:
        resp = httpx.get(url, timeout=10, follow_redirects=True)
    except httpx.HTTPError:
        return
    kind = resp.headers.get("content-type", "").split(";")[0].strip()
    if (
        resp.status_code != 200
        or kind not in _PICTURE_TYPES
        or len(resp.content) > PICTURE_MAX_BYTES
    ):
        return
    for old in _picture_files():
        old.unlink(missing_ok=True)
    (config.DATA_DIR / f"account-picture.{_PICTURE_TYPES[kind]}").write_bytes(resp.content)


# ---- the session -------------------------------------------------------------------


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _remember_access(token: str) -> None:
    # 15 minutes on the relay; used for a little less so a request never carries one
    # that expires on the way.
    _access.update(token=token, until=time.time() + 12 * 60)


def _access_token() -> str:
    if _access["token"] and time.time() < _access["until"]:
        return _access["token"]
    refresh = keyring.session_get()
    if not refresh:
        raise AccountError("Not signed in to Enqueue sync.")
    with _client() as http:
        resp = http.post("/auth/refresh", json={"refresh_token": refresh})
    if resp.status_code != 200:
        raise AccountError("Your Enqueue sync sign-in has ended. Sign in again.")
    pair = resp.json()
    keyring.session_set(pair["refresh_token"])
    _remember_access(pair["access_token"])
    return pair["access_token"]


def signed_in() -> bool:
    return bool(settings.get("account_email") or settings.get("account_device_id"))


def state() -> dict:
    """Who is signed in and how the last sign-in went. Local only, no network."""
    with _lock:
        progress = dict(_progress)
    return {
        "signed_in": signed_in(),
        "email": settings.get("account_email") or "",
        "name": settings.get("account_name") or "",
        "provider": settings.get("account_provider") or "",
        "device_id": settings.get("account_device_id") or "",
        "relay_url": config.HOSTED_RELAY_URL,
        "sign_in": progress,
        # Switched from a relay of its own: the phone still has the old one until it
        # scans a new code (cleared when this Mac makes one).
        "relink_phone": bool(settings.get("account_relink_phone")),
        "picture": picture_file() is not None,
        # A Mac waiting for another device to approve it (sync/join.py).
        "join": _join_status(),
        "plan": {
            "tier": settings.get("account_tier") or "free",
            "pro_until": settings.get("account_pro_until") or None,
            "used_bytes": settings.get("account_used_bytes") or 0,
            "storage_bytes": settings.get("account_storage_bytes") or 0,
        },
    }


def _join_status() -> dict:
    from .sync import join

    return join.status()


# ---- devices -----------------------------------------------------------------------


def devices() -> list[dict]:
    """Every device linked to the account, this Mac marked."""
    with _client() as http:
        resp = http.get("/account", headers=_bearer(_access_token()))
    if resp.status_code != 200:
        raise AccountError(f"Enqueue sync did not answer ({_detail(resp)}).")
    me = resp.json()
    _keep_plan(me.get("plan"))
    if picture_file() is None and me.get("picture"):
        _keep_picture(me["picture"])
    mine = settings.get("account_device_id")
    _keep_my_name(me.get("devices", []), mine)
    return [
        {**d, "this_mac": d["id"] == mine} for d in me.get("devices", []) if not d.get("revoked_at")
    ]


def _keep_plan(plan: dict | None) -> None:
    """The account's plan as the relay last said, for Settings (no network to read)."""
    if not plan:
        return
    settings.update(
        {
            "account_tier": plan.get("tier") or "free",
            "account_pro_until": plan.get("pro_until") or 0,
            "account_used_bytes": int(plan.get("used_bytes") or 0),
            "account_storage_bytes": int((plan.get("limits") or {}).get("storage_bytes") or 0),
        }
    )


def _keep_my_name(listed: list[dict], mine: str | None) -> None:
    """This Mac goes by the name its owner gave it (it once registered the network's
    name, "macbookair.lan"): put it right whenever the list shows otherwise."""
    want = _device_name()
    for d in listed:
        if d["id"] == mine and d.get("name") != want:
            try:
                with _client() as http:
                    resp = http.patch(
                        f"/account/devices/{mine}",
                        json={"name": want},
                        headers=_bearer(_access_token()),
                    )
                if resp.status_code == 204:
                    d["name"] = want
            except httpx.HTTPError:
                pass


def new_device_token(name: str, kind: str = "phone") -> str:
    """A relay token for one more device (a phone being linked, a computer joining)."""
    with _client() as http:
        resp = http.post(
            "/account/devices",
            json={"name": name[:100], "kind": kind},
            headers=_bearer(_access_token()),
        )
    if resp.status_code != 201:
        raise AccountError(f"Enqueue sync could not add the device ({_detail(resp)}).")
    if name == "Phone" and settings.get("account_relink_phone"):
        settings.update({"account_relink_phone": False})
    return resp.json()["relay_token"]


def remove_device(device_id: str) -> None:
    if device_id == settings.get("account_device_id"):
        raise AccountError("To remove this Mac, sign out instead.")
    with _client() as http:
        resp = http.delete(f"/account/devices/{device_id}", headers=_bearer(_access_token()))
    if resp.status_code not in (204, 404):
        raise AccountError(f"Enqueue sync could not remove the device ({_detail(resp)}).")


# ---- leaving -----------------------------------------------------------------------


def _forget_here() -> None:
    """This Mac stops syncing through Enqueue sync. Its library stays as it is."""
    keyring.session_clear()
    keyring.sync_secret_clear()
    _access.update(token=None, until=0.0)
    for old in _picture_files():
        old.unlink(missing_ok=True)
    settings.update(
        {
            "account_id": "",
            "account_email": "",
            "account_name": "",
            "account_provider": "",
            "account_device_id": "",
            "account_relink_phone": False,
            "account_tier": "free",
            "account_pro_until": 0,
            "account_used_bytes": 0,
            "account_storage_bytes": 0,
            "sync_relay_url": "",
        }
    )
    with _lock:
        _progress.update(state="idle", error=None)


def sign_out() -> None:
    """Cancel this Mac's device and end its sign-in; the phone and the library on the
    relay are untouched. Done here even when the relay cannot be reached."""
    try:
        token = _access_token()
        mine = settings.get("account_device_id")
        with _client() as http:
            if mine:
                http.delete(f"/account/devices/{mine}", headers=_bearer(token))
            refresh = keyring.session_get()
            if refresh:
                http.post("/auth/logout", json={"refresh_token": refresh})
    except (AccountError, httpx.HTTPError):
        pass
    _forget_here()


def delete_account() -> None:
    """End the account: every device stops syncing and the relay drops the library.
    The library on this Mac (and on the phone) stays."""
    with _client() as http:
        resp = http.delete("/account", headers=_bearer(_access_token()))
    if resp.status_code not in (204, 401):
        raise AccountError(f"Enqueue sync could not delete the account ({_detail(resp)}).")
    _forget_here()
