"""Pinned artifacts, and extracted page text.

Two things a wall of objects needs once it is longer than a screen: a way to keep the
few that matter in reach, and a way to find a phrase inside one of them.

`page_text` is what makes a PDF a document rather than a picture of one. Until now a
captured PDF had no text anywhere in the system, which meant it could not be searched,
could not be asked about, and could not be curated. It was decoration.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE artifacts ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
    op.execute("CREATE INDEX idx_artifacts_pinned ON artifacts(pinned DESC, created_at DESC)")

    op.execute("""
        -- Derived: droppable, and rebuilt by running the extractor again. The page
        -- number is kept because "page 9" is how a person refers to a place in a PDF,
        -- and a search result that cannot say where it is has not found anything.
        CREATE TABLE page_text (
          artifact_id TEXT NOT NULL REFERENCES artifacts(id),
          page        INTEGER NOT NULL,
          text        TEXT NOT NULL,
          extractor   TEXT NOT NULL,
          PRIMARY KEY (artifact_id, page)
        )
        """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS page_text")
    op.execute("DROP INDEX IF EXISTS idx_artifacts_pinned")
    op.execute("ALTER TABLE artifacts DROP COLUMN pinned")
