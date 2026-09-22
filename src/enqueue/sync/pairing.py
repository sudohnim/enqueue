"""Device pairing (PAIR.1): hand a whole library to a brand-new device over the relay,
with no recovery phrase, no Keychain surgery, and no plaintext key anywhere on the wire.

The problem: a second computer joining the library needs the relay URL, the sync secret,
and the DEK. The relay authenticates every object route with the sync secret, which the
new device does not yet have (it is one of the things being handed over), so it cannot use
the normal object store. And the DEK must never travel as something copy-pasteable.

The flow:
  - The MAIN device (which has the secret) seals {relay, secret, dek} under an Argon2id KEK
    derived from a freshly minted pairing PHRASE - the same primitive that wraps the
    keyring - and PUTs the sealed envelope to `/pair/<id>` on the relay. It shows the id and
    the phrase to the user.
  - The NEW device fetches `/pair/<id>` (no secret needed; the id is a one-time capability),
    derives the same KEK from the phrase the user typed, opens the envelope, and imports the
    secret + DEK. It then pulls the library keyring and the data down like any other join.

The phrase never touches the relay, so the relay (or anyone who guesses an id) sees only
ciphertext. The id locates the envelope; the phrase alone can open it. Keeping them separate
means no single copyable string is the master key.
"""

from __future__ import annotations

import json
import secrets

import httpx

from .. import crypto, keyring, keyring_file, settings
from . import client

# The pairing phrase's entropy: 15 random bytes -> 24 Crockford base32 chars. High enough
# that the Argon2id KEK cannot be brute-forced through the sealed envelope, unlike a PIN.
_PHRASE_BYTES = 15
_SALT_BYTES = 16


class PairingError(Exception):
    """A pairing offer or claim could not be completed (surfaced to the user)."""


def _phrase() -> str:
    return keyring_file._crockford_base32(secrets.token_bytes(_PHRASE_BYTES))


def _normalize_phrase(phrase: str) -> str:
    # The phrase is Crockford base32; accept it however the user retyped it (spaces,
    # dashes, lower case) so a transcription that reads the same still opens the envelope.
    return (phrase or "").strip().upper().replace(" ", "").replace("-", "")


def seal_envelope(payload: dict, phrase: str) -> bytes:
    """Seal a pairing payload under an Argon2id KEK derived from the phrase. The 16-byte
    salt is prepended to the SecretBox ciphertext so the far side can derive the same KEK."""
    salt = secrets.token_bytes(_SALT_BYTES)
    kek = crypto.derive_kek(_normalize_phrase(phrase), salt)
    return salt + crypto.encrypt(json.dumps(payload).encode("utf-8"), kek)


