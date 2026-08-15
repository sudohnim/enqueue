"""What happens when the endpoint on the other end is not what it claimed to be.

The bug these guard against: `llm_backend` was pointed at a host that answers every
path with HTTP 200 and the plain text "Not Found". That is not an HTTP error, so
nothing raised. The OpenAI client saw a non-JSON content type, handed the body back
as a `str`, and the first thing to read `.choices` off it died with

    'str' object has no attribute 'choices'

which reached the app verbatim. A misconfigured URL is an ordinary condition and
has to come back as a sentence naming what to change.

The malformed-response test runs a real HTTP server on 127.0.0.1 and a real OpenAI
client against it, because the failure lives in the client's content-type handling.
A mocked provider would assert nothing about the thing that actually broke.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import openai
import pytest
from pydantic import BaseModel, ValidationError

from enqueue import config, settings
from enqueue.providers.base import (
    ProviderError,
    get_provider,
    get_vision_provider,
    why,
)
from enqueue.providers.ollama import OpenAICompatibleProvider


class Answer(BaseModel):
    answer: str


@contextmanager
def _serve(status: int, content_type: str, body: bytes):
    """Run a one-endpoint HTTP server on a free 127.0.0.1 port. Yields its base URL."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - the name is BaseHTTPRequestHandler's
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # noqa: ARG002 - silence the test server
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()


class TestMalformedResponse:
    def test_a_two_hundred_that_is_not_a_completion_is_a_sentence(self):
        """The exact shape of the reported bug, end to end.

        200 with a text/plain body is the case no layer treats as an error, so it is
        the one that used to reach the person as an AttributeError.
        """
        with _serve(200, "text/plain;charset=UTF-8", b"Not Found") as base_url:
            provider = OpenAICompatibleProvider(model="some-model", base_url=base_url)
            with pytest.raises(ProviderError) as caught:
                provider.complete("s", "u", Answer, max_retries=0)

            said = str(caught.value)
            assert "choices" not in said
            assert "AttributeError" not in said
            assert base_url in said
            assert "not with a chat completion" in said

    def test_an_html_login_page_is_also_a_sentence(self):
        """The other way a wrong URL answers 200: a web page where an API should be."""
        page = b"<html><body>Please sign in</body></html>"
        with _serve(200, "text/html", page) as base_url:
            provider = OpenAICompatibleProvider(model="some-model", base_url=base_url)
            with pytest.raises(ProviderError) as caught:
                provider.complete("s", "u", Answer, max_retries=0)

            assert "not with a chat completion" in str(caught.value)

    def test_json_that_is_not_a_completion_is_a_sentence(self):
        """Right content type, wrong document. Still not an AttributeError."""
        with _serve(200, "application/json", b'{"detail": "no such route"}') as base_url:
            provider = OpenAICompatibleProvider(model="some-model", base_url=base_url)
            with pytest.raises(ProviderError) as caught:
                provider.complete("s", "u", Answer, max_retries=0)

            assert "AttributeError" not in str(caught.value)
            assert base_url in str(caught.value)

    def test_an_unreachable_endpoint_is_a_sentence(self):
        # Port 9 is discard: it exists as a name and refuses, so this stays local and
        # does not depend on a port being free.
        provider = OpenAICompatibleProvider(model="m", base_url="http://127.0.0.1:9/v1")
        with pytest.raises(ProviderError) as caught:
            provider.complete("s", "u", Answer, max_retries=0)

        assert "could not reach the model endpoint" in str(caught.value)
        assert "127.0.0.1:9" in str(caught.value)


def _api_error(cls: type, status: int) -> Exception:
    request = httpx.Request("POST", "http://127.0.0.1:1/v1/chat/completions")
    response = httpx.Response(status, request=request, json={"error": {"message": "no"}})
    return cls("no", response=response, body=None)


def _go_model_error(model_name: str = "deepseek/deepseek-v4-pro") -> openai.AuthenticationError:
    """An OpenCode Go 401 that carries a ModelError body, the root-cause shape (FIX.3)."""
    request = httpx.Request("POST", "http://127.0.0.1:1/v1/chat/completions")
    response = httpx.Response(
        401,
        request=request,
        json={
            "error": {
                "type": "ModelError",
                "message": f"Model {model_name} is not supported",
            }
        },
    )
    return openai.AuthenticationError("no", response=response, body=None)


