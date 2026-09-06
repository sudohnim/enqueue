"""Embedded artifacts: images pasted inside a note.

An image pasted into a note is stored as an ordinary image artifact (so its bytes
ride the existing content-addressed blob store and its E2E sync for free), but it
is not a thing you kept on its own - it belongs to the note that references it as
`![](/artifacts/{id}/blob)`. `embedded_at` marks that: like `deleted_at` and
`vaulted_at`, every live surface (wall, search, retrieval, chunking, export,
pivots) filters `embedded_at IS NULL`, so an embedded image never shows as its own
card or search hit. It rides the artifact snapshot like any other column, so the
flag is the same on every device.

Revision ID: 0028_embedded_at
Revises: 0027_tags_no_whitespace
"""

from __future__ import annotations

from alembic import op

revision = "0028_embedded_at"
down_revision = "0027_tags_no_whitespace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE artifacts ADD COLUMN embedded_at TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE artifacts DROP COLUMN embedded_at")
