"""Proper homes for three bits of state that were parked in derived_values.

derived_values caches what a model derived (attributes, verdicts). Three things had
been written into it as fake rows because that needed no migration, where nobody
looking for them would look:

- "this artifact has cross-field pairs nobody has judged" -> `related_pending`
- "this link's page was fetched and had no article in it" -> `link_previews.body_tried`
- (and, in the search index's own key/value table) "which rule the stored links were
  chosen by" -> `related_state`, which also keeps the judge's calls for the day.

`link_previews.body_tried` does not ride the sync snapshot: the snapshot names its
columns (sync/snapshot.py `_PREVIEW_COLUMNS`).

Revision ID: 0039_related_judge_state
Revises: 0038_related_point
"""

from __future__ import annotations

from alembic import op

revision = "0039_related_judge_state"
down_revision = "0038_related_point"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE related_pending (" " artifact_id TEXT PRIMARY KEY," " since TEXT NOT NULL)"
    )
    op.execute("CREATE TABLE related_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    op.execute("ALTER TABLE link_previews ADD COLUMN body_tried INTEGER NOT NULL DEFAULT 0")
    # Carry over what the earlier build wrote, then clear it out of derived_values.
    op.execute(
        "INSERT OR IGNORE INTO related_pending (artifact_id, since)"
        " SELECT subject, created_at FROM derived_values WHERE scope = 'related_pending'"
    )
    op.execute(
        "UPDATE link_previews SET body_tried = 1 WHERE artifact_id IN"
        " (SELECT subject FROM derived_values WHERE scope = 'preview_body_tried')"
    )
    op.execute(
        "DELETE FROM derived_values WHERE scope IN ('related_pending', 'preview_body_tried')"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE link_previews DROP COLUMN body_tried")
    op.execute("DROP TABLE related_state")
    op.execute("DROP TABLE related_pending")
