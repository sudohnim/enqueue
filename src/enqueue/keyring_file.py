"""The sync keyring file: the wrapped DEK and recovery code (QR.1).

The DEK is wrapped ONLY under a recovery-KEK derived from a high-entropy
recovery phrase. The password-KEK wrap slot has been removed (QR.1): the
DEK persists in the macOS Keychain (or a mode-0600 file on non-macOS), so
no password is needed to unlock on restart. The recovery phrase is the only
way to recover the DEK if the Keychain/file is lost.

Only the wrapped DEK is written to `keyring.json`; the plaintext DEK is held
in memory after unlock/load, and the recovery phrase is never written anywhere.

This is separate from `keyring.py` (the macOS API-key store) on purpose: those
keys go in the Keychain, while this file lives in `DATA_DIR` because the sync
folder itself does not carry it and the device must be able to unlock offline.
"""

from __future__ import annotations

import json

import nacl.exceptions
import nacl.utils

from . import config, crypto, keyring


def _path():
    # Resolved at call time, not import, so a test that repoints config.DATA_DIR
    # at a temp dir still reads and writes the right file (same as settings_path).
    return config.DATA_DIR / "keyring.json"


# The plaintext DEK, held in memory only after unlock/load (QR.1). None
# until then; the sync client treats a locked keyring as "sync paused".
_dek: bytes | None = None


def dek() -> bytes | None:
    """The unlocked DEK, or None when the keyring is locked or uninitialized."""
    return _dek


class UnlockError(Exception):
    """A wrong recovery phrase; never returns partial bytes."""


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


def _is_legacy_format(record: dict) -> bool:
    """True for the old two-slot (password + recovery) keyring.json format."""
    return "password_salt" in record and "dek_by_password" in record


def is_legacy() -> bool:
    """Whether the existing keyring.json is the pre-QR.1 two-slot format.

    Legacy files are pre-release dev installs only. The new code cannot use the
    password slot and must not carry it forward: such a file is re-initialized
    in place (fresh DEK + fresh recovery phrase) behind the destructive
    confirmation, same semantics as FIX.4's guarded reset.
    """
    record = _read()
    return record is not None and _is_legacy_format(record)


def initialize() -> str:
    """Create the DEK, wrap it under the recovery-KEK only, write keyring.json,
    store the DEK in the Keychain/file, return the recovery phrase.

    A legacy two-slot keyring (pre-QR.1) is overwritten in place with a fresh
    DEK and recovery phrase - the caller decides when that is safe (the
    destructive confirmation).
    """
    global _dek

    dek = crypto.new_dek()

    phrase = _crockford_base32(nacl.utils.random(20))
    recovery_salt = nacl.utils.random(16)
    recovery_kek = crypto.derive_kek(phrase, recovery_salt)
    dek_by_recovery = crypto.wrap(dek, recovery_kek)

    _write(
        {
            "version": 2,  # version 2 = passwordless (recovery-only) format
            "recovery_salt": recovery_salt.hex(),
            "dek_by_recovery": dek_by_recovery.hex(),
        }
    )

    # Store the raw DEK in the Keychain (macOS) or file (other platforms)
    keyring.dek_store(dek)

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
        # A wrong recovery phrase, or a damaged record: cannot unlock.
        raise UnlockError("could not unlock") from exc


def unlock_with_recovery(phrase: str) -> bytes:
    """Unlock the DEK using the recovery phrase, then store it in Keychain/file."""
    global _dek

    _dek = _unlock("dek_by_recovery", phrase, "recovery_salt")
    keyring.dek_store(_dek)
    return _dek


def load_dek_from_keychain() -> bytes | None:
    """Load the DEK from Keychain/file into memory on engine startup (QR.1).

    Returns the DEK if found and loads it into _dek, or None if not stored.
    Does not raise - a missing DEK just means sync stays paused until
    explicit unlock or re-initialization.
    """
    global _dek

    if _dek is not None:
        return _dek

    dek = keyring._dek_get()
    if dek is not None:
        _dek = dek
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


def vault_wrap_get() -> dict | None:
    """The stored vault-key wrap (`vault_salt` + `vault_by_pin`), or None if no
    vault has been set up. Lives alongside `dek_by_recovery` in keyring.json - the
    natural home for wrapped-key material - but is a SEPARATE secret: the DEK's
    recovery wrap and the vault's PIN wrap never share a key (the vault is
    zero-knowledge, unrecoverable without the PIN)."""
    record = _read()
    if not record or "vault_salt" not in record or "vault_by_pin" not in record:
        return None
    return {"vault_salt": record["vault_salt"], "vault_by_pin": record["vault_by_pin"]}


def vault_wrap_set(salt_hex: str, wrapped_hex: str) -> None:
    """Persist the vault-key wrap into keyring.json (creating the file if needed)."""
    record = _read() or {}
    record["vault_salt"] = salt_hex
    record["vault_by_pin"] = wrapped_hex
    _write(record)


def vault_wrap_clear() -> None:
    """Forget the vault wrap. The vaulted CONTENT stays encrypted-at-rest and
    becomes permanently unreadable - callers must confirm before calling this."""
    record = _read()
    if not record:
        return
    record.pop("vault_salt", None)
    record.pop("vault_by_pin", None)
    _write(record)


def clear_keyring() -> None:
    """Remove keyring.json and the stored DEK (for reset sync)."""
    global _dek

    _path().unlink(missing_ok=True)
    keyring.dek_clear()
    _dek = None
