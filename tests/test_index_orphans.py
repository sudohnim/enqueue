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


def test_ingest_never_chunks_a_trashed_artifact_back(sqlite_store):
    from enqueue import notes, trash
    from enqueue.ingest import queue as q

    aid = notes.create(body="Wax resist on the foot ring.")["artifact"]["id"]
    q.process(aid)
    trash.delete(aid)

    q.process(aid)  # a retry or backfill that raced the delete

    assert _chunks() == 0
    assert _index_rows(sqlite_store) == {"chunks": 0, "fts_chunks": 0, "fts_chunks_tri": 0}


def test_vaulting_drops_the_note_from_the_index(sqlite_store, monkeypatch):
    from enqueue import notes, vault, vaultops
    from enqueue.ingest import queue as q

    monkeypatch.setattr(vaultops, "push_artifact", lambda *_a, **_k: None)
    vault.lock()
    vault.setup("123456")
    try:
        aid = notes.create(body="The safe code is under the kiln.")["artifact"]["id"]
        q.process(aid)
        vaultops.vault_artifact(aid)
    finally:
        vault.lock()

    assert _index_rows(sqlite_store) == {"chunks": 0, "fts_chunks": 0, "fts_chunks_tri": 0}


def test_prune_drops_chunks_of_trashed_artifacts(sqlite_store):
    from enqueue import notes
    from enqueue.ingest import queue as q

    aid = notes.create(body="Slip trailing a spiral.")["artifact"]["id"]
    q.process(aid)
    with db.transaction() as conn:  # an older build re-chunked it after the delete
        conn.execute("UPDATE artifacts SET deleted_at = ? WHERE id = ?", (db.now(), aid))

    q.prune_index()

    assert _chunks() == 0
    assert _index_rows(sqlite_store) == {"chunks": 0, "fts_chunks": 0, "fts_chunks_tri": 0}


def test_prune_indexes_rows_the_index_is_missing(sqlite_store):
    from enqueue import notes
    from enqueue.ingest import queue as q

    aid = notes.create(body="Reduction firing turns copper red.")["artifact"]["id"]
    q.process(aid)
    whole = _index_rows(sqlite_store)
    sqlite_store.drop_artifact(sqlite_store.CHUNKS, aid)  # an interrupted rebuild

    q.prune_index()

    assert _index_rows(sqlite_store) == whole
    assert whole["chunks"] == _chunks()
