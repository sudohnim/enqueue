"""The ingest queue.

Hard rule 7: capture returns before processing, always. Typing a note and saving it
must never wait on an embedding model loading from disk, and pasting a link must
never wait on anything at all. So the work that makes an artifact findable happens
behind the response.

One worker thread, not a pool. The index lives inside the SQLite file, so there is
no directory lock to serialise on, and the embedding models are large enough that a
second copy is not free; serialising the work costs nothing at this scale and
removes a whole class of bug.

The queue is in memory. If the engine dies with work outstanding, that work is lost
and the artifact is simply unindexed until the next full `enq index`. That is the
right trade for derived data: nothing the person wrote is ever at risk, only the
machine's copy of it.
"""

from __future__ import annotations

import logging
import threading

from ..worker import Worker

log = logging.getLogger(__name__)

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

    # An image is bytes with no text until a vision model reads it (K.11). The
    # description becomes the artifact body, so the rest of the pipeline - chunk,
    # facet, entity, search - treats it like any other text. Best effort like
    # facets: no vision model on the backend, and the image simply stays
    # unsearchable; the capture itself already succeeded.
    described = _describe_image_if_needed(artifact_id)

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
        "described": described,
        "chunks": chunks,
        "indexed": indexed,
        "facets": facets_made,
        "entities": entities_made,
    }


def _describe_image_if_needed(artifact_id: str) -> str:
    """Give an image a searchable description (K.11). Best effort, never raises.

    A captured image is bytes with no text: it cannot be chunked, faceted, or
    searched, so it is invisible to everything except a filename match. This
    reads it with the vision model and stores the description - plus any OCR
    text, when tesseract is installed - as the artifact body. The image then
    flows through the pipeline exactly like a note. A failure (no vision model
    on the backend, a bad file) is logged and swallowed: the capture already
    succeeded, and `enq index --images` re-runs this for every image later.
    """
    from .. import capture, db
    from ..providers.base import get_vision_provider

    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT kind, body, local_only FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None or row["kind"] != "image":
        return ""
    if (row["body"] or "").strip():
        # Already described. A re-run of the pipeline (enq reprocess) must not
        # pay a vision call to describe the same image twice.
        return ""

    found = capture.blob_path(artifact_id)
    if found is None:
        return ""
    path, mime, _ = found
    try:
        text = get_vision_provider(local_only=bool(row["local_only"])).describe_image(
            path.read_bytes(), mime
        )
    except Exception:  # noqa: BLE001 - derived text; never fails the capture
        log.warning("image describe failed for %s", artifact_id)
        # The failure used to be silent: the artifact stayed 'text_only' and
        # nothing anywhere surfaced the images that were invisible to search.
        # 'failed' marks it so the doctor report and the wall can say so.
        with db.transaction() as conn:
            conn.execute("UPDATE artifacts SET status = 'failed' WHERE id = ?", (artifact_id,))
        return ""

    ocr = _ocr_text(path)
    body = text if not ocr else f"{text}\n\n{ocr}"
    with db.transaction() as conn:
        conn.execute(
            "UPDATE artifacts SET body = ?, status = 'ok' WHERE id = ?",
            (body, artifact_id),
        )
    return body


def _ocr_text(path) -> str:
    """OCR text via tesseract when it is installed; empty string otherwise.

    The vision description already asks for visible text word for word, so OCR
    is a bonus for exact-word retrieval, never a requirement. Tesseract keys
    file format detection off the file extension, so the blob is copied to a
    temp file with the right one before it is asked.
    """
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("tesseract"):
        return ""
    suffix = path.suffix or ".png"
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            tmp.write(path.read_bytes())
            tmp.flush()
            out = subprocess.run(
                ["tesseract", tmp.name, "stdout"],
                capture_output=True,
                text=True,
                timeout=60,
            )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (out.stdout or "").strip()


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


_ingest = Worker("ingest", process, pre=_dequeue)


def submit(artifact_id: str) -> None:
    """Queue an artifact for chunking and indexing. Returns immediately."""
    # I5.1 bookkeeping happens before the put: the counter must be incremented
    # before the worker could possibly dequeue the item.
    _queue(artifact_id)
    _ingest.submit(artifact_id)


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


def submit_images() -> int:
    """Re-queue every image for the vision describe step (K.11).

    The one-line catch-up for images captured before the vision step existed: a
    `kind='image'` artifact with no body never had a description, and nothing
    else will ever give it one. Re-running the pipeline describes it (or skips
    it if a vision model still is not available) and then chunks, facets, and
    indexes it like any other artifact.
    """
    from .. import db

    conn = db.get_conn()
    try:
        ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM artifacts WHERE kind = 'image' AND deleted_at IS NULL"
            )
        ]
    finally:
        conn.close()

    for artifact_id in ids:
        submit(artifact_id)
    return len(ids)


def wait_idle(timeout: float = 60.0) -> bool:
    """Block until the queue is drained. For tests and for the CLI, not for requests."""
    return _ingest.wait_idle(timeout)
