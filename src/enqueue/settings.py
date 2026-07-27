"""Settings the person can change without editing the environment.

Three layers, in falling precedence:

  environment   explicit intent from whoever launched the process, always wins
  settings.json what was chosen in the interface
  config        the built-in default

The environment winning matters: a value set in the launcher and silently overridden
by a file the person forgot about is the kind of bug that costs an afternoon. When
that happens the interface says so rather than showing a field that does nothing.

**No secret is ever written here.** The API key is read from `ENQ_LLM_API_KEY` and
never stored, because this file is plaintext on disk and the whole product exists to
keep plaintext off disk. The interface reports whether a key is present, not what it
is. That is a real limitation and it is the correct one.
"""

from __future__ import annotations

import json
import os
from typing import Any

from . import config

SETTINGS_PATH = config.DATA_DIR / "settings.json"

# name -> (environment variable, default, whether the interface may write it)
FIELDS: dict[str, tuple[str, Any, bool]] = {
    "llm_backend": ("ENQ_LLM_BACKEND", config.LLM_BACKEND, True),
    "llm_model": ("ENQ_LLM_MODEL", config.LLM_MODEL, True),
    "llm_url": ("ENQ_OLLAMA_URL", config.OLLAMA_URL, True),
    "model_retries": ("ENQ_MODEL_RETRIES", config.MODEL_RETRIES, True),
    "user_agent": ("ENQ_USER_AGENT", None, True),
    "hotkey": ("ENQ_HOTKEY", "Alt+Shift+E", True),
}

WRITABLE = {name for name, (_, _, may_write) in FIELDS.items() if may_write}


def _stored() -> dict:
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def get(name: str) -> Any:
    """Resolve one setting through all three layers."""
    env_name, default, _ = FIELDS[name]
    from_env = os.getenv(env_name)
    if from_env is not None:
        return from_env
    return _stored().get(name, default)


def backends() -> list[dict]:
    """The named endpoints, and what choosing each one means."""
    import os as _os

    return [
        {
            "name": name,
            "label": spec["label"],
            "url": spec["url"],
            "local": spec["local"],
            "needs_key": bool(spec["key_var"]),
            "key_present": bool(spec["key_var"])
            and bool(_os.getenv(spec["key_var"], "").strip())
            and _os.getenv(spec["key_var"]) != "ollama",
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
    SETTINGS_PATH.write_text(json.dumps(stored, indent=2), encoding="utf-8")
    # Not a secret, but not everyone's business either.
    SETTINGS_PATH.chmod(0o600)
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
        "index": {"path": str(config.QDRANT_PATH), "bytes": size(config.QDRANT_PATH)},
        "counts": {
            table: db.count(table)
            for table in ("artifacts", "chunks", "facets", "chats", "exhibits")
        },
        # Stated rather than implied: there is no key here to lose, because there is
        # no key here at all.
        "api_key_present": bool(os.getenv("ENQ_LLM_API_KEY", "").strip())
        and os.getenv("ENQ_LLM_API_KEY") != "ollama",
    }
