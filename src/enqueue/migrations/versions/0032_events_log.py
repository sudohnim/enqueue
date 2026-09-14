"""Persist the activity log so it survives a restart and can carry full detail.

The Events tab used to read an in-memory ring that vanished on restart and held
only a one-line `detail` per event - enough to say a thing happened, never enough
to see what. This table is the durable backing: every notable engine action (a
question asked and answered, a capture, a facet edit, a sync) lands here with its
timing and a JSON `data` blob holding the full record (the question text, the
answer, which artifacts were cited, per-stage milliseconds). The tab can then let
a person open an event and read what actually happened, not just that it did.

Local diagnostics only: this table is never serialized into a sync snapshot, so a
device's activity stays on that device.

Revision ID: 0032_events_log
Revises: 0031_facet_edited
"""

from __future__ import annotations

from alembic import op

revision = "0032_events_log"
down_revision = "0031_facet_edited"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            kind        TEXT NOT NULL,
            detail      TEXT NOT NULL DEFAULT '',
            data        TEXT,
            duration_ms INTEGER
        )
        """)
    # The tab reads newest-first; index the sort key so a long log stays cheap.
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_id_desc ON events(id DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_events_id_desc")
    op.execute("DROP TABLE IF EXISTS events")
