# Evaluation

Build this before the retriever. It is the only thing that can tell a good exhibit from a plausible one.

Product behaviour is [PRODUCT.md](PRODUCT.md). The schemas being measured are [CURATION.md](CURATION.md).

---

## The number that matters

**Recall at the candidate stage.** Target `recall@150`.

Everything else is secondary, for one reason: a recall failure is fatal *and invisible*.

If the furniture article never enters the candidate pool, the exhibit still reads beautifully.
It is built from the wrong ten artifacts, the through-line is coherent, the placards are grounded in real quotes, and nothing anywhere in the output reveals that the best material in the museum was never considered.

Precision failures are visible and fixable. You read a room and see something that does not belong.
Recall failures just quietly make the museum smaller than the mind it is supposed to hold.

## Do not use RAGAS faithfulness

Borrow **context recall** from RAGAS. Discard **faithfulness**.

Faithfulness asks whether the answer is supported by the retrieved documents.
For question answering that is correct, and it is the right metric for **ask**.

For **curate** it is actively wrong.
The value of an exhibit is the through-line *between* artifacts, which appears in none of them.
Faithfulness would penalise precisely the output the product exists to produce.

Two acts, two metrics. Do not let a shared harness blur them.

## What is already guaranteed and needs no metric

Placard groundedness is enforced by the `evidence` validator in CURATION.md: a placard cannot exist unless the model quoted a verbatim span of the artifact.
There is nothing to measure. Either the call succeeded or it retried.

This is the general pattern worth repeating: **prefer a validator to a metric.**
A metric tells you how often you were wrong. A validator makes it not happen.

---

## The golden set

A hand-marked file. Ten to fifteen lenses, each naming the artifacts that should surface.

Living at `eval/golden.yaml`.

```yaml
lenses:
  - lens: antifragility
    note: the canonical hard case
    should_surface:
      - id: art_0142
        why: joinery designed to be disassembled and remade
        hard: true          # shares no vocabulary with the lens
      - id: art_0311
        why: annealing, metal strengthened by controlled failure
        hard: true
      - id: art_0087
        why: the Taleb excerpt itself
        hard: false
    should_not_surface:
      - id: art_0250
        why: an article about fragile supply chains; topically adjacent, not an instance
```

### How it gets built: propose and correct

The marker proposes nothing and corrects everything.

1. Ingest the existing corpus.
2. A **proposal pass** reads every artifact in full against each lens and drafts `should_surface` with reasons.
3. The marker corrects the draft: removes what does not belong, and **adds what was missed**.
4. The marker adds at least one lens the proposal pass never saw.

**The proposal pass must not use the retrieval pipeline.**
It brute-forces the corpus, reading each artifact whole, because using retrieval to build the set that measures retrieval is circular and would score the system against its own blind spots.
At a few hundred artifacts brute force is cheap. If the corpus grows past what brute force can cover, the proposal pass must be rebuilt rather than quietly switched to retrieval.

The corrections are the real signal. A draft the marker accepts wholesale means the pass was too conservative or the marker was not reading.

### Rules for building it

1. **Every lens must contain at least two `hard: true` artifacts.** A hard artifact is one that shares no meaningful vocabulary with the lens. Without them the set measures topical retrieval, which was never the problem. This is the whole point of the exercise.
2. **Never mark by searching.** If artifacts are found by searching for the lens, the set records exactly what the system already finds, which measures nothing.
3. **Include `should_not_surface`.** Near misses are how precision gets measured, and topically adjacent non-instances are the most informative negatives.
4. **The same artifact should appear under multiple lenses.** That is the product's central claim, and a golden set where every artifact belongs to one lens quietly encodes a folder tree.
5. **Write `why` in the marker's own words.** It becomes a reference for judging whether the generated placard found the same thing.

### Seed lenses

Drawn from the material already in hand and the interests the museum is being built around.

| Lens | Why it is in the set |
|---|---|
| antifragility | the canonical case, and the one the architecture was designed against |
| brutalism | forces the same artifacts to hang in a second, unrelated room |
| slow craft | close enough to antifragility to test precision, not just recall |
| stoic control | book annotations exist for this, so it tests real captured material |
| what I keep saving without knowing why | the unnamed-theme case, where the lens is not a concept at all |
| memory and forgetting | spans Montaigne, physics, and personal notes |
| systems that improve under stress | deliberately near-synonymous with antifragility, to test whether two phrasings return the same room |

The last two matter most.
A near-synonym pair that returns substantially different rooms means retrieval is keying on phrasing rather than concept, which is the failure the facet layer exists to prevent.

---

## Metrics

| Metric | Stage | Target | Notes |
|---|---|---|---|
| `recall@150` | candidates, before rerank | the number | Split it: overall, and **hard-only**. Hard-only is the real score. |
| `recall@150` hard-only | candidates | the moat | If this is low, nothing downstream matters. |
| precision of kept set | after rerank | secondary | `should_not_surface` artifacts appearing in a saved room. |
| lens-pair agreement | candidates | high | Overlap between near-synonymous lenses. Low means phrase-keying. |
| thin honesty | synthesis | no false confidence | Run a lens with almost nothing behind it. The room must return `thin: true`. |

## Ablations to run

Each answers a question that is currently a guess in CURATION.md.

- **No facet layer**, literal chunks only. Establishes the baseline the whole architecture is justified against. If this is close to the full system, the facet layer is not earning its ingest cost.
- **No query expansion**, facets only.
- **Facet count**: 5 versus 10 versus 15.
- **Level distribution**: with and without the minimum-two-at-level-3 rule, and with and without the proper-noun ban. These two validators are the most opinionated things in the system and should have to prove themselves.
- **Levels 0 and 1 dropped** from the index entirely.
- `RecursiveChunker` versus `LateChunker`.
- Candidate pool size: 50 versus 150 versus 400.

## Harness

Runs offline against a fixed corpus snapshot, with a fixed embedding model version, so results are comparable across runs.

Report per lens and in aggregate. A single averaged number hides the case that matters, which is always one specific hard artifact failing to surface.

Store every run. When recall drops, the question is always which change did it, and that is unanswerable without history.

---

## Open

- Corpus size for the golden set. Marking is hand work, and a set built over 200 artifacts may not predict behaviour over 10,000.
- Whether `should_not_surface` needs a severity, since a topically adjacent miss is worse than a random one.
- How often to re-mark. The set encodes what the marker thought was relevant at the time, and that will drift.
