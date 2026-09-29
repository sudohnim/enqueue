"""Related artifacts: links between notes whose facets say the same thing.

Written at ingest from facet similarity (ingest/related.py), stored in both
directions so an older note gains a link when a newer one arrives. Derived data:
rebuilt whenever an artifact's facets are. No foreign keys, so a purge is never
blocked; readers join against live artifacts and purge deletes an artifact's rows.

Revision ID: 0034_related
Revises: 0033_chunk_context
"""

from __future__ import annotations

from alembic import op

revision = "0034_related"
down_revision = "0033_chunk_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS related (
          artifact_id   TEXT NOT NULL,
          related_id    TEXT NOT NULL,
          score         REAL NOT NULL,
          model_version TEXT NOT NULL,
          created_at    TEXT NOT NULL,
          PRIMARY KEY (artifact_id, related_id)
        )
        """)
    op.execute("CREATE INDEX IF NOT EXISTS related_by_related_id ON related (related_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS related")
