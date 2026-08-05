"""Local embeddings. Nothing here ever touches the network after the model is cached.

There is no hosted embeddings endpoint, so this is local by necessity. It is also
strictly more private, which is why it stays local even once a hosted backend is
configured.
"""

from __future__ import annotations

import os
from functools import lru_cache

from .. import config


def _providers() -> list[str] | None:
    """Which ONNX providers to run the dense model on.

    CoreML on macOS first, CPU as the fallback for whatever CoreML cannot take. The
    vectors are bit-identical to the CPU build (measured: max abs diff 0.0), so this
    is a pure speedup and cannot move the retrieval baseline. Override with
    ENQ_EMBED_PROVIDERS (comma-separated) to pin a particular set.
    """
    override = os.getenv("ENQ_EMBED_PROVIDERS")
    if override:
        return [p.strip() for p in override.split(",") if p.strip()]
    try:
        import onnxruntime as ort

        if "CoreMLExecutionProvider" in ort.get_available_providers():
            return ["CoreMLExecutionProvider", "CPUExecutionProvider"]
    except Exception:  # noqa: BLE001 - missing onnxruntime is not fatal at import time
        pass
    return None


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=config.EMBED_MODEL, providers=_providers())


def embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return [vector.tolist() for vector in _model().embed(texts)]


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
    return embed([text])[0]
