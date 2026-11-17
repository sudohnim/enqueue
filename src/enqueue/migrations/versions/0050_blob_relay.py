"""Blob relay: which relay holds a blob.

Revision ID: 0050_blob_relay
Revises: 0049_chat_places
"""

from __future__ import annotations

from alembic import op

revision = "0050_blob_relay"
down_revision = "0049_chat_places"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE blob_relay ("
        " content_hash TEXT PRIMARY KEY,"
        " relay TEXT NOT NULL,"
        " pushed_at TEXT NOT NULL)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE blob_relay")
