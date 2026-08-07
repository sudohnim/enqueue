# PROGRESS - The assistant dispatcher (the eye is the one AI door)

## Orientation - read this first, all of it

Enqueue has one place a person types an unstructured request to the AI: the eye,
which opens a chat. Today that chat can do exactly one thing - answer a question
from the collection (`chats.send` -> retrieve passages -> ask the model -> write
one assistant message). The pivot engine (grouping the library by a computed
attribute) is a second, separate door: its own pill, its own view, `pivot.plan`
and `pivot.run` wired straight to the UI.

This plan makes the eye the **one** door. A person types anything into the chat.
A cheap **router** reads the request and picks a **skill** to run. `answer` is
one skill. `organize` (the pivot engine) is the second. The chosen skill runs,
and its result is written as a typed turn in the transcript - an answer turn
reads like today, an organize turn renders the grouped view inline. The
standalone organize pill goes away. The grid button is repurposed to list
**saved groupings** - a named pivot spec you can re-run.

Nothing here invents new retrieval, new grouping, or a new model call shape. It
is a **router in front of two things that already work**, plus a place to store
a turn's type and a place to save a spec. The whole feature is plumbing and one
small classification call.

### Why a router and not an if-statement

Two skills today, more later (summarize a set, draft from sources, extract a
table). An `if "group" in text` branch is a keyword guess that breaks the moment
a person writes "arrange my book notes by where the author lived" without the
word group. A registry of skills, each with a one-line description the router
reads, is the shape that holds when the third and fourth skills arrive: adding a
skill is adding a registry entry, not editing a branch. The router is one model
call that returns a skill name from the registry's own list.

### The two rules you must never break

These are the whole ethic of the feature. Every phase below serves them. If a
change would violate one, the change is wrong, not the rule.

**Rule 1 - `answer` is the floor. A structured skill is never guessed.**
The router defaults to `answer` on *any* uncertainty: an unrecognized skill
name, a failed model call, a request that does not clearly match a structured
skill, a structured skill that then errors. `answer` is grounded and safe - it
reads the collection and replies, or says it found nothing. It is never wrong to
fall back to it. It *is* wrong to run `organize` on a request that was really a
question, produce an empty grouping, and call that an answer. When in doubt,
answer.

**Rule 2 - the chosen skill is declared and reversible. Never silent.**
Every non-answer turn says which skill ran ("Organized by region") and offers a
one-click way back to the floor ("answer instead", which re-sends the same text
forcing `answer`). A person is never surprised by what the AI decided to do with
their words, and is never trapped in that decision. Routing you cannot see and
cannot undo is a routing you cannot trust.

### The house style for this plan (same as the pivot plan before it)

- **Small, atomic, idempotent tasks a dumb LLM can do.** One checkbox = one
  commit = one green test run. No task assumes cleverness. If a task needs a
  judgment call, the judgment is written out here, not left to the implementer.
- **`[AGENT]`** tasks an implementing agent does. **`[HUMAN]`** tasks only Minh
  does (review gates, running the desktop, committing). The agent never commits.
- Each task states its **exact** signature / SQL / test names and its
  **verification command**. Green means done; then check the box.
- Generalizable, not overfit. `answer` and `organize` are the first two skills,
  but nothing in the router or the dispatch loop names them specially beyond the
  registry. A third skill is a registry entry and a runner - no router edit, no
  dispatch edit, no schema change.

### Anchors (what already exists - do not rebuild)

- `chats.send(chat_id, text)` - the current answer path. Gets history, retrieves
  `passages()`, `_ask_model`, writes the user turn + assistant turn + citations
  in one transaction. This becomes the body of the `answer` skill, extracted
  verbatim. `src/enqueue/chats.py`.
- `chats._append(conn, chat_id, role, text, grounded=False) -> message_id` -
  writes one row to `chat_messages`, computes the next ordinal. Gets two new
  optional params in S1. `src/enqueue/chats.py:381`.
