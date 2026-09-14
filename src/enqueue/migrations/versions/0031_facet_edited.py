"""Mark a facet a person edited by hand, so regeneration never overwrites it.

A summary is machine-written, but a person can now rewrite a facet or add one of their
own (the summary edit feature). An edited facet is theirs: pressing "regenerate" must
replace only the machine-written facets and leave the hand-written ones in place. This
flag is what the regenerate path reads to decide which rows it may delete.

Revision ID: 0031_facet_edited
Revises: 0030_chat_sync
"""

from __future__ import annotations

from alembic import op

revision = "0031_facet_edited"
down_revision = "0030_chat_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE facets ADD COLUMN edited INTEGER NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE facets DROP COLUMN edited")
