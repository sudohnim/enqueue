"""What happens when the endpoint on the other end is not what it claimed to be.

The bug these guard against: `llm_backend` was pointed at a host that answers every
path with HTTP 200 and the plain text "Not Found". That is not an HTTP error, so
nothing raised. The OpenAI client saw a non-JSON content type, handed the body back
as a `str`, and the first thing to read `.choices` off it died with

    'str' object has no attribute 'choices'

which reached the museum verbatim. A misconfigured URL is an ordinary condition and
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

from enqueue.providers.base import ProviderError, why
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