- `pivot.plan(request) -> spec` and `pivot.run(spec) -> {groups, truncated,
  group_by}` and `pivot.PivotError`. The organize skill calls these. Do not
  touch pivot.py's logic. `src/enqueue/pivot.py`.
- The pivot API render helper `_wall_item` and `POST /pivot/run` in
  `src/enqueue/api.py` - the organize turn reuses the same group hydration.
- `renderChat(d, pending)` and `renderPivot(...)` in
  `src/enqueue/static/museum.html`. The transcript loop is at line ~5745 (`for
  (const m of d.messages)`). Organize turns render inside that loop.
- Migrations run via alembic `upgrade head` (`db.py`). Latest is `0012`. Next is
  `0013`. A new table is a plain `CREATE TABLE`; a new column on `chat_messages`
  is `ALTER TABLE ... ADD COLUMN`. Nothing else creates these two objects, so no
  `IF NOT EXISTS` store-race dance is needed (unlike 0011/0012).

---

## Phase S1 - the schema a typed turn needs

A turn is currently only role + text + grounded. To render an organize turn on
reload, the transcript must remember two more things: **what kind** of turn it
was, and, for a structured skill, **the spec that produced it** so the view
re-runs from stored intent, not from re-classifying the old text. Saved
groupings need their own tiny table.

- [x] **S1.1 [AGENT]** Migration `0013_assistant_turns.py` (`revision = "0013"`,
  `down_revision = "0012"`). Two `ALTER TABLE chat_messages ADD COLUMN`:
  - `kind TEXT NOT NULL DEFAULT 'answer'` - the skill that produced the turn.
    Defaulting to `'answer'` backfills every existing row correctly: everything
    written before this feature was an answer.
  - `payload TEXT` (nullable) - JSON the turn needs to re-render itself. NULL for
    an answer (its text is the whole turn). For an organize turn, the pivot spec
    (a dict), so the view re-runs on reload without re-planning.
  Do **not** add a `CHECK (kind IN (...))`: a CHECK freezes the skill list into
  the schema and a third skill would need a migration to add a turn type. `kind`
  stays open; the registry is the source of truth for valid names, not the DB.
  Write a docstring block like 0012's explaining both columns and why `kind` is
  unconstrained.
  Verify: `uv run alembic upgrade head` on a fresh temp DB, then
  `PRAGMA table_info(chat_messages)` shows both columns.

- [x] **S1.2 [AGENT]** Same migration, new table `saved_pivots`:

  ```sql
  CREATE TABLE saved_pivots (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    spec_json  TEXT NOT NULL,   -- the pivot spec, exactly as pivot.run() eats it
    created_at TEXT NOT NULL
  )
  ```

  No `IF NOT EXISTS` - nothing but this migration creates it. `downgrade()` drops
  the table and the two columns (SQLite `DROP COLUMN` works on the pinned
  version; if it rejects, leave a comment that downgrade is dev-only and drop
  just the table).
  Verify: `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run
  alembic upgrade head` round-trips clean.

- [x] **S1.3 [AGENT]** Extend `chats._append` to carry the two new fields:
  `_append(conn, chat_id, role, text, grounded=False, kind="answer",
  payload=None)`. When `payload` is not None, `json.dumps` it before the INSERT;
  store NULL otherwise. Both new params default so every existing caller is
  untouched. Update the INSERT column list + placeholders.
  Verify: existing chat tests still pass - `uv run pytest tests/test_chats.py
  -q`. No new test yet; S3 exercises the new params.

- [x] **S1.4 [AGENT]** Wherever a chat message is read back for the API
  (`get_chat` / the messages serializer feeding `renderChat`), include `kind`
  and parse `payload` from JSON to a dict (or None). The turn dict the frontend
  receives gains `kind` and `payload`. Do not change `grounded`, `cited`, etc.
  Verify: `GET /chats/{id}` on a seeded chat returns messages each with a `kind`
  of `"answer"` and `payload` null. Add one assertion to the existing chat API
  test.

