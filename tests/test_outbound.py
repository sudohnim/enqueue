"""What went to remote models shows in the Activity log, without the text (outbound.py)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from enqueue import db, events, outbound
from enqueue.providers.ollama import OpenAICompatibleProvider


class _Reply(BaseModel):
    ok: bool = True


class Answer(_Reply):
    """Named like the chat answer schema, so it is labelled "chat answers"."""


def _offline(provider):
    provider._instructor = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: _Reply()))
    )
    return provider


@pytest.fixture(autouse=True)
def _clean():
    outbound.flush()
    yield
    outbound.flush()


def _sent():
    return [e for e in events.recent(50) if e["kind"] == "model.sent"]


def test_remote_calls_are_added_up_into_one_row_per_service(store):
    remote = _offline(OpenAICompatibleProvider(model="kimi", base_url="https://opencode.ai/v1"))
    remote.complete(system="Summarize.", user="A" * 1000, response_model=Answer)
    remote.complete(system="Summarize.", user="password = hunter2hunter2", response_model=Answer)

    outbound.flush()

    [row] = _sent()
    assert row["data"]["host"] == "opencode.ai"
    assert row["data"]["calls"] == 2
    assert row["data"]["redacted"] == 1
    assert row["data"]["chars"] > 1000
    assert row["data"]["by"][0]["purpose"] == "chat answers"
    assert "hunter2" not in str(row)  # counts only, never the text
    assert row["detail"].startswith("opencode.ai: 2 calls")


def test_a_local_model_leaves_nothing_to_record(store):
    local = _offline(OpenAICompatibleProvider(model="llama", base_url="http://127.0.0.1:11434/v1"))
    local.complete(system="Summarize.", user="private words", response_model=Answer)

    outbound.flush()

    assert _sent() == []


def test_two_flushes_on_one_day_add_up(store):
    outbound.record("https://api.example.com/v1", "m", "Answer", 10)
    outbound.flush()
    outbound.record("https://api.example.com/v1", "m", "Answer", 5)
    outbound.flush()

    days = outbound.by_day()
    assert len(days) == 1
    assert days[0] == {
        "day": datetime.now(timezone.utc).date().isoformat(),
        "service": "api.example.com",
        "purpose": "chat answers",
        "calls": 2,
        "chars": 15,
    }


def test_old_rows_are_not_returned(store):
    old = (datetime.now(timezone.utc).date() - timedelta(days=40)).isoformat()
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO derived_values (scope, subject, attribute, value, grounded, source,"
        " model_version, created_at)"
        " VALUES ('outbound_day', ?, 'totals', ?, 1, 'engine', '', ?)",
        (f"{old}|api.example.com|chat answers", json.dumps({"calls": 1, "chars": 9}), db.now()),
    )
    conn.commit()
    conn.close()

    assert outbound.by_day() == []
