"""Index bootstrap: make sure the search index exists and is current.

A fresh install has the index tables (migration 0010) but no vectors and no
recorded embedding version. An install upgrading from the Qdrant era has
chunks and facets in SQLite but no sqlite-vec vectors either. And an install
indexed with an older embedding model has a recorded version that no longer
matches `config.EMBED_VERSION`. All three are caught the same way: if the
recorded version differs from the running one, rebuild both collections, and
block search until the rebuild completes so results are never served from an
out-of-date index (Phase 21).

`index_meta` is a plain table, so reading it goes through `db.get_conn` and
does not need the sqlite-vec extension. The rebuild itself goes through the
configured `VectorStore`, the same path `enq reindex` uses, so the engine is
never rebuilt two different ways.
"""

from __future__ import annotations

import shutil
import threading
from collections.abc import Callable

from .. import config, db
from .store import VectorStore, get_store

# The in-process index lifecycle. Search is gated on this: the state must be
# "ready" AND the recorded version must match before a single result is
# served. serve() starts a rebuild thread when the version is missing or
# stale; the rebuild flips the state to "ready" only after the version is
# written, so a half-updated index never serves results and there is no
# silent fallback.
_state_lock = threading.Lock()
_state = {"state": "building", "progress": None}  # state: building | ready | failed


def index_state() -> dict:
    """The rebuild lifecycle: `{"state": ..., "progress": (done, total) | None}`.

    `state` is one of "building", "ready", or "failed". Starts "building"
    so any search before bootstrap is safe by default.
    """
    with _state_lock:
        return dict(_state)


def _set_state(state: str, progress: tuple[int, int] | None = None) -> None:
    with _state_lock:
        _state["state"] = state
        _state["progress"] = progress


def search_allowed() -> bool:
    """Search may read the index only when it is built and current.

    Requires both the in-process lifecycle to be "ready" and the recorded
    version to still match the running model. A mismatch that appears while
    the engine is up blocks search the same way a missing index does.
    """
    with _state_lock:
        if _state["state"] != "ready":
            return False
    return not needs_reindex()


def read_embed_version() -> str | None:
    """The embedding version the index was built at, or None if never built.

    `index_meta` is a plain SQLite table, so this read does not load the
    sqlite-vec extension. A row that was written for a different config
    version is still "built"; whether it matches is `needs_reindex`'s call.
    """
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT value FROM index_meta WHERE key = 'embed_version'").fetchone()
        return row["value"] if row else None
    finally:
        conn.close()


def needs_reindex() -> bool:
    """True when the index is missing or built with a stale embedding version.

    The recorded version is the "index exists" signal. A missing row and a
    row that does not match `config.EMBED_VERSION` both mean the index cannot
    serve results for this run: they differ from another device's results,
    which is exactly what Phase 21 forbids.
    """
    return read_embed_version() != config.EMBED_VERSION


def rebuild_index(store: VectorStore) -> dict:
    """Rebuild all three collections and record the embed version.

    The store clears each collection before inserting (idempotent), so an
    interrupted rebuild is repaired on the next run with no duplicated rows.
    `write_embed_version` runs only after both collections finish, so a
    half-updated index never claims a version.

    Returns per-collection counts plus the table counts, for callers that
    report what they did.
    """
    chunks = store.upsert_chunks()
    facets = store.upsert_facets()
    entities = store.upsert_entities()
    store.write_embed_version()
    return {
        "chunks": chunks,
        "facets": facets,
        "entities": entities,
        "counts": store.counts(),
    }


def rebuild_now(on_progress: Callable[[int, int], None] | None = None) -> dict:
    """Rebuild both collections now, blocking search until it completes.

    The lifecycle is "building" for the whole rebuild, so `search_allowed`
    is False and no request can read a half-updated index. The state flips
    to "ready" only after `write_embed_version` ran; on failure it flips to
    "failed" and search stays blocked (no silent fallback).

    Returns per-collection counts plus the table counts.
    """
    _set_state("building")
    try:
        result = rebuild_index(get_store(on_progress=on_progress))
        get_store.cache_clear()
        _set_state("ready")
        return result
    except Exception:
        _set_state("failed")
        raise


def ensure_index(on_progress: Callable[[int, int], None] | None = None) -> bool:
    """Build the index synchronously if it is missing or stale.

    Returns True if a rebuild ran, False if the index was already current.
    Tests and one-shot callers use this; serve() uses
    `start_rebuild_if_needed` so the app stays up during a rebuild.
    """
    if not needs_reindex():
        _set_state("ready")
        return False
    rebuild_now(on_progress)
    return True


def start_rebuild_if_needed(
    on_progress: Callable[[int, int], None] | None = None,
) -> bool:
    """Start a background rebuild when the index is missing or stale.

    Returns True when a rebuild thread was started, False when the index is
    already current (the state flips to "ready" in that case). Search is
    blocked until the rebuild completes and the version is written; a failed
    rebuild leaves the state "failed" and search blocked, so results are
    never served from an out-of-date index.
    """
    if not needs_reindex():
        _set_state("ready")
        return False
    _set_state("building")
    print("[engine] building search index...", flush=True)

    def _progress(indexed: int, total: int) -> None:
        _set_state("building", (indexed, total))
        if on_progress:
            on_progress(indexed, total)

    def _run() -> None:
        try:
            rebuild_index(get_store(on_progress=_progress))
            get_store.cache_clear()
            _set_state("ready")
            print("[engine] search index ready", flush=True)
        except Exception as exc:  # noqa: BLE001 - a failure must not take the engine down
            _set_state("failed")
            print(f"[engine] search index rebuild failed: {exc}", flush=True)

    threading.Thread(target=_run, name="index-rebuild", daemon=True).start()
    return True


def remove_legacy_qdrant_dir() -> dict | None:
    """Delete the pre-cutover Qdrant data directory, once.

    The old engine kept its vector index at `DATA_DIR/qdrant-local`. After
    the cutover the index lives inside enqueue.db, so a leftover directory is
    dead data. Returns a small report of what was removed, or None when there
    was nothing to remove. Never raises: cleanup must not block startup.
    """
    legacy = config.DATA_DIR / "qdrant-local"
    if not legacy.exists():
        return None
    try:
        files = [p for p in legacy.rglob("*") if p.is_file()]
        size = sum(p.stat().st_size for p in files)
        shutil.rmtree(legacy)
        return {"path": str(legacy), "files": len(files), "bytes": size}
    except OSError as exc:
        return {"path": str(legacy), "error": str(exc)}
