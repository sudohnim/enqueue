"""Settings the person can change without editing the environment.

Three layers, in falling precedence:

  environment   explicit intent from whoever launched the process, always wins
  settings.json what was chosen in the interface
  config        the built-in default

The environment winning matters: a value set in the launcher and silently overridden
by a file the person forgot about is the kind of bug that costs an afternoon. When
that happens the interface says so rather than showing a field that does nothing.

**No secret is ever written here.** This file is plaintext on disk, so the API key
lives in the macOS Keychain instead (see `keyring.py`) and only ever leaves it to be
put in an Authorization header. What this module reports about the key is whether one
exists and its last four characters, never the key.
"""

from __future__ import annotations

import json
import os
from typing import Any

from . import config


def settings_path():
    """Resolved at call time, not at import.

    Binding this once meant a test that repointed `config.DATA_DIR` at a temporary
    directory still read and wrote the developer's real settings file. It was found
    by a theme test that passed or failed depending on what was set in the running
    app, after the suite had already been quietly mutating it.
    """
    return config.DATA_DIR / "settings.json"


# name -> (environment variable, default, whether the interface may write it)
FIELDS: dict[str, tuple[str, Any, bool]] = {
    "llm_backend": ("ENQ_LLM_BACKEND", config.LLM_BACKEND, True),
    "llm_model": ("ENQ_LLM_MODEL", config.LLM_MODEL, True),
    # The vision model used to describe images at ingest (K.11). Separate from
    # the text model: most backends answer text and images with different models.
    "vision_model": ("ENQ_VISION_MODEL", config.VISION_MODEL, True),
    "llm_url": ("ENQ_OLLAMA_URL", config.OLLAMA_URL, True),
    # The relay the sync client pushes to and pulls from (SYNC.3). Empty means
    # sync is not configured. Plaintext on purpose: the relay URL is not a secret.
    "sync_relay_url": ("ENQ_SYNC_RELAY_URL", "", True),
    "model_retries": ("ENQ_MODEL_RETRIES", config.MODEL_RETRIES, True),
    "user_agent": ("ENQ_USER_AGENT", None, True),
    "hotkey": ("ENQ_HOTKEY", "Alt+Shift+E", True),
    # Whether saving a link also fetches what it is. On means one request per link at
    # the moment you save it; off means it stays a bare address until you ask. Default
    # on, because a wall of unresolved URLs is the thing the preview exists to fix.
    "auto_preview": ("ENQ_AUTO_PREVIEW", "on", True),
    # Free text, sent as extra headers on every model call. Some endpoints want a
    # referer or an app name before they will answer; this is the escape hatch that
    # stops each one becoming a code change. One `Name: value` per line.
    "llm_headers": ("ENQ_LLM_HEADERS", "", True),
    # Days a deleted artifact survives before it is destroyed for good.
    "trash_days": ("ENQ_TRASH_DAYS", 30, True),
}

WRITABLE = {name for name, (_, _, may_write) in FIELDS.items() if may_write}


def _stored() -> dict:
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def get(name: str) -> Any:
    """Resolve one setting through all three layers."""
    env_name, default, _ = FIELDS[name]
    from_env = os.getenv(env_name)
    if from_env is not None:
        return from_env
    return _stored().get(name, default)


def _go_chat_models(name: str) -> dict[str, list[str] | str] | None:
    """Expose Go model classification to the settings panel (FIX.3).

    Lets the frontend warn when a model name requires an API shape the adapter
    cannot speak (/responses or /messages), before any call is made.
    """
    if name != "opencode-go":
        return None
    from . import config

    return {
        "chat_completions": sorted(config.GO_CHAT_COMPLETIONS_MODELS),
        "unsupported_shape": sorted(config.GO_UNSUPPORTED_SHAPE_MODELS),
        "examples": config.GO_CHAT_COMPLETIONS_EXAMPLES,
    }


def backends() -> list[dict]:
    """The named endpoints, and what choosing each one means.

    `key_present` is whether the backend's key actually resolves, from either
    source - the environment or the Keychain - because `api_key_state` already
    consults both and the panel's warning must not contradict it (I7.1).
    Resolved once per call: the Keychain read is a subprocess, so per-backend
    resolution would pay for it five times over.
    """
    key = config.llm_api_key()
    return [
        {
            "name": name,
            "label": spec["label"],
            "url": spec["url"],
            "local": spec["local"],
            "needs_key": bool(spec["key_var"]),
            "key_present": bool(spec["key_var"]) and bool(key) and key != "ollama",
            **({"chat_models": _go_chat_models(name)} if name == "opencode-go" else {}),
        }
        for name, spec in config.BACKENDS.items()
    ]


