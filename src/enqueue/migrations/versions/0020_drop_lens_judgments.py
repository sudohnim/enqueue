"""Drop the lens judgment cache.

The lens/curate surface was removed (Phase M): the POST /lens, /curate, and
lens-cache endpoints are gone, so lens_judgments has no reader left. It is a
derived cache - every row is recomputable model output - so it drops cleanly;
the only cost is that a future re-introduction starts with an empty cache.

Revision ID: 0020
Revises: 0019_drop_exhibits
"""

from __future__ import annotations

from alembic import op

revision = "0020_drop_lens_judgments"
down_revision = "0019_drop_exhibits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS lens_judgments")


def downgrade() -> None:
    # Mirror of 0009: recreate the empty table. Judgments are gone either way.
    op.execute("""
        CREATE TABLE lens_judgments (
            lens_key      TEXT NOT NULL,
            artifact_id   TEXT NOT NULL,
            belongs       INTEGER NOT NULL,
            strength      REAL NOT NULL,
            placard       TEXT NOT NULL DEFAULT '',
            evidence      TEXT NOT NULL DEFAULT '',
            model_version TEXT NOT NULL,
            created_at    TEXT NOT NULL,
            PRIMARY KEY (lens_key, artifact_id, model_version)
        )
        """)
    op.execute("CREATE INDEX ix_lens_judgments_lens_key ON lens_judgments (lens_key)")
