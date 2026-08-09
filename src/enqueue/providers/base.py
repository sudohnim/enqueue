"""The one narrow interface every model call goes through.

Never scatter model calls through the codebase. Adapters differ in endpoint, model
id, and instructor mode; nothing else in the system should know which is in use.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ProviderError(RuntimeError):
    """A model call that did not produce an answer, said in a sentence.

    Every failure a person can hit here is ordinary - a key that is wrong, a host that
    is down, a model name that does not exist, an endpoint that is not really an
    OpenAI API. None of them are bugs in this program, so none of them should reach
    the interface as a Python exception name. The interface prints `str(exc)`, so the
    message is the whole product of this class.
    """


def _chain(exc: BaseException) -> list[BaseException]:
    """The exception and everything it was raised from, outermost first.

    instructor wraps what went wrong in its own retry exception, and the OpenAI client
    wraps transport failures in its own types, so the useful exception is somewhere
    below the one that was caught. Outermost first matters: `openai.APIConnectionError`
    sits above `httpx.ConnectError`, and the OpenAI-level type is the one that says
    which of the cases below this is.
    """
    chain, seen = [], set()
    cause: BaseException | None = exc
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        chain.append(cause)
        cause = cause.__cause__
    return chain


def why(exc: BaseException, base_url: str, model: str) -> str:
    """Turn a failed model call into something a person can act on.

    Same job as `preview._why`, one layer down. The cases are distinguished by
    exception type rather than by message text, because the messages come from a
    dependency and are not ours to depend on.
    """
    for link in _chain(exc):
        said = _name_one(link, base_url, model)
        if said:
            return said

    deepest = _chain(exc)[-1]
    return f"{type(deepest).__name__}: {deepest}"[:300]


def _name_one(cause: BaseException, base_url: str, model: str) -> str | None:
    """The sentence for one exception, or None if this one says nothing useful."""
    import openai
    from pydantic import ValidationError

    if isinstance(cause, openai.AuthenticationError):
        return (
            f"the endpoint at {base_url} rejected the API key. Set a valid key in "
            "Settings, or switch the backend to Ollama to stay on this machine"
        )
    if isinstance(cause, openai.PermissionDeniedError):
        return (
            f"the endpoint at {base_url} refused this key access to {model!r}. The key "
            "may not cover that model"
        )
    if isinstance(cause, openai.RateLimitError):
        return (
            f"the endpoint at {base_url} is rate limiting, or the account is out of "
            "credit. Try again later"
        )
    if isinstance(cause, openai.NotFoundError):
        return (
            f"the endpoint at {base_url} has no model named {model!r}. Check the model "
            "name, and check that the URL is the API base path"
        )
    if isinstance(cause, openai.BadRequestError):
        return f"the endpoint at {base_url} rejected the request for {model!r}: {cause}"
    if isinstance(cause, openai.APITimeoutError):
        return f"the endpoint at {base_url} did not answer in time"
    if isinstance(cause, openai.APIConnectionError):
        return f"could not reach the model endpoint at {base_url}. Is it running?"
    if isinstance(cause, openai.APIStatusError):
        return f"the endpoint at {base_url} answered {cause.response.status_code}"

    # The one that is not an error at the transport layer at all. A host that answers
    # 200 with a non-JSON body - a proxy's "Not Found", an HTML login page - makes the
    # OpenAI client hand back the raw text instead of a completion, and the first thing
    # to touch it fails on an attribute. That is a wrong URL wearing a Python crash.
    if isinstance(cause, (AttributeError, TypeError)):
        return (
            f"the endpoint at {base_url} answered, but not with a chat completion. That "
            "address is probably not an OpenAI API base path"
        )
    if isinstance(cause, ValidationError):
        return (
            f"{model} answered, but not in the shape this asked for. A smaller model "
            "often cannot hold a format; try a larger one"
        )
    return None


class Provider(Protocol):
    name: str
    model: str
    base_url: str

    def complete(
        self,
        system: str,
        user: str,
        response_model: type[T],
        context: dict | None = None,
        max_retries: int | None = None,
    ) -> T: ...

    def describe_image(self, image: bytes, mime: str) -> str: ...


def get_vision_provider(local_only: bool = False) -> Provider:
    """The vision-capable provider that describes images at ingest (K.11).

    Same routing rule as `get_provider`: local-only images go to the local
    backend whatever the default is. The model is the separate vision setting - a
    backend that answers text and images with different models (Ollama's llava,
    an OpenRouter vision model) gets both here.
    """
    from .. import config, settings
    from .ollama import OpenAICompatibleProvider

    name = "ollama" if local_only else settings.get("llm_backend")
    backend = config.BACKENDS.get(name, config.BACKENDS["ollama"])

    url = settings.get("llm_url") if not local_only else config.BACKENDS["ollama"]["url"]
    return OpenAICompatibleProvider(
        model=settings.get("vision_model") if not local_only else config.VISION_MODEL,
        base_url=url or backend["url"],
    )


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
