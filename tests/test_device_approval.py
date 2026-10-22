"""Device approval (sync/join.py, relay/accounts.py): a computer that signs in to an
account whose library already has a key asks to join, and one that holds the key
approves it. The key travels sealed to the asker's public key; the relay sees only the
public key and ciphertext; both screens show the same code from that public key.

The relay is the real one (SQLite) behind TestClients, as in test_account.py.
"""

from __future__ import annotations

import base64
import json
import time

import nacl.public
import pytest
from fastapi.testclient import TestClient

from enqueue import account, config, crypto, keyring, keyring_file, settings
from enqueue.api.app import create_app
from enqueue.relay import accounts as accounts_mod
from enqueue.relay.accounts import AccountSettings
from enqueue.relay.app import create_relay
from enqueue.sync import client as sync_client
from enqueue.sync import join
from tests.test_relay_accounts import GOOGLE_DESKTOP, PROVIDER_KEY, _bearer, _token

HOSTED = "https://relay.test"
WEB = "web.apps.googleusercontent.com"


def _relay_app(tmp_path):
    return create_relay(
        tmp_path / "relay",
        secret="first-library-secret",
        account_settings=AccountSettings(
            database_url=f"sqlite:///{tmp_path / 'accounts.db'}",
            jwt_secret="x" * 40,
            environment="test",
            google_client_id=WEB,
            google_desktop_client_id=GOOGLE_DESKTOP,
            rate_limit_per_min=1000,
        ),
    )


