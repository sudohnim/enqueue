# Baseline measurements

Recorded during Phase 0, Part 1 of the implementation plan.

## Library size

| Metric | Value |
| --- | --- |
| Artifact count | 14 |
| Chunks (SQLite) | 45 |
| Vector points (Qdrant chunks) | 51 |
| Vector points (Qdrant facets) | 0 |
| Chats | 1 |
| Link previews | 5 |
| Artifact versions | 9 |
| Annotations | 0 |
| Exhibits | 0 |

## On-disk size

| Location | Size |
| --- | --- |
| SQLite database (`~/.enqueue-poc/enqueue.db`) | 316 KB |
| Qdrant index (`~/.enqueue-poc/qdrant-local/`) | 457 KB |
| Blobs (`~/.enqueue-poc/blobs/`) | 6.0 MB |
| **Total** | **6.8 MB** |

## FTS5 availability

FTS5 is available (returns 1):

```
sqlite3 :memory: "SELECT sqlite_compileoption_used('ENABLE_FTS5');"
```

The app uses Python's bundled SQLite (version 3.53.3, via `import sqlite3`),
which includes FTS5 support.

## sqlite-vec compatibility

sqlite-vec v0.1.9 was installed and verified:

- Extension loading via `conn.load_extension()` works when pointed at the
  bundled `vec0.dylib` in `.venv/lib/python3.12/site-packages/sqlite_vec/vec0.dylib`.
- Creating a `vec0` virtual table, inserting vectors, and querying by distance
  all succeed.
- This confirms sqlite-vec can be wired into the app's existing SQLite connection
  setup as a drop-in extension.

## Search infrastructure

Search currently uses:

1. **Qdrant** (in-process, local mode) for hybrid search: dense embeddings
   via fastembed (BAAI/bge-base-en-v1.5) + sparse BM25.
2. **SQLite FTS5** (available, but not currently wired into the retrieve pipeline;
   search goes through Qdrant only).
3. The retrieve pipeline is in `src/enqueue/retrieve/`: expand → candidates →
   rerank → synthesise.
