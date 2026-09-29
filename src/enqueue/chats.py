"""Chats: conversations with the library.

A turn is submitted, not computed: the answer worker (chats_worker) answers, then
titles and re-topics best effort. See AGENTS.md "Chat".
"""

from __future__ import annotations

import json
import logging
import uuid

from . import chats_worker, db, pivot
from .prompts import CHAT_ANSWER, CHAT_TITLE, CHAT_TOPICS
from .providers.base import get_provider
from .retrieve.candidates import hit_is_stale
from .schemas import Answer, ChatTitle, ChatTopics

log = logging.getLogger(__name__)

# Passages an answer may read. Small: a local 8B model given more summarizes instead.
PASSAGES = 8
# Max chunks per artifact in a passage set, so one long note cannot crowd out the rest.
CHUNKS_PER_ARTIFACT = 2
PASSAGE_WORDS = 220

# History turns sent with a question; the cap only bounds pathological threads.
HISTORY_TURNS = 40

UNTITLED = "New chat"


def _push(chat_id: str) -> None:
    """Best-effort push of the whole chat snapshot to the relay. Never fails the local write."""
    try:
        from .sync.client import push_chat

        push_chat(chat_id)
    except Exception:  # noqa: BLE001 - sync is best-effort, never fatal to the local op
        pass


def create(scope_kind: str = "everything", scope_id: str | None = None) -> dict:
    if scope_kind not in ("everything", "artifact"):
        raise ValueError(f"unknown scope {scope_kind!r}")
    if scope_kind != "everything" and not scope_id:
        raise ValueError(f"a {scope_kind} chat needs something to be scoped to")

    chat_id = str(uuid.uuid4())
    now = db.now()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO chats (id, title, scope_kind, scope_id, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?)",
            (chat_id, UNTITLED, scope_kind, scope_id, now, now),
        )
    _push(chat_id)
    return get(chat_id)


def get(chat_id: str) -> dict:
    conn = db.get_conn()
    try:
        chat = conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
        # A tombstone reads as missing.
        if chat is None or chat["deleted_at"]:
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

        def _message(m) -> dict:
            out = dict(m)
            raw = out.pop("payload", None)
            out["payload"] = json.loads(raw) if raw else None
            return out | {"cited": cited.get(m["id"], [])}

        scope_label = "everything"
        if chat["scope_kind"] == "artifact":
            row = conn.execute(
                "SELECT title FROM artifacts WHERE id = ?", (chat["scope_id"],)
            ).fetchone()
            scope_label = row["title"] if row else "one artifact"

        return {
            "chat": dict(chat) | {"scope_label": scope_label},
            "messages": [_message(m) for m in messages],
            "topics": [dict(t) for t in topics],
        }
    finally:
        conn.close()


def pin(chat_id: str, pinned: bool = True) -> dict:
    """Keep a conversation at the top of the list."""
    with db.transaction() as conn:
        try:
            pinned_int = int(pinned)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"pinned must be an integer: {exc}") from None
        # Bump updated_at so the change wins LWW on other devices.
        cur = conn.execute(
            "UPDATE chats SET pinned = ?, updated_at = ? WHERE id = ?",
            (pinned_int, db.now(), chat_id),
        )
        if not cur.rowcount:
            raise KeyError(chat_id)
    _push(chat_id)
    return get(chat_id)


def listing(limit: int = 40) -> dict:
    """Every chat, pinned first then newest, each with the topics it is about."""
    conn = db.get_conn()
    try:
        chats = conn.execute(
            "SELECT * FROM chats WHERE deleted_at IS NULL"
            " ORDER BY pinned DESC, updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        topics: dict[str, list[str]] = {}
        if chats:
            ids = [c["id"] for c in chats]
            for row in conn.execute(
                "SELECT chat_id, topic FROM chat_topics"
                " WHERE chat_id IN (SELECT value FROM json_each(?))"
                " ORDER BY created_at",
                (json.dumps(ids),),
            ):
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
            (title[:120], db.now(), chat_id),
        )
        if not cur.rowcount:
            raise KeyError(chat_id)
    _push(chat_id)
    return get(chat_id)


