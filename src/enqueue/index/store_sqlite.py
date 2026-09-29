"""sqlite-vec implementation of VectorStore: vec0 + FTS5 tables inside the library file.

The index holds ids only; text is joined back from SQLite by id. Every connection
loads the sqlite_vec extension, so the store opens its own (never db.get_conn).
vec0 has no INSERT OR REPLACE, so an upsert is delete-then-insert in one transaction.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from itertools import groupby
from sqlite3 import OperationalError
from typing import Any

import sqlite_vec

from .. import config, db
from .embed import embed, embed_passage, embed_query
from .fusion import rrf_scored
from .store import VectorStore

# Embedding length (config.EMBED_DIM). A change is a new migration.
DIM = 768

# (drop, create) per index table, shared by `ensure` and `reset`. Migration 0010 has the same DDL.
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
        "CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5("
        " chunk_id UNINDEXED, title, text)",
    ),
    "fts_chunks_tri": (
        "DROP TABLE IF EXISTS fts_chunks_tri",
        "CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks_tri USING fts5("
        " chunk_id UNINDEXED, text, tokenize='trigram')",
    ),
    "fts_facets": (
        "DROP TABLE IF EXISTS fts_facets",
        "CREATE VIRTUAL TABLE IF NOT EXISTS fts_facets USING fts5(" " facet_id UNINDEXED, text)",
    ),
    "vec_entities": (
        "DROP TABLE IF EXISTS vec_entities",
        "CREATE VIRTUAL TABLE IF NOT EXISTS vec_entities USING vec0("
        " entity_id TEXT PRIMARY KEY, embedding float[768])",
    ),
    "fts_entities": (
        "DROP TABLE IF EXISTS fts_entities",
        "CREATE VIRTUAL TABLE IF NOT EXISTS fts_entities USING fts5(" " entity_id UNINDEXED, text)",
    ),
    "vec_sections": (
        "DROP TABLE IF EXISTS vec_sections",
        "CREATE VIRTUAL TABLE IF NOT EXISTS vec_sections USING vec0("
        " section_id TEXT PRIMARY KEY, embedding float[768])",
    ),
    "fts_sections": (
        "DROP TABLE IF EXISTS fts_sections",
        "CREATE VIRTUAL TABLE IF NOT EXISTS fts_sections USING fts5("
        " section_id UNINDEXED, text)",
    ),
}

_COLLECTION_TABLES = {
    "chunks": ("vec_chunks", "fts_chunks", "fts_chunks_tri"),
    "facets": ("vec_facets", "fts_facets"),
    "entities": ("vec_entities", "fts_entities"),
    "sections": ("vec_sections", "fts_sections"),
}

# Literal SQL per collection; values always bound, never interpolated.
# bm25 weights map to every column, UNINDEXED included: (chunk_id, title, text) = (1, 10, 1).
_SQL = {
    "chunks": {
        "select_all": (
            "SELECT c.id, c.text, c.context, a.title"
            " FROM chunks c JOIN artifacts a ON a.id = c.artifact_id"
            " WHERE a.deleted_at IS NULL AND a.vaulted_at IS NULL AND a.embedded_at IS NULL"
        ),
        "clear_vec": "DELETE FROM vec_chunks",
        "clear_fts": "DELETE FROM fts_chunks",
        "clear_fts_tri": "DELETE FROM fts_chunks_tri",
        "insert_vec": "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)",
        "insert_fts": "INSERT INTO fts_chunks (chunk_id, title, text) VALUES (?, ?, ?)",
        "insert_fts_tri": "INSERT INTO fts_chunks_tri (chunk_id, text) VALUES (?, ?)",
        "dense": (
            "SELECT chunk_id AS id, distance FROM vec_chunks"
            " WHERE embedding MATCH ? ORDER BY distance LIMIT ?"
        ),
        "keyword": (
            "SELECT chunk_id AS id, bm25(fts_chunks, 1.0, 10.0, 1.0) AS raw FROM fts_chunks"
            " WHERE fts_chunks MATCH ? ORDER BY bm25(fts_chunks, 1.0, 10.0, 1.0) LIMIT ?"
        ),
        "keyword_tri": (
            "SELECT chunk_id AS id, bm25(fts_chunks_tri) AS raw FROM fts_chunks_tri"
            " WHERE fts_chunks_tri MATCH ? ORDER BY bm25(fts_chunks_tri) LIMIT ?"
        ),
    },
    "facets": {
        "select_all": "SELECT id, statement FROM facets",
        "select_artifact": (
            "SELECT id, statement AS text FROM facets WHERE artifact_id = ? ORDER BY level"
        ),
        "drop_vec": (
            "DELETE FROM vec_facets"
            " WHERE facet_id IN (SELECT id FROM facets WHERE artifact_id = ?)"
        ),
        "drop_fts": (
            "DELETE FROM fts_facets"
            " WHERE facet_id IN (SELECT id FROM facets WHERE artifact_id = ?)"
        ),
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
    "entities": {
        "select_all": "SELECT id, fact FROM entities",
        "select_artifact": (
            "SELECT id, fact AS text FROM entities WHERE artifact_id = ? ORDER BY entity"
        ),
        "drop_vec": (
            "DELETE FROM vec_entities"
            " WHERE entity_id IN (SELECT id FROM entities WHERE artifact_id = ?)"
        ),
        "drop_fts": (
            "DELETE FROM fts_entities"
            " WHERE entity_id IN (SELECT id FROM entities WHERE artifact_id = ?)"
        ),
        "clear_vec": "DELETE FROM vec_entities",
        "clear_fts": "DELETE FROM fts_entities",
        "insert_vec": "INSERT INTO vec_entities (entity_id, embedding) VALUES (?, ?)",
        "insert_fts": "INSERT INTO fts_entities (entity_id, text) VALUES (?, ?)",
        "dense": (
            "SELECT entity_id AS id, distance FROM vec_entities"
            " WHERE embedding MATCH ? ORDER BY distance LIMIT ?"
        ),
        "keyword": (
            "SELECT entity_id AS id, bm25(fts_entities) AS raw FROM fts_entities"
            " WHERE fts_entities MATCH ? ORDER BY bm25(fts_entities) LIMIT ?"
        ),
    },
    "sections": {
        "select_all": "SELECT id, summary FROM sections",
        "select_artifact": (
            "SELECT id, summary AS text FROM sections WHERE artifact_id = ? ORDER BY ordinal"
        ),
        "drop_vec": (
            "DELETE FROM vec_sections"
            " WHERE section_id IN (SELECT id FROM sections WHERE artifact_id = ?)"
        ),
        "drop_fts": (
            "DELETE FROM fts_sections"
            " WHERE section_id IN (SELECT id FROM sections WHERE artifact_id = ?)"
        ),
        "clear_vec": "DELETE FROM vec_sections",
        "clear_fts": "DELETE FROM fts_sections",
        "insert_vec": "INSERT INTO vec_sections (section_id, embedding) VALUES (?, ?)",
        "insert_fts": "INSERT INTO fts_sections (section_id, text) VALUES (?, ?)",
        "dense": (
            "SELECT section_id AS id, distance FROM vec_sections"
            " WHERE embedding MATCH ? ORDER BY distance LIMIT ?"
        ),
        "keyword": (
            "SELECT section_id AS id, bm25(fts_sections) AS raw FROM fts_sections"
            " WHERE fts_sections MATCH ? ORDER BY bm25(fts_sections) LIMIT ?"
        ),
    },
}

_COUNT_SQL = {
    "vec_chunks": "SELECT COUNT(*) FROM vec_chunks",
    "vec_facets": "SELECT COUNT(*) FROM vec_facets",
    "vec_entities": "SELECT COUNT(*) FROM vec_entities",
    "fts_chunks": "SELECT COUNT(*) FROM fts_chunks",
    "fts_chunks_tri": "SELECT COUNT(*) FROM fts_chunks_tri",
    "fts_facets": "SELECT COUNT(*) FROM fts_facets",
    "fts_entities": "SELECT COUNT(*) FROM fts_entities",
    "vec_sections": "SELECT COUNT(*) FROM vec_sections",
    "fts_sections": "SELECT COUNT(*) FROM fts_sections",
}

# Title (and the chunk's model-written context, when it has one) are prepended for
# embedding only; stored chunk text stays clean.
CHUNK_INDEX_TEXT = "{title}\n\n{text}"
CHUNK_INDEX_TEXT_WITH_CONTEXT = "{title}\n\n{context}\n\n{text}"

# On an RRF tie, the keyword leg reorders only if its best beats the runner-up by 20%.
KEYWORD_MARGIN = 0.2


def _chunk_entries(row) -> tuple[str, tuple[str, str], str]:
    """(embed_text, (fts_title, fts_text), trigram_text) for one chunk row.

    A leading "# {title}" heading is dropped from fts_text so the title term is
    counted only in the weighted title column. A chunk's context (ingest/context.py)
    is embedded with it and added to its keyword text, so words the context adds are
    searchable; the trigram table keeps the chunk's own words only.
    """
    title = row["title"] or ""
    text = row["text"] or ""
    context = (row["context"] if "context" in row.keys() else None) or ""
    fts_text = text
    heading = f"# {title}"
    if title and text.startswith(heading):
        fts_text = text[len(heading) :].lstrip("\n").strip()
    if context:
        return (
            CHUNK_INDEX_TEXT_WITH_CONTEXT.format(title=title, context=context, text=text),
            (title, context + "\n\n" + fts_text),
            fts_text,
        )
    return (
        CHUNK_INDEX_TEXT.format(title=title, text=text),
        (title, fts_text),
        fts_text,
    )


def _fts_query(text: str) -> str:
    """User text as a literal FTS5 prefix query: each token quoted, then `*`."""
    tokens = text.split()
    return " ".join('"' + token.replace('"', '""') + '"*' for token in tokens)


def _trigram_query(text: str) -> str:
    """User text as an OR of quoted trigram tokens (3+ chars). Empty means skip."""
    tokens = [t for t in text.split() if len(t) >= 3]
    return " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)


class SqliteVecStore(VectorStore):
    """SQLite-backed search index, one file with the library."""

    def __init__(self, on_progress: Callable[[int, int], None] | None = None) -> None:
        """`on_progress(indexed, total)` is called every 500 rows of a rebuild."""
        self._on_progress = on_progress

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(config.DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        db.set_wal(conn)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return conn

    def _sql(self, name: str) -> dict:
        if name not in _SQL:
            raise ValueError(f"unknown collection {name!r}")
        return _SQL[name]

    def _id_col(self, name: str) -> str:
        if name == self.CHUNKS:
            return "chunk_id"
        if name == self.FACETS:
            return "facet_id"
        if name == self.ENTITIES:
            return "entity_id"
        if name == self.SECTIONS:
            return "section_id"
        raise ValueError(f"unknown collection {name!r}")

    def ensure(self) -> None:
        """Create missing index tables. Recreates a pre-title-column `fts_chunks`."""
        conn = self._connect()
        try:
            for table in _DDL:
                conn.execute(_DDL[table][1])
            columns = [row["name"] for row in conn.execute("PRAGMA table_info(fts_chunks)")]
            if "title" not in columns:
                conn.execute(_DDL["fts_chunks"][0])
                conn.execute(_DDL["fts_chunks"][1])
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

    def upsert_chunks(self, batch_size: int = 64) -> dict:
        return self._rebuild(self.CHUNKS, _chunk_entries, batch_size)

    def upsert_facets(self, batch_size: int = 64) -> dict:
        return self._rebuild(
            self.FACETS, lambda row: (row["statement"], (row["statement"],)), batch_size
        )

    def upsert_entities(self, batch_size: int = 64) -> dict:
        return self._rebuild(self.ENTITIES, lambda row: (row["fact"], (row["fact"],)), batch_size)

    def upsert_sections(self, batch_size: int = 64) -> dict:
        return self._rebuild(
            self.SECTIONS, lambda row: (row["summary"], (row["summary"],)), batch_size
        )

    def _rebuild(self, name: str, entries_of, batch_size: int) -> dict:
        """Clear one collection, then embed and insert in batches, vec + fts per transaction.

        `entries_of(row)` returns `(embed_text, fts_columns_after_id)`.
        """
        self.ensure()
        sql = self._sql(name)

        conn = self._connect()
        try:
            rows = conn.execute(sql["select_all"]).fetchall()
            entries = [(row["id"], *entries_of(row)) for row in rows]
        finally:
            conn.close()

        with self._connect() as conn:
            conn.execute(sql["clear_vec"])
            conn.execute(sql["clear_fts"])
            if name == self.CHUNKS:
                conn.execute(sql["clear_fts_tri"])

        total = 0
        for start in range(0, len(entries), batch_size):
            batch = entries[start : start + batch_size]
            vectors = embed([entry[1] for entry in batch])
            with self._connect() as conn:
                conn.executemany(
                    sql["insert_vec"],
                    [
                        (entry[0], json.dumps(vector))
                        for entry, vector in zip(batch, vectors, strict=True)
                    ],
                )
                conn.executemany(sql["insert_fts"], [(entry[0], *entry[2]) for entry in batch])
                if name == self.CHUNKS:
                    conn.executemany(
                        sql["insert_fts_tri"], [(entry[0], entry[3]) for entry in batch]
                    )
            total += len(batch)
            if self._on_progress and (total % 500 == 0 or total == len(entries)):
                self._on_progress(total, len(entries))

        return {"indexed": total, "collection": name}

    def index_artifact(self, artifact_id: str) -> int:
        """Re-embed one artifact's chunks in place. The caller re-chunks first."""
        self.ensure()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT c.id, c.text, c.context, a.title"
                " FROM chunks c JOIN artifacts a ON a.id = c.artifact_id"
                " WHERE c.artifact_id = ? ORDER BY c.ordinal",
                (artifact_id,),
            ).fetchall()
            if not rows:
                return 0

            entries = [(row["id"], *_chunk_entries(row)) for row in rows]
            vectors = embed([entry[1] for entry in entries])

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
            conn.execute(
                "DELETE FROM fts_chunks_tri"
                " WHERE chunk_id IN (SELECT id FROM chunks WHERE artifact_id = ?)",
                (artifact_id,),
            )
            conn.executemany(
                "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)",
                [
                    (entry[0], json.dumps(vector))
                    for entry, vector in zip(entries, vectors, strict=True)
                ],
            )
            conn.executemany(
                "INSERT INTO fts_chunks (chunk_id, title, text) VALUES (?, ?, ?)",
                [(entry[0], *entry[2]) for entry in entries],
            )
            conn.executemany(
                "INSERT INTO fts_chunks_tri (chunk_id, text) VALUES (?, ?)",
                [(entry[0], entry[3]) for entry in entries],
            )
        return len(entries)

    def index_facets_artifact(self, artifact_id: str) -> int:
        """Re-embed one artifact's facets in place. The caller generates them first."""
        return self._index_layer_artifact(self.FACETS, artifact_id)

    def index_entities_artifact(self, artifact_id: str) -> int:
        """Re-embed one artifact's entity lines in place. The caller generates them first."""
        return self._index_layer_artifact(self.ENTITIES, artifact_id)

    def index_sections_artifact(self, artifact_id: str) -> int:
        """Re-embed one artifact's section summaries in place (ingest/source.py writes them)."""
        return self._index_layer_artifact(self.SECTIONS, artifact_id)

    def _index_layer_artifact(self, name: str, artifact_id: str) -> int:
        """Replace one artifact's rows in a facet-like layer's vec and fts tables."""
        self.ensure()
        sql = self._sql(name)
        with self._connect() as conn:
            rows = conn.execute(sql["select_artifact"], (artifact_id,)).fetchall()
            conn.execute(sql["drop_vec"], (artifact_id,))
            conn.execute(sql["drop_fts"], (artifact_id,))
            if not rows:
                return 0
            vectors = embed([row["text"] for row in rows])
            conn.executemany(
                sql["insert_vec"],
                [(row["id"], json.dumps(v)) for row, v in zip(rows, vectors, strict=True)],
            )
            conn.executemany(sql["insert_fts"], [(row["id"], row["text"]) for row in rows])
        return len(rows)

    def drop_artifact(self, name: str, artifact_id: str) -> None:
        """Remove one artifact's rows from a collection's vec and fts tables."""
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
                conn.execute(
                    "DELETE FROM fts_chunks_tri"
                    " WHERE chunk_id IN (SELECT id FROM chunks WHERE artifact_id = ?)",
                    (artifact_id,),
                )
            else:
                sql = self._sql(name)
                conn.execute(sql["drop_vec"], (artifact_id,))
                conn.execute(sql["drop_fts"], (artifact_id,))

    def write_embed_version(self) -> None:
        """Record the embedding version. Call only after every collection is rebuilt."""
        self.ensure()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO index_meta (key, value) VALUES ('embed_version', ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (config.EMBED_VERSION,),
            )

    def search_dense(
        self, name: str, text: str, limit: int = 30, as_query: bool = True
    ) -> list[dict]:
        """Vector leg only. `score` is cosine similarity in [0, 1]. `as_query=False`
        embeds `text` as a passage, for passage-to-passage similarity."""
        conn = self._connect()
        try:
            return self._dense(conn, name, text, limit, as_query)
        finally:
            conn.close()

    def search_keyword(self, name: str, text: str, limit: int = 30) -> list[dict]:
        """FTS5 BM25 leg only."""
        conn = self._connect()
        try:
            return self._keyword(conn, name, text, limit)
        finally:
            conn.close()

    def search_trigram(self, name: str, text: str, limit: int = 30) -> list[dict]:
        """FTS5 trigram leg only (chunks only)."""
        conn = self._connect()
        try:
            return self._trigram(conn, name, text, limit)
        finally:
            conn.close()

    # Legs take a caller's connection: one search opens one connection (~0.6 ms each).
    # A missing table (upgraded DB before its first write, minimal test corpus) yields no hits.

    def _dense(
        self, conn: sqlite3.Connection, name: str, text: str, limit: int, as_query: bool = True
    ) -> list[dict]:
        query = json.dumps(embed_query(text) if as_query else embed_passage(text))
        try:
            rows = conn.execute(self._sql(name)["dense"], (query, limit)).fetchall()
            # Unit-norm vectors, L2 distance d: cosine = 1 - d^2/2 (Q.2b).
            ranked = [
                (row["id"], max(0.0, min(1.0, 1.0 - (row["distance"] ** 2) / 2.0))) for row in rows
            ]
            return self._fetch_hits(conn, name, ranked)
        except OperationalError:
            return []

    def _keyword(self, conn: sqlite3.Connection, name: str, text: str, limit: int) -> list[dict]:
        query = _fts_query(text)
        if not query:
            return []
        try:
            rows = conn.execute(self._sql(name)["keyword"], (query, limit)).fetchall()
            # bm25 is lower-is-better; flip it.
            ranked = [(row["id"], -row["raw"]) for row in rows]
            return self._fetch_hits(conn, name, ranked)
        except OperationalError:
            return []

    def _trigram(self, conn: sqlite3.Connection, name: str, text: str, limit: int) -> list[dict]:
        sql = self._sql(name).get("keyword_tri")
        query = _trigram_query(text)
        if not sql or not query:
            return []
        try:
            rows = conn.execute(sql, (query, limit)).fetchall()
            ranked = [(row["id"], -row["raw"]) for row in rows]
            return self._fetch_hits(conn, name, ranked)
        except OperationalError:
            return []

    def search(self, name: str, text: str, limit: int = 30, prefetch: int = 100) -> list[dict]:
        """Dense + keyword fused with RRF, trigram as a recall net. Top `limit`."""
        return self.search_legs(name, text, limit=limit, prefetch=prefetch)["fused"]

    def search_legs(
        self, name: str, text: str, limit: int = 30, prefetch: int = 100
    ) -> dict[str, list[dict]]:
        """The fused `search` result plus the raw legs it came from, on one connection."""
        conn = self._connect()
        try:
            dense = self._dense(conn, name, text, prefetch)
            keyword = self._keyword(conn, name, text, prefetch)
            trigram = self._trigram(conn, name, text, prefetch) if name == self.CHUNKS else []
        finally:
            conn.close()
        return {
            "fused": self._fuse(name, dense, keyword, trigram, limit),
            "dense": dense,
            "keyword": keyword,
            "trigram": trigram,
        }

    def _fuse(
        self, name: str, dense: list[dict], keyword: list[dict], trigram: list[dict], limit: int
    ) -> list[dict]:
        """RRF (k=60) over dense + keyword; trigram hits appended after with score 0."""
        id_col = self._id_col(name)
        dense_ids = [hit[id_col] for hit in dense]
        keyword_ids = [hit[id_col] for hit in keyword]
        keyword_score = {hit[id_col]: hit["score"] for hit in keyword}

        fused = rrf_scored(
            dense_ids,
            keyword_ids,
            k=60,
            limit=limit,
        )
        by_id = {hit[id_col]: hit for hit in dense}
        by_id.update({hit[id_col]: hit for hit in keyword})
        ordered: list[tuple[Any, float]] = []
        # Equal RRF scores are contiguous; let a confident keyword winner lead its tie run.
        for _, group in groupby(fused, key=lambda entry: entry[1]):
            run = list(group)
            if len(run) > 1:
                scored = sorted(
                    ((item, keyword_score[item]) for item, _ in run if item in keyword_score),
                    key=lambda pair: pair[1],
                    reverse=True,
                )
                if len(scored) >= 2:
                    best, second = scored[0][1], scored[1][1]
                    if best > second and (best - second) / best >= KEYWORD_MARGIN:
                        winner = scored[0][0]
                        run = [entry for entry in run if entry[0] == winner] + [
                            entry for entry in run if entry[0] != winner
                        ]
            ordered.extend(run)

        if trigram:
            by_id.update({hit[id_col]: hit for hit in trigram})
            known = {item_id for item_id, _ in ordered}
            for hit in trigram:
                item_id = hit[id_col]
                if item_id not in known:
                    ordered.append((item_id, 0.0))
                    known.add(item_id)
        return [
            {**by_id[item_id], "score": round(score, 6)}
            for item_id, score in ordered
            if item_id in by_id
        ]

    def _fetch_hits(self, conn: sqlite3.Connection, name: str, ranked: list) -> list[dict]:
        """Attach payload fields to ranked (id, score) pairs, in rank order. Vanished rows drop."""
        if not ranked:
            return []
        ids = json.dumps([item_id for item_id, _ in ranked])

        if name == self.CHUNKS:
            rows = conn.execute(
                "SELECT id, artifact_id FROM chunks"
                " WHERE id IN (SELECT value FROM json_each(?))",
                (ids,),
            ).fetchall()
        elif name == self.ENTITIES:
            rows = conn.execute(
                "SELECT id, artifact_id, entity, fact, trust, model_version, body_version"
                " FROM entities"
                " WHERE id IN (SELECT value FROM json_each(?))",
                (ids,),
            ).fetchall()
        elif name == self.SECTIONS:
            rows = conn.execute(
                "SELECT id, artifact_id, ordinal, model_version, body_version FROM sections"
                " WHERE id IN (SELECT value FROM json_each(?))",
                (ids,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, artifact_id, level, trust, model_version, body_version"
                " FROM facets"
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
            elif name == self.ENTITIES:
                hit["entity_id"] = item_id
                hit["entity"] = row["entity"]
                hit["fact"] = row["fact"]
                hit["trust"] = row["trust"]
                hit["model_version"] = row["model_version"]
                hit["body_version"] = row["body_version"]
            elif name == self.SECTIONS:
                hit["section_id"] = item_id
                hit["ordinal"] = row["ordinal"]
                hit["model_version"] = row["model_version"]
                hit["body_version"] = row["body_version"]
            else:
                hit["facet_id"] = item_id
                hit["level"] = row["level"]
                hit["trust"] = row["trust"]
                hit["model_version"] = row["model_version"]
                hit["body_version"] = row["body_version"]
            out.append(hit)
        return out

    def counts(self) -> dict:
        """Row counts per index table; a missing table counts as None."""
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
                "entities": _n("vec_entities"),
                "fts_chunks": _n("fts_chunks"),
                "fts_chunks_tri": _n("fts_chunks_tri"),
                "fts_facets": _n("fts_facets"),
                "fts_entities": _n("fts_entities"),
                "sections": _n("vec_sections"),
                "fts_sections": _n("fts_sections"),
            }
        finally:
            conn.close()
