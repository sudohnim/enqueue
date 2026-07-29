"""How many pages a PDF has, stored instead of recomputed.

The wall asked this question by opening the file. Listing artifacts ran `fitz.open` on
every PDF in the page purely to read `doc.page_count`, and each of those calls opened
its own SQLite connection first to find the blob. Measured on this database it cost
13.5 ms per PDF against a 0.8 ms row query: on a full 48-item page, roughly 650 ms of
work to produce a number that cannot change.

It cannot change because the file cannot change. A capture is immutable, which is
exactly what makes this safe to store: there is no invalidation problem, because there
is no event that would invalidate it.

So it is written once, by the pass that already has the document open in order to pull
its text out.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Left NULL for everything already captured. Backfilling here would mean opening
    # every PDF in the collection inside a migration, which is the same cost this
    # exists to remove, paid at the worst possible moment. The reader fills each one in
    # the first time it needs it instead, so an old collection heals as it is used.
    op.execute("ALTER TABLE artifacts ADD COLUMN pages INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE artifacts DROP COLUMN pages")
