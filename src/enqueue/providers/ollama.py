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

import instructor
from openai import OpenAI
from pydantic import BaseModel

from .. import config


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
        response_model: type[BaseModel],
        context: dict | None = None,
        max_retries: int | None = None,
    ):
        # instructor >= 1.9 renamed validation_context to context. The keyword is what
        # carries proper_nouns, artifact_text, and lens into the validators, so getting
        # it wrong silently disables every context-dependent check rather than erroring.
        return self._client.chat.completions.create(
            model=self.model,
            response_model=response_model,
            max_retries=config.MODEL_RETRIES if max_retries is None else max_retries,
            context=context or {},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )


# The old name, kept so nothing importing it breaks. It was never Ollama-specific.
OllamaProvider = OpenAICompatibleProvider
