# Enqueue — implementation progress

Status: **Part 1 (Foundation) in progress**

## Plan

The implementation follows the plan in `~/Downloads/enqueue-plan/`.
Each phase below links to the relevant checkbox in the plan file.

---

## Phase 0 — Verify assumptions ✅

- [x] FTS5 available (confirmed)
- [x] sqlite-vec v0.1.9 works (confirmed)
- [x] Baseline measurements recorded
- [x] Synthetic test corpus generated (50 artifacts, `scripts/make_test_corpus.py`)

## Phase 1 — Test infrastructure ✅

- [x] **1A**: `scripts/make_test_corpus.py` — deterministic 50-artifact generator
- [x] **1B**: `enq test-corpus verify` — constraints verification
- [x] **1C**: `enq test-corpus load` — loads into isolated `evals/test-data/`
- [x] **1D**: `evals/queries.yaml` — 50 queries across 8 categories
- [x] **1E**: `enq eval` — scoring command with per-query pass/fail + aggregate metrics
- [x] **1F**: `evals/HUMAN-TEST-SEARCH.md` — human test protocol written

## Phase 2 — Baseline engine score ✅

- [x] `test-corpus load` now builds isolated Qdrant index (125 chunks, 125 vectors)
- [x] `enq eval` runs directly against test DB + test Qdrant (bypasses engine API)
- [x] Baseline recorded in `docs/decisions/baseline.md` and `evals/results/qdrant-baseline.json`

### Baseline results

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

- Title-only: 10/10 pass (perfect)
- Paraphrase: 10/10 pass (strong)
- Rare-string: 5/5 pass (perfect, sparse BM25 helps)
- Phrase: 5/5 pass
- Partial: 5/5 pass
- Vague-semantic: 4/6 pass (vague_06 fails)
- Regression (Epictetus/Hypatia): pass
- Nothing queries: 0/8 — all false positives (expected for pure vector search without score threshold)

## Next up

Phase 3 — Swappable engine interface (sqlite-vec integration).
Phase 4 — Encrypted sync.

## Phase 2A — Link body indexing ✅

Human search test Test 3 (Lumo mascot) exposed that saved links were searchable
only by preview metadata (title + description); anything in the article body
was unfindable. Fixed:

- [x] `preview.fetch()` extracts the article body (trafilatura, ≥200 chars) and
  stores it in `page_text` (page 0, extractor `trafilatura`)
- [x] `chunk_artifact` prefers the body for links, falls back to the four
  preview fields when extraction yields nothing
- [x] `needs_fetch()`: links with a preview but no body are refetched on the
  next ingest pass, so existing links heal themselves
- [x] Hard rule 6: body text goes through the same secret scan as all other text
- [x] Tests: 6 new (extraction quality, script-shell refusal, full fetch path,
  chunk-from-body, needs_fetch states)
- [x] Verified against the real Proton Lumo article: 7,172 chars extracted
  containing "mascot", "kitten", "Lumo"

Networking is unchanged: the page was already fetched for previews; now its
body is kept instead of discarded. `local_only` and `auto_preview=off` links
still never fetch.

## Phase 2A-followup — Queue blocked behind slow embedding ✅

Verifying the Lumo fix in the running app exposed a second, pre-existing bug:
`saved link not searchable` was not just the missing body — the ingest queue
never drained, so the refetched body was never indexed.

Root cause: the serial queue + CPU embedding (bge-base-en-v1.5, ~0.6 s/chunk on
this machine). A 363-chunk PDF added by the human test blocked the entire queue
for 8–15 minutes; new saves and backfilled link bodies waited behind it.

Fix (`dfa0944`):

- [x] `embed._providers()`: CoreMLExecutionProvider first, CPU fallback
      (`ENQ_EMBED_PROVIDERS` overrides)
- [x] CoreML vectors are bit-identical to CPU (max abs diff 0.0), so the
      retrieval baseline is untouched — verified: eval 41/50, R@1 0.700,
      MRR 0.893, identical to `qdrant-baseline.json`
- [x] `onnxruntime` promoted to a direct dependency (imported directly)
- [x] Verified live: `reprocess` drains in ~3.6 min (was: effectively never),
      and search "Lumo mascot" returns the article at score 1.000

Trafilatura-embedded text is unchanged; this is purely an inference-provider
speedup.

## Phase 3 — Swappable engine interface ✅

`qdrant_client` now appears in exactly one file. Everything else goes through
`get_store()`.

- [x] `src/enqueue/index/store.py`: `VectorStore` ABC (`ensure`, `reset`,
      `upsert_chunks`, `upsert_facets`, `drop_artifact`, `index_artifact`,
      `search`, `search_dense`, `counts`) + `@lru_cache` `get_store()` factory
      reading `config.VECTOR_STORE` (`ENQ_VECTOR_STORE`, default `qdrant`)
- [x] `src/enqueue/index/store_qdrant.py`: `QdrantStore` with the old qdrant.py
      logic copied verbatim; per-instance `lru_cache` client so the eval can
      repoint at a test index via `get_store.cache_clear()`
- [x] `git rm src/enqueue/index/qdrant.py`; callers updated: `api.py`,
      `chats.py`, `retrieve/candidates.py`, `cli.py` (corpus load + eval),
      `trash.py`, `ingest/queue.py`; tests patch
      `enqueue.index.store.get_store`
- [x] `enq eval` and `enq eval --ablation` produce per-query results identical
      to `qdrant-baseline.json` and `qdrant-ablation.json` (latency jitter
      excepted) — recorded as `evals/results/qdrant-via-interface.json`
- [x] 102 tests pass; ruff + pyright clean across `src/` and `tests/`
      (including pre-existing blockers: capture `int(local_only)`, ollama
      generic `complete() -> T`, migrations spec asserts, provider overrides)

Behavior unchanged. The engine interface is now a config change, not a rewrite.

## Phase 4 — Export, the escape hatch ✅

`enq export <dir>` writes the library as plain files. No database, key, or
enqueue-specific software is needed to read them back.

- [x] One markdown file per artifact: notes carry their body, links their
      saved text (`page_text` page 0), captures reference their copied bytes
- [x] Annotations inline (superseded ones marked); each exhibit gets its own
      file listing members with placard, evidence, and strength
- [x] Capture blobs copied to `files/` next to the markdown
- [x] Idempotent by content: re-runs write nothing when nothing changed;
      files a previous export wrote that left the library are pruned
- [x] `enq export --verify` reports whether every non-deleted artifact appears
      in the output (exit 1 when incomplete)
- [x] Tests: full write + idempotency, verify tracking a newly saved artifact,
      stale-file pruning, and the headline property — the export stays
      readable and complete after the entire database is deleted
- [ ] `[HUMAN]` maintainer confirms export output is genuinely readable
      (delegated to the assistant; verified mechanically + live: 22 artifacts
      exported, re-run writes 0 files, `--verify` complete)

Live demo against the real library: 22 artifacts, 11 capture files copied,
README index, Lumo article body present in its markdown.
