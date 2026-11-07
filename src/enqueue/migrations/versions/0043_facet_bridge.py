"""Facet bridge: a summary line that restates the idea in another field's words.

Bridges exist so a search in that field finds the note. They share field words with
every other bridge, so related links leave them out of idea candidates.

Revision ID: 0043_facet_bridge
Revises: 0042_related_owner
"""

from __future__ import annotations

from alembic import op

revision = "0043_facet_bridge"
down_revision = "0042_related_owner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE facets ADD COLUMN bridge INTEGER NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE facets DROP COLUMN bridge")
