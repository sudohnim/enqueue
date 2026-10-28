"""Which models an online service actually serves, so a model id can be picked from a
list and a wrong one is refused when it is saved, not discovered when chat fails.

OpenRouter publishes its list without a key (`GET /api/v1/models`); it is fetched at
most once per `FRESH_S`, kept in memory and in `model-catalog.json` in the data folder
(a public list, nothing of the person's), and read without a network call everywhere
else (`/settings`, `/setup`). OpenAI and Anthropic list models only for a key, so
theirs is fetched with the person's key. OpenCode Go's list is the one in `config`.
A service that cannot be reached leaves the list unknown, and an unknown list refuses
nothing: the check is there to catch typos, not to stop someone offline.
"""

from __future__ import annotations

import json
import threading
import time

import httpx

from . import config

FRESH_S = 12 * 3600
# A model missing from a list this old is looked up again before it is refused: a
# model the service added since the last fetch must not be turned away.
RECHECK_S = 300
SOURCES = {"openrouter": "https://openrouter.ai/api/v1/models"}

_LOCK = threading.Lock()
_CACHE: dict[str, dict] = {}
_FETCHING: set[str] = set()


def _path():
    return config.DATA_DIR / "model-catalog.json"


def _load() -> None:
    if _CACHE:
        return
    try:
        stored = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(stored, dict):
        _CACHE.update({k: v for k, v in stored.items() if isinstance(v, dict)})


def _save() -> None:
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _path().write_text(json.dumps(_CACHE), encoding="utf-8")
    except OSError:
        pass


def _parse(payload: dict) -> dict:
    """The ids that answer in text, and the ones of those that also read pictures."""
    chat, vision = [], []
    for m in payload.get("data") or []:
        ident = m.get("id") if isinstance(m, dict) else None
        if not ident:
            continue
        arch = m.get("architecture") or {}
        if "text" not in (arch.get("output_modalities") or ["text"]):
            continue
        chat.append(ident)
        if "image" in (arch.get("input_modalities") or []):
            vision.append(ident)
    return {"chat": sorted(chat), "vision": sorted(vision), "fetched_at": time.time()}


# OpenAI lists every model it has; these words mark the ones that do not chat.
_NOT_CHAT = ("audio", "realtime", "tts", "transcribe", "image", "embedding", "moderation")


def _openai(key: str) -> dict:
    import openai

    listed = sorted(
        openai.OpenAI(api_key=key, timeout=10).models.list(), key=lambda m: -(m.created or 0)
    )
    chat = [
        m.id
        for m in listed
        if m.id.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-"))
        and not any(w in m.id for w in _NOT_CHAT)
    ]
    return {"chat": sorted(chat), "newest": chat, "fetched_at": time.time()}


def _anthropic(key: str) -> dict:
    import anthropic

    models = anthropic.Anthropic(api_key=key, timeout=10).models.list(limit=1000)
    # Enqueue asks for JSON in a schema, so a model that cannot answer in one is no use.
    usable = [m for m in models if m.capabilities and m.capabilities.structured_outputs.supported]
    vision = [m.id for m in usable if m.capabilities.image_input.supported]
    return {
        "chat": sorted(m.id for m in usable),
        "vision": sorted(vision),
        "newest": [m.id for m in usable],  # the API lists the newest first
        "fetched_at": time.time(),
    }


KEYED = {"openai": _openai, "anthropic": _anthropic}


def _fetch(backend: str) -> dict | None:
    if backend in KEYED:
        key = config.llm_api_key(config.BACKENDS[backend]["url"])
        if key == "no-key":
            return None
        try:
            return KEYED[backend](key)
        except Exception:  # noqa: BLE001 - a list that cannot be had refuses nothing
            return None
    url = SOURCES.get(backend)
    if not url:
        return None
    try:
        resp = httpx.get(url, timeout=10, headers={"User-Agent": "Enqueue (model list)"})
        resp.raise_for_status()
        return _parse(resp.json())
    except (httpx.HTTPError, ValueError):
        return None


def refresh(backend: str) -> dict | None:
    """Fetch the service's list now. None when it has no list or cannot be reached."""
    listing = _fetch(backend)
    if listing is None:
        return None
    if not listing["chat"]:
        return None
    with _LOCK:
        _CACHE[backend] = listing
        _save()
    return listing


def _refresh_behind(backend: str) -> None:
    with _LOCK:
        if backend in _FETCHING:
            return
        _FETCHING.add(backend)

    def run():
        try:
            refresh(backend)
        finally:
            with _LOCK:
                _FETCHING.discard(backend)

    threading.Thread(target=run, name=f"catalog-{backend}", daemon=True).start()


def _local() -> dict | None:
    from . import local_model

    if not local_model.running():
        return None
    held = local_model.models()
    return {
        "chat": sorted(m["name"] for m in held),
        "vision": sorted(m["name"] for m in held if m["vision"]),
        "fetched_at": time.time(),
    }


def cached(backend: str) -> dict | None:
    """The list as last fetched, with no network call; a stale one is refreshed behind."""
    if backend == "local":  # Ollama on this Mac answers at once; nothing is kept
        return _local()
    if backend == "opencode-go":
        # Which of them read pictures is not listed, so the images job is not checked.
        return {"chat": sorted(config.GO_CHAT_COMPLETIONS_MODELS), "fetched_at": None}
    if backend not in SOURCES and backend not in KEYED:
        return None
    with _LOCK:
        _load()
        listing = _CACHE.get(backend)
    if listing is None or time.time() - listing.get("fetched_at", 0) > FRESH_S:
        _refresh_behind(backend)
    return listing


def get(backend: str) -> dict | None:
    """The list, fetched now when none is kept (for the settings page's pickers)."""
    return cached(backend) or refresh(backend)


def unknown(backend: str, model: str, vision: bool = False, recheck: bool = True) -> bool:
    """Whether the service is known not to serve `model` (for that job). False when the
    list is unknown: nothing is refused on a guess. `recheck` looks a missing model up
    again when the list is a few minutes old; without it no network call is made."""
    if not model:
        return False
    listing = cached(backend)
    if listing is None:
        return False
    key = "vision" if vision else "chat"
    if key not in listing or model in listing[key]:
        return False
    fetched = listing.get("fetched_at")
    if recheck and fetched and time.time() - fetched > RECHECK_S:
        listing = refresh(backend) or listing
    return model not in listing[key]


# The model a service starts on once its list is known: a small, cheap one.
_CHEAP = {"anthropic": ("haiku",), "openai": ("luna", "mini")}


def suggest(backend: str, listing: dict) -> tuple[str | None, str | None]:
    """The models to start a service on (chat, pictures), from its own list."""
    if backend == "local":
        from . import local_model

        held = listing.get("chat") or []
        order = [c["model"] for c in reversed(local_model.CHOICES)]
        chat = next((m for m in order if m in held), held[0] if held else None)
        vision = listing.get("vision") or []
        return chat, chat if chat in vision else next(iter(vision), None)
    words = _CHEAP.get(backend)
    newest = listing.get("newest") or []
    if not words or not newest:
        return None, None
    chat = next((m for m in newest if any(w in m for w in words)), newest[0])
    vision = listing.get("vision")
    if vision is None:
        return chat, chat
    pick = [m for m in newest if m in vision]
    return chat, chat if chat in vision else next(iter(pick), None)
