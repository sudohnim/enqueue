"""What a saved link turns out to be.

Saving a link fetches nothing, on purpose: a request would tell the publisher you
read it. That leaves a link with no face, which is the complaint this answers.

A preview is derived and opt-in. The row exists only once the person asked for it,
one request per link, and it can be dropped and fetched again. No remote asset is
ever referenced: an `<img>` pointing at the publisher would leak a request on every
view forever, which is worse than the single fetch it was meant to avoid.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE link_previews (
          artifact_id TEXT PRIMARY KEY REFERENCES artifacts(id),
          status      TEXT NOT NULL,   -- ok | failed
          title       TEXT,
          description TEXT,
          site_name   TEXT,
          error       TEXT,
          fetched_at  TEXT NOT NULL,

          CHECK (status IN ('ok', 'failed')),
          CHECK (status = 'ok' OR error IS NOT NULL)
        )
        """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS link_previews")
