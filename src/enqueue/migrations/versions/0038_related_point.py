"""Related point: the statement behind an idea link.

An idea link joins two artifacts whose summaries make the same point. `point` holds the
related artifact's summary line that matched, so a reader can be told how the two are
related, not only that they are. NULL for a link that is only a shared name (`via`).

Revision ID: 0038_related_point
Revises: 0037_related_via
"""

from __future__ import annotations

from alembic import op

revision = "0038_related_point"
down_revision = "0037_related_via"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE related ADD COLUMN point TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE related DROP COLUMN point")
