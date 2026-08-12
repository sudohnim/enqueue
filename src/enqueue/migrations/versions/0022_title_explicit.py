"""Persist an explicit note title.

NOTE.0/NOTE.3: a note's title is derived from its first line by default, but a
title the person edits by hand is explicit and must survive later body edits.
The flag is what remembers the difference: `notes.edit` only re-derives from the
body when the title is not explicit. Existing rows default to 0 (derived), which
is exactly the behaviour the engine had before this migration - the title was
recomputed from the body on every save.

Revision ID: 0022
Revises: 0021_idx_artifacts_touched
"""

from __future__ import annotations

from alembic import op

revision = "0022_title_explicit"
down_revision = "0021_idx_artifacts_touched"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE artifacts ADD COLUMN title_explicit INTEGER NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE artifacts DROP COLUMN title_explicit")
