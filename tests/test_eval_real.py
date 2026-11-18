"""Opens and the real-search eval built from them."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from enqueue import db, eval_real, opens


@pytest.fixture
def library(store, monkeypatch):
    """Three notes, chunked and indexed, with the gray-zone judge keeping everything."""
    from enqueue import config
    from enqueue.index.store import get_store
    from enqueue.ingest.chunk import chunk_artifact
    from enqueue.retrieve import candidates as cand

    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    monkeypatch.setattr(
        cand, "judge_gray_zone", lambda query, hits: {h["artifact_id"] for h in hits}
    )
    notes = {
        "kiln": ("Kiln firing schedule", "Cone six bisque, then a slow glaze firing."),
        "sourdough": ("Sourdough starter", "Feed the starter twice a day with rye flour."),
        "budget": ("Household budget", "Rent, groceries and the car payment each month."),
    }
    with db.transaction() as conn:
        for aid, (title, body) in notes.items():
            conn.execute(
                "INSERT INTO artifacts (id, kind, title, body, content_hash, status, created_at,"
                " updated_at) VALUES (?, 'note', ?, ?, ?, 'ok', ?, ?)",
                (aid, title, body, aid, db.now(), db.now()),
            )
            chunk_artifact(conn, aid)
    get_store.cache_clear()
    s = get_store()
    s.ensure()
    s.upsert_chunks()
    yield s
    get_store.cache_clear()


def _opens() -> list[dict]:
    conn = db.get_conn()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM opens ORDER BY id").fetchall()]
    finally:
        conn.close()


def test_the_opened_endpoint_records_search_opens_with_query_and_rank(library):
    from enqueue.api.app import create_app

    client = TestClient(create_app())
    assert (
        client.post(
            "/artifacts/kiln/opened", json={"source": "search", "query": " kiln ", "rank": 2}
        ).status_code
        == 204
    )
    client.post("/artifacts/kiln/opened", json={"source": "wall", "query": "ignored", "rank": 5})
    client.post("/artifacts/kiln/opened", json={"source": "made-up"})

    rows = _opens()
    assert [(r["source"], r["query"], r["rank"]) for r in rows] == [
        ("search", "kiln", 2),
        ("wall", None, None),
        ("other", None, None),
    ]


def test_cases_group_by_query_and_skip_trashed_artifacts(library):
    from enqueue import trash

    opens.record("kiln", "search", "Kiln Firing", 1)
    opens.record("sourdough", "search", "kiln firing ", 3)
    opens.record("budget", "search", "money", 1)
    opens.record("budget", "wall")
    trash.delete("budget")

    assert eval_real.cases() == [{"query": "kiln firing", "expect": ["sourdough", "kiln"]}]


def test_run_scores_each_case_against_live_search(library):
    opens.record("kiln", "search", "kiln firing schedule", 1)
    opens.record("sourdough", "search", "car payment", 1)  # opened, but search finds budget

    report = eval_real.run()

    by_query = {r["query"]: r for r in report["results"]}
    assert by_query["kiln firing schedule"]["pass"]
    assert by_query["kiln firing schedule"]["rank"] == 1
    assert report["total"] == 2
    assert report["pass"] == 1 + by_query["car payment"]["pass"]


def test_check_stores_a_baseline_and_reports_lost_queries(library):
    opens.record("kiln", "search", "kiln firing schedule", 1)

    first = eval_real.check(update_baseline=True)
    assert first["baseline"] is None and first["lost"] == []
    stored = json.loads(eval_real.baseline_path().read_text())
    assert stored["pass"] == 1

    assert eval_real.check()["lost"] == []

    now = {
        "results": [
            {"query": "kiln firing schedule", "pass": False},
            {"query": "new", "pass": False},
        ]
    }
    assert eval_real.lost(now, stored) == ["kiln firing schedule"]


def test_purge_removes_an_artifacts_opens(library):
    from enqueue import trash

    opens.record("kiln", "search", "kiln", 1)
    trash.delete("kiln")
    trash.purge("kiln")

    assert _opens() == []


BASE = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _search(conn, query, at, hits=None, source="search"):
    conn.execute(
        "INSERT INTO searches (query, hits, loose, source, created_at) VALUES (?, ?, 0, ?, ?)",
        (query, json.dumps(hits or []), source, at.isoformat()),
    )


def _open(conn, query, at, artifact_id="art1", source="search"):
    conn.execute(
        "INSERT INTO opens (artifact_id, source, query, rank, opened_at) VALUES (?, ?, ?, 1, ?)",
        (artifact_id, source, query, at.isoformat()),
    )


def test_reformulated_search_becomes_a_case(store):
    conn = db.get_conn()
    try:
        _search(conn, "president", BASE, hits=["x"])
        _search(conn, "taleb", BASE + timedelta(seconds=30), hits=["art1"])
        _open(conn, "taleb", BASE + timedelta(seconds=40), "art1")
        assert eval_real.reformulated(conn) == [{"query": "president", "expect": ["art1"]}]
    finally:
        conn.close()


def test_late_reformulation_gives_no_case(store):
    conn = db.get_conn()
    try:
        _search(conn, "president", BASE, hits=["x"])
        _search(conn, "taleb", BASE + timedelta(minutes=5), hits=["art1"])
        _open(conn, "taleb", BASE + timedelta(minutes=5, seconds=10), "art1")
        assert eval_real.reformulated(conn) == []
    finally:
        conn.close()


def test_search_with_hits_and_no_open_is_abandoned(store):
    conn = db.get_conn()
    try:
        _search(conn, "lonely", BASE, hits=["x"])
        assert eval_real.abandoned(conn) == ["lonely"]
    finally:
        conn.close()
