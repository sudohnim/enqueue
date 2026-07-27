"""Pinned conversations.

The rail is ordered by recency, which is right for the ones you are working through
and wrong for the two or three you keep coming back to. Those sink as soon as you
have a busy week, and sinking is the failure mode this whole product is built against.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE chats ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
    op.execute("CREATE INDEX idx_chats_pinned ON chats(pinned DESC, updated_at DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chats_pinned")
    # SQLite gained DROP COLUMN in 3.35; the bundled Python is well past that.
    op.execute("ALTER TABLE chats DROP COLUMN pinned")
