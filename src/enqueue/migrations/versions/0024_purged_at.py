"""Tombstone marker for cross-device permanent delete.

Purge (empty trash) is irreversible, but it must still PROPAGATE: a snapshot
represents an artifact's state, and a hard-deleted row has no state to sync, so a
peer could never learn the artifact is gone (absence in the relay listing is not a
delete signal). Instead a purge becomes a TOMBSTONE - the row is kept with
`purged_at` set, its content stripped, and it rides the normal snapshot/LWW/pull
pipeline. Peers apply the tombstone by stripping their own copy.

A tombstone keeps `deleted_at` set too, so every existing `deleted_at IS NULL`
query already excludes it from the library, search, and pivots; only the trash
views need the extra `purged_at IS NULL` filter.

Revision ID: 0024
Revises: 0023_sync_device_id
"""

from __future__ import annotations

from alembic import op

revision = "0024_purged_at"
down_revision = "0023_sync_device_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE artifacts ADD COLUMN purged_at TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE artifacts DROP COLUMN purged_at")
