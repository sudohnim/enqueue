"""The engine's HTTP API, split into one router per domain (M.9).

`app` is the FastAPI application; `serve()` is the uvicorn entry point the CLI
and the desktop shell call. `list_artifacts` and `_bootstrap_index` are re-exported
for the tests that exercise them directly; the router modules are importable
from `enqueue.api.<domain>`.
"""

from .app import _bootstrap_index, _warm_embeddings, app, serve
from .artifacts import list_artifacts

__all__ = ["app", "serve", "list_artifacts", "_bootstrap_index", "_warm_embeddings"]
