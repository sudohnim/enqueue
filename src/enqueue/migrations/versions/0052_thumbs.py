"""Thumbs: the thumbnail of an artifact.

Revision ID: 0052_thumbs
Revises: 0051_artifact_colours
"""

from __future__ import annotations

from alembic import op

revision = "0052_thumbs"
down_revision = "0051_artifact_colours"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE thumbs ("
        " artifact_id TEXT PRIMARY KEY,"
        " content_hash TEXT NOT NULL,"
        " width INTEGER NOT NULL)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE thumbs")