def all_settings() -> dict:
    """Every setting, with where its value came from, for the interface to render."""
    stored = _stored()
    out = {}
    for name, (env_name, default, may_write) in FIELDS.items():
        from_env = os.getenv(env_name)
        out[name] = {
            "value": from_env if from_env is not None else stored.get(name, default),
            "source": (
                "environment"
                if from_env is not None
                else ("settings" if name in stored else "default")
            ),
            "env_var": env_name,
            "locked": from_env is not None,
            "editable": may_write,
        }
    return out


def update(changes: dict) -> dict:
    """Write the settings the interface is allowed to write.

    A field currently pinned by an environment variable is rejected rather than
    written and ignored, so the interface can say why nothing happened.
    """
    unknown = set(changes) - WRITABLE
    if unknown:
        raise ValueError(f"not settable: {sorted(unknown)}")

    locked = [n for n in changes if os.getenv(FIELDS[n][0]) is not None]
    if locked:
        raise ValueError(
            f"{sorted(locked)} is pinned by the environment "
            f"({', '.join(FIELDS[n][0] for n in locked)}); unset it to change it here"
        )

    stored = _stored()
    for name, value in changes.items():
        if value is None or value == "":
            stored.pop(name, None)
        else:
            stored[name] = value

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings_path().write_text(json.dumps(stored, indent=2), encoding="utf-8")
    # Not a secret, but not everyone's business either.
    settings_path().chmod(0o600)
    return all_settings()


def storage() -> dict:
    """Where everything lives, and how much of it there is."""
    from . import db

    def size(path) -> int:
        try:
            if path.is_dir():
                return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            return path.stat().st_size
        except OSError:
            return 0

    return {
        "data_dir": str(config.DATA_DIR),
        "database": {"path": str(config.DB_PATH), "bytes": size(config.DB_PATH)},
        "blobs": {"path": str(config.BLOB_DIR), "bytes": size(config.BLOB_DIR)},
        "counts": {table: db.count(table) for table in ("artifacts", "chunks", "facets", "chats")},
        **api_key_state(),
    }


def api_key_state() -> dict:
    """What is known about the key without revealing it."""
    from . import keyring

    from_env = os.getenv("ENQ_LLM_API_KEY", "").strip()
    if from_env and from_env != "ollama":
        return {
            "api_key_present": True,
            "api_key_where": "environment",
            "api_key_hint": keyring.hint(from_env),
            "api_key_editable": False,
            "keychain_available": keyring.available(),
        }

    stored = keyring.get()
    return {
        "api_key_present": bool(stored),
        "api_key_where": "keychain" if stored else None,
        "api_key_hint": keyring.hint(stored),
        # Pinned by the environment means the field would do nothing, so it is not
        # offered rather than offered and ignored.
        "api_key_editable": keyring.available(),
        "keychain_available": keyring.available(),
    }


def sync_state() -> dict:
    """What the interface needs to know about sync configuration (SYNC.3).

    The relay URL is a plaintext setting; the per-library secret lives in the
    Keychain and its value is never read back here - only whether one is present
    and its hint. The device id names this device's namespace on the relay.
    Keyring state tells the UI whether sync can proceed or needs initialization.
    """
    from . import keyring, keyring_file
    from .sync import device_id

    keyring_initialized = keyring_file.is_initialized()
    # QR.1: DEK auto-loads from the Keychain/file on startup, so a restart is
    # not locked. When the stored copy is missing (total device loss), the
    # keyring stays locked until the recovery phrase restores it.
    if keyring_initialized and keyring_file.dek() is None:
        keyring_file.load_dek_from_keychain()
    keyring_locked = keyring_initialized and keyring_file.dek() is None
    keyring_ready = keyring_initialized and not keyring_locked

    return {
        "relay_url": get("sync_relay_url") or "",
        "relay_configured": bool(get("sync_relay_url")),
        "secret_present": bool(keyring.sync_secret_get()),
        "secret_hint": keyring.sync_secret_hint(),
        "device_id": device_id(),
        "keyring_initialized": keyring_initialized,
        "keyring_locked": keyring_locked,
        "keyring_ready": keyring_ready,
        "keyring_legacy": keyring_file.is_legacy(),
    }
