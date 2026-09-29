"""Opens: which artifact a person opened, from where, and for which search.

The raw record behind two things: the real-search eval (a search followed by an
open is a labelled example of what that search should find) and usage-aware
ranking. Local only, never synced. No foreign keys, so a purge is never blocked;
purge deletes an artifact's rows.

Revision ID: 0035_opens
Revises: 0034_related
"""

from __future__ import annotations

from alembic import op

revision = "0035_opens"
down_revision = "0034_related"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS opens (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          artifact_id TEXT NOT NULL,
          source      TEXT NOT NULL,
          query       TEXT,
          rank        INTEGER,
          opened_at   TEXT NOT NULL
        )
        """)
    op.execute("CREATE INDEX IF NOT EXISTS opens_by_artifact ON opens (artifact_id)")
    op.execute("CREATE INDEX IF NOT EXISTS opens_by_query ON opens (query)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS opens")
