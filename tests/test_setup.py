"""Where an installation stands (setup.py): the steps left, the settings that need a
look, and the one answer about settings that may call a model."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from enqueue import backup, settings, setup

LOCAL = {"name": "ollama", "label": "Ollama", "local": True, "needs_key": False}
REMOTE = {
    "name": "openrouter",
    "label": "OpenRouter",
    "local": False,
    "needs_key": True,
    "key_present": True,
}
NO_SYNC = {
    "relay_url": "",
    "relay_configured": False,
    "secret_present": False,
    "keyring_ready": False,
    "keyring_locked": False,
    "keyring_legacy": False,
}
NO_KEY = {"api_key_present": False, "api_key_where": None}


@pytest.fixture
def world(store, monkeypatch):
    """An installation described by a few dicts, so each test says what it is about."""
    state = {
        "backend": dict(LOCAL),
        "sync": dict(NO_SYNC),
        "key": dict(NO_KEY),
        "values": {"llm_model": "llama3.1:8b", "vision_model": "llava"},
        "backup_dir": None,
        "last": None,
        "summaries": (0, 0),
    }
    monkeypatch.setattr(setup, "_backend", lambda: state["backend"])
    monkeypatch.setattr(settings, "sync_state", lambda: state["sync"])
    monkeypatch.setattr(settings, "api_key_state", lambda: state["key"])
    monkeypatch.setattr(settings, "get", lambda name: state["values"].get(name, ""))
    monkeypatch.setattr(backup, "configured_dir", lambda: state["backup_dir"])
    monkeypatch.setattr(backup, "last", lambda: state["last"])
    monkeypatch.setattr(setup, "_summaries", lambda: state["summaries"])
    return state


def _step(ident: str) -> dict:
    return next(s for s in setup.status()["steps"] if s["id"] == ident)


def _alerts() -> set[str]:
    return {a["id"] for a in setup.status()["alerts"]}


def _ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class TestSteps:
    def test_a_fresh_installation_has_a_local_model_and_two_things_left(self, world):
        assert _step("model")["state"] == setup.DONE
        assert _step("backup")["state"] == setup.TODO
        assert _step("phone")["state"] == setup.TODO
        assert _alerts() == set()

    def test_a_service_without_its_key_is_not_connected(self, world):
        world["backend"] = REMOTE | {"key_present": False}
        step = _step("model")
        assert step["state"] == setup.TODO and step["guide"] == "api-key"

    def test_opencode_go_needs_its_session_header(self, world):
        world["backend"] = REMOTE | {"name": "opencode-go", "label": "OpenCode Go"}
        world["values"]["llm_model"] = "kimi-k3"
        assert _step("model")["state"] == setup.TODO
        world["values"]["llm_headers"] = "x-opencode-session: abc"
        assert _step("model")["state"] == setup.DONE

    def test_a_backup_is_done_only_once_a_recent_copy_exists(self, world, tmp_path, monkeypatch):
        from enqueue import config, libkey

        monkeypatch.setattr(config, "DATA_DIR", tmp_path)
        world["backup_dir"] = tmp_path / "Enqueue Backup"
        assert _step("backup")["state"] == setup.TODO, "chosen, but no copy made yet"
        world["last"] = {"at": _ago(0.2)}
        step = _step("backup")
        assert (
            step["state"] == setup.WARN and "recovery kit" in step["title"]
        ), "a copy only a lost key opens is not done"
        libkey.get()
        libkey.mark_kit_saved()
        assert _step("backup")["state"] == setup.DONE
        world["last"] = {"at": _ago(9)}
        assert _step("backup")["state"] == setup.WARN

    def test_a_backup_folder_that_went_away_is_said(self, world):
        world["backup_dir"] = Path("/nonexistent-drive/Enqueue Backup")
        assert _step("backup")["state"] == setup.WARN

    def test_sync_is_ready_only_when_every_part_is(self, world):
        world["sync"] = NO_SYNC | {"relay_url": "https://relay.example", "relay_configured": True}
        assert _step("phone")["state"] == setup.TODO
        world["sync"] |= {"secret_present": True, "keyring_ready": True}
        assert _step("phone")["state"] == setup.DONE
        world["sync"] |= {"keyring_ready": False, "keyring_locked": True}
        step = _step("phone")
        assert step["state"] == setup.WARN and step["guide"] == "recovery-phrase"


class TestAlerts:
    def test_a_key_and_headers_nothing_uses_are_pointed_out(self, world):
        world["key"] = {"api_key_present": True, "api_key_where": "keychain"}
        world["values"]["llm_headers"] = "x-opencode-session: abc"
        assert {"key-unused", "headers-unused"} <= _alerts()
        world["backend"] = dict(REMOTE)
        assert not {"key-unused", "headers-unused"} & _alerts()

    def test_a_refused_key_is_said_for_an_online_assistant(self, world, monkeypatch):
        from enqueue.providers import pause

        monkeypatch.setattr(pause, "key_refused", lambda: True)
        assert "key-refused" not in _alerts()  # the assistant on this Mac has no key
        world["backend"] = dict(REMOTE)
        assert "key-refused" in _alerts()

    def test_a_model_the_service_no_longer_answers_for(self, world):
        world["backend"] = REMOTE | {"name": "opencode-go", "label": "OpenCode Go"}
        world["values"] |= {"llm_model": "kimi-k3", "summarize_model": "retired-model"}
        alert = next(a for a in setup.status()["alerts"] if a["id"] == "model-unknown")
        assert "retired-model" in alert["text"] and "kimi-k3" not in alert["text"]

    def test_a_relay_only_this_network_reaches(self, world):
        ready = {"relay_configured": True, "secret_present": True, "keyring_ready": True}
        for url in ("http://127.0.0.1:8788", "http://192.168.1.20:8788", "http://localhost:8788"):
            world["sync"] = NO_SYNC | ready | {"relay_url": url}
            assert "relay-local" in _alerts(), url
        world["sync"] = NO_SYNC | ready | {"relay_url": "https://relay.example.com"}
        assert "relay-local" not in _alerts()

    def test_summaries_waiting_for_the_new_model(self, world):
        world["summaries"] = (12, 1)
        texts = {a["id"]: a["text"] for a in setup.status()["alerts"]}
        assert texts["summaries-stale"].startswith("12 items are waiting")
        assert texts["images-undescribed"].startswith("1 image has")


class TestWhatTheEyeIsTold:
    def test_nothing_secret_is_among_the_facts(self, world):
        world["sync"] = NO_SYNC | {
            "relay_url": "https://relay.example.com/private-path",
            "relay_configured": True,
        }
        world["values"]["llm_headers"] = "x-opencode-session: SESSIONVALUE"
        facts = str(setup.status()["facts"])
        assert "private-path" not in facts and "relay.example.com" not in facts
        assert "SESSIONVALUE" not in facts
        assert setup.status()["facts"]["relay"] == "hosted"


class _Model:
    model = "test-model"
    base_url = "http://127.0.0.1:11434/v1"

    def __init__(self, guide):
        self.guide, self.seen = guide, None

    def complete(self, system, user, response_model, **_):
        self.seen = user
        return response_model(answer="  Right now, no folder is chosen.  ", guide=self.guide)


class TestTheOneModelCall:
    GUIDES = [{"id": "backups", "title": "Backups", "text": "A copy of your library."}]

    def test_it_reads_the_guides_and_the_installation_and_never_the_library(
        self, world, monkeypatch
    ):
        from enqueue import notes
        from enqueue.providers import base

        notes.create(body="A private note about kilns and glaze recipes.")
        model = _Model("backups")
        monkeypatch.setattr(base, "get_provider", lambda *a, **k: model)

        out = setup.answer("do i lose everything if my mac dies", self.GUIDES)

        assert out == {"answer": "Right now, no folder is chosen.", "guide": "backups"}
        assert "A copy of your library." in model.seen
        assert '"backup_folder_chosen": false' in model.seen
        assert "kilns" not in model.seen

    def test_a_guide_it_was_not_offered_is_not_passed_on(self, world, monkeypatch):
        from enqueue.providers import base

        monkeypatch.setattr(base, "get_provider", lambda *a, **k: _Model("made-up"))
        assert setup.answer("anything", self.GUIDES)["guide"] is None

    def test_the_endpoints(self, world, monkeypatch):
        from fastapi.testclient import TestClient

        from enqueue.api.app import create_app
        from enqueue.providers import base

        monkeypatch.setattr(base, "get_provider", lambda *a, **k: _Model("backups"))
        client = TestClient(create_app())
        got = client.get("/setup").json()
        assert [s["id"] for s in got["steps"]] == ["model", "backup", "phone"]
        asked = client.post("/setup/ask", json={"question": "backups?", "guides": self.GUIDES})
        assert asked.status_code == 200 and asked.json()["guide"] == "backups"
        assert client.post("/setup/ask", json={"question": ""}).status_code == 422


INCLUDED = {
    "name": "enqueue",
    "label": "Included with Enqueue",
    "local": False,
    "needs_key": False,
    "included": True,
    "signed_in": True,
    "tier": "free",
}


class TestIncludedAssistant:
    def test_it_is_connected_only_when_signed_in(self, world):
        world["backend"] = INCLUDED | {"signed_in": False}
        step = _step("model")
        assert step["state"] == setup.TODO and "Sign in" in step["detail"]
        world["backend"] = dict(INCLUDED)
        assert _step("model")["state"] == setup.DONE

    def test_a_pro_model_on_the_free_plan_is_said(self, world):
        world["backend"] = dict(INCLUDED)
        world["values"]["llm_model"] = "anthropic/claude-haiku-5.5"
        world["values"]["vision_model"] = "anthropic/claude-haiku-5.5"
        assert "model-needs-pro" not in _alerts()
        world["values"]["llm_model"] = "anthropic/claude-sonnet-5.5"
        assert "model-needs-pro" in _alerts()
        world["backend"] = INCLUDED | {"tier": "pro"}
        assert "model-needs-pro" not in _alerts()

    def test_a_model_it_does_not_offer_is_said(self, world):
        world["backend"] = dict(INCLUDED)
        world["values"]["llm_model"] = "anthropic/claude-haiku-5.5"
        world["values"]["vision_model"] = "llava"
        assert "model-unknown" in _alerts()
