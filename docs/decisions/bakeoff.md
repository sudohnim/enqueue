# Bake-off: Qdrant vs sqlite-vec (Phase 19)

Measured on the synthetic eval corpus (50 artifacts, 125 chunks) in
`evals/test-data/`, built by `enq test-corpus load` and indexed by both
engines from the same chunk rows. Qdrant baseline figures come from Part 2
(`evals/results/qdrant-baseline.json`, `docs/decisions/baseline.md`).

## Verdict

**No regression, cut over is safe on retrieval numbers.** sqlite-vec beats
the Qdrant baseline on recall@1, recall@10, MRR, p95 latency, and
`score_all` duration; lens placement at the operating threshold is within
2.2 percent of baseline (under the 5 percent gate). p95 latency is 21 ms,
well under the 150 ms gate, so no quantization is needed. The [HUMAN]
gates did not trigger.

## Eval results (50 queries, `enq eval`)

| Metric | Qdrant (baseline) | sqlite-vec | delta |
| --- | --- | --- | --- |
| Pass | 41 / 50 | 42 / 50 | +1 |
| Recall@1 | 0.700 | 0.740 | +0.040 |
| Recall@10 | 0.820 | 0.840 | +0.020 |
| MRR (non-zero) | 0.8931 | 0.901 | +0.008 |
| Empty-result count (nothing-OK) | 0 / 8 | 0 / 8 | same |
| p50 latency | 14 ms | 15 ms | +1 ms |
| p95 latency | 26 ms | 21 ms | -5 ms |

Per-query: sqlite-vec fails only the 8 "nothing" queries (expected false
positives for pure top-k search, identical to Qdrant) and fixes `vague_06`,
which Qdrant missed. There are zero new failures. The `regression` category
query `regr_01` (Epictetus/Hypatia, title-prepend regression) passes on both
engines.

## Ablation (dense-only vs hybrid, `enq eval --ablation`)

| Metric | qdrant-dense | sqlite-vec-dense | sqlite-vec hybrid |
| --- | --- | --- | --- |
| Recall@1 | 0.720 | 0.720 | 0.740 |
| Recall@10 | 0.840 | 0.840 | 0.840 |
| MRR | 0.8808 | 0.881 | 0.901 |
| p50 / p95 | 11 / 17 ms | 12 / 16 ms | 15 / 21 ms |

Dense-only is indistinguishable across engines; the hybrid gap comes from
sqlite-vec's FTS5 BM25 branch. Saved to `evals/results/sqlite-vec-ablation.txt`.

## Lens placement accuracy (`enq lens-eval --corpus`)

Correct placement share of artifacts that genuinely belong in "related", by
score threshold. The operating threshold is 0.1 (provisional D4 pick).

| Threshold | Qdrant | sqlite-vec | delta |
| --- | --- | --- | --- |
| 0.05 | 0.933 | 0.933 | 0.000 |
| 0.10 | 0.933 | 0.911 | -0.022 |
| 0.20 | 0.867 | 0.844 | -0.023 |
| 0.30 | 0.844 | 0.844 | 0.000 |
| 0.50 | 0.644 | 0.533 | -0.111 |

At the operating threshold the drop is 2.2 percent, inside the 5 percent
gate. False positives in "related" (wrong_in_related) are lower on
sqlite-vec at every threshold (0.071 vs 0.093 at 0.10).

## score_all duration

Whole-library relevance scoring (`score_all`, Phase 7) on the 50-artifact
corpus:

| Engine | Duration |
| --- | --- |
| Qdrant (Part 2, Phase 7) | 59.6 ms |
| sqlite-vec (this run) | 23-25 ms |

sqlite-vec is roughly 2.5x faster; the brute-force vector scan and FTS5
keyword query in one SQLite file beat qdrant's local-mode fusion plumbing at
this library size.

## On-disk size

| Location | Size |
| --- | --- |
| Qdrant index (`test-data/qdrant/`) | 2.1 MB (separate directory) |
| SQLite database (`test-data/enqueue.db`) | 5.0 MB (library + vec/FTS index in one file) |

The sqlite-vec story is "one file": the index lives inside the database, so
there is no separate index directory to keep in sync, back up, or lose. The
database includes the 50-artifact library content that Qdrant does not
store, so the raw sizes are not index-for-index comparable; the point is the
layout, not the byte count.

## Score-scale decision (why k=1)

The first lens-eval run on sqlite-vec placed nothing above threshold 0.05.
Not a retrieval failure: rankings were correct, but the store's fused scores
lived on a `k=60` RRF scale (maximum ~0.033) while the Qdrant backend's
fusion emits scores on a `1/(rank+1)` scale (Qdrant's local RRF computes
`1/(pos + k)` over 0-based positions with `k=2`, i.e. `1/(rank+1)` per list;
verified in `qdrant_client/hybrid/fusion.py`). The lens threshold was
calibrated on Qdrant's scale, so the sqlite-vec store now fuses with `k=1`,
which reproduces Qdrant's scale exactly. RRF ordering is invariant to `k`,
so this changed magnitudes only, never rankings.

## Latency gate

p95 latency is 21 ms, far below the 150 ms gate; no quantization pass was
needed.

## Open [HUMAN] items

- `evals/HUMAN-TEST-SEARCH.md` against the new engine: a person records the
  answers next to the baseline. Not fabricated here by policy.
- `evals/lens/HUMAN-TEST-LENS.md` and the D4 threshold pick remain open from
  Part 2.
