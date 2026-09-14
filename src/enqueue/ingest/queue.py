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

import contextlib
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from ..worker import Worker

log = logging.getLogger(__name__)

# Facet (summary) retry backoff: exponential, doubling from 30s and capped at 24h. A
# transient model failure (rate limit, 500) reschedules further out each time, so a
# summary is never lost to a temporary limit - it just arrives late, and a persistent
# outage settles at one attempt a day rather than hammering the model.
_FACET_RETRY_BASE = 30  # seconds; delay before the first retry
_FACET_RETRY_CAP = 24 * 60 * 60  # 24h ceiling
_facet_sweeper_started = False
_facet_sweeper_lock = threading.Lock()


def _record_facet_retry(conn, artifact_id: str, error: str) -> None:
    """Owe this artifact a summary, scheduling the next attempt with backoff."""
    row = conn.execute(
        "SELECT attempts FROM facet_retry WHERE artifact_id = ?", (artifact_id,)
    ).fetchone()
    attempts = (row["attempts"] if row else 0) + 1
    # Exponential: 30s, 60s, 120s, ... doubling, capped at 24h. The exponent is
    # clamped so a long-owed summary computes a bounded power, not a giant one.
    delay = min(_FACET_RETRY_BASE * (2 ** min(attempts - 1, 40)), _FACET_RETRY_CAP)
    next_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
    conn.execute(
        "INSERT INTO facet_retry (artifact_id, attempts, next_at, last_error) VALUES (?,?,?,?)"
        " ON CONFLICT(artifact_id) DO UPDATE SET"
        " attempts=excluded.attempts, next_at=excluded.next_at, last_error=excluded.last_error",
        (artifact_id, attempts, next_at, (error or "")[:300]),
    )


def _clear_facet_retry(conn, artifact_id: str) -> None:
    conn.execute("DELETE FROM facet_retry WHERE artifact_id = ?", (artifact_id,))


def _facet_retry_sweep() -> None:
    """Re-submit artifacts whose summary retry is due. Runs forever on a daemon
    thread; each due artifact goes back through the ingest worker, which regenerates
    the facets and clears (or reschedules) the retry row."""
    from .. import db

    while True:
        time.sleep(30)
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn = db.get_conn()
            try:
                due = [
                    r["artifact_id"]
                    for r in conn.execute(
                        "SELECT artifact_id FROM facet_retry WHERE next_at <= ? LIMIT 20", (now,)
                    )
                ]
            finally:
                conn.close()
            for aid in due:
                submit(aid)
        except Exception:  # noqa: BLE001 - a sweep failure must never kill the thread
            log.exception("facet retry sweep failed")


