"""Pending assistant turns, so an answer can outlive the page that asked for it.

A message used to be complete the instant it was written: the turn's text was its
whole life. Phase H breaks that. A submitted question writes a pending assistant
turn first - visible in the transcript as itself - and a background worker fills
it in later, after the person has left, reloaded, or closed the tab. The stored
message is the only place an answer lives, so the transcript has to be able to
hold a turn that exists before its content does.

One column:

  status  TEXT NOT NULL DEFAULT 'done'  - done | pending | failed

`done` is the resting state and backfills every existing row correctly: everything
written before this feature was already complete. A pending assistant turn is
written with `status = 'pending'` and empty text; the worker moves it to `done`
(with the real text) or `failed` (with a reason a person can read). An engine
restart sweeps any row still pending to `failed`, so a pending turn never hangs.

`status` is deliberately unconstrained, for the same reason `kind` has none: the
set of states is owned by the code, and freezing it into the schema would make the
next state a migration.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE chat_messages ADD COLUMN status TEXT NOT NULL DEFAULT 'done'")


def downgrade() -> None:
    # SQLite DROP COLUMN works on the pinned version; if a future engine
    # rejects it, this downgrade is dev-only, exactly as with kind/payload.
    op.execute("ALTER TABLE chat_messages DROP COLUMN status")
