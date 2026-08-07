# PROGRESS - Phase H - answers that outlive the page

## Orientation - read this first

Every AI answer in Enqueue is computed inside a synchronous HTTP request.
A person types a question, the browser holds the connection open while the local model grinds for twenty seconds or more, and only when the model returns does the request finish and the turn get written.

The cost of that shape shows the moment the person navigates away.
The browser aborts the open fetch, the answer they were waiting on is abandoned, and the work either dies or completes into a transcript nobody is looking at.
On a slow local model this is not an edge case, it is the common case: a person asks, gets bored of the spinner, clicks elsewhere, and their answer is gone.

The fix is to stop computing answers inside the request.
Submitting a question should return immediately, having written a visible **pending** turn to the chat.
A background worker computes the answer off the request thread and updates that turn in place when it is done.
The person can leave, close the tab, come back an hour later, and the answer is waiting in the transcript where the pending turn used to be.

This is the exact shape the ingest queue already uses for capture (hard rule 7: capture returns before processing).
Phase H brings the same discipline to answering: the request returns before the model runs, and the work is owned by a worker, not by an open socket.

### The two rules this phase serves

**Rule 1 - the work outlives the page.**
Once a question is submitted, its answer is computed and written to the transcript no matter what the client does - stays, navigates away, reloads, or closes the tab.
An answer is never tied to an open connection.
The only place an answer lives is the stored message, so the model result is always written there, never streamed to a client that may be gone.

**Rule 2 - a pending turn is honest and bounded.**
A turn being computed is shown as visibly pending, never as a fake-empty or a spinner that lies.
It always resolves: to `done` with the answer, or to `failed` with a reason a person can read.
It never silently vanishes, and it never hangs pending forever - an answer interrupted by an engine restart is swept to `failed`, not left spinning.

### The house style for this plan

Small, atomic, idempotent tasks a dumb LLM can do.
One checkbox is one commit is one green test run.
`[AGENT]` tasks an implementing agent does; `[HUMAN]` tasks only Minh does (desktop gates, commits).
The agent never commits.
Each task states its exact signature, SQL, test name, and verification command.
Plain dashes, never em-dashes; one full sentence per line in prose.

### Anchors (what already exists - do not rebuild)

- `chats.send(chat_id, text, force_skill=None)` - the dispatcher: route the text, run the skill, write the user turn plus the assistant turn plus citations in one transaction, then name and retopic. Phase H splits this into a synchronous submit and a worker-side completion. `src/enqueue/chats.py`.
- `chats.ask(text, scope_kind, scope_id)` - opens a new chat with its first turn by calling `send`. It becomes: create the chat, submit the first turn, return immediately.
- `chats.run_answer` / `chats.run_organize` - the skill runners. Unchanged: the worker calls them exactly as `send` does now. They already return a message dict and write nothing themselves.
- `chats._append(conn, chat_id, role, text, grounded=False, kind="answer", payload=None)` - writes one message row. Gains a `status` argument in H1. `src/enqueue/chats.py`.
- `chats.get` / its `_message` serializer - the chat the frontend renders. Gains `status` per message in H1.
- `src/enqueue/ingest/queue.py` - the capture worker: one daemon thread, an in-memory `queue.Queue`, `submit()` returns immediately, `_run()` loops. This is the exact pattern the answer worker mirrors. Do not reuse the same queue - answers are their own work with their own failure handling.
- `museum.html` - `renderChat(d, pending)` (the transcript, already branches on `m.kind`), `sendInChat(text, skill)` and `startChat(text)` (the submit paths), `composer()` (the input). The ephemeral `pending` argument to `renderChat` is replaced by real pending turns read from the stored messages.
- Migrations run via alembic `upgrade head`. Latest is `0013`. Next is `0014`. A new column is `ALTER TABLE ... ADD COLUMN`.

---

## Phase H1 - a message can be pending

A message today is always complete the instant it is written.
An async answer needs a message that exists before its content does, so the transcript can show it and the worker can fill it in.

- [x] **H1.1 [AGENT]** Migration `0014_async_messages.py` (`revision = "0014"`, `down_revision = "0013"`).
  One `ALTER TABLE chat_messages ADD COLUMN status TEXT NOT NULL DEFAULT 'done'`.
  `done` is the resting state and backfills every existing row correctly: everything written before this feature was already complete.
  A pending assistant turn is written with `status = 'pending'` and empty text; the worker moves it to `done` (with the real text) or `failed` (with a reason).
  Do not add a CHECK constraint on status, for the same reason `kind` has none: the set of states is owned by the code, and freezing it in the schema makes the next state a migration.
  Write a docstring block like 0013's explaining the column and the three states.
  Verify: `uv run alembic upgrade head` on a fresh temp DB, then `PRAGMA table_info(chat_messages)` shows `status`; `uv run alembic downgrade -1 && uv run alembic upgrade head` round-trips clean.

