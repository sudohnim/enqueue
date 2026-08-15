"""Constants only. No logic lives here.

Anything here can be overridden by an environment variable of the same name, so a
different model or endpoint never needs a code change.
"""

import os
from pathlib import Path

DATA_DIR = Path.home() / ".enqueue-poc"
DB_PATH = DATA_DIR / "enqueue.db"
BLOB_DIR = DATA_DIR / "blobs"

EMBED_MODEL = "BAAI/bge-base-en-v1.5"
EMBED_DIM = 768
EMBED_VERSION = "bge-base-en-v1.5"

# 127.0.0.1, never localhost. This machine runs a second Ollama in Docker bound to
# the IPv6 wildcard, and localhost resolves to IPv6 first. See docs/PROGRESS.md.
OLLAMA_URL = os.getenv("ENQ_OLLAMA_URL", "http://127.0.0.1:11434/v1")

# Named endpoints, so switching backend is a choice rather than a URL to remember.
# Everything here speaks the OpenAI-compatible protocol, which is the only reason one
# adapter covers all of them.
#
# Anything other than `ollama` sends the text of your artifacts to somebody else's
# computer. That is a real change in what this product is, so it is a deliberate
# selection and never a default, and `local_only` artifacts never take this path.
BACKENDS = {
    "ollama": {
        "label": "Ollama, on this machine",
        "url": "http://127.0.0.1:11434/v1",
        "local": True,
        "key_var": None,
    },
    "openrouter": {
        "label": "OpenRouter",
        "url": "https://openrouter.ai/api/v1",
        "local": False,
        "key_var": "ENQ_LLM_API_KEY",
    },
    "opencode-go": {
        "label": "OpenCode Go",
        # The Go subscription endpoint. Verified against the live host:
        # GET /zen/go/v1/models returns the model list as JSON with a Go key in the
        # Authorization header. OpenCode Zen (/zen/v1) is a separate, still-live
        # product with its own keys; SET2.1 narrowed the picker to Go-only.
        # Go models span three API shapes - /chat/completions, /responses, and
        # /messages - but only /chat/completions matches OpenAICompatibleProvider.
        # The other two shapes are a follow-on, not this fix (FIX.3).
        "url": "https://opencode.ai/zen/go/v1",
        "local": False,
        "key_var": "ENQ_LLM_API_KEY",
    },
}

# OpenCode Go models, classified by the API shape they require. The
# OpenAI-compatible adapter (OpenAICompatibleProvider) speaks only
# /chat/completions, so models from the other two shapes cannot be reached yet
# - full /responses or /messages support is a follow-on. Source: the live
# GET /zen/go/v1/models list and https://opencidi.ai docs/go endpoints.
GO_CHAT_COMPLETIONS_MODELS = frozenset(
    {
        "glm-5.2",
        "glm-5.1",
        "glm-5",
        "kimi-k3",
        "kimi-k2.7-code",
        "kimi-k2.6",
        "kimi-k2.5",
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "mimo-v2.5",
        "mimo-v2.5-pro",
        "mimo-v2-pro",
        "mimo-v2-omni",
        "hy3",
        "hy3-preview",
    }
)
GO_UNSUPPORTED_SHAPE_MODELS = frozenset(
    {
        "grok-4.5",
        "gpt-5.6-luna",
        "minimax-m3",
        "minimax-m2.7",
        "minimax-m2.5",
        "qwen3.7-max",
        "qwen3.8-max",
        "qwen3.7-plus",
        "qwen3.6-plus",
        "qwen3.5-plus",
    }
)

GO_CHAT_COMPLETIONS_EXAMPLES = "glm-5.2, kimi-k3, deepseek-v4-pro, mimo-v2.5, hy3"

LLM_BACKEND = os.getenv("ENQ_LLM_BACKEND", "ollama")

# llama3.1:8b because it is already pulled. It is a placeholder and it is bad at this:
# measured, three of four rerank judgments fail their validators. That is accepted for
# now. A real model gets pointed at when the POC is actually being judged.
#
# Nothing about swapping it is a code change. The adapter speaks the OpenAI-compatible
# protocol, so any endpoint that does too, including a hosted GLM, is these three
# variables:
#
#   ENQ_OLLAMA_URL=https://host/v1  ENQ_LLM_MODEL=glm-5.2  ENQ_LLM_API_KEY=...
LLM_MODEL = os.getenv("ENQ_LLM_MODEL", "llama3.1:8b")

# The vision model used to describe images at ingest (K.11). Distinct from the
# text model: most backends answer text with one model and images with another
# (Ollama: llava or moondream; a hosted endpoint: an OpenRouter vision model).
# When the configured backend has no such model, the describe step degrades
# gracefully and the image stays unsearchable rather than failing the capture.
VISION_MODEL = os.getenv("ENQ_VISION_MODEL", "llava")


def llm_api_key() -> str:
    """The key, resolved at call time rather than at import.

    Order: the environment, then the macOS Keychain, then a placeholder that Ollama
    ignores. It is a function because the Keychain can change while the engine is
    running - someone sets a key in Settings and expects the next question to work
    without restarting anything.
    """
    from_env = os.getenv("ENQ_LLM_API_KEY")
    if from_env:
        return from_env

    from . import keyring

    return keyring.get() or "ollama"


# Kept so existing imports keep working. Prefer `llm_api_key()`: this is bound once at
# import and will not see a key stored later.
LLM_API_KEY = os.getenv("ENQ_LLM_API_KEY", "ollama")

# Retries *after* the first attempt, so 1 means two tries. Kept low on purpose: a
# failed judgment is a dropped candidate rather than a crisis, and on a placeholder
# model most of them fail, so each extra retry buys almost nothing and costs a full
# generation. Set to 0 for the fastest, worst run.
_MODEL_RETRIES = os.getenv("ENQ_MODEL_RETRIES", "1")
try:
    MODEL_RETRIES = int(_MODEL_RETRIES)
except ValueError:
    MODEL_RETRIES = 1

# The vector store backend. sqlite-vec is the default: the index lives inside
# the SQLite file (one encrypted file later), search is exact, and there is no
# single-process directory lock. Read as ENQ_VECTOR_STORE; `get_store()`
# in index/store.py resolves it to an instance.
VECTOR_STORE = os.getenv("ENQ_VECTOR_STORE", "sqlite-vec")

API_HOST = "127.0.0.1"
API_PORT = 8787
API_URL = f"http://{API_HOST}:{API_PORT}"

# Facet eligibility. See docs/CURATION.md.
MIN_WORDS_FOR_FACETS = 40
SKIP_FACETS_FOR_FOLDERS = {"snippets", "biz_"}

# R.9 opt-in cross-encoder rerank stage over the fused free-text candidates.
# The reranker is a ~1 GB local model plus one inference pass per query, so it
# is never on by default - the fused hybrid has to earn this. Read as
# ENQ_SEARCH_RERANK; any of 1/true/yes/on flips it.
_SEARCH_RERANK = os.getenv("ENQ_SEARCH_RERANK", "").strip().lower()
SEARCH_RERANK = _SEARCH_RERANK in ("1", "true", "yes", "on")
