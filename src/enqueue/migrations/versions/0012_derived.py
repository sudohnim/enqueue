"""Cached derived values for the pivot engine.

Phase P1 of the pivot feature. A pivot groups artifacts by an attribute the
model computes, and computing is expensive, so every derived value is cached.
One table serves everything, keyed by what the value was derived from:

  scope   'artifact' when the value came from one artifact's content (extract),
          'value' when it was inferred from another value (enrich)
  subject an artifact id for scope 'artifact', the exact input string otherwise
  source  'model' when the model produced the row, 'user' when a person
          corrected it. A user correction always wins on read (rule 2: the
          director beats the curator), so source is part of the primary key.

grounded is the 'show your work' promise: 1 when the value came from the
artifact's own content, 0 when it came from the model's world knowledge. The
flag travels with the value everywhere and the UI shows it. model_version is
empty when source = 'user' and is otherwise the producing model, so a model
change never serves stale reasoning.

Like 0011, the table uses IF NOT EXISTS because the store can create the same
table before alembic ever runs on a brand-new database, and the two paths must
not fight.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS derived_values (
          scope         TEXT NOT NULL,       -- 'artifact' or 'value'
          subject       TEXT NOT NULL,       -- an artifact id, or the exact input string
          attribute     TEXT NOT NULL,       -- canonical attribute name, lowercased
          value         TEXT NOT NULL,       -- the derived value (empty string = "none found")
          grounded      INTEGER NOT NULL,    -- 1 from content, 0 from world knowledge
          source        TEXT NOT NULL,       -- 'model' or 'user'
          model_version TEXT NOT NULL,       -- '' when source = 'user'
          created_at    TEXT NOT NULL,
          PRIMARY KEY (scope, subject, attribute, source)
        )
        """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS derived_values")
