"""The OpenAI-compatible adapter, for every backend. Gotchas: AGENTS.md "Provider layer"."""

from __future__ import annotations

from typing import TypeVar, cast

import instructor
from openai import BadRequestError, OpenAI
from openai.types.chat import ChatCompletionContentPartParam, ChatCompletionMessageParam
from pydantic import BaseModel

from .. import config
from ..prompts import IMAGE_DESCRIBE
from . import pause
from .base import ProviderError, _check_go_model_shape, why

T = TypeVar("T", bound=BaseModel)


def _extra_headers() -> dict[str, str]:
    """The `llm_headers` setting, one `Name: value` per line. Lines without a colon are dropped."""
    from .. import settings

    raw = str(settings.get("llm_headers") or "")
    headers: dict[str, str] = {}
    for line in raw.splitlines():
        name, sep, value = line.partition(":")
        name, value = name.strip(), value.strip()
        if sep and name and value:
            headers[name] = value
    return headers


class OpenAICompatibleProvider:
    name = "openai-compatible"

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        self.model = model or config.LLM_MODEL
        self.base_url = base_url or config.OLLAMA_URL
        self._instructor = None
        self._instructor_md = None

    def _build(self, mode):
        return instructor.from_openai(
            OpenAI(
                base_url=self.base_url,
                api_key=config.llm_api_key(),
                default_headers=_extra_headers(),
            ),
            mode=mode,
        )

    @property
    def _client(self):
        """The instructor client, built on first model call so reading `.model` stays free."""
        if self._instructor is None:
            self._instructor = self._build(instructor.Mode.JSON)
        return self._instructor

    @property
    def _client_md(self):
        """The same client in MD_JSON mode: the schema is asked for in the prompt and the
        JSON read out of the reply, with no `response_format` on the request."""
        if self._instructor_md is None:
            self._instructor_md = self._build(instructor.Mode.MD_JSON)
        return self._instructor_md

    def complete(
        self,
        system: str,
        user: str,
        response_model: type[T],
        context: dict | None = None,
        max_retries: int | None = None,
    ) -> T:
        # A credential in the text (a note, a PDF, a page) never goes to a remote model:
        # blank it here, where every structured call passes (ingest/secrets.py).
        from .. import privacy
        from ..ingest.secrets import redact

        if privacy.is_remote(self):
            system, user = redact(system), redact(user)

        # Some backends (Gemini) reject an empty user turn, so fold system into user.
        if user.strip():
            messages: list[ChatCompletionMessageParam] = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        else:
            messages = [{"role": "user", "content": system}]

        _check_go_model_shape(self.base_url, self.model)
        pause.check()  # a usage limit is in effect: fail now, without a doomed request
        kwargs = {
            "model": self.model,
            "response_model": response_model,
            "max_retries": config.MODEL_RETRIES if max_retries is None else max_retries,
            "context": context or {},
            "messages": messages,
        }
        try:
            return cast(T, self._client.chat.completions.create(**kwargs))
        except Exception as exc:  # noqa: BLE001 - translated, not swallowed
            if not _refused_json_mode(exc):
                pause.trip_from(exc)  # a 429 pauses every model call until retry-after
                raise ProviderError(why(exc, self.base_url, self.model)) from exc
        # JSON mode sends `response_format: json_object`, and some upstreams refuse it
        # for particular inputs with a bare 400 (OpenCode Go's kimi-k3 answers "Invalid
        # request parameters" for some notes, every time, while the same request without
        # it succeeds). A 400 is not transient, so retrying the same request would fail
        # forever; ask once more in MD_JSON mode, which carries no response_format.
        try:
            return cast(T, self._client_md.chat.completions.create(**kwargs))
        except Exception as exc:  # noqa: BLE001 - translated, not swallowed
            pause.trip_from(exc)
            raise ProviderError(why(exc, self.base_url, self.model)) from exc

    def describe_image(self, image: bytes, mime: str) -> str:
        """A few factual sentences about an image, for the index. Plain client (free text).

        An empty reply raises: indexing nothing would fail silently.
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
        _check_go_model_shape(self.base_url, self.model)
        pause.check()
        try:
            reply = client.chat.completions.create(
                model=self.model,
                max_tokens=300,
                messages=messages,
            )
        except Exception as exc:  # noqa: BLE001 - translated, not swallowed
            pause.trip_from(exc)
            raise ProviderError(why(exc, self.base_url, self.model)) from exc

        text = (reply.choices[0].message.content or "").strip()
        if not text:
            raise ProviderError(f"the vision model at {self.base_url} answered without any text")
        return text


def _refused_json_mode(exc: BaseException) -> bool:
    """Whether a structured call failed on a 400 from the provider (anywhere in the chain;
    instructor wraps the OpenAI error in its own retry exception)."""
    seen = exc
    while seen is not None:
        if isinstance(seen, BadRequestError):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


# Old name, kept for imports.
OllamaProvider = OpenAICompatibleProvider
