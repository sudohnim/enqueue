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
