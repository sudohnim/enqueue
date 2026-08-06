# Feature: Pivot — group a subset of the library by a computed attribute

This file is the whole plan. It is written to be implemented by an LLM that does not know
this codebase. Do not improvise. Do every step in order.

The motivating example is "organize my book notes by the region the author is from." **You
must NOT build that query.** You build a general engine for which that query is one input.
Nothing you write may contain the words book, author, or region as a code path. They appear
only inside test fixtures.

(The previous contents of this file were the tags plan, now shipped; git has it.)

---

## 0. The two rules you must never break

1. **Nothing is hardcoded to a domain.** Every attribute name, instruction, and subset is a
   PARAMETER that arrives at runtime. If you find yourself writing `if attribute == "author"`
   or a prompt that mentions books, you did it wrong: stop and re-read.
2. **An inferred value is never dressed as the user's data.** Every derived value carries a
   `grounded` flag: true when it came from the artifact's own content, false when it came
   from the model's world knowledge. The flag travels with the value everywhere, and the UI
   shows it. This is the product's "show your work" promise; breaking it is the one thing this
   app refuses to do.

## 1. The idea in one paragraph

A **pivot** groups a chosen set of artifacts by an attribute the model computes. An
**attribute** is a named, cached, model-derived value with two ways to produce it: `extract`
(read it from an artifact's content, grounded) and `enrich` (infer it from another value using
world knowledge, not grounded). A pivot is a short pipeline of those, ending in a group key,
then a plain code-level group-by. The model does only the per-item judgments; ordinary code
does the selecting, caching, grouping, and rendering. The library never groups itself in one
giant prompt.

Worked example (a test, not a code path): subset = "notes about books"; step 1 `extract`
attribute `author` from each note; step 2 `enrich` attribute `region` from each distinct
author; group by `region`. The code knows none of those words; they come from a spec.

## 2. Orientation

Local-first macOS app. Python engine (FastAPI) on `127.0.0.1:8787`. You will touch:

| Path | What it is |
| --- | --- |
| `src/enqueue/migrations/versions/` | Alembic migrations. You add `0012_derived.py`. |
| `src/enqueue/derive.py` | NEW. The three model primitives + the cache. You create it. |
| `src/enqueue/pivot.py` | NEW. The code orchestrator and the planner. You create it. |
| `src/enqueue/prompts.py` | Prompt templates live here as module constants. You add three. |
| `src/enqueue/api.py` | FastAPI endpoints. You add the pivot endpoints. |
| `src/enqueue/static/museum.html` | The whole UI. One file, inline `<style>` + `<script>`. |
| `tests/` | Pytest. Mirror `tests/test_tags.py` for style and the `store` fixture. |

Reference shapes to copy (read them, do not import their specifics blindly):

- Model call: `get_provider().complete(system, user, ResponseModel, context=None)` returns a
  Pydantic instance. See `src/enqueue/ingest/facets.py` `generate_for_artifact`.
- Cache table with model-version invalidation: `lens_judgments` in `0009_lens_judgments.py`
  (its PK includes `model_version`, so a model change does not serve stale rows).
- The artifact's text for extraction: `retrieve.candidates.artifact_text(conn, artifact_id, max_words=...)`.

### Running and checking

```bash
bin/relaunch        # rebuild + launch; refuses to start if the HTML fails to parse
uv run pytest -q    # tests must stay green; baseline is 260 passing
uv run black src/ tests/   # must be clean
```

`museum.html` has NUL bytes; `rg` needs `-a` on it or it silently prints nothing.

### How to work these steps

- One checkbox per commit. Never batch. Message: `pivot: <what the step did>`.
- After every checkbox: `uv run pytest -q` green and `bin/relaunch` still starts.
- Every step is idempotent. If the target already exists, tick the box and move on.
- `[AGENT]` do it. `[HUMAN]` stop and hand over.
- No em dashes anywhere. Plain dash.
- The model backend is slow and sometimes wrong. Every model call is `try/except`: on failure
  return a clear result the caller can handle, never a crash and never a silent wrong value.

---

## PHASE P1 — The cache table (one table serves everything)

