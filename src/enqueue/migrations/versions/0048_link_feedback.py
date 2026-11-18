"""Link feedback: the person's ruling on a related pair.

Revision ID: 0048_link_feedback
Revises: 0047_facet_role
"""

from __future__ import annotations

from alembic import op

revision = "0048_link_feedback"
down_revision = "0047_facet_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE link_feedback ("
        " pair TEXT PRIMARY KEY,"
        " verdict TEXT NOT NULL,"
        " idea TEXT NOT NULL DEFAULT '',"
        " created_at TEXT NOT NULL)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE link_feedback")
