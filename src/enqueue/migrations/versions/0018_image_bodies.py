"""An image's vision description may live in its body (K.11).

Captures were forbidden a body because their content is the bytes on disk, and
editing them would destroy the only thing they were saved for. That is still
true of anything a person wrote. But an image's description is machine derived:
the vision step writes it at ingest, the pipeline regenerates it, and nobody
edits it by hand. Allowing `kind='image'` to carry a body lets the description
flow through chunking, facets, entities, and search exactly like a note's text,
with no second home for it.

SQLite cannot alter a CHECK constraint, so the table is rebuilt with the same
columns and indexes and the relaxed check. Foreign keys are turned off for the
swap, as the SQLite procedure for such a rebuild requires; `foreign_key_check`
confirms nothing was orphaned before they are turned back on.

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

# The column list, kept in one place so the copy and the rebuild cannot drift.
_COLUMNS = (
    "id, kind, title, body, source_url, content_hash, mime, filename, created_at,"
    " updated_at, local_only, status, pinned, deleted_at, pages"
)


def upgrade() -> None:
    # PRAGMA foreign_keys is a no-op inside a transaction, so the whole swap runs
    # in autocommit: off during the rebuild, checked, then back on.
    with op.get_context().autocommit_block():
        op.execute("PRAGMA foreign_keys = OFF")
        op.execute("""
            CREATE TABLE artifacts_new (
              id           TEXT PRIMARY KEY,
              kind         TEXT NOT NULL,        -- note | link | pdf | image | file
              title        TEXT NOT NULL,

              -- Markdown for kind='note'; the machine-written vision description for
              -- kind='image' (K.11). A capture otherwise has no body: its content is
              -- the bytes on disk, and editing it would destroy the only thing it was
              -- saved for.
              body         TEXT,

              source_url   TEXT,
              content_hash TEXT NOT NULL UNIQUE, -- dedupe key
              mime         TEXT,                 -- captures only
              filename     TEXT,                 -- captures only
              created_at   TEXT NOT NULL,
              updated_at   TEXT NOT NULL,
              local_only   INTEGER NOT NULL DEFAULT 0,
              status       TEXT NOT NULL,        -- ok | pending | text_only | failed
              pinned       INTEGER NOT NULL DEFAULT 0,
              deleted_at   TEXT,
              pages        INTEGER,

              CHECK (kind IN ('note', 'link', 'pdf', 'image', 'file')),
              -- An image's body is derived text the pipeline writes and regenerates,
              -- never something a person edits, so it cannot destroy the capture.
              CHECK (kind IN ('note', 'image') OR body IS NULL)
            )
            """)
        op.execute(f"INSERT INTO artifacts_new ({_COLUMNS}) SELECT {_COLUMNS} FROM artifacts")
        op.execute("DROP TABLE artifacts")
        op.execute("ALTER TABLE artifacts_new RENAME TO artifacts")
        op.execute("CREATE INDEX idx_artifacts_created ON artifacts(created_at DESC)")
        op.execute("CREATE INDEX idx_artifacts_pinned ON artifacts(pinned DESC, created_at DESC)")
        op.execute("CREATE INDEX idx_artifacts_live ON artifacts(deleted_at, created_at DESC)")
        op.execute("PRAGMA foreign_key_check")
        op.execute("PRAGMA foreign_keys = ON")


def downgrade() -> None:
    """Put the old check back. An image with a body would violate it, so the
    description is discarded - it is derived text, rebuildable by re-running
    the ingest pipeline."""
    with op.get_context().autocommit_block():
        op.execute("PRAGMA foreign_keys = OFF")
        op.execute("""
            CREATE TABLE artifacts_old (
              id           TEXT PRIMARY KEY,
              kind         TEXT NOT NULL,
              title        TEXT NOT NULL,
              body         TEXT,
              source_url   TEXT,
              content_hash TEXT NOT NULL UNIQUE,
              mime         TEXT,
              filename     TEXT,
              created_at   TEXT NOT NULL,
              updated_at   TEXT NOT NULL,
              local_only   INTEGER NOT NULL DEFAULT 0,
              status       TEXT NOT NULL,
              pinned       INTEGER NOT NULL DEFAULT 0,
              deleted_at   TEXT,
              pages        INTEGER,
              CHECK (kind IN ('note', 'link', 'pdf', 'image', 'file')),
              CHECK (kind = 'note' OR body IS NULL)
            )
            """)
        op.execute(
            "INSERT INTO artifacts_old SELECT * FROM artifacts"
            " WHERE kind = 'note' OR body IS NULL"
        )
        op.execute("DROP TABLE artifacts")
        op.execute("ALTER TABLE artifacts_old RENAME TO artifacts")
        op.execute("CREATE INDEX idx_artifacts_created ON artifacts(created_at DESC)")
        op.execute("CREATE INDEX idx_artifacts_pinned ON artifacts(pinned DESC, created_at DESC)")
        op.execute("CREATE INDEX idx_artifacts_live ON artifacts(deleted_at, created_at DESC)")
        op.execute("PRAGMA foreign_key_check")
        op.execute("PRAGMA foreign_keys = ON")
