"""Crypto building blocks (E2E.md Phase E1).

PyNaCl (libsodium) only - no hand-rolled primitives, no other crypto library.
XChaCha20-Poly1305 (SecretBox) for the box, Argon2id (MODERATE) for the key
derivation, and a keyed HMAC for the content-addressed blob name. DEC-D5: the
Argon2id preset is MODERATE, recorded here, not chosen elsewhere.
"""

from __future__ import annotations

import hashlib
import hmac

import nacl.pwhash
import nacl.secret
import nacl.utils

# DEC-D5: libsodium crypto_pwhash MODERATE.
OPSLIMIT = nacl.pwhash.argon2id.OPSLIMIT_MODERATE
MEMLIMIT = nacl.pwhash.argon2id.MEMLIMIT_MODERATE
DEK_BYTES = 32


def derive_kek(password: str, salt: bytes) -> bytes:
    """Argon2id (MODERATE) key derivation; 32-byte output."""
    return nacl.pwhash.argon2id.kdf(
        DEK_BYTES,
        password.encode("utf-8"),
        salt,
        opslimit=OPSLIMIT,
        memlimit=MEMLIMIT,
    )


def new_dek() -> bytes:
    """A fresh 32-byte data-encryption key."""
    return nacl.utils.random(DEK_BYTES)


def _seal(data: bytes, key: bytes) -> bytes:
    # SecretBox.encrypt prepends a fresh random nonce to the ciphertext.
    return nacl.secret.SecretBox(key).encrypt(data)


def _open(ciphertext: bytes, key: bytes) -> bytes:
    # SecretBox.decrypt raises CryptoError on a wrong key or a flipped byte.
    return nacl.secret.SecretBox(key).decrypt(ciphertext)


def wrap(dek: bytes, kek: bytes) -> bytes:
    """Wrap the DEK under a KEK (same box as encrypt; the KEK is the key)."""
    return _seal(dek, kek)


def unwrap(wrapped: bytes, kek: bytes) -> bytes:
    return _open(wrapped, kek)


def encrypt(plaintext: bytes, dek: bytes) -> bytes:
    return _seal(plaintext, dek)


def decrypt(ciphertext: bytes, dek: bytes) -> bytes:
    return _open(ciphertext, dek)


def blob_name(content_hash: str, dek: bytes) -> str:
    """Hex HMAC-SHA256 of `content_hash` keyed by the DEK.

    A plain content hash would let anyone with folder access test whether a
    known file is in the library; the keyed digest reveals nothing.
    """
    return hmac.new(dek, content_hash.encode("utf-8"), hashlib.sha256).hexdigest()
