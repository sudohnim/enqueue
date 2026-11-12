"""Saved views sync between computers: a change time per view, and deleted views.

Revision ID: 0044_view_sync
Revises: 0043_facet_bridge
"""

from __future__ import annotations

from alembic import op

revision = "0044_view_sync"
down_revision = "0043_facet_bridge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE saved_pivots ADD COLUMN updated_at TEXT")
    op.execute("ALTER TABLE saved_pivots ADD COLUMN _device_id TEXT")
    op.execute(
        "CREATE TABLE pivot_tombstones"
        " (id TEXT PRIMARY KEY, deleted_at TEXT NOT NULL, _device_id TEXT)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE pivot_tombstones")
    op.execute("ALTER TABLE saved_pivots DROP COLUMN _device_id")
    op.execute("ALTER TABLE saved_pivots DROP COLUMN updated_at")
