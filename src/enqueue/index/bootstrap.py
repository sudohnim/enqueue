"""Index bootstrap: make sure the search index exists at startup.

A fresh install has the index tables (migration 0010) but no vectors and no
recorded embedding version. An install upgrading from the Qdrant era has
chunks and facets in SQLite but no sqlite-vec vectors either, and no
recorded version. Both are caught the same way: if `index_meta` has no
`embed_version`, rebuild both collections now, so search works on the first
request with no manual `enq reindex`.

`index_meta` is a plain table, so reading it goes through `db.get_conn` and
does not need the sqlite-vec extension. The rebuild itself goes through the
configured `VectorStore`, the same path `enq reindex` uses, so the engine is
never rebuilt two different ways.

Phase 21 extends this to a version mismatch (the recorded version differs
from `config.EMBED_VERSION`): block search and rebuild. Here we only handle
"never built". Adding the mismatch case is a one-line change to
`needs_reindex` once it lands.
"""

from __future__ import annotations

from collections.abc import Callable

from .. import db
from .store import VectorStore, get_store


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
    """True if the index has never been built (no embed version recorded)."""
    return read_embed_version() is None


def rebuild_index(store: VectorStore) -> dict:
    """Rebuild both collections and record the embed version.

    The store clears each collection before inserting (idempotent), so an
    interrupted rebuild is repaired on the next run with no duplicated rows.
    `write_embed_version` runs only after both collections finish, so a
    half-updated index never claims a version.

    Returns per-collection counts plus the table counts, for callers that
    report what they did.
    """
    chunks = store.upsert_chunks()
    facets = store.upsert_facets()
    store.write_embed_version()
    return {"chunks": chunks, "facets": facets, "counts": store.counts()}


def ensure_index(on_progress: Callable[[int, int], None] | None = None) -> bool:
    """Build the index once at startup if it has never been built.

    Returns True if a rebuild ran, False if the index was already built. Safe
    to call repeatedly: once the embed version is recorded this is a cheap
    read and a no-op.

    The store is created with `on_progress` so a rebuild prints row progress;
    the cache is cleared afterward so the long-lived search path hands out a
    store without a progress callback, one instance for the process.
    """
    if not needs_reindex():
        return False
    rebuild_index(get_store(on_progress=on_progress))
    get_store.cache_clear()
    return True
