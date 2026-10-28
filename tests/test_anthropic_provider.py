"""The Anthropic backend: a person's own key, the Messages API through the official SDK.

A real HTTP server on 127.0.0.1 plays the Messages API, so the SDK's own request and
error handling run, not a mock of them.
"""

from __future__ import annotations

import inspect
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import anthropic
import pytest
from pydantic import BaseModel, ValidationInfo, model_validator

from enqueue import catalog, config, schemas, settings
from enqueue.providers import pause
from enqueue.providers.anthropic import AnthropicProvider
from enqueue.providers.base import LocalOnly, ProviderError, get_provider, get_vision_provider


class Word(BaseModel):
    word: str

    @model_validator(mode="after")
    def not_banned(self, info: ValidationInfo):
        if self.word in (info.context or {}).get("banned", ()):
            raise ValueError(f"{self.word!r} is banned")
        return self


def _message(text: str, stop: str = "end_turn") -> dict:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


@contextmanager
def _messages_api(replies: list[tuple[int, dict]]):
    """Answer each POST with the next (status, body). Yields the requests it got."""
    got: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - the name is BaseHTTPRequestHandler's
            size = int(self.headers.get("Content-Length") or 0)
            got.append(
                {
                    "body": json.loads(self.rfile.read(size)),
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                }
            )
            status, body = replies.pop(0)
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            if status == 429:
                self.send_header("retry-after", "120")
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format, *args):  # noqa: ARG002 - silence the test server
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", got
    finally:
        server.shutdown()


def _provider(url: str) -> AnthropicProvider:
    p = AnthropicProvider(model="claude-haiku-5-5", base_url=url)
    p._sdk = anthropic.Anthropic(api_key="test-key", base_url=url, max_retries=0)
    return p


def test_the_anthropic_backend_gets_the_anthropic_adapter(store):
    settings.update({"llm_backend": "anthropic", "llm_model": "claude-haiku-5-5"})
    assert isinstance(get_provider(), AnthropicProvider)
    assert get_provider().base_url == "https://api.anthropic.com"
    settings.update({"vision_model": "claude-haiku-5-5"})
    assert isinstance(get_vision_provider(), AnthropicProvider)
    with pytest.raises(LocalOnly):
        get_provider(local_only=True)


def test_openai_rides_the_openai_compatible_adapter(store):
    from enqueue.providers.ollama import OpenAICompatibleProvider

    settings.update({"llm_backend": "openai", "llm_model": "gpt-6-luna"})
    p = get_provider()
    assert isinstance(p, OpenAICompatibleProvider)
    assert p.base_url == "https://api.openai.com/v1"


def test_a_structured_answer_asks_for_the_schema_and_is_validated(store):
    with _messages_api([(200, _message('{"word": "raven"}'))]) as (url, got):
        out = _provider(url).complete("Say a word.", "Any bird.", Word)
    assert out.word == "raven"
    body = got[0]["body"]
    assert body["system"] == "Say a word."
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert not {"temperature", "top_p", "top_k"} & set(body)
    assert "test-key" in json.dumps(got[0]["headers"])


def test_a_reply_the_validators_refuse_is_asked_for_again_with_the_reason(store):
    replies = [(200, _message('{"word": "crow"}')), (200, _message('{"word": "raven"}'))]
    with _messages_api(replies) as (url, got):
        out = _provider(url).complete("s", "u", Word, context={"banned": {"crow"}})
    assert out.word == "raven"
    retry = got[1]["body"]["messages"]
    assert retry[1] == {"role": "assistant", "content": '{"word": "crow"}'}
    assert "banned" in retry[2]["content"]


def test_retries_end_in_a_sentence(store):
    replies = [(200, _message('{"word": "crow"}'))] * 2
    with _messages_api(replies) as (url, _):
        with pytest.raises(ProviderError, match="not in the shape"):
            _provider(url).complete("s", "u", Word, context={"banned": {"crow"}}, max_retries=2)


def test_a_refusal_is_not_parsed_as_an_answer(store):
    with _messages_api([(200, _message("No.", stop="refusal"))]) as (url, _):
        with pytest.raises(ProviderError, match="declined"):
            _provider(url).complete("s", "u", Word)


def test_a_refused_key_says_so(store):
    err = {"type": "error", "error": {"type": "authentication_error", "message": "bad key"}}
    with _messages_api([(401, err)]) as (url, _):
        with pytest.raises(ProviderError, match="rejected the API key"):
            _provider(url).complete("s", "u", Word)


def test_a_rate_limit_pauses_every_model_call(store):
    err = {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}
    try:
        with _messages_api([(429, err)]) as (url, _):
            with pytest.raises(ProviderError):
                _provider(url).complete("s", "u", Word)
        assert pause.active()
    finally:
        pause.reset()


