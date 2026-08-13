"""Persist the device that last wrote each artifact.

E2E.md Phase E3/SYNC.4: the LWW key is `(updated_at, device_id)`, compared
lexicographically. The local DB must remember which device wrote the current
row, or a pull that applies snapshots out of order cannot tell a newer local
edit from a stale one (and the convergence invariant breaks on equal
timestamps). The column is NULL for artifacts that predate sync or were never
pushed; the no-op check falls back to this device's own id for those.

Revision ID: 0023
Revises: 0022_title_explicit
"""

from __future__ import annotations

from alembic import op

revision = "0023_sync_device_id"
down_revision = "0022_title_explicit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE artifacts ADD COLUMN _device_id TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE artifacts DROP COLUMN _device_id")