def open_envelope(envelope: bytes, phrase: str) -> dict:
    """Inverse of seal_envelope. Raises PairingError on a wrong phrase or damaged bytes."""
    if len(envelope) <= _SALT_BYTES:
        raise PairingError("The pairing envelope was malformed.")
    salt, sealed = envelope[:_SALT_BYTES], envelope[_SALT_BYTES:]
    try:
        kek = crypto.derive_kek(_normalize_phrase(phrase), salt)
        return json.loads(crypto.decrypt(sealed, kek).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - any failure is "wrong phrase / bad data"
        raise PairingError("The phrase did not open the pairing. Check it and try again.") from exc


def create_offer() -> dict:
    """MAIN device: seal this library's {relay, secret, dek} and stage it on the relay.

    Returns the pairing id and phrase to show the user. Requires sync to be fully set up
    here (relay + secret + an unlocked DEK)."""
    relay = (settings.get("sync_relay_url") or "").strip()
    if not relay:
        raise PairingError("Set up sync on this device before pairing another one.")
    secret = keyring.sync_secret_get()
    if not secret:
        raise PairingError("This device has no sync secret yet. Finish setting up sync first.")
    dek = keyring_file.load_dek_from_keychain()
    if dek is None:
        raise PairingError("The library key is locked on this device. Unlock sync, then retry.")

    phrase = _phrase()
    envelope = seal_envelope({"relay": relay, "secret": secret, "dek": dek.hex()}, phrase)

    pid = secrets.token_urlsafe(18)  # 24 url-safe chars; matches the relay's id pattern
    try:
        with httpx.Client(timeout=30) as http:
            resp = http.put(
                f"{relay.rstrip('/')}/pair/{pid}",
                content=envelope,
                headers={
                    "Authorization": f"Bearer {secret}",
                    "Content-Type": "application/octet-stream",
                },
            )
    except httpx.HTTPError as exc:
        raise PairingError(f"Could not reach the relay to stage the pairing: {exc}") from exc
    if resp.status_code not in (200, 201):
        raise PairingError(f"The relay refused the pairing ({resp.status_code}).")

    return {"pairing_id": pid, "phrase": phrase, "relay_url": relay, "expires_in": 600}


def claim_offer(relay_url: str, pairing_id: str, phrase: str) -> dict:
    """NEW device: fetch the sealed envelope, open it with the phrase, and import the key.

    Refused when this device already has its own keyring - joining would orphan that DEK.
    After importing, it pulls the library keyring (for the vault wrap + the initialized
    marker) and kicks a background pull of the data."""
    relay = (relay_url or "").strip()
    pairing_id = (pairing_id or "").strip()
    phrase = (phrase or "").strip()
    if not relay or not pairing_id or not phrase:
        raise PairingError("Relay URL, pairing code, and phrase are all required.")
    if keyring_file.is_initialized():
        raise PairingError(
            "This device already has a sync keyring. Reset sync here first if you mean to "
            "replace it - joining another library would orphan the current one."
        )

    try:
        with httpx.Client(timeout=30) as http:
            resp = http.get(f"{relay.rstrip('/')}/pair/{pairing_id}")
    except httpx.HTTPError as exc:
        raise PairingError(f"Could not reach the relay: {exc}") from exc
    if resp.status_code == 404:
        raise PairingError(
            "That pairing code was not found. It may have expired, already been used, or "
            "been mistyped - generate a fresh one on the other device."
        )
    if resp.status_code != 200:
        raise PairingError(f"The relay returned {resp.status_code} fetching the pairing.")

    payload = open_envelope(resp.content, phrase)

    imported_relay = (payload.get("relay") or relay).strip()
    secret = payload.get("secret") or ""
    dek_hex = payload.get("dek") or ""
    try:
        dek = bytes.fromhex(dek_hex)
    except ValueError as exc:
        raise PairingError("The pairing contained an invalid key.") from exc
    if not secret or len(dek) != crypto.DEK_BYTES:
        raise PairingError("The pairing was incomplete.")

    # Point at the relay + secret first, so pulling the keyring is an authenticated GET.
    settings.update({"sync_relay_url": imported_relay})
    keyring.sync_secret_set(secret)

    # The library keyring (vault wrap + the initialized marker) rides down from the relay;
    # we do not need the recovery phrase because the envelope already carried the raw DEK.
    if not client.pull_keyring():
        raise PairingError(
            "Could not fetch the library keyring from the relay. Make sure the other device "
            "has finished setting up sync, then try again."
        )
    keyring.dek_store(dek)  # the DEK handed over directly - no recovery phrase needed

    settings.update({"sync_backfill_done": True})

    # Start the background sync worker now. It is normally started at engine boot, but this
    # device had no relay configured then, so start() no-op'd; without this a freshly paired
    # device would not auto-sync (pull deletes/edits) until the app was restarted. start() is
    # idempotent, so calling it again after a later restart is harmless.
    from . import worker

    worker.start()

    import threading

    def _bg():
        result = client.pull()
        print(f"[sync] pairing pull applied {result.get('pulled', 0)} snapshots", flush=True)

    threading.Thread(target=_bg, daemon=True).start()
    return settings.sync_state()
