"""Typed assistant turns, and the saved groupings that reuse them.

A turn used to be only role + text + grounded. To render a non-answer turn on
reload, the transcript must remember two more things: what kind of turn it
was, and, for a structured skill, the spec that produced it so the view
re-runs from stored intent, not from re-classifying the old text.

Two columns:

  kind    TEXT NOT NULL DEFAULT 'answer'  - the skill that produced the turn
  payload TEXT                            - JSON the turn needs to re-render itself

`kind` is deliberately unconstrained. A CHECK (kind IN (...)) would freeze the
skill list into the schema and a third skill would need a migration to add a
turn type. The registry in assistant.py is the source of truth for valid
names, not the database. Defaulting to 'answer' backfills every existing row
correctly: everything written before this feature was an answer.

`payload` is NULL for an answer (its text is the whole turn). For an organize
turn it holds the pivot spec (a dict, JSON-encoded), so the view re-runs the
grouping on reload without re-planning.

The saved_pivots table is the home for a grouping worth keeping: a named
pivot spec you can re-run from the grid button. Nothing but this migration
creates it, so no IF NOT EXISTS store-race dance is needed (unlike 0011/0012).

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE chat_messages ADD COLUMN kind TEXT NOT NULL DEFAULT 'answer'")
    op.execute("ALTER TABLE chat_messages ADD COLUMN payload TEXT")
    op.execute("""
        CREATE TABLE saved_pivots (
          id         TEXT PRIMARY KEY,
          name       TEXT NOT NULL,
          spec_json  TEXT NOT NULL,   -- the pivot spec, exactly as pivot.run() eats it
          created_at TEXT NOT NULL
        )
        """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS saved_pivots")
    # SQLite DROP COLUMN works on the pinned version; if a future engine
    # rejects it, this downgrade is dev-only and the table drop is the part
    # that matters.
    op.execute("ALTER TABLE chat_messages DROP COLUMN kind")
    op.execute("ALTER TABLE chat_messages DROP COLUMN payload")
