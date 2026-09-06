"""A transient model failure while generating an artifact's summary (facets) must
not lose the summary: it is owed in facet_retry, surfaced as `summary_generating`,
and retried in the background until it succeeds. A content/gate skip is not retried.
"""

from __future__ import annotations

from datetime import datetime, timezone

from enqueue import db, notes
from enqueue.ingest import facets as facets_mod
from enqueue.ingest import queue as q


def _retry_row(aid):
    conn = db.get_conn()
    try:
        return conn.execute(
            "SELECT attempts, next_at FROM facet_retry WHERE artifact_id = ?", (aid,)
        ).fetchone()
    finally:
        conn.close()


def test_transient_failure_owes_a_retry_and_reads_as_generating(store, monkeypatch):
    aid = notes.create(body="a body long enough to earn a summary from the model")["artifact"]["id"]

    monkeypatch.setattr(
        facets_mod, "generate_for_artifact", lambda conn, _id: (0, "APIError: 500 over capacity")
    )
    assert q._facet_artifact(aid) == 0
    row = _retry_row(aid)
    assert row is not None and row["attempts"] == 1
    assert notes.get(aid)["summary_generating"] is True

    # A second failure escalates the backoff (attempts grows), still owed.
    assert q._facet_artifact(aid) == 0
    assert _retry_row(aid)["attempts"] == 2


def test_success_clears_the_retry(store, monkeypatch):
    aid = notes.create(body="another body worth summarizing at some length here")["artifact"]["id"]
    monkeypatch.setattr(facets_mod, "generate_for_artifact", lambda conn, _id: (0, "APIError: 429"))
    q._facet_artifact(aid)
    assert _retry_row(aid) is not None

    # Now the model answers: the facets are written by the real generator, so stub a
    # success that returns a count (indexing is a no-op on the test store).
    monkeypatch.setattr(facets_mod, "generate_for_artifact", lambda conn, _id: (3, None))
    q._facet_artifact(aid)
    assert _retry_row(aid) is None
    assert notes.get(aid)["summary_generating"] is False


def test_backoff_is_exponential_and_capped_at_24h(store):
    aid = notes.create(body="body for the backoff cap check, long enough to matter")["artifact"][
        "id"
    ]

    def delay_seconds(attempts_before):
        with db.transaction() as conn:
            conn.execute("DELETE FROM facet_retry WHERE artifact_id = ?", (aid,))
            if attempts_before:
                conn.execute(
                    "INSERT INTO facet_retry (artifact_id, attempts, next_at) VALUES (?,?,?)",
                    (aid, attempts_before, "2000-01-01T00:00:00+00:00"),
                )
            q._record_facet_retry(conn, aid, "APIError: 500")
        row = _retry_row(aid)
        gone = datetime.fromisoformat(row["next_at"]) - datetime.now(timezone.utc)
        return gone.total_seconds()

    assert 25 <= delay_seconds(0) <= 35  # first retry ~30s
    assert 55 <= delay_seconds(1) <= 65  # then ~60s (doubling)
    assert 110 <= delay_seconds(2) <= 130  # then ~120s
    # A long-owed summary settles at the 24h ceiling, never beyond.
    assert 86_000 <= delay_seconds(50) <= 86_400 + 5


def test_content_skip_is_not_retried(store, monkeypatch):
    aid = notes.create(body="short")["artifact"]["id"]
    monkeypatch.setattr(
        facets_mod,
        "generate_for_artifact",
        lambda conn, _id: (0, "no facet cleared the quality gate"),
    )
    q._facet_artifact(aid)
    assert _retry_row(aid) is None  # a content skip never schedules a retry
    assert notes.get(aid)["summary_generating"] is False
