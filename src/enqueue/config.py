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

# llama3.1:8b because it is already pulled. qwen2.5:7b-instruct is the better
# instruction follower for this task if it is ever worth the download; the coder
# variant is tuned for code and is the wrong shape for conceptual abstraction.
LLM_MODEL = os.getenv("ENQ_LLM_MODEL", "llama3.1:8b")

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
