"""Local embeddings. Nothing here ever touches the network after the model is cached.

Lumo has no embeddings endpoint, so this is local by necessity. It is also strictly
more private, which is why it stays local even once a hosted backend is configured.
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


@lru_cache(maxsize=1)
def _sparse_model():
    """BM25 sparse vectors.

    Dense embeddings blur proper nouns, so "what did Epictetus say about control"
    returns everything except the Epictetus note. Measured, not assumed. Sparse
    retrieval is what makes names, titles, error codes, and rare jargon findable.
    """
    from fastembed import SparseTextEmbedding

    return SparseTextEmbedding(model_name=config.SPARSE_MODEL)


def embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return [vector.tolist() for vector in _model().embed(texts)]


def embed_one(text: str) -> list[float]:
    return embed([text])[0]


def embed_sparse(texts: list[str]) -> list[tuple[list[int], list[float]]]:
    """Return (indices, values) pairs, the shape Qdrant wants."""
    if not texts:
        return []
    return [
        (vector.indices.tolist(), vector.values.tolist()) for vector in _sparse_model().embed(texts)
    ]


def embed_sparse_one(text: str) -> tuple[list[int], list[float]]:
    return embed_sparse([text])[0]
