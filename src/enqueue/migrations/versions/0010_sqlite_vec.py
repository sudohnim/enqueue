"""The search index moves out of Qdrant's directory and into this database.

Phase 18A. Qdrant kept vectors and plaintext payloads in a directory next to
the database; the index now lives in the same SQLite file as the library, in
tables that are pure derived data and rebuildable from `chunks` and `facets`
(`POST /index` or `enq index`):

  vec_chunks, vec_facets   sqlite-vec vec0 virtual tables, dense vectors
  fts_chunks, fts_facets   FTS5 virtual tables, keyword retrieval
  index_meta               key/value, holds the embedding version

vec0 is a loadable extension, so the migration loads it on the alembic
connection before creating the virtual tables. FTS5 ships inside the Python
sqlite3 module.

Everything here uses IF NOT EXISTS: `ensure()` on the store can create the
same tables before alembic ever runs on a brand-new database, and the two
paths must not fight. Migration 0001 handles the pre-migration adoption case
the same way.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

import sqlite_vec
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

# The embedding length the vec0 tables are built with. Equal to config.EMBED_DIM
# (768, BAAI/bge-base-en-v1.5); kept literal because a migration is a frozen
# artifact, and a later model change is a new revision, not an edit to this one.
DIM = 768


def _load_vec(bind) -> None:
    """Load the sqlite-vec extension on the migration's connection.

    `op.get_bind()` is a SQLAlchemy Connection; the sqlite3.Connection it wraps
    is what `sqlite_vec.load` needs, and it has to be told it may load
    extensions first.
    """
    raw = bind.connection.driver_connection
    raw.enable_load_extension(True)
    sqlite_vec.load(raw)
    raw.enable_load_extension(False)


def upgrade() -> None:
    _load_vec(op.get_bind())
    op.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
          chunk_id TEXT PRIMARY KEY,
          embedding float[768]
        )
        """)
    op.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_facets USING vec0(
          facet_id TEXT PRIMARY KEY,
          embedding float[768]
        )
        """)
    op.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5(
          chunk_id UNINDEXED,
          title,
          text
        )
        """)
    op.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks_tri USING fts5(
          chunk_id UNINDEXED,
          text,
          tokenize='trigram'
        )
        """)
    op.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_facets USING fts5(
          facet_id UNINDEXED,
          text
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS index_meta (
          key   TEXT PRIMARY KEY,
          value TEXT
        )
        """)


def downgrade() -> None:
    # Dropping a vec0 virtual table still needs the extension: SQLite has to
    # resolve the module to destroy the table's internal representation.
    _load_vec(op.get_bind())
    op.execute("DROP TABLE IF EXISTS index_meta")
    op.execute("DROP TABLE IF EXISTS fts_facets")
    op.execute("DROP TABLE IF EXISTS fts_chunks_tri")
    op.execute("DROP TABLE IF EXISTS fts_chunks")
    op.execute("DROP TABLE IF EXISTS vec_facets")
    op.execute("DROP TABLE IF EXISTS vec_chunks")
