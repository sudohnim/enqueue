"""An engine-wide pause on model calls after the provider says "limit reached".

A usage limit is a property of the account, not of one request: when OpenCode Go
answers 429 `GoUsageLimitError` ("limitName": "5 hour"), every call made before the
window rolls will fail the same way. Retrying each ingest step on its own backoff
spent one refused call per queued item and inflated every item's attempt count, so
the library resumed piecemeal, hours after the limit had already reset.

So the first 429 trips one pause for the whole engine, until the moment the provider
names in its `retry-after` header (OpenCode sends seconds). While paused, a model
call fails at once without touching the network (`ModelPaused`, which counts as
transient), owed ingest work is rescheduled for the end of the pause without
counting an attempt, and the retry sweeper waits. The first call after the pause
goes out normally; if the provider still refuses, the pause is simply tripped again.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .base import ProviderError

# When the provider gives no retry-after, wait this long before one call probes again.
DEFAULT_WAIT = 15 * 60
# Never shorter than this: a zero or tiny retry-after must not become a hammer.
MIN_WAIT = 30

_lock = threading.Lock()
_until: datetime | None = None
_reason = ""


class ModelPaused(ProviderError):
    """A model call refused locally because the provider's usage limit is in effect."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def until() -> datetime | None:
    """When the current pause ends, or None when calls are not paused."""
    with _lock:
        return _until if _until is not None and _now() < _until else None


def active() -> bool:
    return until() is not None


def status() -> dict | None:
    """The pause as data for diagnostics (`enq doctor`), or None when not paused."""
    end = until()
    if end is None:
        return None
    return {"until": end.isoformat(), "reason": _reason}


def check() -> None:
    """Raise ModelPaused when calls are paused; called before every model call."""
    end = until()
    if end is not None:
        local = end.astimezone().strftime("%H:%M")
        raise ModelPaused(f"Paused: {_reason}. Model calls resume at {local}.")


def _retry_after_seconds(response) -> float | None:
    """The provider's retry-after, as seconds from now: an integer, or an HTTP date."""
    headers = getattr(response, "headers", None)
    raw = (headers.get("retry-after") or "").strip() if headers is not None else ""
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        return (parsedate_to_datetime(raw) - _now()).total_seconds()
    except (TypeError, ValueError):
        return None


def _describe(response) -> str:
    """A short name for the limit: OpenCode's `GoUsageLimitError` + `limitName`."""
    try:
        body = json.loads(response.text)
    except Exception:  # noqa: BLE001 - any unreadable body gets the generic name
        body = {}
    if not isinstance(body, dict):
        body = {}
    error = body.get("error")
    kind = error.get("type") if isinstance(error, dict) else None
    metadata = body.get("metadata")
    limit = metadata.get("limitName") if isinstance(metadata, dict) else None
    if kind == "GoUsageLimitError":
        return "OpenCode Go usage limit" + (f" ({limit})" if limit else "")
    return "the model provider is rate limiting"


def trip_from(exc: BaseException) -> bool:
    """Pause all model calls if `exc` is (or wraps) a 429. Returns whether it did.

    The pause runs until the provider's retry-after (at least MIN_WAIT), or
    DEFAULT_WAIT when it gives none. A later 429 can only extend the pause.
    """
    import openai

    global _until, _reason
    link: BaseException | None = exc
    while link is not None and not isinstance(link, openai.RateLimitError):
        link = link.__cause__ or link.__context__
    if link is None:
        return False
    response = getattr(link, "response", None)
    wait = _retry_after_seconds(response)
    wait = DEFAULT_WAIT if wait is None else max(MIN_WAIT, wait)
    end = _now() + timedelta(seconds=wait)
    reason = _describe(response)
    with _lock:
        was_active = _until is not None and _now() < _until
        if was_active and _until is not None and end <= _until:
            return True
        _until, _reason = end, reason
    if not was_active:
        from .. import events

        local = end.astimezone().strftime("%H:%M")
        events.emit(
            "model.paused",
            f"{reason}: model calls paused until {local}",
            data={"until": end.isoformat(), "retry_after_seconds": round(wait), "reason": reason},
        )
    return True


def lift(why: str) -> int:
    """End the pause early because what it was about changed: a new API key, or a
    different backend, model, or endpoint. The limit belonged to the old account or
    model, so waiting it out would only idle a working one.

    Also brings every owed summary retry forward to now, so the backlog resumes at
    once instead of at the old pause end (the sweeper takes 20 every 30s). Returns
    how many retries were brought forward.
    """
    from .. import db, events

    was = active()
    reset()
    now = _now().isoformat()
    with db.transaction() as conn:
        moved = conn.execute(
            "UPDATE facet_retry SET next_at = ? WHERE next_at > ?", (now, now)
        ).rowcount
    if was or moved:
        events.emit(
            "model.resumed",
            f"{why}: model calls resumed, {moved} owed summaries brought forward",
            data={"was_paused": was, "retries_moved": moved},
        )
    return moved


def reset() -> None:
    """Clear any pause. For tests."""
    global _until, _reason
    with _lock:
        _until, _reason = None, ""
