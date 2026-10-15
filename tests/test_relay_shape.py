"""What the relay can learn from an object: its padded size and a hashed name (crypto.py).
desktop/src/sync.rs has the same functions; its test opens what these make."""

from __future__ import annotations

from enqueue import crypto

KEY = bytes([7]) * 32


def test_a_payload_round_trips_and_its_size_is_a_bucket():
    for n in (0, 1, 200, 244, 245, 3000, 70_000):
        sealed = crypto.seal_payload(b"x" * n, KEY)
        assert crypto.open_payload(sealed, KEY) == b"x" * n
        body = len(sealed) - 40  # nonce and tag
        assert body == crypto._bucket(n + 12)
    # Notes a few words apart land in the same bucket.
    assert len(crypto.seal_payload(b"a" * 20, KEY)) == len(crypto.seal_payload(b"a" * 200, KEY))


def test_an_older_unpadded_object_still_opens():
    assert crypto.open_payload(crypto.encrypt(b'{"old": true}', KEY), KEY) == b'{"old": true}'


def test_names_say_nothing_and_use_their_own_key():
    name = crypto.object_name("3f1c-artifact-id", KEY)
    assert "3f1c" not in name and len(name) == 40
    assert name == crypto.object_name("3f1c-artifact-id", KEY), "stable, so a push overwrites"
    assert crypto.blob_name("abc", KEY) != crypto.legacy_blob_name("abc", KEY)
    assert crypto.names_key(KEY) != KEY
