"""The sync keyring file (QR.1 passwordless format).

The DEK is wrapped only under a recovery-KEK and persists in the Keychain (or a
mode-0600 file off macOS), so there is no password and no locked-on-restart
state: initialize() creates everything, the recovery phrase recovers the DEK if
the Keychain/file is lost, and the phrase never touches disk.
"""

from __future__ import annotations

import pytest

from enqueue import keyring_file


@pytest.fixture(autouse=True)
def _reset_dek():
    keyring_file._dek = None
    yield
    keyring_file._dek = None


def test_initialize_creates_a_keyring_without_a_password(store):
    phrase = keyring_file.initialize()
    assert phrase
    assert keyring_file.is_initialized()
    assert keyring_file.dek() is not None


def test_the_dek_survives_a_restart_via_the_stored_copy(store):
    keyring_file.initialize()
    dek = keyring_file.dek()
    assert dek is not None

    # An engine restart loses the in-memory DEK; the stored copy (Keychain/file)
    # restores it with no password and no prompt (QR.1).
    keyring_file._dek = None
    assert keyring_file.dek() is None
    loaded = keyring_file.load_dek_from_keychain()
    assert loaded == dek
    assert keyring_file.dek() == dek


def test_recovery_unlocks_when_the_stored_dek_is_lost(store):
    from enqueue import keyring

    phrase = keyring_file.initialize()
    dek = keyring_file.dek()
    assert dek is not None

    # Total device loss of the stored DEK: the recovery phrase is the only way.
    keyring_file._dek = None
    keyring.dek_clear()
    assert keyring_file.load_dek_from_keychain() is None
    assert keyring_file.unlock_with_recovery(phrase) == dek
    # The recovered DEK is stored again, so a later restart stays unlocked.
    assert keyring_file.load_dek_from_keychain() == dek


def test_a_wrong_recovery_phrase_raises(store):
    keyring_file.initialize()
    keyring_file._dek = None
    with pytest.raises(keyring_file.UnlockError):
        keyring_file.unlock_with_recovery("0" * 40)


def test_regenerate_recovery_invalidates_the_old_phrase(store):
    old = keyring_file.initialize()
    dek = keyring_file.dek()
    assert dek is not None
    new = keyring_file.regenerate_recovery(dek)

    keyring_file._dek = None
    with pytest.raises(keyring_file.UnlockError):
        keyring_file.unlock_with_recovery(old)
    assert keyring_file.unlock_with_recovery(new) == dek


def test_the_recovery_phrase_never_touches_disk(store):
    phrase = keyring_file.initialize()
    raw = keyring_file._path().read_text(encoding="utf-8")
    assert phrase not in raw


def test_the_keyring_file_has_no_password_slot(store):
    keyring_file.initialize()
    record = keyring_file._read()
    assert record is not None
    assert record["version"] == 2
    assert "dek_by_password" not in record
    assert "password_salt" not in record
    assert "dek_by_recovery" in record


def test_a_legacy_two_slot_file_is_detected(store):
    legacy = {
        "version": 1,
        "password_salt": "ab" * 16,
        "recovery_salt": "cd" * 16,
        "dek_by_password": "ef" * 40,
        "dek_by_recovery": "01" * 40,
    }
    keyring_file._write(legacy)
    assert keyring_file.is_initialized()
    assert keyring_file.is_legacy()


def test_initialize_overwrites_a_legacy_file_in_place(store):
    legacy = {
        "version": 1,
        "password_salt": "ab" * 16,
        "recovery_salt": "cd" * 16,
        "dek_by_password": "ef" * 40,
        "dek_by_recovery": "01" * 40,
    }
    keyring_file._write(legacy)

    phrase = keyring_file.initialize()
    assert keyring_file.is_legacy() is False
    record = keyring_file._read()
    assert record is not None
    assert record["version"] == 2
    assert "password_salt" not in record
    assert keyring_file.unlock_with_recovery(phrase) == keyring_file.dek()


def test_clear_keyring_removes_the_file_and_dek(store):
    keyring_file.initialize()
    assert keyring_file.is_initialized()
    keyring_file.clear_keyring()
    assert not keyring_file.is_initialized()
    assert keyring_file.dek() is None
