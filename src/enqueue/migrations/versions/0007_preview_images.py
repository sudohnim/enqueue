"""A link's picture, stored rather than referenced.

The preview deliberately dropped `og:image`, because keeping the URL and rendering it
in an `<img>` would fetch from the publisher on every view of that card, forever. That
is a worse leak than the single request the no-fetch default was avoiding, and it is
silent.

Downloading it once during the same opt-in fetch has the opposite shape: one more
request in a moment the person already chose, and then the bytes are local and the
publisher never hears from you again. So the column holds a content hash into the
same blob store everything else uses, never a remote address.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE link_previews ADD COLUMN image_hash TEXT")
    op.execute("ALTER TABLE link_previews ADD COLUMN image_mime TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE link_previews DROP COLUMN image_mime")
    op.execute("ALTER TABLE link_previews DROP COLUMN image_hash")
