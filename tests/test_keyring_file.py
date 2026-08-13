"""The sync keyring file (E2E.md Phase E2).

Forgetting the password must not destroy the library: the DEK is wrapped under
both a password-KEK and a recovery-KEK. These prove unlock, wrong-password
refusal, recovery, and that the phrase never touches disk.
"""

from __future__ import annotations

import pytest

from enqueue import keyring_file


@pytest.fixture(autouse=True)
def _reset_dek():
    keyring_file._dek = None
    yield
    keyring_file._dek = None


def test_unlock_returns_the_dek_initialize_produced(store):
    keyring_file.initialize("hunter2")
    dek = keyring_file.dek()
    assert dek is not None

    keyring_file._dek = None
    assert keyring_file.unlock("hunter2") == dek


def test_unlock_with_a_wrong_password_raises(store):
    keyring_file.initialize("hunter2")
    keyring_file._dek = None
    with pytest.raises(keyring_file.UnlockError):
        keyring_file.unlock("wrong")


def test_recovery_unlocks_when_the_password_is_unknown(store):
    phrase = keyring_file.initialize("hunter2")
    dek = keyring_file.dek()

    keyring_file._dek = None
    assert keyring_file.unlock_with_recovery(phrase) == dek


def test_regenerate_recovery_invalidates_the_old_phrase(store):
    old = keyring_file.initialize("hunter2")
    dek = keyring_file.dek()
    assert dek is not None
    new = keyring_file.regenerate_recovery(dek)

    keyring_file._dek = None
    with pytest.raises(keyring_file.UnlockError):
        keyring_file.unlock_with_recovery(old)
    assert keyring_file.unlock_with_recovery(new) == dek


def test_the_recovery_phrase_never_touches_disk(store):
    phrase = keyring_file.initialize("hunter2")
    raw = keyring_file._path().read_text(encoding="utf-8")
    assert phrase not in raw
