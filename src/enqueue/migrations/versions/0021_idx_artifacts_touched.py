"""Index the wall's sort key.

The wall's default order is `touched` (`updated_at DESC`), and every page load
runs a scan plus sort over the whole artifacts table. The index below covers
exactly the predicate and ordering the default wall page uses:

    SELECT ... FROM artifacts
    WHERE deleted_at IS NULL [AND pinned = ?]
    ORDER BY updated_at DESC LIMIT ? OFFSET ?

so the common page turns into an index walk. `pinned` is a two-value flag, so
a leading `pinned` column would be wasted selectivity; it sits after the
high-cardinality `updated_at` for the pinned shelves, which are tiny.

Revision ID: 0021
Revises: 0020_drop_lens_judgments
"""

from __future__ import annotations

from alembic import op

revision = "0021_idx_artifacts_touched"
down_revision = "0020_drop_lens_judgments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX idx_artifacts_touched" " ON artifacts(deleted_at, pinned, updated_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_artifacts_touched")
