# Lens evaluation

`enq lens-eval` measures how `LENS_SCORE_THRESHOLD` places true matches:
for each topic and threshold it applies the lens with `judge_top=0` (so the
threshold is the only decision-maker) and reports what share of the
artifacts that genuinely belong landed in `related`, and what share of
unrelated artifacts wrongly landed there.

## Ground truth

There are two sources, and they answer two different questions:

1. **The eval corpus** (`enq lens-eval --corpus`) uses `../queries.yaml`
   `expect_artifact_ids` as ground truth. The corpus is synthetic, so its
   ground truth is machine-verifiable by construction. This is what the
   threshold table in `docs/decisions/lens-view.md` was measured with.
2. **`topics.yaml`** (this directory, not yet written) is ground truth for
   the real library: 10 topics phrased the way a person would type them, and
   for each, the artifact ids that genuinely belong. Only a person who knows
   the library can supply that. `enq lens-eval` without `--corpus` reads this
   file and runs against whatever library the current config points at.

## topics.yaml shape

```yaml
topics:
  - topic: "how sourdough keeps itself alive"
    ids: ["<artifact id>", ...]
  - topic: "trains and their own sense of time"
    ids: ["<artifact id>"]
```

## CI guard

There is no CI pipeline in this repo yet. When one appears, it should run
`enq lens-eval --corpus --baseline 0.933`; the command exits 2 if the best
correct placement across thresholds drops more than 5 percent below the
baseline recorded in `docs/decisions/lens-view.md` (0.933 at the time of
writing).
