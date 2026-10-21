"""The search index's daily upkeep: keyword segments merged, the file's space given back.

Every re-index of an item left its old keyword entries in FTS5 segments until a merge;
nothing merged them, and one library's index grew to 160 times its text."""

from __future__ import annotations

from enqueue import db, notes
from enqueue.index.store import get_store
from enqueue.ingest import queue


def _keyword_segments(table: str) -> int:
    with db.transaction() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}_data").fetchone()[0]


def test_compacting_merges_reindexed_entries_and_search_still_finds_them(store):
    aid = notes.create(body="The willow bends in the storm and does not break.")["artifact"]["id"]
    store_ = get_store()
    for _ in range(12):
        store_.index_artifact(aid)  # each re-index writes tombstones for the old rows
    grown = _keyword_segments("fts_chunks_tri") + _keyword_segments("fts_chunks")
    result = store_.compact()
    assert _keyword_segments("fts_chunks_tri") + _keyword_segments("fts_chunks") < grown
    assert result["after_mb"] <= result["before_mb"]
    assert store_.search_keyword("chunks", "willow", 5)


def test_it_runs_at_most_once_a_day(store, monkeypatch):
    calls = []
    monkeypatch.setattr(
        type(get_store()),
        "compact",
        lambda self: calls.append(1) or {"before_mb": 1, "after_mb": 1},
    )
    queue.compact_index_if_due()
    queue.compact_index_if_due()
    assert calls == [1]
