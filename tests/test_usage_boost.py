"""Usage-aware ranking: opens, citations and pins lift a note a little, and fade."""

from __future__ import annotations

import pytest

from enqueue import db, opens


def _note(conn, aid: str, body: str, pinned: int = 0) -> None:
    conn.execute(
        "INSERT INTO artifacts (id, kind, title, body, content_hash, status, pinned,"
        " created_at, updated_at) VALUES (?, 'note', 'Glaze notes', ?, ?, 'ok', ?, ?, ?)",
        (aid, body, aid, pinned, db.now(), db.now()),
    )


def _boost(ids):
    conn = db.get_conn()
    try:
        return opens.usage_boost(conn, ids)
    finally:
        conn.close()


def test_unused_artifacts_get_no_boost(store):
    with db.transaction() as conn:
        _note(conn, "a", "x")
    assert _boost(["a"]) == {}


def test_the_boost_grows_with_use_and_saturates_below_the_cap(store):
    with db.transaction() as conn:
        _note(conn, "a", "x")
        _note(conn, "b", "x")
    opens.record("a", "wall")
    for _ in range(50):
        opens.record("b", "search", "glaze", 1)

    boost = _boost(["a", "b"])

    assert boost["a"] == pytest.approx(1 + opens.USAGE_WEIGHT / (1 + opens.USAGE_HALF), abs=1e-3)
    assert boost["a"] < boost["b"] < 1 + opens.USAGE_WEIGHT


def test_old_use_fades_and_pins_and_citations_count(store):
    with db.transaction() as conn:
        _note(conn, "old", "x")
        _note(conn, "new", "x")
        _note(conn, "pinned", "x", pinned=1)
        _note(conn, "cited", "x")
        conn.execute(
            "INSERT INTO opens (artifact_id, source, opened_at) VALUES ('old', 'wall', ?)",
            ("2020-01-01T00:00:00",),
        )
        conn.execute(
            "INSERT INTO chats (id, title, created_at, updated_at) VALUES ('c', 't', ?, ?)",
            (db.now(), db.now()),
        )
        conn.execute(
            "INSERT INTO chat_messages (id, chat_id, ordinal, role, text, grounded, created_at)"
            " VALUES ('m', 'c', 1, 'assistant', 'answer', 1, ?)",
            (db.now(),),
        )
        conn.execute(
            "INSERT INTO chat_citations (message_id, artifact_id, rank) VALUES ('m', 'cited', 1)"
        )
    opens.record("new", "wall")

    boost = _boost(["old", "new", "pinned", "cited"])

    assert boost["old"] < 1.001 < boost["new"]
    assert boost["cited"] == pytest.approx(boost["new"], abs=1e-3)
    assert boost["pinned"] == pytest.approx(1 + opens.USAGE_WEIGHT / 2)


def test_search_breaks_a_tie_toward_the_note_you_use(store, monkeypatch):
    from enqueue import config
    from enqueue.index.store import get_store
    from enqueue.ingest.chunk import chunk_artifact
    from enqueue.retrieve import candidates as cand

    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    monkeypatch.setattr(
        cand, "judge_gray_zone", lambda query, hits: {h["artifact_id"] for h in hits}
    )
    body = "Celadon glaze crawls when the bisque is dusty."
    with db.transaction() as conn:
        for aid in ("first", "second"):
            _note(conn, aid, body)
            chunk_artifact(conn, aid)
    get_store.cache_clear()
    s = get_store()
    s.ensure()
    s.upsert_chunks()

    before = [h["artifact_id"] for h in cand.search_results("celadon glaze crawls")]
    unused = before[1]
    for _ in range(3):
        opens.record(unused, "search", "celadon glaze crawls", 2)
    after = [h["artifact_id"] for h in cand.search_results("celadon glaze crawls")]

    assert after[0] == unused
    get_store.cache_clear()
