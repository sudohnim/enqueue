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
from itertools import groupby
from sqlite3 import OperationalError
from typing import Any

import sqlite_vec

from .. import config, db
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
        "CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5("
        " chunk_id UNINDEXED, title, text)",
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
}

# Which index tables make up each collection.
_COLLECTION_TABLES = {
    "chunks": ("vec_chunks", "fts_chunks"),
    "facets": ("vec_facets", "fts_facets"),
    "entities": ("vec_entities", "fts_entities"),
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
        "insert_fts": "INSERT INTO fts_chunks (chunk_id, title, text) VALUES (?, ?, ?)",
        "dense": (
            "SELECT chunk_id AS id, distance FROM vec_chunks"
            " WHERE embedding MATCH ? ORDER BY distance LIMIT ?"
        ),
        "keyword": (
            "SELECT chunk_id AS id, bm25(fts_chunks, 1.0, 10.0, 1.0) AS raw FROM fts_chunks"
            " WHERE fts_chunks MATCH ? ORDER BY bm25(fts_chunks, 1.0, 10.0, 1.0) LIMIT ?"
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
    "entities": {
        "select_all": "SELECT id, fact FROM entities",
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
}

_COUNT_SQL = {
    "vec_chunks": "SELECT COUNT(*) FROM vec_chunks",
    "vec_facets": "SELECT COUNT(*) FROM vec_facets",
    "vec_entities": "SELECT COUNT(*) FROM vec_entities",
    "fts_chunks": "SELECT COUNT(*) FROM fts_chunks",
    "fts_facets": "SELECT COUNT(*) FROM fts_facets",
    "fts_entities": "SELECT COUNT(*) FROM fts_entities",
}

# The text a chunk is embedded and indexed under. The title is prepended for
# indexing only; the stored chunk text stays clean. Without this, a note
# whose title is the only place a name appears is unfindable by that name
# (measured in Part 1: the Epictetus note is the author's own paraphrase and
# never contains the word "Epictetus").
CHUNK_INDEX_TEXT = "{title}\n\n{text}"

# The keyword branch's voice in the dense+keyword RRF fusion. RRF reads
# ranks only, so the title-weighted bm25 (R.5's 10x title column) can only
# matter through the keyword branch's ORDER. When dense and keyword rank the
# same ids symmetrically the fused scores tie and rrf_scored falls back to
# first-seen order, which is dense order. That is right when the keyword
# branch is itself undecided, but a title match the keyword branch clearly
# prefers must beat a body match. So on an RRF tie, let the keyword branch
# override dense order only when it is confident: its best score must beat
# the runner-up by at least this relative margin, or the tie keeps dense
# order. 0.2 = the keyword winner must be 20% more confident.
KEYWORD_MARGIN = 0.2


# How each collection's rows land in its FTS table. The embed text and the
# keyword columns can differ: a chunk embeds as "title\n\ntext" (the title is
# the only place some names appear) but indexes title and text as separate
# FTS columns, so bm25 can weight the title. Facets and entities have no
# separate title, so their fts row is the same string they embed.
#
# Note on bm25 weights: FTS5 maps weights positionally to every column,
# including UNINDEXED ones. `bm25(fts_chunks, 10.0, 1.0)` on a
# (chunk_id, title, text) table would apply 10.0 to the unindexed chunk_id
# (ignored) and 1.0 to the title - silently no weighting. The three-weight
# form is the one that actually weights the title.
def _chunk_entries(row) -> tuple[str, tuple[str, str]]:
    """(embed_text, fts_row) for one chunk row, shared by rebuild and single-artifact index.

    The fts text column drops a leading heading that just restates the
    artifact title ("# On the Writings of Hypatia"): with that heading in
    the text too, FTS5 counts the title term in both columns and normalizes
    by row length, so the title's bm25 weight cannot tell a short title from
    a long one. The title column alone carries the term then. The embed text
    keeps the heading - it is still the chunk's context for vectors.
    """
    title = row["title"] or ""
    text = row["text"] or ""
    fts_text = text
    heading = f"# {title}"
    if title and text.startswith(heading):
        fts_text = text[len(heading) :].lstrip("\n").strip()
    return (
        CHUNK_INDEX_TEXT.format(title=title, text=text),
        (title, fts_text),
    )


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
        conn = sqlite3.connect(config.DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        db.set_wal(conn)
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
        if name == self.ENTITIES:
            return "entity_id"
        raise ValueError(f"unknown collection {name!r}")

    def ensure(self) -> None:
        """Create the index tables if they do not exist.

        Safe to call repeatedly. IF NOT EXISTS everywhere means this can also
        run before alembic ever has: migration 0010 uses the same DDL, so the
        two paths cannot fight.

        A database indexed before the title-weight change has the old
        two-column `fts_chunks` shape; recreate it so the title column and
        its bm25 weight apply. The recreate only fires once (the next write
        path after an upgrade), and every caller of `ensure` repopulates the
        rows it clears, so no data is silently dropped.
        """
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

    # -- writing ----------------------------------------------------------

    def upsert_chunks(self, batch_size: int = 64) -> dict:
        return self._rebuild(self.CHUNKS, _chunk_entries, batch_size)

    def upsert_facets(self, batch_size: int = 64) -> dict:
        return self._rebuild(
            self.FACETS, lambda row: (row["statement"], (row["statement"],)), batch_size
        )

    def upsert_entities(self, batch_size: int = 64) -> dict:
        return self._rebuild(self.ENTITIES, lambda row: (row["fact"], (row["fact"],)), batch_size)

    def _rebuild(self, name: str, entries_of, batch_size: int) -> dict:
        """Rebuild one collection from its source table, in place.

        Clear the collection, then embed and insert in batches of
        `batch_size`. Each batch writes the vector table and the keyword
        table in one transaction, so the two can never diverge mid-write.

        `entries_of(row)` returns `(embed_text, fts_row)`: the embed text is
        what gets embedded, and `fts_row` is the keyword-table columns after
        the item id (a single string for facets and entities, `(title, text)`
        for chunks).
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
        return len(entries)

    def index_facets_artifact(self, artifact_id: str) -> int:
        """Re-embed one artifact's facets in place, like index_artifact for chunks.

        The facet's statement is the text embedded (the same text upsert_facets
        indexes). One artifact's facet rows are replaced; the rest of the facet
        collection is untouched, so a capture can index its own facets without a
        whole-collection rebuild. The caller generates the facet rows first.
        """
        self.ensure()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, statement FROM facets WHERE artifact_id = ? ORDER BY level",
                (artifact_id,),
            ).fetchall()
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
            if not rows:
                return 0
            entries = [(row["id"], row["statement"]) for row in rows]
            vectors = embed([text for _, text in entries])
            conn.executemany(
                "INSERT INTO vec_facets (facet_id, embedding) VALUES (?, ?)",
                [
                    (item_id, json.dumps(vector))
                    for (item_id, _), vector in zip(entries, vectors, strict=True)
                ],
            )
            conn.executemany(
                "INSERT INTO fts_facets (facet_id, text) VALUES (?, ?)",
                [(item_id, text) for item_id, text in entries],
            )
        return len(entries)

    def index_entities_artifact(self, artifact_id: str) -> int:
        """Re-embed one artifact's entity lines in place, like index_facets_artifact.

        The enriched fact line is the text embedded (the same text upsert_entities
        indexes). One artifact's entity rows are replaced; the rest of the entity
        collection is untouched, so a capture can index its own entities without a
        whole-collection rebuild. The caller generates the entity rows first.
        """
        self.ensure()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, fact FROM entities WHERE artifact_id = ? ORDER BY entity",
                (artifact_id,),
            ).fetchall()
            conn.execute(
                "DELETE FROM vec_entities"
                " WHERE entity_id IN (SELECT id FROM entities WHERE artifact_id = ?)",
                (artifact_id,),
            )
            conn.execute(
                "DELETE FROM fts_entities"
                " WHERE entity_id IN (SELECT id FROM entities WHERE artifact_id = ?)",
                (artifact_id,),
            )
            if not rows:
                return 0
            entries = [(row["id"], row["fact"]) for row in rows]
            vectors = embed([text for _, text in entries])
            conn.executemany(
                "INSERT INTO vec_entities (entity_id, embedding) VALUES (?, ?)",
                [
                    (item_id, json.dumps(vector))
                    for (item_id, _), vector in zip(entries, vectors, strict=True)
                ],
            )
            conn.executemany(
                "INSERT INTO fts_entities (entity_id, text) VALUES (?, ?)",
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
            elif name == self.ENTITIES:
                conn.execute(
                    "DELETE FROM vec_entities"
                    " WHERE entity_id IN (SELECT id FROM entities WHERE artifact_id = ?)",
                    (artifact_id,),
                )
                conn.execute(
                    "DELETE FROM fts_entities"
                    " WHERE entity_id IN (SELECT id FROM entities WHERE artifact_id = ?)",
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
        dense_ids = [hit[id_col] for hit in dense]
        keyword_ids = [hit[id_col] for hit in keyword]
        keyword_score = {hit[id_col]: hit["score"] for hit in keyword}

        fused = rrf_scored(
            dense_ids,
            keyword_ids,
            # k=1 reproduces the Qdrant backend's fused score scale: their RRF
            # is 1/(pos + 2) over 0-based positions, which is 1/(rank + 1)
            # over 1-based ranks. The lens score threshold was calibrated on
            # that scale, so scores have to be comparable across engines.
            # Ranking is k-invariant, so this changes magnitudes only.
            k=1,
            limit=limit,
        )
        # RRF reads ranks only, so the bm25 title weight (10x, R.5) can only
        # act through the keyword ORDER. On an RRF tie rrf_scored keeps
        # first-seen order, which is dense order. Let the keyword branch
        # overturn that only when it is confident - its best score beats the
        # runner-up by KEYWORD_MARGIN or more; a title match at 10x bm25 is
        # confidently better than a body match, while two title matches of
        # the same name ("On the Writings of Hypatia" vs "Teaching the Works
        # of Hypatia of Alexandria") score within noise of each other and
        # keep dense order, which is the semantic branch's call.
        by_id = {hit[id_col]: hit for hit in dense}
        by_id.update({hit[id_col]: hit for hit in keyword})
        ordered: list[tuple[Any, float]] = []
        # rrf_scored sorts by (-score, first-seen), so equal-score items are
        # contiguous; groupby folds them into tie runs.
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
        return [
            {**by_id[item_id], "score": round(score, 6)}
            for item_id, score in ordered
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
        elif name == self.ENTITIES:
            rows = conn.execute(
                "SELECT id, artifact_id, entity, fact, trust, model_version, body_version"
                " FROM entities"
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
            else:
                hit["facet_id"] = item_id
                hit["level"] = row["level"]
                hit["trust"] = row["trust"]
                hit["model_version"] = row["model_version"]
                hit["body_version"] = row["body_version"]
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
                "entities": _n("vec_entities"),
                "fts_chunks": _n("fts_chunks"),
                "fts_facets": _n("fts_facets"),
                "fts_entities": _n("fts_entities"),
            }
        finally:
            conn.close()
