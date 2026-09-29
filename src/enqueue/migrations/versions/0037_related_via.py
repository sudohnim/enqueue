"""Related via: the shared name behind a "both mention" link.

A related link is either an idea link (facets that make the same point; `via` NULL)
or a mention link (both artifacts name the same person, place or thing; `via` holds
that name, for "both mention Taleb").

Revision ID: 0037_related_via
Revises: 0036_sections
"""

from __future__ import annotations

from alembic import op

revision = "0037_related_via"
down_revision = "0036_sections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE related ADD COLUMN via TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE related DROP COLUMN via")
