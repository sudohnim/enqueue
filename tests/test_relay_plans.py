"""Enqueue sync's plans on the hosted relay: what free and Pro hold, how RevenueCat's
webhook moves an account between them, and how the limits are kept.

The phone buys Pro through RevenueCat with its account id as the RevenueCat user; the
webhook is the only thing that makes an account Pro besides the admin grant.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from enqueue.relay import accounts as accounts_mod
from enqueue.relay.accounts import GiB, AccountSettings
from enqueue.relay.app import create_relay

from .test_relay_accounts import GOOGLE_DESKTOP, GOOGLE_WEB, PROVIDER_KEY, _bearer, _sign_in

HOOK = "Bearer revenuecat-test-hook"


@pytest.fixture
def relay(tmp_path, monkeypatch):
    monkeypatch.setattr(
        accounts_mod.Accounts, "_signing_key", lambda self, token, url: PROVIDER_KEY.public_key()
    )
    settings = AccountSettings(
        database_url=f"sqlite:///{tmp_path / 'accounts.db'}",
        jwt_secret="x" * 40,
        environment="test",
        google_client_id=GOOGLE_WEB,
        google_desktop_client_id=GOOGLE_DESKTOP,
        rate_limit_per_min=1000,
        revenuecat_webhook_auth=HOOK,
    )
    app = create_relay(
        tmp_path / "relay",
        secret="first-library-secret",
        admin_secret="admin-secret",
        account_settings=settings,
    )
    return TestClient(app)


def _device(relay, pair, name, kind):
    return relay.post(
        "/account/devices", json={"name": name, "kind": kind}, headers=_bearer(pair["access_token"])
    )


def _event(account_id, kind="INITIAL_PURCHASE", expires_in=30 * 86400, at=None, **extra):
    now = time.time()
    event = {
        "type": kind,
        "app_user_id": account_id,
        "entitlement_ids": ["pro"],
        "event_timestamp_ms": int((at or now) * 1000),
        "expiration_at_ms": None if expires_in is None else int((now + expires_in) * 1000),
        **extra,
    }
    return {"api_version": "1.0", "event": event}


def _hook(relay, body, auth=HOOK):
    return relay.post("/webhooks/revenuecat", json=body, headers={"Authorization": auth})


def _plan(relay, pair):
    return relay.get("/account/plan", headers=_bearer(pair["access_token"])).json()


def test_a_new_account_is_free_with_one_computer_one_phone_and_a_gigabyte(relay):
    pair = _sign_in(relay)
    plan = _plan(relay, pair)
    assert plan["tier"] == "free"
    assert plan["limits"] == {"computers": 1, "phones": 1, "storage_bytes": 1 * GiB}
    assert plan["account_id"] == pair["account"]["id"]


def test_free_refuses_a_second_computer_and_pro_takes_it(relay):
    pair = _sign_in(relay)
    assert _device(relay, pair, "Mac", "computer").status_code == 201
    second = _device(relay, pair, "Other Mac", "computer")
    assert second.status_code == 402
    assert "one computer" in second.json()["detail"]
    assert _hook(relay, _event(pair["account"]["id"])).json()["tier"] == "pro"
    assert _device(relay, pair, "Other Mac", "computer").status_code == 201


def test_a_new_phone_replaces_the_old_one_only_once_it_syncs(relay):
    pair = _sign_in(relay)
    old = _device(relay, pair, "Phone", "phone").json()
    assert relay.get("/sync/objects", headers=_bearer(old["relay_token"])).status_code == 200
    new = _device(relay, pair, "Phone", "phone").json()
    # A code shown and not scanned yet cuts nobody off.
    assert relay.get("/sync/objects", headers=_bearer(old["relay_token"])).status_code == 200
    assert relay.get("/sync/objects", headers=_bearer(new["relay_token"])).status_code == 200
    assert relay.get("/sync/objects", headers=_bearer(old["relay_token"])).status_code == 401


def test_the_webhook_refuses_anyone_but_revenuecat(relay):
    pair = _sign_in(relay)
    assert _hook(relay, _event(pair["account"]["id"]), auth="Bearer guess").status_code == 401
    assert _hook(relay, _event(pair["account"]["id"]), auth="").status_code == 401
    assert _plan(relay, pair)["tier"] == "free"


def test_the_webhook_is_closed_while_unset(tmp_path, monkeypatch):
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
    assert _hook(relay, _event(pair["account"]["id"]), auth="").status_code == 401


def test_cancelling_keeps_pro_to_the_end_of_the_period_and_expiry_ends_it(relay):
    pair = _sign_in(relay)
    account = pair["account"]["id"]
    _hook(relay, _event(account))
    _hook(relay, _event(account, "CANCELLATION", expires_in=5 * 86400))
    assert _plan(relay, pair)["tier"] == "pro"
    _hook(relay, _event(account, "EXPIRATION", expires_in=-60))
    assert _plan(relay, pair)["tier"] == "free"


def test_a_refund_ends_pro_at_once(relay):
    # RevenueCat sends a refund as a cancellation whose expiry is now.
    pair = _sign_in(relay)
    account = pair["account"]["id"]
    _hook(relay, _event(account))
    _hook(relay, _event(account, "CANCELLATION", expires_in=-1, cancel_reason="CUSTOMER_SUPPORT"))
    assert _plan(relay, pair)["tier"] == "free"


def test_a_late_older_event_never_undoes_a_newer_one(relay):
    pair = _sign_in(relay)
    account = pair["account"]["id"]
    _hook(relay, _event(account, "RENEWAL"))
    stale = _hook(relay, _event(account, "EXPIRATION", expires_in=-60, at=time.time() - 3600))
    assert stale.json()["ignored"] == "older event"
    assert _plan(relay, pair)["tier"] == "pro"


def test_events_about_other_entitlements_or_strangers_change_nothing(relay):
    pair = _sign_in(relay)
    account = pair["account"]["id"]
    other = _event(account)
    other["event"]["entitlement_ids"] = ["something-else"]
    assert _hook(relay, other).json()["ignored"]
    assert _hook(relay, _event("$RCAnonymousID:abc")).json()["ignored"] == "unknown user"
    assert _hook(relay, {"event": {"type": "TEST"}}).status_code == 200
    assert _plan(relay, pair)["tier"] == "free"


def test_pro_raises_the_librarys_storage_and_free_lowers_it_again(relay):
    pair = _sign_in(relay)
    account = pair["account"]["id"]
    phone = _device(relay, pair, "Phone", "phone").json()
    _hook(relay, _event(account))
    assert _plan(relay, pair)["limits"]["storage_bytes"] == 50 * GiB
    _hook(relay, _event(account, "EXPIRATION", expires_in=-60))
    assert _plan(relay, pair)["limits"]["storage_bytes"] == 1 * GiB
    put = relay.put("/sync/object/x", content=b"abc", headers=_bearer(phone["relay_token"]))
    assert put.status_code == 201
    assert _plan(relay, pair)["used_bytes"] == 3


def test_the_phone_asks_for_its_plan_with_its_device_token(relay):
    pair = _sign_in(relay)
    phone = _device(relay, pair, "Phone", "phone").json()
    plan = relay.get("/account/plan", headers=_bearer(phone["relay_token"]))
    assert plan.status_code == 200
    assert plan.json()["account_id"] == pair["account"]["id"]
    assert relay.get("/account/plan", headers=_bearer("enqd_nope")).status_code == 401


def test_a_transfer_moves_the_pro_time_to_the_other_account(relay):
    first = _sign_in(relay)
    second = _sign_in(relay, sub="google-user-2", email="other@example.com")
    _hook(relay, _event(first["account"]["id"]))
    _hook(
        relay,
        {
            "event": {
                "type": "TRANSFER",
                "transferred_from": [first["account"]["id"]],
                "transferred_to": [second["account"]["id"]],
            }
        },
    )
    assert _plan(relay, first)["tier"] == "free"
    assert _plan(relay, second)["tier"] == "pro"


def test_the_admin_grants_pro_by_email_and_takes_it_back(relay):
    pair = _sign_in(relay)
    admin = {"Authorization": "Bearer admin-secret"}
    granted = relay.put("/admin/accounts/pro", json={"email": "MINH@example.com"}, headers=admin)
    assert granted.status_code == 200
    assert _plan(relay, pair)["tier"] == "pro"
    relay.put("/admin/accounts/pro", json={"email": "minh@example.com", "days": 0}, headers=admin)
    assert _plan(relay, pair)["tier"] == "free"
    nobody = relay.put("/admin/accounts/pro", json={"email": "x@y.z"}, headers=admin)
    assert nobody.status_code == 404
    bad = {"Authorization": "Bearer nope"}
    assert relay.put("/admin/accounts/pro", json={"email": "x"}, headers=bad).status_code == 401