- [x] `[AGENT]` Create `src/enqueue/migrations/versions/0012_derived.py`, copying the shape of
      `0009_lens_judgments.py` (docstring, `from __future__`, `from alembic import op`, the four
      module vars). Set `revision = "0012"`, `down_revision = "0011"`. In `upgrade()`:

      ```sql
      CREATE TABLE IF NOT EXISTS derived_values (
        scope         TEXT NOT NULL,       -- 'artifact' or 'value'
        subject       TEXT NOT NULL,       -- an artifact id, or the exact input string
        attribute     TEXT NOT NULL,       -- canonical attribute name, lowercased
        value         TEXT NOT NULL,       -- the derived value (empty string = "none found")
        grounded      INTEGER NOT NULL,    -- 1 from content, 0 from world knowledge
        source        TEXT NOT NULL,       -- 'model' or 'user'
        model_version TEXT NOT NULL,       -- '' when source = 'user'
        created_at    TEXT NOT NULL,
        PRIMARY KEY (scope, subject, attribute, source)
      );
      ```

      In `downgrade()`: `DROP TABLE IF EXISTS derived_values;`. One `op.execute` per statement.
- [x] `[AGENT]` Verify: `bin/relaunch`, then
      `uv run python -c "from enqueue import db; c=db.get_conn(); print([r[1] for r in c.execute('PRAGMA table_info(derived_values)')])"`
      prints the eight columns.

Notes for the implementer: `source='user'` is a correction and always wins over `source='model'`
on read (rule 2, the director beats the curator). Two scopes because an attribute of an
artifact is cached per artifact, but an attribute inferred from a value (world knowledge) is
cached per value: fifty notes by twenty authors need twenty region lookups, not fifty, and a
region does not change.

---

## PHASE P2 — The three model primitives (`src/enqueue/derive.py`)

Create the file. Header: `from __future__ import annotations`, `import uuid`, `import json`,
`from datetime import datetime, timezone`, `from . import db`, `from .providers.base import get_provider`.
Add `_now()` returning an ISO-8601 UTC string. Every model call is wrapped so a failure returns
a sentinel, never raises out of the module.

Define the response models near the top:

```python
from pydantic import BaseModel

class _One(BaseModel):
    value: str          # the derived value, or "" when there is none

class _Buckets(BaseModel):
    mapping: dict[str, str]   # raw value -> canonical bucket name
```

- [x] `[AGENT]` `_read(scope, subject, attribute) -> dict | None`: return the cached row as
      `{"value", "grounded", "source"}`, preferring `source='user'` over `source='model'`. Read
      connection, closed in `finally`. Returns `None` when nothing is cached.
- [x] `[AGENT]` `_write(scope, subject, attribute, value, grounded, source, model_version)`:
      `INSERT OR REPLACE INTO derived_values (...)`. One `db.transaction()`.
- [x] `[AGENT]` `extract(artifact_id, attribute, instruction) -> dict`: derive an attribute from
      ONE artifact's content, grounded. Steps: normalize `attribute` (lowercased, stripped);
      return the cache hit if present (`_read('artifact', artifact_id, attribute)`); otherwise read
      the artifact text (`artifact_text(conn, artifact_id, max_words=400)`), build a prompt from
      `prompts.EXTRACT_ATTRIBUTE` (Phase P3) filled with `attribute` and `instruction`, call the
      model for `_One`, `_write('artifact', artifact_id, attribute, value, grounded=1, source='model', model_version=provider.model)`,
      return `{"value", "grounded": True, "source": "model"}`. On any model error, return
      `{"value": "", "grounded": True, "source": "model", "error": str(exc)}` and do NOT cache.
- [x] `[AGENT]` `enrich(input_value, attribute, instruction) -> dict`: derive an attribute from a
      VALUE using world knowledge, NOT grounded. Same shape as `extract` but scope `'value'`,
      subject is the exact `input_value` string, `grounded=0`, and the prompt is
      `prompts.ENRICH_ATTRIBUTE`. An empty `input_value` returns `{"value": "", "grounded": False}`
      without a model call.
- [ ] `[AGENT]` `bucketize(values, instruction) -> dict`: collapse many raw values into fewer
      canonical buckets. De-duplicate and sort `values`; if there are 0 or 1 distinct values return
      the identity map; otherwise call the model once with `prompts.BUCKETIZE` filled with the
      `instruction` and the value list, for `_Buckets`; return its `mapping`, defaulting any value
      the model omitted to itself. This call is not cached (it is one call and its input set
      changes).
- [ ] `[AGENT]` `override(scope, subject, attribute, value) -> dict`: write a user correction,
      `source='user'`, `grounded` unchanged from any existing model row (or `1` if none), `model_version=''`.
      This is how a wrong value gets fixed. Return the stored row.
- [ ] `[AGENT]` Tests in `tests/test_derive.py` (use `store` fixture; stub the provider the way
      the existing tests stub it, search tests for `get_provider` or a provider fixture). Assert:
      `extract` caches (second call makes no model call), `extract` returns `grounded=True`,
      `enrich` returns `grounded=False` and caches by value (two artifacts with the same input value
      cause one `enrich` call), `override` wins over a model row on `_read`, a model failure yields
      an empty value and no cache row, `bucketize` maps `["Colombia","Argentina","France"]` onto
      fewer buckets given an instruction. Keep the fixtures domain-neutral where you can; the
      book/author/region words may appear ONLY inside these test fixtures, never in `derive.py`.
