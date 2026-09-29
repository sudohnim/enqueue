"""Chunk context: a model-written line that places a chunk in its document.

A chunk of a long document loses what surrounds it: "the second approach failed
too" is unfindable by what it is about. `context` holds one or two sentences the
ingest model writes to situate the chunk (which document, which part, what it
refers to); it is embedded and keyword-indexed with the chunk. Derived data: it is
regenerated whenever the artifact is re-chunked. `context_model` stamps the model.

Revision ID: 0033_chunk_context
Revises: 0032_events_log
"""

from __future__ import annotations

from alembic import op

revision = "0033_chunk_context"
down_revision = "0032_events_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE chunks ADD COLUMN context TEXT")
    op.execute("ALTER TABLE chunks ADD COLUMN context_model TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE chunks DROP COLUMN context_model")
    op.execute("ALTER TABLE chunks DROP COLUMN context")