- [x] **S1.5 [HUMAN]** Review the migration and the `_append` change. Confirm the
  default-`'answer'` backfill is right for the existing corpus and that no CHECK
  was added. Then continue.

---

## Phase S2 - the skill registry and the router

One new module, `src/enqueue/assistant.py`. It holds the registry (a mapping of
skill name -> a small descriptor) and `route(request) -> skill_name`. It does
**not** run skills yet - S3 wires dispatch. Keep the classification and the
registry in one place so adding a skill is a one-file edit.

- [x] **S2.1 [AGENT]** Define the skill descriptor and registry. A skill is a
  plain dataclass: `name: str`, `describe: str` (one line the router prompt shows
  the model - "answer a question from the collection", "organize a set of notes
  into groups by a computed attribute"), and `run: Callable[[str, str], dict]`
  (chat_id, text) -> the message dict the dispatcher will store (`{role, text,
  grounded, kind, payload, cited}`). Register two entries: `answer` and
  `organize`. The `run` callables come from S3; for now point them at stubs that
  raise `NotImplementedError` so the registry imports clean and the router can
  list names.
  Verify: `python -c "from enqueue.assistant import REGISTRY; print(sorted(REGISTRY))"`
  prints `['answer', 'organize']`.

- [x] **S2.2 [AGENT]** `route(request: str) -> str`. One model call. Prompt is
  built from the registry: list each skill's name + `describe`, ask the model
  which single skill best fits the request, and instruct it that when nothing
  clearly fits a structured skill, it must pick `answer`. Response model is a
  one-field Pydantic (`skill: str`). Then **clamp to the floor**: if the returned
  name is not in `REGISTRY`, return `"answer"`. Wrap the whole call in
  try/except - on any exception return `"answer"`. Empty/whitespace request
  returns `"answer"` without calling the model. This function can never raise and
  can never return a name outside the registry (Rule 1, in code).
  Put the prompt template in `src/enqueue/prompts.py` next to `PIVOT_PLAN`
  (`ASSISTANT_ROUTE`), built from a `{skills}` block and `{request}`.
  Verify: unit test below.

- [x] **S2.3 [AGENT]** `tests/test_assistant.py`, router tests, provider stubbed
  the way `test_pivot.py` stubs it (`monkeypatch.setattr(assistant,
  "get_provider", lambda: _FakeProvider(...))`):
  - `test_routes_to_a_named_skill` - stub returns `{"skill": "organize"}`,
    assert `route(...) == "organize"`.
  - `test_unknown_skill_name_falls_to_answer` - stub returns `{"skill":
    "translate"}` (not registered), assert `route(...) == "answer"`. **Rule 1.**
  - `test_model_error_falls_to_answer` - stub raises, assert `route(...) ==
    "answer"`. **Rule 1.**
  - `test_empty_request_falls_to_answer` - `route("")` and `route("   ")` return
    `"answer"` without calling the model at all.
  Verify: `uv run pytest tests/test_assistant.py -q`.

- [x] **S2.4 [HUMAN]** Review the router prompt wording and the two clamps.
  Confirm the prompt tells the model to prefer `answer` under doubt, and that the
  code enforces it regardless of what the model says. This is Rule 1's home;
  read it closely.

---

## Phase S3 - dispatch: `chats.send` becomes route -> run -> store typed turn

Now the two skills get real `run` bodies and `chats.send` stops being the answer
path and becomes the dispatcher.

- [x] **S3.1 [AGENT]** Extract today's `chats.send` body into an `answer` skill
  runner - move the retrieve-passages -> `_ask_model` -> compose logic into a
  function `run_answer(chat_id, text) -> dict` that returns `{role:
  "assistant", text, grounded, kind: "answer", payload: None, cited: [...]}`
  **without writing to the DB** (the dispatcher writes). Point the registry's
  `answer.run` at it. Behavior must be byte-identical to today's answer.
  Verify: existing chat send tests pass unchanged - `uv run pytest
  tests/test_chats.py -q`.

- [x] **S3.2 [AGENT]** `organize` skill runner `run_organize(chat_id, text) ->
  dict`. Body: `spec = pivot.plan(text)`; `result = pivot.run(spec)`. Return
  `{role: "assistant", text: <a one-line human summary, e.g. "Organized {N}
  notes by {group_by} into {G} groups.">, grounded: <all groups grounded?>,
  kind: "organize", payload: spec, cited: []}`. The rendered groups are **not**
  stored in text - the frontend re-runs the spec from `payload` (S4). On
  `pivot.PivotError`: **do not store an organize turn**. Instead call
  `run_answer(chat_id, text)` and return that. **Rule 1 in the runner**: a
  structured skill that cannot execute falls to the floor rather than storing a
  broken group.
  Verify: unit test in S3.5.

- [x] **S3.3 [AGENT]** Rewrite `chats.send(chat_id, text)` as the dispatcher:
  1. `skill_name = assistant.route(text)`.
  2. `skill = REGISTRY[skill_name]` (route guarantees membership).
  3. `msg = skill.run(chat_id, text)`.
  4. In one transaction: `_append(conn, chat_id, "user", text)` then
     `_append(conn, chat_id, "assistant", msg["text"], grounded=msg["grounded"],
     kind=msg["kind"], payload=msg["payload"])`, then write `cited` citations
     for the assistant turn exactly as today.
  The transaction shape (both turns + citations atomic) is preserved from the
  current `send`. Only the middle - "what produced the assistant text" - changed
  from hardcoded answer to routed skill.
  Verify: S3.5.

- [x] **S3.4 [AGENT]** `chats.send` gains an optional `force_skill: str | None =
  None`. When set and in `REGISTRY`, skip `route()` and use it directly. This is
  the server side of Rule 2's "answer instead" - the frontend re-sends the same
  text with `force_skill="answer"`. When `force_skill` is None or unknown, route
  normally. The API `POST /chats/{id}/messages` gains an optional `skill` field
  passed through.
  Verify: S3.5.

- [x] **S3.5 [AGENT]** `tests/test_assistant.py` dispatch tests (or extend
  `test_chats.py`), stubbing both `assistant.get_provider` (router) and the
  skill dependencies (`derive.get_provider` for organize's pivot, the answer
  model for answer):
  - `test_send_answer_stores_an_answer_turn` - router picks answer; the stored
    assistant row has `kind == "answer"`, `payload is None`.
  - `test_send_organize_stores_an_organize_turn` - router picks organize, pivot
    stubbed to a real spec+groups; stored row has `kind == "organize"` and
    `payload` round-trips to the spec.
  - `test_organize_planerror_falls_to_answer` - router picks organize,
    `pivot.plan` raises `PivotError`; the stored turn is `kind == "answer"`.
    **Rule 1.**
  - `test_force_skill_answer_bypasses_router` - `send(..., force_skill="answer")`
    stores an answer turn even though the router stub would pick organize.
    **Rule 2.**
  Verify: `uv run pytest tests/test_assistant.py tests/test_chats.py -q`.

- [x] **S3.6 [HUMAN]** Review dispatch. Confirm the transaction still writes both
  turns + citations atomically, that answer behavior is unchanged, and that both
  fall-to-answer paths (PlanError, force) land correctly. Run the full suite:
  `uv run pytest -q`. Then `uv run enq eval` - the eval measures answer quality
  and must be **unchanged** (answer path is byte-identical).

---

## Phase S4 - the transcript renders typed turns (declared + reversible)

The chat view already loops `d.messages`. An `answer` turn renders exactly as
today. An `organize` turn renders the grouped view inline, labeled, with the way
back. This is Rule 2's home in the UI.

> **Fixed after S3, found in S4 review:** the *first* message of a chat did not
> route. The eye opens a new chat via `POST /chats` -> `chats.ask`, which was the
> old hardcoded answer path - so "organize my notes by X" typed fresh was always
> answered, never grouped (the exact path the feature is for). `chats.ask` now
> creates the chat and dispatches through `send`, so the first turn routes like
> any later one; a failing first turn deletes its own empty husk (the old
> no-empty-conversation promise, preserved). Regression tests:
> `TestAskRoutesTheFirstMessage` in `tests/test_assistant.py`.

- [x] **S4.1 [AGENT]** In `renderChat`'s message loop (`museum.html` ~5745),
  branch on `m.kind`. `answer` (and any unknown kind, defensively): render as
  today. `organize`: render the assistant bubble with (a) the one-line label
  from `m.text` ("Organized by region"), (b) the grouped view, (c) the "answer
  instead" control.
  Use `rg -a` to read the file (NUL bytes). Keep all styling in the existing
  inline `<style>` and token vars - no new colors, no CDN.

- [x] **S4.2 [AGENT]** The organize turn's groups: re-run the spec. Reuse `POST
  /pivot/run` with `{spec: m.payload}` (one run endpoint, no fork) to get the
  hydrated groups (`_wall_item` per artifact, per-group `grounded`), and render
  them with the **existing** `renderPivot` group markup - the `.pivotgroup`
  sections, the `.groundnote` marker when `groups.some(g => g.grounded ===
  false)`. Do not fork a second grouping renderer; call the same one the
  standalone pivot used.
  Verify: seed a chat with an organize turn, load it, confirm the groups render
  identical to the old standalone pivot for the same spec.

- [x] **S4.3 [AGENT]** The "answer instead" control on every organize turn:
  a small button in the turn that re-sends the **same** user text with
  `skill: "answer"` (S3.4's force), appending a fresh answer turn below. Label it
  plainly ("Answer instead", not an icon-only). This is Rule 2: the routing is
  reversible in one click, always visible.
  Verify: clicking it on an organize turn produces an answer turn for the same
  question.

- [x] **S4.4 [AGENT]** The move/correction control that the standalone pivot had
  (`pivotMove`/`pickGroup`, writing `POST /derived/override` at scope='artifact')
  must keep working inside the in-chat organize turn - it is the same rendered
  groups, so wire the same handlers. A correction re-runs the turn's spec (S4.2)
  so the moved artifact lands in its new group. Confirm the override still wins
  after enrich (pivot.py already handles this; this task is only that the UI
  handler is present in the chat render path).
  Verify: move an artifact between groups in a chat organize turn; reload; it
  stays moved (override persisted, spec re-run reflects it).

- [ ] **S4.5 [HUMAN]** Run the desktop (`bin/relaunch`). Type a question - get an
  answer. Type "organize my notes by ..." - get a labeled, grounded-marked group
  view inline. Click "answer instead" - get the answer. Move an artifact between
  groups. Pixel-check the organize turn against the app's editorial theme
  (cream, yellow accent, IBM Plex): the inline groups must not look like a
  bolted-on panel. Fix anything that looks off before continuing.

---

## Phase S5 - saved groupings and the grid button

A grouping worth keeping gets a name and a home. The grid button (which used to
do nothing useful for AI) becomes the saved-groupings list.

- [x] **S5.1 [AGENT]** `src/enqueue/pivots_saved.py`: `save(name, spec) -> id`
  (uuid, `json.dumps(spec)`, `created_at`), `list() -> [{id, name, created_at}]`
  (newest first), `get(id) -> {id, name, spec}`, `delete(id)`. Plain SQLite over
  `saved_pivots`. No model calls.
  Verify: `tests/test_saved_pivots.py` - save then list then get round-trips the
  spec; delete removes it. `uv run pytest tests/test_saved_pivots.py -q`.

- [x] **S5.2 [AGENT]** API: `POST /pivots` (body `{name, spec}` -> `{id}`),
  `GET /pivots` (list), `GET /pivots/{id}` (with spec), `DELETE /pivots/{id}`.
  Running a saved one reuses `POST /pivot/run` with the fetched spec (no new run
  path). Wire to S5.1.
  Verify: curl each; add one API test asserting save->list->run works.

- [x] **S5.3 [AGENT]** "Save this grouping" action on an organize turn (S4):
  a small control that prompts for a name (the app's own input affordance, never
  a browser `prompt()` if the app has a nicer one) and `POST /pivots` with the
  turn's `payload` spec. On success, a quiet confirmation. Naming is the **only**
  place a person types a name; grouping itself never prompts (consistent with
  "never prompt for a tag at capture").
  Verify: save from a turn; it appears in `GET /pivots`.

- [x] **S5.4 [AGENT]** Repurpose the grid button in the ribbon: it opens the
  saved-groupings list (a view or sheet listing each saved grouping by name +
  when saved). Clicking one **runs** it - render the same grouped view
  (`renderPivot` + `POST /pivot/run` on the stored spec) as a standalone result
  surface (not a chat turn; a saved grouping is a re-openable view, not a
  conversation). Each row has a delete affordance (`DELETE /pivots/{id}`).
  Empty state: a plain line telling the person groupings they save from the eye
  land here. Do not leave the button doing its old thing.
  Verify: save two groupings, open the grid button, run one, delete the other.

- [ ] **S5.5 [HUMAN]** Desktop review of saved groupings: save from a chat, open
  the grid list, run it, confirm it matches what the chat turn showed, delete it.
  Empty state legible. Theme-consistent.

---

## Phase S6 - remove the standalone organize door

The eye is now the only unstructured AI door. The old organize pill and its mode
are dead weight and a second way to do one thing (the exact maintainability tax
the one-paradigm rule warns against).

- [x] **S6.1 [AGENT]** Remove the standalone `organize` pill / `openField(
  'organize')` entry point and its `startPivot` top-level invocation from the
  ribbon. Keep `renderPivot` and the run endpoint - they are reused by the chat
  organize turn (S4) and saved groupings (S5). Delete only the *entry point*, not
  the renderer.
  Verify: `rg -a "openField\('organize'\)|startPivot" src/enqueue/static/museum.html`
  returns nothing in an entry-point context; the pill is gone from the ribbon.

- [x] **S6.2 [AGENT]** Sweep for now-dead code the removed pill used and nothing
  else does (a dedicated organize view container, its show/hide handler). Remove
  what is provably unreferenced; leave anything the chat turn or saved groupings
  still call. When unsure whether something is shared, keep it and note it.
  Verify: `bin/relaunch` parse-gates the JS clean; the app boots; the eye and the
  grid button are the only two AI-grouping entry points.

- [ ] **S6.3 [HUMAN]** Final desktop pass. Confirm exactly two doors: the eye
  (type anything -> routed) and the grid button (saved groupings). No orphaned
  organize pill. Run `uv run pytest -q`, `uv run black --check .`, `uv run enq
  eval` (answer quality unchanged). Commit each phase's work as its own commit
  (agent never commits; you do).

---

## Verification commands (the whole feature)

```bash
uv run pytest -q                 # full suite green
uv run pytest tests/test_assistant.py tests/test_saved_pivots.py -q
uv run black --check .           # style
uv run enq eval                  # answer quality UNCHANGED (answer path byte-identical)
bin/relaunch                     # desktop boots, JS parse-gates clean
```

## Out of scope (do not build here)

- A third skill (summarize, draft, extract-table). The registry makes it a
  one-file add later; adding one now is scope creep.
- Streaming the organize turn. It renders after the run completes, like the
  standalone pivot did.
- A structured `field` op for pivot (grouping by `kind`/pdf-ness without a model
  call). Independent of the dispatcher - planned as **Phase F** below, to be
  built after the dispatcher's human gates pass.
- Router memory / multi-turn skill state. Each `send` routes its own text.
  A follow-up in an organize thread still routes fresh (and can be an answer).
- Renaming or re-theming the eye. It is already the door; this plan only makes it
  the *only* door.

## The two rules, restated (paste them into the router and the render review)

1. **`answer` is the floor.** Uncertain route, unknown skill, model error, skill
   error -> `answer`. A structured skill is never guessed. Enforced in code in
   S2.2 and S3.2, tested in S2.3 and S3.5.
2. **Declared and reversible.** Every non-answer turn says what ran and offers
   "answer instead" (S4.1, S4.3). No silent routing, no trap.

---

# Phase F - the `field` op (structured attributes, zero model calls)

## Why this exists

Live-test finding: "organize my saved things by kind" over the whole library
planned an `extract` step and ran it **per artifact** - ~124 sequential model
calls, ~40 minutes on a slow local model. But `kind` is not something to read out
of a note's prose; it is a column already on the row (`note | link | pdf | image
| file`). The engine paid a model to re-derive a fact it already stored.

The fix is a third step op beside `extract` and `enrich`:

- `extract` - read an attribute from the artifact's **text**. One model call per
  artifact. Grounded.
- `enrich` - infer an attribute from a prior **value** using world knowledge.
  One model call per distinct value. Not grounded.
- `field` - read an attribute straight from the artifact's **own structured
  metadata** (its kind, its source, when it was saved). **Zero** model calls.
  The most grounded of the three: it is literally the user's stored data.

"organize by kind" becomes one `field` step: one batched SQL read, instant, over
any number of artifacts. The 40-minute path disappears for the whole class of
structured-attribute groupings.

### The rule this phase must never break

**A `field` reads only what the row already holds - it never invents.** The set
of readable fields is a fixed registry of real columns and trivial derivations of
them (a URL's host, a timestamp's month). No field guesses, infers, or calls a
model; a request for an attribute not in the registry is not a `field` step (the
planner falls back to `extract`/`enrich`). `field` is the grounded floor of the
pivot engine exactly as `answer` is the grounded floor of the dispatcher.

### Anchors

- `derive.extract` / `derive.enrich` / `derive.bucketize` / `derive._read` /
  `derive.override` - the per-item primitives. `field` joins them as a fourth.
  `src/enqueue/derive.py`.
- `pivot.run` first-step loop (`src/enqueue/pivot.py:120-146`) - today the first
  step is always `extract`. It gains a `field` branch. The enrich correction
  logic (a user override at scope='artifact' wins) is the pattern to mirror.
- `pivot.plan` / `_validate_plan` and `PIVOT_PLAN` in `prompts.py` - the planner
  learns the `field` op and the registry.
- artifacts columns: `kind, title, source_url, mime, filename, created_at,
  updated_at, local_only, status, pages`. The registry reads these; it does
  not add columns.

---

## F1 - the field registry and `derive.field`

- [x] **F1.1 [AGENT]** New module `src/enqueue/fields.py` holding the registry:
  `FIELDS: dict[str, Field]` where a `Field` is `{name, describe, resolve}`.
  `describe` is the one line the planner prompt shows (like the skill registry's
  `describe`). `resolve(row) -> str` maps one artifact row to its label, pure and
  model-free. Start with exactly three, all from real columns, none hardcoding a
  domain vocabulary (the *values* come from the data):
  - `kind` - `row["kind"]` (note/link/pdf/image/file). describe: "what kind of
    thing it is (note, link, pdf, image, file)".
  - `source` - the host of `source_url` (`urlsplit(...).hostname or ""`), "" when
    there is no url. describe: "the website a link or file came from".
  - `captured` - `row["created_at"][:7]` (the `YYYY-MM` month). describe: "the
    month it was saved".
  A resolver returning `""` is legal and becomes the "not determined" bucket,
  exactly like an empty extract - never dropped.
  Verify: `tests/test_fields.py::test_resolvers` - build a fake row dict for each
  field and assert the label. `uv run pytest tests/test_fields.py -q`.

- [x] **F1.2 [AGENT]** `derive.field(artifact_id, field_name) -> dict` returning
  the same shape as `extract` (`{"value", "grounded": True, "source": "field"}`).
  Body: a user override wins first (`_read("artifact", artifact_id, field_name)`
  with `source == "user"` - rule 2, mirrors the enrich path); otherwise read the
  artifact row and apply `FIELDS[field_name].resolve`. **Do not cache** a field
  read: it is a free SQL read and caching would risk serving a stale label after
  the row changes. An unknown `field_name` raises `KeyError` (the planner's
  validation prevents it reaching here; this is the belt).
  Verify: `tests/test_fields.py::test_field_reads_the_row` and
  `::test_user_override_wins` (write an override via `derive.override`, assert
  `derive.field` returns it). No model call happens - assert with a provider that
  raises if called.

---

## F2 - `run()` executes a `field` first step

- [x] **F2.1 [AGENT]** In `pivot.run`, the first-step loop branches on
  `first["op"]`: `"extract"` as today; `"field"` reads every artifact's label via
  `derive.field(artifact_id, first["attribute"])` - no model call. Everything
  downstream (enrich steps, bucketize, group-by, empty-key bucket, override) is
  unchanged: a `field` first step is just a cheaper way to fill `key_of`.
  A run whose only step is a `field` is fully grounded (`any_enrich` stays False).
  Verify: `tests/test_pivot.py::test_field_step_groups_with_no_model_calls` -
  three artifacts of two kinds, a one-step `field` spec on `kind`, a provider that
  raises if `complete` is called; assert the groups are correct and `grounded`,
  and that the provider was never called.

- [x] **F2.2 [AGENT]** `tests/test_pivot.py::test_field_then_enrich` - a `field`
  step (`kind`) followed by an `enrich` step is a valid chain (structured read,
  then world-knowledge inference on top). Assert the enrich runs once per distinct
  kind and the run is marked not grounded (an enrich taints the whole run, exactly
  as with an extract lead). This proves `field` composes, not just stands alone.

---

## F3 - the planner emits `field` ops

- [x] **F3.1 [AGENT]** Extend `PIVOT_PLAN` (`prompts.py`): teach the third op.
  Add a rule - "If the attribute is a property the item already carries - its
  kind, the site it came from, when it was saved - use a `field` step, which reads
  it directly with no interpretation. Use `extract` only for something stated in
  the item's own text, and `enrich` only to infer from a previous value." Inject
  the registry the way the router injects skills: a `{fields}` block of
  `- name: describe` lines, and instruct that a `field` step's attribute must be
  one of those names. Keep `extract`/`enrich` attributes free-form.

- [x] **F3.2 [AGENT]** `_validate_plan` (`pivot.py`): allow `op == "field"`
  alongside extract/enrich. A `field` step whose attribute is not in
  `fields.FIELDS` raises `PivotError` with a UI sentence ("The plan reads a field
  'X' I do not know how to read straight from your items."). The
  enrich-cannot-lead rule stays; a `field` **can** lead (it is a grounded read).
  Verify: `tests/test_pivot.py::test_plan_rejects_unknown_field` (stub the planner
  to return a `field` on a nonexistent attribute; assert `PivotError`).

- [x] **F3.3 [AGENT]** `tests/test_pivot.py::test_plan_uses_field_for_kind` -
  stub the planner to return a one-step `field` spec on `kind` for "organize by
  kind"; assert `plan()` accepts it and `group_by == "kind"`. Documents the
  intended planner behavior even though the stub, not a live model, produces it.

---

## F4 - verify the path is instant

- [ ] **F4.1 [HUMAN]** Desktop: `bin/relaunch`, ask the eye "organize my saved
  things by kind" over everything. It routes to `organize`, plans a `field` step,
  and returns groups **immediately** (no per-artifact model wait). Compare against
  the old 40-minute extract path to confirm the win. Save the grouping; re-open it
  from the grid button and confirm it re-runs instantly and reflects any newly
  captured items.

## Out of scope for Phase F

- More fields than the three (tags-as-groups, file size, page-count buckets).
  Each is a one-line registry add later; three proves the shape.
- A `field` that computes across artifacts (counts, rankings). `field` is a
  per-item read, nothing more.
- Making `extract` fall back to `field` automatically. The planner chooses; the
  op stays explicit so a spec always says exactly what it read and how.