def _session(relay, sub="g-c1", email="minh@example.com"):
    resp = relay.post("/auth/google", json={"id_token": _token(aud=WEB, sub=sub, email=email)})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _device(relay, session, name, kind):
    resp = relay.post(
        "/account/devices", json={"name": name, "kind": kind}, headers=_bearer(session)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["relay_token"]


@pytest.fixture
def relay(tmp_path, monkeypatch):
    monkeypatch.setattr(
        accounts_mod.Accounts, "_signing_key", lambda self, t, u: PROVIDER_KEY.public_key()
    )
    return TestClient(_relay_app(tmp_path), base_url=HOSTED)


def _pub(key: nacl.public.PrivateKey) -> str:
    return base64.b64encode(bytes(key.public_key)).decode()


# ---- the relay's rules ----------------------------------------------------------------


def test_an_approval_is_sealed_to_the_asker_and_collected_once(relay):
    session = _session(relay)
    asker = _device(relay, session, "Work Mac", "computer")
    private = nacl.public.PrivateKey.generate()
    ask = relay.post("/account/joins", json={"public_key": _pub(private)}, headers=_bearer(asker))
    assert ask.status_code == 201
    jid = ask.json()["id"]

    listed = relay.get("/account/joins", headers=_bearer(session)).json()["joins"]
    assert [(j["id"], j["name"]) for j in listed] == [(jid, "Work Mac")]
    # The asker does not see its own ask, and cannot approve itself.
    assert relay.get("/account/joins", headers=_bearer(asker)).json()["joins"] == []
    selfish = relay.post(
        f"/account/joins/{jid}/approve", json={"sealed": "AAAA"}, headers=_bearer(asker)
    )
    assert selfish.status_code == 403

    public = base64.b64decode(listed[0]["public_key"])
    assert crypto.join_code(public) == crypto.join_code(bytes(private.public_key))
    dek = crypto.new_dek()
    sealed = base64.b64encode(crypto.seal_to(public, json.dumps({"dek": dek.hex()}).encode()))
    ok = relay.post(
        f"/account/joins/{jid}/approve", json={"sealed": sealed.decode()}, headers=_bearer(session)
    )
    assert ok.status_code == 204

    got = relay.get(f"/account/joins/{jid}", headers=_bearer(asker)).json()
    assert got["status"] == "approved"
    opened = json.loads(crypto.open_sealed(private, base64.b64decode(got["sealed"])))
    assert bytes.fromhex(opened["dek"]) == dek
    assert relay.get(f"/account/joins/{jid}", headers=_bearer(asker)).json() == {"status": "gone"}


def test_a_denied_ask_says_so_and_another_account_never_sees_it(relay):
    session = _session(relay)
    asker = _device(relay, session, "Work Mac", "computer")
    jid = relay.post(
        "/account/joins",
        json={"public_key": _pub(nacl.public.PrivateKey.generate())},
        headers=_bearer(asker),
    ).json()["id"]
    stranger = _session(relay, sub="g-other", email="someone@example.com")
    assert relay.get("/account/joins", headers=_bearer(stranger)).json()["joins"] == []
    assert (
        relay.post(
            f"/account/joins/{jid}/approve", json={"sealed": "AAAA"}, headers=_bearer(stranger)
        ).status_code
        == 404
    )
    assert relay.post(f"/account/joins/{jid}/deny", headers=_bearer(session)).status_code == 204
    assert relay.get(f"/account/joins/{jid}", headers=_bearer(asker)).json()["status"] == "denied"


def test_an_ask_needs_a_real_public_key_and_a_live_device(relay):
    session = _session(relay)
    asker = _device(relay, session, "Work Mac", "computer")
    bad = relay.post("/account/joins", json={"public_key": "c2hvcnQ="}, headers=_bearer(asker))
    assert bad.status_code == 400
    nobody = relay.post(
        "/account/joins",
        json={"public_key": _pub(nacl.public.PrivateKey.generate())},
        headers=_bearer("enqd_made-up"),
    )
    assert nobody.status_code == 401


def test_an_ask_runs_out(relay, monkeypatch):
    session = _session(relay)
    asker = _device(relay, session, "Work Mac", "computer")
    jid = relay.post(
        "/account/joins",
        json={"public_key": _pub(nacl.public.PrivateKey.generate())},
        headers=_bearer(asker),
    ).json()["id"]
    later = time.time() + accounts_mod.JOIN_TTL_S + 5
    monkeypatch.setattr(accounts_mod.time, "time", lambda: later)
    assert relay.get("/account/joins", headers=_bearer(session)).json()["joins"] == []
    assert relay.get(f"/account/joins/{jid}", headers=_bearer(asker)).json()["status"] == "expired"


# ---- the Mac: sign in, ask, get approved ------------------------------------------------


@pytest.fixture
def mac(store, tmp_path, monkeypatch):
    """A Mac with no library key yet, signing in to the account through the engine."""
    vault: dict[str, str] = {}
    monkeypatch.setattr(keyring, "_get", lambda service, strict=False: vault.get(service))
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
    relay_app = _relay_app(tmp_path)
    relay = TestClient(relay_app, base_url=HOSTED)
    monkeypatch.setattr(config, "HOSTED_RELAY_URL", HOSTED)
    monkeypatch.setattr(account, "_client", lambda: TestClient(relay_app, base_url=HOSTED))
    monkeypatch.setattr(join, "_http", lambda: TestClient(relay_app, base_url=HOSTED))
    monkeypatch.setattr(join, "POLL_S", 0.05)
    account._access.update(token=None, until=0.0)
    account._pending.clear()
    join.cancel()

    enabled: list[str] = []

    def _enable(secret, relay_url=None):
        keyring.sync_secret_set(secret)
        settings.update({"sync_relay_url": relay_url})
        enabled.append(secret)

    monkeypatch.setattr("enqueue.sync.enable.enable", _enable)
    monkeypatch.setattr(settings, "_resync_to_relay", lambda: None)

    def _pull_keyring():
        token = keyring.sync_secret_get()
        got = relay.get("/sync/object/lib/keyring.enc", headers=_bearer(token))
        if got.status_code != 200:
            return False
        (config.DATA_DIR / "keyring.json").write_bytes(got.content)
        return True

    monkeypatch.setattr(sync_client, "pull_keyring", _pull_keyring)
    monkeypatch.setattr(sync_client, "pull", lambda: {"pulled": 0})
    engine = TestClient(create_app(), base_url="http://127.0.0.1:8787")
    yield {"engine": engine, "relay": relay, "enabled": enabled}
    join.cancel()


def _sign_in(engine, ok=True):
    url = engine.post("/account/sign-in", json={"provider": "google"}).json()["url"]
    state = url.split("state=")[1].split("&")[0]
    page = engine.get("/account/google/callback", params={"code": "c1", "state": state})
    if ok:
        assert page.status_code == 200, page.text


def _library_with_a_key(relay, session) -> tuple[bytes, bytes]:
    """The account's library as another device left it: a keyring on the relay, made
    the way a Mac makes one, and that Mac's key."""
    dek = crypto.new_dek()
    record = {
        "version": 2,
        "recovery_salt": "aa" * 16,
        "dek_by_recovery": crypto.wrap(dek, b"k" * 32).hex(),
    }
    phone = _device(relay, session, "Phone", "phone")
    body = json.dumps(record).encode()
    put = relay.put("/sync/object/lib/keyring.enc", content=body, headers=_bearer(phone))
    assert put.status_code == 201
    return dek, body


def _wait_for(pred, seconds=5.0):
    until = time.time() + seconds
    while time.time() < until:
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_a_new_mac_asks_to_join_and_gets_the_key_from_an_approval(mac):
    engine, relay = mac["engine"], mac["relay"]
    session = _session(relay)
    dek, _ = _library_with_a_key(relay, session)

    _sign_in(engine)
    me = engine.get("/account").json()
    assert me["sign_in"]["state"] == "join"
    assert me["join"]["state"] == "waiting" and len(me["join"]["code"]) == 7
    assert not keyring_file.is_initialized()  # no second key was made

    # The other computer: sees the ask with the same code, and approves it.
    listed = relay.get("/account/joins", headers=_bearer(session)).json()["joins"]
    public = base64.b64decode(listed[0]["public_key"])
    assert crypto.join_code(public) == me["join"]["code"]
    sealed = crypto.seal_to(public, json.dumps({"dek": dek.hex()}).encode())
    relay.post(
        f"/account/joins/{listed[0]['id']}/approve",
        json={"sealed": base64.b64encode(sealed).decode()},
        headers=_bearer(session),
    )

    assert _wait_for(lambda: engine.get("/account").json()["sign_in"]["state"] == "done")
    assert keyring_file.load_dek_from_keychain() == dek
    assert keyring_file.is_initialized() and mac["enabled"]


def test_the_engine_approves_with_the_key_it_holds(mac):
    engine, relay = mac["engine"], mac["relay"]
    keyring_file.initialize()  # this Mac is the one that holds the key
    _sign_in(engine)
    assert engine.get("/account").json()["sign_in"]["state"] == "done"

    session = _session(relay)
    work = _device(relay, session, "Work Mac", "phone")  # kind aside, any device may ask
    private = nacl.public.PrivateKey.generate()
    relay.post("/account/joins", json={"public_key": _pub(private)}, headers=_bearer(work))

    waiting = engine.get("/account/joins").json()["joins"]
    assert [j["name"] for j in waiting] == ["Work Mac"]
    assert waiting[0]["code"] == crypto.join_code(bytes(private.public_key))
    assert engine.post(f"/account/joins/{waiting[0]['id']}/approve").status_code == 200

    got = relay.get(f"/account/joins/{waiting[0]['id']}", headers=_bearer(work)).json()
    opened = json.loads(crypto.open_sealed(private, base64.b64decode(got["sealed"])))
    assert bytes.fromhex(opened["dek"]) == keyring_file.load_dek_from_keychain()


def test_the_first_mac_on_an_account_makes_the_key_after_signing_in(mac):
    engine = mac["engine"]
    _sign_in(engine)
    assert engine.get("/account").json()["sign_in"]["state"] == "needs_key"
    assert not mac["enabled"]
    assert engine.post("/settings/keyring-init", json={}).status_code == 200
    assert engine.post("/account/finish").json()["sign_in"]["state"] == "done"
    assert mac["enabled"]


def test_a_mac_with_another_librarys_key_is_refused_not_merged(mac):
    engine, relay = mac["engine"], mac["relay"]
    session = _session(relay)
    _library_with_a_key(relay, session)
    keyring_file.initialize()  # a key of its own, for a different library
    _sign_in(engine, ok=False)
    me = engine.get("/account").json()
    assert me["sign_in"]["state"] == "failed"
    assert "different" in me["sign_in"]["error"]
    assert not me["signed_in"]
    listed = relay.get("/account", headers=_bearer(session)).json()["devices"]
    names = [d["name"] for d in listed if not d.get("revoked_at")]
    assert names == ["Phone"]  # the device the refused sign-in made is gone
