"""Drop the exhibits and exhibit_members tables, and the exhibit chat scope.

The "collections" model (exhibits + exhibit_members, with the /exhibits* API) was
an earlier agent's workaround for the add-to-grouping bug. Saved groupings
(saved_pivots) carry the same concept with a re-runnable spec, so the collections
surface is removed entirely (Phase M).

Chats could be scoped to an exhibit; that scope dies with the tables. Existing
exhibit-scoped rows are rewritten to 'everything' during this migration, and the
scope_kind CHECK is recreated without 'exhibit'.

Revision ID: 0019
Revises: 0018
"""

from __future__ import annotations

from alembic import op

revision = "0019_drop_exhibits"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Exhibit-scoped chats become everything-scoped, and their scope_id (which
    # referenced an exhibit row that is about to be dropped) is cleared. Do this
    # before the table rebuild so the copy below never sees an 'exhibit' row the
    # new CHECK rejects.
    op.execute(
        "UPDATE chats SET scope_kind = 'everything', scope_id = NULL"
        " WHERE scope_kind = 'exhibit'"
    )

    # SQLite cannot ALTER TABLE ... DROP CONSTRAINT, so the chats table is
    # rebuilt without 'exhibit' in the scope_kind CHECK. The shape matches the
    # schema at head (0003 chats + 0004 pinned).
    op.execute(
        "CREATE TABLE chats_new ("
        "  id          TEXT PRIMARY KEY,"
        "  title       TEXT NOT NULL,"
        "  scope_kind  TEXT NOT NULL DEFAULT 'everything',"
        "  scope_id    TEXT,"
        "  created_at  TEXT NOT NULL,"
        "  updated_at  TEXT NOT NULL,"
        "  pinned      INTEGER NOT NULL DEFAULT 0,"
        "  CHECK (scope_kind IN ('everything', 'artifact')),"
        "  CHECK (scope_kind = 'everything' OR scope_id IS NOT NULL)"
        ")"
    )
    op.execute(
        "INSERT INTO chats_new (id, title, scope_kind, scope_id, created_at, updated_at,"
        " pinned) SELECT id, title, scope_kind, scope_id, created_at, updated_at,"
        " pinned FROM chats"
    )
    op.execute("DROP TABLE chats")
    op.execute("ALTER TABLE chats_new RENAME TO chats")
    op.execute("CREATE INDEX idx_chats_updated ON chats(updated_at DESC)")

    # The members table goes first; its rows are the ones that reference exhibits.
    op.execute("DROP TABLE IF EXISTS exhibit_members")
    op.execute("DROP TABLE IF EXISTS exhibits")


def downgrade() -> None:
    # Downgrade not supported; recreating exhibits would not restore membership.
    pass
