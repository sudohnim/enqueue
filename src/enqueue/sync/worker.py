"""The background sync worker (SYNC.5).

One pull at a time on the shared `Worker` thread, triggered by the SSE event
stream (live) and a timer (fallback). The pull lists changed objects since the
cursor, downloads them, and applies them through the LWW merge. The SSE client
mirrors dequeue's discipline: query-token auth, auto-reconnect on a transient
drop, a terminal stop on auth rejection, and a heartbeat.
"""

from __future__ import annotations

import logging
import threading

import httpx
from httpx import HTTPError

from ..worker import Worker
from .client import _relay_url, _secret, pull

log = logging.getLogger(__name__)

# Timer fallback interval. The SSE stream is the live path; this catches edits
# that arrived while the stream was down or reconnecting. Five seconds is "soon"
# without polling the relay hard when idle (an idle list-changed-since is cheap
# and returns nothing).
POLL_SECONDS = 5.0
RECONNECT_SECONDS = 5.0

_worker = Worker("sync", lambda _: pull())
_stop = threading.Event()
_threads: list[threading.Thread] = []


def start() -> None:
    """Start the timer fallback and the SSE listener, when sync is configured."""
    if not _relay_url() or _threads:
        return
    _stop.clear()
    _threads.append(_spawn(_timer_loop, "sync-timer"))
    _threads.append(_spawn(_sse_loop, "sync-sse"))


def stop() -> None:
    _stop.set()


def _spawn(fn, name: str) -> threading.Thread:
    thread = threading.Thread(target=fn, name=f"enqueue-{name}", daemon=True)
    thread.start()
    return thread


def _timer_loop() -> None:
    while not _stop.wait(POLL_SECONDS):
        _worker.submit("pull")


def _sse_loop() -> None:
    url = _relay_url()
    base = url.rstrip("/")
    while not _stop.is_set():
        try:
            with httpx.stream(
                "GET",
                f"{base}/sync/events",
                params={"token": _secret()},
                timeout=httpx.Timeout(connect=10, read=None, write=None, pool=None),
            ) as resp:
                if resp.status_code in (401, 403):
                    return  # terminal: the secret is wrong; no point reconnecting
                if resp.status_code != 200:
                    if _stop.wait(RECONNECT_SECONDS):
                        return
                    continue
                for line in resp.iter_lines():
                    if _stop.is_set():
                        return
                    if line.startswith("event: object"):
                        _worker.submit("pull")
        except HTTPError as exc:
            # Transient drop. The timer fallback keeps pulling while we back off
            # and reconnect; no second reconnect loop is added on top of httpx.
            log.debug("sync sse dropped (%s); timer fallback keeps pulling", exc)
        if _stop.wait(RECONNECT_SECONDS):
            return


def wait_idle(timeout: float = 60.0) -> bool:
    """Block until the pull queue is drained. For tests, not for requests."""
    return _worker.wait_idle(timeout)
