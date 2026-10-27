"""Local embeddings. Nothing here ever touches the network after the model is cached.

There is no hosted embeddings endpoint, so this is local by necessity. It is also
strictly more private, which is why it stays local even once a hosted backend is
configured.
"""

from __future__ import annotations

import gc
import os
import threading
import time
from contextlib import contextmanager
from functools import lru_cache

from .. import config


def _providers() -> list[str]:
    """Which ONNX providers run the dense model: the CPU, unless ENQ_EMBED_PROVIDERS
    (comma-separated) names others. CoreML was tried first until 2026-10-27; measured on
    an M-series Mac it was no faster (a query 18 ms either way, 32 passages 10.9 s on
    CoreML against 9.6 s on the CPU) and kept more memory."""
    override = os.getenv("ENQ_EMBED_PROVIDERS")
    if override:
        return [p.strip() for p in override.split(",") if p.strip()]
    return ["CPUExecutionProvider"]


# The model is about 400 MB once loaded, more while a batch runs. It is loaded on first
# use and let go after EMBED_IDLE_S without one, so an engine left open all day does not
# hold it; a search after that waits about half a second for it to load again. With
# ONNX's memory arena off, letting go returns the memory to the system (with it on, a
# measured 999 MB only fell to 800 MB). Batches are capped for the same reason: the
# default of 256 passages peaked at 1.1 GB, 16 at about 820 MB, at the same speed.
EMBED_IDLE_S = float(os.getenv("ENQ_EMBED_IDLE", "300"))
EMBED_BATCH = 16

_state = threading.Condition()
_loaded = None
_users = 0
_last_used = 0.0
_reaper = None


@contextmanager
def _using():
    """The model, held for one call: the idle reaper never unloads it mid-embed."""
    global _loaded, _users, _last_used, _reaper
    with _state:
        if _loaded is None:
            from fastembed import TextEmbedding

            _loaded = TextEmbedding(
                model_name=config.EMBED_MODEL,
                providers=_providers(),
                enable_cpu_mem_arena=False,
            )
        if _reaper is None and EMBED_IDLE_S > 0:
            _reaper = threading.Thread(target=_reap, name="embed-idle", daemon=True)
            _reaper.start()
        _users += 1
        model = _loaded
    try:
        yield model
    finally:
        with _state:
            _users -= 1
            _last_used = time.monotonic()


def _reap() -> None:
    while True:
        time.sleep(min(30.0, EMBED_IDLE_S))
        with _state:
            if _loaded is not None and not _users and time.monotonic() - _last_used > EMBED_IDLE_S:
                unload()


def unload() -> None:
    """Let the model go; the next embed loads it again (or loads another EMBED_MODEL)."""
    global _loaded
    with _state:
        _loaded = None
    gc.collect()


def embed(texts: list[str]) -> list[list[float]]:
    """Passages, framed as the model expects (config.EMBED_DOC_PREFIX)."""
    if not texts:
        return []
    prefix = config.EMBED_DOC_PREFIX
    with _using() as model:
        return [
            v.tolist() for v in model.embed([prefix + t for t in texts], batch_size=EMBED_BATCH)
        ]


def token_count(text: str) -> int:
    """Tokens the embedder sees in `text`, not counting its two special tokens. The
    tokenizer truncates, so anything past config.EMBED_MAX_TOKENS reads as the cap."""
    with _using() as model:
        return max(0, model.token_count(text) - 2)


def embed_query(text: str) -> list[float]:
    """A search, as the model expects one: EMBED_QUERY_PREFIX, then the text."""
    return embed_one(config.EMBED_QUERY_PREFIX + text)


def embed_passage(text: str) -> list[float]:
    """One passage, framed like the indexed ones, for passage-to-passage similarity
    (related notes)."""
    return embed_one(config.EMBED_DOC_PREFIX + text)


@lru_cache(maxsize=512)
def embed_one(text: str) -> list[float]:
    """Embed a single string, memoized.

    A hybrid search embeds its query once for the chunk branch and once for the facet
    branch, so the same string was run through the model twice per search - measured at
    ~11 ms each, the largest single cost in a ~40 ms query. Query text is deterministic
    under a fixed model, so the second run is pure waste, and repeated queries (paging,
    re-searching, a chat follow-up in the same scope) become free.

    The returned list is shared across cache hits and must not be mutated in place; the
    only caller serialises it read-only. Indexing uses `embed()` (the batch path), which
    is deliberately uncached because its texts are unique and would only bloat the cache.
    """
    with _using() as model:
        return [v.tolist() for v in model.embed([text])][0]
