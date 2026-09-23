"""Device pairing (PAIR.1): hand a library to a new device over the relay with no recovery
phrase and no plaintext key on the wire.

Two layers are tested here:
  - the sealed envelope (Argon2id KEK from the phrase), which must round-trip and must NOT
    open under a wrong phrase; and
  - the relay's one-time pairing endpoints, which must let an UNAUTHENTICATED device fetch
    the envelope exactly once (the id is a capability), while the upload stays authenticated.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from enqueue import keyring, settings
from enqueue.relay.app import create_relay
from enqueue.sync import client, pairing
from enqueue.sync import worker as sync_worker


def _client(tmp_path, secret="test-secret"):
    return TestClient(create_relay(tmp_path, secret=secret))


class _FakeResp:
    def __init__(self, status, content=b""):
        self.status_code = status
        self.content = content


class _FakeHTTP:
    """Minimal httpx.Client stand-in: returns a canned response for get/put."""

    def __init__(self, get_resp=None, put_resp=None):
        self._get = get_resp
        self._put = put_resp

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, **kw):
        return self._get

    def put(self, url, **kw):
        return self._put


def _auth(secret="test-secret"):
    return {"Authorization": f"Bearer {secret}"}


# --- the sealed envelope -----------------------------------------------------------------


def test_envelope_round_trips():
    payload = {"relay": "https://r.example", "secret": "s3cr3t", "dek": "ab" * 32}
    env = pairing.seal_envelope(payload, "PHRASE12345")
    assert pairing.open_envelope(env, "PHRASE12345") == payload


def test_envelope_tolerates_retyped_phrase_formatting():
    # The phrase is Crockford base32; a user who retypes it with spaces, dashes, or in
    # lower case must still open the envelope.
    env = pairing.seal_envelope({"k": "v"}, "ABCD2345")
    assert pairing.open_envelope(env, "  abcd-2345 ") == {"k": "v"}


def test_wrong_phrase_does_not_open():
    env = pairing.seal_envelope({"dek": "00" * 32}, "RIGHTPHRASE")
    try:
        pairing.open_envelope(env, "WRONGPHRASE")
    except pairing.PairingError:
        pass
    else:
        raise AssertionError("a wrong phrase must not open the envelope")


def test_truncated_envelope_is_rejected():
    try:
        pairing.open_envelope(b"tooshort", "PHRASE")
    except pairing.PairingError:
        pass
    else:
        raise AssertionError("a malformed envelope must be rejected")


# --- the relay pairing endpoints ---------------------------------------------------------


def test_pairing_upload_is_authenticated_fetch_is_not(tmp_path):
    client = _client(tmp_path)
    pid = "abcdefghijklmnop1234"  # matches the relay id pattern
    body = b"\x00\x01sealed-envelope-bytes\xff"

    # The main device (which HAS the secret) uploads the envelope.
    put = client.put(f"/pair/{pid}", content=body, headers=_auth())
    assert put.status_code == 201

    # The joining device fetches by id WITHOUT the secret and gets the bytes back.
    got = client.get(f"/pair/{pid}")
    assert got.status_code == 200
    assert got.content == body


def test_pairing_is_one_time(tmp_path):
    client = _client(tmp_path)
    pid = "onetimeonetime123456"
    client.put(f"/pair/{pid}", content=b"envelope", headers=_auth())

    assert client.get(f"/pair/{pid}").status_code == 200
    # Consumed on first fetch: a second fetch (a replay, or a relay-side snoop after the
    # real device claimed it) finds nothing.
    assert client.get(f"/pair/{pid}").status_code == 404


def test_pairing_upload_requires_the_secret(tmp_path):
    client = _client(tmp_path)
    r = client.put("/pair/needsecret1234567890", content=b"x")  # no auth header
    assert r.status_code == 401


def test_pairing_rejects_a_malformed_id(tmp_path):
    client = _client(tmp_path)
    assert client.put("/pair/short", content=b"x", headers=_auth()).status_code == 400
    assert client.get("/pair/short").status_code == 400


def test_unknown_pairing_id_is_404(tmp_path):
    client = _client(tmp_path)
    assert client.get("/pair/doesnotexist12345678").status_code == 404


# --- the claim flow (imports the key AND starts the sync worker) -------------------------


def test_claim_imports_key_and_starts_the_worker(store, monkeypatch):
    """The end-to-end regression: a claimed pairing must import the secret + DEK AND start
    the background sync worker. The worker start is the fix for a paired device that would
    not auto-sync (pull deletes/edits) until the app was restarted, because start() no-op'd
    at boot when no relay was configured yet."""
    dek = bytes(range(32))
    envelope = pairing.seal_envelope(
        {"relay": "https://relay.example", "secret": "libsecret", "dek": dek.hex()},
        "PAIRPHRASE1234",
    )

    # No real relay/keychain: the GET returns the sealed envelope, the keyring pull is a
    # no-op success, and the data pull returns nothing.
    monkeypatch.setattr(
        pairing.httpx, "Client", lambda *a, **k: _FakeHTTP(get_resp=_FakeResp(200, envelope))
    )
    monkeypatch.setattr(client, "pull_keyring", lambda: True)
    monkeypatch.setattr(client, "pull", lambda: {"pulled": 0})
    saved = {}
    monkeypatch.setattr(keyring, "sync_secret_set", lambda s: saved.__setitem__("secret", s))
    monkeypatch.setattr(keyring, "sync_secret_get", lambda: saved.get("secret"))
    started = {"n": 0}
    monkeypatch.setattr(sync_worker, "start", lambda: started.__setitem__("n", started["n"] + 1))

    out = pairing.claim_offer("https://relay.example", "pairingid1234567890", "pairphrase1234")

    assert started["n"] == 1, "claim must start the sync worker so the device auto-syncs"
    assert saved["secret"] == "libsecret"
    assert keyring._dek_get() == dek  # the DEK handed over was stored (store fixture -> file)
    assert settings.get("sync_relay_url") == "https://relay.example"
    assert isinstance(out, dict)


def test_claim_refuses_when_a_keyring_already_exists(store, monkeypatch):
    """Claiming onto a device that already has a library would orphan its DEK - refuse."""
    (store / "keyring.json").write_text("{}")  # makes keyring_file.is_initialized() true
    monkeypatch.setattr(sync_worker, "start", lambda: None)
    try:
        pairing.claim_offer("https://relay.example", "pairingid1234567890", "phrase")
    except pairing.PairingError as exc:
        assert "already has a sync keyring" in str(exc)
    else:
        raise AssertionError("claim must refuse when a keyring already exists")


# --- the worker start() contract the config paths rely on --------------------------------


def test_worker_start_is_noop_without_a_relay(monkeypatch):
    monkeypatch.setattr(sync_worker, "_threads", [])
    monkeypatch.setattr(sync_worker, "_relay_url", lambda: "")
    sync_worker.start()
    assert sync_worker._threads == [], "no relay -> no worker threads"


def test_worker_start_is_idempotent_when_configured(monkeypatch):
    monkeypatch.setattr(sync_worker, "_threads", [])
    monkeypatch.setattr(sync_worker, "_relay_url", lambda: "https://relay.example")
    spawned = []
    monkeypatch.setattr(sync_worker, "_spawn", lambda fn, name: spawned.append(name) or object())

    sync_worker.start()
    sync_worker.start()  # second call must not spawn a second set of threads
    assert spawned == ["sync-timer", "sync-sse"]
