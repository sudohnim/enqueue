"""Crypto building blocks (E2E.md Phase E1).

PyNaCl (libsodium) only - no hand-rolled primitives, no other crypto library.
XSalsa20-Poly1305 (libsodium's SecretBox) for the box, Argon2id (MODERATE) for the key
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
    """Hex HMAC-SHA256 of `content_hash` under the names key (`names_key`).

    A plain content hash would let anyone with folder access test whether a
    known file is in the library; the keyed digest reveals nothing.
    """
    return hmac.new(
        names_key(dek), b"blob:" + content_hash.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def legacy_blob_name(content_hash: str, dek: bytes) -> str:
    """The name blobs had before the names key (HMAC under the DEK itself): still
    fetched, for a blob nobody has pushed again since."""
    return hmac.new(dek, content_hash.encode("utf-8"), hashlib.sha256).hexdigest()


# ---- what goes to the relay -------------------------------------------------------
# A relay object's size and name are all the relay learns about it, so both are made
# to say little. A payload is padded before it is sealed (`seal_payload`): a marker,
# its true length, then zeros to the next power of two from 256 bytes, and to the next
# multiple of 64 KiB past that, so a note's size is a bucket, not a word count. An
# object's name hashes its id under a key of its own (`names_key`), never the DEK
# itself, so the key that encrypts never also names. `open_payload` reads an older
# unpadded object as it is. Keep in step with `seal_payload`/`open_payload`/`names_key`
# in desktop/src/sync.rs. Vault sealing and key wraps use encrypt/_seal: never padded.

_PAD = b"\x00ENQPAD1"
_BIG = 64 * 1024


def _bucket(n: int) -> int:
    if n > _BIG:
        return -(-n // _BIG) * _BIG
    size = 256
    while size < n:
        size *= 2
    return size


def seal_payload(plaintext: bytes, dek: bytes) -> bytes:
    body = _PAD + len(plaintext).to_bytes(4, "big") + plaintext
    return _seal(body + bytes(_bucket(len(body)) - len(body)), dek)


def open_payload(ciphertext: bytes, dek: bytes) -> bytes:
    body = _open(ciphertext, dek)
    if not body.startswith(_PAD):
        return body
    n = int.from_bytes(body[len(_PAD) : len(_PAD) + 4], "big")
    return body[len(_PAD) + 4 : len(_PAD) + 4 + n]


def names_key(dek: bytes) -> bytes:
    return hmac.new(dek, b"enqueue relay names v1", hashlib.sha256).digest()


def object_name(ident: str, dek: bytes) -> str:
    """What an artifact or a conversation is called on the relay: its id, hashed."""
    return hmac.new(names_key(dek), ident.encode("utf-8"), hashlib.sha256).hexdigest()[:40]
