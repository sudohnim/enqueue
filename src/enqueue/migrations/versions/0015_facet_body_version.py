"""Facets remember which body they were generated from.

A facet is a model-written abstraction of an artifact body, and the body is not
immutable: a note is edited, and every edit is a new body. Without a marker of
which body a facet came from, the concept layer can silently describe text that
has been deleted or rewritten, and a wrong concept hit costs more trust than a
missed one.

`facets.model_version` already records which model wrote the facet, but nothing
records which body it read. This adds that second provenance stamp:

  body_version  TEXT  - the artifact body version (updated_at) the facet was
                        generated from; NULL means the row predates this column
                        and its provenance is unknown

A facet is current only when both versions match the artifact's current state:
body_version equals the artifact's updated_at (the body it was built against)
and model_version equals the current model. Either mismatch makes the facet
stale. Staleness is cheap to detect - a comparison, no model call - and cheap
to heal: the next successful facet regeneration replaces the stale row with a
fresh one carrying both current versions. A NULL body_version is deliberately
treated as stale on read, because an unverifiable claim is not a verifiable one.

`body_version` is unconstrained, like `model_version` and `kind` before it: the
set of meaningful values is owned by the code, not the schema.

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE facets ADD COLUMN body_version TEXT")


def downgrade() -> None:
    # SQLite DROP COLUMN works on the pinned version; if a future engine
    # rejects it, this downgrade is dev-only, exactly as with kind/payload.
    op.execute("ALTER TABLE facets DROP COLUMN body_version")
