# PLAN - the search relevance floor (the one miss from Phases R/C/M/P)

## Why this exists

Phases R/C/M/P validated well: the Chopper indexing bug is fixed, the deletions and splits landed, and retrieval scores 42/42 on every real-match query in the eval (titles, paraphrases, rare strings, long docs, vague-semantic, regression).
One thing was measured but never closed.

The R.4 eval grew to 50 queries and added a `nothing` category: 8 gibberish queries ("quantum flux capacitor", "hyperdimensional cheese grater", "zephyrian marmot migration patterns") whose `expect_artifact_ids` is `[]` - they should return nothing.
The harness reports **Nothing-OK: 0/8**: every gibberish query returns results.
Confirmed live: `GET /search?q=hyperdimensional cheese grater` returns 2 artifacts.

The cause is structural, not a tuning slip.
Dense kNN always returns its nearest neighbors no matter how far they are, and RRF fuses by rank, so a gibberish query's fused result looks shaped like a real one - a top-ranked list - even though nothing is actually close.
There is no floor that says "the best match is too weak; return nothing."

For a second brain this is a false-positive problem, and false positives cost more than misses: a person searches for something they never saved and gets a confident wall of unrelated notes instead of an honest "nothing found."
Every peer app (mem, Fabric, mymind) treats "no results" as a valid, common answer.

This plan adds the floor, and - the hard constraint - adds it without dropping any of the 42 real-match queries.

## House rules (same as PROGRESS.md)

Do one task per turn, in order, and verify each with its "Done when" line before checking the box.
`[AGENT]` for an implementing agent, `[HUMAN]` for Minh; the agent never commits.
Python is `black`, line-length 100. The gate is `bin/verify`.
Never use the em dash; plain dash only.
Bug fixes start from a failing reproduction - here the reproduction already exists as the eval's `nothing` category.

## The design constraint - read before touching code

RRF fused scores cannot tell a gibberish query from a real one, because RRF only sees ranks: both produce a rank-1 item.
The signal that separates them lives in the raw legs, before fusion:

- A real query has at least one strong leg: a lexical hit (FTS5/trigram/fuzzy over title, body, entity, annotation) or a dense neighbor that is genuinely close.
- A gibberish query has no lexical hit at all, and its best dense neighbor is far (large cosine distance / low similarity).

So the floor is a judgment on the raw legs, not on the fused score: keep a result only when some leg clears a real-match bar.
An absolute dense-distance cutoff alone is fragile (distances are not calibrated across queries), so pair it with the lexical signal: a result survives if it has any lexical hit, or if its dense similarity is above a floor calibrated on the eval.
Calibrate the floor against the eval, not by eye.

## Tasks

- [x] **Q.1 [AGENT]** Confirm and pin the reproduction.
  Run `uv run enq eval` and record the current numbers: Recall@10, MRR, and Nothing-OK (expected `0/8`).
  Add nothing to the code yet.
  Done when: the eval output is captured in this file under Q.1 as the baseline, showing `Nothing-OK: 0/8` and the non-nothing pass count (expected 42/42).

- [x] **Q.2 [AGENT]** Expose the raw per-leg signal at the point of fusion.
  Anchor: `src/enqueue/retrieve/candidates.py` - `search_results`, `_hybrid_results`, and the `_weighted_hits` helper (M.6c), plus `src/enqueue/index/store_sqlite.py` `search`/`search_dense` which return `distance`/`score` per hit.
  Thread the best dense similarity (or distance) and whether any lexical leg (FTS5, trigram, fuzzy) matched, per artifact, through to where the final result list is assembled, without changing ranking yet.
  Done when: `search_results` has, for each candidate, a flag "had a lexical hit" and the best dense similarity available at the filtering point; existing tests still pass (`uv run pytest tests/test_search_results.py tests/test_annotation_search.py -q`).

> DECISION (Minh, after the Q.4 block-out): a single dense threshold cannot work - the eval proved the weakest real matches (cosine ~0.518) sit below the strongest gibberish neighbors (~0.668), so no constant separates them. The floor is a TWO-TIER gate: instant keep/drop where the signal is clear, and one model judgment on the ambiguous gray zone. Chosen for robustness - its failure mode is a small honest leak, never the silent disappearance of a real note. Q.3 and Q.4 below are rewritten to this decision. Do them in order; each is atomic and idempotent.

