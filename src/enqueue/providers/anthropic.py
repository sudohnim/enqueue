"""The Anthropic adapter: the Messages API through the official SDK, for a person's own key."""

from __future__ import annotations

import base64
from typing import TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from .. import config, outbound, privacy
from ..prompts import IMAGE_DESCRIBE
from . import pause
from .base import ProviderError, why

T = TypeVar("T", bound=BaseModel)

MAX_TOKENS = 16000


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str, base_url: str) -> None:
        self.model = model
        self.base_url = base_url
        self._sdk = None

    @property
    def _client(self) -> anthropic.Anthropic:
        """Built on first model call, so reading `.model` stays free."""
        if self._sdk is None:
            self._sdk = anthropic.Anthropic(
                api_key=config.llm_api_key(self.base_url), base_url=self.base_url
            )
        return self._sdk

    def _call(self, purpose: str, chars: int, blanked: int = 0, **kwargs):
        pause.check()
        if privacy.is_remote(self):
            outbound.record(self.base_url, self.model, purpose, chars, blanked)
        try:
            reply = self._client.messages.create(model=self.model, **kwargs)
        except Exception as exc:  # noqa: BLE001 - translated, not swallowed
            pause.trip_from(exc)
            pause.note_failure(exc, self.base_url, self.model)
            raise ProviderError(why(exc, self.base_url, self.model)) from exc
        pause.note_success()
        if reply.stop_reason == "refusal":
            raise ProviderError(f"{self.model} declined to answer this one")
        text = "".join(b.text for b in reply.content if b.type == "text").strip()
        if reply.stop_reason == "max_tokens" or not text:
            raise ProviderError(f"{self.model} stopped before it finished the answer")
        return text

    def complete(
        self,
        system: str,
        user: str,
        response_model: type[T],
        context: dict | None = None,
        max_retries: int | None = None,
    ) -> T:
        from ..ingest.secrets import REDACTION, redact

        before = (system + user).count(REDACTION)
        system, user = redact(system), redact(user)
        blanked = (system + user).count(REDACTION) - before
        schema = anthropic.transform_schema(response_model.model_json_schema())
        messages: list = [{"role": "user", "content": user if user.strip() else system}]
        attempts = max(1, config.MODEL_RETRIES if max_retries is None else max_retries)
        for attempt in range(attempts):
            text = self._call(
                response_model.__name__,
                len(system) + len(user),
                blanked,
                max_tokens=MAX_TOKENS,
                system=system if user.strip() else anthropic.omit,
                messages=messages,
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
            try:
                return response_model.model_validate_json(text, context=context or {})
            except ValidationError as exc:
                if attempt == attempts - 1:
                    raise ProviderError(why(exc, self.base_url, self.model)) from exc
                messages += [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": f"Fix these errors and answer again:\n{exc}"},
                ]
        raise AssertionError("unreachable")

    def describe_image(self, image: bytes, mime: str) -> str:
        """A few factual sentences about an image, for the index."""
        data = base64.standard_b64encode(image).decode("ascii")
        return self._call(
            "image",
            len(data),
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": mime, "data": data},
                        },
                        {"type": "text", "text": IMAGE_DESCRIBE},
                    ],
                }
            ],
        )