def test_a_credential_is_blanked_before_it_leaves(store, monkeypatch):
    from enqueue import privacy

    monkeypatch.setattr(privacy, "is_remote", lambda p: True)
    note = "aws key AKIAIOSFODNN7EXAMPLE in here"
    with _messages_api([(200, _message('{"word": "raven"}'))]) as (url, got):
        _provider(url).complete("s", note, Word)
    assert "AKIAIOSFODNN7EXAMPLE" not in json.dumps(got[0]["body"])


def test_an_image_is_sent_as_an_image_block(store):
    with _messages_api([(200, _message("A raven on a fence."))]) as (url, got):
        text = _provider(url).describe_image(b"\x89PNG", "image/png")
    assert text == "A raven on a fence."
    block = got[0]["body"]["messages"][0]["content"][0]
    assert block["type"] == "image" and block["source"]["media_type"] == "image/png"


def test_every_schema_can_be_asked_for():
    for _, model in inspect.getmembers(schemas, inspect.isclass):
        if issubclass(model, BaseModel) and model.__module__ == schemas.__name__:
            anthropic.transform_schema(model.model_json_schema())


def test_the_model_lists_are_fetched_with_the_key(store, monkeypatch):
    monkeypatch.setattr(config, "llm_api_key", lambda url=None: "no-key")
    assert catalog._fetch("anthropic") is None
    monkeypatch.setattr(config, "llm_api_key", lambda url=None: "sk-test")
    monkeypatch.setitem(catalog.KEYED, "openai", lambda key: {"chat": [key], "fetched_at": 0})
    assert catalog._fetch("openai")["chat"] == ["sk-test"]


def test_each_service_keeps_its_own_key(store, monkeypatch):
    from enqueue import keyring

    vault: dict[str, str] = {keyring.SERVICE: "sk-or-saved-before-the-split"}
    monkeypatch.setattr(keyring, "_get", lambda service, strict=False: vault.get(service))
    monkeypatch.setattr(
        keyring, "_set", lambda service, secret, noun="key": vault.update({service: secret})
    )
    monkeypatch.setattr(keyring, "_clear", lambda service: vault.pop(service, None) is not None)
    monkeypatch.delenv("ENQ_LLM_API_KEY", raising=False)

    url = {n: b["url"] for n, b in config.BACKENDS.items()}
    # A key from before the split belongs to the services there were then, never a new one.
    assert config.llm_api_key(url["openrouter"]) == "sk-or-saved-before-the-split"
    assert config.llm_api_key(url["anthropic"]) == "no-key"
    keyring.set("sk-ant-mine", "anthropic")
    keyring.set("sk-oa-mine", "openai")
    assert config.llm_api_key(url["anthropic"]) == "sk-ant-mine"
    assert config.llm_api_key(url["openai"]) == "sk-oa-mine"
    assert config.llm_api_key(url["openrouter"]) == "sk-or-saved-before-the-split"
    by_name = {b["name"]: b for b in settings.backends()}
    assert by_name["anthropic"]["key_hint"] == "...mine"
    keyring.clear("openrouter")
    assert config.llm_api_key(url["openrouter"]) == "no-key"
    assert config.llm_api_key(url["anthropic"]) == "sk-ant-mine"


def test_a_service_starts_on_a_small_model_from_its_own_list():
    anthropic_list = {
        "chat": ["claude-haiku-5-5", "claude-opus-5-5", "claude-sonnet-5-5"],
        "vision": ["claude-haiku-5-5", "claude-opus-5-5", "claude-sonnet-5-5"],
        "newest": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"],
    }
    assert catalog.suggest("anthropic", anthropic_list) == ("claude-haiku-5-5",) * 2
    openai_list = {"chat": ["gpt-6", "gpt-6-luna"], "newest": ["gpt-6", "gpt-6-luna"]}
    assert catalog.suggest("openai", openai_list) == ("gpt-6-luna",) * 2
    assert catalog.suggest("openai", {"chat": ["gpt-7"], "newest": ["gpt-7"]}) == ("gpt-7",) * 2
    assert catalog.suggest("openrouter", {"chat": ["x"]}) == (None, None)


def test_the_models_route_names_the_suggested_model(store, monkeypatch):
    from fastapi.testclient import TestClient

    from enqueue.api.app import create_app

    monkeypatch.setitem(
        catalog._CACHE,
        "anthropic",
        {"chat": ["claude-haiku-5-5"], "vision": [], "newest": ["claude-haiku-5-5"]},
    )
    monkeypatch.setattr(catalog, "_load", lambda: None)
    import time as _time

    catalog._CACHE["anthropic"]["fetched_at"] = _time.time()
    got = TestClient(create_app()).get("/settings/models?backend=anthropic").json()
    assert got["suggested"] == "claude-haiku-5-5" and got["suggested_vision"] is None
