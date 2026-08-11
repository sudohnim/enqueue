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
from typing import Generic, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


class Worker(Generic[T]):
    """A single daemon thread draining an in-memory queue.

    `handle(item)` runs on the worker thread and must never raise out of the
    loop; the loop logs and swallows so one bad item cannot stop the queue.
    `pre(item)` is optional and runs before the handler, still on the worker
    thread - the ingest queue uses it for its I5.1 coalescing bookkeeping.
    """

    def __init__(
        self,
        name: str,
        handle: Callable[[T], object],
        pre: Callable[[T], None] | None = None,
    ) -> None:
        self._name = name
        self._handle = handle
        self._pre = pre
        self._work: queue.Queue[T] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()

    def _run(self) -> None:
        while True:
            item = self._work.get()
            self._idle.clear()
            if self._pre is not None:
                self._pre(item)
            try:
                self._handle(item)
            except Exception:  # noqa: BLE001 - one bad item must not stop the queue
                log.exception("%s failed for %s", self._name, item)
            finally:
                self._work.task_done()
                if self._work.empty():
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

    def wait_idle(self, timeout: float = 60.0) -> bool:
        """Block until the queue is drained. For tests and the CLI, not for requests."""
        return self._idle.wait(timeout)
