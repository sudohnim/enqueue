"""The entities table: proper names with a one-line fact each.

An artifact's own words, its chunks, and its facets all share the same
vocabulary problem: they can only be found by a question that uses words the
artifact uses. "Notes on presidents" never reaches a Roosevelt biography that
never says "president". The entity layer closes the gap from the name side:
`entities` stores the proper names the body mentions, each enriched with a
one-line world-knowledge fact ("Theodore Roosevelt - 26th US President, known
for trust-busting and the Panama Canal."). Those lines are indexed the way
facets are, so a question phrased in the world's vocabulary reaches an
artifact that never used it.

The table mirrors `facets` row for row - same provenance stamps, same trust
column - and swaps `level`/`statement` for `entity`/`fact`. Each row is a
single name plus the single line that identifies it:

  id            TEXT    PK
  artifact_id   TEXT    the artifact the name was extracted from
  entity        TEXT    the canonical name as the body uses it
  fact          TEXT    the enriched one-line fact (indexed text)
  model_version TEXT    which model wrote the fact ('' = user-written)
  body_version  TEXT    which body the extraction read; NULL = unknown
                        provenance, treated as stale on read
  trust         REAL    symmetric to facets.trust

`entity` and `fact` are stored with full case (both are user-visible), while
the generated index columns keep the lowercased copies. A regeneration
replaces one artifact's rows wholesale, so the table never accumulates stale
entries.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS entities (
          id            TEXT PRIMARY KEY,
          artifact_id   TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
          entity        TEXT NOT NULL,
          fact          TEXT NOT NULL,
          model_version TEXT NOT NULL,
          body_version  TEXT,
          trust         REAL NOT NULL DEFAULT 0.5
        )
        """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_entities_artifact ON entities (artifact_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS entities")
