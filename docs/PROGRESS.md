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

But first: **[HUMAN]** — maintainer runs `evals/HUMAN-TEST-SEARCH.md` and records answers.
