"""The wall's "Reading your library" line (reading.py, GET /reading) and the refused-key
flag behind its "turned down the key" wording (providers/pause.py)."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from enqueue import db, notes, reading
from enqueue.api.admin import _summary_progress
from enqueue.ingest import queue as q
from enqueue.providers import pause
from enqueue.providers.base import ProviderError
from enqueue.providers.ollama import OpenAICompatibleProvider
from enqueue.schemas import Answer


@pytest.fixture(autouse=True)
def _no_pause():
    pause.reset()
    yield
    pause.reset()


def _notes(n: int) -> list[str]:
    return [
        notes.create(f"Note number {i} about something worth keeping.")["artifact"]["id"]
        for i in range(n)
    ]


def _summarize(ids: list[str]) -> None:
    """Give each artifact a machine summary line written from its current body."""
    with db.transaction() as conn:
        for aid in ids:
            conn.execute(
                "INSERT INTO facets (id, artifact_id, level, statement, model_version, trust,"
                " body_version) VALUES (?, ?, 1, 'A line.', 'm',  0.5,"
                " (SELECT MAX(created_at) FROM artifact_versions WHERE artifact_id = ?))",
                ("f-" + aid, aid, aid),
            )


def _owe(ids: list[str], why: str = "rate limited") -> None:
    later = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    with db.transaction() as conn:
        for aid in ids:
            conn.execute(
                "INSERT INTO facet_retry (artifact_id, attempts, next_at, last_error)"
                " VALUES (?, 1, ?, ?)",
                (aid, later, why),
            )


def test_counts_match_the_doctor(store, quiet_queue):
    ids = _notes(14)
    _summarize(ids[:4])
    got = reading.progress()
    conn = db.get_conn()
    try:
        doctor = _summary_progress(conn)
    finally:
        conn.close()
    assert (got["total"], got["done"]) == (14, 4) == (14, doctor["current"])
    assert got["remaining"] == doctor["stale"] == 10


def test_nothing_owed_shows_nothing(store, quiet_queue):
    _notes(12)
    got = reading.progress()
    assert got["state"] == "idle"
    assert got["show"] is False


def test_a_big_read_shows_while_work_is_owed(store, quiet_queue):
    ids = _notes(12)
    _owe(ids)
    got = reading.progress()
    assert got["state"] == "retrying"
    assert got["show"] is True


def test_a_few_items_are_ordinary_upkeep(store, quiet_queue):
    ids = _notes(reading.SHOW_FROM - 1)
    _owe(ids)
    assert reading.progress()["show"] is False


def test_a_note_being_written_is_not_owed_work(store, quiet_queue):
    ids = _notes(12)
    _owe(ids, q.WAITING)
    assert reading.progress()["state"] == "idle"


def test_a_busy_queue_is_reading(store, quiet_queue, monkeypatch):
    _notes(12)
    monkeypatch.setattr(q, "busy", lambda: 3)
    got = reading.progress()
    assert (got["state"], got["show"]) == ("reading", True)


def test_a_usage_limit_is_named_with_its_end(store, quiet_queue, monkeypatch):
    ids = _notes(12)
    _owe(ids)
    end = datetime.now(timezone.utc) + timedelta(minutes=20)
    monkeypatch.setattr(pause, "until", lambda: end)
    got = reading.progress()
    assert got["state"] == "paused"
    assert got["paused_until"] == end.isoformat()
    assert got["show"] is True


def test_done_hides_the_line(store, quiet_queue):
    ids = _notes(12)
    _summarize(ids)
    _owe(ids)
    got = reading.progress()
    assert got["remaining"] == 0
    assert got["show"] is False


def test_the_endpoint(store, quiet_queue):
    from fastapi.testclient import TestClient

    from enqueue.api.app import create_app

    _notes(3)
    body = TestClient(create_app()).get("/reading").json()
    assert set(body) == {"total", "done", "remaining", "state", "paused_until", "show"}
    assert body["total"] == 3


@contextmanager
def _answering(status: int, body: dict):
    """A provider that answers every call with one status and JSON body."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - the name is BaseHTTPRequestHandler's
            self.rfile.read(int(self.headers["Content-Length"]))
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format, *args):  # noqa: ARG002 - silence the test server
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()


def test_a_refused_key_is_remembered_until_lifted(store, quiet_queue):
    _notes(12)
    refused = {"error": {"type": "invalid_api_key", "message": "bad key"}}
    with _answering(401, refused) as base_url:
        provider = OpenAICompatibleProvider(model="some-model", base_url=base_url)
        with pytest.raises(ProviderError):
            provider.complete("s", "u", Answer, max_retries=1)
    assert pause.key_refused()
    got = reading.progress()
    assert (got["state"], got["show"]) == ("key", True)

    pause.lift("key changed")
    assert not pause.key_refused()


def test_an_unknown_go_model_is_not_a_refused_key(store):
    unknown = {"error": {"type": "ModelError", "message": "Model nope is not supported"}}
    with _answering(401, unknown) as base_url:
        provider = OpenAICompatibleProvider(model="nope", base_url=base_url)
        with pytest.raises(ProviderError):
            provider.complete("s", "u", Answer, max_retries=1)
    assert not pause.key_refused()


def test_a_call_that_goes_through_clears_a_refused_key():
    with pause._lock:
        pause._key_refused = True
    pause.note_success()
    assert not pause.key_refused()
