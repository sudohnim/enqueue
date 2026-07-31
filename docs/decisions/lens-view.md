# The lens view: design record

How the topic view works, what the engine already did before this part, and the
decisions that bound its cost. Written during Part 2, Phase 5.

## The pipeline (what `POST /curate` does today)

Order: `expand -> candidates -> rerank -> synthesise`.

1. **expand** (`src/enqueue/retrieve/expand.py`): turns the lens into search
   queries. Returns `[lens, *restatements, *passages]`. `LensExpansion` is
   validated to 3-8 restatements plus passages; one observed call produced 9
   queries total (lens + 5 restatements + 3 passages). Falls back to the bare
   lens when the model call fails.
2. **candidates** (`src/enqueue/retrieve/candidates.py`): vector + keyword
   search over chunks and facets, rolled up to artifact ids. Defaults:
   `limit=150`, `per_query=40` per query, best score wins per artifact.
   Facet hits are weighted by the facet's trust score.
3. **rerank** (`src/enqueue/retrieve/rerank.py`): one judgment call per
   candidate, bounded concurrency (`RERANK_CONCURRENCY=4`), retries low
   (`ENQ_MODEL_RETRIES`, default 1). Returns a dict with exactly:
   - `kept`: the passing artifacts, sorted by strength descending, then
     truncated to `belongs[:keep]`. Artifacts that passed the relevance check
     but ranked below the cutoff are discarded entirely.
   - `rejected`: **an integer count**, not a list of artifact ids.
   - `failed`: an integer count of judgment calls that errored.
   - `considered`: the number of candidates judged.
   The placard is generated in this same call (one model call per artifact).
4. **synthesise** (`src/enqueue/retrieve/curate.py`): one more call producing
   the exhibit (name, through line). If it fails, the room is still returned
   with `synthesis_error` set.

## The wall's ordering

`ORDERINGS` in `src/enqueue/api.py`:

- `ingested`: `created_at DESC` — the museum-shelf order
- `touched`: `updated_at DESC` — **the endpoint's default** (`order="touched"`)
- `title`: `title COLLATE NOCASE ASC`

The comment on `ORDERINGS` previously claimed `ingested` was the default. It
was stale: the endpoint has always defaulted to `touched`, and `notes.py`
states the wall is ordered by last touch (annotating an artifact bumps its
`updated_at`). The comment was fixed to say so.

## The before number (Phase 5 timing)

One full `curate()` run on an isolated library of **100 artifacts** (the
50-artifact eval corpus loaded twice with distinct hashes), using the
configured provider (hosted `deepseek-v4-flash` via the OpenAI-compatible
endpoint), in-process (same code path as `POST /curate` minus HTTP):

| metric | value |
| --- | --- |
| wall-clock | **1048 s (~17.5 min)** |
| model calls | 53 (1 expand + 52 judgments) |
| expansions | 9 |
| candidates / considered | 52 |
| rejected | 23 |
| failed judgments | 29 |
| kept | 0 |

Two findings worth keeping:

- Cost grows with the library: judgments are one model call per candidate,
  and the candidate pool is capped only by `limit=150`. On 100 artifacts the
  whole library is the pool. Phase 9 exists to bound this.
- 29 of 52 judgment calls failed schema validation on this model
  (`strength` returned null where an integer is required), silently dropping
  candidates. The failures surfaced as `failed` counts, never as answers.

The 100-artifact number is the "before" for the bounded design in Phases 7-9.

## Stage one timing (Phase 7)

`score_all(lens)` — whole-library vector + keyword scoring through the Part 1
`VectorStore` interface, zero model calls. Measured in one process on an
Apple Silicon Mac (CoreML embed, local Qdrant):

| library | wall-clock | artifacts | nonzero |
| --- | --- | --- | --- |
| 100-artifact temp library | **55.6 ms** | 100 | 78 |
| 50-artifact eval corpus | **59.6 ms** | 50 | 33 |

Both well under the one-second gate (Phase 7 `[HUMAN]` stop: >1 s on 100
artifacts; not triggered). Scores are hybrid fusion scores in the 0.0-0.6
range on this corpus (median ~0.03, p75 ~0.06), so the provisional
`LENS_SCORE_THRESHOLD` of 0.1 sits above the bulk noise and below the
meaningful tail. The threshold itself stays provisional until Phase 13's
measured table (D4).

## Decisions referenced

- **D2**: how the lens wall pages and pins.
- **D3**: coverage labelling — never claim a judgment that did not happen.
- **D4**: the `LENS_SCORE_THRESHOLD` value is chosen by the maintainer from a
  measured table (Phase 13), not picked by the implementer.

## Coverage labelling (Phase 10, decision D3)

The lens response carries `coverage`, `scored_count`, `total_count`, and
`judged_count`.

- `coverage: complete` means stage one searched every chunk: the search
  window (chunk-level per-query limit and prefetch) was at least the chunk
  count, so no artifact was silently left outside the search. The second
  section may then be labelled "not related".
- `coverage: partial` means scoring was capped for some reason (a narrow
  window). Artifacts outside the window were never checked, so the second
  section must be labelled "not yet checked", never "not related" (D3:
  never claim a judgment - or here, a scoring - that did not happen).
- `scored_count` is how many artifacts received at least one indexed hit;
  `total_count` is every non-deleted artifact; `judged_count` is how many
  got a model judgment.

## The lens endpoint (Phase 11, decision D2)

