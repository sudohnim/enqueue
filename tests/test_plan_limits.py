"""A plan limit reached is said where it bites, with Upgrade on the free plan: the month's
included AI used up, Enqueue sync's storage full, and a second computer refused."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from enqueue import account, events, keyring_file, notes, settings, setup
from enqueue.providers import pause
from enqueue.providers.ollama import OpenAICompatibleProvider
from enqueue.relay.app import create_relay
from enqueue.schemas import Answer
from enqueue.sync import client
from tests.test_account import HOSTED, _sign_in_google, _token, world  # noqa: F401
from tests.test_relay_accounts import GOOGLE_DESKTOP
from tests.test_sync_regressions import _configure, _serve


@pytest.fixture(autouse=True)
def _no_pause():
    pause.reset()
    yield
    pause.reset()


@contextmanager
def _included_ai_used_up():
    """The relay's included assistant at the month's cap (relay/ai.py)."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - the name is BaseHTTPRequestHandler's
            self.rfile.read(int(self.headers["Content-Length"]))
            raw = json.dumps(
                {
                    "error": {
                        "message": "This month's included assistant is used up.",
                        "type": "usage_limit",
                        "code": 429,
                    }
                }
            ).encode()
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("retry-after", str(20 * 86400))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format, *args):  # noqa: ARG002 - silence the test server
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()


def _alerts() -> dict:
    return {a["id"]: a for a in setup.status()["alerts"]}


def test_the_months_included_ai_used_up_says_when_it_comes_back_and_offers_pro(store):
    with _included_ai_used_up() as base_url:
        provider = OpenAICompatibleProvider(model="some-model", base_url=base_url)
        with pytest.raises(Exception):
            provider.complete("s", "u", Answer, max_retries=1)
        assert pause.limit() == "included_ai"
        with pytest.raises(pause.ModelPaused) as caught:
            provider.complete("s", "u", Answer, max_retries=1)
    assert str(caught.value).startswith(pause.INCLUDED_USED_UP)
    assert "comes back on" in str(caught.value)

    alert = _alerts()["ai-used-up"]
    assert alert["upgrade"] and "model-paused" not in _alerts()
    settings.update({"account_tier": "pro"})
    assert not _alerts()["ai-used-up"]["upgrade"]


def test_another_usage_limit_is_not_the_plan(store):
    pause._until = pause._now().replace(year=2999)
    pause._reason = "the model provider is rate limiting"
    assert pause.limit() == ""
    assert "model-paused" in _alerts() and "ai-used-up" not in _alerts()


@pytest.fixture
def full_relay(store, monkeypatch):
    base, server, thread = _serve(
        create_relay(store / "relay", secret="test-secret", quota_bytes=1)
    )
    _configure(base, monkeypatch)
    monkeypatch.setattr(account, "signed_in", lambda: True)
    yield
    server.should_exit = True
    thread.join(timeout=5)


def test_a_full_sync_keeps_the_change_owed_and_says_so(full_relay):
    aid = notes.create(body="written once the plan was full")["artifact"]["id"]
    client.push_artifact(aid)

    assert aid in client._unpushed()
    assert settings.get("account_sync_full") is True
    assert [e for e in events.recent(20) if e["kind"] == "sync.full"]
    alert = _alerts()["sync-full"]
    assert alert["upgrade"] and alert["tab"] == "sync"

    # Once there is room, the next push goes up and the warning goes.
    client._note_full(False)
    assert "sync-full" not in _alerts()


def test_sync_close_to_full_is_said_before_it_is(store, monkeypatch):
    monkeypatch.setattr(account, "signed_in", lambda: True)
    settings.update({"account_storage_bytes": 1000, "account_used_bytes": 790})
    assert "sync-nearly-full" not in _alerts()
    settings.update({"account_used_bytes": 850})
    assert _alerts()["sync-nearly-full"]["upgrade"]
    settings.update({"account_used_bytes": 1000})
    assert "sync-full" in _alerts() and "sync-nearly-full" not in _alerts()


def test_a_second_computer_is_refused_with_the_way_to_pro(world):  # noqa: F811
    relay = world["relay"]
    pair = relay.post("/auth/google", json={"id_token": _token(aud=GOOGLE_DESKTOP, sub="g-c1")})
    access = pair.json()["access_token"]
    other = relay.post(
        "/account/devices",
        json={"name": "Work Mac", "kind": "computer"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert other.status_code == 201

    keyring_file.initialize()
    engine = world["engine"]
    url = engine.post("/account/sign-in", json={"provider": "google"}).json()["url"]
    from tests.test_account import _query

    engine.get("/account/google/callback", params={"code": "c1", "state": _query(url)["state"]})

    me = engine.get("/account").json()
    assert not me["signed_in"]
    assert me["sign_in"]["state"] == "failed" and me["sign_in"]["limit"] == "computers"
    assert "Upgrade" in me["sign_in"]["error"]
    assert me["plan"]["checkout_url"].startswith("https://pay.rev.cat/abc123/")
