"""Chat places: where an answer came from in an artifact.

Revision ID: 0049_chat_places
Revises: 0048_link_feedback
"""

from __future__ import annotations

from alembic import op

revision = "0049_chat_places"
down_revision = "0048_link_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE chat_places ("
        " message_id TEXT NOT NULL,"
        " n INTEGER NOT NULL,"
        " artifact_id TEXT NOT NULL,"
        " page INTEGER,"
        " quote TEXT NOT NULL DEFAULT '',"
        " PRIMARY KEY (message_id, n))"
    )


def downgrade() -> None:
    op.execute("DROP TABLE chat_places")
