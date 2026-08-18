"""The FastAPI app: routers assembled in route order, plus the startup path.

`app` is constructed at import time so `from enqueue.api import app` (the
tests) and the OpenAPI schema work without booting the server. `serve()` is
the uvicorn entry point the CLI and the desktop shell call; it does the
startup housekeeping (trash purge, orphan sweep, embedding warm-up, index
bootstrap) and then blocks on the server.
"""

from __future__ import annotations

from fastapi import FastAPI

from .. import chats_worker, config, trash
from . import admin, artifacts, chats, pivots, search, settings, static, write


def create_app() -> FastAPI:
    app = FastAPI(title="Enqueue engine", version="0.2.0")
    # Router order is route order: it is what the OpenAPI paths render in.
    app.include_router(static.router)
    app.include_router(artifacts.router)
    app.include_router(write.router)
    app.include_router(admin.router)
    app.include_router(search.router)
    app.include_router(chats.router)
    app.include_router(settings.router)
    app.include_router(pivots.router)
    return app


app = create_app()


def serve() -> None:
    import uvicorn

    # QR.1: load the DEK from the Keychain/file so sync is unlocked with no
    # prompt after a restart. A missing DEK just means sync stays paused until
    # the recovery phrase is used or the keyring is re-initialized.
    try:
        from .. import keyring_file

        if keyring_file.load_dek_from_keychain() is not None:
            print("[engine] sync keyring unlocked from the Keychain")
    except Exception as exc:  # noqa: BLE001 - never block startup on this
        print(f"[engine] could not auto-load the sync keyring: {exc}")

    try:
        expired = trash.purge_expired()
        if expired["purged"]:
            print(f"[engine] purged {expired['purged']} artifact(s) past the trash window")
    except Exception as exc:  # noqa: BLE001 - never block startup on housekeeping
        print(f"[engine] could not purge the trash: {exc}")

    # Answers interrupted by a restart left pending rows that no worker will ever
    # finish (the in-memory queue died with the old process). Rule 2: a pending
    # turn always resolves, so sweep them to `failed` with a reason a person can
    # read and retry (H5.1).
    try:
        orphaned = chats_worker.sweep_orphaned_pending()
        if orphaned:
            print(f"[engine] interrupted {orphaned} answer(s) from the previous run")
    except Exception as exc:  # noqa: BLE001 - never block startup on housekeeping
        print(f"[engine] could not sweep interrupted answers: {exc}")

    _warm_embeddings()

    _bootstrap_index()

    _start_sync_worker()

    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT, log_level="warning")


def _start_sync_worker() -> None:
    """Start the background sync worker (SYNC.5) when a relay is configured.

    `start()` is a no-op when `sync_relay_url` is empty, so this is always safe.
    """
    try:
        from ..sync.worker import start

        start()
    except Exception as exc:  # noqa: BLE001 - sync is additive; never block startup
        print(f"[engine] could not start the sync worker: {exc}")


def _warm_embeddings() -> None:
    """Load the embedding model in the background so the first search is not cold.

    The dense model loads lazily on its first use, which is ~2.9 s on this machine
    (ONNX plus the CoreML session). Nothing at startup touches it when the index is
    already current, so that whole cost landed on the person's first search. A person
    looks at the wall before they search, so warming here on a daemon thread hides it
    behind that gap. It never blocks the engine: a failure is a slower first query,
    not an error.
    """
    import threading

    def _warm() -> None:
        try:
            from ..index.embed import embed_one

            embed_one("warm")
        except Exception as exc:  # noqa: BLE001 - a cold first query is the worst case
            print(f"[engine] embedding warm-up skipped: {exc}")

    threading.Thread(target=_warm, name="embed-warm", daemon=True).start()


def _bootstrap_index() -> None:
    """Make the index exist and be current on startup, without blocking it.

    The version compare (Phase 21) happens here: if `index_meta` has no
    embedding version, or its version no longer matches the running model, a
    background rebuild starts and search is blocked until it completes. If
    the index is already current, nothing starts and search is live from the
    first request. A failed rebuild leaves search blocked (no silent
    fallback) and prints to the engine log.
    """
    from ..index.bootstrap import remove_legacy_qdrant_dir, start_rebuild_if_needed

    def _progress(indexed: int, total: int) -> None:
        print(f"[engine] building search index: {indexed}/{total} rows", flush=True)

    if start_rebuild_if_needed(on_progress=_progress):
        print(
            "[engine] search index rebuilding in the background; "
            "search is enabled when it completes",
            flush=True,
        )

    # The cutover: the new index now lives inside enqueue.db, so a leftover
    # qdrant-local directory is dead data. Remove it once a run has confirmed
    # the sqlite-vec index (the check above), and log what was deleted.
    removed = remove_legacy_qdrant_dir()
    if removed:
        if "error" in removed:
            print(
                f"[engine] could not remove the legacy qdrant index at "
                f"{removed['path']}: {removed['error']}",
                flush=True,
            )
        else:
            print(
                f"[engine] removed the legacy qdrant index at {removed['path']} "
                f"({removed['files']} files, {removed['bytes'] / 1024:.0f} KiB); "
                "the search index now lives inside enqueue.db",
                flush=True,
            )
