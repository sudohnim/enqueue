"""The trash.

Everything else in this product is kept on purpose, and that stays true: nothing here
expires on its own, and nothing is removed because it got old or because you stopped
looking at it. What this adds is the one case the collection could not previously
express, which is *you deciding* something should not be in it.

Deleting is therefore two steps and a delay, never one step. The row is marked, it
leaves every surface, and the bytes survive for a window you control. A hoarder's
tool that can lose something in one keystroke is not a hoarder's tool.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE artifacts ADD COLUMN deleted_at TEXT")
    # Every listing filters on this, so it leads the index.
    op.execute("CREATE INDEX idx_artifacts_live ON artifacts(deleted_at, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_artifacts_live")
    op.execute("ALTER TABLE artifacts DROP COLUMN deleted_at")
