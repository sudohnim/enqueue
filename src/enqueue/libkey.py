"""The library key: the one secret every other key of a library comes from.

Enqueue is zero-knowledge: nothing it sends anywhere (backups today; the relay and the
hosted service later) can be read without this key, and nobody but the person holds it.
It is 32 random bytes, made once, the first time something needs it, and kept in the
macOS Keychain (service `enqueue-library-key`; a mode-0600 file elsewhere).

Each use gets its own key, derived from this one (`derive`, HKDF-SHA256 with the use as
its label), so a key that leaks for one purpose says nothing about the others, and a
use can start a new generation without the library changing its root:

- `backup`, `backup-names`: what backups are encrypted with and how their files are
  named (backup.py).

The way back to the key on a new Mac, after every device is gone, is the recovery kit:
the key written as 56 letters and digits (`kit`, Crockford base32 with a checksum), which
the person saves somewhere of their own. There is no other copy and no reset. Settings
shows the kit until the person says they saved it (`kit_saved`).

The sync key (keyring_file.py) is not derived from this one yet; moving it under the
library key is the next step of the same design.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone

from . import config, keyring

SERVICE = "enqueue-library-key"
_SALT = b"enqueue library key v1"
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class KitError(ValueError):
    """A recovery kit that cannot be read; the message says why, for a person."""


# ---- where it lives --------------------------------------------------------------


def _file():
    return config.DATA_DIR / "library-key"


def _load() -> bytes | None:
    if keyring.available():
        raw = keyring._get(SERVICE)
    else:
        try:
            raw = _file().read_text(encoding="ascii").strip()
        except OSError:
            raw = None
    if not raw:
        return None
    try:
        key = base64.b64decode(raw)
    except ValueError:
        return None
    return key if len(key) == 32 else None


def _save(key: bytes) -> None:
    raw = base64.b64encode(key).decode("ascii")
    if keyring.available():
        keyring._set(SERVICE, raw, noun="library key")
        if _load() != key:
            raise RuntimeError("the library key did not store correctly in the Keychain")
        return
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(raw)


def get(create: bool = True) -> bytes | None:
    """The library key; made and stored the first time it is asked for."""
    key = _load()
    if key is None and create:
        key = secrets.token_bytes(32)
        _save(key)
    return key


def adopt(key: bytes) -> None:
    """Make `key` this library's key: a library restored from a backup on a new Mac
    keeps the key its backups are locked with. The recovery kit stays valid, so it
    counts as saved."""
    if len(key) != 32:
        raise ValueError("a library key is 32 bytes")
    _save(key)
    _write_kit_state({"saved_at": _now(), "key_id": key_id(key), "adopted": True})


# ---- keys for each use -----------------------------------------------------------


def derive(key: bytes, use: str, length: int = 32) -> bytes:
    """A key for one use, from the library key (HKDF-SHA256, RFC 5869)."""
    prk = hmac.new(_SALT, key, hashlib.sha256).digest()
    out = b""
    block = b""
    counter = 1
    while len(out) < length:
        block = hmac.new(prk, block + use.encode() + bytes([counter]), hashlib.sha256).digest()
        out += block
        counter += 1
    return out[:length]


def key_id(key: bytes) -> str:
    """A short public name for a key (16 hex characters), so a backup can say which
    key opens it without saying anything about the key."""
    return derive(key, "key-id", 8).hex()


# ---- the recovery kit ------------------------------------------------------------


def _b32(data: bytes) -> str:
    out, acc, bits = [], 0, 0
    for byte in data:
        acc = (acc << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append(_ALPHABET[(acc >> bits) & 31])
    if bits:
        out.append(_ALPHABET[(acc << (5 - bits)) & 31])
    return "".join(out)


def _unb32(text: str) -> bytes:
    acc, bits, out = 0, 0, bytearray()
    for ch in text:
        acc = (acc << 5) | _ALPHABET.index(ch)
        bits += 5
        if bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 0xFF)
    return bytes(out)


def kit(key: bytes) -> str:
    """The key as a recovery kit: 32 bytes and a 3-byte checksum, in groups of four."""
    code = _b32(key + hashlib.sha256(b"enqueue kit" + key).digest()[:3])
    return "-".join(code[i : i + 4] for i in range(0, len(code), 4))


def from_kit(text: str) -> bytes:
    """The key a recovery kit holds. Forgives spacing, dashes, case and the letters
    people mistake for digits (O for 0, I and L for 1)."""
    clean = "".join(ch for ch in text.upper() if ch.isalnum())
    clean = clean.translate(str.maketrans("OIL", "011"))
    if any(ch not in _ALPHABET for ch in clean):
        raise KitError("a recovery kit has only letters and digits; check what was typed")
    if len(clean) != 56:
        raise KitError(f"a recovery kit is 56 characters; this one has {len(clean)}")
    raw = _unb32(clean)
    key, check = raw[:32], raw[32:35]
    if hashlib.sha256(b"enqueue kit" + key).digest()[:3] != check:
        raise KitError("that recovery kit has a typo in it; check each group of four")
    return key


def _kit_path():
    return config.DATA_DIR / "recovery-kit.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_kit_state(state: dict) -> None:
    path = _kit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def kit_saved() -> bool:
    """Whether the person said they saved the kit for the key this library has now."""
    key = get(create=False)
    if key is None:
        return False
    try:
        state = json.loads(_kit_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return state.get("key_id") == key_id(key)


def mark_kit_saved() -> None:
    _write_kit_state({"saved_at": _now(), "key_id": key_id(get())})
