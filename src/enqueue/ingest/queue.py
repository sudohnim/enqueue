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

# How many pending queue items each artifact has (I5.1). A burst of saves to one
# note enqueues that id several times; the worker processes them in order, and
# the facet/entity step is skipped whenever a newer item for the same id is still
# queued, so the last edit in the burst regenerates the derived data once instead
# of every keystroke-save paying a model call. The count is the number of queued
# items, decremented as each is dequeued; `_pending` is what the derived steps
# read at the moment they are about to spend a model call.
_queued: dict[str, int] = {}
_queued_lock = threading.Lock()


def _queue(artifact_id: str) -> None:
    """Remember one pending queue item. Called by `submit`, under the lock."""
    with _queued_lock:
        _queued[artifact_id] = _queued.get(artifact_id, 0) + 1


def _dequeue(artifact_id: str) -> None:
    """Forget one pending queue item. Called by the worker when it picks one up."""
    with _queued_lock:
        remaining = _queued.get(artifact_id, 0) - 1
        if remaining > 0:
            _queued[artifact_id] = remaining
        else:
            _queued.pop(artifact_id, None)


def _pending(artifact_id: str) -> int:
    """How many newer queue items for this artifact are still unprocessed."""
    with _queued_lock:
        return _queued.get(artifact_id, 0)


def process(artifact_id: str) -> dict:
    """Resolve, extract, chunk, and index one artifact. Synchronous."""
    from .. import capture, db, preview
    from ..index.store import get_store
    from . import chunk as chunk_mod

    # A saved link is only an address until the publisher is asked what it is. Doing
    # that here rather than at capture time is what keeps saving instant: the request
    # happens behind the response, on this thread, where nobody is waiting on it.
    #
    # `local_only` is excluded on purpose. Marking something local only is a promise
    # that it does not cause network traffic, and an automatic fetch would break that
    # promise without anyone asking for it.
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT kind, local_only FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
    finally:
        conn.close()

    if (
        row is not None
        and row["kind"] == "link"
        and not row["local_only"]
        and preview.auto_enabled()
        and preview.needs_fetch(artifact_id)
    ):
        preview.fetch_quietly(artifact_id)

    # A PDF has to be read before it can be chunked. Everything else already carries
    # its own text by the time it gets here.
    pages = capture.extract_text(artifact_id)

    with db.transaction() as conn:
        chunks = chunk_mod.chunk_artifact(conn, artifact_id)

    store = get_store()
    indexed = store.index_artifact(artifact_id) if chunks else 0
    if not chunks:
        # An artifact can lose its text: a note emptied, a preview refetched and
        # failed. Its stale points have to go, or search keeps returning it.
        store.drop_artifact(store.CHUNKS, artifact_id)
        store.drop_artifact(store.FACETS, artifact_id)

    # Facets are the conceptual layer that lets a question reach an artifact whose
    # own words never mention it - "notes on a president" reaching a Roosevelt
    # biography that never says "president". Generating them here, behind the
    # response, is what keeps them from being a batch nobody remembers to run
    # (an unfaceted library answers only literal matches). Best effort: a facet
    # failure never fails the capture, and the artifact is still findable by text.
    facets_made = _facet_artifact(artifact_id) if chunks else 0

    # Entities are the named things in the body, each enriched with a one-line
    # world-knowledge fact. They close the same gap from the other side: a
    # question phrased in the world's vocabulary ("presidents") reaches a
    # biography that never says it. Same discipline as facets - best effort,
    # one bad entity never fails the artifact, and the artifact stays findable
    # by its own words regardless.
    entities_made = _entities_artifact(artifact_id) if chunks else 0

    return {
        "artifact_id": artifact_id,
        "pages": pages,
        "chunks": chunks,
        "indexed": indexed,
        "facets": facets_made,
        "entities": entities_made,
    }


def _facet_artifact(artifact_id: str) -> int:
    """Generate one artifact's facets and index them. Best effort, never raises.

    A model call sits behind this, so it runs only on the ingest worker, never on
    the capture path. An artifact the facet gate has excluded is skipped, and a
    model failure is logged and swallowed - the capture already succeeded.
    """
    if _pending(artifact_id) > 0:
        # A newer edit for the same artifact is still queued (I5.1): regenerating
        # now would be thrown away when that edit re-facets against its newer body.
        # Skip, and let the queued edit do it once, so a burst of saves costs one
        # facet regen, not one per keystroke.
        return 0
    from .. import db
    from ..index.store import get_store
    from . import facets as facets_mod

    conn = db.get_conn()
    try:
        gated = conn.execute(
            "SELECT 1 FROM facet_skips WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        if gated:
            return 0
        count, error = facets_mod.generate_for_artifact(conn, artifact_id)
        conn.commit()
    except Exception:  # noqa: BLE001 - facets are derived; a failure never blocks capture
        log.exception("facet generation failed for %s", artifact_id)
        return 0
    finally:
        conn.close()

    if error:
        log.warning("facet generation for %s: %s", artifact_id, error)
        return 0
    if count:
        get_store().index_facets_artifact(artifact_id)
    return count


def _entities_artifact(artifact_id: str) -> int:
    """Extract and enrich one artifact's entities, then index them. Best effort.

    Mirrors `_facet_artifact`: a model call sits behind this, so it runs only on
    the ingest worker, never on the capture path. An excluded artifact is
    skipped, and a failure is logged and swallowed - the capture already
    succeeded. One bad entity never fails the artifact; the per-entity quality
    gate in `entities.generate_for_artifact` drops just that line.
    """
    if _pending(artifact_id) > 0:
        # Same coalescing as the facet step (I5.1): a newer edit is queued, so the
        # extraction and per-entity enrichment would be redone for that newer body.
        return 0
    from .. import db
    from ..index.store import get_store
    from . import entities as entities_mod

    conn = db.get_conn()
    try:
        gated = conn.execute(
            "SELECT 1 FROM facet_skips WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        if gated:
            return 0
        count, error = entities_mod.generate_for_artifact(conn, artifact_id)
        conn.commit()
    except Exception:  # noqa: BLE001 - entities are derived; a failure never blocks capture
        log.exception("entity generation failed for %s", artifact_id)
        return 0
    finally:
        conn.close()

    if error:
        log.warning("entity generation for %s: %s", artifact_id, error)
        return 0
    if count:
        get_store().index_entities_artifact(artifact_id)
    return count


def _run() -> None:
    while True:
        artifact_id = _work.get()
        _idle.clear()
        _dequeue(artifact_id)
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
    _queue(artifact_id)
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
        ids = [r["id"] for r in conn.execute("SELECT id FROM artifacts WHERE deleted_at IS NULL")]
    finally:
        conn.close()

    for artifact_id in ids:
        submit(artifact_id)
    return len(ids)


def wait_idle(timeout: float = 60.0) -> bool:
    """Block until the queue is drained. For tests and for the CLI, not for requests."""
    return _idle.wait(timeout)
