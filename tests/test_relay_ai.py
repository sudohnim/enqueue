"""The assistant included with Enqueue sync (relay/ai.py): a pass-through to OpenRouter
under Enqueue's key, for a linked device, limited by plan and metered per month.

OpenRouter is replaced by an httpx MockTransport that records what reached it, so the
tests see exactly what Enqueue sends on and what it keeps.
"""

from __future__ import annotations

import time

import httpx
import pytest
from fastapi.testclient import TestClient

from enqueue import included_ai
from enqueue.relay import accounts as accounts_mod
from enqueue.relay.accounts import AccountSettings
from enqueue.relay.app import create_relay

from .test_relay_accounts import GOOGLE_WEB, PROVIDER_KEY, _bearer, _sign_in

HOOK = "Bearer hook"
FREE_MODEL = "anthropic/claude-haiku-5.5"
PRO_MODEL = "anthropic/claude-sonnet-5.5"


class FakeOpenRouter:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.auth: list[str] = []
        self.status = 200
        self.cost: float | None = 0.01

    def handler(self, request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        self.sent.append(body)
        self.auth.append(request.headers.get("authorization", ""))
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "upstream says no"}})
        usage = {"prompt_tokens": 1000, "completion_tokens": 200}
        if self.cost is not None:
            usage["cost"] = self.cost
        return httpx.Response(
            200,
            json={
                "id": "gen-1",
                "model": body["model"],
                "choices": [{"message": {"role": "assistant", "content": "hello"}}],
                "usage": usage,
            },
        )


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(
        accounts_mod.Accounts, "_signing_key", lambda self, token, url: PROVIDER_KEY.public_key()
    )
    fake = FakeOpenRouter()
    settings = AccountSettings(
        database_url=f"sqlite:///{tmp_path / 'accounts.db'}",
        jwt_secret="x" * 40,
        environment="test",
        google_client_id=GOOGLE_WEB,
        rate_limit_per_min=1000,
        revenuecat_webhook_auth=HOOK,
        openrouter_api_key="sk-or-enqueue",
    )
    app = create_relay(
        tmp_path / "relay",
        secret="first-library-secret",
        account_settings=settings,
        ai_client=httpx.Client(transport=httpx.MockTransport(fake.handler)),
    )
    relay = TestClient(app)
    pair = _sign_in(relay)
    phone = relay.post(
        "/account/devices",
        json={"name": "Phone", "kind": "phone"},
        headers=_bearer(pair["access_token"]),
    ).json()
    return relay, fake, pair, phone["relay_token"]


def _ask(relay, token, model=FREE_MODEL, **extra):
    return relay.post(
        "/ai/v1/chat/completions",
        json={"model": model, "messages": [{"role": "user", "content": "hi"}], **extra},
        headers=_bearer(token),
    )


def _pro(relay, pair):
    now = time.time()
    relay.post(
        "/webhooks/revenuecat",
        json={
            "event": {
                "type": "INITIAL_PURCHASE",
                "app_user_id": pair["account"]["id"],
                "entitlement_ids": ["pro"],
                "event_timestamp_ms": int(now * 1000),
                "expiration_at_ms": int((now + 86400 * 30) * 1000),
            }
        },
        headers={"Authorization": HOOK},
    )


def test_a_linked_device_asks_through_enqueues_key_and_the_cost_is_metered(world):
    relay, fake, pair, token = world
    resp = _ask(relay, token)
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "hello"
    assert fake.auth == ["Bearer sk-or-enqueue"]  # Enqueue's key, never the device token
    sent = fake.sent[0]
    assert sent["provider"]["data_collection"] == "deny"
    assert sent["usage"] == {"include": True}
    usage = relay.get("/account/plan", headers=_bearer(token)).json()["ai"]
    assert usage["used_usd"] == pytest.approx(0.01)
    assert usage["requests"] == 1
    assert usage["cap_usd"] == included_ai.MONTHLY_CAP_USD["free"]


def test_without_a_linked_device_nothing_reaches_openrouter(world):
    relay, fake, pair, _ = world
    assert _ask(relay, "enqd_not-a-device").status_code == 401
    assert _ask(relay, pair["access_token"]).status_code == 401  # a session is not a device
    assert fake.sent == []


def test_free_cannot_use_a_pro_model_and_pro_can(world):
    relay, fake, pair, token = world
    refused = _ask(relay, token, PRO_MODEL)
    assert refused.status_code == 403
    assert "Pro" in refused.json()["error"]["message"]
    assert _ask(relay, token, "anthropic/claude-opus-5.5").status_code == 403
    assert fake.sent == []
    _pro(relay, pair)
    assert _ask(relay, token, PRO_MODEL).status_code == 200


def test_a_spent_month_answers_429_until_next_month(world):
    relay, fake, pair, token = world
    fake.cost = included_ai.MONTHLY_CAP_USD["free"]
    assert _ask(relay, token).status_code == 200
    spent = _ask(relay, token)
    assert spent.status_code == 429
    assert int(spent.headers["retry-after"]) >= 60
    assert "Pro raises it" in spent.json()["error"]["message"]
    assert len(fake.sent) == 1


def test_a_reply_without_a_cost_is_priced_from_its_tokens(world):
    relay, fake, pair, token = world
    fake.cost = None
    _ask(relay, token)
    used = relay.get("/account/plan", headers=_bearer(token)).json()["ai"]["used_usd"]
    assert used == pytest.approx(included_ai.estimate_cost(FREE_MODEL, 1000, 200), abs=1e-4)


def test_enqueues_key_refused_upstream_is_an_outage_not_a_bad_key(world):
    relay, fake, pair, token = world
    fake.status = 401
    resp = _ask(relay, token)
    assert resp.status_code == 503  # a device must not tell its owner their key failed


def test_streaming_is_refused(world):
    relay, fake, pair, token = world
    assert _ask(relay, token, stream=True).status_code == 400
    assert fake.sent == []


def test_the_model_list_marks_what_the_plan_unlocks(world):
    relay, fake, pair, token = world
    listed = relay.get("/ai/v1/models", headers=_bearer(token)).json()
    allowed = {m["id"]: m["allowed"] for m in listed["data"]}
    assert allowed[FREE_MODEL] and not allowed[PRO_MODEL]
    assert listed["tier"] == "free"


def test_without_enqueues_key_the_assistant_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(
        accounts_mod.Accounts, "_signing_key", lambda self, token, url: PROVIDER_KEY.public_key()
    )
    settings = AccountSettings(
        database_url=f"sqlite:///{tmp_path / 'a.db'}",
        jwt_secret="x" * 40,
        environment="test",
        google_client_id=GOOGLE_WEB,
    )
    relay = TestClient(create_relay(tmp_path / "r", secret="s" * 30, account_settings=settings))
    pair = _sign_in(relay)
    token = relay.post(
        "/account/devices", json={"name": "Mac"}, headers=_bearer(pair["access_token"])
    ).json()["relay_token"]
    assert _ask(relay, token).status_code == 503
