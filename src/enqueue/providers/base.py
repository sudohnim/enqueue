"""The one narrow interface every model call goes through.

Never scatter model calls through the codebase. Adapters differ in endpoint, model
id, and instructor mode; nothing else in the system should know which is in use.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class Provider(Protocol):
    name: str
    model: str

    def complete(
        self,
        system: str,
        user: str,
        response_model: type[T],
        context: dict | None = None,
        max_retries: int | None = None,
    ) -> T: ...


def get_provider(local_only: bool = False) -> Provider:
    """Return the configured provider.

    Local-only artifacts always route to the local backend, whatever the default is.
    That is the one rule here that is not a preference: marking something local-only
    is a promise that its text never leaves the machine, and a configuration change
    must not be able to quietly break it.
    """
    from .. import config, settings
    from .ollama import OpenAICompatibleProvider

    name = "ollama" if local_only else settings.get("llm_backend")
    backend = config.BACKENDS.get(name, config.BACKENDS["ollama"])

    url = settings.get("llm_url") if not local_only else config.BACKENDS["ollama"]["url"]
    return OpenAICompatibleProvider(
        model=settings.get("llm_model") if not local_only else config.LLM_MODEL,
        base_url=url or backend["url"],
    )
