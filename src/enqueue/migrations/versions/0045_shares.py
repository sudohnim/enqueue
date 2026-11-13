"""Shared notes: the link each shared note has, and the key that opens it.

Revision ID: 0045_shares
Revises: 0044_view_sync
"""

from __future__ import annotations

from alembic import op

revision = "0045_shares"
down_revision = "0044_view_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE shares ("
        " artifact_id TEXT PRIMARY KEY,"
        " share_id TEXT NOT NULL UNIQUE,"
        " link_key TEXT NOT NULL,"
        " seal_key TEXT NOT NULL,"
        " passphrase INTEGER NOT NULL DEFAULT 0,"
        " expires_at TEXT,"
        " created_at TEXT NOT NULL,"
        " shared_at TEXT NOT NULL,"
        " shared_hash TEXT NOT NULL)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE shares")
