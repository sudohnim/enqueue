"""The original files (`blobs/`), encrypted on the Mac's disk.

Every file is named by the hash of its plaintext, as before, and once the recovery kit is
saved its bytes are sealed under a key derived from the library key (`libkey.derive(...,
"blobs")`): libsodium's secretstream, 1 MiB chunks, the last tagged final, behind a
13-byte header (`ENQF`, a format byte, the key id), the format backups use. Before the
kit is saved the files stay plain, for the same reason the database does: a lost
Keychain would otherwise lose them too (db.encrypt_library).

Everything reads and writes through here: `write`, `read`, `exists`. A file from before
(plain) reads as it is, and `seal_all` (engine start, after the database is encrypted)
seals each one in place, through a partial file, checked by opening it again before it
replaces the plain copy.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from collections import OrderedDict
from pathlib import Path

from nacl.bindings import (
    crypto_secretstream_xchacha20poly1305_init_pull,
    crypto_secretstream_xchacha20poly1305_init_push,
    crypto_secretstream_xchacha20poly1305_pull,
    crypto_secretstream_xchacha20poly1305_push,
    crypto_secretstream_xchacha20poly1305_state,
    crypto_secretstream_xchacha20poly1305_TAG_FINAL,
    crypto_secretstream_xchacha20poly1305_TAG_MESSAGE,
)
from nacl.exceptions import CryptoError

from . import config, libkey

log = logging.getLogger("enqueue.blobstore")

MAGIC = b"ENQF"
FORMAT = 1
HEADER = 13
CHUNK = 1 << 20


class BlobError(RuntimeError):
    """An original file could not be read: missing, damaged, or under another key."""


def path(content_hash: str) -> Path:
    return config.BLOB_DIR / Path(content_hash).name


def exists(content_hash: str | None) -> bool:
    return bool(content_hash) and path(content_hash).is_file()


def _key() -> tuple[bytes, str] | None:
    """The files key and its id, or None while files stay plain (kit not saved)."""
    if not libkey.kit_saved():
        return None
    key = libkey.get(create=False)
    if key is None:
        return None
    return libkey.derive(key, "blobs"), libkey.key_id(key)


def is_sealed(file: Path) -> bool:
    try:
        with open(file, "rb") as f:
            head = f.read(5)
    except OSError:
        return False
    return head[:4] == MAGIC and head[4:5] == bytes([FORMAT])


def _seal_bytes(data: bytes, key: bytes, kid: str) -> bytes:
    state = crypto_secretstream_xchacha20poly1305_state()
    ad = MAGIC + bytes([FORMAT]) + bytes.fromhex(kid)
    out = [ad, crypto_secretstream_xchacha20poly1305_init_push(state, key)]
    chunks = [data[i : i + CHUNK] for i in range(0, len(data), CHUNK)] or [b""]
    for i, chunk in enumerate(chunks):
        last = i == len(chunks) - 1
        tag = (
            crypto_secretstream_xchacha20poly1305_TAG_FINAL
            if last
            else crypto_secretstream_xchacha20poly1305_TAG_MESSAGE
        )
        out.append(crypto_secretstream_xchacha20poly1305_push(state, chunk, ad, tag))
    return b"".join(out)


def _open_bytes(raw: bytes, name: str) -> bytes:
    ad = raw[:HEADER]
    keys = _key()
    if keys is None:
        # A sealed file on a Mac whose kit is not marked saved: the key still opens it.
        key = libkey.get(create=False)
        if key is None:
            raise BlobError(f"{name} is locked and this Mac has no library key")
        keys = (libkey.derive(key, "blobs"), libkey.key_id(key))
    key, kid = keys
    if ad[5:HEADER].hex() != kid:
        raise BlobError(f"{name} is locked with a different library's key")
    state = crypto_secretstream_xchacha20poly1305_state()
    crypto_secretstream_xchacha20poly1305_init_pull(state, raw[HEADER : HEADER + 24], key)
    at, out = HEADER + 24, []
    while True:
        chunk = raw[at : at + CHUNK + 17]
        if not chunk:
            raise BlobError(f"{name} is cut short")
        at += len(chunk)
        try:
            plain, tag = crypto_secretstream_xchacha20poly1305_pull(state, chunk, ad)
        except CryptoError:
            raise BlobError(f"{name} is damaged") from None
        out.append(plain)
        if tag == crypto_secretstream_xchacha20poly1305_TAG_FINAL:
            return b"".join(out)


# Recently opened files, decrypted, in memory only: a PDF's reader asks for page after
# page, and each page would otherwise decrypt the whole file again. Bounded by size.
_RECENT: OrderedDict[str, bytes] = OrderedDict()
_RECENT_BYTES = 256 << 20
_recent_lock = threading.Lock()


def read(content_hash: str) -> bytes:
    """The file's plaintext. Raises FileNotFoundError when there is none."""
    with _recent_lock:
        if content_hash in _RECENT:
            _RECENT.move_to_end(content_hash)
            return _RECENT[content_hash]
    file = path(content_hash)
    raw = file.read_bytes()
    if raw[:4] == MAGIC and raw[4:5] == bytes([FORMAT]):
        data = _open_bytes(raw, file.name)
    else:
        data = raw
    if len(data) <= _RECENT_BYTES // 2:
        with _recent_lock:
            _RECENT[content_hash] = data
            while sum(len(v) for v in _RECENT.values()) > _RECENT_BYTES:
                _RECENT.popitem(last=False)
    return data


