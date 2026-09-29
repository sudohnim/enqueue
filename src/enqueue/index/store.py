"""The vector store interface. Picking a backend is a config change (ENQ_VECTOR_STORE)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from functools import lru_cache

from .. import config


class VectorStore(ABC):
    """What an index backend must do. Hits carry ids only; collection names are the contract."""

    CHUNKS = "chunks"
    FACETS = "facets"
    ENTITIES = "entities"

    @abstractmethod
    def ensure(self) -> None:
        """Create the collections if they do not exist."""

    @abstractmethod
    def reset(self, name: str) -> None:
        """Drop and recreate one collection. For a full rebuild."""

    @abstractmethod
    def upsert_chunks(self, batch_size: int = 64) -> dict:
        """Rebuild the whole chunks index. Returns {"indexed": n, "collection": name}."""

    @abstractmethod
    def upsert_facets(self, batch_size: int = 64) -> dict:
        """Rebuild the whole facets index. Returns {"indexed": n, "collection": name}."""

    @abstractmethod
    def upsert_entities(self, batch_size: int = 64) -> dict:
        """Rebuild the whole entities index. Returns {"indexed": n, "collection": name}."""

    @abstractmethod
    def drop_artifact(self, name: str, artifact_id: str) -> None:
        """Remove every vector belonging to one artifact."""

    @abstractmethod
    def index_artifact(self, artifact_id: str) -> int:
        """Re-embed one artifact's chunks in place; returns how many were indexed."""

    @abstractmethod
    def index_facets_artifact(self, artifact_id: str) -> int:
        """Re-embed one artifact's facets in place; returns how many were indexed."""

    @abstractmethod
    def index_entities_artifact(self, artifact_id: str) -> int:
        """Re-embed one artifact's entity lines in place; returns how many were indexed."""

    @abstractmethod
    def search(self, name: str, text: str, limit: int = 30, prefetch: int = 100) -> list[dict]:
        """Hybrid retrieval, best first. `prefetch` is the per-leg window before fusion."""

    @abstractmethod
    def search_legs(
        self, name: str, text: str, limit: int = 30, prefetch: int = 100
    ) -> dict[str, list[dict]]:
        """`{"fused", "dense", "keyword", "trigram"}`: `search` plus its raw legs, one pass.

        Each leg holds up to `prefetch` hits in its own rank order.
        """

    @abstractmethod
    def search_dense(
        self, name: str, text: str, limit: int = 30, as_query: bool = True
    ) -> list[dict]:
        """Dense leg only. Same hit shape as `search`. `as_query=False` embeds `text` as
        a passage rather than a search."""

    @abstractmethod
    def search_keyword(self, name: str, text: str, limit: int = 30) -> list[dict]:
        """Keyword leg only. Same hit shape as `search`."""

    @abstractmethod
    def search_trigram(self, name: str, text: str, limit: int = 30) -> list[dict]:
        """Trigram leg only (chunks only; [] elsewhere). Same hit shape as `search`."""

    @abstractmethod
    def counts(self) -> dict:
        """Vectors per collection, keyed by collection name."""

    @abstractmethod
    def write_embed_version(self) -> None:
        """Record which embedding version the index was built at."""


@lru_cache(maxsize=1)
def get_store(on_progress: Callable[[int, int], None] | None = None) -> VectorStore:
    """The configured store, one per process. `on_progress` feeds `POST /index` progress."""
    name = (config.VECTOR_STORE or "sqlite-vec").strip().lower()
    if name in ("sqlite-vec", "sqlite_vec"):
        from .store_sqlite import SqliteVecStore

        return SqliteVecStore(on_progress=on_progress)
    raise ValueError(
        f"unknown VECTOR_STORE {config.VECTOR_STORE!r}; " "set ENQ_VECTOR_STORE=sqlite-vec"
    )
