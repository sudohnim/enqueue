"""The OpenAI-compatible adapter. Named for Ollama because that is what it points at
by default, but nothing here is Ollama-specific: any endpoint speaking the same
protocol works by setting three environment variables. See `config.LLM_MODEL`.

Three things here are deliberate and easy to get wrong:

1. The endpoint is 127.0.0.1, never localhost. This machine may run a second Ollama
   in Docker bound to the IPv6 wildcard, and localhost resolves to IPv6 first.
2. The instructor mode is JSON, passed explicitly. The default is TOOLS, which needs
   function calling. MD_JSON and JSON require nothing of the endpoint beyond chat.
3. The API key is resolved per client rather than at import, so a key stored in
   Settings takes effect on the next question instead of the next restart. Ollama
   ignores it; a hosted endpoint does not.
"""

from __future__ import annotations

from typing import TypeVar, cast

import instructor
from openai import OpenAI
from openai.types.chat import ChatCompletionContentPartParam, ChatCompletionMessageParam
from pydantic import BaseModel

from .. import config
from ..prompts import IMAGE_DESCRIBE
from .base import ProviderError, why

T = TypeVar("T", bound=BaseModel)


def _extra_headers() -> dict[str, str]:
    """Headers the person configured, one `Name: value` per line.

    OpenRouter wants an HTTP-Referer and an X-Title before it will attribute a call,
    and every hosted endpoint has some variation on that. Without this each one is a
    code change, which is how an adapter that was meant to be generic stops being it.
    """
    from .. import settings

    raw = str(settings.get("llm_headers") or "")
    headers: dict[str, str] = {}
    for line in raw.splitlines():
        name, sep, value = line.partition(":")
        name, value = name.strip(), value.strip()
        # A line with no colon is a typo, not a header. Silently sending it as one
        # would produce a confusing rejection from the far end.
        if sep and name and value:
            headers[name] = value
    return headers


class OpenAICompatibleProvider:
    name = "openai-compatible"

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        self.model = model or config.LLM_MODEL
        self.base_url = base_url or config.OLLAMA_URL
        self._client = instructor.from_openai(
            OpenAI(
                base_url=self.base_url,
                api_key=config.llm_api_key(),
                default_headers=_extra_headers(),
            ),
            mode=instructor.Mode.JSON,
        )

    def complete(
        self,
        system: str,
        user: str,
        response_model: type[T],
        context: dict | None = None,
        max_retries: int | None = None,
    ) -> T:
        # instructor >= 1.9 renamed validation_context to context. The keyword is what
        # carries proper_nouns, artifact_text, and lens into the validators, so getting
        # it wrong silently disables every context-dependent check rather than erroring.
        # Many calls put the whole prompt in `system` and send an empty `user`
        # (the router, the pivot planner, extract). Ollama accepts that; Gemini and
        # other providers reject a request whose user contents are empty ("contents
        # is not specified"). When there is no user turn, fold the system prompt into
        # the user message so the request always carries content, on every backend.
        if user.strip():
            messages: list[ChatCompletionMessageParam] = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        else:
            messages = [{"role": "user", "content": system}]

        try:
            return cast(
                T,
                self._client.chat.completions.create(
                    model=self.model,
                    response_model=response_model,
                    max_retries=config.MODEL_RETRIES if max_retries is None else max_retries,
                    context=context or {},
                    messages=messages,
                ),
            )
        # This is the only boundary between somebody else's HTTP endpoint and the rest
        # of the program, so it is the only place that knows enough to say what went
        # wrong. Everything above it gets one exception type carrying one sentence.
        except Exception as exc:  # noqa: BLE001 - translated, not swallowed
            raise ProviderError(why(exc, self.base_url, self.model)) from exc

    def describe_image(self, image: bytes, mime: str) -> str:
        """Describe an image in a few factual sentences, for the search index.

        The image travels as a base64 data URL inside an OpenAI vision message,
        sent to the plain client rather than the instructor-wrapped one: this
        step wants free text, not a schema. The model is the vision setting this
        provider was built with, so the caller picks it via `get_vision_provider`.
        A bare description that comes back empty is a failure like any other:
        storing it would index a silent nothing.
        """
        import base64

        data_url = f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"
        client = OpenAI(
            base_url=self.base_url,
            api_key=config.llm_api_key(),
            default_headers=_extra_headers(),
        )
        content: list[ChatCompletionContentPartParam] = [
            {"type": "text", "text": IMAGE_DESCRIBE},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
        messages: list[ChatCompletionMessageParam] = [{"role": "user", "content": content}]
        try:
            reply = client.chat.completions.create(
                model=self.model,
                max_tokens=300,
                messages=messages,
            )
        except Exception as exc:  # noqa: BLE001 - translated, not swallowed
            raise ProviderError(why(exc, self.base_url, self.model)) from exc

        text = (reply.choices[0].message.content or "").strip()
        if not text:
            raise ProviderError(f"the vision model at {self.base_url} answered without any text")
        return text


# The old name, kept so nothing importing it breaks. It was never Ollama-specific.
OllamaProvider = OpenAICompatibleProvider