def write(data: bytes, content_hash: str | None = None) -> str:
    """Store `data` under its hash (sealed once the kit is saved) and return the hash.
    A file already there is left alone: the same hash is the same bytes."""
    content_hash = content_hash or hashlib.sha256(data).hexdigest()
    file = path(content_hash)
    if file.is_file():
        return content_hash
    config.BLOB_DIR.mkdir(parents=True, exist_ok=True)
    keys = _key()
    raw = _seal_bytes(data, *keys) if keys else data
    tmp = file.with_name("." + file.name + ".partial")
    tmp.write_bytes(raw)
    os.replace(tmp, file)
    return content_hash


def replace(content_hash: str, data: bytes) -> None:
    """Rewrite a file in place under the same name (the vault seals one under its own
    key, and opens it again). The disk layer goes on top as for any write."""
    file = path(content_hash)
    keys = _key()
    raw = _seal_bytes(data, *keys) if keys else data
    tmp = file.with_name("." + file.name + ".partial")
    tmp.write_bytes(raw)
    os.replace(tmp, file)
    with _recent_lock:
        _RECENT.pop(content_hash, None)


class Handle:
    """One stored file, for code that reads it and writes it back (vaultops.py)."""

    def __init__(self, content_hash: str):
        self.content_hash = content_hash

    def exists(self) -> bool:
        return exists(self.content_hash)

    def read_bytes(self) -> bytes:
        return read(self.content_hash)

    def write_bytes(self, data: bytes) -> None:
        replace(self.content_hash, data)


def size(content_hash: str) -> int:
    """The plaintext's length, without decrypting: the header, then each chunk with its
    17 bytes of tag."""
    file = path(content_hash)
    length = file.stat().st_size
    if not is_sealed(file):
        return length
    body = length - HEADER - 24
    chunks = max(1, -(-body // (CHUNK + 17)))
    return body - 17 * chunks


def remove(content_hash: str) -> None:
    with _recent_lock:
        _RECENT.pop(content_hash, None)
    path(content_hash).unlink(missing_ok=True)


def seal_all() -> int:
    """Seal every plain file in place (engine start, once the kit is saved). Each sealed
    copy is opened again and compared before it replaces the plain one. Returns how many
    were sealed; stops quietly when the files are to stay plain."""
    keys = _key()
    if keys is None or not config.BLOB_DIR.is_dir():
        return 0
    sealed = 0
    for file in config.BLOB_DIR.iterdir():
        if not file.is_file() or file.name.startswith(".") or is_sealed(file):
            continue
        try:
            data = file.read_bytes()
            raw = _seal_bytes(data, *keys)
            if _open_bytes(raw, file.name) != data:
                raise BlobError(f"{file.name} did not read back")
            tmp = file.with_name("." + file.name + ".partial")
            tmp.write_bytes(raw)
            os.replace(tmp, file)
            sealed += 1
        except (OSError, BlobError) as exc:
            log.warning("could not seal %s: %s", file.name, exc)
    return sealed
