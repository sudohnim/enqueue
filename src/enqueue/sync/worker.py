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
import time

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
# When the relay is unreachable, stop pulling every 5s: back off exponentially
# (10s, 20s, ... capped) so an outage is a handful of quiet retries, not a
# traceback every tick. Reset the moment a pull succeeds.
BACKOFF_MAX_SECONDS = 300.0

# monotonic timestamp before which the timer loop skips submitting a pull.
_backoff_until = 0.0
_fail_streak = 0


def _pull_handler(_item: object) -> object:
    """Run one pull, turning a relay outage into a terse warning + backoff.

    A network failure to a flaky relay is expected operation, not a bug, so it
    must not reach the shared Worker's `log.exception` (a full traceback every
    tick). We swallow the network-error families here with a one-line warning and
    arm an exponential backoff the timer loop honours. Any OTHER exception is a
    real defect and is left to propagate so the Worker logs it in full.
    """
    global _backoff_until, _fail_streak
    try:
        result = pull()
    except (httpx.TimeoutException, httpx.TransportError, HTTPError) as exc:
        _fail_streak += 1
        delay = min(POLL_SECONDS * 2**_fail_streak, BACKOFF_MAX_SECONDS)
        _backoff_until = time.monotonic() + delay
        log.warning(
            "sync pull failed (relay unreachable: %s); backing off %.0fs",
            type(exc).__name__,
            delay,
        )
        return None
    if _fail_streak:
        log.info("sync pull recovered after %d failed attempt(s)", _fail_streak)
    _fail_streak = 0
    _backoff_until = 0.0
    try:
        pulled = (result or {}).get("pulled", 0)
        if pulled:
            from .. import events

            events.emit("sync.pull", f"{pulled} applied")
    except Exception:  # noqa: BLE001
        pass
    return result


_worker = Worker("sync", _pull_handler)
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
        # Honour the backoff armed by a failed pull: while the relay is down the
        # timer stays quiet instead of queuing a doomed pull every 5s.
        if time.monotonic() < _backoff_until:
            continue
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
