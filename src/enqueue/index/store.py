"""The vector store interface.

The engine's searchable index is the thing the plan bets on twice: sqlite-vec today
(inside the SQLite file), possibly another backend later. Every backend
must do the same work, so the interface is the contract, and picking a backend
is a config change rather than a rewrite.

The abstract class has no behavior by design. Anything that can be shared has to
earn its place here, and nothing has yet.

Two deliberate notes on the shape:

- `index_artifact` is on the interface even though the original plan sketch did
  not list it. The ingest queue needs "replace exactly one artifact's vectors in
  place" (save a note, re-embed only that note), and every backend has to be
  able to do that or the queue cannot be backend-neutral.
- The bulk rebuilds (`upsert_chunks`, `upsert_facets`) fetch their rows from
  SQLite themselves rather than taking rows as an argument, exactly as the
  Qdrant logic did before the interface existed. "Copy the logic exactly,
  change no behavior" outranks the sketch.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from functools import lru_cache

from .. import config


class VectorStore(ABC):
    """What an index backend must do.

    `CHUNKS` and `FACETS` are the two collections every backend indexes, and
    their names are part of the contract: payloads carry ids only, so the name
    is all the caller needs to say which index it means. `ENTITIES` is the
    third: the enriched entity lines, indexed exactly like facets.
    """

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
        """Re-embed one artifact's facets in place; returns how many were indexed.

        The per-artifact counterpart to `upsert_facets` (which clears and rebuilds
        the whole collection): this replaces one artifact's facet vectors and leaves
        the rest alone, so facets can be indexed on capture without a full rebuild.
        """

    @abstractmethod
    def index_entities_artifact(self, artifact_id: str) -> int:
        """Re-embed one artifact's entity lines in place; returns how many were indexed.

        The per-artifact counterpart to `upsert_entities`: this replaces one
        artifact's entity vectors and leaves the rest alone, so entities can be
        indexed on capture without a full rebuild.
        """

    @abstractmethod
    def search(self, name: str, text: str, limit: int = 30, prefetch: int = 100) -> list[dict]:
        """Hybrid (dense + sparse) retrieval, scored highest first.

        Hits carry the payload of each matching vector. Payloads hold ids only.
        `prefetch` is the per-branch window the engine searches before fusing;
        callers that need whole-collection coverage raise it so nothing is
        silently left outside the window.
        """

    @abstractmethod
    def search_dense(self, name: str, text: str, limit: int = 30) -> list[dict]:
        """Dense-only retrieval, for ablations. Same hit shape as `search`."""

    @abstractmethod
    def counts(self) -> dict:
        """Vectors per collection, keyed by collection name."""

    @abstractmethod
    def write_embed_version(self) -> None:
        """Record which embedding version the index was built at."""


@lru_cache(maxsize=1)
def get_store(on_progress: Callable[[int, int], None] | None = None) -> VectorStore:
    """The configured store, cached. One instance per process.

    The cache exists so the engine holds one instance for its lifetime;
    sqlite-vec opens its own connection per operation, so there is no
    directory lock to protect - the singleton is a stability rule, not a
    locking rule. `get_store.cache_clear()` exists for the eval harness,
    which repoints the store at an isolated test index within the same
    process.

    `on_progress(indexed, total)` is called every 500 rows of a bulk rebuild;
    backends without a rebuild progress path ignore it. The engine's
    `POST /index` route uses it for the progress indicator.
    """
    name = (config.VECTOR_STORE or "sqlite-vec").strip().lower()
    if name in ("sqlite-vec", "sqlite_vec"):
        from .store_sqlite import SqliteVecStore

        return SqliteVecStore(on_progress=on_progress)
    raise ValueError(
        f"unknown VECTOR_STORE {config.VECTOR_STORE!r}; " "set ENQ_VECTOR_STORE=sqlite-vec"
    )
