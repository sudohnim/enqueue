"""K.11: images get a vision description at ingest, and the facet gate admits them.

The vision model call is faked everywhere: what is under test is the routing, the
stored description, the degrade path, and the gate - not a particular model.
"""

from __future__ import annotations

import hashlib
import uuid
from types import SimpleNamespace

import pytest

from enqueue import config, db

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class FakeVision:
    """A vision provider that answers without any model."""

    model = "fake-vision"

    def __init__(self, text: str):
        self._text = text

    def complete(self, *args, **kwargs):  # pragma: no cover - vision has no complete
        raise AssertionError("the vision provider is never asked for structured text")

    def describe_image(self, image: bytes, mime: str) -> str:
        return self._text


def _seed_image(tmp_path, local_only=0, body=None, status="text_only", kind="image"):
    """An image artifact row plus its blob, bypassing the queue."""
    artifact_id = str(uuid.uuid4())
    data = PNG + artifact_id.encode()
    digest = hashlib.sha256(data).hexdigest()
    blob = config.BLOB_DIR / digest
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(data)
    now = "2024-01-01T00:00:00+00:00"
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, mime, filename,"
            " created_at, updated_at, local_only, status)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                artifact_id,
                kind,
                "A capture",
                body,
                digest,
                "image/png",
                "capture.png",
                now,
                now,
                local_only,
                status,
            ),
        )
    return artifact_id


def _fake_vision(monkeypatch, text="A red bicycle leaning against a brick wall."):
    """Point the ingest describe step at a fake vision provider, returning the
    local_only flag it was asked with."""
    seen = {}

    def _provider(local_only=False):
        seen["local_only"] = local_only
        return FakeVision(text)

    from enqueue.providers import base as providers_base

    monkeypatch.setattr(providers_base, "get_vision_provider", _provider)
    return seen


def _quiet_derived(monkeypatch):
    """No facet/entity model calls, and a store that never embeds."""
    from enqueue.ingest import queue as ingest_queue

    monkeypatch.setattr(ingest_queue, "_facet_artifact", lambda aid: 0)
    monkeypatch.setattr(ingest_queue, "_entities_artifact", lambda aid: 0)

    class FakeStore:
        CHUNKS = "chunks"
        FACETS = "facets"
        ENTITIES = "entities"

        def __init__(self):
            self.indexed = []

        def index_artifact(self, artifact_id):
            self.indexed.append(artifact_id)
            return 1

        def drop_artifact(self, *args):
            pass

    from enqueue.index import store as store_mod

    fake = FakeStore()
    monkeypatch.setattr(store_mod, "get_store", lambda *a, **k: fake)
    return fake


class TestDescribeAtIngest:
    def test_image_gets_a_searchable_description(self, store, quiet_queue, monkeypatch):
        from enqueue.ingest import queue as ingest_queue

        artifact_id = _seed_image(store)
        _fake_vision(monkeypatch)
        fake_store = _quiet_derived(monkeypatch)

        result = ingest_queue.process(artifact_id)

        assert result["described"]  # the description landed as the body
        conn = db.get_conn()
        try:
            row = conn.execute(
                "SELECT body, status FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
        finally:
            conn.close()
        assert "red bicycle" in row["body"]
        assert row["status"] == "ok"
        # The description flows through the pipeline like any other text.
        assert fake_store.indexed == [artifact_id]
        chunks = (
            db.get_conn()
            .execute("SELECT COUNT(*) FROM chunks WHERE artifact_id = ?", (artifact_id,))
            .fetchone()[0]
        )
        assert chunks >= 1

    def test_local_only_image_stays_on_the_machine(self, store, quiet_queue, monkeypatch):
        from enqueue.ingest import queue as ingest_queue

        artifact_id = _seed_image(store, local_only=1)
        seen = _fake_vision(monkeypatch)
        _quiet_derived(monkeypatch)

        ingest_queue.process(artifact_id)

        assert seen["local_only"]

    def test_already_described_image_is_not_charged_again(self, store, quiet_queue, monkeypatch):
        from enqueue.ingest import queue as ingest_queue

        artifact_id = _seed_image(store, body="A description that already exists.", status="ok")
        calls = []

        def _provider(local_only=False):
            calls.append(local_only)
            return FakeVision("should never be asked")

        from enqueue.providers import base as providers_base

        monkeypatch.setattr(providers_base, "get_vision_provider", _provider)
        _quiet_derived(monkeypatch)

        result = ingest_queue.process(artifact_id)

        assert result["described"] == ""
        assert calls == []

    def test_no_vision_model_marks_the_image_failed(self, store, quiet_queue, monkeypatch):
        from enqueue.ingest import queue as ingest_queue
        from enqueue.providers.base import ProviderError

        artifact_id = _seed_image(store)

        def _broken(local_only=False):
            raise ProviderError(
                "the endpoint at http://127.0.0.1:11434/v1 has no " "model named 'llava'"
            )

        from enqueue.providers import base as providers_base

        monkeypatch.setattr(providers_base, "get_vision_provider", _broken)
        _quiet_derived(monkeypatch)

        result = ingest_queue.process(artifact_id)

        # The capture already succeeded; the image just stays unsearchable.
        assert result["described"] == ""
        conn = db.get_conn()
        try:
            status = conn.execute(
                "SELECT status FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()["status"]
        finally:
            conn.close()
        # R.3a: a describe failure is no longer silent. The artifact is marked
        # 'failed' so the doctor report and the wall can surface it, instead of
        # staying 'text_only' as if nothing went wrong.
        assert status == "failed"

    def test_ocr_text_is_appended_when_tesseract_is_installed(
        self, store, quiet_queue, monkeypatch
    ):
        import shutil
        import subprocess

        from enqueue.ingest import queue as ingest_queue

        artifact_id = _seed_image(store)
        _fake_vision(monkeypatch)
        _quiet_derived(monkeypatch)
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/tesseract")
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="sign reads OPEN")
        )

        result = ingest_queue.process(artifact_id)

        assert "OPEN" in result["described"]
        assert "sign reads OPEN" in result["described"]


