"""Which originals may leave this Mac (C4a)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from enqueue import blobstore, db, offload

RELAY = "https://relay.example"
OLD = "2020-01-01T00:00:00+00:00"


def _seed(kind="pdf", name=None, pinned=0, local_only=0, relay=RELAY, thumb=False, opened=None):
    aid = name or str(uuid.uuid4())
    digest = blobstore.write(b"x", str(uuid.uuid4()))
    now = db.now()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts"
            " (id, kind, title, content_hash, mime, status, pinned, local_only,"
            " created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (aid, kind, "A capture", digest, "application/pdf", "ok", pinned, local_only, OLD, OLD),
        )
        conn.execute(
            "INSERT INTO blob_relay (content_hash, relay, pushed_at) VALUES (?,?,?)",
            (digest, relay.rstrip("/"), now),
        )
        if thumb:
            conn.execute(
                "INSERT INTO thumbs (artifact_id, content_hash, width) VALUES (?,?,?)",
                (aid, digest, 520),
            )
        if opened is not None:
            conn.execute(
                "INSERT INTO opens (artifact_id, source, opened_at) VALUES (?,?,?)",
                (aid, "wall", opened),
            )
    return aid


def test_candidates_are_old_originals_on_this_relay(store):
    good = _seed()

    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    _seed(pinned=1)
    _seed(local_only=1)
    _seed(opened=yesterday)
    _seed(relay="https://other.example")
    _seed(kind="image")
    _seed(kind="image", thumb=True)
    _seed(kind="note")

    got = offload.candidates(db.get_conn(), 30, RELAY)
    ids = [r["id"] for r in got]
    assert good in ids
    assert len(ids) == 2
