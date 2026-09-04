"""VAULT.2 - the PIN-wrapped vault key lifecycle.

Locks the guarantees the whole vault rests on: the raw key never hits disk, a
wrong PIN never unlocks, lock() clears memory, and there is NO recovery path
(zero-knowledge - a forgotten PIN is unrecoverable by design).
"""

from __future__ import annotations

import json

import pytest

from enqueue import config, keyring_file, vault


@pytest.fixture(autouse=True)
def _reset(store):
    vault.lock()
    yield
    vault.lock()


def _keyring_json() -> dict:
    return json.loads((config.DATA_DIR / "keyring.json").read_text())


def test_setup_creates_a_wrap_and_unlocks(store):
    assert vault.is_setup() is False
    vault.setup("123456")
    assert vault.is_setup() is True
    assert vault.is_unlocked() is True
    assert len(vault.key()) == 32


def test_the_raw_key_is_never_written_to_disk(store):
    vault.setup("123456")
    raw = vault.key()
    record = _keyring_json()
    # Only the salt + PIN-wrapped form are persisted; the raw key appears nowhere.
    assert "vault_salt" in record and "vault_by_pin" in record
    assert raw.hex() not in json.dumps(record)
    assert bytes.fromhex(record["vault_by_pin"]) != raw


def test_lock_clears_memory_and_key_raises(store):
    vault.setup("123456")
    vault.lock()
    assert vault.is_unlocked() is False
    with pytest.raises(vault.VaultError):
        vault.key()


def test_correct_pin_unlocks_to_the_same_key(store):
    vault.setup("123456")
    original = vault.key()
    vault.lock()
    assert vault.unlock("123456") == original
    assert vault.is_unlocked() is True


def test_wrong_pin_raises_and_stays_locked(store):
    vault.setup("123456")
    vault.lock()
    with pytest.raises(vault.VaultError):
        vault.unlock("000000")
    assert vault.is_unlocked() is False


def test_pin_must_be_six_digits(store):
    for bad in ("12345", "1234567", "abcdef", "12 45 6", ""):
        with pytest.raises(vault.VaultError):
            vault.setup(bad)
        assert vault.is_setup() is False


def test_no_recovery_path_exists(store):
    """Zero-knowledge: the wrap carries only the PIN slot, never a recovery slot,
    so nothing but the PIN can ever unwrap it."""
    vault.setup("123456")
    record = _keyring_json()
    assert "vault_by_pin" in record
    # No recovery-phrase wrap of the vault key, by design.
    assert "vault_by_recovery" not in record
    wrap = keyring_file.vault_wrap_get()
    assert set(wrap) == {"vault_salt", "vault_by_pin"}


def test_setup_refuses_when_already_set_up(store):
    vault.setup("123456")
    with pytest.raises(vault.VaultError):
        vault.setup("654321")


def test_change_pin_rewraps_same_key(store):
    vault.setup("123456")
    key = vault.key()
    vault.change_pin("123456", "654321")
    # Same key (content stays valid), still unlocked.
    assert vault.key() == key
    vault.lock()
    # Old PIN no longer works; new one does.
    with pytest.raises(vault.VaultError):
        vault.unlock("123456")
    assert vault.unlock("654321") == key


def test_change_pin_requires_correct_old(store):
    vault.setup("123456")
    with pytest.raises(vault.VaultError):
        vault.change_pin("000000", "654321")
