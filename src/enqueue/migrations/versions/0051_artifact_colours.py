"""Artifact colours: the colours of a picture.

Revision ID: 0051_artifact_colours
Revises: 0050_blob_relay
"""

from __future__ import annotations

from alembic import op

revision = "0051_artifact_colours"
down_revision = "0050_blob_relay"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE artifact_colours ("
        " artifact_id TEXT NOT NULL,"
        " r INTEGER NOT NULL,"
        " g INTEGER NOT NULL,"
        " b INTEGER NOT NULL,"
        " share REAL NOT NULL,"
        " PRIMARY KEY (artifact_id, r, g, b))"
    )


def downgrade() -> None:
    op.execute("DROP TABLE artifact_colours")
