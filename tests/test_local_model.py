"""A model on this Mac through Ollama: finding it, downloading a model, choosing it, and
what choosing it lets local-only items do. A real HTTP server plays Ollama."""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from enqueue import catalog, local_model, settings
from enqueue.providers.base import LocalOnly, get_provider, local_model_on


@contextmanager
def _ollama(held: list[dict], pull_lines: list[dict] | None = None):
    """A fake Ollama: /api/version, /api/tags, /api/show and a streaming /api/pull."""

    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: bytes, kind="application/json"):
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802 - the name is BaseHTTPRequestHandler's
            if self.path == "/api/version":
                return self._send(b'{"version":"0.12.0"}')
            self._send(
                json.dumps(
                    {"models": [{"name": m["name"], "size": 3 * 2**30} for m in held]}
                ).encode()
            )

        def do_POST(self):  # noqa: N802
            size = int(self.headers.get("Content-Length") or 0)
            asked = json.loads(self.rfile.read(size) or b"{}")
            if self.path == "/api/show":
                m = next(m for m in held if m["name"] == asked["model"])
                return self._send(json.dumps({"capabilities": m["caps"]}).encode())
            body = b"\n".join(json.dumps(line).encode() for line in pull_lines or []) + b"\n"
            held.append({"name": asked["model"], "caps": ["completion"]})
            self._send(body, "application/x-ndjson")

        def log_message(self, format, *args):  # noqa: ARG002
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()


def test_status_says_when_ollama_is_missing(monkeypatch):
    monkeypatch.setattr(local_model, "BASE", "http://127.0.0.1:9")
    monkeypatch.setattr(local_model, "installed", lambda: False)
    s = local_model.status()
    assert not s["installed"] and not s["running"] and s["models"] == []


def test_status_lists_the_models_that_answer(monkeypatch):
    held = [
        {"name": "gemma3:4b", "caps": ["completion", "vision"]},
        {"name": "nomic-embed-text", "caps": ["embedding"]},
    ]
    with _ollama(held) as url:
        monkeypatch.setattr(local_model, "BASE", url)
        s = local_model.status()
    assert s["running"]
    assert s["models"] == [{"name": "gemma3:4b", "size": 3 * 2**30, "vision": True}]


def test_the_recommended_model_fits_the_memory():
    assert local_model.recommended(8) == "gemma3:4b"
    assert local_model.recommended(16) == "qwen3:8b"
    assert local_model.recommended(64) == "gemma3:12b"
    assert local_model.recommended(4) == "gemma3:4b"


def test_a_download_reports_its_progress_and_finishes(store, monkeypatch):
    lines = [
        {"status": "pulling manifest"},
        {"status": "downloading", "total": 100, "completed": 40},
        {"status": "downloading", "total": 100, "completed": 100},
        {"status": "success"},
    ]
    held: list[dict] = []
    with _ollama(held, lines) as url:
        monkeypatch.setattr(local_model, "BASE", url)
        local_model.pull("gemma3:4b")
        for _ in range(100):
            if local_model.pull_state()["state"] != "pulling":
                break
            time.sleep(0.02)
    state = local_model.pull_state()
    assert state["state"] == "done" and state["completed"] == 100 == state["total"]
    assert [m["name"] for m in held] == ["gemma3:4b"]


def test_only_offered_models_are_downloaded():
    with pytest.raises(ValueError):
        local_model.pull("some/other-model")


def test_a_failed_download_says_why(store, monkeypatch):
    with _ollama([], [{"error": "disk full"}]) as url:
        monkeypatch.setattr(local_model, "BASE", url)
        local_model.pull("qwen3:8b")
        for _ in range(100):
            if local_model.pull_state()["state"] != "pulling":
                break
            time.sleep(0.02)
    assert local_model.pull_state()["state"] == "failed"
    assert local_model.pull_state()["error"] == "disk full"


def test_the_model_list_and_suggestion_come_from_ollama(monkeypatch):
    held = [
        {"name": "gemma3:4b", "caps": ["completion", "vision"]},
        {"name": "qwen3:8b", "caps": ["completion"]},
    ]
    with _ollama(held) as url:
        monkeypatch.setattr(local_model, "BASE", url)
        listing = catalog.cached("local")
        assert listing["chat"] == ["gemma3:4b", "qwen3:8b"]
        assert catalog.suggest("local", listing) == ("qwen3:8b", "gemma3:4b")
        assert catalog.unknown("local", "llama9:1b")
    monkeypatch.setattr(local_model, "BASE", "http://127.0.0.1:9")
    assert catalog.cached("local") is None


def test_local_only_items_use_a_model_on_this_mac_only(store):
    settings.update({"llm_backend": "openrouter", "llm_model": "m"})
    assert not local_model_on()
    with pytest.raises(LocalOnly):
        get_provider(local_only=True)
    settings.update({"llm_backend": "local", "llm_model": "gemma3:4b"})
    assert local_model_on()
    p = get_provider(local_only=True)
    assert p.base_url == "http://127.0.0.1:11434/v1" and p.model == "gemma3:4b"


def test_a_local_only_note_is_summarized_only_by_a_model_on_this_mac(store):
    from enqueue import db, notes
    from enqueue.ingest import facets

    note = notes.create(body="private thoughts " * 20, local_only=True)
    conn = db.get_conn()
    try:
        settings.update({"llm_backend": "openrouter", "llm_model": "m"})
        assert facets.summary_off(conn, note["artifact"]["id"])
        settings.update({"llm_backend": "local", "llm_model": "gemma3:4b"})
        assert not facets.summary_off(conn, note["artifact"]["id"])
    finally:
        conn.close()


def test_the_phone_is_given_the_included_assistant(store):
    from enqueue import included_ai
    from enqueue.sync import client

    settings.update({"llm_backend": "local", "llm_model": "gemma3:4b"})
    s = client.phone_settings()
    assert s["llm_backend"] == "enqueue" and s["llm_model"] == included_ai.DEFAULT_MODEL
    assert s["llm_api_key"] == ""
