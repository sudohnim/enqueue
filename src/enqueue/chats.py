"""Chats: conversations with the library.

A turn is submitted, not computed: the answer worker (chats_worker) answers, then
titles and re-topics best effort. See AGENTS.md "Chat".
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from contextvars import copy_context

from . import chats_worker, config, db, pivot, privacy
from .prompts import CHAT_ANSWER, CHAT_REWRITE, CHAT_TITLE, CHAT_TOPICS
from .providers.base import get_provider
from .retrieve.candidates import hit_is_stale
from .schemas import Answer, ChatTitle, ChatTopics, Standalone

log = logging.getLogger(__name__)

# Passages an answer may read, and the words kept of each. Small for a model on this
# machine: a local 8B model given more summarizes instead. A hosted model reads far
# more, and a chunk is at most about 300 words, so it gets each one whole.
PASSAGES = 8
PASSAGE_WORDS = 220
REMOTE_PASSAGES = 20
REMOTE_PASSAGE_WORDS = 400
# Max chunks per artifact in a passage set, so one long note cannot crowd out the rest.
CHUNKS_PER_ARTIFACT = 2
# Turns of the conversation shown to the model that restates a follow-up.
REWRITE_TURNS = 6
# A follow-up this short cannot be searched for by itself.
SHORT_FOLLOW_UP_WORDS = 8


def _budget(provider) -> tuple[int, int]:
    """(passages, words of each) the answering model is given."""
    if privacy.is_remote(provider):
        return REMOTE_PASSAGES, REMOTE_PASSAGE_WORDS
    return PASSAGES, PASSAGE_WORDS


def _background(fn):
    """Start `fn` on a thread now; the returned `wait(seconds)` gives its result, or
    None when it raised or is not back in time (it then finishes unattended)."""
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except Exception:  # noqa: BLE001 - preparation is an enhancement, never a gate
            log.warning("answer preparation failed", exc_info=True)

    worker = threading.Thread(target=copy_context().run, args=(run,), daemon=True)
    worker.start()

    def wait(seconds: float):
        worker.join(seconds)
        return box.get("value")

    return wait


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


def _scoped_passages(conn, artifact_id: str, question: str, limit: int) -> list[dict]:
    """What an answer about one artifact reads.

    An artifact that fits is read whole, no search. A longer one (a PDF, a long
    article) used to be cut to its opening chunks, so nothing past the first pages
    could be answered. Now the answer gets the document in brief (`_overview`), its
    opening, and the passages that best match the question, in document order.
    """
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT c.id, c.artifact_id, c.text, a.title, a.kind FROM chunks c"
            " JOIN artifacts a ON a.id = c.artifact_id"
            " WHERE c.artifact_id = ? ORDER BY c.ordinal",
            (artifact_id,),
        )
    ]
    if len(rows) <= limit:
        return rows

    from .index.store import get_store

    overview = _overview(conn, rows[0])
    room = limit - len(overview)
    best = get_store().search_within(artifact_id, question, room)
    if not best:  # nothing indexed yet: the opening is the best there is
        return overview + rows[:room]
    chosen = set(([rows[0]["id"]] + [cid for cid in best if cid != rows[0]["id"]])[:room])
    return overview + [r for r in rows if r["id"] in chosen]


def _overview(conn, opening: dict) -> list[dict]:
    """A long artifact in brief, as one passage: its section summaries when it has
    them (ingest/source.py), else its summary lines. Empty when it has neither, or
    they were written from an older body or by another model."""
    aid = opening["artifact_id"]
    cache: dict = {}

    def current(rows) -> list:
        return [r for r in rows if not hit_is_stale(conn, {"artifact_id": aid, **dict(r)}, cache)]

    parts = current(
        conn.execute(
            "SELECT summary AS line, model_version, body_version FROM sections"
            " WHERE artifact_id = ? ORDER BY ordinal",
            (aid,),
        ).fetchall()
    )
    if parts:
        head = "The whole document in brief, part by part:"
        lines = [f"{n}. {r['line']}" for n, r in enumerate(parts, 1)]
    else:
        parts = current(
            conn.execute(
                "SELECT statement AS line, model_version, body_version, edited FROM facets"
                " WHERE artifact_id = ? ORDER BY level",
                (aid,),
            ).fetchall()
        )
        head = "What the whole document says, in brief:"
        lines = [f"- {r['line']}" for r in parts]
    if not parts:
        return []
    return [
        opening
        | {"id": f"overview:{aid}", "text": head + "\n" + "\n".join(lines), "why": "overview"}
    ]


def passages(question: str, scope_kind: str, scope_id: str | None) -> list[dict]:
    """The passages an answer may read. A scoped chat reads its artifact: whole when
    it fits, searched inside when it does not (`_scoped_passages`).

    Everything-scope applies the same relevance floor as /search (Q.5, Q.10). A
    two-sided question ("compare X and Y", retrieve/decompose.py) searches each side
    on its own and interleaves them, so both sides reach the answer; slots left over
    are filled from the whole question. When the chat model is remote, local-only
    artifacts are left out: their text never leaves the machine (privacy.py). A chat
    scoped to one local-only artifact is not answered: no model reads it.
    """
    if scope_kind == "artifact":
        if scope_id is None:
            return []
        limit, _ = _budget(get_provider(local_only=privacy.is_local_only(scope_id)))
        conn = db.get_conn()
        try:
            return _scoped_passages(conn, scope_id, question, limit)
        finally:
            conn.close()
    provider = get_provider()
    return privacy.shareable(_everything_passages(question, _budget(provider)[0]), provider)


def _chat_provider(chat_id: str):
    """The model for a chat: the local one when it is scoped to a local-only artifact."""
    conn = db.get_conn()
    try:
        chat = conn.execute(
            "SELECT scope_kind, scope_id FROM chats WHERE id = ?", (chat_id,)
        ).fetchone()
    finally:
        conn.close()
    private = chat is not None and chat["scope_kind"] == "artifact"
    return get_provider(local_only=private and privacy.is_local_only(chat["scope_id"]))


def _everything_passages(question: str, limit: int = PASSAGES) -> list[dict]:
    from .retrieve.decompose import parts

    sides = parts(question)
    if not sides:
        return _library_passages(question, limit)
    lists = [_library_passages(side, limit) for side in sides]
    lists.append(_library_passages(question, limit))
    out: list[dict] = []
    seen: set[str] = set()
    for rank in range(limit):
        for found in lists[:-1]:
            if rank < len(found) and found[rank]["id"] not in seen:
                out.append(found[rank])
                seen.add(found[rank]["id"])
    for p in lists[-1]:
        if p["id"] not in seen:
            out.append(p)
            seen.add(p["id"])
    return out[:limit]


def _library_passages(question: str, limit: int = PASSAGES) -> list[dict]:
    """Everything-scope retrieval for one question, best first."""
    from .retrieve.lift import lift

    # Query lifting (retrieve/lift.py) is a search-model call: it runs beside the
    # retrieval below and is waited for only so long (config.CHAT_PREP_WAIT_S).
    lifting = _background(lambda: lift(question))
    conn = db.get_conn()
    try:
        from .index.store import get_store
        from .retrieve.candidates import _cached_verdicts, _floor_verdict

        # The gray zone is not sent to a judge here. The answering model reads every
        # passage it is given and is told to refuse when none fits, so a judge call
        # before it was the same model ruling twice, on less text, at the cost of one
        # (often two) more round trips per answer. A verdict /search already cached
        # is free and still counts: a cached "no" drops the passage.
        def known(hits: list[dict]) -> set[str]:
            return _cached_verdicts(question, hits)[0]

        store = get_store()
        found: dict[str, dict] = {}
        window = limit * 4
        chunk_legs = store.search_legs(store.CHUNKS, question, limit=window)
        dense_sims: dict[str, float] = {}
        for hit in chunk_legs["dense"][:window]:
            cid = hit["chunk_id"]
            if hit["score"] > dense_sims.get(cid, 0.0):
                dense_sims[cid] = hit["score"]
        # Lexical proof is a keyword hit: a chunk holding every content word of the
        # question. A trigram (substring) hit is recall only, as in /search: counted as
        # proof, a question's filler words ("what", "the", "about") carried unrelated
        # passages past the floor and crowded out the ones that matched.
        lexical_chunks = {hit["chunk_id"] for hit in chunk_legs["keyword"][:window]}
        verdicts = {
            hit["chunk_id"]: _floor_verdict(
                {
                    "dense_similarity": dense_sims.get(hit["chunk_id"], 0.0),
                    "had_lexical_hit": hit["chunk_id"] in lexical_chunks,
                }
            )
            for hit in chunk_legs["fused"]
        }

        # Gray-zone chunks are kept unless a cached verdict says otherwise.
        kept_gray: set[str] = set()
        gray_chunks = [cid for cid, verdict in verdicts.items() if verdict == "gray"]
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
            kept_gray = known([{"artifact_id": aid, **info} for aid, info in by_aid.items()])

        # One pass in ranked order, so a judged passage takes the place its rank earned
        # rather than whatever is left after the sure ones.
        per_artifact: dict[str, int] = {}
        for hit in chunk_legs["fused"]:
            aid = hit["artifact_id"]
            verdict = verdicts[hit["chunk_id"]]
            if verdict == "drop" or (verdict == "gray" and aid not in kept_gray):
                continue
            if per_artifact.get(aid, 0) >= CHUNKS_PER_ARTIFACT:
                continue
            found[hit["chunk_id"]] = {"score": hit["score"], "why": "passage"}
            per_artifact[aid] = per_artifact.get(aid, 0) + 1
            if len(found) >= limit:
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
        claims = lifting(config.CHAT_PREP_WAIT_S) or []
        lift_legs = [store.search_legs(store.FACETS, claim, limit=4) for claim in claims]
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

        if gray_facet_entity:
            faces = {
                r["id"]: (r["title"], r["kind"])
                for r in conn.execute(
                    "SELECT id, title, kind FROM artifacts"
                    " WHERE id IN (SELECT value FROM json_each(?))",
                    (json.dumps(list(gray_facet_entity)),),
                ).fetchall()
            }
            kept = known(
                [
                    {
                        "artifact_id": aid,
                        "title": faces.get(aid, ("", ""))[0],
                        "kind": faces.get(aid, ("", ""))[1] or "artifact",
                        "snippet": " ".join(snippet.split())[:400],
                    }
                    for aid, (_why, _score, snippet) in gray_facet_entity.items()
                ]
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
        return out[:limit]
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
    question: str,
    history: str,
    found: list[dict],
    empty_reason: str | None = None,
    provider=None,
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
    provider = provider or get_provider()
    _, words = _budget(provider)
    body = "\n\n".join(
        f"[{p.get('kind', 'artifact')}] (id: {p['artifact_id']}) {p['title']}\n"
        f"{_clip(p['text'], words)}"
        for p in found
    )
    return provider.complete(
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

    # Retrieval runs on the question as it stands alone; the model still answers the
    # message as typed, with the conversation above it.
    asked = _standalone(chat, text)
    found = passages(asked, chat["scope_kind"], chat["scope_id"])
    empty_reason = empty_scope_reason(chat["scope_kind"], chat["scope_id"]) if not found else None
    answer = _ask_model(text, history, found, empty_reason, provider=_chat_provider(chat_id))

    by_artifact = {p["artifact_id"] for p in found}
    return {
        "role": "assistant",
        "text": answer.answer,
        "grounded": answer.grounded,
        "kind": "answer",
        "payload": None,
        "cited": [aid for aid in dict.fromkeys(answer.cited) if aid in by_artifact],
    }


def _standalone(chat, text: str) -> str:
    """The question to search for: `text`, or for a follow-up the same question
    restated so it stands without the conversation.

    "What about the second one?" used to be searched for as those words; the
    conversation reached the answering model but never the search. On a follow-up the
    search model restates the message from the last few turns, in the one call that
    also lifts it into claims (cached for retrieve/lift.py), so a follow-up costs no
    more model calls than a first question. If the model is not back in
    config.CHAT_PREP_WAIT_S, a short follow-up is searched together with the question
    before it, and a long one as typed.
    """
    conn = db.get_conn()
    try:
        prior = conn.execute(
            "SELECT role, text FROM chat_messages WHERE chat_id = ? AND status = 'done'"
            " ORDER BY ordinal DESC LIMIT ?",
            (chat["id"], REWRITE_TURNS + 1),
        ).fetchall()[
            1:
        ]  # the newest done row is this message
    finally:
        conn.close()
    prior = [r for r in reversed(prior) if r["text"].strip()]
    asked_before = [r["text"] for r in prior if r["role"] == "user"]
    if not asked_before:
        return text

    private = chat["scope_kind"] == "artifact" and privacy.is_local_only(chat["scope_id"])
    transcript = "\n".join(f"{r['role']}: {' '.join(r['text'].split())[:400]}" for r in prior)

    def restate() -> str:
        from .retrieve import lift

        provider = get_provider(local_only=True) if private else get_provider(role="search")
        out = provider.complete(
            system=CHAT_REWRITE,
            user=f"Conversation:\n{transcript}\n\nLatest message: {text}",
            response_model=Standalone,
        )
        question = " ".join(out.question.split())
        claims = lift._clean(out.claims)
        if claims:
            lift.store(question, provider.model, claims)
        return question

    restated = _background(restate)(config.CHAT_PREP_WAIT_S)
    if restated:
        return restated
    if len(text.split()) < SHORT_FOLLOW_UP_WORDS:
        return f"{asked_before[-1]} {text}"
    return text


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
        named = _chat_provider(chat_id).complete(
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
        found = _chat_provider(chat_id).complete(
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
