"""The sync keyring file: the wrapped DEK, password, and recovery code (E2E.md Phase E2).

Forgetting the password must not destroy the library, so the DEK is wrapped
twice: once under a KEK derived from the password (Argon2id MODERATE), and once
under a recovery-KEK derived from a high-entropy recovery phrase. Only the
wrapped keys are written to `keyring.json`; the plaintext DEK is held in memory
only after unlock, and the recovery phrase is never written anywhere.

This is separate from `keyring.py` (the macOS API-key store) on purpose: those
keys go in the Keychain, while this file lives in `DATA_DIR` because the sync
folder itself does not carry it and the device must be able to unlock offline.
"""

from __future__ import annotations

import json

import nacl.exceptions
import nacl.utils

from . import config, crypto


def _path():
    # Resolved at call time, not import, so a test that repoints config.DATA_DIR
    # at a temp dir still reads and writes the right file (same as settings_path).
    return config.DATA_DIR / "keyring.json"


# The plaintext DEK, held in memory only after unlock (E2E.md Section 1). None
# until then; the sync client treats a locked keyring as "sync paused".
_dek: bytes | None = None


def dek() -> bytes | None:
    """The unlocked DEK, or None when the keyring is locked or uninitialized."""
    return _dek


class UnlockError(Exception):
    """A wrong password or recovery phrase; never returns partial bytes."""


def _crockford_base32(data: bytes) -> str:
    """Crockford base32 (no I, L, O, U) of the bytes - the recovery phrase."""
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    out: list[str] = []
    acc = 0
    bits = 0
    for byte in data:
        acc = (acc << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append(alphabet[(acc >> bits) & 31])
    if bits:
        out.append(alphabet[(acc << (5 - bits)) & 31])
    return "".join(out)


def _read() -> dict | None:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write(record: dict) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    path.chmod(0o600)


def is_initialized() -> bool:
    return _path().exists()


def initialize(password: str) -> str:
    """Create the DEK, wrap it twice, write keyring.json, return the recovery phrase."""
    global _dek

    dek = crypto.new_dek()

    password_salt = nacl.utils.random(16)
    kek = crypto.derive_kek(password, password_salt)
    dek_by_password = crypto.wrap(dek, kek)

    phrase = _crockford_base32(nacl.utils.random(20))
    recovery_salt = nacl.utils.random(16)
    recovery_kek = crypto.derive_kek(phrase, recovery_salt)
    dek_by_recovery = crypto.wrap(dek, recovery_kek)

    _write(
        {
            "version": 1,
            "password_salt": password_salt.hex(),
            "recovery_salt": recovery_salt.hex(),
            "dek_by_password": dek_by_password.hex(),
            "dek_by_recovery": dek_by_recovery.hex(),
        }
    )
    _dek = dek
    return phrase


def _unlock(field: str, secret: str, salt_field: str) -> bytes:
    record = _read()
    if record is None:
        raise UnlockError("sync has not been initialized")
    try:
        salt = bytes.fromhex(record[salt_field])
        wrapped = bytes.fromhex(record[field])
        kek = crypto.derive_kek(secret, salt)
        return crypto.unwrap(wrapped, kek)
    except (KeyError, ValueError, nacl.exceptions.CryptoError) as exc:
        # A wrong password, a wrong recovery phrase, or a damaged record are all
        # one case: cannot unlock, and never partial bytes.
        raise UnlockError("could not unlock") from exc


def unlock(password: str) -> bytes:
    global _dek

    _dek = _unlock("dek_by_password", password, "password_salt")
    return _dek


def unlock_with_recovery(phrase: str) -> bytes:
    global _dek

    _dek = _unlock("dek_by_recovery", phrase, "recovery_salt")
    return _dek


def regenerate_recovery(dek: bytes) -> str:
    """Make a new recovery phrase and rewrap, invalidating the old one."""
    record = _read()
    if record is None:
        raise UnlockError("sync has not been initialized")
    phrase = _crockford_base32(nacl.utils.random(20))
    salt = nacl.utils.random(16)
    kek = crypto.derive_kek(phrase, salt)
    record["recovery_salt"] = salt.hex()
    record["dek_by_recovery"] = crypto.wrap(dek, kek).hex()
    _write(record)
    return phrase
