"""Enqueue sync from the Mac's side (account.py): sign in with Google or Apple in the
browser, come back to the engine, and end up syncing with a device token of its own.

The relay here is the real one (relay/app.py with accounts on, SQLite), reached through a
TestClient; Google's and Apple's signing keys are replaced by one this file makes, as in
test_relay_accounts.py. Nothing touches the network or the real Keychain.
"""

from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from enqueue import account, config, keyring, keyring_file, settings
from enqueue.api.app import create_app
from enqueue.relay import accounts as accounts_mod
from enqueue.relay.accounts import AccountSettings
from enqueue.relay.app import create_relay
from tests.test_relay_accounts import APPLE_SERVICE, GOOGLE_DESKTOP, PROVIDER_KEY, _token

HOSTED = "https://relay.test"


@pytest.fixture
def world(store, tmp_path, monkeypatch):
    # A Keychain in a dict: every service account.py and the sync code use.
    vault: dict[str, str] = {}
    monkeypatch.setattr(keyring, "_get", lambda service: vault.get(service))
    monkeypatch.setattr(
        keyring, "_set", lambda service, value, noun="key": vault.update({service: value})
    )
    monkeypatch.setattr(keyring, "_clear", lambda service: vault.pop(service, None) is not None)

    monkeypatch.setattr(
        accounts_mod.Accounts, "_signing_key", lambda self, t, u: PROVIDER_KEY.public_key()
    )
    monkeypatch.setattr(
        accounts_mod.Accounts,
        "google_desktop_code",
        lambda self, code, verifier, redirect: _token(aud=GOOGLE_DESKTOP, sub="g-" + code),
    )
    relay_app = create_relay(
        tmp_path / "relay",
        secret="first-library-secret",
        account_settings=AccountSettings(
            database_url=f"sqlite:///{tmp_path / 'accounts.db'}",
            jwt_secret="x" * 40,
            environment="test",
            google_client_id="web.apps.googleusercontent.com",
            google_desktop_client_id=GOOGLE_DESKTOP,
            apple_client_id=APPLE_SERVICE,
            rate_limit_per_min=1000,
        ),
    )
    relay = TestClient(relay_app, base_url=HOSTED)
    monkeypatch.setattr(config, "HOSTED_RELAY_URL", HOSTED)
    monkeypatch.setattr(account, "_client", lambda: TestClient(relay_app, base_url=HOSTED))
    account._access.update(token=None, until=0.0)
    account._pending.clear()

    # Turning sync on reaches the relay through the sync client; here it only records.
    enabled: list[tuple[str, str]] = []

    def _enable(secret, relay_url=None):
        keyring.sync_secret_set(secret)
        settings.update({"sync_relay_url": relay_url})
        enabled.append((secret, relay_url))

    monkeypatch.setattr("enqueue.sync.enable.enable", _enable)
    # A settings change pushes the settings to the relay in the background: no network here.
    monkeypatch.setattr(settings, "_resync_to_relay", lambda: None)
    keyring_file.initialize()
    engine = TestClient(create_app(), base_url="http://127.0.0.1:8787")
    return {"engine": engine, "relay": relay, "vault": vault, "enabled": enabled}


