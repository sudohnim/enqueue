"""Device approval: a computer signed in to Enqueue sync gets the library's key from a
device that already holds it, with nothing typed and no key on the wire in the clear.

The asking Mac (signed in, with its own device token, and no key yet) makes a Curve25519
key pair, posts the public half to the relay (`POST /account/joins`) and shows a code
made from it (crypto.join_code). Every other signed-in Mac sees the ask (`waiting()`),
shows the same code worked out from the same public key, and on Approve seals the
library's key to that public key and posts the sealed bytes. The asker collects them
once, opens them with its private half, fetches the library's keyring and starts
syncing. The relay holds only a public key and ciphertext; a relay that swapped in a key
of its own would make the two codes differ, which is why the person is asked to compare.

The private half lives in this process only. An engine restart while waiting simply
asks again.
"""

from __future__ import annotations

import base64
import json
import threading
import time

import httpx

from .. import crypto, keyring, keyring_file, settings

POLL_S = 3.0

_lock = threading.Lock()
_ask: dict = {"state": "idle", "id": None, "code": None, "expires_at": None, "error": None}
_private = None  # nacl.public.PrivateKey while an ask is waiting
_generation = 0


class JoinError(Exception):
    """Shown to the person as written."""


def _http() -> httpx.Client:
    """The client for the relay's own routes (replaced in tests)."""
    return httpx.Client(timeout=30)


def _relay() -> str:
    return (settings.get("sync_relay_url") or "").strip().rstrip("/")


def _token() -> str:
    token = keyring.sync_secret_get() or ""
    if not token:
        raise JoinError("Sign in to Enqueue sync first.")
    return token