- [x] **H1.2 [AGENT]** Extend `chats._append` with `status: str = "done"`, threaded into the INSERT column list and placeholders.
  Every existing caller keeps writing `done` by omission, so nothing changes yet.
  Verify: `uv run pytest tests/test_chats.py -q`.

- [x] **H1.3 [AGENT]** Include `status` in `_message` (the `get` serializer), so every message the frontend receives carries its status.
  Do not change `kind`, `payload`, `grounded`, or `cited`.
  Verify: `GET /chats/{id}` on a seeded chat returns each message with a `status` of `"done"`. Add one assertion to the existing chat API test.

- [ ] **H1.4 [HUMAN]** Review the migration and the default-`done` backfill. Confirm no CHECK was added, then continue.

---

## Phase H2 - the answer worker

A background worker that computes one submitted answer and writes it into its pending turn.
Mirror the ingest queue: one daemon thread, an in-memory queue, submit returns immediately.

- [x] **H2.1 [AGENT]** New module `src/enqueue/chats_worker.py` (or a clearly separate section of a jobs module - not the ingest queue).
  It holds an in-memory `queue.Queue`, a single daemon worker thread started lazily, and `submit(job)` that returns immediately.
  A job is a small dataclass: `chat_id: str`, `message_id: str` (the pending assistant turn to fill), `text: str`, `force_skill: str | None`.
  The worker loop pops a job, computes, and completes the message; one bad job never stops the worker (log and move on), exactly like `ingest/queue.py::_run`.
  Verify: `python -c "from enqueue import chats_worker; print(hasattr(chats_worker, 'submit'))"` prints `True`.

- [x] **H2.2 [AGENT]** The worker's compute step reuses the existing dispatch, unchanged in behavior:
  `skill_name = force_skill if force_skill in assistant.REGISTRY else assistant.route(text)`, then `msg = assistant.REGISTRY[skill_name].run(chat_id, text)`.
  Then in one transaction it UPDATEs the pending message row to `status = 'done'` with `msg["text"]`, `grounded`, `kind`, `payload`, and writes the citations for that message id (the same citation write `send` does today).
  On any exception it UPDATEs the message to `status = 'failed'` with a short human sentence as its text ("That answer could not be completed."), and writes no citations.
  Naming and retopic (`_name`, `_retopic`) move here, run only after a successful `done`, best effort as today.
  Verify: unit test in H2.3.

- [x] **H2.3 [AGENT]** `tests/test_chats_worker.py`, stubbing the router through `assistant.get_provider` and the answer path through `chats.get_provider` + `chats.passages` exactly as `tests/test_assistant.py` does:
  - `test_worker_fills_a_pending_turn_to_done` - seed a chat with a pending assistant turn, run the worker's compute on it directly (synchronously, not through the thread), assert the row is now `status == 'done'` with the stubbed answer text and `kind == 'answer'`.
  - `test_worker_marks_a_failed_turn` - make the skill raise, assert the row is `status == 'failed'` with a non-empty human sentence and no citations.
  - `test_worker_runs_off_the_request` - `submit(job)` returns before the (stubbed, slow) compute finishes; assert the pending row is still pending immediately after submit and `done` after `wait_idle()`.
  Verify: `uv run pytest tests/test_chats_worker.py -q`.

---

## Phase H3 - submit returns immediately

`send` and `ask` stop computing and start submitting.
They write the pending turn and hand the work to the worker.

- [x] **H3.1 [AGENT]** Rewrite `chats.send(chat_id, text, force_skill=None)`:
  1. Validate as today.
  2. In one transaction: `_append` the user turn, then `_append` a pending assistant turn (`role="assistant"`, `text=""`, `status="pending"`), capturing its `message_id`.
  3. `chats_worker.submit(Job(chat_id, message_id, text, force_skill))`.
  4. Return `get(chat_id)` immediately - the chat now ends in a visible pending turn.
  No routing, no model call, and no naming happen on this path anymore; all of that moved to the worker (H2).
  Verify: H3.3.

- [x] **H3.2 [AGENT]** Rewrite `chats.ask(text, scope_kind, scope_id)` to match: `create` the chat, then run the same submit body as `send` (user turn plus pending assistant turn plus `submit`), and return the chat immediately.
  The old "delete the husk on failure" logic is gone: submitting cannot fail on the model (the model runs later, in the worker), so a chat is created only when a real question was submitted, and a failed answer becomes a `failed` turn inside it rather than a deleted chat.
  Verify: H3.3.