def delete(chat_id: str) -> dict:
    """Delete a chat (the one deletable object). Leaves a tombstone so the delete syncs."""
    now = db.now()
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
        conn.execute(
            "UPDATE chats SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (now, now, chat_id),
        )
    _push(chat_id)
    return {"deleted": chat_id}


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
    """The passages an answer may read. A scoped chat reads its artifact, no search.

    Everything-scope applies the same relevance floor as /search (Q.5, Q.10).
    """
    conn = db.get_conn()
    try:
        if scope_kind == "artifact":
            if scope_id is None:
                return []
            return _scoped_passages(conn, [scope_id])

        from .index.store import get_store
        from .retrieve.candidates import _floor_verdict, judge_gray_zone

        store = get_store()
        found: dict[str, dict] = {}
        window = PASSAGES * 4
        chunk_legs = store.search_legs(store.CHUNKS, question, limit=window)
        dense_sims: dict[str, float] = {}
        lexical_chunks: set[str] = set()
        for hit in chunk_legs["dense"][:window]:
            cid = hit["chunk_id"]
            if hit["score"] > dense_sims.get(cid, 0.0):
                dense_sims[cid] = hit["score"]
        for leg in ("keyword", "trigram"):
            for hit in chunk_legs[leg][:window]:
                lexical_chunks.add(hit["chunk_id"])
        per_artifact: dict[str, int] = {}
        # Gray-zone chunks are collected, then judged in one batched call below.
        gray_chunks: list[str] = []
        gray_scores: dict[str, float] = {}
        gray_artifacts: dict[str, str] = {}
        for hit in chunk_legs["fused"]:
            aid = hit["artifact_id"]
            verdict = _floor_verdict(
                {
                    "dense_similarity": dense_sims.get(hit["chunk_id"], 0.0),
                    "had_lexical_hit": hit["chunk_id"] in lexical_chunks,
                }
            )
            if verdict == "drop":
                continue
            if verdict == "gray":
                gray_chunks.append(hit["chunk_id"])
                gray_scores[hit["chunk_id"]] = hit["score"]
                gray_artifacts[hit["chunk_id"]] = aid
                continue
            if per_artifact.get(aid, 0) >= CHUNKS_PER_ARTIFACT:
                continue
            found[hit["chunk_id"]] = {"score": hit["score"], "why": "passage"}
            per_artifact[aid] = per_artifact.get(aid, 0) + 1
            if len(found) >= PASSAGES:
                break

        if gray_chunks:
            gray_rows = conn.execute(
                "SELECT c.id, c.artifact_id, c.text, a.title, a.kind FROM chunks c"
                " JOIN artifacts a ON a.id = c.artifact_id"
                " WHERE c.id IN (SELECT value FROM json_each(?))",
                (json.dumps(gray_chunks),),
            ).fetchall()
            by_aid: dict[str, dict] = {}
            for r in gray_rows:
                by_aid.setdefault(
                    r["artifact_id"],
                    {
                        "title": r["title"],
                        "kind": r["kind"],
                        "snippet": " ".join(r["text"].split())[:400],
                    },
                )
            kept = judge_gray_zone(
                question,
                [{"artifact_id": aid, **info} for aid, info in by_aid.items()],
            )
            for cid in gray_chunks:
                aid = gray_artifacts[cid]
                if aid not in kept:
                    continue
                if per_artifact.get(aid, 0) >= CHUNKS_PER_ARTIFACT:
                    continue
                found[cid] = {"score": gray_scores[cid], "why": "passage"}
                per_artifact[aid] = per_artifact.get(aid, 0) + 1
                if len(found) >= PASSAGES:
                    break

        # Facet/entity hits face the same floor: keyword leg = lexical, dense leg = similarity.
        facet_entity_dense: dict[str, float] = {}
        facet_entity_lexical: set[str] = set()
        fe_legs = {
            name: store.search_legs(name, question, limit=4)
            for name in (store.FACETS, store.ENTITIES, store.SECTIONS)
        }
        # Query lifting (retrieve/lift.py): facet-style restatements of the question
        # search the facet index too. Their dense similarity counts; never lexical.
        from .retrieve.lift import lift

        lift_legs = [store.search_legs(store.FACETS, claim, limit=4) for claim in lift(question)]
        facet_hits = fe_legs[store.FACETS]["fused"] + [h for ll in lift_legs for h in ll["fused"]]
        for ll in lift_legs:
            for hit in ll["dense"][:window]:
                aid = hit["artifact_id"]
                if hit["score"] > facet_entity_dense.get(aid, 0.0):
                    facet_entity_dense[aid] = hit["score"]
        for legs in fe_legs.values():
            for hit in legs["dense"][:window]:
                aid = hit["artifact_id"]
                if hit["score"] > facet_entity_dense.get(aid, 0.0):
                    facet_entity_dense[aid] = hit["score"]
            for hit in legs["keyword"][:window]:
                facet_entity_lexical.add(hit["artifact_id"])

        def _pull_opening(aid: str, why: str, score: float) -> None:
            row = conn.execute(
                "SELECT id FROM chunks WHERE artifact_id = ? ORDER BY ordinal LIMIT 1",
                (aid,),
            ).fetchone()
            if row and row["id"] not in found:
                found[row["id"]] = {"score": score, "why": why}

        def _pull_section(aid: str, ordinal: int, why: str, score: float) -> None:
            n_sections = conn.execute(
                "SELECT COUNT(*) AS n FROM sections WHERE artifact_id = ?", (aid,)
            ).fetchone()["n"]
            n_chunks = conn.execute(
                "SELECT COUNT(*) AS n FROM chunks WHERE artifact_id = ?", (aid,)
            ).fetchone()["n"]
            if not n_chunks:
                return
            at = min(n_chunks - 1, int((ordinal - 0.5) / max(n_sections, 1) * n_chunks))
            row = conn.execute(
                "SELECT id FROM chunks WHERE artifact_id = ? ORDER BY ordinal LIMIT 1 OFFSET ?",
                (aid, at),
            ).fetchone()
            if row and row["id"] not in found:
                found[row["id"]] = {"score": score, "why": why}

        # A facet or entity hit pulls in its artifact's opening chunk. Stale hits are skipped.
        cache: dict = {}
        gray_facet_entity: dict[str, tuple[str, float, str]] = {}
        for hit in facet_hits:
            if hit_is_stale(conn, hit, cache):
                continue
            aid = hit["artifact_id"]
            why = f"facet L{hit.get('level')}"
            verdict = _floor_verdict(
                {
                    "dense_similarity": facet_entity_dense.get(aid, 0.0),
                    "had_lexical_hit": aid in facet_entity_lexical,
                }
            )
            if verdict == "drop":
                continue
            if verdict == "gray":
                stmt = conn.execute(
                    "SELECT statement FROM facets WHERE id = ?", (hit["facet_id"],)
                ).fetchone()
                gray_facet_entity.setdefault(
                    aid, (why, hit["score"], stmt["statement"] if stmt else "")
                )
                continue
            _pull_opening(aid, why, hit["score"])

        for hit in fe_legs[store.ENTITIES]["fused"]:
            if hit_is_stale(conn, hit, cache):
                continue
            aid = hit["artifact_id"]
            verdict = _floor_verdict(
                {
                    "dense_similarity": facet_entity_dense.get(aid, 0.0),
                    "had_lexical_hit": aid in facet_entity_lexical,
                }
            )
            if verdict == "drop":
                continue
            if verdict == "gray":
                gray_facet_entity.setdefault(aid, ("entity", hit["score"], hit.get("fact") or ""))
                continue
            _pull_opening(aid, "entity", hit["score"])

        # A section hit pulls the chunk from that part of the document (section i of n
        # sits around i/n of the way through), so the answer reads the page the summary
        # described rather than the opening.
        for hit in fe_legs[store.SECTIONS]["fused"]:
            if hit_is_stale(conn, hit, cache):
                continue
            aid = hit["artifact_id"]
            verdict = _floor_verdict(
                {
                    "dense_similarity": facet_entity_dense.get(aid, 0.0),
                    "had_lexical_hit": aid in facet_entity_lexical,
                }
            )
            if verdict == "drop":
                continue
            why = f"section {hit.get('ordinal')}"
            if verdict == "gray":
                row = conn.execute(
                    "SELECT summary FROM sections WHERE id = ?", (hit["section_id"],)
                ).fetchone()
                gray_facet_entity.setdefault(
                    aid, (why, hit["score"], row["summary"] if row else "")
                )
                continue
            _pull_section(aid, hit.get("ordinal") or 1, why, hit["score"])

        # The judge reads the matched facet statement / entity fact, not the opening chunk.
        if gray_facet_entity:
            faces = {
                r["id"]: (r["title"], r["kind"])
                for r in conn.execute(
                    "SELECT id, title, kind FROM artifacts"
                    " WHERE id IN (SELECT value FROM json_each(?))",
                    (json.dumps(list(gray_facet_entity)),),
                ).fetchall()
            }
            kept = judge_gray_zone(
                question,
                [
                    {
                        "artifact_id": aid,
                        "title": faces.get(aid, ("", ""))[0],
                        "kind": faces.get(aid, ("", ""))[1] or "artifact",
                        "snippet": " ".join(snippet.split())[:400],
                    }
                    for aid, (_why, _score, snippet) in gray_facet_entity.items()
                ],
            )
            for aid, (why, score, _snippet) in gray_facet_entity.items():
                if aid not in kept:
                    continue
                if why.startswith("section "):
                    _pull_section(aid, int(why.split()[1]), why, score)
                else:
                    _pull_opening(aid, why, score)

        if not found:
            return []

        rows = conn.execute(
            "SELECT c.id, c.artifact_id, c.text, a.title, a.kind FROM chunks c"
            " JOIN artifacts a ON a.id = c.artifact_id"
            " WHERE c.id IN (SELECT value FROM json_each(?))",
            (json.dumps(list(found)),),
        ).fetchall()

        out = [dict(r) | found[r["id"]] for r in rows]
        out.sort(key=lambda r: r["score"], reverse=True)
        return out[:PASSAGES]
    finally:
        conn.close()


