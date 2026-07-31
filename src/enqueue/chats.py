"""Chats: exploring the collection by talking to it.

Asking used to be one shot. You named a theme, a room was hung, and the thread was
gone. That is the wrong shape for the thing this product is actually for, because
the conceptualisation is rarely known in advance. It gets found by circling.

So a chat keeps the thread, and the concepts it circles are extracted and kept
against it. Those topics are the same kind of object a lens is: a topic taken out of
a conversation can be handed straight to the curator to hang a room. That is the
whole reason to store them rather than to name conversations by their first line.

Three model calls, in falling order of importance:

  answer   grounded in retrieved passages, or honestly refused
  topics   the concepts the conversation is circling
  title    what it is called in the list

Only the first one blocks the reply. A failure in either of the other two leaves a
chat that works and is named by its first question, which is a bad name and not a
broken product.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from . import db
from .prompts import CHAT_ANSWER, CHAT_TITLE, CHAT_TOPICS
from .providers.base import get_provider
from .schemas import Answer, ChatTitle, ChatTopics

log = logging.getLogger(__name__)

# How many passages an answer is allowed to read. Small on purpose: a local 8B model
# given twenty passages produces a summary of the passages instead of an answer.
PASSAGES = 8
PASSAGE_WORDS = 220

# Turns of history sent with a question. The whole transcript would crowd out the
# passages, which are the part that makes the answer worth anything.
HISTORY_TURNS = 6

UNTITLED = "New chat"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- shape


def create(scope_kind: str = "everything", scope_id: str | None = None) -> dict:
    if scope_kind not in ("everything", "artifact", "exhibit"):
        raise ValueError(f"unknown scope {scope_kind!r}")
    if scope_kind != "everything" and not scope_id:
        raise ValueError(f"a {scope_kind} chat needs something to be scoped to")

    chat_id = str(uuid.uuid4())
    now = _now()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO chats (id, title, scope_kind, scope_id, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?)",
            (chat_id, UNTITLED, scope_kind, scope_id, now, now),
        )
    return get(chat_id)


def get(chat_id: str) -> dict:
    conn = db.get_conn()
    try:
        chat = conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
        if chat is None:
            raise KeyError(chat_id)

        messages = conn.execute(
            "SELECT * FROM chat_messages WHERE chat_id = ? ORDER BY ordinal", (chat_id,)
        ).fetchall()

        cited: dict[str, list[dict]] = {}
        for row in conn.execute(
            "SELECT c.message_id, c.artifact_id, c.rank, a.title, a.kind"
            " FROM chat_citations c"
            " JOIN chat_messages m ON m.id = c.message_id"
            " JOIN artifacts a ON a.id = c.artifact_id"
            " WHERE m.chat_id = ? ORDER BY c.rank",
            (chat_id,),
        ):
            cited.setdefault(row["message_id"], []).append(
                {"artifact_id": row["artifact_id"], "title": row["title"], "kind": row["kind"]}
            )

        topics = conn.execute(
            "SELECT id, topic FROM chat_topics WHERE chat_id = ? ORDER BY created_at",
            (chat_id,),
        ).fetchall()

        scope_label = "everything"
        if chat["scope_kind"] == "artifact":
            row = conn.execute(
                "SELECT title FROM artifacts WHERE id = ?", (chat["scope_id"],)
            ).fetchone()
            scope_label = row["title"] if row else "one artifact"
        elif chat["scope_kind"] == "exhibit":
            row = conn.execute(
                "SELECT name FROM exhibits WHERE id = ?", (chat["scope_id"],)
            ).fetchone()
            scope_label = row["name"] if row else "one room"

        return {
            "chat": dict(chat) | {"scope_label": scope_label},
            "messages": [dict(m) | {"cited": cited.get(m["id"], [])} for m in messages],
            "topics": [dict(t) for t in topics],
        }
    finally:
        conn.close()


def pin(chat_id: str, pinned: bool = True) -> dict:
    """Keep a conversation at the top.

    Recency is the right order for the threads you are working through and the wrong
    one for the two or three you keep returning to: those sink after one busy week,
    and sinking is the failure this product exists to prevent.
    """
    with db.transaction() as conn:
        try:
            pinned_int = int(pinned)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"pinned must be an integer: {exc}") from None
        cur = conn.execute("UPDATE chats SET pinned = ? WHERE id = ?", (pinned_int, chat_id))
        if not cur.rowcount:
            raise KeyError(chat_id)
    return get(chat_id)


def listing(limit: int = 40) -> dict:
    """Every chat, pinned first then newest, each with the topics it is about."""
    conn = db.get_conn()
    try:
        chats = conn.execute(
            "SELECT * FROM chats ORDER BY pinned DESC, updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        topics: dict[str, list[str]] = {}
        for row in conn.execute("SELECT chat_id, topic FROM chat_topics ORDER BY created_at"):
            topics.setdefault(row["chat_id"], []).append(row["topic"])

        return {"items": [dict(c) | {"topics": topics.get(c["id"], [])} for c in chats]}
    finally:
        conn.close()


def rename(chat_id: str, title: str) -> dict:
    title = title.strip()
    if not title:
        raise ValueError("a chat needs a name")
    with db.transaction() as conn:
        cur = conn.execute(
            "UPDATE chats SET title = ?, updated_at = ? WHERE id = ?",
            (title[:120], _now(), chat_id),
        )
        if not cur.rowcount:
            raise KeyError(chat_id)
    return get(chat_id)


def delete(chat_id: str) -> dict:
    """Chats are the one thing here that can be thrown away.

    Everything else in the museum is kept by design. A conversation is not an
    artifact: it is scaffolding around the artifacts, and keeping every one of them
    forever would make the list useless, which is the failure mode the whole product
    is built against.
    """
    with db.transaction() as conn:
        exists = conn.execute("SELECT 1 FROM chats WHERE id = ?", (chat_id,)).fetchone()
        if exists is None:
            raise KeyError(chat_id)
        conn.execute(
            "DELETE FROM chat_citations WHERE message_id IN"
            " (SELECT id FROM chat_messages WHERE chat_id = ?)",
            (chat_id,),
        )
        conn.execute("DELETE FROM chat_messages WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM chat_topics WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    return {"deleted": chat_id}


# ----------------------------------------------------------------------- retrieval


def _clip(text: str, words: int = PASSAGE_WORDS) -> str:
    parts = text.split()
    return text if len(parts) <= words else " ".join(parts[:words]) + " ..."


def _scoped_passages(conn, artifact_ids: list[str]) -> list[dict]:
    """Every chunk of a named set of artifacts. No search: the scope is the answer."""
    if not artifact_ids:
        return []
    marks = ",".join("?" * len(artifact_ids))
    rows = conn.execute(
        f"SELECT c.id, c.artifact_id, c.text, a.title, a.kind FROM chunks c"
        f" JOIN artifacts a ON a.id = c.artifact_id"
        f" WHERE c.artifact_id IN ({marks}) ORDER BY c.artifact_id, c.ordinal",
        artifact_ids,
    ).fetchall()
    return [dict(r) for r in rows][:PASSAGES]


def passages(question: str, scope_kind: str, scope_id: str | None) -> list[dict]:
    """The passages an answer is allowed to read.

    Scoped chats do not search at all: if you asked about one PDF, the PDF is the
    candidate set, and running retrieval over it would only find reasons to leave
    parts of it out.
    """
    conn = db.get_conn()
    try:
        if scope_kind == "artifact":
            if scope_id is None:
                return []
            return _scoped_passages(conn, [scope_id])
        if scope_kind == "exhibit":
            members = [
                r["artifact_id"]
                for r in conn.execute(
                    "SELECT artifact_id FROM exhibit_members WHERE exhibit_id = ?"
                    " AND ejected_at IS NULL ORDER BY rank",
                    (scope_id,),
                )
            ]
            return _scoped_passages(conn, members)

        from .index.store import get_store

        store = get_store()
        found: dict[str, dict] = {}
        for hit in store.search(store.CHUNKS, question, limit=PASSAGES):
            found[hit["chunk_id"]] = {"score": hit["score"], "why": "passage"}

        # The other half of the abstraction gap. A question phrased as a concept can
        # match a facet whose artifact shares no vocabulary with it, which is the case
        # the whole facet ladder exists for. Pull the artifact's opening chunk in so
        # the answer has something literal to stand on.
        for hit in store.search(store.FACETS, question, limit=4):
            row = conn.execute(
                "SELECT id FROM chunks WHERE artifact_id = ? ORDER BY ordinal LIMIT 1",
                (hit["artifact_id"],),
            ).fetchone()
            if row and row["id"] not in found:
                found[row["id"]] = {"score": hit["score"], "why": f"facet L{hit.get('level')}"}

        if not found:
            return []

        marks = ",".join("?" * len(found))
        rows = conn.execute(
            f"SELECT c.id, c.artifact_id, c.text, a.title, a.kind FROM chunks c"
            f" JOIN artifacts a ON a.id = c.artifact_id WHERE c.id IN ({marks})",
            list(found),
        ).fetchall()

        out = [dict(r) | found[r["id"]] for r in rows]
        out.sort(key=lambda r: r["score"], reverse=True)
        return out[:PASSAGES]
    finally:
        conn.close()


def readiness() -> dict:
    """Whether there is anything to retrieve from, and why not if not.

    An empty answer has three completely different causes: nothing saved, nothing
    indexed, or nothing relevant. Telling them apart is the difference between a
    person fixing it in ten seconds and concluding the product does not work.
    """
    conn = db.get_conn()
    try:
        artifacts = conn.execute("SELECT COUNT(*) AS n FROM artifacts").fetchone()["n"]
        chunks = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
    finally:
        conn.close()

    indexed = None
    try:
        from .index.store import get_store

        indexed = get_store().counts().get("chunks")
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return {"ready": False, "reason": f"the index is unavailable: {exc}"}

    if not artifacts:
        return {"ready": False, "reason": "nothing has been saved yet"}
    if not chunks:
        return {"ready": False, "reason": "nothing saved has any text in it yet"}
    if not indexed:
        return {"ready": False, "reason": "the index is empty; run `enq index` to rebuild it"}
    return {"ready": True, "reason": None}


# ------------------------------------------------------------------------- talking


def _history(conn, chat_id: str) -> str:
    rows = conn.execute(
        "SELECT role, text FROM chat_messages WHERE chat_id = ? ORDER BY ordinal DESC LIMIT ?",
        (chat_id, HISTORY_TURNS),
    ).fetchall()
    if not rows:
        return ""
    lines = [f"{r['role']}: {' '.join(r['text'].split())[:600]}" for r in reversed(rows)]
    return "Earlier in this conversation:\n" + "\n".join(lines) + "\n\n"


def empty_scope_reason(scope_kind: str, scope_id: str | None) -> str | None:
    """Why a scoped chat found nothing, when the reason is the scope itself.

    Measured: a chat opened from a link whose preview had failed reported "nothing you
    have saved speaks to that yet" for a question the collection answered immediately
    at a retrieval score of 1.0. The answer was true of the scope and false of the
    museum, and nothing on screen said which one had been searched.
    """
    if scope_kind == "everything" or not scope_id:
        return None

    conn = db.get_conn()
    try:
        if scope_kind == "artifact":
            row = conn.execute(
                "SELECT kind, title FROM artifacts WHERE id = ?", (scope_id,)
            ).fetchone()
            if row is None:
                return "that artifact is gone"
            if row["kind"] == "link":
                return (
                    "this link has not been fetched, so there is nothing in it to read yet. "
                    "Fetch a preview, or ask the whole museum instead"
                )
            if row["kind"] in ("pdf", "image", "file"):
                return (
                    f"no text has been extracted from this {row['kind']} yet, so there is "
                    "nothing in it to read. Ask the whole museum instead"
                )
            return "this artifact has no text in it yet"

        if scope_kind == "exhibit":
            return "nothing in this room has any text in it yet"
    finally:
        conn.close()
    return None


def _ask_model(
    question: str, history: str, found: list[dict], empty_reason: str | None = None
) -> Answer:
    if not found:
        return Answer(
            answer=(
                f"Nothing here to answer from: {empty_reason}."
                if empty_reason
                else "Nothing you have saved speaks to that yet."
            ),
            grounded=False,
            cited=[],
        )

    body = "\n\n".join(f"[{p['artifact_id']}] {p['title']}\n{_clip(p['text'])}" for p in found)
    return get_provider().complete(
        system=CHAT_ANSWER,
        user=f"{history}Question: {question}\n\nPassages:\n\n{body}",
        response_model=Answer,
        context={"offered_artifact_ids": [p["artifact_id"] for p in found]},
    )


def _append(conn, chat_id: str, role: str, text: str, grounded: bool = False) -> str:
    ordinal = conn.execute(
        "SELECT COALESCE(MAX(ordinal), -1) + 1 AS n FROM chat_messages WHERE chat_id = ?",
        (chat_id,),
    ).fetchone()["n"]
    message_id = str(uuid.uuid4())
    try:
        grounded_int = int(grounded)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"grounded must be an integer: {exc}") from None
    conn.execute(
        "INSERT INTO chat_messages (id, chat_id, ordinal, role, text, grounded, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (message_id, chat_id, ordinal, role, text, grounded_int, _now()),
    )
    return message_id


def send(chat_id: str, text: str) -> dict:
    """One turn: the question and its answer, written together or not at all.

    Writing the question first and the answer afterwards looks natural and is wrong.
    When the model call fails, the question is left in the transcript with nothing
    under it, and asking again appends a second copy. Measured, on the second turn of
    the first real conversation: two identical questions, one answer.

    So nothing is written until there is an answer to write with it. The interface
    shows the question immediately; the log gains it once the exchange is real.
    """
    text = text.strip()
    if not text:
        raise ValueError("say something")

    conn = db.get_conn()
    try:
        chat = conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
        if chat is None:
            raise KeyError(chat_id)
        history = _history(conn, chat_id)
        first_exchange = (
            conn.execute(
                "SELECT COUNT(*) AS n FROM chat_messages WHERE chat_id = ?", (chat_id,)
            ).fetchone()["n"]
            == 0
        )
    finally:
        conn.close()

    found = passages(text, chat["scope_kind"], chat["scope_id"])
    empty_reason = empty_scope_reason(chat["scope_kind"], chat["scope_id"]) if not found else None
    answer = _ask_model(text, history, found, empty_reason)

    by_artifact = {p["artifact_id"]: p for p in found}
    with db.transaction() as conn:
        _append(conn, chat_id, "user", text)
        message_id = _append(conn, chat_id, "assistant", answer.answer, answer.grounded)
        for rank, artifact_id in enumerate(dict.fromkeys(answer.cited)):
            if artifact_id in by_artifact:
                conn.execute(
                    "INSERT OR IGNORE INTO chat_citations (message_id, artifact_id, rank)"
                    " VALUES (?,?,?)",
                    (message_id, artifact_id, rank),
                )
        conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (_now(), chat_id))

    if first_exchange:
        _name(chat_id, text, answer.answer)
    _retopic(chat_id)

    return get(chat_id)


# --------------------------------------------------------------------------- names


def _name(chat_id: str, question: str, answer: str) -> None:
    """Title the chat from its first exchange. Best effort: a bad name is not a fault."""
    try:
        named = get_provider().complete(
            system=CHAT_TITLE,
            user=f"Question: {question}\n\nAnswer: {' '.join(answer.split())[:800]}",
            response_model=ChatTitle,
        )
        title = named.title
    except Exception:  # noqa: BLE001
        log.warning("could not name chat %s; falling back to its first question", chat_id)
        title = " ".join(question.split())[:60]

    with db.transaction() as conn:
        conn.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))


def _retopic(chat_id: str) -> None:
    """Re-derive the concepts this conversation is circling.

    Regenerated from the whole transcript each time rather than appended to, because
    a conversation's real subject is often not visible until several turns in, and a
    topic list that only grows accumulates the wrong early guesses forever.

    Existing topics are kept if they come back, so a topic that has already been used
    to hang a room does not change identity underneath it.
    """
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT role, text, grounded FROM chat_messages WHERE chat_id = ? ORDER BY ordinal",
            (chat_id,),
        ).fetchall()
    finally:
        conn.close()

    if len(rows) < 2:
        return

    # A conversation where nothing was found has no concept in it to extract, and the
    # model will invent one rather than return none. Observed: a chat whose only two
    # answers were both "nothing here to answer from" produced the topics
    # "NotesNotFetched" and "MuseumCollection", which name the failure and the app.
    #
    # Topics are meant to be handed back to the curator as a lens. A lens drawn from
    # an empty exchange retrieves nothing, so it is worse than having none.
    if not any(row["grounded"] for row in rows if row["role"] == "assistant"):
        return

    transcript = "\n\n".join(f"{r['role']}: {' '.join(r['text'].split())[:700]}" for r in rows)
    try:
        found = get_provider().complete(
            system=CHAT_TOPICS,
            user=transcript[:6000],
            response_model=ChatTopics,
        )
    except Exception:  # noqa: BLE001 - a chat with no topics still works
        log.warning("could not derive topics for chat %s", chat_id)
        return

    now = _now()
    with db.transaction() as conn:
        keep = {t.lower() for t in found.topics}
        for row in conn.execute(
            "SELECT id, topic FROM chat_topics WHERE chat_id = ?", (chat_id,)
        ).fetchall():
            if row["topic"].lower() not in keep:
                conn.execute("DELETE FROM chat_topics WHERE id = ?", (row["id"],))
        for topic in found.topics:
            conn.execute(
                "INSERT OR IGNORE INTO chat_topics (id, chat_id, topic, created_at)"
                " VALUES (?,?,?,?)",
                (str(uuid.uuid4()), chat_id, topic, now),
            )
