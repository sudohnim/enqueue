"""Crypto building blocks (E2E.md Phase E1).

The load-bearing guarantee: XChaCha20-Poly1305 with a fresh random nonce per
call, Argon2id MODERATE, and a keyed HMAC for the blob name. Wrong-key and
tamper cases must raise, never return partial data.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import nacl.exceptions

from enqueue import crypto


def test_encrypt_then_decrypt_round_trips():
    dek = crypto.new_dek()
    assert crypto.decrypt(crypto.encrypt(b"hello", dek), dek) == b"hello"


def test_decrypt_with_a_wrong_key_raises():
    dek = crypto.new_dek()
    other = crypto.new_dek()
    ciphertext = crypto.encrypt(b"secret", dek)
    with pytest.raises(nacl.exceptions.CryptoError):
        crypto.decrypt(ciphertext, other)


def test_flipping_a_byte_makes_decrypt_raise():
    dek = crypto.new_dek()
    ciphertext = bytearray(crypto.encrypt(b"secret", dek))
    ciphertext[-1] ^= 0x01
    with pytest.raises(nacl.exceptions.CryptoError):
        crypto.decrypt(bytes(ciphertext), dek)


def test_encrypt_is_nondeterministic():
    dek = crypto.new_dek()
    assert crypto.encrypt(b"x", dek) != crypto.encrypt(b"x", dek)


def test_wrap_unwrap_round_trips_and_wrong_kek_raises():
    dek = crypto.new_dek()
    kek = crypto.derive_kek("password", b"0123456789abcdef")
    wrapped = crypto.wrap(dek, kek)
    assert crypto.unwrap(wrapped, kek) == dek

    other_kek = crypto.derive_kek("other", b"0123456789abcdef")
    with pytest.raises(nacl.exceptions.CryptoError):
        crypto.unwrap(wrapped, other_kek)


def test_derive_kek_is_deterministic_for_a_password_and_salt():
    salt = b"0123456789abcdef"
    assert crypto.derive_kek("pw", salt) == crypto.derive_kek("pw", salt)
    assert crypto.derive_kek("pw", salt) != crypto.derive_kek("pw2", salt)


def test_blob_name_is_stable_per_key_and_hides_the_hash():
    dek = crypto.new_dek()
    name = crypto.blob_name("some-content-hash", dek)
    assert name == crypto.blob_name("some-content-hash", dek)
    assert name != crypto.blob_name("some-content-hash", crypto.new_dek())
    assert "some-content-hash" not in name


@given(st.binary(min_size=0, max_size=4096))
@settings(max_examples=100, deadline=None)
def test_round_trip_property(data):
    dek = crypto.new_dek()
    assert crypto.decrypt(crypto.encrypt(data, dek), dek) == data
