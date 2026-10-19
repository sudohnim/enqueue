"""The hosted relay's accounts: Google and Apple sign-in, sessions, device tokens.

Google's and Apple's signing keys are replaced by one this test makes, so a token is
signed exactly as the provider would sign it, and a forged one is exactly what a
stranger could write. The account database is SQLite here, Postgres when hosted.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from enqueue.relay import accounts as accounts_mod
from enqueue.relay.accounts import AccountSettings
from enqueue.relay.app import create_relay

GOOGLE_WEB = "web-client.apps.googleusercontent.com"
GOOGLE_DESKTOP = "desktop-client.apps.googleusercontent.com"
APPLE_SERVICE = "com.sudohnim.enqueue.signin"

PROVIDER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
STRANGER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(
    *,
    iss="https://accounts.google.com",
    aud=GOOGLE_WEB,
    sub="google-user-1",
    email="minh@example.com",
    exp_in=600,
    key=PROVIDER_KEY,
):
    now = int(time.time())
    return jwt.encode(
        {"iss": iss, "aud": aud, "sub": sub, "email": email, "iat": now, "exp": now + exp_in},
        key,
        algorithm="RS256",
    )


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
        apple_client_id=APPLE_SERVICE,
        rate_limit_per_min=1000,
    )
    app = create_relay(tmp_path / "relay", secret="first-library-secret", account_settings=settings)
    return TestClient(app)


def _sign_in(client, **kw):
    resp = client.post("/auth/google", json={"id_token": _token(**kw)})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_a_google_sign_in_makes_one_account_and_signs_in_again_to_it(relay):
    first = _sign_in(relay)
    again = _sign_in(relay)
    assert first["account"]["id"] == again["account"]["id"]
    assert first["account"]["email"] == "minh@example.com"
    me = relay.get("/account", headers=_bearer(first["access_token"])).json()
    assert me["provider"] == "google" and me["devices"] == [] and not me["has_library"]


@pytest.mark.parametrize(
    "bad",
    [
        {"key": STRANGER_KEY},  # forged: not signed by Google
        {"aud": "someone-elses-app.apps.googleusercontent.com"},  # another app's token
        {"iss": "https://evil.example"},
        {"exp_in": -60},  # expired
    ],
)
def test_a_token_google_did_not_issue_to_us_is_refused(relay, bad):
    resp = relay.post("/auth/google", json={"id_token": _token(**bad)})
    assert resp.status_code == 401


def test_apple_tokens_for_the_services_id_or_the_app_both_count(relay):
    for aud in (APPLE_SERVICE, "com.sudohnim.enqueue"):
        tok = _token(iss="https://appleid.apple.com", aud=aud, sub="apple-1", email=None)
        resp = relay.post("/auth/apple", json={"identity_token": tok, "user_name": "Minh"})
        assert resp.status_code == 200, resp.text
    other = _token(iss="https://appleid.apple.com", aud="com.other.app", sub="apple-1")
    assert relay.post("/auth/apple", json={"identity_token": other}).status_code == 401


def test_sign_in_is_refused_until_its_clients_are_set_up(tmp_path, monkeypatch):
    monkeypatch.setattr(
        accounts_mod.Accounts, "_signing_key", lambda self, token, url: PROVIDER_KEY.public_key()
    )
    settings = AccountSettings(
        database_url=f"sqlite:///{tmp_path / 'a.db'}", jwt_secret="x" * 40, environment="test"
    )
    client = TestClient(create_relay(tmp_path / "r", secret="s" * 30, account_settings=settings))
    assert client.post("/auth/google", json={"id_token": _token()}).status_code == 503


def test_production_will_not_start_on_a_weak_jwt_secret(tmp_path):
    settings = AccountSettings(database_url=f"sqlite:///{tmp_path / 'a.db'}")
    settings.environment = "production"
    with pytest.raises(RuntimeError):
        create_relay(tmp_path / "r", secret="s" * 30, account_settings=settings)


def test_refresh_swaps_the_token_and_logout_ends_the_session(relay):
    pair = _sign_in(relay)
    swapped = relay.post("/auth/refresh", json={"refresh_token": pair["refresh_token"]})
    assert swapped.status_code == 200
    # A retry of a lost reply still works within the grace period.
    assert (
        relay.post("/auth/refresh", json={"refresh_token": pair["refresh_token"]}).status_code
        == 200
    )
    new = swapped.json()["refresh_token"]
    assert relay.post("/auth/logout", json={"refresh_token": new}).status_code == 204
    assert relay.post("/auth/refresh", json={"refresh_token": new}).status_code == 401
    # An access token is never a refresh token.
    assert (
        relay.post("/auth/refresh", json={"refresh_token": pair["access_token"]}).status_code == 401
    )


def test_a_device_token_opens_only_its_accounts_library_until_cancelled(relay):
    mine = _sign_in(relay)
    theirs = _sign_in(relay, sub="google-user-2", email="other@example.com")

    phone = relay.post(
        "/account/devices", json={"name": "Pixel"}, headers=_bearer(mine["access_token"])
    ).json()
    mac = relay.post(
        "/account/devices", json={"name": "Mac"}, headers=_bearer(mine["access_token"])
    ).json()
    other = relay.post(
        "/account/devices", json={"name": "Pixel"}, headers=_bearer(theirs["access_token"])
    ).json()
    assert phone["library_id"] == mac["library_id"] != other["library_id"]

    put = relay.put(
        "/sync/object/lib/vault.enc", content=b"mine", headers=_bearer(phone["relay_token"])
    )
    assert put.status_code == 201
    assert (
        relay.get("/sync/object/lib/vault.enc", headers=_bearer(mac["relay_token"])).content
        == b"mine"
    )
    assert (
        relay.get("/sync/object/lib/vault.enc", headers=_bearer(other["relay_token"])).status_code
        == 404
    )
    # The relay's first library (a plain secret) is not the account's.
    assert (
        relay.get("/sync/object/lib/vault.enc", headers=_bearer("first-library-secret")).status_code
        == 404
    )

    # Cancel the phone: its token stops at once; the Mac's keeps working.
    gone = relay.delete(
        f"/account/devices/{phone['device_id']}", headers=_bearer(mine["access_token"])
    )
    assert gone.status_code == 204
    assert relay.get("/sync/objects", headers=_bearer(phone["relay_token"])).status_code == 401
    assert relay.get("/sync/objects", headers=_bearer(mac["relay_token"])).status_code == 200
    # Nobody cancels someone else's device.
    assert (
        relay.delete(
            f"/account/devices/{other['device_id']}", headers=_bearer(mine["access_token"])
        ).status_code
        == 404
    )


def test_deleting_the_account_shuts_its_library(relay):
    pair = _sign_in(relay)
    mac = relay.post(
        "/account/devices", json={"name": "Mac"}, headers=_bearer(pair["access_token"])
    ).json()
    assert relay.delete("/account", headers=_bearer(pair["access_token"])).status_code == 204
    assert relay.get("/sync/objects", headers=_bearer(mac["relay_token"])).status_code == 401
    assert relay.get("/account", headers=_bearer(pair["access_token"])).status_code == 401


def test_without_a_database_the_relay_has_no_accounts(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(create_relay(tmp_path, secret="s" * 30))
    assert client.post("/auth/google", json={"id_token": "x"}).status_code == 404