def start_facet_retry_sweeper() -> None:
    """Start the background summary-retry sweeper once (idempotent)."""
    global _facet_sweeper_started
    with _facet_sweeper_lock:
        if _facet_sweeper_started:
            return
        _facet_sweeper_started = True
    threading.Thread(target=_facet_retry_sweep, name="facet-retry", daemon=True).start()


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

    # An explicit "Try again" forces the refetch (bypassing the auto + needs_fetch
    # gates); otherwise the automatic path only fetches a link that has never been
    # asked, and never re-hammers one that already refused.
    forced = preview.take_forced(artifact_id)
    if (
        row is not None
        and row["kind"] == "link"
        and not row["local_only"]
        and (forced or (preview.auto_enabled() and preview.needs_fetch(artifact_id)))
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

    # An ingest that produced nothing (an artifact with no extractable text re-applied
    # by a sync) is not activity worth a row - logging every one buries the questions
    # and captures a person actually cares about. Only record an ingest that did work.
    if not (chunks or facets_made or entities_made):
        return {
            "artifact_id": artifact_id,
            "pages": pages,
            "described": described,
            "chunks": chunks,
            "indexed": indexed,
            "facets": facets_made,
            "entities": entities_made,
        }

    try:
        from .. import db, events

        # Name the artifact in the row (a bare hash means nothing to a person) and carry
        # the useful counts + its id in the record, so the Activity view can open it.
        conn = db.get_conn()
        try:
            row = conn.execute(
                "SELECT title, kind FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
        finally:
            conn.close()
        title = (row["title"] if row else "") or "(untitled)"
        kind = row["kind"] if row else ""
        events.emit(
            "ingest",
            f"{title[:60]}: {chunks} chunks, {facets_made} facets",
            data={
                "artifact_id": artifact_id,
                "title": title,
                "kind": kind,
                "pages": pages,
                "chunks": chunks,
                "indexed": indexed,
                "facets": facets_made,
                "entities": entities_made,
            },
        )
    except Exception:  # noqa: BLE001
        pass

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
    error = None
    count = 0
    try:
        gated = conn.execute(
            "SELECT 1 FROM facet_skips WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        if gated:
            _clear_facet_retry(conn, artifact_id)  # gate is permanent, stop retrying
            conn.commit()
            return 0
        count, error = facets_mod.generate_for_artifact(conn, artifact_id)
        if error and error != "no facet cleared the quality gate":
            # A transient model failure (rate limit, 500, network): keep the summary
            # owed and retry it in the background with escalating backoff.
            _record_facet_retry(conn, artifact_id, error)
        else:
            # Success, or a content-skip that a retry would not change: stop owing.
            _clear_facet_retry(conn, artifact_id)
            if error == "no facet cleared the quality gate":
                # The model ran and produced nothing worth keeping. Mark it skipped so it
                # stops reading as "generating" forever - it is done, just summary-less.
                conn.execute(
                    "INSERT OR IGNORE INTO facet_skips (artifact_id, reason) VALUES (?, 'gate')",
                    (artifact_id,),
                )
        conn.commit()
    except Exception:  # noqa: BLE001 - facets are derived; a failure never blocks capture
        log.exception("facet generation failed for %s", artifact_id)
        with contextlib.suppress(Exception):
            _record_facet_retry(conn, artifact_id, "unexpected error")
            conn.commit()
        return 0
    finally:
        conn.close()

    if error:
        log.warning("facet generation for %s: %s", artifact_id, error)
        return 0
    if count:
        get_store().index_facets_artifact(artifact_id)
        # Facets ride the artifact snapshot to other devices (the phone cannot make its
        # own). Push without bumping recency - a background summary is not a "touch"; the
        # phone's pull re-applies the snapshot on an equal key and picks the facets up.
        facets_mod.sync_facets(artifact_id, bump=False)
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


def backfill_summaries() -> int:
    """Queue every artifact that still owes a summary and is not already being retried.

    The durable backlog is DERIVED from the DB, not a persisted in-memory queue: an
    artifact owes a summary when it is live, not permanently gated (`facet_skips`), and
    has no `facets`. This is what makes summaries survive a restart - the in-memory queue
    is lost when the engine dies, but the DB still knows exactly what is unsummarized, so
    running this at every startup re-queues the lost work.

    It cooperates with the retry backoff (the 30s->24h schedule in `facet_retry`) rather
    than fighting it: artifacts already owed a retry are LEFT to the sweeper, so a failing
    model is never hammered; only artifacts with no retry row (never attempted, or lost to
    a restart before their first attempt) are queued here. On failure they enter
    `facet_retry` and back off; on success they are faceted - so a second startup queues
    almost nothing. A link with no body is force-previewed first, so the worker fetches
    its page before summarizing it. Returns the number queued.
    """
    from .. import db, preview

    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT a.id, a.kind, a.body FROM artifacts a"
            " WHERE a.deleted_at IS NULL AND a.vaulted_at IS NULL AND a.embedded_at IS NULL"
            "   AND a.kind != 'chat'"
            "   AND NOT EXISTS (SELECT 1 FROM facets f WHERE f.artifact_id = a.id)"
            "   AND NOT EXISTS (SELECT 1 FROM facet_skips s WHERE s.artifact_id = a.id)"
            "   AND NOT EXISTS (SELECT 1 FROM facet_retry r WHERE r.artifact_id = a.id)"
        ).fetchall()
    finally:
        conn.close()

    for row in rows:
        # A link summarizes off its fetched article body; force a fetch when it has none
        # so the worker downloads the page before it chunks and faceters it.
        if row["kind"] == "link" and not (row["body"] or "").strip():
            with contextlib.suppress(Exception):
                preview.force(row["id"])
        submit(row["id"])
    return len(rows)


def start_summary_backfill() -> None:
    """Kick the summary backfill once, off the startup thread so boot never blocks.

    Derives the unsummarized set from the DB and queues it (respecting the retry
    backoff). Runs on a short-lived daemon so a large library does not delay the engine
    coming up; the actual generation happens on the ingest worker as usual.
    """

    def _run() -> None:
        try:
            n = backfill_summaries()
            if n:
                log.info("summary backfill queued %d artifact(s)", n)
        except Exception:  # noqa: BLE001 - a backfill hiccup must never break startup
            log.exception("summary backfill failed")

    threading.Thread(target=_run, name="summary-backfill", daemon=True).start()


def submit_all() -> int:
    """Put every artifact back through extraction, chunking, and indexing.

    Needed whenever the pipeline learns something new. A PDF captured before text
    extraction existed has no text and never will until it is asked again, and there
    is no way for it to know that it is out of date.
    """
    from .. import db

    conn = db.get_conn()
    try:
        ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM artifacts WHERE deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL"
            )
        ]
    finally:
        conn.close()

    for artifact_id in ids:
        submit(artifact_id)
    return len(ids)


def submit_images() -> int:
    """Re-queue every image still without a description for the vision step (K.11/L.2).

    The backfill for images captured before a working vision model existed, or
    whose describe run failed: each image with no body is re-read so the vision
    step gives it real content, then chunk, facet, and index flow like any other
    artifact. Already-described images are skipped (their body is set and nothing
    re-charges them).
    """
    from .. import db

    conn = db.get_conn()
    try:
        ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM artifacts WHERE kind = 'image' AND deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL"
                " AND (body IS NULL OR TRIM(body) = '')"
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
