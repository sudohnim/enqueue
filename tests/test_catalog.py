"""The model catalog: a model the service does not serve is refused when saved and said in
Settings; a list that cannot be fetched refuses nothing."""

import time

import httpx
import pytest

from enqueue import catalog, settings, setup

REAL_REFRESH = catalog.refresh

LISTING = {
    "data": [
        {
            "id": "google/gemini-3.8-flash",
            "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
        },
        {
            "id": "moonshotai/kimi-k3",
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
        },
        {
            "id": "black-forest-labs/flux",
            "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]},
        },
    ]
}


@pytest.fixture
def openrouter(monkeypatch, store):
    monkeypatch.setattr(catalog, "_CACHE", {"openrouter": catalog._parse(LISTING)})
    settings.update({"llm_backend": "openrouter", "llm_model": "google/gemini-3.8-flash"})


def test_the_listing_keeps_text_models_and_marks_the_ones_that_read_pictures():
    listing = catalog._parse(LISTING)
    assert listing["chat"] == ["google/gemini-3.8-flash", "moonshotai/kimi-k3"]
    assert listing["vision"] == ["google/gemini-3.8-flash"]


def test_a_model_openrouter_does_not_serve_is_refused(openrouter):
    with pytest.raises(ValueError, match="doesn't offer google/gemini-3-flash"):
        settings.update({"llm_model": "google/gemini-3-flash"})
    settings.update({"summarize_model": "moonshotai/kimi-k3"})
    assert settings.get("summarize_model") == "moonshotai/kimi-k3"


def test_the_images_job_needs_a_model_that_reads_pictures(openrouter):
    with pytest.raises(ValueError, match="reading pictures"):
        settings.update({"vision_model": "moonshotai/kimi-k3"})
    settings.update({"vision_model": "google/gemini-3.8-flash"})


def test_the_service_and_model_are_checked_together(openrouter):
    with pytest.raises(ValueError):
        settings.update({"llm_backend": "opencode-go", "llm_model": "google/gemini-3.8-flash"})


def test_an_unknown_list_refuses_nothing(store):
    settings.update({"llm_backend": "openrouter", "llm_model": "anything/at-all"})
    assert settings.get("llm_model") == "anything/at-all"


def test_a_model_added_since_the_list_was_fetched_is_looked_up_again(monkeypatch, openrouter):
    old = catalog._CACHE["openrouter"] | {"fetched_at": time.time() - catalog.RECHECK_S - 1}
    monkeypatch.setattr(catalog, "_CACHE", {"openrouter": old})
    newer = {"data": LISTING["data"] + [{"id": "z-ai/glm-5.2"}]}
    monkeypatch.setattr(
        catalog,
        "refresh",
        lambda b: catalog._CACHE.update({b: catalog._parse(newer)}) or catalog._CACHE[b],
    )
    settings.update({"llm_model": "z-ai/glm-5.2"})
    assert settings.get("llm_model") == "z-ai/glm-5.2"


def test_settings_says_when_a_saved_model_is_not_offered(openrouter, monkeypatch):
    monkeypatch.setattr(catalog, "_CACHE", {})  # saved before the list was known
    settings.update({"summarize_model": "google/gemini-3-flash"})
    monkeypatch.setattr(catalog, "_CACHE", {"openrouter": catalog._parse(LISTING)})
    alert = next(a for a in setup.status()["alerts"] if a["id"] == "model-unknown")
    assert "google/gemini-3-flash" in alert["text"] and "OpenRouter" in alert["text"]


def test_a_service_that_cannot_be_reached_gives_no_list(monkeypatch):
    def down(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", down)
    assert REAL_REFRESH("openrouter") is None


def test_the_models_route_serves_the_pickers(openrouter):
    from fastapi.testclient import TestClient

    from enqueue.api.app import create_app

    client = TestClient(create_app())
    got = client.get("/settings/models", params={"backend": "openrouter"}).json()
    assert got["known"] and "moonshotai/kimi-k3" in got["chat"]
    assert got["vision"] == ["google/gemini-3.8-flash"]
    assert client.get("/settings/models", params={"backend": "ollama"}).json()["known"] is False
