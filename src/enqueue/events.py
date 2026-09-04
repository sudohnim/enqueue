"""A small in-memory event log (VAULT.6 decoy + real diagnostics).

The Settings "Events" tab shows this: a bounded, in-memory ring of the notable
things the engine did this session (sync pulls/pushes, ingest completions,
captures). It is genuinely useful diagnostics - which is the point of the decoy:
the tab reads as ordinary event tracing, and the "Diagnostics" button inside it
is the vault door. Nothing here is persisted or synced; it resets on restart.
"""

from __future__ import annotations

import threading
import time
from collections import deque

_MAX = 200
_events: deque[dict] = deque(maxlen=_MAX)
_lock = threading.Lock()


def emit(kind: str, detail: str = "") -> None:
    """Record one event. Never raises - diagnostics must not break a real path."""
    try:
        with _lock:
            _events.append(
                {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": str(kind), "detail": str(detail)}
            )
    except Exception:  # noqa: BLE001 - a logging failure is never worth propagating
        pass


def recent(limit: int = 100) -> list[dict]:
    """The most recent events, newest first."""
    with _lock:
        items = list(_events)
    items.reverse()
    return items[: max(1, min(limit, _MAX))]
