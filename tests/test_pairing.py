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

from enqueue.relay.app import create_relay
from enqueue.sync import pairing


def _client(tmp_path, secret="test-secret"):
    return TestClient(create_relay(tmp_path, secret=secret))


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
