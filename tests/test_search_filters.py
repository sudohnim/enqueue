"""Filters read from the words of a search: kinds and times, applied exactly."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from enqueue import db
from enqueue.retrieve import filters

NOW = datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc)  # a Tuesday


def _parse(q):
    return filters.parse(q, NOW)


@pytest.mark.parametrize(
    "query, text, kinds, since, until, label",
    [
        (
            "that pdf from last month about kilns",
            "kilns",
            {"pdf"},
            "2026-08-01T00:00:00+00:00",
            "2026-09-01T00:00:00+00:00",
            "PDFs · saved last month",
        ),
        ("screenshots from yesterday", "", {"image"}, "2026-09-28", "2026-09-29", None),
        ("articles on pricing this week", "pricing", {"link"}, "2026-09-28", None, None),
        ("glaze notes I saved in march", "glaze notes", set(), "2026-03-01", "2026-04-01", None),
        ("budget in december", "budget", set(), "2025-12-01", "2026-01-01", None),
        ("trip photos from 2024", "trip", {"image"}, "2024-01-01", "2025-01-01", None),
        ("kiln log the last 10 days", "kiln log", set(), "2026-09-19", None, None),
        ("recipes in may", "recipes", set(), "2026-05-01", "2026-06-01", None),
    ],
)
def test_kinds_and_times_are_pulled_out(query, text, kinds, since, until, label):
    rest, f = _parse(query)
    assert rest == text
    assert f.kinds == kinds
    assert (f.since or "").startswith(since)
    assert (f.until or "").startswith(until) if until else f.until is None
    if label:
        assert f.label == label


@pytest.mark.parametrize(
    "query",
    [
        "my notes on stoicism",  # "note" is never a kind
        "what may happen to the kiln",  # "may" the verb
    ],
)
def test_ordinary_searches_have_no_filter(query):
    rest, f = _parse(query)
    assert not f
    assert rest == query


def _note(aid, kind, days_old, title):
    at = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, status, created_at,"
            " updated_at) VALUES (?, ?, ?, ?, ?, 'ok', ?, ?)",
            (aid, kind, title, "x" if kind == "note" else None, aid, at, at),
        )


def test_search_applies_the_filters_and_an_empty_match_is_empty(store, monkeypatch):
    from enqueue.retrieve import candidates as cand

    _note("old-pdf", "pdf", 60, "Kiln manual")
    _note("new-pdf", "pdf", 0, "Kiln schedule")
    _note("new-note", "note", 0, "Kiln thoughts")
    seen = []

    def hybrid(q, limit, lifts=None):
        seen.append(q)
        return [
            {"artifact_id": a, "score": 1.0, "had_lexical_hit": True}
            for a in ("old-pdf", "new-pdf", "new-note")
        ]

    monkeypatch.setattr(cand, "_hybrid_results", hybrid)

    hits = cand.search_results("kiln pdfs from this week")
    assert [h["artifact_id"] for h in hits] == ["new-pdf"]
    assert seen == ["kiln"]

    listing = cand.search_results("pdfs")  # a filter alone lists what it allows
    assert {h["artifact_id"] for h in listing} == {"old-pdf", "new-pdf"}

    assert cand.search_results("screenshots") == []  # no images: nothing, not everything
    assert cand.search_results("#no-such-tag") == []


def test_the_endpoint_reports_what_it_understood(store, monkeypatch):
    from fastapi.testclient import TestClient

    from enqueue.api import search as search_api
    from enqueue.api.app import create_app
    from enqueue.index import bootstrap

    monkeypatch.setattr(bootstrap, "search_allowed", lambda: True)
    monkeypatch.setattr(search_api, "search_results", lambda q, limit=20: [])
    client = TestClient(create_app())
    body = client.get("/search", params={"q": "pdfs from last week"}).json()
    assert body["filters"] == "PDFs · saved last week"
    assert client.get("/search", params={"q": '"pdfs from last week"'}).json()["filters"] == ""
