"""Chats, and the topics a chat turns out to be about.

Asking used to be a single shot: name a theme, get a room, lose the thread. A chat
keeps the thread, which matters here more than it does in a general assistant,
because the thing being explored is the person's own collection and the exploration
is how the conceptualisation gets found.

Topics are the reason this is not just a transcript. As a conversation runs, the
concepts it circles are extracted and stored against the chat. Those are the same
kind of object a lens is, so a topic is clickable: it hangs a room.

Messages are append-only. Topics are derived and can be regenerated from the
messages at any time.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TABLES = (
    """
    CREATE TABLE chats (
      id          TEXT PRIMARY KEY,
      title       TEXT NOT NULL,

      -- What the chat can see. A chat opened from an artifact stays on that artifact,
      -- which is what makes "ask about this PDF" cheap instead of paying for the
      -- whole pipeline every time.
      scope_kind  TEXT NOT NULL DEFAULT 'everything',  -- everything | artifact | exhibit
      scope_id    TEXT,

      created_at  TEXT NOT NULL,
      updated_at  TEXT NOT NULL,

      CHECK (scope_kind IN ('everything', 'artifact', 'exhibit')),
      CHECK (scope_kind = 'everything' OR scope_id IS NOT NULL)
    )
    """,
    """
    -- Append-only. An answer is a thing that was said at a time, with the artifacts
    -- it was said from; editing it would make the citations lie.
    CREATE TABLE chat_messages (
      id         TEXT PRIMARY KEY,
      chat_id    TEXT NOT NULL REFERENCES chats(id),
      ordinal    INTEGER NOT NULL,
      role       TEXT NOT NULL,   -- user | assistant
      text       TEXT NOT NULL,

      -- Whether the answer came from the collection or was refused for want of it.
      -- Stored rather than inferred from the citation count, because "I looked and
      -- found nothing" is a different claim from "I did not look".
      grounded   INTEGER NOT NULL DEFAULT 0,

      created_at TEXT NOT NULL,

      CHECK (role IN ('user', 'assistant')),
      UNIQUE (chat_id, ordinal)
    )
    """,
    """
    CREATE TABLE chat_citations (
      message_id  TEXT NOT NULL REFERENCES chat_messages(id),
      artifact_id TEXT NOT NULL REFERENCES artifacts(id),
      rank        INTEGER NOT NULL,
      PRIMARY KEY (message_id, artifact_id)
    )
    """,
    """
    -- Derived. Drop it and the next generation pass rebuilds it from the messages.
    CREATE TABLE chat_topics (
      id         TEXT PRIMARY KEY,
      chat_id    TEXT NOT NULL REFERENCES chats(id),
      topic      TEXT NOT NULL,
      created_at TEXT NOT NULL,
      UNIQUE (chat_id, topic)
    )
    """,
)

INDEXES = (
    "CREATE INDEX idx_messages_chat ON chat_messages(chat_id, ordinal)",
    "CREATE INDEX idx_topics_chat   ON chat_topics(chat_id)",
    "CREATE INDEX idx_chats_updated ON chats(updated_at DESC)",
)

DROP_ORDER = ("chat_topics", "chat_citations", "chat_messages", "chats")


def upgrade() -> None:
    for statement in TABLES:
        op.execute(statement)
    for statement in INDEXES:
        op.execute(statement)


def downgrade() -> None:
    for table in DROP_ORDER:
        op.execute(f"DROP TABLE IF EXISTS {table}")
