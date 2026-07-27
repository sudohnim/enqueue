"""Vector index, dense plus sparse, fused with Reciprocal Rank Fusion.

HARD RULE: payloads hold ids only. No text, no titles, no URLs, no excerpts.

Qdrant writes payloads unencrypted to disk. Putting chunk text there would write
plaintext excerpts of the entire hoard to an unencrypted store, which is exactly what
the encryption elsewhere exists to prevent. Text lives in SQLite and is fetched by id
after retrieval. This is cheap now and impossible to retrofit once an index exists.

Why hybrid: measured on a real corpus, "what did Epictetus say about control" returned
The Prince and The Odyssey and never the Epictetus note. Dense embeddings blur proper
nouns. Sparse is not an optimisation here, it is the difference between search working
and not working.
"""

from __future__ import annotations

import uuid
from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FusionQuery,
    Prefetch,
    PointStruct,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)
from qdrant_client.models import Fusion as FusionKind

from .. import config, db
from .embed import embed, embed_sparse, embed_sparse_one, embed_one

CHUNKS = "chunks"
FACETS = "facets"

DENSE = "dense"
SPARSE = "sparse"


@lru_cache(maxsize=1)
def client() -> QdrantClient:
    """Server if ENQ_QDRANT_URL is set, otherwise in process.

    In-process mode holds a lock on its directory, so the client is cached and the
    engine must be the only process touching it.
    """
    if config.QDRANT_URL:
        return QdrantClient(url=config.QDRANT_URL)
    config.QDRANT_PATH.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(config.QDRANT_PATH))


def _create(name: str) -> None:
    client().create_collection(
        collection_name=name,
        vectors_config={DENSE: VectorParams(size=config.EMBED_DIM, distance=Distance.COSINE)},
        sparse_vectors_config={SPARSE: SparseVectorParams(index=SparseIndexParams())},
    )


def ensure_collections() -> None:
    existing = {c.name for c in client().get_collections().collections}
    for name in (CHUNKS, FACETS):
        if name not in existing:
            _create(name)


def _reset(name: str) -> None:
    qc = client()
    if name in {c.name for c in qc.get_collections().collections}:
        qc.delete_collection(name)
    _create(name)


def _index(name: str, rows: list, text_of, payload_of, batch_size: int = 64) -> dict:
    _reset(name)
    qc = client()
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
                for r, d, s in zip(batch, dense, sparse)
            ],
        )
        total += len(batch)

    return {"indexed": total, "collection": name}


def index_chunks(batch_size: int = 64) -> dict:
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT c.id, c.artifact_id, c.text, a.title"
            " FROM chunks c JOIN artifacts a ON a.id = c.artifact_id"
        ).fetchall()
    finally:
        conn.close()

    # The title is prepended for indexing only; the stored chunk text stays clean.
    #
    # Without this, a note whose title is the only place a name appears is unfindable
    # by that name. Measured: the Epictetus note is the author's own paraphrase and
    # never contains the word "Epictetus", so both dense and sparse retrieval missed
    # it entirely on "what did Epictetus say about control". Hybrid did not help,
    # because the term was not in the indexed text at all.
    return _index(
        CHUNKS,
        rows,
        text_of=lambda r: f"{r['title']}\n\n{r['text']}",
        payload_of=lambda r: {
            "artifact_id": r["artifact_id"],
            "chunk_id": r["id"],
            "embed_version": config.EMBED_VERSION,
        },
        batch_size=batch_size,
    )


def index_facets(batch_size: int = 64) -> dict:
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, artifact_id, level, statement, trust FROM facets"
        ).fetchall()
    finally:
        conn.close()

    return _index(
        FACETS,
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


def drop_artifact(collection: str, artifact_id: str) -> None:
    """Remove every point belonging to one artifact."""
    from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue

    ensure_collections()
    client().delete(
        collection_name=collection,
        points_selector=FilterSelector(
            filter=Filter(
                must=[FieldCondition(key="artifact_id", match=MatchValue(value=artifact_id))]
            )
        ),
    )


def index_artifact(artifact_id: str) -> int:
    """Re-embed one artifact's chunks in place.

    The full `index_chunks` pass resets the collection, which is right for a rebuild
    and wrong for a save: it would drop the whole index every time a note is edited.
    This replaces one artifact's points and leaves the rest alone.
    """
    ensure_collections()
    drop_artifact(CHUNKS, artifact_id)

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

    # Title prepended for indexing only, exactly as in the full pass. See index_chunks.
    texts = [f"{r['title']}\n\n{r['text']}" for r in rows]
    dense = embed(texts)
    sparse = embed_sparse(texts)

    client().upsert(
        collection_name=CHUNKS,
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
            for r, d, s in zip(rows, dense, sparse)
        ],
    )
    return len(rows)


def search(collection: str, text: str, limit: int = 30, prefetch: int = 100) -> list[dict]:
    """Hybrid retrieval: dense and sparse, fused with RRF."""
    indices, values = embed_sparse_one(text)

    result = client().query_points(
        collection_name=collection,
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
    return [{"score": p.score, **p.payload} for p in result.points]


def search_dense(collection: str, text: str, limit: int = 30) -> list[dict]:
    """Dense only. Kept for the ablation that measures what sparse is worth."""
    result = client().query_points(
        collection_name=collection,
        query=embed_one(text),
        using=DENSE,
        limit=limit,
        with_payload=True,
    )
    return [{"score": p.score, **p.payload} for p in result.points]


def counts() -> dict:
    qc = client()
    out = {}
    for name in (CHUNKS, FACETS):
        try:
            out[name] = qc.get_collection(name).points_count
        except Exception:
            out[name] = None
    return out
