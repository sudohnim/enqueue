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
        # The env must be cleared or this test reads the real ENQ_LLM_API_KEY and
        # passes or fails depending on whether the launcher exported one.
        monkeypatch.delenv("ENQ_LLM_API_KEY", raising=False)
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

    def test_backends_report_a_keychain_key_as_present(self, store, monkeypatch):
        """I7.1: key_present reflects the resolved key (Keychain or env), so the
        panel warning cannot contradict what api_key_state reports."""
        monkeypatch.delenv("ENQ_LLM_API_KEY", raising=False)
        monkeypatch.setattr(keyring, "get", lambda: "sk-live-abcdefgh9999")
        by_name = {b["name"]: b for b in settings.backends()}
        assert by_name["openrouter"]["key_present"] is True
        assert by_name["opencode"]["key_present"] is True
        assert by_name["ollama"]["key_present"] is False  # needs no key

    def test_backends_with_no_key_report_absent(self, store, monkeypatch):
        monkeypatch.delenv("ENQ_LLM_API_KEY", raising=False)
        monkeypatch.setattr(keyring, "get", lambda: None)
        by_name = {b["name"]: b for b in settings.backends()}
        assert by_name["openrouter"]["key_present"] is False
        assert by_name["opencode-go"]["key_present"] is False

    def test_backends_environment_key_wins(self, store, monkeypatch):
        """The environment is still the top of the resolution order (I7.1)."""
        monkeypatch.setenv("ENQ_LLM_API_KEY", "sk-from-the-environment")
        by_name = {b["name"]: b for b in settings.backends()}
        assert by_name["openrouter"]["key_present"] is True

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


class TestNothingIsWrittenUntilUpdate:
    """The contract the settings forms rely on: the file changes only when an
    explicit update() lands, and then only by the named changes - never as a side
    effect of reading settings or re-rendering a form."""

    def test_no_settings_file_exists_until_an_update_is_called(self, store):
        assert not settings.settings_path().exists()

    def test_update_writes_only_the_named_changes(self, store):
        settings.update({"llm_model": "some-model"})
        written = json.loads(settings.settings_path().read_text(encoding="utf-8"))
        assert written == {"llm_model": "some-model"}

    def test_update_merges_into_what_is_already_stored(self, store):
        settings.update({"llm_model": "some-model"})
        settings.update({"user_agent": "Enqueue/0.2"})
        written = json.loads(settings.settings_path().read_text(encoding="utf-8"))
        assert written == {"llm_model": "some-model", "user_agent": "Enqueue/0.2"}


class TestSyncSettings:
    """SYNC.3: the relay URL is a plaintext setting; the per-library secret lives
    in the Keychain and is never written to a file; the device id is stable."""

    def _stub_secret(self, monkeypatch, value=None):
        stored = {"secret": value}
        monkeypatch.setattr(keyring, "sync_secret_get", lambda: stored["secret"])
        monkeypatch.setattr(keyring, "sync_secret_set", lambda s: stored.__setitem__("secret", s))
        monkeypatch.setattr(
            keyring, "sync_secret_clear", lambda: stored.__setitem__("secret", None)
        )
        monkeypatch.setattr(keyring, "sync_secret_hint", lambda: keyring.hint(stored["secret"]))
        return stored

    def test_get_settings_reports_relay_configuration(self, store, monkeypatch):
        from fastapi.testclient import TestClient

        from enqueue.api import app

        self._stub_secret(monkeypatch, value="shh-secret")

        with TestClient(app) as client:
            empty = client.get("/settings").json()["sync"]
            assert empty["relay_configured"] is False
            assert empty["relay_url"] == ""
            assert empty["secret_present"] is True
            assert empty["device_id"]

        settings.update({"sync_relay_url": "https://relay.example/v1"})
        with TestClient(app) as client:
            configured = client.get("/settings").json()["sync"]
            assert configured["relay_configured"] is True
            assert configured["relay_url"] == "https://relay.example/v1"

    def test_the_sync_secret_never_touches_disk(self, store, monkeypatch):
        stored = self._stub_secret(monkeypatch, value=None)

        keyring.sync_secret_set("shh-secret")
        settings.update({"sync_relay_url": "https://relay.example"})

        assert stored["secret"] == "shh-secret"
        written = json.loads(settings.settings_path().read_text(encoding="utf-8"))
        assert "shh-secret" not in json.dumps(written)
        # The URL is plaintext on purpose; the secret is not.
        assert written["sync_relay_url"] == "https://relay.example"

    def test_device_id_is_stable_and_a_uuid(self, store):
        import uuid

        from enqueue.sync import device_id

        first = device_id()
        second = device_id()
        assert first == second
        uuid.UUID(first)  # a real UUID4, not a name-derived string