def readiness() -> dict:
    """Whether there is anything to answer from, and which of the reasons if not."""
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
    """Why a scoped chat found nothing, when the scope itself is the reason (unfetched link)."""
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
                    "Fetch a preview, or ask the whole library instead"
                )
            if row["kind"] in ("pdf", "image", "file"):
                return (
                    f"no text has been extracted from this {row['kind']} yet, so there is "
                    "nothing in it to read. Ask the whole library instead"
                )
            return "this artifact has no text in it yet"
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

    # The header MUST carry the artifact id: the Answer validator rejects cited ids it
    # was not offered (CHATBUG.1).
    body = "\n\n".join(
        f"[{p.get('kind', 'artifact')}] (id: {p['artifact_id']}) {p['title']}\n{_clip(p['text'])}"
        for p in found
    )
    return get_provider().complete(
        system=CHAT_ANSWER,
        user=f"{history}Question: {question}\n\nPassages:\n\n{body}",
        response_model=Answer,
        context={"offered_artifact_ids": [p["artifact_id"] for p in found]},
    )


def _append(
    conn,
    chat_id: str,
    role: str,
    text: str,
    grounded: bool = False,
    kind: str = "answer",
    payload: dict | None = None,
    status: str = "done",
) -> str:
    """Write one message row at the next ordinal.

    `kind` is the skill, `payload` the JSON a turn re-renders from (the pivot spec),
    `status` pending/done/failed.
    """
    ordinal = conn.execute(
        "SELECT COALESCE(MAX(ordinal), -1) + 1 AS n FROM chat_messages WHERE chat_id = ?",
        (chat_id,),
    ).fetchone()["n"]
    message_id = str(uuid.uuid4())
    try:
        grounded_int = int(grounded)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"grounded must be an integer: {exc}") from None
    payload_json = json.dumps(payload) if payload is not None else None
    conn.execute(
        "INSERT INTO chat_messages"
        " (id, chat_id, ordinal, role, text, grounded, kind, payload, status, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            message_id,
            chat_id,
            ordinal,
            role,
            text,
            grounded_int,
            kind,
            payload_json,
            status,
            db.now(),
        ),
    )
    return message_id


