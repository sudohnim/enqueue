"""Source items: one row per outside item brought into the library.

Revision ID: 0053_source_items
Revises: 0052_thumbs
"""

from __future__ import annotations

from alembic import op

revision = "0053_source_items"
down_revision = "0052_thumbs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE source_items ("
        " source TEXT NOT NULL,"
        " external_id TEXT NOT NULL,"
        " stamp TEXT NOT NULL,"
        " artifact_id TEXT,"
        " PRIMARY KEY (source, external_id))"
    )


def downgrade() -> None:
    op.execute("DROP TABLE source_items")
