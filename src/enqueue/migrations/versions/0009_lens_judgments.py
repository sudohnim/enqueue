"""Cached lens judgments: the same topic is instant next time.

Phase 8. A judgment is one model call per artifact per lens, and the rerank
cost grows with the library. Most lenses get curated once and then re-visited
as the wall pages; the first run pays for the model calls, and every later run
reads the row instead.

The cache is per (lens_key, artifact_id, model_version): the same artifact
under the same normalized lens, produced by the same model, is never judged
twice. A different model is a different reasoning system, and rows it did not
produce would be stale reasoning, so model_version is part of the key rather
than a column that is compared.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.execute("DROP TABLE lens_judgments")