- [ ] `[AGENT]` `uv run pytest -q tests/test_derive.py` green; `uv run black src/enqueue/derive.py tests/test_derive.py`.

---

## PHASE P3 — The prompt templates (`src/enqueue/prompts.py`)

Add three module constants. They are TEMPLATES with `{placeholders}`; they must never name a
domain. The caller fills `{attribute}`, `{instruction}`, `{text}`, `{values}`.

- [x] `[AGENT]` `EXTRACT_ATTRIBUTE`: instruct the model to read the given artifact text and return
      ONLY the value of the named attribute described by the instruction, or an empty string if the
      text does not support one. Tell it not to guess beyond the text (this call is grounded). Reply
      as the `_One` JSON shape.
- [x] `[AGENT]` `ENRICH_ATTRIBUTE`: instruct the model to return the named attribute for the given
      input value using general knowledge, or an empty string if it does not know. State plainly that
      this is a knowledge lookup, not a fact from the user's data. Reply as `_One`.
- [x] `[AGENT]` `BUCKETIZE`: instruct the model to group the given list of raw values into a smaller
      set of canonical buckets per the instruction, returning a mapping of every raw value to its
      bucket. Reply as `_Buckets`.
- [x] `[AGENT]` No test needed for the strings alone; they are exercised by Phase P2 and P4 tests.

---

## PHASE P4 — The orchestrator and the planner (`src/enqueue/pivot.py`)

This is CODE. The only model calls it makes are through `derive` (P2) and the one planner call.
It never groups with the model. Header imports `derive`, `db`, and the provider.

A **spec** is a plain dict:

```python
{
  "subset": {"kind": "search" | "tags" | "ids", "value": "<query or comma tags or id list>"},
  "steps": [
    {"op": "extract", "attribute": "<name>", "instruction": "<what to pull from the note>"},
    {"op": "enrich",  "attribute": "<name>", "instruction": "<what to infer from the prior value>"}
  ],
  "group_by": "<attribute name; must be the last step's attribute>",
  "bucketize": true | false,
  "bucketize_instruction": "<how to canonicalize the group keys>"
}
```

- [ ] `[AGENT]` `resolve_subset(subset) -> list[str]`: return artifact ids. `kind='ids'` splits the
      value; `kind='tags'` calls `tags.ids_with_all(...)`; `kind='search'` runs
      `candidates.search_results(value, limit=MAX)` and takes the artifact ids. Cap at
      `MAX_PIVOT_ARTIFACTS = 200`; if more match, take the first 200 and record that it was truncated.
