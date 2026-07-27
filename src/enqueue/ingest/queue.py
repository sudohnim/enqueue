"""The ingest queue.

Hard rule 7: capture returns before processing, always. Typing a note and saving it
must never wait on an embedding model loading from disk, and pasting a link must
never wait on anything at all. So the work that makes an artifact findable happens
behind the response.

One worker thread, not a pool. The in-process Qdrant holds a lock on its directory
and the embedding models are large enough that a second copy is not free; serialising
the work costs nothing at this scale and removes a whole class of bug.

The queue is in memory. If the engine dies with work outstanding, that work is lost
and the artifact is simply unindexed until the next full `enq index`. That is the
right trade for derived data: nothing the person wrote is ever at risk, only the
machine's copy of it.
"""

from __future__ import annotations

import logging
import queue
import threading

log = logging.getLogger(__name__)

_work: queue.Queue[str] = queue.Queue()
_worker: threading.Thread | None = None
_lock = threading.Lock()
_idle = threading.Event()
_idle.set()


def process(artifact_id: str) -> dict:
    """Extract, chunk, and index one artifact. Synchronous."""
    from .. import capture, db
    from ..index import qdrant
    from . import chunk as chunk_mod

    # A PDF has to be read before it can be chunked. Everything else already carries
    # its own text by the time it gets here.
    pages = capture.extract_text(artifact_id)

    with db.transaction() as conn:
        chunks = chunk_mod.chunk_artifact(conn, artifact_id)

    indexed = qdrant.index_artifact(artifact_id) if chunks else 0
    if not chunks:
        # An artifact can lose its text: a note emptied, a preview refetched and
        # failed. Its stale points have to go, or search keeps returning it.
        qdrant.drop_artifact(qdrant.CHUNKS, artifact_id)

    return {"artifact_id": artifact_id, "pages": pages, "chunks": chunks, "indexed": indexed}


def _run() -> None:
    while True:
        artifact_id = _work.get()
        _idle.clear()
        try:
            process(artifact_id)
        except Exception:  # noqa: BLE001 - one bad artifact must not stop the queue
            log.exception("ingest failed for %s", artifact_id)
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
        _worker = threading.Thread(target=_run, name="enqueue-ingest", daemon=True)
        _worker.start()


def submit(artifact_id: str) -> None:
    """Queue an artifact for chunking and indexing. Returns immediately."""
    _ensure_worker()
    _idle.clear()
    _work.put(artifact_id)


def submit_all() -> int:
    """Put every artifact back through extraction, chunking, and indexing.

    Needed whenever the pipeline learns something new. A PDF captured before text
    extraction existed has no text and never will until it is asked again, and there
    is no way for it to know that it is out of date.
    """
    from .. import db

    conn = db.get_conn()
    try:
        ids = [r["id"] for r in conn.execute("SELECT id FROM artifacts")]
    finally:
        conn.close()

    for artifact_id in ids:
        submit(artifact_id)
    return len(ids)


def wait_idle(timeout: float = 60.0) -> bool:
    """Block until the queue is drained. For tests and for the CLI, not for requests."""
    return _idle.wait(timeout)
