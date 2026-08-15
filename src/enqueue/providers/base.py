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
        # OpenCode Go returns 401 (not 404) with a ModelError body when the model
        # name is not recognized; the SDK maps any 401 to AuthenticationError so
        # without this check a wrong model name reads as "rejected the API key"
        # when the key is valid. Inspect the body and name the real failure (FIX.3).
        go_note = _go_model_error_from_auth(cause, base_url, model)
        if go_note:
            return go_note
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


def _go_model_error_from_auth(cause, base_url: str, model: str) -> str | None:
    """If a 401 response body says ModelError, name the real failure (FIX.3).

    OpenCode Go returns 401 (not 404) with
    {"error":{"type":"ModelError","message":"Model X is not supported"}}
    for an unrecognized model name. The OpenAI SDK raises AuthenticationError
    for any 401, so without this check the translator says "rejected the API key"
    when the key is valid and the model name is the problem.
    """
    resp = getattr(cause, "response", None)
    if resp is None:
        return None
    try:
        body = resp.json()
    except Exception:
        return None
    inner = body.get("error", {}) if isinstance(body, dict) else {}
    if inner.get("type") != "ModelError":
        return None
    from .. import config

    msg = inner.get("message", "")
    # OpenCode Go message format: "Model X is not supported"
    model_from_msg = msg.replace("Model ", "").replace(" is not supported", "").strip()
    if model_from_msg in config.GO_UNSUPPORTED_SHAPE_MODELS:
        return (
            f"the model {model_from_msg!r} needs an API shape Enqueue does not "
            "speak yet. OpenCode Go serves it behind /responses or /messages, "
            "and Enqueue's adapter only speaks /chat/completions. Pick a "
            f"chat-completions model instead ({config.GO_CHAT_COMPLETIONS_EXAMPLES})."
        )
    # Unrecognized model name (e.g. 'deepseek/deepseek-v4-pro' with an OpenRouter prefix)
    return (
        f"the endpoint at {base_url} does not serve the model {model!r}. The key is "
        "valid, but that model name is not recognized - check the name in Settings. "
        f"The Go chat-completions models are: {config.GO_CHAT_COMPLETIONS_EXAMPLES}."
    )


def _check_go_model_shape(base_url: str, model: str) -> None:
    """FIX.3: refuse to call a Go model that needs /responses or /messages.

    OpenCode Go serves Grok 4.5, GPT 5.6 Luna, MiniMax, and Qwen behind API shapes
    that OpenAICompatibleProvider cannot reach (it only speaks /chat/completions).
    Intercept those names here so the person gets the real limitation instead of
    whatever HTTP error the server would throw - which can misread as an auth
    rejection. No-op for backends whose URL is not the Go endpoint.
    """
    from .. import config

    go_url = config.BACKENDS["opencode-go"]["url"]
    if base_url != go_url:
        return
    if model and model in config.GO_UNSUPPORTED_SHAPE_MODELS:
        raise ProviderError(
            f"the model {model!r} needs an API shape Enqueue does not speak yet. "
            "OpenCode Go serves it behind /responses or /messages, and Enqueue's "
            "adapter only speaks /chat/completions. Pick a chat-completions model "
            f"instead ({config.GO_CHAT_COMPLETIONS_EXAMPLES})."
        )


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
    if (
        name == "opencode"
    ):  # Stored Zen configs resolve to Go (Zen is still live, just not in this codebase).
        name = "opencode-go"
    backend = config.BACKENDS.get(name, config.BACKENDS["ollama"])

    # SET.1: the endpoint is implied by the backend. A named backend uses its own
    # URL, and a stored `llm_url` (a stale localhost from before) never overrides
    # it. Only `custom` reads the user-typed URL. Local-only always routes to the
    # local Ollama.
    if local_only:
        url = config.BACKENDS["ollama"]["url"]
    elif name == "custom":
        url = settings.get("llm_url") or backend["url"]
    else:
        url = backend["url"]
    return OpenAICompatibleProvider(
        model=settings.get("vision_model") if not local_only else config.VISION_MODEL,
        base_url=url,
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
    if (
        name == "opencode"
    ):  # Stored Zen configs resolve to Go (Zen is still live, just not in this codebase).
        name = "opencode-go"
    backend = config.BACKENDS.get(name, config.BACKENDS["ollama"])

    # SET.1: the endpoint is implied by the backend. A named backend uses its own
    # URL, and a stored `llm_url` (a stale localhost from before) never overrides
    # it. Only `custom` reads the user-typed URL. Local-only always routes to the
    # local Ollama.
    if local_only:
        url = config.BACKENDS["ollama"]["url"]
    elif name == "custom":
        url = settings.get("llm_url") or backend["url"]
    else:
        url = backend["url"]
    return OpenAICompatibleProvider(
        model=settings.get("llm_model") if not local_only else config.LLM_MODEL,
        base_url=url,
    )
