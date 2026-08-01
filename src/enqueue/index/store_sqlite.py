"""The sqlite-vec implementation of the VectorStore interface.

Everything Qdrant kept in a directory - vectors, sparse indices, payloads -
lives here inside the main SQLite file, which is the whole point of Part 3:
one file, exact recall (brute force), SQL joins instead of payload filters,
and no single-process directory lock.

The price is that brute-force search over 768-dim vectors is O(n) per query,
which is what Phase 19's bake-off measures. The latency gate is real work.

HARD RULE, inherited from the Qdrant backend: the index holds ids only. No
text, no titles, no URLs. Text lives in SQLite and is joined back by id
after retrieval. The vec0 tables carry chunk_id/facet_id plus the embedding;
artifact_id, level, and trust are read from `chunks` and `facets` in the
same database, in a second query kept in rank order.

Two sqlite-vec constraints that shape the code:

- A vec0 table needs the extension loaded on every connection that touches
  it, so this store opens its own connections (never db.get_conn) and loads
  sqlite_vec on each one. One connection per operation, which also makes the
  store safe to call from the API thread and the ingest worker thread at
  once.
- vec0 has no INSERT OR REPLACE (a primary-key conflict errors), so an
  "upsert" deletes the stale rows and inserts fresh ones in the same
  transaction. The bulk rebuilds clear their collection first, exactly like
  the Qdrant backend's reset-then-upsert.

The SQL lives in literal strings at module level: one bundle per collection,
values always bound with `?`. No statement is ever assembled from user
input, so any text can be searched and only the `?` placeholders carry data.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from sqlite3 import OperationalError

import sqlite_vec

from .. import config
from .embed import embed, embed_one
from .fusion import rrf_scored
from .store import VectorStore

# The embedding length the vec0 tables are built with. Equal to
# config.EMBED_DIM (768, BAAI/bge-base-en-v1.5); a dimension change is a new
# migration, so this stays a literal in both the migration and here.
DIM = 768

# Table DDL, one (drop, create) pair per index table. Shared by `ensure`
# (create if missing) and `reset` (drop and recreate), so the shape of the
# index tables is defined exactly once. Migration 0010 carries the same DDL
# with IF NOT EXISTS; the two can never fight.
_DDL = {
    "vec_chunks": (
        "DROP TABLE IF EXISTS vec_chunks",
        "CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0("
        " chunk_id TEXT PRIMARY KEY, embedding float[768])",
    ),
    "vec_facets": (
        "DROP TABLE IF EXISTS vec_facets",
        "CREATE VIRTUAL TABLE IF NOT EXISTS vec_facets USING vec0("
        " facet_id TEXT PRIMARY KEY, embedding float[768])",
    ),
    "fts_chunks": (
        "DROP TABLE IF EXISTS fts_chunks",
        "CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5(" " chunk_id UNINDEXED, text)",
    ),
    "fts_facets": (
        "DROP TABLE IF EXISTS fts_facets",
        "CREATE VIRTUAL TABLE IF NOT EXISTS fts_facets USING fts5(" " facet_id UNINDEXED, text)",
    ),
}

# Which index tables make up each collection.
_COLLECTION_TABLES = {
    "chunks": ("vec_chunks", "fts_chunks"),
    "facets": ("vec_facets", "fts_facets"),
}

# Literal SQL per collection. The id column is selected as `id` so every
# branch reads row["id"]; values are always bound, never interpolated.
_SQL = {
    "chunks": {
        "select_all": (
            "SELECT c.id, c.text, a.title"
            " FROM chunks c JOIN artifacts a ON a.id = c.artifact_id"
            " WHERE a.deleted_at IS NULL"
        ),
        "clear_vec": "DELETE FROM vec_chunks",
        "clear_fts": "DELETE FROM fts_chunks",
        "insert_vec": "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)",
        "insert_fts": "INSERT INTO fts_chunks (chunk_id, text) VALUES (?, ?)",
        "dense": (
            "SELECT chunk_id AS id, distance FROM vec_chunks"
            " WHERE embedding MATCH ? ORDER BY distance LIMIT ?"
        ),
        "keyword": (
            "SELECT chunk_id AS id, bm25(fts_chunks) AS raw FROM fts_chunks"
            " WHERE fts_chunks MATCH ? ORDER BY bm25(fts_chunks) LIMIT ?"
        ),
    },
    "facets": {
        "select_all": "SELECT id, statement FROM facets",
        "clear_vec": "DELETE FROM vec_facets",
        "clear_fts": "DELETE FROM fts_facets",
        "insert_vec": "INSERT INTO vec_facets (facet_id, embedding) VALUES (?, ?)",
        "insert_fts": "INSERT INTO fts_facets (facet_id, text) VALUES (?, ?)",
        "dense": (
            "SELECT facet_id AS id, distance FROM vec_facets"
            " WHERE embedding MATCH ? ORDER BY distance LIMIT ?"
        ),
        "keyword": (
            "SELECT facet_id AS id, bm25(fts_facets) AS raw FROM fts_facets"
            " WHERE fts_facets MATCH ? ORDER BY bm25(fts_facets) LIMIT ?"
        ),
    },
}

_COUNT_SQL = {
    "vec_chunks": "SELECT COUNT(*) FROM vec_chunks",
    "vec_facets": "SELECT COUNT(*) FROM vec_facets",
    "fts_chunks": "SELECT COUNT(*) FROM fts_chunks",
    "fts_facets": "SELECT COUNT(*) FROM fts_facets",
}

# The text a chunk is embedded and indexed under. The title is prepended for
# indexing only; the stored chunk text stays clean. Without this, a note
# whose title is the only place a name appears is unfindable by that name
# (measured in Part 1: the Epictetus note is the author's own paraphrase and
# never contains the word "Epictetus").
CHUNK_INDEX_TEXT = "{title}\n\n{text}"


def _fts_query(text: str) -> str:
    """Make arbitrary user text a valid FTS5 prefix query.

    Every whitespace-separated token is quoted, with embedded quotes doubled,
    so operators (AND, OR, NOT, NEAR, *) and punctuation are treated as
    literal terms instead of query syntax. Each token then gets a prefix
    star *outside* the quotes, so a partial word matches ("hydr" finds
    "hydroponics") while quoted terms stay literal. An empty string stays
    empty, and the caller treats that as "match nothing".
    """
    tokens = text.split()
    return " ".join('"' + token.replace('"', '""') + '"*' for token in tokens)


class SqliteVecStore(VectorStore):
    """SQLite-backed search index, one file with the library."""

    def __init__(self, on_progress: Callable[[int, int], None] | None = None) -> None:
        """`on_progress(indexed, total)` is called every 500 rows of a rebuild."""
        self._on_progress = on_progress

    # -- connections ------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return conn

    # -- collections ------------------------------------------------------

    def _sql(self, name: str) -> dict:
        if name not in _SQL:
            raise ValueError(f"unknown collection {name!r}")
        return _SQL[name]

    def _id_col(self, name: str) -> str:
        if name == self.CHUNKS:
            return "chunk_id"
        if name == self.FACETS:
            return "facet_id"
        raise ValueError(f"unknown collection {name!r}")

    def ensure(self) -> None:
        """Create the index tables if they do not exist.

        Safe to call repeatedly. IF NOT EXISTS everywhere means this can also
        run before alembic ever has: migration 0010 uses the same DDL, so the
        two paths cannot fight.
        """
        conn = self._connect()
        try:
            for table in _DDL:
                conn.execute(_DDL[table][1])
        finally:
            conn.close()

    def reset(self, name: str) -> None:
        """Drop and recreate one collection. For a full rebuild."""
        if name not in _COLLECTION_TABLES:
            raise ValueError(f"unknown collection {name!r}")
        conn = self._connect()
        try:
            for table in _COLLECTION_TABLES[name]:
                conn.execute(_DDL[table][0])
                conn.execute(_DDL[table][1])
        finally:
            conn.close()

    # -- writing ----------------------------------------------------------

    def upsert_chunks(self, batch_size: int = 64) -> dict:
        return self._rebuild(
            self.CHUNKS,
            lambda row: CHUNK_INDEX_TEXT.format(title=row["title"], text=row["text"]),
            batch_size,
        )

    def upsert_facets(self, batch_size: int = 64) -> dict:
        return self._rebuild(self.FACETS, lambda row: row["statement"], batch_size)

    def _rebuild(self, name: str, text_of, batch_size: int) -> dict:
        """Rebuild one collection from its source table, in place.

        Clear the collection, then embed and insert in batches of
        `batch_size`. Each batch writes the vector table and the keyword
        table in one transaction, so the two can never diverge mid-write.
        """
        self.ensure()
        sql = self._sql(name)

        conn = self._connect()
        try:
            rows = conn.execute(sql["select_all"]).fetchall()
            entries = [(row["id"], text_of(row)) for row in rows]
        finally:
            conn.close()

        with self._connect() as conn:
            conn.execute(sql["clear_vec"])
            conn.execute(sql["clear_fts"])

        total = 0
        for start in range(0, len(entries), batch_size):
            batch = entries[start : start + batch_size]
            vectors = embed([text for _, text in batch])
            with self._connect() as conn:
                conn.executemany(
                    sql["insert_vec"],
                    [
                        (item_id, json.dumps(vector))
                        for (item_id, _), vector in zip(batch, vectors, strict=True)
                    ],
                )
                conn.executemany(sql["insert_fts"], [(item_id, text) for item_id, text in batch])
            total += len(batch)
            if self._on_progress and (total % 500 == 0 or total == len(entries)):
                self._on_progress(total, len(entries))

        return {"indexed": total, "collection": name}

    def index_artifact(self, artifact_id: str) -> int:
        """Re-embed one artifact's chunks in place.

        The full `upsert_chunks` pass clears the collection, which is right
        for a rebuild and wrong for a save: it would drop the whole index
        every time a note is edited. This replaces one artifact's rows and
        leaves the rest alone. The queue re-chunks the artifact before
        calling, so this reads the fresh chunk rows.
        """
        self.ensure()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT c.id, c.text, a.title"
                " FROM chunks c JOIN artifacts a ON a.id = c.artifact_id"
                " WHERE c.artifact_id = ? ORDER BY c.ordinal",
                (artifact_id,),
            ).fetchall()
            if not rows:
                return 0

            entries = [
                (row["id"], CHUNK_INDEX_TEXT.format(title=row["title"], text=row["text"]))
                for row in rows
            ]
            vectors = embed([text for _, text in entries])

            conn.execute(
                "DELETE FROM vec_chunks"
                " WHERE chunk_id IN (SELECT id FROM chunks WHERE artifact_id = ?)",
                (artifact_id,),
            )
            conn.execute(
                "DELETE FROM fts_chunks"
                " WHERE chunk_id IN (SELECT id FROM chunks WHERE artifact_id = ?)",
                (artifact_id,),
            )
            conn.executemany(
                "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)",
                [
                    (item_id, json.dumps(vector))
                    for (item_id, _), vector in zip(entries, vectors, strict=True)
                ],
            )
            conn.executemany(
                "INSERT INTO fts_chunks (chunk_id, text) VALUES (?, ?)",
                [(item_id, text) for item_id, text in entries],
            )
        return len(entries)

    def drop_artifact(self, name: str, artifact_id: str) -> None:
        """Remove every indexed row belonging to one artifact.

        Both the vector and the keyword table for the collection lose the
        artifact's ids in one transaction.
        """
        self.ensure()
        with self._connect() as conn:
            if name == self.CHUNKS:
                conn.execute(
                    "DELETE FROM vec_chunks"
                    " WHERE chunk_id IN (SELECT id FROM chunks WHERE artifact_id = ?)",
                    (artifact_id,),
                )
                conn.execute(
                    "DELETE FROM fts_chunks"
                    " WHERE chunk_id IN (SELECT id FROM chunks WHERE artifact_id = ?)",
                    (artifact_id,),
                )
            elif name == self.FACETS:
                conn.execute(
                    "DELETE FROM vec_facets"
                    " WHERE facet_id IN (SELECT id FROM facets WHERE artifact_id = ?)",
                    (artifact_id,),
                )
                conn.execute(
                    "DELETE FROM fts_facets"
                    " WHERE facet_id IN (SELECT id FROM facets WHERE artifact_id = ?)",
                    (artifact_id,),
                )
            else:
                raise ValueError(f"unknown collection {name!r}")

    def write_embed_version(self) -> None:
        """Record which embedding version the index was built at.

        Called only once both collections are rebuilt, so the stored version
        never claims an index that is half updated.
        """
        self.ensure()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO index_meta (key, value) VALUES ('embed_version', ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (config.EMBED_VERSION,),
            )

    # -- reading ----------------------------------------------------------

    def search_dense(self, name: str, text: str, limit: int = 30) -> list[dict]:
        """Vector nearest-neighbour only, for ablations. Same hit shape as `search`."""
        query = json.dumps(embed_one(text))
        conn = self._connect()
        try:
            rows = conn.execute(self._sql(name)["dense"], (query, limit)).fetchall()
            ranked = [(row["id"], 1.0 / (1.0 + row["distance"])) for row in rows]
            return self._fetch_hits(conn, name, ranked)
        finally:
            conn.close()

    def _search_keyword(self, name: str, text: str, limit: int) -> list[dict]:
        """FTS5 BM25 only, for the fusion inside `search`."""
        query = _fts_query(text)
        if not query:
            return []
        conn = self._connect()
        try:
            rows = conn.execute(self._sql(name)["keyword"], (query, limit)).fetchall()
            # bm25() returns negative values, lower is better; flip so hits
            # carry a higher-is-better score like every other branch.
            ranked = [(row["id"], -row["raw"]) for row in rows]
            return self._fetch_hits(conn, name, ranked)
        finally:
            conn.close()

    def search(self, name: str, text: str, limit: int = 30, prefetch: int = 100) -> list[dict]:
        """Hybrid retrieval: dense and keyword, fused with reciprocal rank fusion.

        Each branch is searched with `prefetch` candidates, the same window
        the Qdrant backend used, then the two ranked id lists are fused and
        the top `limit` hits returned with their fused score.
        """
        dense = self.search_dense(name, text, limit=prefetch)
        keyword = self._search_keyword(name, text, limit=prefetch)
        id_col = self._id_col(name)

        fused = rrf_scored(
            [hit[id_col] for hit in dense],
            [hit[id_col] for hit in keyword],
            # k=1 reproduces the Qdrant backend's fused score scale: their RRF
            # is 1/(pos + 2) over 0-based positions, which is 1/(rank + 1)
            # over 1-based ranks. The lens score threshold was calibrated on
            # that scale, so scores have to be comparable across engines.
            # Ranking is k-invariant, so this changes magnitudes only.
            k=1,
            limit=limit,
        )
        by_id = {hit[id_col]: hit for hit in dense}
        by_id.update({hit[id_col]: hit for hit in keyword})
        return [
            {**by_id[item_id], "score": round(score, 6)}
            for item_id, score in fused
            if item_id in by_id
        ]

    def _fetch_hits(self, conn: sqlite3.Connection, name: str, ranked: list) -> list[dict]:
        """Attach payload ids to ranked (id, score) pairs, preserving rank order.

        The json_each IN pattern is the app's sanctioned way to bind an id
        list; a source row that vanished after ranking is dropped rather than
        served stale.
        """
        if not ranked:
            return []
        ids = json.dumps([item_id for item_id, _ in ranked])

        if name == self.CHUNKS:
            rows = conn.execute(
                "SELECT id, artifact_id FROM chunks"
                " WHERE id IN (SELECT value FROM json_each(?))",
                (ids,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, artifact_id, level, trust FROM facets"
                " WHERE id IN (SELECT value FROM json_each(?))",
                (ids,),
            ).fetchall()
        by_id = {row["id"]: row for row in rows}

        out = []
        for item_id, score in ranked:
            row = by_id.get(item_id)
            if row is None:
                continue
            hit = {"score": round(score, 6), "artifact_id": row["artifact_id"]}
            if name == self.CHUNKS:
                hit["chunk_id"] = item_id
            else:
                hit["facet_id"] = item_id
                hit["level"] = row["level"]
                hit["trust"] = row["trust"]
            out.append(hit)
        return out

    def counts(self) -> dict:
        """Row counts for all four index tables.

        Keyed by collection for the interface consumers (`chunks`, `facets`)
        with the keyword tables alongside; a table that does not exist counts
        as None, matching the Qdrant backend's "absent collection" shape.
        """
        conn = self._connect()
        try:

            def _n(table: str) -> int | None:
                try:
                    return conn.execute(_COUNT_SQL[table]).fetchone()[0]
                except OperationalError:
                    return None

            return {
                "chunks": _n("vec_chunks"),
                "facets": _n("vec_facets"),
                "fts_chunks": _n("fts_chunks"),
                "fts_facets": _n("fts_facets"),
            }
        finally:
            conn.close()
