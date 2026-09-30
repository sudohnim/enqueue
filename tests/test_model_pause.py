"""The engine-wide pause on model calls after a provider usage limit (providers/pause.py)."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from enqueue import db, events, notes
from enqueue.ingest import facets as facets_mod
from enqueue.ingest import queue as q
from enqueue.ingest.source import Owed
from enqueue.providers import pause
from enqueue.providers.base import ProviderError, is_transient
from enqueue.providers.ollama import OpenAICompatibleProvider
from enqueue.schemas import Answer


@pytest.fixture(autouse=True)
def _no_pause():
    pause.reset()
    yield
    pause.reset()


@contextmanager
def _usage_limited(retry_after="276"):
    """A provider that answers every call the way OpenCode Go does at its 5-hour limit."""
    hits: list[int] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - the name is BaseHTTPRequestHandler's
            self.rfile.read(int(self.headers["Content-Length"]))
            hits.append(1)
            raw = json.dumps(
                {
                    "type": "error",
                    "error": {"type": "GoUsageLimitError", "message": "Go usage limit exceeded"},
                    "metadata": {"limitName": "5 hour"},
                }
            ).encode()
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            if retry_after is not None:
                self.send_header("retry-after", retry_after)
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format, *args):  # noqa: ARG002 - silence the test server
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", hits
    finally:
        server.shutdown()
        server.server_close()


def test_a_usage_limit_pauses_every_call_until_retry_after(store):
    with _usage_limited("276") as (base_url, hits):
        provider = OpenAICompatibleProvider(model="some-model", base_url=base_url)
        with pytest.raises(ProviderError):
            provider.complete("s", "u", Answer, max_retries=1)
        first = len(hits)
        assert first >= 1

        end = pause.until()
        assert end is not None
        left = (end - datetime.now(timezone.utc)).total_seconds()
        assert 260 < left <= 276
        assert pause.status()["reason"] == "OpenCode Go usage limit (5 hour)"

        # While paused, a call fails at once without reaching the provider, and reads
        # as transient so the work stays owed.
        with pytest.raises(pause.ModelPaused) as caught:
            provider.complete("s", "u", Answer, max_retries=1)
        assert len(hits) == first
        assert is_transient(caught.value)
        assert "resume at" in str(caught.value)

    # One activity row for the pause, not one per refused call.
    paused = [e for e in events.recent(50) if e["kind"] == "model.paused"]
    assert len(paused) == 1
    assert paused[0]["data"]["retry_after_seconds"] == 276


def test_without_retry_after_the_pause_uses_the_default_wait(store):
    with _usage_limited(None) as (base_url, _hits):
        provider = OpenAICompatibleProvider(model="some-model", base_url=base_url)
        with pytest.raises(ProviderError):
            provider.complete("s", "u", Answer, max_retries=1)
    left = (pause.until() - datetime.now(timezone.utc)).total_seconds()
    assert pause.DEFAULT_WAIT - 20 < left <= pause.DEFAULT_WAIT


def test_a_non_rate_limit_error_does_not_pause():
    assert pause.trip_from(RuntimeError("boom")) is False
    assert not pause.active()
    pause.check()  # no raise


def test_a_paused_retry_is_due_at_the_pause_end_without_counting_an_attempt(
    store, quiet_queue, monkeypatch
):
    aid = notes.create(body="a body long enough to earn a summary from the model")["artifact"]["id"]
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO facet_retry (artifact_id, attempts, next_at, last_error)"
            " VALUES (?, 3, '2000-01-01T00:00:00+00:00', 'APIError: 500')",
            (aid,),
        )
    end = datetime.now(timezone.utc) + timedelta(seconds=276)
    monkeypatch.setattr(pause, "until", lambda: end)
    monkeypatch.setattr(
        facets_mod,
        "generate_for_artifact",
        lambda conn, _id: (0, Owed("ModelPaused: Paused: OpenCode Go usage limit")),
    )
    q._facet_artifact(aid)

    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT attempts, next_at FROM facet_retry WHERE artifact_id = ?", (aid,)
        ).fetchone()
    finally:
        conn.close()
    assert row["attempts"] == 3
    next_at = datetime.fromisoformat(row["next_at"])
    assert end <= next_at <= end + timedelta(seconds=60)


def test_the_sweeper_waits_while_paused(store, quiet_queue, monkeypatch):
    aid = notes.create(body="a body long enough to earn a summary from the model")["artifact"]["id"]
    quiet_queue.clear()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO facet_retry (artifact_id, attempts, next_at, last_error)"
            " VALUES (?, 1, '2000-01-01T00:00:00+00:00', 'APIError: 429')",
            (aid,),
        )
    monkeypatch.setattr(pause, "active", lambda: True)
    assert q._sweep_due() == []
    monkeypatch.setattr(pause, "active", lambda: False)
    assert q._sweep_due() == [aid]


def test_a_new_api_key_lifts_the_pause_and_brings_retries_forward(store, quiet_queue):
    aid = notes.create(body="a body long enough to earn a summary from the model")["artifact"]["id"]
    later = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO facet_retry (artifact_id, attempts, next_at, last_error)"
            " VALUES (?, 1, ?, 'ModelPaused')",
            (aid, later),
        )
    pause._until = datetime.now(timezone.utc) + timedelta(hours=4)
    pause._reason = "OpenCode Go usage limit (5 hour)"
    assert pause.active()

    moved = pause.lift("new API key")

    assert moved == 1
    assert not pause.active()
    conn = db.get_conn()
    try:
        next_at = conn.execute(
            "SELECT next_at FROM facet_retry WHERE artifact_id = ?", (aid,)
        ).fetchone()["next_at"]
    finally:
        conn.close()
    assert datetime.fromisoformat(next_at) <= datetime.now(timezone.utc)
    assert [e for e in events.recent(20) if e["kind"] == "model.resumed"]


def test_changing_the_model_lifts_the_pause(store):
    from enqueue import settings

    pause._until = datetime.now(timezone.utc) + timedelta(hours=4)
    settings.update({"summarize_model": "some-other-model"})
    assert not pause.active()


def test_an_unrelated_setting_leaves_the_pause(store):
    from enqueue import settings

    pause._until = datetime.now(timezone.utc) + timedelta(hours=4)
    settings.update({"trash_days": 10})
    assert pause.active()