- [x] **Q.2b [AGENT]** Fix `search_dense` to report true cosine, not the compressed `1/(1+d)` pseudo-value. Do this first; the gray-zone bars in Q.3 need an honestly-scaled number.
  Anchor: `src/enqueue/index/store_sqlite.py`, `search_dense` (the `1/(1+d)` transform over the vec0 L2 `distance`).
  First confirm the stored/query embeddings are L2-normalized (bge-base via fastembed normally are; check by asserting one vector's norm is ~1.0). If normalized, replace the reported similarity with `1 - (distance * distance) / 2`, clamped to `[0, 1]`. This is monotone in `distance`, so it changes no ranking - only the reported number. If the vectors are NOT normalized, stop and report; do not guess a formula.
  Done when: `search_dense` returns a value in `[0,1]` that is ~0.7 to 0.8 for a known-close pair and ~0.5 for a far pair; `uv run enq eval` recall@10 on the non-nothing queries is unchanged (ranking is untouched); `uv run pytest tests/test_store_sqlite.py -q` is green.

- [x] **Q.3 [AGENT]** Replace the single-threshold floor with the two-tier gray-zone gate.
  Anchor: `src/enqueue/retrieve/candidates.py` - the existing `MIN_DENSE_SIMILARITY` constant and `passes_relevance_floor(hit)` (Q.2/Q.3 already thread `had_lexical_hit` and `dense_similarity` onto each hit).
  Define two named constants on the true-cosine scale (Q.2b): `KEEP_ABOVE` (clearly relevant, keep without asking) and `DROP_BELOW` (clearly irrelevant, drop without asking). Starting values to calibrate in Q.4: `KEEP_ABOVE = 0.75`, `DROP_BELOW = 0.45`.
  Rewrite the keep decision for a hit with NO lexical hit (a hit WITH any lexical leg is always kept, unchanged):
  - `dense_similarity >= KEEP_ABOVE` -> keep, no model call.
  - `dense_similarity < DROP_BELOW` -> drop, no model call.
  - otherwise (the gray zone) -> ask the gray-zone judge (Q.3b); keep iff it says relevant.
  A search left with zero kept hits returns `[]`. Do not touch the ordering of survivors.
  Done when: the two constants exist with a comment that Q.4 calibrates them; hits with a lexical leg or `>= KEEP_ABOVE` still pass with no model call; `uv run pytest tests/test_search_results.py -q` is green.

- [x] **Q.3b [AGENT]** The gray-zone judge: one model call that decides relevance for the ambiguous candidates only.
  Add a function in `candidates.py` (for example `judge_gray_zone(query, candidates) -> set[kept_ids]`) that sends the provider ONE batched call over just the gray-zone candidates: the query, then each candidate as `[{kind}] {title}\n{snippet}` with its id, asking for each whether it genuinely matches the query or is only loosely/coincidentally similar. Response model is a list of `{id, relevant: bool}`.
  Three hard requirements:
  - Fail-open: if the model call raises or returns malformed, KEEP every gray-zone candidate. A leak is safer than hiding a real note.
  - Cache: memoize the verdict per `(query, artifact_id, model_version)` (reuse the `derived_values` cache or a small table) so re-running the same search makes no new call.
  - Only the gray zone: candidates with a lexical hit or `>= KEEP_ABOVE` never reach this function, so most searches make zero model calls.
  Done when: a unit test with a stubbed provider shows a gray-zone candidate judged `relevant` is kept and one judged `not` is dropped; a raising provider keeps all (fail-open); a second identical search makes no second provider call (cache); `uv run pytest -q` is green.
  DONE: `judge_gray_zone` + `_apply_floor` in `candidates.py` replace `passes_relevance_floor` (removed - a per-hit bool cannot express judge semantics); `chats.passages()` runs the same judge on gray-zone chunks, capped per artifact. Verdicts cache in `derived_values` scope `'gray_judge'` under `(query, artifact_id, model_version)`. Real bug found and fixed in the prompt: the line must lead with `[id:<artifact_id>]` or the model echoes the ordinal index, every verdict is skipped, and the gate silently fail-opens. Eval with model reachable (gemini-2.5-flash): hybrid unchanged 42/50 / MRR 0.900 / Nothing-OK 0/8; rollup **48/50, Recall@10 0.960, MRR 0.968, Nothing-OK 8/8** (was 42/50, 0.840, 0.900, 0/8). The judge correctly empties every gibberish query and keeps genuine matches with no lexical leg. TWO genuine vague-semantic matches now drop in rollup (vague_01, vague_03) - the judge genuinely judges them not-relevant; a neutral prompt did not recover them and cost one Nothing-OK, so reverted. Those 2 are the precise Q.4 calibration target below. Unit tests green: `TestQ3bGrayZoneJudge` (relevant kept / not dropped, raising keeps all, cache no-second-call) plus an autouse fail-open judge stub in both test files so no test touches the real model. Full suite 387 passed, black clean, `bin/verify` green.

- [ ] **Q.4 [AGENT]** Calibrate the two bars and record the eval, with the model reachable.
  The gray-zone gate needs the provider, so run the eval with a backend up (`uv run enq eval` reaches `get_provider()`).
  Adjust `KEEP_ABOVE` / `DROP_BELOW` so the gray zone is as small as it can be while (1) every one of the 42 real-match queries still passes and (2) `Nothing-OK` is as high as the judge reaches. Record the final two constants, the judge model used, and the final eval numbers in this file.
  If the judge misses specific gibberish queries (the earlier probe on `llama3.1:8b` missed 3 of 9), note which and whether a stronger backend (Gemini) or a tighter prompt closes them; do not lower a bar in a way that drops a real query to compensate.
  Done when: `uv run enq eval` shows the 42 real-match queries still passing and `Nothing-OK` improved toward `8/8`, with the two constants, the judge model, and the numbers recorded here.

- [x] **Q.5 [AGENT]** Carry the floor into the answer path.
  Anchor: `chats.passages()` (`src/enqueue/chats.py`) feeds the answer model, and the model already refuses with `grounded=false` when nothing bears on the question.
  Confirm that passages now respects the same floor, so an answer over a no-match question refuses honestly instead of grounding on far neighbors; if `passages()` bypasses the floored path, route it through the same filter.
  Done when: a chat question that matches nothing in the library returns a `grounded=false` "nothing you have saved" answer, and `uv run pytest tests/test_chats.py -q` is green.

- [ ] **Q.6 [HUMAN]** Desktop pass.
  `bin/relaunch`, search a few things you never saved (confirm "nothing found", not a wall of unrelated cards), then search several things you did save (confirm they still come back exactly as before).
  Ask the eye a question about something not in the library and confirm it says so plainly.
  Done when: gibberish searches read as empty, real searches are unchanged, and the answer path refuses honestly.

## Verification commands

```
uv run enq eval                 # Nothing-OK 8/8, non-nothing pass count unchanged from baseline
uv run pytest -q                # full suite green
uv run black --check src/ tests/
bin/verify                      # JS parse + pytest + contrast
```

## Out of scope

- Re-tuning any real-match ranking. The floor removes non-matches; it never reorders matches.
- A per-query adaptive threshold or a learned cutoff. A single calibrated constant is the right complexity at this corpus size; revisit only if the eval later shows one constant cannot serve both directions.
- The stale eval line in PROGRESS.md (it still cites the old 15-query `14/15, 0.933`); update it to the 50-query numbers when Q.4 lands, but that is a doc edit, not a task here.

---

# PLAN addendum - two more from a live review

## Phase K - the fast-capture overlay reads clinical (quieter + delight)

Ran the impeccable `quieter` and `delight` lenses over `src/enqueue/static/capture.html`.
This is an Operate surface and the one act the whole product rests on, so it must feel certain and quiet, not like a form.
It reads clinical because it stacks three uppercase-tracked micro-labels (the "ENQUEUE" wordmark, the kind label, the "RETURN TO KEEP" hint), wears a heavy `--line-strong` (#7f8296) card border, uses the loud Kraken purple `--accent: #7132f5` instead of the design system's muted lavender `#5e6ad2`, and opens with a spec-sheet placeholder that lists file types instead of carrying a voice.
DESIGN.md wants scarce lavender, hairline borders, and whisper shadows; the overlay is louder and colder than its own system.
This is refinement, not a redesign: keep every capture behavior and all the JS untouched - the change is chrome, color, copy, and the confirmation beat.

Delight thesis: keeping something should feel certain and a little warm, because Enqueue keeps what Dequeue would let decay - things you toss here stay.

- [x] **K.1 [AGENT]** Quiet the chrome. Soften the card edge from `--line-strong` to a hairline `--line` (or drop the border and let `--shadow-lifted` carry the edge, `capture.html:106-117`); lighten or remove the title-bar bottom border (`#bar`, 133-147) so the surface step alone separates it. Done when: the overlay reads as a soft lifted card, not a boxed panel, at the 30px bar scale.
- [x] **K.2 [AGENT]** Align the accent to the system. Change `--accent` / `--accent-strong` from `#7132f5` to the design system's muted lavender `#5e6ad2` (and `--lavender-subtle` to its rgba), matching the home page and DESIGN.md so the accent stops shouting (`capture.html:56-61`). Done when: the disc, focus ring, and drag boundary are the same muted lavender as the wall, not the loud purple.
- [x] **K.3 [AGENT]** Cut the redundant clinical labels. The disc plus the uppercase "ENQUEUE" wordmark is a redundant banner (the window already is Enqueue); drop the caps wordmark and keep the disc alone as the quiet mark (`capture.html:264-267`). Keep the live kind label - it is information, not chrome - and set it and the footer hint to sentence case so at most one uppercase micro-label survives (`.label`, 188-195). Done when: the header is the disc plus the live kind, and the window carries one uppercase micro-label at most.
- [x] **K.4 [AGENT]** Give the empty field a voice. Replace the placeholder "A note, a link, an image, or dropped files" with product voice grounded in "it stays" rather than a comma list of types - the kind label already classifies what you typed (`capture.html:275`). Short, warm, unmistakably Enqueue (for example along the lines of "Toss it here. It stays." - agree the exact copy with Minh). Done when: the placeholder carries voice and is not a list of file types.
- [x] **K.5 [AGENT]** Make the "Kept" beat feel certain. The C.3c beat exists (status "Kept." plus a 200ms lavender border, `capture.html:378-390`); elevate it proportionally for a routine save so it reads as "it is safe" - a single calm pulse or settle of the brand disc as it confirms, then dismiss. Proportional, never celebratory; `prefers-reduced-motion` still collapses to an instant dismiss (the existing guard stays). Done when: keeping something gives one calm, unmistakable confirmation, and reduced motion dismisses instantly with no flash.
- [ ] **K.6 [HUMAN]** Desktop review: summon the overlay, type a note, paste an image, drop a file; confirm it feels quiet and certain, not clinical, and that reduced motion is respected.

Verify (K.1-K.5): `bin/verify` (JS parse + contrast) passes, and the capture logic still works end to end (type -> Return -> Kept -> dismiss; paste image; drop file).

## Phase L - an image's annotation answers as "just text, not an image"

Triaged from a live chat: asking about the captured "tony tony chopper" image returns "It appears I have a note saved with the text 'tony tony chopper'. However, this is just text and not an image."

This is NOT a search-recall bug - search works. The annotation "tony tony chopper" was indexed (R.2) and correctly found; it lives as a chunk on image artifact `b5dd5315`. Two downstream gaps produce the wrong answer:

1. The answer passage omits the artifact kind. `chats._ask_model` builds each passage as `[id] title\n text` with no kind, so the model sees the bare annotation text and cannot tell it is a note ON an image versus a standalone text note.
2. The image has no description. It is `status=text_only`, `body=None`: the local text-only model's vision describe failed (GT.1 #2), so the image's only searchable text is its annotation, and there is nothing describing the picture itself.

- [x] **L.1 [AGENT]** Carry artifact kind (and annotation provenance) into the answer context. Anchor: `chats._ask_model` in `src/enqueue/chats.py`, where the passage body is assembled as `[{artifact_id}] {title}\n{text}`. Include the kind, and mark annotation-sourced text as a note on the artifact, so the model receives something like `[image] {title}\n(note added by you) tony tony chopper` rather than bare text. Done when: asking about the chopper image yields an answer that identifies it as an image whose note is "tony tony chopper", not "just text and not an image", and `uv run pytest tests/test_chats.py tests/test_annotation_search.py -q` is green.
- [x] **L.2 [AGENT]** Re-describe `text_only` images on a vision-capable backend. Anchor: `_describe_image_if_needed` in `src/enqueue/ingest/queue.py` (GT.1 #2, the swallowed-failure path), and the `status=text_only` images. When the configured backend can see images (the current Gemini backend can), a describe pass gives the image real content; add a backfill action (a CLI command or a settings button beside "Rebuild concepts") that re-runs describe over `text_only` images and clears the status on success. Done when: a `text_only` image, after re-describe on a vision backend, has a body and is findable by its visual content, not only by its annotation.
- [ ] **L.3 [HUMAN]** Desktop: ask about the chopper image and confirm the answer knows it is an image; run the re-describe and confirm the image is findable by what it depicts.

Verify (L.1): `uv run pytest -q` green; the answer path names the kind. L.2 depends on a vision-capable backend being selected.

## Note on scope

Phases K and L are additive to Phase Q (the relevance floor).
Independent of each other; Q and L both touch retrieval/answer quality, K is pure front-end refinement.
Recommended order if done together: L.1 (cheap, fixes a visibly wrong answer), then Q (the floor), then K (the capture polish), then L.2 (the heavier vision re-describe).
