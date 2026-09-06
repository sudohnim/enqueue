"""Starring (a flag change) must bump updated_at and push, or it never propagates:
an unbumped updated_at ties the pre-star snapshot under LWW, and no push means the
relay never hears about it. Regression for stars not syncing between devices.
"""

from __future__ import annotations

from enqueue import db, notes
import enqueue.sync.client as sync_client
from enqueue.api import artifacts as api_artifacts


def _row(aid):
    conn = db.get_conn()
    try:
        return conn.execute(
            "SELECT pinned, updated_at FROM artifacts WHERE id = ?", (aid,)
        ).fetchone()
    finally:
        conn.close()


def test_starring_bumps_updated_at_and_pushes(store, monkeypatch):
    pushed = []
    monkeypatch.setattr(sync_client, "push_artifact", lambda aid: pushed.append(aid))

    aid = notes.create(body="star me and sync me")["artifact"]["id"]
    before = _row(aid)["updated_at"]
    pushed.clear()  # ignore the create's own push; we only care about the star's

    api_artifacts.set_flags(aid, api_artifacts.ArtifactFlags(pinned=True))

    after = _row(aid)
    assert after["pinned"] == 1
    assert after["updated_at"] > before  # bumped so LWW carries the star
    assert pushed == [aid]  # pushed so the other devices hear about it
