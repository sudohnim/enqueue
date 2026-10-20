"""How far the assistant is through reading the library, for the line on the wall.

A first import, a switch of ingest model, or a sync that pulls a big library onto a
new Mac leaves many items without a current summary at once, and the model reads them
one by one for a while. The wall says so (`GET /reading`, `refreshReading` in
static/js/home.js) until it is done. One aggregate query, no model call: the page
polls it every few seconds only while the line is up.
"""

from __future__ import annotations

from . import db
from .ingest import queue as ingest_queue
from .providers import pause

# Fewer items than this left unread is ordinary upkeep (a capture, an edit), not a
# big read, so the line does not come up for it.
SHOW_FROM = 10

_COUNTS = """
SELECT COUNT(*) AS total,
       COALESCE(SUM(EXISTS (
           SELECT 1 FROM facets f
            WHERE f.artifact_id = a.id AND f.edited = 0
              AND f.body_version IS (SELECT MAX(v.created_at) FROM artifact_versions v
                                      WHERE v.artifact_id = a.id))), 0) AS done
  FROM artifacts a
 WHERE a.deleted_at IS NULL AND a.vaulted_at IS NULL AND a.embedded_at IS NULL
   AND a.kind != 'chat'
   AND NOT EXISTS (SELECT 1 FROM facet_skips s WHERE s.artifact_id = a.id)
"""


def progress() -> dict:
    """Where the reading stands.

    `total`/`done` count the same items `enq doctor` does (summaries current vs not).
    `state` says what the work is doing: `reading` (the queue is busy), `retrying`
    (items owed a run, the queue idle until they come due), `paused` (a usage limit,
    until `paused_until`), `key` (the service refused the key), or `idle`. `show` is
    whether a big read is under way: at least SHOW_FROM items left and work owed or
    blocked. A note still being typed (`queue.WAITING`) is not owed work here.
    """
    conn = db.get_conn()
    try:
        row = conn.execute(_COUNTS).fetchone()
        owed = conn.execute(
            "SELECT COUNT(*) AS n FROM facet_retry WHERE COALESCE(last_error, '') NOT LIKE ?",
            (ingest_queue.WAITING + "%",),
        ).fetchone()["n"]
    finally:
        conn.close()
    total, done = int(row["total"]), int(row["done"])
    remaining = total - done
    end = pause.until()
    if pause.key_refused():
        state = "key"
    elif end is not None:
        state = "paused"
    elif ingest_queue.busy():
        state = "reading"
    elif owed:
        state = "retrying"
    else:
        state = "idle"
    return {
        "total": total,
        "done": done,
        "remaining": remaining,
        "state": state,
        "paused_until": end.isoformat() if end is not None else None,
        "show": remaining >= SHOW_FROM and state != "idle",
    }
