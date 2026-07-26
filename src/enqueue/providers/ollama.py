"""Ollama adapter, via its OpenAI-compatible endpoint.

Two things here are deliberate and easy to get wrong:

1. The endpoint is 127.0.0.1, never localhost. This machine may run a second Ollama
   in Docker bound to the IPv6 wildcard, and localhost resolves to IPv6 first.
2. The instructor mode is JSON, passed explicitly. The default is TOOLS, which needs
   function calling. MD_JSON and JSON require nothing of the endpoint beyond chat.
"""

from __future__ import annotations

import instructor
from openai import OpenAI
from pydantic import BaseModel

from .. import config


class OllamaProvider:
    name = "ollama"

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        self.model = model or config.LLM_MODEL
        self._client = instructor.from_openai(
            OpenAI(base_url=base_url or config.OLLAMA_URL, api_key="ollama"),
            mode=instructor.Mode.JSON,
        )

    def complete(
        self,
        system: str,
        user: str,
        response_model: type[BaseModel],
        context: dict | None = None,
        max_retries: int = 3,
    ):
        # instructor >= 1.9 renamed validation_context to context. The keyword is what
        # carries proper_nouns, artifact_text, and lens into the validators, so getting
        # it wrong silently disables every context-dependent check rather than erroring.
        return self._client.chat.completions.create(
            model=self.model,
            response_model=response_model,
            max_retries=max_retries,
            context=context or {},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