class TestFacetGate:
    def test_described_image_is_eligible(self, store, quiet_queue):
        from enqueue.ingest.facets import apply_eligibility_gate

        _seed_image(store, body=("word " * 45).strip(), status="ok")
        _seed_image(store, body=None, status="text_only")  # still undescribed
        counts = apply_eligibility_gate()
        assert counts["eligible"] == 1
        assert counts["text_only"] == 1

    def test_described_pdf_is_eligible(self, store, quiet_queue):
        from enqueue.ingest.facets import apply_eligibility_gate

        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO artifacts (id, kind, title, body, content_hash, status,"
                " created_at, updated_at) VALUES ('pdf1','pdf','Paper',NULL,'p1','ok',"
                " datetime('now'), datetime('now'))"
            )
            conn.execute(
                "INSERT INTO page_text (artifact_id, page, text, extractor)"
                " VALUES ('pdf1', 0, 'a long page of extracted text that easily clears"
                " the minimum word count for the facet gate because it describes a"
                " genuine argument with evidence and reasoning spread across many"
                " sentences rather than a bare heading, plus supporting detail and"
                " a conclusion that ties the whole passage together', 'test')"
            )
        counts = apply_eligibility_gate()
        assert counts["eligible"] == 1
        assert counts["kind"] == 0


class TestRequeueImages:
    def test_submit_images_requeues_only_images(self, store, quiet_queue, monkeypatch):
        from enqueue.ingest import queue as ingest_queue

        image_id = _seed_image(store)
        note_id = str(uuid.uuid4())
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO artifacts (id, kind, title, body, content_hash, status,"
                " created_at, updated_at) VALUES (?,?,?,?,?, 'ok',"
                " datetime('now'), datetime('now'))",
                (note_id, "note", "A note", "Some words", "n1"),
            )
        submitted = []
        monkeypatch.setattr(ingest_queue, "submit", submitted.append)

        assert ingest_queue.submit_images() == 1
        assert submitted == [image_id]


class TestVisionProvider:
    def test_local_only_routes_to_the_local_backend(self, store, quiet_queue):
        from enqueue.providers.base import get_vision_provider

        provider = get_vision_provider(local_only=True)
        assert provider.model == config.VISION_MODEL
        assert provider.base_url == config.BACKENDS["ollama"]["url"]

    def test_describe_sends_a_vision_message(self, store, quiet_queue, monkeypatch):
        from enqueue.prompts import IMAGE_DESCRIBE
        from enqueue.providers import ollama as ollama_mod

        captured = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content="A red bicycle leaning against a brick wall."
                            )
                        )
                    ]
                )

        class FakeClient:
            chat = SimpleNamespace(completions=FakeCompletions())

        class FakeOpenAI:
            def __init__(self, **kwargs):
                captured["client_kwargs"] = kwargs

            chat = FakeClient.chat

        monkeypatch.setattr(ollama_mod, "OpenAI", FakeOpenAI)

        provider = object.__new__(ollama_mod.OpenAICompatibleProvider)
        provider.model = "llava-test"
        provider.base_url = "http://127.0.0.1:11434/v1"

        out = provider.describe_image(PNG, "image/png")

        assert out == "A red bicycle leaning against a brick wall."
        assert captured["model"] == "llava-test"
        content = captured["messages"][0]["content"]
        assert content[0] == {"type": "text", "text": IMAGE_DESCRIBE}
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")

    def test_empty_vision_answer_is_a_failure(self, store, quiet_queue, monkeypatch):
        from enqueue.providers import ollama as ollama_mod
        from enqueue.providers.base import ProviderError

        class FakeCompletions:
            def create(self, **kwargs):
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
                )

        class FakeClient:
            chat = SimpleNamespace(completions=FakeCompletions())

        class FakeOpenAI:
            def __init__(self, **kwargs):
                pass

            chat = FakeClient.chat

        monkeypatch.setattr(ollama_mod, "OpenAI", FakeOpenAI)

        provider = object.__new__(ollama_mod.OpenAICompatibleProvider)
        provider.model = "llava-test"
        provider.base_url = "http://127.0.0.1:11434/v1"

        with pytest.raises(ProviderError):
            provider.describe_image(PNG, "image/png")
