"""`artifacts.keep_drafts`: whether a note keeps a history of drafts.

1 (the default) keeps drafts by the library's policy (drafts.py); 0 keeps only the
latest, which is still needed as the note's body version. Set from the note's Details
panel or its drafts list.

Revision ID: 0040_keep_drafts
Revises: 0039_related_judge_state
"""

from __future__ import annotations

from alembic import op

revision = "0040_keep_drafts"
down_revision = "0039_related_judge_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE artifacts ADD COLUMN keep_drafts INTEGER NOT NULL DEFAULT 1")


def downgrade() -> None:
    op.execute("ALTER TABLE artifacts DROP COLUMN keep_drafts")
