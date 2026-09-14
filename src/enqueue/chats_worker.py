"""The answer worker: compute submitted answers into their pending turns.

Hard rule, mirrored from the ingest queue: a submitted question returns before
the model runs, always. Asking must never wait on the local model grinding for
twenty seconds with a browser holding the connection open - the shape that made
an answer die the moment the person navigated away. So submitting writes a
pending turn and hands the work to this worker; the answer is computed here,
off the request thread, and written into the stored message, which is the only
place an answer lives (Rule 1: the work outlives the page).

One worker thread, not a pool, for the same reason the ingest queue is one: the
single local model serialises the work anyway, and concurrency would only add a
class of bug. The queue is in memory. If the engine dies with work outstanding,
that work is orphaned by definition - no worker will ever finish it - so startup
sweeps every row still pending to `failed` (`sweep_orphaned_pending`). Rule 2: a
pending turn always resolves, to done or to failed with a reason a person can
read; it never hangs, and it never silently vanishes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .worker import Worker

log = logging.getLogger(__name__)

# The human sentence a turn that failed mid-compute resolves to. Short and plain:
# the transcript shows it as the turn's text, with the question still above it.
FAILED_TEXT = "That answer could not be completed."
# Startup sweep text: the worker that owned this turn is gone, and the reason has
# to say so rather than pretending the answer failed.
INTERRUPTED_TEXT = "That answer was interrupted. Ask again."


@dataclass
class Job:
    """One submitted question, with the pending assistant turn to fill in."""

    chat_id: str
    message_id: str
    text: str
    force_skill: str | None = None


def _one_line(text: str, cap: int = 80) -> str:
    """A question squeezed to a single row-width line for the event summary."""
    s = " ".join((text or "").split())
    return s if len(s) <= cap else s[: cap - 1] + "…"


def _emit_answered(events, job: Job, skill_name: str, msg: dict, route_ms, answer_ms, total_ms):
    """Log a completed answer with the whole exchange and where the time went."""
    cited = list(msg.get("cited") or [])
    grounded = bool(msg.get("grounded"))
    # Resolve cited artifact ids to titles so the opened event reads without a lookup.
    titles = _titles_for(cited)
    secs = total_ms / 1000
    detail = f"{_one_line(job.text)}  →  {'grounded' if grounded else 'no match'}, {secs:.1f}s"
    events.emit(
        "ask.answered",
        detail,
        data={
            "question": job.text,
            "answer": msg.get("text", ""),
            "skill": skill_name,
            "model": _answer_model(),
            "grounded": grounded,
            "cited": [{"id": a, "title": titles.get(a, "")} for a in cited],
            "timing_ms": {"route": route_ms, "answer": answer_ms, "total": total_ms},
        },
        duration_ms=total_ms,
    )


def _answer_model() -> str:
    """The model that answered, for the event record. Best effort, never raises."""
    try:
        from .providers.base import get_provider

        return get_provider().model or ""
    except Exception:  # noqa: BLE001
        return ""


def _titles_for(artifact_ids: list[str]) -> dict[str, str]:
    """Map artifact ids to titles for the event record. Best effort, never raises."""
    if not artifact_ids:
        return {}
    try:
        from . import db

        conn = db.get_conn()
        try:
            marks = ",".join("?" for _ in artifact_ids)
            rows = conn.execute(
                f"SELECT id, title FROM artifacts WHERE id IN ({marks})", artifact_ids
            ).fetchall()
            return {r["id"]: (r["title"] or "") for r in rows}
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return {}


def _commit_answer(db, job: Job, msg: dict) -> None:
    """Write the finished turn, retrying a transient lock. Raises on a real failure
    (a deleted chat's FK violation, or a lock that never clears) so the caller can
    resolve the turn to `failed` with the reason."""
    import sqlite3
    import time

    attempts = 5
    for i in range(attempts):
        try:
            with db.transaction() as conn:
                _finish_pending(conn, job.message_id, msg)
                conn.execute(
                    "UPDATE chats SET updated_at = ? WHERE id = ?", (db.now(), job.chat_id)
                )
            return
        except sqlite3.OperationalError as exc:
            # "database is locked" is the retryable one; anything else is a real error.
            if "locked" not in str(exc).lower() or i == attempts - 1:
                raise
            time.sleep(0.2 * (i + 1))


def compute(job: Job) -> None:
    """Compute one answer and write it into its pending turn. Synchronous.

    This is the worker thread's core, factored out so tests can call it directly:
    route the request to a skill, run it exactly as `send` used to, then in one
    transaction move the pending message to `done` with the real turn and its
    citations. On any failure the message resolves to `failed` with a short
    human sentence, and no citations. A failure never raises out of here - one
    bad job must not stop the worker.
    """
    import time

    from . import assistant, chats, db, events
    from .providers.base import ProviderError

    t0 = time.monotonic()
    try:
        t = time.monotonic()
        skill_name = (
            job.force_skill if job.force_skill in assistant.REGISTRY else assistant.route(job.text)
        )
        route_ms = int((time.monotonic() - t) * 1000)

        t = time.monotonic()
        msg = assistant.REGISTRY[skill_name].run(job.chat_id, job.text)
        answer_ms = int((time.monotonic() - t) * 1000)

        # Commit the finished turn, retrying a transient "database is locked" a few times
        # so a busy moment (a sync applying a batch) does not throw away a real answer the
        # model already produced. A genuine defect still surfaces after the retries.
        _commit_answer(db, job, msg)

        # The answer has landed. Record what happened so the Events tab can show the
        # whole exchange - the question, the answer, whether it was grounded, which
        # artifacts it cited, and where the seconds went (routing vs answering).
        total_ms = int((time.monotonic() - t0) * 1000)
        _emit_answered(events, job, skill_name, msg, route_ms, answer_ms, total_ms)

        # Naming and retopic are conveniences, best effort as today: a bad name or
        # a failed topic derivation must not undo a completed answer. They run only
        # after a successful `done`, on the first exchange for the title. I8.2:
        # their failure is caught HERE, not by the outer failure handler, so it can
        # never reach the message-mutating `failed` path (a done answer stays done).
        # Compute keeps its never-raises contract; `_run` need not log a misleading
        # "answer failed" for a turn that actually completed.
        try:
            if _first_exchange(job.chat_id, job.message_id):
                chats._name(job.chat_id, job.text, msg["text"])
            chats._retopic(job.chat_id)
        except Exception:  # noqa: BLE001 - naming is best effort; the answer already landed
            log.exception("naming or topic derivation failed for chat %s", job.chat_id)

        # The answer (and its title/topics) has landed: push the whole conversation so
        # the other device sees the completed turn, not just the pending one send() sent.
        chats._push(job.chat_id)
    except Exception as exc:  # noqa: BLE001 - one bad job must not stop the worker
        log.exception("answer failed for message %s: %s", job.message_id, exc)
        events.emit(
            "ask.failed",
            _one_line(job.text),
            data={
                "question": job.text,
                "error_type": type(exc).__name__,
                "error": str(exc)[:2000],
            },
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        # The cause is the actionable part (a rejected key, a dead endpoint), so it
        # is stored beside the turn (CR.2) and the chat view renders it with a path
        # to the fix. Only a ProviderError carries a sentence worth showing: it is
        # already human - "the endpoint at ... rejected the API key..." - while a
        # genuine bug must not leak its exception text into the interface.
        cause = str(exc)[:300] if isinstance(exc, ProviderError) else None
        with db.transaction() as conn:
            # I8.1: guarded so this can only transition a still-pending turn. If the
            # answer already committed `done` and a best-effort name/topic write
            # raised after that, this must not clobber the finished answer.
            conn.execute(
                "UPDATE chat_messages SET status = 'failed', text = ?, error = ?"
                " WHERE id = ? AND status = 'pending'",
                (FAILED_TEXT, cause, job.message_id),
            )


def _finish_pending(conn, message_id: str, msg: dict) -> None:
    """Move a pending assistant turn to `done`, with its citations, in one write."""
    try:
        grounded_int = int(msg["grounded"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"grounded must be an integer: {exc}") from None
    conn.execute(
        "UPDATE chat_messages SET status = 'done', text = ?, grounded = ?, kind = ?,"
        " payload = ? WHERE id = ?",
        (msg["text"], grounded_int, msg["kind"], json_dumps(msg["payload"]), message_id),
    )
    for rank, artifact_id in enumerate(msg["cited"]):
        conn.execute(
            "INSERT OR IGNORE INTO chat_citations (message_id, artifact_id, rank)"
            " VALUES (?,?,?)",
            (message_id, artifact_id, rank),
        )


def _first_exchange(chat_id: str, message_id: str) -> bool:
    """Whether this turn is the chat's first exchange: no assistant turn before it.

    Naming happens once, from the first exchange, exactly as it used to in `send`.
    The user turn already exists by the time the worker runs, so "no earlier
    assistant turn" is the right test - a chat answered twice names once.
    """
    from . import db

    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM chat_messages WHERE chat_id = ? AND id != ?"
            " AND role = 'assistant'",
            (chat_id, message_id),
        ).fetchone()
        return row["n"] == 0
    finally:
        conn.close()


def json_dumps(payload: dict | None) -> str | None:
    """The payload column: JSON text or NULL, matching chats._append."""
    import json

    return json.dumps(payload) if payload is not None else None


_worker = Worker("answers", compute)


def submit(job: Job) -> None:
    """Queue an answer for computation. Returns immediately."""
    _worker.submit(job)


def wait_idle(timeout: float = 60.0) -> bool:
    """Block until the queue is drained. For tests and the CLI, not for requests."""
    return _worker.wait_idle(timeout)


def sweep_orphaned_pending() -> int:
    """On startup: every row still pending is orphaned, because the in-memory
    queue did not survive the restart and no worker will ever finish it.

    Rule 2: a pending turn always resolves. The sweep is what bounds it - an
    answer interrupted by an engine restart lands as `failed` with a reason a
    person can read and retry, never as a forever-spinner.
    """
    from . import db

    with db.transaction() as conn:
        cur = conn.execute(
            "UPDATE chat_messages SET status = 'failed', text = ?, error = ?"
            " WHERE status = 'pending'",
            (INTERRUPTED_TEXT, "The app restarted while this answer was running."),
        )
        return cur.rowcount
