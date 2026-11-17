"""Facet role: which job a summary line does.

Revision ID: 0047_facet_role
Revises: 0046_searches
"""

from __future__ import annotations

from alembic import op

revision = "0047_facet_role"
down_revision = "0046_searches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE facets ADD COLUMN role TEXT")
    op.execute(
        "UPDATE facets SET role = CASE "
        "WHEN bridge = 1 THEN 'bridge' "
        "WHEN level = 0 THEN 'kind' "
        "WHEN level = 1 THEN 'subject' "
        "ELSE 'idea' END"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE facets DROP COLUMN role")
