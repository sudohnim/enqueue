"""Local embeddings. Nothing here ever touches the network after the model is cached.

Lumo has no embeddings endpoint, so this is local by necessity. It is also strictly
more private, which is why it stays local even once a hosted backend is configured.
"""

from __future__ import annotations

from functools import lru_cache

from .. import config


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=config.EMBED_MODEL)


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