def ask(question: str, scope_kind: str = "everything", scope_id: str | None = None) -> dict:
    """Create a chat and submit its first turn. Returns before the model runs."""
    question = question.strip()
    if not question:
        raise ValueError("say something")
    chat_id = create(scope_kind, scope_id)["chat"]["id"]
    _submit(chat_id, question)
    return get(chat_id)


def run_answer(chat_id: str, text: str) -> dict:
    """The `answer` skill: retrieve, ask, return the turn dict. Writes nothing.

    Citations outside the offered passages are dropped.
    """
    conn = db.get_conn()
    try:
        chat = conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
        if chat is None:
            raise KeyError(chat_id)
        history = _history(conn, chat_id)
    finally:
        conn.close()

    found = passages(text, chat["scope_kind"], chat["scope_id"])
    empty_reason = empty_scope_reason(chat["scope_kind"], chat["scope_id"]) if not found else None
    answer = _ask_model(text, history, found, empty_reason)

    by_artifact = {p["artifact_id"] for p in found}
    return {
        "role": "assistant",
        "text": answer.answer,
        "grounded": answer.grounded,
        "kind": "answer",
        "payload": None,
        "cited": [aid for aid in dict.fromkeys(answer.cited) if aid in by_artifact],
    }


def run_organize(chat_id: str, text: str) -> dict:
    """The `organize` skill: plan and run a pivot; the spec rides in `payload`.

    Any failure falls back to `run_answer` (Rule 1: never crash the turn).
    """
    try:
        spec = pivot.plan(text)
        result = pivot.run(spec)
    except Exception as exc:  # noqa: BLE001 - Rule 1: organize never crashes the turn
        log.warning("could not organize (%s: %s); answering instead", type(exc).__name__, exc)
        return run_answer(chat_id, text)

    total = sum(len(group["artifact_ids"]) for group in result["groups"])
    return {
        "role": "assistant",
        "text": (
            f"Organized {total} notes by {result['group_by']} "
            f"into {len(result['groups'])} groups."
        ),
        "grounded": all(group["grounded"] for group in result["groups"]),
        "kind": "organize",
        "payload": spec,
        "cited": [],
    }


