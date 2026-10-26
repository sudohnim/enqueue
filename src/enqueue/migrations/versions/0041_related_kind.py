"""Related kind and distance: which links are analogies, and how far they reach.

`kind` says how two artifacts were linked: `subject` (about the same thing), `mention`
(naming the same thing) or `idea` (judged to make the same point). `distance` is how
far apart their subjects are, 1 minus the closest subject-line similarity, so an idea
link between a willow in a storm and a software release can be told from one between
two notes on the same book. Both are derived and recomputed (related.VERSION).

Revision ID: 0041_related_kind
Revises: 0040_keep_drafts
"""

from __future__ import annotations

from alembic import op

revision = "0041_related_kind"
down_revision = "0040_keep_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE related ADD COLUMN kind TEXT")
    op.execute("ALTER TABLE related ADD COLUMN distance REAL")


def downgrade() -> None:
    op.execute("ALTER TABLE related DROP COLUMN distance")
    op.execute("ALTER TABLE related DROP COLUMN kind")
