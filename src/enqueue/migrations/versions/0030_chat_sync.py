"""Make a conversation a syncable object.

Conversations were device-local: the sync serializes the `artifacts` table only, and
a chat lives in its own `chats`/`chat_messages` tables, so it never rode the relay.
To sync a chat with the same E2E snapshot mechanism artifacts use it needs the two
columns every synced row already has - the LWW device stamp and a soft-delete
tombstone - so a delete can propagate instead of vanishing locally.

`_device_id` is the id of the device whose write produced the current row, stamped at
push time; it is the tiebreaker in the `(updated_at, _device_id)` last-writer-wins key.
`deleted_at` turns delete into a tombstone: the row is kept, its messages stripped, so
the deletion is a state other devices can converge on rather than an absence they would
each re-create from a stale snapshot.

Revision ID: 0030_chat_sync
Revises: 0029_pivot_result_cache
"""

from __future__ import annotations

from alembic import op

revision = "0030_chat_sync"
down_revision = "0029_pivot_result_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE chats ADD COLUMN _device_id TEXT")
    op.execute("ALTER TABLE chats ADD COLUMN deleted_at TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE chats DROP COLUMN deleted_at")
    op.execute("ALTER TABLE chats DROP COLUMN _device_id")
