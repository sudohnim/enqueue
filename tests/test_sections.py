"""Section summaries as a search layer: written by map-reduce, indexed, searched, staled."""

from __future__ import annotations

import uuid

import pytest

from enqueue import db
from enqueue.ingest import source

FILLER = "The tutor walks through the week's material slowly and with patience. "


class _Provider:
    name = "fake"

    def __init__(self, model="ingest-model"):
        self.model = model

    def complete(self, system, user, response_model, context=None, max_retries=None):
        section = user.split("\n")[1]  # "Section i of n"
        topic = "cartography and old sea charts" if section.startswith("Section 3") else "study"
        return response_model(summary=f"This part covers {topic} ({section.lower()}).")


@pytest.fixture
def sqlite_store(store, monkeypatch):
    import enqueue.providers.base as base_mod
    from enqueue import config
    from enqueue.index.store import get_store
    from enqueue.retrieve import candidates as cand

    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    monkeypatch.setattr(base_mod, "get_provider", lambda **kw: _Provider())
    monkeypatch.setattr(cand, "get_provider", lambda **kw: _Provider())
    monkeypatch.setattr(
        cand, "judge_gray_zone", lambda query, hits: {h["artifact_id"] for h in hits}
    )
    get_store.cache_clear()
    s = get_store()
    s.ensure()
    yield s
    get_store.cache_clear()


def _long_doc() -> str:
    aid = str(uuid.uuid4())
    body = "\n\n".join(f"Week {i}. " + FILLER * 40 for i in range(40))
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, status, created_at,"
            " updated_at) VALUES (?, 'note', 'Course notes', ?, ?, 'ok', ?, ?)",
            (aid, body, aid, db.now(), db.now()),
        )
    return aid


def _read(aid):
    conn = db.get_conn()
    try:
        return source.ingest_text(conn, aid)
    finally:
        conn.commit()
        conn.close()


def _sections(aid):
    conn = db.get_conn()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, ordinal, summary FROM sections WHERE artifact_id = ? ORDER BY ordinal",
                (aid,),
            )
        ]
    finally:
        conn.close()


def test_map_reduce_writes_sections_and_rereading_keeps_them(sqlite_store):
    aid = _long_doc()

    _read(aid)
    first = _sections(aid)
    _read(aid)  # facets, entities and contexts each read the document

    assert len(first) > 3
    assert first[2]["summary"].startswith("This part covers cartography")
    assert _sections(aid) == first  # unchanged text keeps its rows, so its index holds


def test_a_long_document_is_found_by_what_one_section_is_about(sqlite_store):
    from enqueue.retrieve.candidates import search_results

    aid = _long_doc()
    _read(aid)
    assert sqlite_store.index_sections_artifact(aid) == len(_sections(aid))

    hits = search_results("cartography sea charts")

    assert hits and hits[0]["artifact_id"] == aid
    assert hits[0]["why"] == "section 3"


def test_sections_from_another_model_are_ignored(sqlite_store, monkeypatch):
    import enqueue.providers.base as base_mod
    from enqueue.retrieve import candidates as cand

    aid = _long_doc()
    _read(aid)
    sqlite_store.index_sections_artifact(aid)
    newer = _Provider(model="a-newer-model")
    monkeypatch.setattr(base_mod, "get_provider", lambda **kw: newer)
    monkeypatch.setattr(cand, "get_provider", lambda **kw: newer)

    assert cand.search_results("cartography sea charts") == []


def test_chat_pulls_the_passage_from_that_part_of_the_document(sqlite_store):
    from enqueue import chats
    from enqueue.ingest.chunk import chunk_artifact

    aid = _long_doc()
    with db.transaction() as conn:
        chunk_artifact(conn, aid)
    _read(aid)
    sqlite_store.index_sections_artifact(aid)

    found = chats.passages("cartography sea charts", "library", None)

    section_hits = [p for p in found if p.get("why", "").startswith("section")]
    assert section_hits, found
    n_sections = len(_sections(aid))
    week = int(section_hits[0]["text"].split("Week ")[1].split(".")[0])
    assert 2 / n_sections <= (week + 1) / 40 <= 3 / n_sections + 0.1


def test_purge_removes_sections(sqlite_store):
    from enqueue import trash

    aid = _long_doc()
    _read(aid)
    sqlite_store.index_sections_artifact(aid)
    trash.delete(aid)
    trash.purge(aid)

    assert _sections(aid) == []
    assert sqlite_store.counts()["sections"] == 0