def send(chat_id: str, text: str, force_skill: str | None = None) -> dict:
    """Submit one turn. Returns the chat ending in a pending turn the worker fills."""
    text = text.strip()
    if not text:
        raise ValueError("say something")

    conn = db.get_conn()
    try:
        chat = conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
    finally:
        conn.close()
    if chat is None:
        raise KeyError(chat_id)

    _submit(chat_id, text, force_skill)
    # The worker pushes again once the answer lands.
    _push(chat_id)
    return get(chat_id)


def _submit(chat_id: str, text: str, force_skill: str | None = None) -> None:
    """Write the user turn + a pending assistant turn in one transaction, then queue the job."""
    with db.transaction() as conn:
        _append(conn, chat_id, "user", text)
        message_id = _append(conn, chat_id, "assistant", "", kind="answer", status="pending")
        conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (db.now(), chat_id))
    from . import events

    events.emit(
        "ask.submitted",
        " ".join((text or "").split())[:80],
        data={"question": text, "chat_id": chat_id},
    )
    chats_worker.submit(chats_worker.Job(chat_id, message_id, text, force_skill))


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
    """Re-derive topics from the whole transcript. Topics that come back keep their ids."""
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

    # No grounded answer: nothing to extract (the model would invent failure topics).
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

    now = db.now()
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