- [ ] `[AGENT]` `run(spec) -> dict`: the orchestration. In order:
      1. `ids = resolve_subset(spec["subset"])`.
      2. Maintain a dict `key_of[artifact_id]`. For the FIRST step (always `extract`): for each id,
         `derive.extract(id, step.attribute, step.instruction)`; set `key_of[id]` to its value.
      3. For each later step (`enrich`): collect the DISTINCT current values across all ids; call
         `derive.enrich(value, step.attribute, step.instruction)` once per distinct value (this is the
         per-value caching that keeps calls bounded); then remap `key_of[id]` through those results.
      4. If `spec["bucketize"]`: `mapping = derive.bucketize(list(set(key_of.values())), spec["bucketize_instruction"])`;
         remap `key_of` through `mapping`.
      5. Group: a `defaultdict(list)` from final key to artifact ids. An empty key becomes the bucket
         `""` rendered as "not determined" by the UI (never dropped, never hidden - rule 2 and the
         lens's D3 honesty).
      6. Return `{"groups": [{"key": k, "artifact_ids": v, "grounded": <False if any step was enrich else True>} ...],
         "truncated": <bool>, "group_by": spec["group_by"]}`, groups ordered by size descending.
- [ ] `[AGENT]` `run` must be resumable and cheap on re-run: because every `derive` call is cached,
      calling `run(spec)` twice makes model calls only for artifacts or values not seen before.
- [ ] `[AGENT]` `plan(request) -> dict`: one model call turning a natural-language request into a
      spec. Use a new `prompts.PIVOT_PLAN` template and a Pydantic model matching the spec shape.
      The model decides the subset, the step chain, and whether a step is `extract` (from the note) or
      `enrich` (world knowledge). Validate the returned spec: last step's attribute equals `group_by`;
      at least one step; every `enrich` follows an `extract` or another `enrich`. On an invalid or
      failed plan, raise a `PivotError` with a sentence the UI can show.
- [ ] `[AGENT]` Add `PIVOT_PLAN` to `prompts.py`: instruct the model to convert a request into the
      spec JSON, choosing `extract` when the value is in the note and `enrich` when it needs world
      knowledge, and to write a short `bucketize_instruction` when the group keys will be messy.
- [ ] `[AGENT]` Tests in `tests/test_pivot.py` (stub the provider): a two-step spec (extract then
      enrich) over a small fixture produces the expected groups; enrich is called once per distinct
      value not once per artifact; an empty derived key lands in the `""` group and is not dropped;
      `resolve_subset` truncates past the cap; a spec whose last step attribute differs from `group_by`
      is rejected. Use the book/author/region example as ONE fixture; assert the same code groups a
      second, unrelated fixture (e.g. recipes by cuisine) with zero code changes - this is the
      generalization guard.
- [ ] `[AGENT]` `uv run pytest -q tests/test_pivot.py` green; black clean.

---

## PHASE P5 — API

- [ ] `[AGENT]` `POST /pivot/plan` body `{"request": str}` returns `{"spec": <spec>}` from
      `pivot.plan`. 400 with the sentence on `PivotError`.
- [ ] `[AGENT]` `POST /pivot/run` body `{"spec": <spec>}` returns `pivot.run(spec)`, then hydrate each
      group's `artifact_ids` into wall items (reuse `_wall_item` the way `list_artifacts` does) so the
      client can render cards without a second round trip. Keep `grounded` and `truncated` in the response.
- [ ] `[AGENT]` `POST /derived/override` body `{"scope","subject","attribute","value"}` calls
      `derive.override(...)` so a user can correct a wrong derived value. Return the stored row.
- [ ] `[AGENT]` Tests in `tests/test_api_pivot.py` (TestClient): plan then run returns groups; override
      then re-run shows the corrected value winning. Green.

---

## PHASE P6 — UI (`museum.html`)

Product register: inline, no sidebar, hierarchy through space. Reuse existing tokens. Parse-check
after every edit (`bin/relaunch` gates on `node --check`).

- [ ] `[AGENT]` **Entry.** Add an "organize by..." affordance. The lightest place is the search/ask
      surface: a request like "organize book notes by author region" typed into the ask field is sent
      to `POST /pivot/plan` then `POST /pivot/run` when the model reads it as an organize request; or add
      a small explicit control. Choose the lighter option and keep it consistent with how search and ask
      already look.
- [ ] `[AGENT]` **Grouped render.** Generalize the lens's two-section view to N sections: one section
      per group, header = the group key (or "Not determined" for the empty key), then that group's cards
      in the existing wall grid. Order groups as the API returned them (largest first). The whole response
      is grounded=false when any enrich ran: show a small, quiet marker on the group headers reading that
      the grouping uses the assistant's knowledge, not text from your notes (rule 2). Do not bury it.
- [ ] `[AGENT]` **Correction.** On a group header (or a per-card affordance), allow moving an item to a
      different group, which calls `POST /derived/override` and re-runs. This is how a wrong value gets
      fixed; it must be visible, because a misfiled item is otherwise invisible.
- [ ] `[AGENT]` Do NOT change the plain wall, search, or the artifact card face. The pivot is a distinct
      view, entered deliberately and left by returning to the wall.
- [ ] `[AGENT]` Verify by looking: run an organize request, see N groups, see the "assistant's knowledge"
      marker when enrichment ran, correct one item and see it move and persist. Confirm keyboard focus on
      the new controls.

---

## Done

- [ ] `[AGENT]` `uv run pytest -q` green (was 260, now higher), `uv run black --check src/ tests/` clean,
      `bin/relaunch` starts, `uv run enq eval` unchanged from before this feature (pivot must not touch the
      search ranking path).
- [ ] `[HUMAN]` Review: confirm no attribute name, subject, or domain word is hardcoded in `derive.py` or
      `pivot.py`; confirm every enriched value is labeled inferred in the UI; confirm a corrected value
      survives a re-run; confirm the same engine groups two unrelated example requests with no code change.

## Out of scope (do not build unless a later plan says so)

- Saving a pivot as a permanent view (it is ephemeral, like the lens).
- Multi-key pivots (group by two attributes at once). One group key for now.
- Automatic re-derivation when an artifact changes; a stale cached value is acceptable until the user
  re-runs or overrides.
- Any domain-specific attribute library. There are no built-in attributes; every one comes from a spec.
- Numeric or date bucketing helpers. Bucketize is the model's job for now.
