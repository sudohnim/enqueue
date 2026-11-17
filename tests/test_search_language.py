"""Natural-language search: the words that become filters, and where a word is found."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

import pytest

from enqueue import config, db, notes
from enqueue.index.store import get_store
from enqueue.retrieve import filters
from enqueue.retrieve.candidates import search_results

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_real_judge(monkeypatch):
    """No test reaches a model: keep every gray-zone hit, the fail-open path."""
    from enqueue.retrieve import candidates as cand

    class _KeepAllJudge:
        model = "test-judge"

        def complete(self, *args, **kwargs):
            return cand._GrayZoneResponse(verdicts=[])

    monkeypatch.setattr(cand, "get_provider", lambda *a, **k: _KeepAllJudge())


@pytest.fixture
def sqlite_store(store, monkeypatch):
    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    s = get_store()
    s.ensure()
    yield s
    get_store.cache_clear()


def _quiet_derived(monkeypatch):
    """Chunking and indexing are real; only the model-written layers are stubbed."""
    from enqueue.ingest import queue as ingest_queue

    monkeypatch.setattr(ingest_queue, "_facet_artifact", lambda aid: 0)
    monkeypatch.setattr(ingest_queue, "_entities_artifact", lambda aid: 0)


@pytest.mark.parametrize(
    "query, kinds, since, until, exact, must_have, must_not",
    [
        pytest.param(
            "pdfs from last month",
            {"pdf"},
            "2026-10-01T00:00:00+00:00",
            "2026-11-01T00:00:00+00:00",
            "",
            [],
            [],
            id="pdfs-from-last-month",
        ),
        pytest.param(
            "the article about pricing I saved last week",
            {"link"},
            "2026-11-09T00:00:00+00:00",
            "2026-11-16T00:00:00+00:00",
            None,
            ["pricing"],
            [],
            id="article-last-week",
        ),
        pytest.param(
            "screenshots this week",
            {"image"},
            "2026-11-16T00:00:00+00:00",
            None,
            "",
            [],
            [],
            id="screenshots-this-week",
        ),
        pytest.param(
            "notes about hiring",
            set(),
            None,
            None,
            "notes about hiring",
            [],
            [],
            id="notes-about-hiring",
        ),
        pytest.param(
            "receipts in March",
            set(),
            "2026-03-01T00:00:00+00:00",
            "2026-04-01T00:00:00+00:00",
            None,
            ["receipts"],
            [],
            id="receipts-in-march",
        ),
        pytest.param(
            "photos from 2024",
            {"image"},
            "2024-01-01T00:00:00+00:00",
            "2025-01-01T00:00:00+00:00",
            "",
            [],
            [],
            id="photos-from-2024",
        ),
        pytest.param(
            "pdf about tax in the last 30 days",
            {"pdf"},
            "2026-10-17T00:00:00+00:00",
            None,
            None,
            ["tax"],
            [],
            id="pdf-last-30-days",
        ),
        pytest.param(
            "what did I save yesterday",
            set(),
            "2026-11-15T00:00:00+00:00",
            "2026-11-16T00:00:00+00:00",
            None,
            [],
            ["yesterday"],
            id="what-did-i-save-yesterday",
        ),
    ],
)
def test_language_filters(query, kinds, since, until, exact, must_have, must_not):
    text, found = filters.parse(query, now=NOW)
    assert found.kinds == kinds
    assert found.since == since
    assert found.until == until
    if exact is not None:
        assert text == exact
    for word in must_have:
        assert word in text
    for word in must_not:
        assert word not in text


def test_a_quoted_phrase_is_not_a_time_filter(sqlite_store, quiet_queue, monkeypatch):
    from enqueue.ingest import queue as ingest_queue

    _quiet_derived(monkeypatch)
    aid = notes.create(body="We spoke about the garden last week.")["artifact"]["id"]
    with db.transaction() as conn:
        conn.execute(
            "UPDATE artifacts SET created_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
            (aid,),
        )
    ingest_queue.process(aid)

    hits = search_results('"last week"')
    assert aid in [h["artifact_id"] for h in hits]


def test_a_word_in_a_note_body_is_found(sqlite_store, quiet_queue, monkeypatch):
    from enqueue.ingest import queue as ingest_queue

    _quiet_derived(monkeypatch)
    aid = notes.create(body="The marmalade recipe uses Seville oranges.")["artifact"]["id"]
    ingest_queue.process(aid)

    hits = search_results("marmalade")
    assert aid in [h["artifact_id"] for h in hits]


def test_a_word_in_pdf_page_text_is_found(sqlite_store, quiet_queue, monkeypatch):
    from enqueue import capture
    from enqueue.ingest import queue as ingest_queue

    _quiet_derived(monkeypatch)
    # The page text is already there; extraction must not replace it from a blob.
    monkeypatch.setattr(capture, "extract_text", lambda aid: 1)
    aid = str(uuid.uuid4())
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, status, created_at,"
            " updated_at) VALUES (?, 'pdf', 'A field report', NULL, ?, 'ok', ?, ?)",
            (aid, aid + "_hash", db.now(), db.now()),
        )
        conn.execute(
            "INSERT INTO page_text (artifact_id, page, text, extractor) VALUES (?, 0, ?, 'test')",
            (aid, "The sample was crushed with a quartzite mortar and sieved."),
        )
    ingest_queue.process(aid)

    hits = search_results("quartzite")
    assert aid in [h["artifact_id"] for h in hits]
