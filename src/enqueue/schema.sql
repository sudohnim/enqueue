-- Enqueue POC schema. See docs/PROGRESS.md task A2.
--
-- Two classes of table:
--   sacred     artifacts, blocks, note_entries  -- append-only, never UPDATE, never DELETE
--   derived    chunks, facets, facet_skips      -- droppable and rebuildable from the sacred set

CREATE TABLE IF NOT EXISTS artifacts (
  id            TEXT PRIMARY KEY,
  kind          TEXT NOT NULL,          -- note | bookmark | pdf | image | other
  title         TEXT NOT NULL,
  source_url    TEXT,
  content_hash  TEXT NOT NULL UNIQUE,   -- dedupe key
  captured_at   TEXT NOT NULL,
  imported_from TEXT,                   -- 'fabric:books' etc
  provenance    TEXT NOT NULL,          -- authored | pasted | unknown
  local_only    INTEGER NOT NULL DEFAULT 0,
  status        TEXT NOT NULL           -- ok | text_only | failed
);

CREATE TABLE IF NOT EXISTS blocks (
  id           TEXT PRIMARY KEY,
  artifact_id  TEXT NOT NULL REFERENCES artifacts(id),
  parent_id    TEXT REFERENCES blocks(id),   -- NULL at top level. THIS IS THE NESTING.
  ordinal      INTEGER NOT NULL,
  depth        INTEGER NOT NULL,
  text         TEXT NOT NULL,
  created_at   TEXT
);

-- Append-only. Editing a note appends a row with supersedes_id set.
-- There is no UPDATE on user-authored text anywhere in this codebase.
CREATE TABLE IF NOT EXISTS note_entries (
  id            TEXT PRIMARY KEY,
  artifact_id   TEXT NOT NULL REFERENCES artifacts(id),
  supersedes_id TEXT REFERENCES note_entries(id),
  text          TEXT NOT NULL,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
  id            TEXT PRIMARY KEY,
  artifact_id   TEXT NOT NULL REFERENCES artifacts(id),
  ordinal       INTEGER NOT NULL,
  text          TEXT NOT NULL,
  chunker       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS facets (
  id            TEXT PRIMARY KEY,
  artifact_id   TEXT NOT NULL REFERENCES artifacts(id),
  level         INTEGER NOT NULL,       -- 0..4
  statement     TEXT NOT NULL,
  model_version TEXT NOT NULL,
  trust         REAL NOT NULL DEFAULT 0.5
);

CREATE TABLE IF NOT EXISTS facet_skips (
  artifact_id  TEXT PRIMARY KEY REFERENCES artifacts(id),
  reason       TEXT NOT NULL           -- too_short | kind | text_only
);

CREATE TABLE IF NOT EXISTS secret_hits (
  id           TEXT PRIMARY KEY,
  artifact_id  TEXT NOT NULL REFERENCES artifacts(id),
  kind         TEXT NOT NULL,
  line         INTEGER NOT NULL,
  excerpt      TEXT NOT NULL           -- value already redacted
);

CREATE TABLE IF NOT EXISTS exhibits (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  theme         TEXT NOT NULL,          -- IMMUTABLE after insert
  through_line  TEXT,
  thin          INTEGER NOT NULL DEFAULT 0,
  thin_reason   TEXT,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exhibit_members (
  exhibit_id    TEXT NOT NULL REFERENCES exhibits(id),
  artifact_id   TEXT NOT NULL REFERENCES artifacts(id),
  placard       TEXT NOT NULL,
  evidence      TEXT NOT NULL,
  strength      INTEGER NOT NULL,
  rank          INTEGER NOT NULL,
  origin        TEXT NOT NULL,          -- generated | manual
  ejected_at    TEXT,
  PRIMARY KEY (exhibit_id, artifact_id)
);

CREATE INDEX IF NOT EXISTS idx_blocks_artifact ON blocks(artifact_id);
CREATE INDEX IF NOT EXISTS idx_blocks_parent   ON blocks(parent_id);
CREATE INDEX IF NOT EXISTS idx_notes_artifact  ON note_entries(artifact_id);
CREATE INDEX IF NOT EXISTS idx_chunks_artifact ON chunks(artifact_id);
CREATE INDEX IF NOT EXISTS idx_facets_artifact ON facets(artifact_id);
CREATE INDEX IF NOT EXISTS idx_secrets_artifact ON secret_hits(artifact_id);
