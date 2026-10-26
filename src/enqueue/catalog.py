"""Which models an online service actually serves, so a model id can be picked from a
list and a wrong one is refused when it is saved, not discovered when chat fails.

OpenRouter publishes its list without a key (`GET /api/v1/models`); it is fetched at
most once per `FRESH_S`, kept in memory and in `model-catalog.json` in the data folder
(a public list, nothing of the person's), and read without a network call everywhere
else (`/settings`, `/setup`). OpenCode Go's list is the one in `config`.
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


def refresh(backend: str) -> dict | None:
    """Fetch the service's list now. None when it has no list or cannot be reached."""
    url = SOURCES.get(backend)
    if not url:
        return None
    try:
        resp = httpx.get(url, timeout=10, headers={"User-Agent": "Enqueue (model list)"})
        resp.raise_for_status()
        listing = _parse(resp.json())
    except (httpx.HTTPError, ValueError):
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


def cached(backend: str) -> dict | None:
    """The list as last fetched, with no network call; a stale one is refreshed behind."""
    if backend == "opencode-go":
        # Which of them read pictures is not listed, so the images job is not checked.
        return {"chat": sorted(config.GO_CHAT_COMPLETIONS_MODELS), "fetched_at": None}
    if backend not in SOURCES:
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
