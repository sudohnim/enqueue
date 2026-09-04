"""Secret-vault marker.

An artifact the owner locks into the vault gets `vaulted_at` set. Like the trash
tombstone, it is a marker on the row that rides the normal snapshot/LWW/pull
pipeline, so vaulting is consistent across devices. Unlike trash, a vaulted row is
NOT hidden by `deleted_at IS NULL`, so every live surface (library, search,
retrieval, chat passages, pivots, export) needs an explicit `vaulted_at IS NULL`
filter, and the vault view is the one place that shows `vaulted_at IS NOT NULL`.

The vaulted row's content is additionally encrypted at rest with the PIN-derived
vault key (see the VAULT phase); this column only marks membership so the filters
and sync can see it in clear.

Revision ID: 0025
Revises: 0024_purged_at
"""

from __future__ import annotations

from alembic import op

revision = "0025_vaulted_at"
down_revision = "0024_purged_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE artifacts ADD COLUMN vaulted_at TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE artifacts DROP COLUMN vaulted_at")
