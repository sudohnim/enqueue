"""Materialized result cache for a saved view (custom pivot).

A saved view stores its spec and re-runs live (pivots_saved), but a spec with an
`extract`/`enrich` step pays for model judgments every open - slow on a large
library even though the judgments are cached per value. This adds a cache of the
computed group STRUCTURE (each group's key + artifact_ids, not the hydrated cards)
so a re-open renders instantly from the cache while a background refresh re-runs the
spec and updates it. The cards themselves are always re-hydrated from the current
artifacts on serve, so titles/state stay fresh; only the expensive grouping is cached.

`result_json` is the stripped pivot.run result (groups without `items`), `result_at`
is when it was computed. Both null means "never run" - the first open computes and
fills them. A spec edit (include/exclude/rename) clears the cache so the next open
recomputes.

Revision ID: 0029_pivot_result_cache
Revises: 0028_embedded_at
"""

from __future__ import annotations

from alembic import op

revision = "0029_pivot_result_cache"
down_revision = "0028_embedded_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE saved_pivots ADD COLUMN result_json TEXT")
    op.execute("ALTER TABLE saved_pivots ADD COLUMN result_at TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE saved_pivots DROP COLUMN result_at")
    op.execute("ALTER TABLE saved_pivots DROP COLUMN result_json")
