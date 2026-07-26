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
        max_retries: int = 3,
    ) -> T: ...


def get_provider(local_only: bool = False) -> Provider:
    """Return the configured provider.

    Local-only artifacts always route to Ollama, whatever the default is. The POC
    has one adapter, so this is a seam rather than a decision point today.
    """
    from .ollama import OllamaProvider

    return OllamaProvider()
