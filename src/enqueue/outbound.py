"""A record of what was sent to remote models, for the Activity log.

Every structured call and image description to a non-loopback endpoint is counted
here (providers/ollama.py): which service, which model, what for, how many characters
and how many credentials were blanked on the way (ingest/secrets.py). The text itself
is never recorded.

One row per call would bury everything else in the bounded log (a reprocess makes
several calls per item), so calls are added up and written as one `model.sent` row per
service every WINDOW seconds, and whenever the engine shuts down cleanly.
"""

from __future__ import annotations

import atexit
import threading
from urllib.parse import urlsplit

WINDOW = 600.0

# What each structured call is for, by its response model.
PURPOSES = {
    "_RawFacetSet": "idea cards",
    "_RawEntitySet": "entities",
    "_RawFactSet": "entity facts",
    "_RawFact": "entity facts",
    "_RawSectionSummary": "section summaries",
    "_RawChunkContextSet": "passage context",
    "Answer": "chat answers",
    "AssistantRoute": "chat routing",
    "ChatTitle": "chat titles",
    "ChatTopics": "chat topics",
    "_GrayZoneResponse": "search judging",
    "_RawOrder": "search ranking",
    "_RawLift": "search lifting",
    "_PlannedSpec": "view planning",
    "_One": "view values",
    "_Buckets": "view grouping",
    "image": "image descriptions",
}

_lock = threading.Lock()
_pending: dict[tuple[str, str, str], dict[str, int]] = {}
_timer: threading.Timer | None = None


def record(base_url: str, model: str, purpose: str, chars: int, redacted: int = 0) -> None:
    """Count one call to a remote model. Never raises: it must not fail a model call."""
    global _timer
    try:
        host = urlsplit(base_url).hostname or base_url
        label = PURPOSES.get(purpose, purpose)
        with _lock:
            row = _pending.setdefault((host, model, label), {"calls": 0, "chars": 0, "redacted": 0})
            row["calls"] += 1
            row["chars"] += chars
            row["redacted"] += redacted
            if _timer is None:
                _timer = threading.Timer(WINDOW, flush)
                _timer.daemon = True
                _timer.start()
    except Exception:  # noqa: BLE001 - diagnostics only
        pass


def flush() -> None:
    """Write what was counted since the last flush as one Activity row per service."""
    global _timer
    with _lock:
        pending = dict(_pending)
        _pending.clear()
        if _timer is not None:
            _timer.cancel()
            _timer = None
    if not pending:
        return

    from . import events

    by_host: dict[str, list[dict]] = {}
    for (host, model, label), row in pending.items():
        by_host.setdefault(host, []).append({"model": model, "purpose": label, **row})
    for host, rows in by_host.items():
        rows.sort(key=lambda r: -r["chars"])
        calls = sum(r["calls"] for r in rows)
        chars = sum(r["chars"] for r in rows)
        redacted = sum(r["redacted"] for r in rows)
        purposes: dict[str, int] = {}
        for r in rows:
            purposes[r["purpose"]] = purposes.get(r["purpose"], 0) + r["calls"]
        detail = (
            f"{host}: {calls} call{'s' if calls != 1 else ''}, {_size(chars)} ("
            + ", ".join(f"{p} {n}" for p, n in sorted(purposes.items(), key=lambda kv: -kv[1]))
            + ")"
        )
        if redacted:
            detail += f", {redacted} secret{'s' if redacted != 1 else ''} blanked"
        events.emit(
            "model.sent",
            detail,
            data={
                "host": host,
                "calls": calls,
                "chars": chars,
                "redacted": redacted,
                "by": rows,
            },
        )


def _size(chars: int) -> str:
    if chars >= 1_000_000:
        return f"{chars / 1_000_000:.1f}M chars"
    if chars >= 1_000:
        return f"{chars / 1_000:.0f}k chars"
    return f"{chars} chars"


atexit.register(flush)
