"""Related owner: which artifact chose each link.

A link is written in both directions by the artifact that chose it, and recomputing an
artifact replaces only its own choices, so a link another note chose is never lost.
Derived: the rows are copied as owned by their `artifact_id` and recomputed at startup
(related.VERSION).

Revision ID: 0042_related_owner
Revises: 0041_related_kind
"""

from __future__ import annotations

from alembic import op

revision = "0042_related_owner"
down_revision = "0041_related_kind"
branch_labels = None
depends_on = None

_COLUMNS = "artifact_id, related_id, score, model_version, created_at, via, point, kind, distance"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE related_new (
          artifact_id   TEXT NOT NULL,
          related_id    TEXT NOT NULL,
          owner         TEXT NOT NULL,
          score         REAL NOT NULL,
          model_version TEXT NOT NULL,
          created_at    TEXT NOT NULL,
          via           TEXT,
          point         TEXT,
          kind          TEXT,
          distance      REAL,
          PRIMARY KEY (artifact_id, related_id, owner)
        )
        """)
    op.execute(
        f"INSERT INTO related_new ({_COLUMNS}, owner) SELECT {_COLUMNS}, artifact_id FROM related"
    )
    op.execute("DROP TABLE related")
    op.execute("ALTER TABLE related_new RENAME TO related")
    op.execute("CREATE INDEX related_by_related_id ON related (related_id)")
    op.execute("CREATE INDEX related_by_owner ON related (owner)")


def downgrade() -> None:
    op.execute("""
        CREATE TABLE related_old (
          artifact_id   TEXT NOT NULL,
          related_id    TEXT NOT NULL,
          score         REAL NOT NULL,
          model_version TEXT NOT NULL,
          created_at    TEXT NOT NULL,
          via           TEXT,
          point         TEXT,
          kind          TEXT,
          distance      REAL,
          PRIMARY KEY (artifact_id, related_id)
        )
        """)
    op.execute(f"INSERT OR IGNORE INTO related_old ({_COLUMNS}) SELECT {_COLUMNS} FROM related")
    op.execute("DROP TABLE related")
    op.execute("ALTER TABLE related_old RENAME TO related")
    op.execute("CREATE INDEX related_by_related_id ON related (related_id)")
