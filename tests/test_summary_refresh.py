"""Re-summarizing the library after a summary-model switch.

Search only uses facets written by the active summary model, so a switch leaves the
conceptual layer empty until every item is re-summarized. That refresh used to run as
one multi-hour request (`POST /facets`): a restart killed it, `redo` started over, it
ran off the ingest worker, and it summarized trashed and vaulted items too. Now the
stale set is derived from the DB at every startup and queued on the worker.
"""

from __future__ import annotations

import uuid

from enqueue import db, notes
from enqueue.ingest import facets as facets_mod
from enqueue.ingest import queue as q
from enqueue.providers.base import get_provider


def _facet(aid: str, model: str) -> None:
    with db.transaction() as conn:
        # Stamped with the body it was written from, like the real generator does.
        body_version = conn.execute(
            "SELECT MAX(created_at) FROM artifact_versions WHERE artifact_id = ?", (aid,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO facets (id, artifact_id, level, statement, model_version, body_version,"
            " trust) VALUES (?, ?, 1, 'A statement about a general idea.', ?, ?, 0.5)",
            (str(uuid.uuid4()), aid, model, body_version),
        )


def test_backfill_queues_summaries_written_by_another_model(store, quiet_queue):
    body = "a body long enough to earn a summary from the model, with a few more words"
    stale = notes.create(body=body)["artifact"]["id"]
    current = notes.create(body=body + " and another")["artifact"]["id"]
    quiet_queue.clear()
    _facet(stale, "some-older-model")
    _facet(current, get_provider(summarize=True).model)

    assert q.backfill_summaries() >= 1
    assert stale in quiet_queue
    assert current not in quiet_queue


def test_backfill_skips_trashed_and_vaulted(store, quiet_queue):
    body = "a body long enough to earn a summary from the model, with a few more words"
    trashed = notes.create(body=body)["artifact"]["id"]
    vaulted = notes.create(body=body + " again")["artifact"]["id"]
    with db.transaction() as conn:
        conn.execute("UPDATE artifacts SET deleted_at = '2026-01-01' WHERE id = ?", (trashed,))
        conn.execute("UPDATE artifacts SET vaulted_at = '2026-01-01' WHERE id = ?", (vaulted,))
    quiet_queue.clear()
    q.backfill_summaries()
    assert trashed not in quiet_queue and vaulted not in quiet_queue


def test_redo_forces_even_current_summaries(store, quiet_queue):
    aid = notes.create(body="a body long enough to earn a summary from the model")["artifact"]["id"]
    _facet(aid, get_provider(summarize=True).model)
    quiet_queue.clear()
    assert q.queue_summary_refresh(redo=True) >= 1
    assert aid in quiet_queue
    # The force is taken once, by the run that regenerates it.
    assert facets_mod.take_forced(aid) is True
    assert facets_mod.take_forced(aid) is False


def test_generate_all_never_summarizes_a_vaulted_or_trashed_item(store, quiet_queue, monkeypatch):
    body = "a body long enough to earn a summary from the model, with a few more words"
    live = notes.create(body=body)["artifact"]["id"]
    vaulted = notes.create(body=body + " again")["artifact"]["id"]
    trashed = notes.create(body=body + " and again")["artifact"]["id"]
    with db.transaction() as conn:
        conn.execute("UPDATE artifacts SET vaulted_at = '2026-01-01' WHERE id = ?", (vaulted,))
        conn.execute("UPDATE artifacts SET deleted_at = '2026-01-01' WHERE id = ?", (trashed,))
    seen: list[str] = []
    monkeypatch.setattr(
        facets_mod, "generate_for_artifact", lambda conn, aid: (seen.append(aid), (0, None))[1]
    )
    facets_mod.generate_all(redo=True)
    assert live in seen
    assert vaulted not in seen and trashed not in seen