`POST /lens` accepts `{lens, judge_top, limit, offset}` and returns
`related`, `other`, `pinned`, and the coverage fields. Each entry carries the
same fields the wall renders (kind, title, excerpt, has_blob, pages,
preview-image flags, timestamps, pinned), so the client needs no second call.

- **Pins (D2):** pinned artifacts stay pinned, above both sections. They are
  not sorted into related or other and are not judged - a topic view is
  temporary and must not disturb deliberate pins, and judging a shelf that
  does not move would spend model calls on nothing.
- **Paging:** related and other page independently, the way pinned and
  unpinned page separately on the wall; each reports its own total and more
  flag.
- **Ephemeral:** the lens is stateless. Applying it writes nothing to
  `exhibits`, bumps no `updated_at`, and modifies no artifact (the judgment
  cache is the one table written, and that is its purpose). Clearing the lens
  is therefore a client-side act - drop the lens state and re-request with
  the normal ordering; the wall returns to touched order because the lens
  left no trace. Tested: updated_at identical before and after, zero exhibit
  rows.
- **Orderings:** `ORDERINGS` gains `relevance` so the ordering control can
  express the mode; the plain wall rejects it with a clear message because
  there is no score column to sort by.

## Keeping it correct as the library grows (Phase 12)

- **New artifacts do not invalidate the cache.** A judgment row is keyed by
  (lens_key, artifact_id, model_version); a new artifact simply has no row,
  so on the next application of a lens only artifacts without a cached
  judgment that rank in the top `judge_top` are judged. Tested: apply, add
  one artifact, re-apply - at most one new model call.
- **Trashed artifacts leave both sections immediately.** Every stage queries
  `deleted_at IS NULL`, so a trash action is visible to the next lens
  application with no cache work at all. Tested.
- **Embedding version changes do not touch judgments.** Scores are computed
  live on every application of a lens (score_all runs a real search each
  time), so there is no cached score to invalidate - a version bump changes
  future scores the moment it lands. Judgments are about meaning, not about
  vectors: "this artifact belongs under this lens" survives an embedding
  change, so `lens_judgments` rows are kept. The judgment cache is keyed by
  model version (the reasoner), not by embedding version (the measure).
- **Purge-driven cleanup of `lens_judgments` is implemented in Part 4,
  Phase 29 and is deliberately not attempted here.** Trashing an artifact
  keeps its judgment rows; the purge phase owns that lifecycle.

## Threshold tuning (Phase 13, decision D4)

`enq lens-eval --corpus` measures threshold placement on the eval corpus
(45 queries with known matches; synthetic, machine-verifiable ground truth).
Each topic runs with `judge_top=0`, so the threshold is the only
decision-maker. Measured with the CoreML embedder, 2025-05-11:

| threshold | true matches correctly placed | unrelated wrongly in related |
|-----------|------------------------------|------------------------------|
| 0.0       | 45/45  (1.000)               | 2055/2055 (1.000)            |
| 0.05      | 42/45  (0.933)               | 333/2055 (0.162)             |
| 0.1       | 42/45  (0.933)               | 191/2055 (0.093)             |
| 0.2       | 39/45  (0.867)               | 88/2055 (0.043)              |
| 0.3       | 38/45  (0.844)               | 54/2055 (0.026)              |
| 0.5       | 29/45  (0.644)               | 11/2055 (0.005)              |

The knee is at 0.1: it keeps the full 0.05 placement (93.3%) while halving
the wrong-in-related rate (9.3%). The three misses at 0.1 are the
vague-semantic corpus queries (grit, imagination, inquiry, and their kin),
which score low by design - no threshold recovers them without flooding the
shelf.

**The choice is the maintainer's (D4).** The default `LENS_SCORE_THRESHOLD`
stays at 0.1, provisionally supported by this table, until the maintainer
picks from it and records why.

The CI guard does not exist yet (no pipeline in this repo). When CI lands it
should run `enq lens-eval --corpus --baseline 0.933`, which exits 2 when the
best correct placement drops more than 5 percent below 0.933.

## Performance guardrails (Phase 14)

- **The split comes first, placards fill in.** `POST /lens` is now a
  text/event-stream: the `split` event arrives as soon as stage one
  finishes - both sections bucketed by score, candidates named in
  `judging`, every entry `judged: false` - and `judgment` events follow one
  per artifact, carrying the placard and the final placement. The person
  sees the wall before the model has spoken. Tested with a slow provider:
  zero model calls have been made when the split is received. The progress
  state is the stream itself: each judgment event carries
  `judged_so_far`/`judge_total`, which is all a first-run client needs to
  render "checking 3 of 20".
- **Cached replay is instant.** Re-applying the same lens makes zero model
  calls; a cached application of a three-artifact library completes in well
  under a second in the test suite.
- **Check More is a re-request with a higher judge_top.** The cache makes
  already-judged artifacts free, so raising judge_top from 1 to 3 costs
  exactly two model calls, never a re-judgment of the first.
- **Judge Top is capped.** `LENS_JUDGE_TOP_MAX` (default 100,
  `ENQ_LENS_JUDGE_TOP_MAX`) bounds a single application so one request
  cannot spend the library's entire judgment budget. The response reports
  the clamped `judge_top` and the cap; the wall copy explains the cap when
  the lens UI lands.
- Every lens application logs stage-one duration, model calls, cache hits,
  coverage, and total duration.
