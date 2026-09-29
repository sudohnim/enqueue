"""One worker-thread lifecycle, shared by the ingest queue and the answer worker.

Both queues are the same shape: a single daemon thread drains an in-memory
Queue one item at a time, and submitting never blocks on the work it hands
off - the ingest queue keeps capture instant, the answer worker keeps asking
instant. They differ only in what they do with each item (and the ingest
queue's I5.1 bookkeeping before it does it), so the whole lifecycle - the
queue, the idle Event, the double-checked worker start, the run loop, and
wait_idle - lives here once.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any, Generic, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

# Put on the work queue to wake an idle worker for an exclusive job; never handled.
_WAKE = object()


class Worker(Generic[T]):
    """A single daemon thread draining an in-memory queue.

    `handle(item)` runs on the worker thread and must never raise out of the
    loop; the loop logs and swallows so one bad item cannot stop the queue.
    `pre(item)` is optional and runs before the handler, still on the worker
    thread - the ingest queue uses it for its I5.1 coalescing bookkeeping.
    `on_idle()` is optional and runs on the worker thread each time the queue
    drains, before `wait_idle` returns - the ingest queue prunes its index there.
    `run_exclusive(fn)` runs `fn` on the worker thread between two items, ahead of
    anything still queued, so work that must not race the handler (a full index
    rebuild, a prune) never fights it for the database.
    """

    def __init__(
        self,
        name: str,
        handle: Callable[[T], object],
        pre: Callable[[T], None] | None = None,
        on_idle: Callable[[], None] | None = None,
    ) -> None:
        self._name = name
        self._handle = handle
        self._pre = pre
        self._on_idle = on_idle
        self._work: queue.Queue[T] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        self._jobs: queue.Queue[tuple[Callable[[], Any], Future]] = queue.Queue()

    def _run_jobs(self) -> None:
        while True:
            try:
                fn, done = self._jobs.get_nowait()
            except queue.Empty:
                return
            if not done.set_running_or_notify_cancel():
                continue
            try:
                done.set_result(fn())
            except Exception as exc:  # noqa: BLE001 - handed back to the caller
                done.set_exception(exc)

    def _run(self) -> None:
        while True:
            item = self._work.get()
            self._idle.clear()
            self._run_jobs()
            if item is _WAKE:
                self._work.task_done()
                if self._work.empty():
                    self._idle.set()
                continue
            if self._pre is not None:
                self._pre(item)
            try:
                self._handle(item)
            except Exception:  # noqa: BLE001 - one bad item must not stop the queue
                log.exception("%s failed for %s", self._name, item)
            finally:
                self._work.task_done()
                if self._work.empty():
                    if self._on_idle is not None:
                        try:
                            self._on_idle()  # housekeeping once a burst of work drains
                        except Exception:  # noqa: BLE001 - never stop the queue for it
                            log.exception("%s idle hook failed", self._name)
                    self._idle.set()

    def _ensure_worker(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._run, name=f"enqueue-{self._name}", daemon=True
            )
            self._worker.start()

    def submit(self, item: T) -> None:
        """Queue an item for processing; returns immediately."""
        self._ensure_worker()
        self._idle.clear()
        self._work.put(item)

    def run_exclusive(
        self, fn: Callable[[], Any], wait: bool = True, timeout: float | None = None
    ) -> Any:
        """Run `fn` on the worker thread as soon as the current item finishes.

        With `wait`, block until it has run and return its result (or raise its
        exception); otherwise return at once and let it run in the background.
        """
        done: Future = Future()
        self._jobs.put((fn, done))
        self._ensure_worker()
        self._work.put(_WAKE)
        return done.result(timeout) if wait else None

    def wait_idle(self, timeout: float = 60.0) -> bool:
        """Block until the queue is drained. For tests and the CLI, not for requests."""
        return self._idle.wait(timeout)
