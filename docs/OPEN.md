# Open questions

Things the code hit that the specs did not answer. Short list on purpose: the first few passes are throwaway and most of this can wait.

---

## 0. Strict validators plus a weak model is pathological

Second end-to-end curate, after the first round of fixes: 10 candidates, **4 of 10 judgments failed**, all but one on `evidence is not a verbatim span`. The model paraphrases rather than copying, consistently, across every run.

Everything else improved. Placards became wall text instead of filing notes, the suggested name populated, duplicate tensions disappeared. The validators are doing exactly what they exist to do, and `llama3.1:8b` cannot satisfy the one that matters most.

**`rejected: 0` is not yet evidence of anything.** It looked alarming, and PROGRESS.md names it as a broken-model tell, but with `pool=10` drawn from a corpus of 52 the candidates are the top twenty percent and are genuinely plausible. Zero rejections at `pool=150` would be damning. Re-test there before concluding.

The first run, for reference: 21 minutes, 6 of 10 failed, every placard self-referential.

The validators are working. `llama3.1:8b` cannot meet them. It paraphrases instead of quoting verbatim, and it emits truncated JSON. Each failure burned four attempts, so ten candidates became roughly thirty model calls, all serialised because Ollama does not run them in parallel. Bounded concurrency bought nothing.

Three responses, and the choice is a real one:

1. **A better model.** Everything above is a capability problem, not a design problem. The evidence rule and the self-reference ban are correct and a stronger model satisfies them without retrying.
2. **Cheaper failure.** Already applied: rerank drops to two retries, because a failed judgment is a dropped candidate rather than a crisis.
3. **Weaker validators.** Available, and wrong. The evidence rule is the anti-hallucination mechanism, and softening it to fuzzy matching buys throughput by letting the model invent quotes.

`rejected: 0` is separately alarming and PROGRESS.md already names it as a broken-model tell. Candidates arrive by similarity, so most should be rejected on judgment. The rerank prompt now says so explicitly. Unverified whether that is enough.

---

## 1. The eval corpus needs planted analogies

The only item that changes what gets built.

Junk data has no genuine analogies, and the golden set exists to measure whether hard analogies surface. A corpus of lorem ipsum will score perfectly and mean nothing.

Two ways out, and one is better than the real notes ever were:

- **Constructed fixtures.** Twenty to thirty short documents written so that specific pairs rhyme under a lens without sharing vocabulary. Ground truth is known by construction rather than by hand-marking, which removes the whole propose-and-correct step in Phase H.
- **Public domain.** Epictetus, Montaigne, Feynman. Real prose, real analogies, nothing private.

Not blocking the POC. Blocking Phase H.

---

## 2. `local_only` and "no facets" are conflated

`config.SKIP_FACETS_FOR_FOLDERS` currently drives both the facet gate and the `local_only` flag. Different ideas that happened to agree on the sample data.

- `local_only` is a privacy decision: never leaves this machine.
- Facet-ineligible is a quality decision: nothing here worth abstracting.

A long private journal entry is both `local_only` and very much worth facets. Five-minute split, left visible rather than buried.

---

## 3. Thresholds that are guesses

| Constant | Value | What it did on real input |
|---|---|---|
| `MIN_WORDS_FOR_FACETS` | 40 | skipped 18 of 76 notes |
| `MERGE_FLOOR_WORDS` | 120 | chunks 1,421 to 633, median 17 to 38 words |
| `MAX_WORDS` | 600 | never hit, largest chunk was 213 |

The merge floor is the one to question first. It fixed an obvious problem, but nothing says 120 beats 80 or 200.

---

## 4. Blobs have no real capture date

PDFs and images fall back to file mtime, so they sort as captured today. Honest fix is a separate `imported_at`, which needs a schema field. Cosmetic until there is a UI.

---

## 5. `note_entries` exists and nothing writes to it

The append-only note table is in the schema and the API returns it. Nothing exercises it until capture exists.

---

## 6. The provenance classifier is crude

Four heuristics, two constitute a match. It found a real bug in itself: a note opening with "That's an excellent..." scored `authored` because the source used a curly apostrophe and the phrase list used a straight one. Fixed by normalising punctuation.

Still undercounts, and probably cannot do better. A conversation where the human wrote half may not belong in two buckets at all.
