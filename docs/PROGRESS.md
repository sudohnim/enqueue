# Enqueue — implementation progress

Status: **Part 2 (Lens view) DONE** (lens wall UI reverted by maintainer decision - backend API-only; UI recoverable from commit 2cd2390) - phases 5-17 complete; open [HUMAN] items: evals/lens/topics.yaml, the D4 threshold pick, and the human lens test (evals/lens/HUMAN-TEST-LENS.md)

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

## Phase 5 — Record the curate pipeline ✅

`docs/decisions/lens-view.md` records the four-stage pipeline
(expand → candidates → rerank → synthesise), the observed expansion width
(9 queries), candidates defaults (`limit=150`, `per_query=40`), the rerank
return shape, and the wall's ordering modes (default: `touched`).

- [x] Before number: one full `curate()` on 100 artifacts took **1048 s**
      (~17.5 min) and 53 model calls (1 expand + 52 judgments); 29/52
      judgments failed schema validation (`strength` null) and dropped
      silently. This is the number Phases 7-9 exist to bound.
- [x] Stale `ORDERINGS` comment fixed: it claimed `ingested` was the default;
      the endpoint always defaulted to `touched`.

## Phase 6 — Stop discarding information already computed ✅

`rerank()` no longer throws away what it paid for:

- [x] `rejected` is now a list of `{artifact_id, reason}` (reason when the
      judgment gave one); the integer count lives on as `rejected_count`
- [x] `relevant` returns the full passing list before `belongs[:keep]`
      truncation; `kept` stays the truncated list
- [x] `failed_ids` lists artifacts whose judgment call errored, next to the
      existing `failed` count
- [x] `Judgment` gains an optional `reason`; the RERANK prompt asks for it on
      no-verdicts
- [x] Conservation test: `len(relevant) + len(rejected) + len(failed_ids) ==
      considered` passes for every partitioning
- [x] Wall UI reads `rejected_count` (it rendered the old number as `N
      rejected`, which now needs the explicit count field)

## Phase 7 — Score every artifact cheaply, no model calls ✅

`score_all(lens) -> dict[str, float]` in `retrieve/score.py`: one relevance
score per non-deleted artifact via the Part 1 `VectorStore` interface, using
the same rollup as the curate path. Zero is a score, not an omission — every
artifact gets an entry.

- [x] No language model anywhere in the file; the search limit is read from
      the chunk and artifact counts so the whole library is covered
- [x] Provisional `LENS_SCORE_THRESHOLD = 0.1` (env `ENQ_LENS_SCORE_THRESHOLD`),
      above the bulk hybrid-score noise (p75 ~0.06) on this corpus; marked
      provisional, tuned in Phase 13 against D4
- [x] Timings (Apple Silicon, CoreML embed, local Qdrant): **55.6 ms** on the
      100-artifact library, **59.6 ms** on the 50-artifact eval corpus — both
      under the one-second gate
- [x] Tests: one entry per artifact, trashed artifacts excluded, provider
      bomb proves zero model calls, unchunked artifact scores exactly zero

## Phase 8 — Remember judgments so the same topic is instant next time ✅

- [x] Migration `0009` creates `lens_judgments`: `lens_key`, `artifact_id`,
      `belongs`, `strength`, `placard`, `evidence`, `model_version`,
      `created_at`; primary key is `(lens_key, artifact_id, model_version)`
      with an index on `lens_key`
- [x] `lens_key()` in `retrieve/judgments.py`: lowercase, trimmed,
      whitespace-collapsed, sha256-hashed; capitalization/spacing variants
      produce the same key (tested)
- [x] `rerank._judge` consults the cache before calling the provider and
      writes successful judgments through; a row for a different
      `model_version` is treated as absent, so a model switch re-judges
- [x] Staleness: the cache-hit rebuild re-validates the evidence verbatim
      against the current artifact text, so an edited artifact falls through
      to a fresh judgment; the lens is deliberately absent from the rebuild
      context because the lens-word placard gate is a quality rule, not a
      staleness signal
- [x] `enq lens-cache clear` and `enq lens-cache stats` (thin CLI over
      `POST /lens-cache/clear`, `GET /lens-cache/stats`)
- [x] Tests: key normalization, zero-call replay, re-judge on model change,
      stale-row fallthrough, clear. Test scripts now key by artifact id: the
      thread pool exposed a latent pop-order race in the list-based scripted
      providers

Note: the running engine predates this phase; restart it (`bin/relaunch`) for
the cache to go live.

## Part 3 — sqlite-vec engine migration (in progress)

## Phase 18A — Index tables inside the database ✅

Migration `0010` moves the search index into the SQLite file that already
holds the library:

- [x] `vec_chunks` / `vec_facets` — sqlite-vec `vec0` virtual tables, each
      with a TEXT primary key (`chunk_id` / `facet_id`) and an embedding of
      length `EMBED_DIM` (768)
- [x] `fts_chunks` / `fts_facets` — FTS5 virtual tables indexing one text
      column with the id as an unindexed reference column
- [x] `index_meta` — key/value table to hold the embedding version
- [x] The migration loads the sqlite-vec extension on the alembic connection
      for both upgrade and downgrade (dropping a `vec0` table also needs the
      module), and everything uses `IF NOT EXISTS` so the store's `ensure()`
      and alembic never fight on a fresh database
- [x] `sqlite-vec` moved from dev extras into the main dependencies: the
      migration runs at app startup
- [x] Verified forward and backward on a copy of the real database (22
      artifacts, 464 chunks): upgrade to head, downgrade to 0009, re-upgrade
      — data preserved; `test_index_revision_round_trips` pins the cycle

Tests: 6 migration tests pass.

## Phase 18B — Fusion function, on its own ✅

`src/enqueue/index/fusion.py` holds reciprocal rank fusion as a pure function
with zero imports from the rest of the app:

- [x] `rrf(*ranked_lists, k=60, limit=30)` — ids in rank order in, fused id
      list out; score per id is the sum of 1/(k + rank) across lists; ties
      break by first appearance so the same input always yields the same
      output
- [x] `rrf_scored` also returns each id's fused score, so the store can tag
      hits with a branch-agnostic score and the formula lives in one place
- [x] Tests: one list, two identical lists, two disjoint lists (tie-break),
      two lists sharing one id, limit truncation, determinism across runs,
      and a scored-variant check against the hand-computed formula

Tests: 7 fusion tests pass.
