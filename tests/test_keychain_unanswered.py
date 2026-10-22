"""A Keychain that cannot answer is not a Keychain without the key.

The library key is made the first time it is asked for. A read that timed out behind a
permission prompt, was refused, or hit a locked keychain used to come back as "no key",
so the next ask made a new key and stored it over the real one (`-U`): an encrypted
library locked for good. These tests drive the real `_read` against a fake `security`.
"""

from __future__ import annotations

import subprocess

import pytest

from enqueue import keyring, libkey

# conftest swaps libkey's Keychain access for a file in every test; these tests need the
# real path, taken here at import, before any fixture runs.
_REAL_LOAD, _REAL_SAVE = libkey._load, libkey._save


class FakeSecurity:
    """Answers `security` the way macOS does: 44 for a missing item."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}
        self.fail: str | None = None  # "timeout" | "denied" | None
        self.writes = 0

    def run(self, args, input=None, **kw):
        if args[1:2] == ["-i"]:
            self.writes += 1
            parts = input.split()
            service = parts[parts.index("-s") + 1]
            self.items[service] = input.split('-w "', 1)[1].rsplit('"', 1)[0]
            return subprocess.CompletedProcess(args, 0, "", "")
        if self.fail == "timeout":
            raise subprocess.TimeoutExpired(args, kw.get("timeout", 0))
        if self.fail == "denied":
            return subprocess.CompletedProcess(args, 51, "", "User interaction is not allowed.")
        service = args[args.index("-s") + 1]
        if service not in self.items:
            return subprocess.CompletedProcess(args, 44, "", "could not be found")
        return subprocess.CompletedProcess(args, 0, self.items[service] + "\n", "")


@pytest.fixture
def security(monkeypatch):
    fake = FakeSecurity()
    monkeypatch.setattr(keyring, "available", lambda: True)
    monkeypatch.setattr(libkey, "_load", _REAL_LOAD)
    monkeypatch.setattr(libkey, "_save", _REAL_SAVE)
    monkeypatch.setattr(keyring.subprocess, "run", fake.run)
    keyring._CACHE.clear()
    yield fake
    keyring._CACHE.clear()


@pytest.mark.parametrize("failure", ["timeout", "denied"])
def test_an_unanswered_keychain_never_replaces_the_library_key(security, failure):
    first = libkey.get()
    stored = dict(security.items)
    writes = security.writes
    keyring._CACHE.clear()
    security.fail = failure
    with pytest.raises(keyring.KeychainUnavailable):
        libkey.get()
    assert security.items == stored and security.writes == writes
    security.fail = None
    keyring._CACHE.clear()
    assert libkey.get() == first


def test_a_missing_key_is_still_made_once(security):
    key = libkey.get()
    assert len(key) == 32 and security.writes == 1
    keyring._CACHE.clear()
    assert libkey.get() == key and security.writes == 1


def test_other_secrets_still_read_as_absent_when_unanswered(security):
    security.fail = "timeout"
    assert keyring._get("enqueue-llm-key") is None
    assert "enqueue-llm-key" not in keyring._CACHE  # not remembered as missing
