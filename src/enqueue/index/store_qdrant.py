"""Qdrant implementation of the VectorStore interface.

The dense-plus-sparse hybrid with Reciprocal Rank Fusion was measured against a
real corpus (the Epictetus note was unfindable with dense alone), so it is the
default behaviour of the default backend, not an experiment. Everything here was
moved verbatim from the old `index/qdrant.py`; the retrieval numbers are the
baseline that every other backend has to reproduce.

HARD RULE: payloads hold ids only. No text, no titles, no URLs, no excerpts.

Qdrant writes payloads unencrypted to disk. Putting chunk text there would write
plaintext excerpts of the entire hoard to an unencrypted store, which is exactly
what the encryption elsewhere exists to prevent. Text lives in SQLite and is
fetched by id after retrieval. This is cheap now and impossible to retrofit once
an index exists.
"""

from __future__ import annotations

import functools
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    Fusion as FusionKind,
    FusionQuery,
    Prefetch,
    PointStruct,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from .. import config, db
from .embed import embed, embed_sparse, embed_sparse_one, embed_one
from .store import VectorStore


class QdrantStore(VectorStore):
    """Qdrant backend, in-process local mode unless ENQ_QDRANT_URL is set.

    The client is per-instance and lazy: `get_store()` is a process singleton, so
    the engine holds exactly one client, and the eval harness repoints the store
    at a test index by clearing the `get_store` cache and letting a fresh
    instance open the test path.
    """

    def __init__(self) -> None:
        self._client_cache = functools.lru_cache(maxsize=1)(self._open_client)

    def _open_client(self) -> QdrantClient:
        """Server if ENQ_QDRANT_URL is set, otherwise in process.

        In-process mode holds a lock on its directory, so the client is cached
        and the engine must be the only process touching it.
        """
        if config.QDRANT_URL:
            return QdrantClient(url=config.QDRANT_URL)
        config.QDRANT_PATH.mkdir(parents=True, exist_ok=True)
        return QdrantClient(path=str(config.QDRANT_PATH))

    def _create(self, name: str) -> None:
        self._client_cache().create_collection(
            collection_name=name,
            vectors_config={DENSE: VectorParams(size=config.EMBED_DIM, distance=Distance.COSINE)},
            sparse_vectors_config={SPARSE: SparseVectorParams(index=SparseIndexParams())},
        )

    def ensure(self) -> None:
        existing = {c.name for c in self._client_cache().get_collections().collections}
        for name in (self.CHUNKS, self.FACETS):
            if name not in existing:
                self._create(name)

    def reset(self, name: str) -> None:
        qc = self._client_cache()
        if name in {c.name for c in qc.get_collections().collections}:
            qc.delete_collection(name)
        self._create(name)

    def _index(self, name: str, rows: list, text_of, payload_of, batch_size: int = 64) -> dict:
        self.reset(name)
        qc = self._client_cache()
        total = 0

        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            texts = [text_of(r) for r in batch]
            dense = embed(texts)
            sparse = embed_sparse(texts)

            qc.upsert(
                collection_name=name,
                points=[
                    PointStruct(
                        id=str(uuid.uuid4()),
                        vector={
                            DENSE: d,
                            SPARSE: SparseVector(indices=s[0], values=s[1]),
                        },
                        payload=payload_of(r),
                    )
                    for r, d, s in zip(batch, dense, sparse, strict=True)
                ],
            )
            total += len(batch)

        return {"indexed": total, "collection": name}

    def upsert_chunks(self, batch_size: int = 64) -> dict:
        conn = db.get_conn()
        try:
            rows = conn.execute(
                "SELECT c.id, c.artifact_id, c.text, a.title"
                " FROM chunks c JOIN artifacts a ON a.id = c.artifact_id"
                " WHERE a.deleted_at IS NULL"
            ).fetchall()
        finally:
            conn.close()

        # The title is prepended for indexing only; the stored chunk text stays clean.
        #
        # Without this, a note whose title is the only place a name appears is
        # unfindable by that name. Measured: the Epictetus note is the author's own
        # paraphrase and never contains the word "Epictetus", so both dense and
        # sparse retrieval missed it entirely on "what did Epictetus say about
        # control". Hybrid did not help, because the term was not in the indexed
        # text at all.
        return self._index(
            self.CHUNKS,
            rows,
            text_of=lambda r: f"{r['title']}\n\n{r['text']}",
            payload_of=lambda r: {
                "artifact_id": r["artifact_id"],
                "chunk_id": r["id"],
                "embed_version": config.EMBED_VERSION,
            },
            batch_size=batch_size,
        )

    def upsert_facets(self, batch_size: int = 64) -> dict:
        conn = db.get_conn()
        try:
            rows = conn.execute(
                "SELECT id, artifact_id, level, statement, trust FROM facets"
            ).fetchall()
        finally:
            conn.close()

        return self._index(
            self.FACETS,
            rows,
            text_of=lambda r: r["statement"],
            payload_of=lambda r: {
                "artifact_id": r["artifact_id"],
                "facet_id": r["id"],
                "level": r["level"],
                "trust": r["trust"],
                "embed_version": config.EMBED_VERSION,
            },
            batch_size=batch_size,
        )

    def drop_artifact(self, name: str, artifact_id: str) -> None:
        """Remove every point belonging to one artifact."""
        from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue

        self.ensure()
        self._client_cache().delete(
            collection_name=name,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[FieldCondition(key="artifact_id", match=MatchValue(value=artifact_id))]
                )
            ),
        )

    def index_artifact(self, artifact_id: str) -> int:
        """Re-embed one artifact's chunks in place.

        The full `upsert_chunks` pass resets the collection, which is right for a
        rebuild and wrong for a save: it would drop the whole index every time a
        note is edited. This replaces one artifact's points and leaves the rest
        alone.
        """
        self.ensure()
        self.drop_artifact(self.CHUNKS, artifact_id)

        conn = db.get_conn()
        try:
            rows = conn.execute(
                "SELECT c.id, c.artifact_id, c.text, a.title"
                " FROM chunks c JOIN artifacts a ON a.id = c.artifact_id"
                " WHERE c.artifact_id = ? ORDER BY c.ordinal",
                (artifact_id,),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return 0

        # Title prepended for indexing only, exactly as in the full pass. See upsert_chunks.
        texts = [f"{r['title']}\n\n{r['text']}" for r in rows]
        dense = embed(texts)
        sparse = embed_sparse(texts)

        self._client_cache().upsert(
            collection_name=self.CHUNKS,
            points=[
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector={DENSE: d, SPARSE: SparseVector(indices=s[0], values=s[1])},
                    payload={
                        "artifact_id": r["artifact_id"],
                        "chunk_id": r["id"],
                        "embed_version": config.EMBED_VERSION,
                    },
                )
                for r, d, s in zip(rows, dense, sparse, strict=True)
            ],
        )
        return len(rows)

    def search(self, name: str, text: str, limit: int = 30, prefetch: int = 100) -> list[dict]:
        """Hybrid retrieval: dense and sparse, fused with RRF."""
        indices, values = embed_sparse_one(text)

        result = self._client_cache().query_points(
            collection_name=name,
            prefetch=[
                Prefetch(query=embed_one(text), using=DENSE, limit=prefetch),
                Prefetch(
                    query=SparseVector(indices=indices, values=values),
                    using=SPARSE,
                    limit=prefetch,
                ),
            ],
            query=FusionQuery(fusion=FusionKind.RRF),
            limit=limit,
            with_payload=True,
        )
        return [{"score": p.score, **dict(p.payload or {})} for p in result.points]

    def search_dense(self, name: str, text: str, limit: int = 30) -> list[dict]:
        """Dense only. Kept for the ablation that measures what sparse is worth."""
        result = self._client_cache().query_points(
            collection_name=name,
            query=embed_one(text),
            using=DENSE,
            limit=limit,
            with_payload=True,
        )
        return [{"score": p.score, **dict(p.payload or {})} for p in result.points]

    def counts(self) -> dict:
        qc = self._client_cache()
        out = {}
        for name in (self.CHUNKS, self.FACETS):
            try:
                out[name] = qc.get_collection(name).points_count
            except Exception:  # noqa: BLE001 - an absent collection is a count of zero
                out[name] = None
        return out


# Names used in payloads and prefetch queries; kept module-level so the methods
# read the same way they did before the interface existed.
DENSE = "dense"
SPARSE = "sparse"
