"""The activity log (VAULT.6 decoy + real diagnostics).

The Settings "Events" tab shows this: the notable things the engine did - a
question asked and answered, a capture, a facet edit, a sync pull or push. It is
genuinely useful diagnostics, which is the point of the decoy: the tab reads as
ordinary event tracing, and the "Diagnostics" button inside it is the vault door.

Each event carries a one-line `detail` for the row plus an optional `data` blob
(any JSON-able dict) holding the full record - the question text, the answer, the
artifacts cited, per-stage timings - so the tab can open an event and show what
actually happened, not just that it did. Events are persisted (0032_events_log)
so the log survives a restart, and are never synced: a device's activity is its
own. A bounded number is kept; the oldest are trimmed so the table cannot grow
without limit.

Nothing here ever raises: a logging failure must never break a real path.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

log = logging.getLogger(__name__)

# How many events to retain. A person reviewing "what happened" cares about the
# recent past, not the whole history of the install, and this keeps the table
# small enough to read and trim cheaply.
_MAX = 2000
# Trim in batches so the delete does not run on every single emit.
_TRIM_SLACK = 200
_since_trim = 0


def emit(
    kind: str,
    detail: str = "",
    data: dict[str, Any] | None = None,
    duration_ms: int | float | None = None,
) -> None:
    """Record one event. Never raises - diagnostics must not break a real path.

    `kind` is the dotted category the tab groups by (e.g. "ask.answered"),
    `detail` the one-line summary shown on the row, `data` an optional JSON-able
    dict opened on demand, and `duration_ms` how long the action took when known.
    """
    global _since_trim
    try:
        from . import db

        blob = None
        if data is not None:
            try:
                blob = json.dumps(data, default=str)[:20000]
            except Exception:  # noqa: BLE001 - a bad blob never blocks the row
                blob = None
        dur = int(duration_ms) if duration_ms is not None else None
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO events (ts, kind, detail, data, duration_ms) VALUES (?,?,?,?,?)",
                (ts, str(kind), str(detail), blob, dur),
            )
            _since_trim += 1
            if _since_trim >= _TRIM_SLACK:
                _since_trim = 0
                conn.execute(
                    "DELETE FROM events WHERE id <= " "(SELECT MAX(id) FROM events) - ?",
                    (_MAX,),
                )
    except Exception:  # noqa: BLE001 - a logging failure is never worth propagating
        pass


def recent(limit: int = 100) -> list[dict]:
    """The most recent events, newest first. Each row includes its parsed `data`."""
    try:
        from . import db

        conn = db.get_conn()
        try:
            rows = conn.execute(
                "SELECT id, ts, kind, detail, data, duration_ms FROM events"
                " ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, _MAX)),),
            ).fetchall()
        finally:
            conn.close()
        out = []
        for r in rows:
            data = None
            if r["data"]:
                try:
                    data = json.loads(r["data"])
                except Exception:  # noqa: BLE001
                    data = None
            out.append(
                {
                    "id": r["id"],
                    "ts": r["ts"],
                    "kind": r["kind"],
                    "detail": r["detail"] or "",
                    "data": data,
                    "duration_ms": r["duration_ms"],
                }
            )
        return out
    except Exception:  # noqa: BLE001 - an empty log is always a safe answer
        return []
