"""Contextual chunks: the ingest model places each chunk of a long document in it."""

from __future__ import annotations

import uuid

import pytest

from enqueue import db
from enqueue.ingest import context as context_mod


class _Provider:
    name = "fake"
    model = "ctx-model"

    def __init__(self, reply):
        self.reply = reply
        self.calls: list[str] = []

    def complete(self, system, user, response_model, context=None, max_retries=None):
        self.calls.append(user)
        if isinstance(self.reply, Exception):
            raise self.reply
        return response_model(**self.reply)


def _patch(monkeypatch, reply):
    import enqueue.providers.base as base_mod

    provider = _Provider(reply)
    monkeypatch.setattr(base_mod, "get_provider", lambda **kw: provider)
    return provider


def _artifact(chunks: list[str], status: str = "ok") -> str:
    aid = str(uuid.uuid4())
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, status, created_at,"
            " updated_at) VALUES (?, 'note', 'Field guide', ?, ?, ?, ?, ?)",
            (aid, "\n\n".join(chunks), aid, status, db.now(), db.now()),
        )
        for i, text in enumerate(chunks):
            conn.execute(
                "INSERT INTO chunks (id, artifact_id, ordinal, text, chunker) VALUES (?,?,?,?,?)",
                (f"{aid}-{i}", aid, i, text, "test"),
            )
    return aid


def _generate(aid):
    conn = db.get_conn()
    try:
        return context_mod.generate_for_artifact(conn, aid)
    finally:
        conn.commit()
        conn.close()


def _contexts(aid):
    conn = db.get_conn()
    try:
        return [
            (r["context"], r["context_model"])
            for r in conn.execute(
                "SELECT context, context_model FROM chunks WHERE artifact_id = ? ORDER BY ordinal",
                (aid,),
            )
        ]
    finally:
        conn.close()


def test_each_chunk_gets_its_context(store, monkeypatch):
    provider = _patch(
        monkeypatch,
        {
            "contexts": [
                {"index": 1, "context": "From a field guide; the part on spotting tracks."},
                {"index": 2, "context": "Same guide, on reading droppings."},
            ]
        },
    )
    aid = _artifact(["Look for the split hoof.", "Pellets mean a deer passed."])

    assert _generate(aid) == (2, None)
    assert _contexts(aid) == [
        ("From a field guide; the part on spotting tracks.", "ctx-model"),
        ("Same guide, on reading droppings.", "ctx-model"),
    ]
    assert len(provider.calls) == 1 and "[2] Pellets mean a deer passed." in provider.calls[0]


def test_missing_or_overlong_contexts_are_dropped(store, monkeypatch):
    _patch(
        monkeypatch,
        {"contexts": [{"index": 2, "context": "word " * 60}, {"index": 9, "context": "stray"}]},
    )
    aid = _artifact(["one", "two"])

    assert _generate(aid) == (0, None)
    assert _contexts(aid) == [(None, None), (None, None)]


def test_single_chunk_and_secret_flagged_artifacts_make_no_call(store, monkeypatch):
    provider = _patch(monkeypatch, {"contexts": []})

    assert _generate(_artifact(["only one chunk"])) == (0, None)
    assert _generate(_artifact(["a", "b"], status="text_only")) == (0, None)
    assert provider.calls == []


def test_many_chunks_are_batched(store, monkeypatch):
    provider = _patch(monkeypatch, {"contexts": []})
    _generate(_artifact([f"chunk {i}" for i in range(context_mod.BATCH + 1)]))
    assert len(provider.calls) == 2


def test_a_model_failure_leaves_plain_chunks(store, monkeypatch):
    _patch(monkeypatch, RuntimeError("model down"))
    aid = _artifact(["one", "two"])

    count, error = _generate(aid)

    assert count == 0 and "model down" in error
    assert _contexts(aid) == [(None, None), (None, None)]


def test_context_is_embedded_and_keyword_indexed_but_not_trigram():
    from enqueue.index.store_sqlite import _chunk_entries

    row = {"title": "Guide", "text": "Pellets mean a deer passed.", "context": "On droppings."}

    embed, (fts_title, fts_text), tri = _chunk_entries(_Row(row))

    assert "On droppings." in embed and "Pellets" in embed
    assert fts_title == "Guide" and fts_text.startswith("On droppings.")
    assert tri == "Pellets mean a deer passed."
    plain = _chunk_entries(_Row({**row, "context": None}))
    assert plain[1][1] == plain[2] == "Pellets mean a deer passed."


class _Row(dict):
    """A dict that answers `keys()` and `[]` like sqlite3.Row."""


@pytest.fixture
def sqlite_store(store, monkeypatch):
    from enqueue import config
    from enqueue.index.store import get_store

    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    s = get_store()
    s.ensure()
    yield s
    get_store.cache_clear()


def test_an_exact_phrase_only_in_the_context_is_not_an_exact_hit(sqlite_store):
    from enqueue.retrieve.candidates import _exact_phrase_hits

    aid = _artifact(["Pellets mean a deer passed.", "Tracks in the snow."])
    with db.transaction() as conn:
        conn.execute(
            "UPDATE chunks SET context = 'about reading droppings' WHERE id = ?", (f"{aid}-0",)
        )
    sqlite_store.index_artifact(aid)

    assert _exact_phrase_hits("reading droppings", 10) == []
    assert [h["artifact_id"] for h in _exact_phrase_hits("deer passed", 10)] == [aid]


def test_ingest_reindexes_after_writing_contexts(store, quiet_queue, monkeypatch):
    from enqueue import notes
    from enqueue.index import store as store_mod
    from enqueue.ingest import queue

    indexed: list[str] = []

    class _Store:
        CHUNKS, FACETS, ENTITIES = "chunks", "facets", "entities"

        def index_artifact(self, aid):
            indexed.append(aid)
            return 1

        def drop_artifact(self, *a):
            pass

    monkeypatch.setattr(store_mod, "get_store", lambda: _Store())
    monkeypatch.setattr(queue, "_facet_artifact", lambda aid: 0)
    monkeypatch.setattr(queue, "_entities_artifact", lambda aid: 0)
    monkeypatch.setattr(queue, "_context_artifact", lambda aid: 2)
    body = "\n\n".join(f"## Part {i}\n\n" + ("word " * 200) for i in range(3))
    aid = notes.create(body=body)["artifact"]["id"]

    result = queue.process(aid)

    assert result["chunks"] > 1 and result["contexts"] == 2
    assert indexed == [aid, aid]
