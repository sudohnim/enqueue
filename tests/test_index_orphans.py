"""Re-ingesting an artifact must replace its index rows, never add to them."""

from __future__ import annotations

import pytest

from enqueue import db


@pytest.fixture
def sqlite_store(store, quiet_queue, monkeypatch):
    from enqueue import config
    from enqueue.index.store import get_store
    from enqueue.ingest import queue as q

    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    for step in (
        "_sections_artifact",
        "_facet_artifact",
        "_entities_artifact",
        "_context_artifact",
    ):
        monkeypatch.setattr(q, step, lambda _aid: 0)
    get_store.cache_clear()
    s = get_store()
    s.ensure()
    yield s
    get_store.cache_clear()


def _index_rows(store) -> dict:
    counts = store.counts()
    return {k: counts[k] for k in ("chunks", "fts_chunks", "fts_chunks_tri")}


def _chunks() -> int:
    conn = db.get_conn()
    try:
        return conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
    finally:
        conn.close()


def test_reprocessing_replaces_chunk_rows_in_the_index(sqlite_store):
    from enqueue import notes
    from enqueue.ingest import queue as q

    aid = notes.create(body="# Kilns\\n\\n" + "Cone six firing notes. " * 200)["artifact"]["id"]
    q.process(aid)
    once = _index_rows(sqlite_store)

    q.process(aid)
    q.process(aid)

    assert _index_rows(sqlite_store) == once
    assert once["chunks"] == _chunks()


def test_prune_removes_rows_whose_source_is_gone(sqlite_store):
    from enqueue import notes
    from enqueue.ingest import queue as q

    aid = notes.create(body="Glaze crawling after a dusty bisque.")["artifact"]["id"]
    q.process(aid)
    with db.transaction() as conn:  # an older build left rows behind like this
        conn.execute("DELETE FROM chunks WHERE artifact_id = ?", (aid,))

    removed = sqlite_store.prune_orphans()

    assert removed["chunks"] >= 1
    assert _index_rows(sqlite_store) == {"chunks": 0, "fts_chunks": 0, "fts_chunks_tri": 0}