def relay_keyring(token: str, relay: str) -> bytes | None:
    """The library's keyring on the relay, or None when the library has no key yet."""
    try:
        with _http() as http:
            resp = http.get(
                f"{relay.rstrip('/')}/sync/object/lib/keyring.enc",
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError:
        raise JoinError("Enqueue sync could not be reached. Try again.") from None
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise JoinError(f"Enqueue sync did not answer ({resp.status_code}). Try again.")
    return resp.content


def same_library(local: bytes, remote: bytes) -> bool:
    """Whether two keyrings hold the same library key: both wrap it under the same
    recovery phrase, so the recovery wrap and its salt match."""
    try:
        a, b = json.loads(local), json.loads(remote)
    except ValueError:
        return False
    keys = ("dek_by_recovery", "recovery_salt")
    return all(a.get(k) and a.get(k) == b.get(k) for k in keys)


# ---- the asking Mac --------------------------------------------------------------


def start() -> dict:
    """Ask to join. Needs the device token sign-in gave this Mac, and no key here."""
    global _private, _generation
    import nacl.public

    if keyring_file.load_dek_from_keychain() is not None:
        raise JoinError("This Mac already has the library's key.")
    relay, token = _relay(), _token()
    if not relay:
        raise JoinError("Sign in to Enqueue sync first.")
    private = nacl.public.PrivateKey.generate()
    public = bytes(private.public_key)
    try:
        with _http() as http:
            resp = http.post(
                f"{relay}/account/joins",
                json={"public_key": base64.b64encode(public).decode()},
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError:
        raise JoinError("Enqueue sync could not be reached. Try again.") from None
    if resp.status_code != 201:
        raise JoinError(_detail(resp, "Enqueue sync could not take the request"))
    body = resp.json()
    with _lock:
        _generation += 1
        gen = _generation
        _private = private
        _ask.update(
            state="waiting",
            id=body["id"],
            code=crypto.join_code(public),
            expires_at=body["expires_at"],
            error=None,
        )
    threading.Thread(target=_wait, args=(gen,), name="enqueue-join", daemon=True).start()
    return status()


def status() -> dict:
    with _lock:
        return {k: _ask[k] for k in ("state", "code", "expires_at", "error")}


def cancel() -> None:
    global _private, _generation
    with _lock:
        _generation += 1
        _private = None
        _ask.update(state="idle", id=None, code=None, expires_at=None, error=None)


def _set(gen: int, **values) -> bool:
    with _lock:
        if gen != _generation:
            return False
        _ask.update(values)
        return True


def _wait(gen: int) -> None:
    while True:
        time.sleep(POLL_S)
        with _lock:
            if gen != _generation:
                return
            jid, private, expires = _ask["id"], _private, _ask["expires_at"] or 0
        try:
            with _http() as http:
                resp = http.get(
                    f"{_relay()}/account/joins/{jid}",
                    headers={"Authorization": f"Bearer {_token()}"},
                )
        except (httpx.HTTPError, JoinError):
            if time.time() > expires:
                _set(gen, state="expired")
                return
            continue  # a dropped connection: keep waiting until the ask runs out
        if resp.status_code != 200:
            if time.time() > expires:
                _set(gen, state="expired")
                return
            continue
        answer = resp.json()
        if answer.get("status") == "pending":
            continue
        if answer.get("status") == "denied":
            _set(gen, state="denied")
            return
        if answer.get("status") != "approved":
            _set(gen, state="expired")
            return
        try:
            _receive(private, base64.b64decode(answer["sealed"]))
        except Exception as exc:  # noqa: BLE001 - shown to the person, never raised away
            _set(gen, state="failed", error=str(exc) or "The key did not arrive whole.")
            return
        _set(gen, state="approved", error=None)
        from .. import account

        account.joined()
        return


def _receive(private, sealed: bytes) -> None:
    """Open the sealed key, take the library's keyring and start syncing."""
    from . import client
    from .enable import enable

    try:
        payload = json.loads(crypto.open_sealed(private, sealed))
        dek = bytes.fromhex(payload["dek"])
    except Exception as exc:  # noqa: BLE001
        raise JoinError("The key that arrived could not be opened.") from exc
    if len(dek) != crypto.DEK_BYTES:
        raise JoinError("The key that arrived was not whole.")
    if not keyring_file.is_initialized() and not client.pull_keyring():
        raise JoinError("Could not fetch the library's keyring. Try again.")
    keyring.dek_store(dek)
    keyring_file._wrap_by_library(dek)
    keyring_file.load_dek_from_keychain()
    # Whatever this Mac already holds goes up once, beside what it pulls down.
    settings.update({"sync_backfill_done": False})
    enable(_token(), _relay())

    def _pull() -> None:
        from .. import events

        result = client.pull()
        events.emit(
            "sync.joined",
            f"joined the library: {result.get('pulled', 0)} items",
            {"pulled": result.get("pulled", 0)},
        )

    threading.Thread(target=_pull, name="enqueue-join-pull", daemon=True).start()


# ---- a Mac that holds the key -----------------------------------------------------


def waiting() -> list[dict]:
    """Devices asking to join, each with the code worked out here from its public key."""
    from .. import account

    if not account.signed_in():
        return []
    with account._client() as http:
        resp = http.get("/account/joins", headers=account._bearer(account._access_token()))
    if resp.status_code != 200:
        raise JoinError(_detail(resp, "Enqueue sync did not answer"))
    out = []
    for j in resp.json().get("joins", []):
        try:
            public = base64.b64decode(j["public_key"])
        except ValueError:
            continue
        out.append(
            {
                "id": j["id"],
                "name": j.get("name") or "A computer",
                "kind": j.get("kind") or "computer",
                "code": crypto.join_code(public),
                "expires_at": j.get("expires_at"),
            }
        )
    return out


def approve(join_id: str) -> None:
    """Seal this Mac's library key to the asker's public key, as the relay lists it."""
    from .. import account

    dek = keyring_file.load_dek_from_keychain()
    if dek is None:
        raise JoinError("This Mac does not hold the library's key, so it cannot approve.")
    token = account._access_token()
    with account._client() as http:
        listed = http.get("/account/joins", headers=account._bearer(token))
        if listed.status_code != 200:
            raise JoinError(_detail(listed, "Enqueue sync did not answer"))
        ask = next((j for j in listed.json().get("joins", []) if j["id"] == join_id), None)
        if ask is None:
            raise JoinError("That request has ended. Ask again from the other computer.")
        public = base64.b64decode(ask["public_key"])
        sealed = crypto.seal_to(public, json.dumps({"dek": dek.hex()}).encode())
        resp = http.post(
            f"/account/joins/{join_id}/approve",
            json={"sealed": base64.b64encode(sealed).decode()},
            headers=account._bearer(token),
        )
    if resp.status_code != 204:
        raise JoinError(_detail(resp, "Enqueue sync did not take the approval"))


def deny(join_id: str) -> None:
    from .. import account

    with account._client() as http:
        resp = http.post(
            f"/account/joins/{join_id}/deny", headers=account._bearer(account._access_token())
        )
    if resp.status_code not in (204, 404):
        raise JoinError(_detail(resp, "Enqueue sync did not take the answer"))


def _detail(resp: httpx.Response, lead: str) -> str:
    try:
        said = resp.json().get("detail")
    except ValueError:
        said = None
    return f"{lead} ({said or resp.status_code})."
