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

## Eval results — Qdrant baseline (hybrid search)

Recorded with `enq eval --json-path evals/results/qdrant-baseline.json` on
50 test queries from `evals/queries.yaml` against the synthetic test corpus
(50 artifacts, 125 chunks, 125 Qdrant vector points).

| Metric | Value |
| --- | --- |
| Total queries | 50 |
| Pass | 41 / 50 (82%) |
| Recall@1 | 0.700 |
| Recall@10 | 0.820 |
| MRR (non-zero) | 0.893 |
| Nothing-OK | 0/8 |
| p50 latency | 14 ms |
| p95 latency | 26 ms |

### Observations

- **Title-only queries (10/10 pass)**: Perfect. Every exact title match returns
  the correct artifact at rank 1.
- **Paraphrase queries (10/10 pass)**: Strong. Dense embeddings capture semantic
  overlap even when the search text doesn't match the title exactly.
- **Rare-string queries (5/5 pass)**: Perfect. The sparse BM25 component handles
  proper nouns and rare terms well.
- **Phrase queries (5/5 pass)**: Perfect.
- **Partial queries (5/5 pass)**: Perfect.
- **Vague-semantic queries (4/6 pass)**: vague_06 fails — the query is too
  semantically distant from any artifact. The other 5 resolve correctly due to
  sparse BM25 overlap with chunk content.
- **Regression (regr_01, pass)**: The Epictetus/Hypatia regression is fixed by
  prepending the title to chunk text during indexing.
- **Nothing queries (0/8 pass)**: All 8 return false positives. This is inherent
  to vector search without a minimum score threshold — Qdrant always returns
  the top-k closest vectors even when none are relevant. A score-threshold
  filter in the reranker would fix this.

### Score threshold recommendation

Plan part-1-foundation Phase 13 ([HUMAN]) quantifies the medium-relevance cutoff
for the topic view. Once a score threshold is chosen (e.g., cosine similarity
≥ 0.30), the same threshold can be applied to search results to suppress
irrelevant hits, fixing the nothing-query false positives.

Until then, the 0/8 nothing-OK score is an expected limitation of pure vector
search, not a regression.
