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

# Sparse retrieval. Dense vectors blur proper nouns; this is what finds names.
SPARSE_MODEL = "Qdrant/bm25"

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
    "opencode": {
        "label": "OpenCode Zen",
        # opencode.ai/zen/v1, not api.opencode.ai/v1. The latter host resolves and
        # answers 200 with the plain text "Not Found" for every path, which is not an
        # HTTP error and so is not caught as one - the OpenAI client hands the body
        # back as a string and the first attribute access on it fails. Verified against
        # the live host: GET /zen/v1/models returns the model list as JSON.
        "url": "https://opencode.ai/zen/v1",
        "local": False,
        "key_var": "ENQ_LLM_API_KEY",
    },
    "custom": {
        "label": "Something else that speaks the OpenAI protocol",
        "url": "",
        "local": False,
        "key_var": "ENQ_LLM_API_KEY",
    },
}

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

# M0 runs Qdrant in process, at QDRANT_PATH. Set ENQ_QDRANT_URL to use a server instead.
#
# AGENTS.md specifies a sidecar because in-process mode is documented for roughly
# 20,000 points, and a real corpus passes that on day one. The POC runs on junk data
# well under the limit, and dropping the container removes a dependency that was
# costing more than it gave. Switch to the server before the corpus is real.
QDRANT_URL = os.getenv("ENQ_QDRANT_URL", "")
QDRANT_PATH = DATA_DIR / "qdrant-local"

API_HOST = "127.0.0.1"
API_PORT = 8787
API_URL = f"http://{API_HOST}:{API_PORT}"

# Facet eligibility. See docs/CURATION.md.
MIN_WORDS_FOR_FACETS = 40
SKIP_FACETS_FOR_FOLDERS = {"snippets", "biz_"}

RERANK_CONCURRENCY = 4
