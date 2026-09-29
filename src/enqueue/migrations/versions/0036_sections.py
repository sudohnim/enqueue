"""Sections: the ingest model's summary of each section of a long document.

Written by map-reduce ingestion (ingest/source.py) when a document is longer than one
read, and indexed as its own search layer, so a long document is findable by what
each part is about. Derived data, stamped with the model and body version that made
it like facets; purge deletes an artifact's rows.

Revision ID: 0036_sections
Revises: 0035_opens
"""

from __future__ import annotations

from alembic import op

revision = "0036_sections"
down_revision = "0035_opens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS sections (
          id            TEXT PRIMARY KEY,
          artifact_id   TEXT NOT NULL,
          ordinal       INTEGER NOT NULL,
          summary       TEXT NOT NULL,
          model_version TEXT NOT NULL,
          body_version  TEXT,
          created_at    TEXT NOT NULL
        )
        """)
    op.execute("CREATE INDEX IF NOT EXISTS sections_by_artifact ON sections (artifact_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sections")
