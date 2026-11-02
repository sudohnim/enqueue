"""Error reports: where the code broke, never the library's words, never when off."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from enqueue import config, settings, telemetry


@pytest.fixture
def sent(store, monkeypatch):
    out: list[dict] = []
    monkeypatch.setattr(config, "POSTHOG_KEY", "phc_test")
    monkeypatch.setattr(telemetry, "_send", out.append)
    monkeypatch.setattr(telemetry, "_seen", {})
    monkeypatch.setattr(telemetry, "_sent_at", [])

    class Now:  # run the sending thread inline
        def __init__(self, target=None, args=(), **_):
            self.go = lambda: target(*args)

        def start(self):
            self.go()

    monkeypatch.setattr(telemetry.threading, "Thread", Now)
    # This file stands in for Enqueue's own code, whose frames are the ones kept.
    monkeypatch.setattr(telemetry, "PACKAGE", Path(__file__).resolve().parent)
    return out


def _boom():
    raise ValueError("could not parse 'My secret plan' from https://x.com/a for a@b.com")


def test_a_logged_error_is_reported_without_its_words(sent):
    telemetry.install()
    try:
        _boom()
    except ValueError:
        logging.getLogger("enqueue.ingest.queue").exception("failed for note 'Tax plan'")
    [event] = sent
    assert event["event"] == "$exception"
    props = event["properties"]
    [exc] = props["$exception_list"]
    assert exc["type"] == "ValueError"
    assert "secret" not in str(event) and "Tax plan" not in str(event)
    assert "x.com" not in exc["value"] and "a@b.com" not in exc["value"]
    frame = exc["stacktrace"]["frames"][-1]
    assert frame["function"] == "_boom" and frame["filename"] == "tests/test_telemetry.py"
    assert props["area"] == "ingest.queue"
    assert props["$process_person_profile"] is False and props["$geoip_disable"] is True
    assert "vars" not in str(frame) and "context_line" not in str(frame)


def test_the_same_error_from_the_same_place_is_sent_once(sent):
    for _ in range(3):
        telemetry.report("sync", "KeyError", "x", [{"filename": "a.py", "lineno": 3}])
    assert len(sent) == 1


def test_a_model_services_failure_is_not_a_bug(sent):
    from enqueue.providers.base import ProviderError

    telemetry.report_exception("ask", ProviderError("the endpoint is rate limiting"))
    assert sent == []


def test_nothing_leaves_when_switched_off_or_without_a_key(sent, monkeypatch):
    settings.update({"telemetry": "off"})
    telemetry.report("sync", "KeyError", "x")
    settings.update({"telemetry": "on"})
    monkeypatch.setattr(config, "POSTHOG_KEY", "")
    telemetry.report("sync", "KeyError", "y")
    assert sent == []


def test_a_page_error_is_sent_on_from_the_engine(sent):
    from fastapi.testclient import TestClient

    from enqueue.api.app import create_app

    TestClient(create_app()).post(
        "/report",
        json={
            "kind": "TypeError",
            "message": "x is undefined near 'Grocery list'",
            "source": "http://127.0.0.1:8787/static/js/home.js",
            "line": 42,
        },
    )
    [event] = sent
    [exc] = event["properties"]["$exception_list"]
    assert exc["type"] == "TypeError" and "Grocery" not in exc["value"]
    assert exc["stacktrace"]["frames"][0]["filename"] == "static/js/home.js"


def test_the_phone_follows_the_macs_switch(store):
    from enqueue.sync import client

    settings.update({"telemetry": "off"})
    assert client.phone_settings()["telemetry"] == "off"
