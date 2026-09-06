"""Fold whitespace out of existing tag names.

A tag is now a single token: `normalize` strips all whitespace, so `Mental Models`
becomes `mentalmodels`. Older tags were stored trimmed and lowercased but could
still hold interior spaces (the Fabric "Space" import made some). This migration
brings stored names into the new canonical form. Where folding a name collides with
a tag that already exists in canonical form, the two are merged: every artifact of
the whitespace tag is repointed onto the surviving tag (deduped) and the now-empty
duplicate row is dropped.

Revision ID: 0027_tags_no_whitespace
Revises: 0026_facet_retry
"""

from __future__ import annotations

import re

from alembic import op

revision = "0027_tags_no_whitespace"
down_revision = "0026_facet_retry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.exec_driver_sql(
        "SELECT id, name FROM tags WHERE name GLOB '*[ \t\n\r]*'"
    ).fetchall()
    for tag_id, name in rows:
        canon = re.sub(r"\s+", "", name).lower()
        if not canon or canon == name:
            continue
        existing = bind.exec_driver_sql("SELECT id FROM tags WHERE name = ?", (canon,)).fetchone()
        if existing and existing[0] != tag_id:
            # A canonical tag already exists: move this tag's artifacts onto it
            # (INSERT OR IGNORE drops rows the artifact already has) and delete
            # the now-redundant whitespace tag.
            keep = existing[0]
            bind.exec_driver_sql(
                "INSERT OR IGNORE INTO artifact_tags (artifact_id, tag_id, created_at)"
                " SELECT artifact_id, ?, created_at FROM artifact_tags WHERE tag_id = ?",
                (keep, tag_id),
            )
            bind.exec_driver_sql("DELETE FROM artifact_tags WHERE tag_id = ?", (tag_id,))
            bind.exec_driver_sql("DELETE FROM tags WHERE id = ?", (tag_id,))
        else:
            bind.exec_driver_sql("UPDATE tags SET name = ? WHERE id = ?", (canon, tag_id))


def downgrade() -> None:
    # Folding whitespace is lossy - the original spacing is gone - so there is
    # nothing to restore. The canonical names are valid under the old rules too.
    pass
