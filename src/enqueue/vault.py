"""The secret-vault key (VAULT.2).

A random `vault_key` wrapped ONLY by a PIN-derived KEK (argon2id), mirroring the
DEK's recovery wrap - with one deliberate difference: it is NEVER also wrapped by
the recovery phrase and NEVER stored raw, so a forgotten PIN is unrecoverable BY
DESIGN (the settled zero-knowledge guarantee). The wrapped pair lives in
keyring.json (see `keyring_file.vault_wrap_*`); the raw key is held in process
memory only after `unlock()` and is dropped by `lock()` (called on app
background / inactivity, wired in VAULT.6).

Threat note: a 6-digit PIN is only 10^6 possibilities, so the wrap is not safe
against an offline brute-force by someone who has keyring.json. argon2id (MODERATE
ops/mem, the same KDF the DEK recovery uses) is the deliberate mitigation - each
guess costs ~0.1-0.7s, turning a full sweep into months, not seconds - and the
online lockout/backoff (VAULT.6) covers on-device guessing. This is the accepted
cost of a memorable PIN; a passphrase would raise it but the user chose 6 digits.
"""

from __future__ import annotations

import nacl.exceptions
import nacl.utils

from . import crypto, keyring_file

# The unwrapped vault key, in memory only after unlock. None = locked.
_vault_key: bytes | None = None


class VaultError(Exception):
    """The vault is not set up, is locked, a wrong PIN, or a bad PIN format."""


def _require_pin(pin: str) -> None:
    if not (isinstance(pin, str) and pin.isdigit() and len(pin) == 6):
        raise VaultError("PIN must be exactly 6 digits")


def is_setup() -> bool:
    """Whether a vault key has been created (a wrap exists)."""
    return keyring_file.vault_wrap_get() is not None


def is_unlocked() -> bool:
    return _vault_key is not None


def setup(pin: str) -> None:
    """Create the vault key on first use and wrap it under the PIN.

    Refuses if a vault already exists (changing the PIN is a separate rewrap, not
    this). The raw key is written NOWHERE - only the PIN-wrapped form is stored.
    """
    global _vault_key
    if is_setup():
        raise VaultError("vault already set up")
    _require_pin(pin)
    key = crypto.new_dek()
    salt = nacl.utils.random(16)
    kek = crypto.derive_kek(pin, salt)
    keyring_file.vault_wrap_set(salt.hex(), crypto.wrap(key, kek).hex())
    _vault_key = key


def unlock(pin: str) -> bytes:
    """Unwrap the vault key with the PIN into memory. Wrong PIN -> VaultError."""
    global _vault_key
    wrap = keyring_file.vault_wrap_get()
    if wrap is None:
        raise VaultError("vault is not set up")
    try:
        salt = bytes.fromhex(wrap["vault_salt"])
        wrapped = bytes.fromhex(wrap["vault_by_pin"])
        kek = crypto.derive_kek(pin, salt)
        _vault_key = crypto.unwrap(wrapped, kek)
    except (KeyError, ValueError, nacl.exceptions.CryptoError) as exc:
        # A wrong PIN or a damaged wrap: never return partial bytes.
        raise VaultError("incorrect PIN") from exc
    return _vault_key


def change_pin(old_pin: str, new_pin: str) -> None:
    """Re-wrap the SAME vault key under a new PIN (content stays encrypted as-is).

    Verifies the old PIN by unwrapping with it first, so a change needs the current
    code even when the vault is already open. The key never changes, so nothing has
    to be re-encrypted - only the wrapper. Leaves the vault unlocked.
    """
    global _vault_key
    key = unlock(old_pin)  # raises VaultError on a wrong old PIN
    _require_pin(new_pin)
    salt = nacl.utils.random(16)
    kek = crypto.derive_kek(new_pin, salt)
    keyring_file.vault_wrap_set(salt.hex(), crypto.wrap(key, kek).hex())
    _vault_key = key


def lock() -> None:
    """Drop the unwrapped key from memory. Idempotent."""
    global _vault_key
    _vault_key = None


def key() -> bytes:
    """The unwrapped vault key, or raise if locked. Callers encrypt/decrypt
    vaulted content with this (VAULT.3)."""
    if _vault_key is None:
        raise VaultError("vault is locked")
    return _vault_key
