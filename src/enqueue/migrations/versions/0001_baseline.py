"""Baseline: the artifact model.

Three classes of data, not two. The first build had only two and that was the bug.

  capture   came from the world.  body is NULL, bytes are frozen, fidelity is the point.
  note      you wrote it.         body is markdown, updated in place, every version kept.
  derived   the machine made it.  droppable and rebuildable from the two above.

This revision is the shape the database had before migrations existed. A database
created by the old `schema.sql` is stamped here rather than replayed; see `db.migrate`.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TABLES = (
    """
    CREATE TABLE artifacts (
      id           TEXT PRIMARY KEY,
      kind         TEXT NOT NULL,        -- note | link | pdf | image | file
      title        TEXT NOT NULL,

      -- Markdown, and ONLY for kind='note'. A capture has no body: its content is the
      -- bytes on disk, and editing it would destroy the only thing it was saved for.
      body         TEXT,

      source_url   TEXT,
      content_hash TEXT NOT NULL UNIQUE, -- dedupe key
      mime         TEXT,                 -- captures only
      filename     TEXT,                 -- captures only
      created_at   TEXT NOT NULL,
      updated_at   TEXT NOT NULL,
      local_only   INTEGER NOT NULL DEFAULT 0,
      status       TEXT NOT NULL,        -- ok | pending | text_only | failed

      CHECK (kind IN ('note', 'link', 'pdf', 'image', 'file')),
      -- A capture can never carry a body, so the invariant cannot be violated by a bug
      -- in application code. It is enforced here instead of hoped for.
      CHECK (kind = 'note' OR body IS NULL)
    )
    """,
    """
    -- Every state a note's body has ever been saved in, appended before each update.
    -- The artifact holds the present; this holds the past. Nothing the user wrote is
    -- ever destroyed, which is what makes two machines editing one note safe.
    CREATE TABLE artifact_versions (
      id          TEXT PRIMARY KEY,
      artifact_id TEXT NOT NULL REFERENCES artifacts(id),
      body        TEXT NOT NULL,
      created_at  TEXT NOT NULL
    )
    """,
    """
    -- Your commentary on a CAPTURED artifact. Append-only and superseding by id,
    -- because it comments on something immutable and there is no current state to
    -- resolve. A note's own body is never stored here.
    CREATE TABLE annotations (
      id            TEXT PRIMARY KEY,
      artifact_id   TEXT NOT NULL REFERENCES artifacts(id),
      supersedes_id TEXT REFERENCES annotations(id),
      text          TEXT NOT NULL,
      created_at    TEXT NOT NULL
    )
    """,
    # ---- derived. Every table below can be dropped and rebuilt from those above. ----
    """
    CREATE TABLE chunks (
      id          TEXT PRIMARY KEY,
      artifact_id TEXT NOT NULL REFERENCES artifacts(id),
      ordinal     INTEGER NOT NULL,
      text        TEXT NOT NULL,
      chunker     TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE facets (
      id            TEXT PRIMARY KEY,
      artifact_id   TEXT NOT NULL REFERENCES artifacts(id),
      level         INTEGER NOT NULL,   -- 0..4
      statement     TEXT NOT NULL,
      model_version TEXT NOT NULL,
      trust         REAL NOT NULL DEFAULT 0.5
    )
    """,
    """
    CREATE TABLE facet_skips (
      artifact_id TEXT PRIMARY KEY REFERENCES artifacts(id),
      reason      TEXT NOT NULL       -- too_short | kind | text_only
    )
    """,
    """
    CREATE TABLE secret_hits (
      id          TEXT PRIMARY KEY,
      artifact_id TEXT NOT NULL REFERENCES artifacts(id),
      kind        TEXT NOT NULL,
      line        INTEGER NOT NULL,
      excerpt     TEXT NOT NULL       -- value already redacted
    )
    """,
    """
    CREATE TABLE exhibits (
      id           TEXT PRIMARY KEY,
      name         TEXT NOT NULL,
      theme        TEXT NOT NULL,      -- IMMUTABLE after insert
      through_line TEXT,
      thin         INTEGER NOT NULL DEFAULT 0,
      thin_reason  TEXT,
      created_at   TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE exhibit_members (
      exhibit_id  TEXT NOT NULL REFERENCES exhibits(id),
      artifact_id TEXT NOT NULL REFERENCES artifacts(id),
      placard     TEXT NOT NULL,
      evidence    TEXT NOT NULL,
      strength    INTEGER NOT NULL,
      rank        INTEGER NOT NULL,
      origin      TEXT NOT NULL,      -- generated | manual
      ejected_at  TEXT,
      PRIMARY KEY (exhibit_id, artifact_id)
    )
    """,
)

INDEXES = (
    "CREATE INDEX idx_versions_artifact    ON artifact_versions(artifact_id)",
    "CREATE INDEX idx_annotations_artifact ON annotations(artifact_id)",
    "CREATE INDEX idx_chunks_artifact      ON chunks(artifact_id)",
    "CREATE INDEX idx_facets_artifact      ON facets(artifact_id)",
    "CREATE INDEX idx_secrets_artifact     ON secret_hits(artifact_id)",
    "CREATE INDEX idx_artifacts_created    ON artifacts(created_at DESC)",
)

DROP_ORDER = (
    "exhibit_members",
    "exhibits",
    "secret_hits",
    "facet_skips",
    "facets",
    "chunks",
    "annotations",
    "artifact_versions",
    "artifacts",
)


def upgrade() -> None:
    for statement in TABLES:
        op.execute(statement)
    for statement in INDEXES:
        op.execute(statement)


def downgrade() -> None:
    for table in DROP_ORDER:
        op.execute(f"DROP TABLE IF EXISTS {table}")
