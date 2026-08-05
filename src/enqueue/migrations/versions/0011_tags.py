"""Tags: two source tables for user-authored labels.

Phase T1 of the tags feature. Tags are user-authored and permanent, so they
are SOURCE tables, never derived: they survive `enq rebuild`, and nothing in
the index or the embedding pipeline owns them.

  tags            one canonical row per tag name (lowercased, trimmed)
  artifact_tags   the many-to-many link from artifacts to tags

A tag is optional and added after an artifact exists; nothing at capture time
ever asks for one. Conversations cannot be tagged, so there is no chats link.

Everything here uses IF NOT EXISTS: `ensure()` on the store can create the
same tables before alembic ever runs on a brand-new database, and the two
paths must not fight. Migration 0001 handles the pre-migration adoption case
the same way.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS tags (
          id          TEXT PRIMARY KEY,
          name        TEXT NOT NULL UNIQUE,   -- canonical: lowercased, trimmed
          created_at  TEXT NOT NULL
        )
        """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS artifact_tags (
          artifact_id TEXT NOT NULL REFERENCES artifacts(id),
          tag_id      TEXT NOT NULL REFERENCES tags(id),
          created_at  TEXT NOT NULL,
          PRIMARY KEY (artifact_id, tag_id)
        )
        """)


def downgrade() -> None:
    # Child first: the link table references the tags table.
    op.execute("DROP TABLE IF EXISTS artifact_tags")
    op.execute("DROP TABLE IF EXISTS tags")
