"""Searches: a local record of what was asked and what came back.

Revision ID: 0046_searches
Revises: 0045_shares
"""

from __future__ import annotations

from alembic import op

revision = "0046_searches"
down_revision = "0045_shares"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE searches ("
        " id INTEGER PRIMARY KEY,"
        " query TEXT NOT NULL,"
        " hits TEXT NOT NULL DEFAULT '[]',"
        " loose INTEGER NOT NULL DEFAULT 0,"
        " source TEXT NOT NULL,"
        " created_at TEXT NOT NULL)"
    )
    op.execute("CREATE INDEX idx_searches_created ON searches(created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE searches")
