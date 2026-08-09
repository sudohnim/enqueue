"""Why a failed answer failed, stored next to the turn that carries it.

A failed assistant turn already resolves to a short human sentence (FAILED_TEXT)
that the transcript shows as the turn's own text. That sentence says the answer
could not be completed, but not why - and the reason is the actionable part: a
rejected API key, a dead endpoint, a model that does not exist. Before this the
cause was logged and lost, so the chat view could only offer "try again" with no
path to the fix.

One column:

  error  TEXT  - NULL, or a one-line cause a person can read and act on

The worker stores the provider layer's sentence (`ProviderError` carries one -
"the endpoint at ... rejected the API key. Set a valid key in Settings...") when
the failure is a model-call failure, and leaves it NULL for anything else, so a
genuine bug never leaks its exception text into the interface. The chat view
renders the cause with a link to the AI settings when it is present.

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE chat_messages ADD COLUMN error TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE chat_messages DROP COLUMN error")
