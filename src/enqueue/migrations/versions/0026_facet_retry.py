"""Facet (AI summary) retry queue.

An artifact's facets - the model's compressed reading, shown as the reader's
Summary - are generated on the ingest worker. A transient model failure (a rate
limit, a 500) used to be swallowed, leaving the artifact permanently summary-less
until something re-ingested it. This table lets a failed generation be retried in
the background with escalating backoff until it succeeds: one row per artifact still
owing a summary, with the attempt count and the earliest time to try again. A
success, a content-skip, or a gate-skip removes the row. It is local, derived
bookkeeping - never synced.

Revision ID: 0026_facet_retry
Revises: 0025_vaulted_at
"""

from __future__ import annotations

from alembic import op

revision = "0026_facet_retry"
down_revision = "0025_vaulted_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE facet_retry ("
        " artifact_id TEXT PRIMARY KEY,"
        " attempts INTEGER NOT NULL DEFAULT 0,"
        " next_at TEXT NOT NULL,"
        " last_error TEXT"
        ")"
    )
    op.execute("CREATE INDEX idx_facet_retry_next ON facet_retry(next_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_facet_retry_next")
    op.execute("DROP TABLE IF EXISTS facet_retry")