- [x] **H3.3 [AGENT]** `tests/test_chats.py` (or extend `test_assistant.py`):
  - `test_send_returns_a_pending_turn_without_calling_the_model` - stub the worker's `submit` to a no-op recorder; assert `send` returns a chat whose last message is `status == 'pending'`, and that no router or answer provider was called on the request path.
  - `test_ask_opens_a_chat_with_a_pending_first_turn` - same shape for `ask`.
  - Then let the worker run (call its compute directly on the recorded job) and assert the turn resolves to `done`.
  Verify: `uv run pytest tests/test_chats.py tests/test_assistant.py -q`. Run `uv run enq eval` and confirm answer quality is unchanged - the skill runners are byte-identical, only when they run changed.

- [ ] **H3.4 [HUMAN]** Review the submit split. Confirm the request path makes zero model calls, the worker owns routing and naming, and a failed answer lands as a `failed` turn, not a lost chat or a 500.

---

## Phase H4 - the transcript shows pending, resolves live, survives leaving

The UI stops holding an open request and starts reading stored state.
A pending turn renders as itself and refreshes until it resolves; leaving and returning just re-reads the transcript.

- [x] **H4.1 [AGENT]** In `renderChat`, render a message with `status === 'pending'` as a persistent thinking turn (the curator bubble with a quiet "reading what you saved..." state), and a message with `status === 'failed'` as a plain failed turn showing its text with a "Try again" affordance.
  Remove the old ephemeral `pending` argument path: the pending turn is now a real stored message, not a fake one drawn on top.
  Use `rg -a` on `museum.html` (NUL bytes); keep all styling in the existing inline `<style>` and tokens.

- [x] **H4.2 [AGENT]** `sendInChat(text, skill)` and `startChat(text)` stop awaiting the answer.
  They POST, take the returned chat (which ends in a pending turn), render it, and start polling: re-fetch `GET /chats/{id}` every ~2 seconds while any message is `pending`, re-rendering on change, and stop polling when none are pending.
  A single poller per chat; opening a different surface cancels it.
  Verify: submitting a question shows a pending turn immediately and it fills in when the worker finishes, with no held request.

- [x] **H4.3 [AGENT]** `showChat(id)` resumes the same poller when the chat it opens contains a pending message, so a person who left during an answer and comes back sees it finish without doing anything.
  Verify: submit a question, navigate home before it finishes, reopen the chat from the eye list, and watch the pending turn resolve on its own.

- [x] **H4.4 [AGENT]** A `failed` turn's "Try again" re-submits the same user text (the failed turn's preceding user message) as a fresh turn, exactly as a new question would.
  Verify: force a failure, click "Try again", a new pending turn appears and resolves.

---

## Phase H5 - interrupted answers do not hang

An engine restart with work outstanding leaves pending turns that no worker will ever finish.
Rule 2 says a pending turn always resolves, so startup must clean them up.

- [x] **H5.1 [AGENT]** On engine startup (in `serve()`, beside the trash purge), sweep every `chat_messages` row still `status = 'pending'` to `status = 'failed'` with the text "That answer was interrupted. Ask again."
  The in-memory queue does not survive a restart, so any pending row at boot is definitionally orphaned.
  Verify: `tests/test_chats_worker.py::test_startup_sweeps_orphaned_pending` - insert a pending row, run the sweep, assert it is now `failed`.

- [ ] **H5.2 [HUMAN]** Desktop pass: `bin/relaunch`, ask a question, quit the app mid-answer, relaunch, open the chat - the turn reads as interrupted with a way to retry, never a forever-spinner.

---

## Verification commands

```
uv run pytest -q                         # full suite green
uv run pytest tests/test_chats_worker.py tests/test_chats.py tests/test_assistant.py -q
uv run black --check .                    # style
uv run enq eval                           # answer quality unchanged (runners byte-identical)
bin/relaunch                              # desktop boots, JS parse-gates clean
```

## Out of scope for Phase H

- Token streaming. The answer appears when it is done, as it does today; streaming partial tokens is a different mechanism and a different feature.
- Async pivots and saved-grouping runs. The organize turn already renders after its run; routing organize through the same worker is a natural follow-on but is not in this phase - do chat answers first, where the wait bites hardest.
- Cancellation. A submitted answer runs to completion; a cancel control is a later addition, not part of making answers survive navigation.
- A durable job store. The in-memory queue plus the startup sweep is the right trade at this scale, matching the ingest queue: derived work, cheap to redo, never risking anything the person authored.
- Multiple workers. One serial worker matches the single local model and the ingest queue; concurrency is a later lever if one model ever becomes many.

## The two rules, restated (paste them into the worker and the render review)

1. **The work outlives the page.** An answer is computed and stored regardless of the client; it lives only in the stored message, never in an open connection. Enforced in H2/H3, tested in H2.3 and H3.3.
2. **A pending turn is honest and bounded.** Visibly pending, always resolving to done or failed with a reason, never hanging (H4.1, H5.1). No spinner that lies.