def _query(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def _sign_in_google(engine) -> None:
    url = engine.post("/account/sign-in", json={"provider": "google"}).json()["url"]
    q = _query(url)
    page = engine.get("/account/google/callback", params={"code": "c1", "state": q["state"]})
    assert page.status_code == 200, page.text


def test_google_sign_in_ends_with_this_mac_syncing_on_a_token_of_its_own(world):
    engine = world["engine"]
    url = engine.post("/account/sign-in", json={"provider": "google"}).json()["url"]
    q = _query(url)
    assert url.startswith("https://accounts.google.com/")
    assert q["client_id"] == config.GOOGLE_DESKTOP_CLIENT_ID
    assert q["code_challenge_method"] == "S256" and q["code_challenge"]
    assert q["redirect_uri"] == "http://127.0.0.1:8787/account/google/callback"
    assert engine.get("/account").json()["sign_in"]["state"] == "waiting"

    page = engine.get("/account/google/callback", params={"code": "c1", "state": q["state"]})
    assert page.status_code == 200 and "signed in" in page.text.lower()

    me = engine.get("/account").json()
    assert me["signed_in"] and me["email"] == "minh@example.com" and me["provider"] == "google"
    assert me["sign_in"]["state"] == "done"
    token, relay_url = world["enabled"][-1]
    assert token.startswith("enqd_") and relay_url == HOSTED
    assert world["vault"][keyring.SESSION_SERVICE]  # the session, in the Keychain
    # The token opens the account's library on the relay.
    assert (
        world["relay"]
        .get("/sync/objects", headers={"Authorization": f"Bearer {token}"})
        .status_code
        == 200
    )


def test_a_callback_this_mac_did_not_start_finishes_nothing(world):
    engine = world["engine"]
    page = engine.get("/account/google/callback", params={"code": "c1", "state": "made-up"})
    assert page.status_code == 400
    assert not engine.get("/account").json()["signed_in"]
    assert world["enabled"] == []
    # And a state is good once.
    url = engine.post("/account/sign-in", json={"provider": "google"}).json()["url"]
    state = _query(url)["state"]
    assert (
        engine.get("/account/google/callback", params={"code": "c1", "state": state}).status_code
        == 200
    )
    assert (
        engine.get("/account/google/callback", params={"code": "c1", "state": state}).status_code
        == 400
    )


def test_a_cancelled_sign_in_says_so_and_stops_waiting(world):
    engine = world["engine"]
    url = engine.post("/account/sign-in", json={"provider": "google"}).json()["url"]
    page = engine.get(
        "/account/google/callback", params={"error": "access_denied", "state": _query(url)["state"]}
    )
    assert page.status_code == 400
    me = engine.get("/account").json()
    assert not me["signed_in"] and me["sign_in"]["state"] == "failed"


def test_apple_sign_in_comes_back_through_the_relay_with_a_one_time_code(world):
    engine, relay = world["engine"], world["relay"]
    url = engine.post("/account/sign-in", json={"provider": "apple"}).json()["url"]
    q = _query(url)
    assert url.startswith("https://appleid.apple.com/auth/authorize")
    assert q["client_id"] == config.APPLE_SERVICES_ID
    assert q["redirect_uri"] == f"{HOSTED}/auth/apple/callback"
    handback = json.loads(base64.urlsafe_b64decode(q["state"] + "=" * (-len(q["state"]) % 4)))
    assert handback["r"] == "http://127.0.0.1:8787/account/apple/done"

    # Apple posts to the relay, which sends the browser back to this engine.
    apple = _token(
        iss="https://appleid.apple.com",
        aud=APPLE_SERVICE,
        sub="apple-7",
        email="m@privaterelay.appleid.com",
    )
    back = relay.post(
        "/auth/apple/callback",
        data={"id_token": apple, "state": q["state"]},
        follow_redirects=False,
    )
    assert back.status_code == 303
    target = urlparse(back.headers["location"])
    page = engine.get(target.path + "?" + target.query)
    assert page.status_code == 200, page.text
    me = engine.get("/account").json()
    assert me["signed_in"] and me["provider"] == "apple"


def test_sign_in_waits_for_the_librarys_key(world, monkeypatch):
    monkeypatch.setattr(keyring_file, "is_initialized", lambda: False)
    resp = world["engine"].post("/account/sign-in", json={"provider": "google"})
    assert resp.status_code == 409


def test_a_phones_code_gets_a_token_of_its_own_and_can_be_cancelled(world):
    engine, relay = world["engine"], world["relay"]
    _sign_in_google(engine)
    phone = engine.post("/account/device-token", json={"name": "Phone"}).json()["relay_token"]
    mac = world["enabled"][-1][0]
    assert phone != mac
    auth = {"Authorization": f"Bearer {phone}"}
    assert relay.put("/sync/object/lib/vault.enc", content=b"x", headers=auth).status_code == 201

    devices = engine.get("/account/devices").json()["devices"]
    assert {d["name"] for d in devices} >= {"Phone"}
    assert sum(d["this_mac"] for d in devices) == 1
    phone_id = next(d["id"] for d in devices if d["name"] == "Phone")
    mine = next(d["id"] for d in devices if d["this_mac"])
    assert engine.delete(f"/account/devices/{mine}").status_code == 400  # sign out instead
    assert engine.delete(f"/account/devices/{phone_id}").status_code == 200
    assert relay.get("/sync/objects", headers=auth).status_code == 401


def test_signing_out_stops_this_mac_and_cancels_its_token(world):
    engine, relay = world["engine"], world["relay"]
    _sign_in_google(engine)
    mac = world["enabled"][-1][0]
    me = engine.post("/account/sign-out").json()
    assert not me["signed_in"]
    assert keyring.sync_secret_get() is None and keyring.session_get() is None
    assert settings.get("sync_relay_url") == ""
    assert relay.get("/sync/objects", headers={"Authorization": f"Bearer {mac}"}).status_code == 401


def test_deleting_the_account_shuts_every_device_out(world):
    engine, relay = world["engine"], world["relay"]
    _sign_in_google(engine)
    phone = engine.post("/account/device-token", json={"name": "Phone"}).json()["relay_token"]
    assert engine.delete("/account").status_code == 200
    assert (
        relay.get("/sync/objects", headers={"Authorization": f"Bearer {phone}"}).status_code == 401
    )
    assert not engine.get("/account").json()["signed_in"]


def test_a_token_for_another_device_needs_a_sign_in(world):
    resp = world["engine"].post("/account/device-token", json={"name": "Phone"})
    assert resp.status_code == 502


def test_a_mac_on_its_own_relay_moves_its_library_into_the_account(world, monkeypatch):
    import time as _time

    from enqueue.sync import client as sync_client
    from enqueue.sync import worker as sync_worker

    engine = world["engine"]
    # Syncing through a relay of its own, part way through its pulls.
    settings.update({"sync_relay_url": "https://my-relay.example", "sync_backfill_done": True})
    keyring.sync_secret_set("my-own-relay-password-123456")
    sync_client._write_cursor(67811)
    pushed, restarted = [], []
    monkeypatch.setattr(sync_client, "push_everything", lambda: pushed.append(1) or 0)
    monkeypatch.setattr(sync_worker, "restart", lambda: restarted.append(1))

    _sign_in_google(engine)

    token, relay_url = world["enabled"][-1]
    assert token.startswith("enqd_") and relay_url == HOSTED
    assert keyring.sync_secret_get() == token  # the old password is no longer used
    assert sync_client._read_cursor() == 0  # the new library is pulled from its start
    assert restarted == [1]
    deadline = _time.time() + 5
    while not pushed and _time.time() < deadline:
        _time.sleep(0.05)
    assert pushed == [1]  # everything goes up, once
    me = engine.get("/account").json()
    assert me["signed_in"] and me["relink_phone"]

    # Making the phone's code is what the prompt waits for.
    engine.post("/account/device-token", json={"name": "Phone"})
    assert not engine.get("/account").json()["relink_phone"]


def test_a_signed_in_mac_does_not_start_a_second_sign_in(world):
    _sign_in_google(world["engine"])
    resp = world["engine"].post("/account/sign-in", json={"provider": "apple"})
    assert resp.status_code == 409


def test_the_google_picture_is_kept_on_this_mac_and_served(world, monkeypatch):
    import httpx

    engine = world["engine"]
    photo = b"\x89PNG fake"
    monkeypatch.setattr(
        accounts_mod.Accounts,
        "google_desktop_code",
        lambda self, code, verifier, redirect: _token(
            aud=GOOGLE_DESKTOP, sub="g-pic", picture="https://lh3.googleusercontent.com/a/x"
        ),
    )
    monkeypatch.setattr(
        account.httpx,
        "get",
        lambda url, **kw: httpx.Response(200, content=photo, headers={"content-type": "image/png"}),
    )
    _sign_in_google(engine)
    assert engine.get("/account").json()["picture"]
    got = engine.get("/account/picture")
    assert got.status_code == 200 and got.content == photo
    engine.post("/account/sign-out")
    assert engine.get("/account/picture").status_code == 404


def test_signing_in_again_only_renews_the_session_and_the_picture(world, monkeypatch):
    import httpx

    engine = world["engine"]
    _sign_in_google(engine)
    devices_before = engine.get("/account/devices").json()["devices"]
    token_before = keyring.sync_secret_get()
    monkeypatch.setattr(
        accounts_mod.Accounts,
        "google_desktop_code",
        lambda self, code, verifier, redirect: _token(
            aud=GOOGLE_DESKTOP, sub="g-" + code, picture="https://lh3.googleusercontent.com/a/y"
        ),
    )
    monkeypatch.setattr(
        account.httpx,
        "get",
        lambda url, **kw: httpx.Response(
            200, content=b"jpg", headers={"content-type": "image/jpeg"}
        ),
    )
    url = engine.post("/account/sign-in", json={"provider": "google", "refresh": True}).json()[
        "url"
    ]
    page = engine.get(
        "/account/google/callback", params={"code": "c1", "state": _query(url)["state"]}
    )
    assert page.status_code == 200, page.text
    assert engine.get("/account").json()["picture"]
    assert keyring.sync_secret_get() == token_before  # same device, sync untouched
    assert len(engine.get("/account/devices").json()["devices"]) == len(devices_before)


def test_signing_in_again_as_someone_else_is_refused(world):
    engine = world["engine"]
    _sign_in_google(engine)
    url = engine.post("/account/sign-in", json={"provider": "google", "refresh": True}).json()[
        "url"
    ]
    page = engine.get(
        "/account/google/callback", params={"code": "other", "state": _query(url)["state"]}
    )
    # The fake Google names the code as the subject: "g-other" is another account.
    assert page.status_code == 400 and "different account" in page.text