class TestWhy:
    """Each case is named from the exception type, never from its message text."""

    def test_a_rejected_key_says_so(self):
        said = why(_api_error(openai.AuthenticationError, 401), "http://x/v1", "m")
        assert "rejected the API key" in said

    def test_a_missing_model_names_the_model(self):
        said = why(_api_error(openai.NotFoundError, 404), "http://x/v1", "ghost-7b")
        assert "'ghost-7b'" in said

    def test_rate_limiting_says_to_wait(self):
        said = why(_api_error(openai.RateLimitError, 429), "http://x/v1", "m")
        assert "rate limiting" in said

    def test_the_openai_level_type_wins_over_the_transport_one(self):
        """`openai.APIConnectionError` is raised *from* `httpx.ConnectError`.

        Walking to the deepest cause would report the httpx type and lose the case.
        """
        request = httpx.Request("POST", "http://127.0.0.1:1/v1")
        outer = openai.APIConnectionError(request=request)
        outer.__cause__ = httpx.ConnectError("Connection refused")
        assert "could not reach the model endpoint" in why(outer, "http://x/v1", "m")

    def test_a_reply_that_does_not_fit_the_shape_blames_the_model(self):
        with pytest.raises(ValidationError) as excinfo:
            Answer(answer=None)  # type: ignore[arg-type] - the None is the point
        said = why(excinfo.value, "http://x/v1", "tiny-1b")
        assert "not in the shape" in said

    def test_an_unknown_failure_still_returns_a_string(self):
        said = why(ZeroDivisionError("boom"), "http://x/v1", "m")
        assert said == "ZeroDivisionError: boom"

    def test_a_cause_cycle_does_not_hang(self):
        first, second = ValueError("a"), ValueError("b")
        first.__cause__ = second
        second.__cause__ = first
        assert why(first, "http://x/v1", "m")

    def test_go_model_error_is_not_a_key_rejection(self):
        """FIX.3: OpenCode Go returns 401 ModelError for an unrecognized model name,
        but the SDK raises AuthenticationError. The translator must say the model is
        not served, not that the key was rejected.
        """
        cause = _go_model_error("deepseek/deepseek-v4-pro")
        said = why(cause, config.BACKENDS["opencode-go"]["url"], "deepseek/deepseek-v4-pro")
        assert "rejected the API key" not in said
        assert "does not serve the model" in said
        assert "deepseek/deepseek-v4-pro" in said
        assert "valid" in said.lower()

    def test_go_unsupported_shape_model_error_names_the_real_limitation(self):
        """FIX.3: when the ModelError body names a model that needs /responses or
        /messages, the translator names the API-shape limitation, not an auth failure.
        """
        cause = _go_model_error("grok-4.5")
        said = why(cause, config.BACKENDS["opencode-go"]["url"], "grok-4.5")
        assert "rejected the API key" not in said
        assert "API shape" in said
        assert "grok-4.5" in said
        assert "chat-completions" in said

    def test_a_plain_key_rejection_still_says_so(self):
        """The ModelError check must not swallow a genuine 401."""
        cause = _api_error(openai.AuthenticationError, 401)
        said = why(cause, "https://x/v1", "m")
        assert "rejected the API key" in said


class TestGoModelShapeCheck:
    """FIX.3: refuse a Go model that needs /responses or /messages before calling."""

    def test_unsupported_shape_model_is_refused_before_calling(self):
        provider = OpenAICompatibleProvider(
            model="grok-4.5",
            base_url=config.BACKENDS["opencode-go"]["url"],
        )
        with pytest.raises(ProviderError) as caught:
            provider.complete("s", "u", Answer, max_retries=0)
        said = str(caught.value)
        assert "API shape" in said
        assert "grok-4.5" in said
        assert "chat-completions" in said

    def test_chat_completions_model_is_allowed_through(self):
        """A model on the supported list must not be refused by the shape check.

        It may still fail for other reasons (rate limit, no key) - the point is that
        the shape check does not block it.
        """
        from enqueue.providers.base import _check_go_model_shape

        # Should not raise.
        _check_go_model_shape(config.BACKENDS["opencode-go"]["url"], "kimi-k3")
        _check_go_model_shape(config.BACKENDS["opencode-go"]["url"], "deepseek-v4-pro")

    def test_non_go_backend_is_unaffected(self):
        """The shape check is a no-op for backends that are not OpenCode Go."""
        from enqueue.providers.base import _check_go_model_shape

        _check_go_model_shape("http://127.0.0.1:11434/v1", "grok-4.5")


class TestBackendUrlDerivation:
    """SET.1: the endpoint is implied by the backend, never by a stored llm_url.

    A named backend has its URL in config.BACKENDS; a stale stored llm_url (the
    old localhost default) must not override it. Only `custom` reads the
    user-typed URL, and local-only always routes to the local Ollama.
    """

    def test_a_named_backend_uses_its_own_url_not_the_stored_one(self, monkeypatch):
        monkeypatch.setattr(
            settings,
            "get",
            lambda name: {
                "llm_backend": "opencode-go",
                "llm_model": "kimi-k3",
                "llm_url": "http://127.0.0.1:11434/v1",  # the stale localhost default
            }.get(name),
        )

        provider = get_provider()
        assert provider.base_url == config.BACKENDS["opencode-go"]["url"]
        assert "127.0.0.1" not in provider.base_url

    def test_custom_uses_the_stored_url(self, monkeypatch):
        monkeypatch.setattr(
            settings,
            "get",
            lambda name: {
                "llm_backend": "custom",
                "llm_model": "some-model",
                "llm_url": "https://myhost.example/v1",
            }.get(name),
        )

        provider = get_provider()
        assert provider.base_url == "https://myhost.example/v1"

    def test_local_only_always_routes_to_ollama(self, monkeypatch):
        monkeypatch.setattr(
            settings,
            "get",
            lambda name: {
                "llm_backend": "opencode-go",
                "llm_model": "kimi-k3",
                "llm_url": "https://myhost.example/v1",
            }.get(name),
        )

        provider = get_provider(local_only=True)
        assert provider.base_url == config.BACKENDS["ollama"]["url"]

    def test_vision_provider_derives_the_url_the_same_way(self, monkeypatch):
        monkeypatch.setattr(
            settings,
            "get",
            lambda name: {
                "llm_backend": "openrouter",
                "vision_model": "google/gemini-3-flash",
                "llm_url": "http://127.0.0.1:11434/v1",
            }.get(name),
        )

        provider = get_vision_provider()
        assert provider.base_url == config.BACKENDS["openrouter"]["url"]
