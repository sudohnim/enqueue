"""Settings, and the one value that must never be written to a file.

The API key is the interesting case. Everything else here is a preference; the key is
a secret, and the whole reason it lives in the Keychain is that `settings.json` is
plaintext on disk.
"""

from __future__ import annotations

import json

import pytest

from enqueue import keyring, settings
from enqueue.providers.ollama import _extra_headers


class TestTheKeyNeverTouchesDisk:
    def test_the_settings_file_has_no_field_for_it(self, store):
        assert "llm_api_key" not in settings.WRITABLE
        with pytest.raises(ValueError, match="not settable"):
            settings.update({"llm_api_key": "sk-should-never-land"})

    def test_writing_settings_does_not_write_a_key(self, store):
        settings.update({"llm_model": "some-model", "llm_headers": "X-Title: Enqueue"})
        written = json.loads(settings.settings_path().read_text(encoding="utf-8"))
        assert "llm_api_key" not in written
        assert not any("sk-" in str(v) for v in written.values())

    def test_what_is_reported_is_presence_and_a_hint_only(self, store, monkeypatch):
        monkeypatch.setattr(keyring, "available", lambda: True)
        monkeypatch.setattr(keyring, "get", lambda: "sk-live-abcdefgh9999")

        state = settings.api_key_state()
        assert state["api_key_present"] is True
        assert state["api_key_hint"] == "...9999"
        # The key itself must not appear anywhere in what the interface receives.
        assert "sk-live-abcdefgh9999" not in json.dumps(state)
        assert "sk-live-abcdefgh9999" not in json.dumps(settings.storage())

    def test_the_environment_wins_and_locks_the_field(self, store, monkeypatch):
        """A field that silently does nothing is worse than no field, so when the key
        is pinned by the environment the interface is told not to offer one."""
        monkeypatch.setenv("ENQ_LLM_API_KEY", "sk-from-the-environment")
        state = settings.api_key_state()
        assert state["api_key_where"] == "environment"
        assert state["api_key_editable"] is False

    def test_a_hint_is_useless_without_the_key(self, monkeypatch):
        # `hint(None)` means "look it up", so without this the test reads the real
        # login Keychain and passes or fails depending on what the developer happens
        # to have stored. Found the hard way: it failed against a key left behind by
        # a manual check in the running app.
        monkeypatch.setattr(keyring, "get", lambda: None)

        assert keyring.hint("sk-abcdefghijkl") == "...ijkl"
        assert keyring.hint("tiny") == "..."
        assert keyring.hint("") is None
        assert keyring.hint(None) is None


class TestKeychainGuards:
    def test_an_empty_key_is_refused(self, monkeypatch):
        monkeypatch.setattr(keyring, "available", lambda: True)
        with pytest.raises(ValueError, match="not a key"):
            keyring.set("   ")

    def test_a_line_break_is_refused(self, monkeypatch):
        """`security -i` is line-oriented, so a newline would end the command early
        and store a truncated key that looks fine and fails to authenticate."""
        monkeypatch.setattr(keyring, "available", lambda: True)
        with pytest.raises(ValueError, match="line break"):
            keyring.set("sk-first\nsk-second")

    def test_without_a_keychain_it_refuses_rather_than_falling_back(self, monkeypatch):
        """Falling back to the settings file would put the key in plaintext, quietly,
        which is worse than not offering to store it at all."""
        monkeypatch.setattr(keyring, "available", lambda: False)
        with pytest.raises(RuntimeError, match="ENQ_LLM_API_KEY"):
            keyring.set("sk-anything")
        assert keyring.get() is None


class TestExtraHeaders:
    def test_well_formed_lines_become_headers(self, store):
        settings.update({"llm_headers": "HTTP-Referer: https://example.com\nX-Title: Enqueue"})
        assert _extra_headers() == {
            "HTTP-Referer": "https://example.com",
            "X-Title": "Enqueue",
        }

    def test_malformed_lines_are_dropped_rather_than_sent(self, store):
        """A line with no colon is a typo. Sending it as a header produces a confusing
        rejection from the far end instead of a visible mistake here."""
        settings.update({"llm_headers": "no colon here\n: novalue\nX-Ok: yes\n\n"})
        assert _extra_headers() == {"X-Ok": "yes"}

    def test_empty_means_no_headers(self, store):
        settings.update({"llm_headers": ""})
        assert _extra_headers() == {}
