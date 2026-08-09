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
import queue
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

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


_work: queue.Queue[Job] = queue.Queue()
_worker: threading.Thread | None = None
_lock = threading.Lock()
_idle = threading.Event()
_idle.set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute(job: Job) -> None:
    """Compute one answer and write it into its pending turn. Synchronous.

    This is the worker thread's core, factored out so tests can call it directly:
    route the request to a skill, run it exactly as `send` used to, then in one
    transaction move the pending message to `done` with the real turn and its
    citations. On any failure the message resolves to `failed` with a short
    human sentence, and no citations. A failure never raises out of here - one
    bad job must not stop the worker.
    """
    from . import assistant, chats, db
    from .providers.base import ProviderError

    try:
        skill_name = (
            job.force_skill if job.force_skill in assistant.REGISTRY else assistant.route(job.text)
        )
        msg = assistant.REGISTRY[skill_name].run(job.chat_id, job.text)

        with db.transaction() as conn:
            _finish_pending(conn, job.message_id, msg)
            conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (_now(), job.chat_id))

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
    except Exception as exc:  # noqa: BLE001 - one bad job must not stop the worker
        log.exception("answer failed for message %s: %s", job.message_id, exc)
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


def _run() -> None:
    while True:
        job = _work.get()
        _idle.clear()
        try:
            compute(job)
        except Exception:  # noqa: BLE001 - one bad job must not stop the worker
            log.exception("answer failed for %s", job)
        finally:
            _work.task_done()
            if _work.empty():
                _idle.set()


def _ensure_worker() -> None:
    global _worker
    if _worker and _worker.is_alive():
        return
    with _lock:
        if _worker and _worker.is_alive():
            return
        _worker = threading.Thread(target=_run, name="enqueue-answers", daemon=True)
        _worker.start()


def submit(job: Job) -> None:
    """Queue an answer for computation. Returns immediately."""
    _ensure_worker()
    _idle.clear()
    _work.put(job)


def wait_idle(timeout: float = 60.0) -> bool:
    """Block until the queue is drained. For tests and the CLI, not for requests."""
    return _idle.wait(timeout)


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
