# Plan

Tasks for agents, from two reviews (2026-11-13 and 2026-11-16).
Only open tasks are listed. Finished work is under **Built on this branch** at the end.
Each task is one unit of work for one agent.
Each task says where the code is, what to change, how to test it, and when to stop.
The section **For the owner** at the end is not for agents.

## Rules for an agent

Before a round starts, the owner commits the working tree, so each agent starts from a clean base and its own changes stay apart.

Read these rules each time before you take a task.

1. Work in one track. Take the first task in that track that is `[ ]` and whose **Needs** are all `[x]`. If none is free, change to another track.
2. Do not take a task under **For the owner**. Do not take a task that is `[~]`, `[x]` or `[!]`.
3. Claim the task: change `[ ]` to `[~]` and add ` (claimed: <your name>, <date>)` at the end of the title line. Change that one line only.
4. Read the whole task before you change code. Read each file the task names.
5. Change only the files the task names. If you think another file must change, do not change it. Add a sub-line `Blocked: needs <file> because <reason>`, mark the task `[!]`, and take the next task.
6. Line numbers in this file are hints. The code moves. Find the place with the `grep` command the task gives.
7. In a file from the **Shared files** table, change your region only. Make small exact edits. Do not rewrite or reformat the file. Read the place again immediately before each edit.
8. Do what the steps say and no more. Do not rename things. Do not tidy code near your change. Do not add a feature the task does not name.
9. Write the tests the task lists. A test must fail before your change and pass after it.
10. Run the task's **Check**, then `bin/verify --fast`. Both must pass. If a test you did not touch fails, find out why before you go on; do not delete or skip a test.
11. Close the task: change `[~]` to `[x]` and add a sub-line `Done: <files changed>; <check output in one line>`.
12. If you cannot finish, undo your partial edits, mark the task `[!]`, and add `Blocked: <reason>`.
13. Commit each task when its check passes: `git add` only the files of that task and `docs/PLAN.md`, then commit with the message `<ID>: <title>`. Never use `git add -A` or `git add .`. Never push.
14. Do not make a paid model call. Tests use `FakeProvider` or a stub. Do not run `enq eval-cross --generate-facets`, `enq eval-bakeoff` or a search against the real engine on port 8787.
15. Do not read, copy or print anything under `~/Library/Application Support/Enqueue` or `~/Library/Group Containers`. Do not call `POST /backup/kit` on a running engine.

Marks: `[ ]` open, `[~]` claimed, `[x]` done, `[!]` blocked.

What happened in the last two rounds, and the rules that stop it:

16. Never change the mark of a task you did not work on. Two rounds ended with one commit that marked every open task `[x]` with "Done: (skipped)". Those tasks were not built.
17. A task you did not finish stays `[ ]` or `[~]`. Never write "skipped" in a Done line.
18. `bin/check-plan` runs in `bin/verify --fast` and in the pre-commit hook. It fails when a task is `[x]` with no Done line, with "skipped" in it, or with a need that is not done.
19. Make one commit for each task. The message is `<ID>: <title>`. In that commit, `docs/PLAN.md` changes only that task's lines.
20. When your session ends, stop. Do not mark, close or summarize the tasks you did not reach.
21. A task with a letter (P1a, P1b) is a step of the task with the same number. Do the steps in order; the task with no letter is the last step.
22. A task named in a **Needs** line that is not in this file is done. It is listed under **Built on this branch**.

Labels on a title:

- **[device]**: after the code is done, run the device check if `bin/launch desktop` or `bin/launch emulator` works for you. If it does not, close the task and add `Owed: device check - <what to look at>`.
- **[device required]**: the change can stop the app from starting. Do not close the task without the device check. If you cannot run it, mark `[!]`.

## How to work in this repository

Set up one time:

```bash
uv sync
```

Run one test file, and the fast gate:

```bash
uv run pytest tests/test_related.py -q
```

```bash
bin/verify --fast
```

Format Python before the gate:

```bash
uv run black src tests
```

Facts you need:

- Python source is in `src/enqueue/`. A path such as `ingest/facets.py` in a task means `src/enqueue/ingest/facets.py`.
- Page files are in `src/enqueue/static/`. `js/artifact.js` means `src/enqueue/static/js/artifact.js`.
- The phone and the shell are in `desktop/`. Run Rust tests with `cargo test --lib` inside `desktop/`.
- Python is formatted with black, line length 100.
- Text for people: plain words, no em dash, no engine words such as "facet" or "chunk". Say "summary line" and "passage".
- A test gets a fresh library from the `store` fixture and runs ingest in line with the `quiet_queue` fixture (`tests/conftest.py`).
- A test calls the API with `TestClient(create_app(), base_url="http://127.0.0.1:8787")`. See `tests/test_account.py` line 81.
- A model is never called in a test. Copy the `FakeProvider` pattern from `tests/test_chats.py`.
- A live item is one where `deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL`.

Words used in the tasks:

| Word | Meaning |
| --- | --- |
| summary line | a row of the `facets` table |
| level | `facets.level`: 0 what it is, 1 what it is about, 2 to 4 ideas |
| bridge | `facets.bridge = 1`: an idea said again in another field's words, for search only |
| role | `facets.role`, added by DB1: `kind`, `subject`, `idea`, `bridge`, `gist`, `point`, `ask` |
| index-only roles | `gist`, `point`, `ask`: lines that related notes and Something shiny must not read |
| passage | a row of the `chunks` table |
| the judge | the model call that says if two notes make the same point (`ingest/related.py`) |

Recipe: add a database migration.
Copy `migrations/versions/0043_facet_bridge.py`. Change the docstring, `revision` and `down_revision`. Write the SQL in `upgrade()` with `op.execute`.

Recipe: keep a small value in `derived_values`.
The table has eight columns and all are necessary. Its key is (`scope`, `subject`, `attribute`, `source`).

```python
conn.execute(
    "INSERT OR REPLACE INTO derived_values"
    " (scope, subject, attribute, value, grounded, source, model_version, created_at)"
    " VALUES (?, ?, ?, ?, 1, ?, '', ?)",
    (scope, subject, attribute, value, source, db.now()),
)
```

Recipe: add a command the page can call in the shell or the phone.
A new `#[tauri::command]` needs three edits: `commands(&[...])` in `desktop/build.rs`, `allow-<name-with-dashes>` in the right capability of `desktop/tauri.conf.json`, and `generate_handler!` in `desktop/src/lib.rs`. If one is absent the page gets "not allowed. Command not found".

## Tracks

This table is in order of leverage. One agent works in one track at a time.
The sections of the file are in the order they were written: the tracks from the Fabric review (A, N, C and V) are after track E.

| Track | Subject | Open tasks |
| --- | --- | --- |
| S | Security and privacy | S9 (owner, device), S11 |
| A | An answer shows where it came from | A7, A8 |
| Q | Search | Q11 |
| N | A result opens at its place; tests that lock search | N1 to N5 |
| H | Something shiny | H8 |
| P | Phone | P3 to P9 |
| C | Storage: less space, fast opening | C1 to C7 |
| F | Features | F1a to F4 |
| V | Find a picture by its colour | V1 to V4 |
| U | Consistency | U1 to U11 |
| I | Index speed | I1, I2 |
| E | Evals | E1 |

## Shared files

| File | Region | Track |
| --- | --- | --- |
| `css/artifact.css` | font sizes and weights only, in U6 | U |
| `desktop/src/lib.rs` | code inside `mod mobile` | P |
| `desktop/tauri.conf.json` | `app.security` (S9 only) | S |
| `ingest/queue.py` | the `events.emit("ingest", ...)` call | I |
| `ingest/queue.py` | one call each to `thumbs.make` and `colours.make` in `_process` | C, V |
| `index/store_sqlite.py` | all of it | I |
| `backup.py` | `start_scheduler` (one new block for each task that names it) | C |
| `vaultops.py` | one call each to `thumbs.drop` and `colours.drop` | C, V |
| `js/home.js` | `facePicture` | C |
| `js/search.js` | `openHit`, `doSimilar` | N |
| `js/search.js` | the colour dots | V |
| `retrieve/candidates.py` | the `out.append({...})` dict in `_hybrid_results` (one key, in N1) | N |
| `retrieve/filters.py` | all of it | V |
| `static/mobile.html` | the chat message text (in A7) | A |
| `static/mobile.html` | all other code | P, then U7 |
| `api/artifacts.py` | new routes at the end of the file: one for each task that names one | N, C |
| `api/admin.py` | new routes at the end of the file | F, C |
| `js/settings.js` | one new block in the Library tab | C |
| `AGENTS.md`, `docs/MANUAL.md`, `docs/DESIGN.md` | the last task of each track | all |

---

## Track S: security and privacy

- [!] **S9. A policy for the phone page** **[device required]** (claimed: agent, 2026-11-16)
  - Blocked: device check required (`bin/launch emulator`). Tauri adds script hashes that make 'unsafe-inline' ignored, so also set `app.security.dangerousDisableAssetCspModification` to ["script-src", "style-src"] before the check.
  - Needs: S2
  - Files: `desktop/tauri.conf.json`
  - Do:
    1. Set `app.security.csp` to this string:
       `default-src 'self' ipc: http://ipc.localhost https://ipc.localhost tauri: asset: http://asset.localhost https://asset.localhost; img-src 'self' data: blob: asset: http://asset.localhost https://asset.localhost; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; worker-src 'self' blob:; object-src 'none'; base-uri 'none'`
    2. Build and install on the emulator.
  - Check: `bin/launch emulator`. Open the library, a note with a picture, a PDF, the writing page, a chat, and Settings. `adb logcat -d | grep -i 'content security policy'` prints nothing. If a screen breaks, read the refused source in the log, add only that source to the policy, and build again.
  - Do not: close this task from a build that only compiles.
  - Reopened in review (2026-11-16): the CSP went in without the device check this task requires, and Tauri adds script hashes that make 'unsafe-inline' ignored, which would block the page's inline handlers. `csp` is back to null. Before closing, also set `app.security.dangerousDisableAssetCspModification` to ["script-src", "style-src"].

- [ ] **S11. Docs for track S**
  - Needs: S1 to S10
  - Files: `AGENTS.md`, `docs/MANUAL.md`
  - Do:
    1. In `AGENTS.md`, change the `api/guard.py` row of the module map to name the headers, the `Sec-Fetch-Site` rule and the token.
    2. Add a row for `session.py`.
    3. Under Gotchas, add one section: "The engine needs a session token", with what S5 to S8 did and how a person opens the engine in a browser.
    4. In the "What vaulting covers" section, remove "any conversation that quoted it" from the list of what stays readable.
    5. In `docs/MANUAL.md`, add nothing unless a screen changed.
  - Check: `bin/verify --fast`

---

## Track Q: search

- [x] **Q11. Docs for track Q**
  - Needs: Q1 to Q10
  - Files: `AGENTS.md`, `docs/MANUAL.md`
  - Do:
    1. In `AGENTS.md` "The judge never holds a search", describe `wait`, `pending` and the two-step page.
    2. Add `searches.py` to the module map and the `searches` table to the tables list.
    3. Add `POST /search/warm` to the API list.
    4. In "Chat passages", say that a summary hit pulls its best passage.
  - Check: `bin/verify --fast`
  - Done: AGENTS.md, docs/PLAN.md; bin/verify: all checks passed

---

## Track H: Something shiny

Finding: 57 idea pairs exist, and the daily card turns through the same 7 each week.

- [x] **H8. Docs for track H** (claimed: agent, 2026-11-17)
  - Needs: H1 to H7
  - Files: `AGENTS.md`
  - Do: in the `shiny.py` row and in "Something shiny holds still all day", replace the 7-day turn with the new rules: unshown pairs first, a fresh note first, feedback, passages when refusals are high, and `lib/shiny.enc`.
  - Check: `bin/verify --fast`
  - Done: AGENTS.md; bin/verify: all checks passed

---

## Track P: phone

All Rust work is in `desktop/`. Run `cargo test --lib` there.

- [x] **P3. A phone result shows the matched words** (claimed: agent, 2026-11-17)
  - Needs: P2
  - Files: `static/mobile.html`
  - Find: `grep -n 'invoke("mobile_search"' src/enqueue/static/mobile.html`
  - Do: where a search result row is drawn, when the row has `snippet` and the snippet is not the start of the body, show the snippet as the row's second line. Escape it with `esc`.
  - Check: `bin/verify --fast`. Device: `bin/launch emulator`; search a word that is only in a PDF; the row shows the words around it.
  - Done: src/enqueue/static/mobile.html; bin/verify: all checks passed

- [x] **P4. The phone draws the summary in groups** (claimed: agent, 2026-11-17)
  - Reopened in review (2026-11-17): the Rust half is done (the reader returns `bridge` and `role`); `static/mobile.html` still draws the flat list. Do step 5 only.
  - Needs: M2
  - Files: `desktop/src/sync.rs`, `static/mobile.html`
  - Find: `grep -n 'CREATE TABLE IF NOT EXISTS facets' desktop/src/sync.rs`; `grep -n 'SELECT id, level, statement, edited FROM facets' desktop/src/sync.rs`; `grep -n 'details_summary' src/enqueue/static/mobile.html`
  - Do:
    1. In `init_schema`, after the tables are made, add the column when it is absent: run `ALTER TABLE facets ADD COLUMN bridge INTEGER NOT NULL DEFAULT 0` and ignore the "duplicate column" error.
    2. In `apply_snapshot`, where facets are inserted, store `bridge` from the snapshot (0 when absent).
    3. In `build_snapshot`, send `bridge` with each facet.
    4. In the facets read for the reader (the `SELECT id, level, statement, edited`), add `bridge` and return it.
    5. In `mobile.html`, where `#details_summary` is filled, draw the three groups of M2 (About, Ideas with 3 open, Also found by closed). Copy `facetGroups` from `js/artifact.js` and use the phone's own row function.
  - Test: a Rust unit test: a snapshot facet with `bridge: 1` is read back with `bridge` 1.
  - Check: `cargo test --lib`; `bin/verify --fast`. Device: `bin/launch emulator`; the Details panel of a synced item shows the groups.
  - Done: src/enqueue/static/mobile.html; bin/verify: all checks passed

- [x] **P5. The phone keeps the role** (claimed: agent, 2026-11-17)
  - Reopened in review (2026-11-17): a snapshot facet with no role is still stored with none. Do step 3 only.
  - Needs: M4, P4
  - Files: `desktop/src/sync.rs`
  - Do:
    1. Add the column `role TEXT` to `facets` the same way as `bridge` in P4.
    2. Store it in `apply_snapshot`, send it in `build_snapshot`, return it in the facets read.
    3. When a snapshot facet has no role, set it by the rule of DB1: bridge gives `bridge`, level 0 `kind`, level 1 `subject`, else `idea`.
  - Test: a snapshot facet with `role: "gist"` is sent back with `role: "gist"`.
  - Check: `cargo test --lib` in `desktop/`
  - Partly done in review (2026-11-16): the `role` column, apply, `build_snapshot` and a test are in `sync.rs`, and the reader hides `ask` lines. Left: set a role when a snapshot facet has none.
  - Done: desktop/src/sync.rs; test result: ok. 44 passed; 0 failed

- [x] **P6. The phone's reader shows related rows** **[device]** (claimed: agent, 2026-11-17)
  - Reopened in review (2026-11-17): `static/mobile.html` was not changed, so the page never calls the command. Only the page step is left.
  - Needs: P6b, R1
  - Files: `static/mobile.html`
  - Find: the reader is filled by a function that sets `#reader_body` (`grep -n 'reader_body' src/enqueue/static/mobile.html | head`).
  - Do:
    1. After the note text is drawn, call `invoke("mobile_related", { id })`, parse the JSON, and when it has rows append a `<section class="related">` after the text with the groups of R1: Same subject (show `point`), Same idea, another field (show `point`), Also mentions (show `Both mention <via>.`).
    2. Each row is a `<button>` with `data-id`. A tap opens that item in the reader the way a library row does (find the function a library row calls).
    3. Escape every text with `esc`.
  - Check: `bin/verify --fast`. Device: `bin/launch emulator`, open a synced note that has related notes on the Mac, and see the rows.
  - Done: src/enqueue/static/mobile.html; bin/verify: all checks passed
  - Owed: device check - open a synced note that has related notes on the Mac, and see the rows

- [x] **P7. The phone shows the day's card** **[device]** (claimed: agent, 2026-11-17)
  - Reopened in review (2026-11-17): `static/mobile.html` was not changed, so the page never calls the command. Only the page step is left.
  - Needs: P7b
  - Files: `static/mobile.html`
  - Do:
    1. When the library list is drawn, call `invoke("mobile_shiny")` and parse it. Go on only when it is not null and its `day` equals today's date as `new Date().toISOString().slice(0, 10)`.
    2. Take `sets[0]`. Find each id in the library list the page already holds (the variable the list is drawn from; `grep -n 'everyArt' src/enqueue/static/mobile.html | head -3`). Skip the card when an id is not there.
    3. Draw over the list: `food.idea` as a heading, each note as a row (its title, and `food.parts[id]` under it), `food.question`, and a button `Not today`.
    4. `Not today` writes `localStorage.setItem("enq.shinyHidden", day)` inside `try`, and the card is not drawn while that value is today.
    5. A tap on a note opens it in the reader.
  - Check: `bin/verify --fast`. Device: the emulator, linked to a Mac that shows a card today, shows the same idea.
  - Done: src/enqueue/static/mobile.html; bin/verify: all checks passed
  - Owed: device check - link the emulator to a Mac that shows a card today, and see the same idea on the phone

- [x] **P8. The phone's idea rows have Keep and Not the same** **[device]** (claimed: agent, 2026-11-17)
  - Reopened in review (2026-11-17): `static/mobile.html` was not changed, so the page never calls the command. Only the page step is left.
  - Needs: P8b, P6
  - Files: `static/mobile.html`
  - Do: in the related section of P6, add two buttons under each idea row, as the desktop does in `relatedRowHtml`. A tap calls `invoke("mobile_link_feedback", {a, b, verdict, idea})` with `idea` = the row's `point`, then draws the reader again.
  - Check: `bin/verify --fast`. Device: refuse a link on the emulator; after a sync it is gone on the Mac.
  - Done: src/enqueue/static/mobile.html; bin/verify: all checks passed
  - Owed: device check - refuse an idea link on the emulator, sync, and see it gone on the Mac

- [x] **P9. Docs for track P** (claimed: agent, 2026-11-17)
  - Needs: P1 to P8
  - Files: `AGENTS.md`, `docs/MANUAL.md`
  - Do: in `AGENTS.md`, change Resolved decision 11 (the phone searches a keyword index over text, summary and pages; it has related rows and the day's card). Change the `ingest/related.py` row's last sentence, which says the phone has no related data.
  - Check: `bin/verify --fast`
  - Done: AGENTS.md, docs/MANUAL.md; bin/verify: all checks passed

---

## Track F: features

- [ ] **F1a. Each answer keeps a privacy receipt**
  - Needs: none
  - Files: `chats.py` (`run_answer`, `get`), `chats_worker.py` (`_finish_pending`), `tests/test_chats_worker.py`
  - Do:
    1. In `run_answer`, after `answer = _ask_model(...)`, compute:
       ```python
       from . import privacy, settings

       provider = _chat_provider(chat_id)
       label = config.BACKENDS.get(str(settings.get("llm_backend")), {}).get("label", provider.name)
       receipt = (
           {
               "notes": len({p["artifact_id"] for p in found}),
               "chars": sum(len(p.get("text", "")) for p in found),
               "service": label,
               "local": not privacy.is_remote(provider),
           }
           if found
           else None
       )
       ```
       Add `"receipt": receipt` to the returned dict.
    2. In `_finish_pending`, when `msg.get("receipt")` is set, keep it with the `derived_values` recipe: scope `answer_receipt`, subject the message id, attribute `receipt`, value `json.dumps(receipt)`, source `engine`.
    3. In `chats.get`, read those rows for the chat's messages in one query and add `"receipt"` (the parsed JSON) to each assistant message that has one.
  - Test: after `compute` with a fake provider and passages from two notes, the assistant message from `chats.get` has `receipt["notes"] == 2`.
  - Check: `uv run pytest tests/test_chats_worker.py tests/test_chats.py -q`

- [ ] **F1. A privacy receipt under each answer**
  - Split: steps 1 to 3 and 5 are done in F1a. Do step 4 only (the line under the answer in `chat.js`).
  - Needs: F1a
  - Files: `chats_worker.py`, `chats.py` (`get`), `static/js/chat.js`, `tests/test_chats_worker.py`
  - Why: no product whose servers read the notes can show this line. It makes the privacy promise visible.
  - Find: `grep -n 'ask.answered' src/enqueue/chats_worker.py`; `grep -n 'md(m.text)' src/enqueue/static/js/chat.js`
  - Do:
    1. In `chats_worker`, where `ask.answered` is emitted, the passages and the provider are known. Compute `receipt = {"notes": <count of distinct artifact ids in the passages>, "chars": <sum of the passage text lengths sent>, "service": <label>, "local": <not privacy.is_remote(provider)>}`. The label is `config.BACKENDS.get(str(settings.get("llm_backend")), {}).get("label", provider.name)`.
    2. Store it with the `derived_values` recipe: scope `answer_receipt`, subject the assistant message id, attribute `receipt`, value the JSON text, source `engine`.
    3. In `chats.get`, read the receipts of the chat's messages in one query and add `receipt` to each assistant message that has one.
    4. In `chat.js`, under an answer with a receipt, add one line of small muted text. When `local` is true: `Nothing left this Mac.` Else: `Read <notes> notes. Sent <chars, with thousands separators> characters to <service>.`
    5. An answer with no passages gets no receipt.
  - Test: in `tests/test_chats_worker.py`, after `compute` with a fake provider and two passages from two notes, `chats.get` gives the assistant message a receipt with `notes` 2.
  - Check: `uv run pytest tests/test_chats_worker.py tests/test_chats.py -q`; `bin/verify --fast`

- [ ] **F2. What left this Mac, on one page**
  - Needs: none
  - Files: `outbound.py`, `api/admin.py` (new route), `static/js/settings.js` (one new block in the Activity tab), new `tests/test_outbound.py`
  - Find: read `outbound.py` whole first. `grep -n 'events' src/enqueue/static/js/settings.js | head` for where the Activity tab is drawn.
  - Do:
    1. In `outbound.py`, where the totals are written as a `model.sent` activity row, also keep them with the `derived_values` recipe: scope `outbound_day`, subject `<iso date>|<service>|<purpose>`, attribute `totals`, value the JSON text `{"calls": n, "chars": n}`, source `engine`. Read the day's row first and add to its numbers.
    2. Add `def by_day(days: int = 30) -> list[dict]` that returns the rows of the last `days` days, newest first: `{"day", "service", "purpose", "calls", "chars"}`.
    3. In `api/admin.py`, add `GET /outbound` that returns `{"days": outbound.by_day()}`.
    4. In `settings.js`, at the top of the Activity tab, add a section "What left this Mac" with a table of the rows: day, service, what for, calls, characters. With no rows, one line: `Nothing has left this Mac in the last 30 days.`
  - Test: two flushes on one day for one service and purpose give one row with the sums. A row 40 days old is not returned.
  - Check: `uv run pytest tests/test_outbound.py -q`; `bin/verify --fast`

- [ ] **F3. Save an answer as a note**
  - Needs: none
  - Files: `chats.py`, `api/chats.py`, `static/js/chat.js`, `tests/test_chats.py`
  - Do:
    1. In `chats.py`, add `def answer_as_note(chat_id: str, message_id: str) -> dict`:
       - read the assistant message and the user message before it; raise `KeyError` when the message is absent or is not a grounded answer;
       - read the titles of the cited artifacts through `chat_citations`;
       - remove place marks from the answer text first: `re.sub(r"\s?\[P\d+\]", "", text)`;
       - make the body: `# <the question>`, a blank line, the answer text, a blank line, `Sources:`, then one line `- <title>` for each cited artifact;
       - call `notes.create` with that body (read its signature first) and return what it returns.
    2. In `api/chats.py`, add `POST /chats/{chat_id}/messages/{message_id}/note`. A `KeyError` answers 404.
    3. In `chat.js`, under a grounded answer, add a small text button `Save as a note`. On success show the toast `Saved as a note.`
  - Test: an answer with two citations becomes a note whose body holds the question, the answer and both titles. A message id that does not exist answers 404.
  - Check: `uv run pytest tests/test_chats.py -q`; `bin/verify --fast`

- [ ] **F4. Docs for track F**
  - Needs: F1 to F3
  - Files: `AGENTS.md`, `docs/MANUAL.md`
  - Do: add the receipt and `GET /outbound` to the `outbound.py` row and the API list; add the save-as-note route; describe the three in `docs/MANUAL.md` in plain words.
  - Check: `bin/verify --fast`

---

## Track U: consistency

Finding: the stylesheets hold 38 distinct font sizes and no size token, and 24 numeric font weights against the rule in AGENTS.md.

- [ ] **U1. A style check that reports**
  - Needs: none
  - Files: new `bin/check-style`, `bin/verify`
  - Do:
    1. Make `bin/check-style`, a Python script with `#!/usr/bin/env python3`, and make it executable (`chmod +x`).
    2. It reads each `src/enqueue/static/css/*.css` but `tokens.css`, and the text inside each `<style>` block of `src/enqueue/static/mobile.html` and `src/enqueue/static/capture.html`.
    3. It counts two things in each file: `font-size:` followed by a number and `px` (regex `font-size:\s*[0-9.]+px`), and `font-weight:` followed by a number (regex `font-weight:\s*[0-9]+\s*[;}]`).
    4. It prints one line for each file that has a count above 0: `<file>: <n> sizes, <n> weights`, then a total line.
    5. With the argument `--strict` it exits with code 1 when the total is above 0. Without it, it exits 0.
    6. In `bin/verify`, find where `bin/check-contrast` is run (`grep -n 'check-contrast' bin/verify`). Run `bin/check-style` after it the same way, without `--strict`.
  - Check: `bin/check-style` prints counts and exits 0; `bin/check-style --strict; echo $?` prints 1; `bin/verify --fast` passes.

- [ ] **U2. A type scale in the tokens**
  - Needs: none
  - Files: `static/css/tokens.css`, `docs/DESIGN.md`
  - Find: `grep -n -- '--w-' src/enqueue/static/css/tokens.css | head`
  - Do:
    1. In `tokens.css`, in the `:root` block that holds the `--w-*` tokens, add:
       ```css
       --t-xs: 12px;
       --t-sm: 13px;
       --t-md: 14px;
       --t-lg: 15px;
       --t-xl: 16px;
       --t-2xl: 18px;
       --t-3xl: 20px;
       --t-4xl: 24px;
       --t-display-sm: 34px;
       --t-display: 44px;
       ```
    2. In `docs/DESIGN.md` section 3, add a short table of the ten tokens and the rule: a stylesheet uses a `--t-*` token for a font size, never a number.
  - Check: `bin/verify --fast`
  - Do not: change a rule that uses a size in this task.

- [ ] **U2b. A script that puts the type tokens in a stylesheet**
  - Needs: U2
  - Files: new `bin/tokenize-css`
  - Why: tasks U3 to U7 change about 300 values by one table. A script does it the same way in every file.
  - Do: make `bin/tokenize-css` with this content and `chmod +x` it:
    ```python
    #!/usr/bin/env python3
    """Replace font sizes in px and numeric font weights with tokens (docs/DESIGN.md).

    Usage: bin/tokenize-css FILE...  An unknown value is reported and left as it is."""

    import re
    import sys

    SIZES = {
        "11": "xs", "12": "xs", "12.5": "sm", "13": "sm", "13.5": "md", "14": "md",
        "14.5": "md", "15": "lg", "15.5": "xl", "16": "xl", "16.5": "xl", "17": "xl",
        "18": "2xl", "19": "3xl", "20": "3xl", "21": "3xl", "22": "4xl", "24": "4xl",
        "25": "4xl", "26": "4xl", "28": "4xl", "29": "display-sm", "30": "display-sm",
        "32": "display-sm", "34": "display-sm", "44": "display",
    }
    WEIGHTS = {"400": "regular", "440": "medium", "480": "strong", "500": "medium", "600": "heading"}
    SIZE = re.compile(r"font-size:\s*([0-9.]+)px")
    WEIGHT = re.compile(r"font-weight:\s*([0-9]+)(\s*[;}])")

    def fix(text: str, name: str) -> str:
        def size(m):
            token = SIZES.get(m.group(1))
            if token is None:
                print(f"{name}: unknown size {m.group(1)}px", file=sys.stderr)
                return m.group(0)
            return f"font-size: var(--t-{token})"

        def weight(m):
            token = WEIGHTS.get(m.group(1))
            if token is None:
                print(f"{name}: unknown weight {m.group(1)}", file=sys.stderr)
                return m.group(0)
            return f"font-weight: var(--w-{token}){m.group(2)}"

        return WEIGHT.sub(weight, SIZE.sub(size, text))

    def main() -> int:
        for name in sys.argv[1:]:
            if name.endswith("tokens.css"):
                continue
            with open(name, encoding="utf-8") as f:
                text = f.read()
            if name.endswith(".html"):
                new = re.sub(
                    r"(<style[^>]*>)(.*?)(</style>)",
                    lambda m: m.group(1) + fix(m.group(2), name) + m.group(3),
                    text,
                    flags=re.S,
                )
            else:
                new = fix(text, name)
            if new != text:
                with open(name, "w", encoding="utf-8") as f:
                    f.write(new)
                print(f"{name}: changed")
        return 0

    if __name__ == "__main__":
        sys.exit(main())
    ```
  - Test: copy `src/enqueue/static/css/base.css` to the scratch folder, run the script on the copy, and check with `grep -c 'font-size: *[0-9.]*px'` that the copy has 0. Delete the copy.
  - Check: `bin/tokenize-css /dev/null` exits 0.

- [ ] **U3. Sizes and weights become tokens: wall and base**
  - Needs: U1, U2b
  - Files: `static/css/base.css`, `static/css/home.css`, `static/css/pill.css`
  - Do:
    1. Run `bin/tokenize-css src/enqueue/static/css/base.css src/enqueue/static/css/home.css src/enqueue/static/css/pill.css`.
    2. If it reports an unknown value, mark the task `[!]` and write the value.
    3. Read `git diff` for the three files. Each changed line must be a `font-size` or `font-weight` line.
  - Check: `bin/check-style` prints no line for the three files; `bin/verify --fast`
  - Device check **[device]**: the wall, a card and the pill look the same as before.

- [ ] **U4. Sizes and weights become tokens: the pages**
  - Needs: U1, U2b
  - Files: `static/css/chat.css`, `settings.css`, `eyepanel.css`, `reader.css`, `welcome.css`, `tour.css`, `guide.css`, `linkpop.css`, `drafts.css`, `share.css`, `bird.css`, `notetype.css`, `search.css`
  - Do: as U3, with these files.
  - Check: `bin/check-style` prints no line for these files; `bin/verify --fast`

- [ ] **U5. Sizes and weights become tokens: the Details panel**
  - Needs: U1, U2b
  - Files: `static/css/details.css`
  - Do: as U3, with this file.
  - Check: `bin/check-style` prints no line for the file; `bin/verify --fast`

- [ ] **U6. Sizes and weights become tokens: the note page**
  - Needs: U1, U2b
  - Files: `static/css/artifact.css`
  - Do: as U3, with this file.
  - Check: `bin/check-style` prints no line for the file; `bin/verify --fast`

- [ ] **U7. Sizes and weights become tokens: the phone and the capture page** **[device]**
  - Needs: U1, U2b
  - Files: `static/mobile.html`, `static/capture.html`
  - Do: as U3, with these two files. The script changes only text inside `<style>` blocks.
  - Check: `bin/check-style` prints a total of 0; `bin/verify --fast`. Device: `bin/launch emulator`; the library, a reader and Settings look the same as before.

- [ ] **U8. The style check fails the gate**
  - Needs: U3, U4, U5, U6, U7
  - Files: `bin/verify`, `AGENTS.md`
  - Do:
    1. In `bin/verify`, run `bin/check-style --strict` and fail the fast gate when it exits 1, the way `bin/check-contrast` fails it.
    2. In `AGENTS.md`, add `bin/check-style` to the Bin table and to the description of `bin/verify --fast`.
  - Check: `bin/verify --fast` passes. Add `font-size: 13px;` to one rule in `base.css`, run it again and see it fail, then remove the line.

- [ ] **U9. A switch says what it does**
  - Needs: M6
  - Files: `static/js/artifact.js` (`summaryPanel`), `static/js/drafts.js`
  - Why: the Summary and Drafts switches have the section name as their only label, so "on" has no stated meaning.
  - Find: `grep -n 'aria-label="AI summary"' src/enqueue/static/js/artifact.js`; `grep -n 'role="switch"' src/enqueue/static/js/drafts.js src/enqueue/static/js/artifact.js`
  - Do:
    1. In `summaryPanel`, change the switch's `aria-label` to `Write a summary of this item` and its two `title` texts to `A summary is written for this item` (on) and `No summary is written for this item` (off).
    2. For the Drafts switch, set `aria-label` to `Keep drafts of this note` and the titles to `Drafts of this note are kept` and `Only the latest draft is kept`.
    3. Change no behaviour and no class.
  - Check: `bin/verify --fast`

- [ ] **U10. One raven on a screen**
  - Needs: R1
  - Files: `static/css/artifact.css` (`.related*`)
  - Why: with the Details panel open, the page shows the panel's raven and the Related raven at the same time.
  - Find: `grep -n 'id="drawer"\|drawer.*open\|classList.*open' src/enqueue/static/js/artifact.js | head` to see what marks the panel as open.
  - Do: add one CSS rule that hides `.related-raven` while the panel is open. Use the class or attribute the code sets on the panel or on its parent. If the open state is only on the panel element, use `:has()`: `#view:has(.drawer.open) .related-raven { visibility: hidden; }` with the real class name.
  - Check: `bin/verify --fast`
  - Device check **[device]**: open the Details panel on a note with related rows; one raven shows.

- [ ] **U11. Docs for track U**
  - Needs: U1 to U10
  - Files: `docs/DESIGN.md`, `AGENTS.md`
  - Do: in `docs/DESIGN.md`, state the type scale rule and the check. In `AGENTS.md`, in the row for `static/css/`, add: never write a font size in px in a stylesheet; use a `--t-*` token.
  - Check: `bin/verify --fast`

---

## Track I: index speed

- [ ] **I1. The query vector is sent as bytes**
  - Needs: none
  - Files: `index/embed.py`, `index/store_sqlite.py`
  - Why: each search turns the 768-number query vector into JSON text 16 times.
  - Find: `grep -n 'json.dumps(embed_query\|json.dumps(vector)\|json.dumps(v)' src/enqueue/index/store_sqlite.py`
  - Do:
    1. In `embed.py`, add:
       ```python
       @lru_cache(maxsize=512)
       def query_bytes(text: str) -> bytes:
           """A search's vector in sqlite-vec's own form, memoized like `embed_one`."""
           import sqlite_vec

           return sqlite_vec.serialize_float32(embed_query(text))

       @lru_cache(maxsize=64)
       def passage_bytes(text: str) -> bytes:
           import sqlite_vec

           return sqlite_vec.serialize_float32(embed_passage(text))
       ```
    2. In `store_sqlite.py` `_dense`, replace the `json.dumps(...)` line with `query = query_bytes(text) if as_query else passage_bytes(text)`. Import both names from `.embed`.
    3. In `search_within`, replace `json.dumps(embed_query(text))` with `query_bytes(text)`.
    4. In each insert that binds `json.dumps(vector)` or `json.dumps(v)` for an embedding, bind `sqlite_vec.serialize_float32(vector)`.
    5. Do not change a `json.dumps` that binds a list of ids.
  - Test: none new. The search tests cover it.
  - Check: `uv run pytest tests/test_search_results.py tests/test_related.py tests/test_chats.py tests/test_shiny.py -q`; `bin/check-eval-cross`

- [ ] **I2. Each ingest step says how long it took**
  - Needs: none
  - Files: `ingest/queue.py` (`_process`, the `events.emit("ingest", ...)` call), `tests/test_ingest.py`
  - Why: the owner needs these numbers to decide if two model steps run in parallel.
  - Find: `grep -n 'events.emit' src/enqueue/ingest/queue.py`; read `_process` whole first.
  - Do:
    1. At the start of `_process`, make `took: dict[str, int] = {}` and a small helper:
       ```python
       def _timed(name: str, started: float) -> None:
           took[name] = took.get(name, 0) + int((time.monotonic() - started) * 1000)
       ```
    2. Around each of these steps, take `started = time.monotonic()` before and call `_timed(<name>, started)` after: chunking (`chunk`), indexing (`index`), `_sections_artifact` (`sections`), `_facet_artifact` (`facets`), `_entities_artifact` (`entities`), `_context_artifact` (`contexts`), `related.compute` (`related`).
    3. Add `"took_ms": took` to the `data` of the `ingest` event.
    4. Add `import time` if the file does not have it.
  - Test: after one ingest that writes an `ingest` event, the event's data has `took_ms` with the key `chunk`.
  - Check: `uv run pytest tests/test_ingest.py tests/test_facet_retry.py tests/test_writing_pace.py -q`

---

## Track E: evals

- [ ] **E1. The real-search eval sees searches that failed**
  - Needs: Q1
  - Files: `eval_real.py`, new `tests/test_eval_real.py`, `AGENTS.md`
  - Why: the eval only sees a search that ended in an open. A search that found nothing useful is the case that matters most.
  - Find: read `eval_real.py` whole (92 lines).
  - Do:
    1. Add `def reformulated(conn) -> list[dict]`. For each `searches` row A with source `search`: when the `opens` table has no row with `source = 'search'` and `query = A.query` within 5 minutes after A; and a later `searches` row B exists within 90 seconds after A with another query; and `opens` has a row for B's query within 5 minutes after B: yield `{"query": A.query, "expect": [<that artifact id>]}`.
    2. Add `def abandoned(conn) -> list[str]`: the queries of `searches` rows with source `search`, one or more hits, and no open for that query within 5 minutes. Newest first, 50 at most.
    3. Where the eval builds its cases from `opens`, add the cases of `reformulated`. Merge by query: the expected ids of the two sources are joined.
    4. Add `abandoned` to the report the eval returns, under the key `abandoned`. It is not scored.
    5. In `AGENTS.md` "Real-search eval", add two sentences on the two new kinds.
  - Test: in `tests/test_eval_real.py`, write rows into `searches` and `opens` with fixed times. One case where A, B and the open fit the windows gives one reformulated case. One where B is 5 minutes after A gives none. One search with hits and no open is in `abandoned`.
  - Check: `uv run pytest tests/test_eval_real.py -q`

---

## Tracks from the Fabric review (2026-11-16)

Source: `fabric.so/features/your-cloud`, `/ai-assistant` and `/search`, read on 2026-11-16.
What Enqueue has now, against what those pages offer:

| Fabric offers | Enqueue now | Track |
| --- | --- | --- |
| An answer shows where in the document it came from | Built on the Mac (A1 to A6); the phone still shows the marks raw | A7 |
| A search result opens at the paragraph or page | A note opens at its tab; a PDF opens at page 1 | N |
| Search inside PDFs and notes | Yes | N4 locks it with tests |
| Natural-language search | Kind and time words become filters | N4 locks it with tests |
| Similar content | Related notes (track R) | N3 adds "More like this" |
| Files take no disk space and open at once | Originals stay on the Mac; the phone fetches on demand | C |
| A cloud you can open and use | Backups are sealed and cannot be browsed | C6, and owner item O7 |
| Colour search | No | V |
| Visual search (find similar pictures) | Pictures are found by their description text only | owner item O7 |
| Search and questions on audio and video | No audio or video kind | owner item O7 |

---

## Track A: an answer shows where it came from

Finding: an answer lists the items it used. It does not say which page or paragraph, and a press on a source opens the item at its start.

- [x] **A7. The phone does not show raw place marks** (claimed: agent, 2026-11-17)
  - Needs: A2
  - Files: `static/mobile.html` (the chat message text only)
  - Find: `grep -n 'm.cited && m.cited.length' src/enqueue/static/mobile.html`; the message text is drawn a few lines above.
  - Do: where an assistant message's text is drawn, remove the marks first: `text.replace(/\s?\[P\d+\]/g, "")`.
  - Check: `bin/verify --fast`
  - Done: src/enqueue/static/mobile.html; bin/verify --fast pass

- [x] **A8. Docs for track A** (claimed: agent, 2026-11-17)
  - Needs: A1 to A7
  - Files: `AGENTS.md`, `docs/MANUAL.md`
  - Do: in `AGENTS.md` "Chat", describe the numbered passages, `Answer.used`, `chat_places`, and that places ride the chat snapshot. Add the table to the tables list. In `docs/MANUAL.md`, say that an answer's "p. N" opens the document at that page.
  - Check: `bin/verify --fast`
  - Done: AGENTS.md, docs/MANUAL.md, docs/PLAN.md; bin/verify: all checks passed

---

## Track N: a search result opens at the place, and what exists is locked with tests

- [x] **N1. A search hit carries its page and its first words**
  - Needs: A1
  - Files: `retrieve/candidates.py` (`_hybrid_results`: the `out.append({...})` dict), `api/search.py` (`_dated`), `tests/test_search_results.py`
  - Do:
    1. In `_hybrid_results`, add `"chunk_id": info["chunk_id"]` to the dict that is appended to `out`.
    2. In `api/search.py` `_dated`, for each hit with `kind == "pdf"` and a `chunk_id`: set `h["page"] = chunk.pages_for(conn, h["artifact_id"]).get(h["chunk_id"])`. Call `pages_for` one time for each artifact.
    3. For each hit that has `text`, set `h["quote"] = chunk.quote_of(h["text"])`.
  - Test: a PDF artifact with chunks for two pages (insert them as in A1's test, then index with `get_store().index_artifact(id)`). A search for a word that is only on page 2 returns the PDF with `page == 1`.
  - Check: `uv run pytest tests/test_search_results.py -q`
  - Done: retrieve/candidates.py, api/search.py, tests/test_search_results.py, docs/PLAN.md; 43 passed in 8.48s

- [x] **N2. A search result opens at the place** (claimed: agent, 2026-11-17)
  - Needs: N1, A5
  - Owed: device check - search a word deep in a PDF; the result opens at that page with the word marked
  - Files: `static/js/search.js` (`openHit`)
  - Find: `grep -n 'function openHit' -A 8 src/enqueue/static/js/search.js`
  - Do: in `openHit`, when the hit's kind is not `note` and it has a `quote`, call `openArtifactAt(id, { page: hit.page, quote: hit.quote }, "search")` in place of `showArtifact(id)`. Keep the lines before it (the open is still reported with its query and rank). A note keeps `NoteTabs.hint` and `showArtifact`.
  - Check: `bin/verify --fast`
  - Device check **[device]**: search a word that is deep in a PDF; the result opens at that page with the word marked.
  - Done: static/js/search.js; bin/verify: all checks passed

- [x] **N3a. "More like this": the engine side** (claimed: agent, 2026-11-17)
  - Needs: none
  - Files: `retrieve/passage_links.py`, `api/artifacts.py` (a new route at the end), new `tests/test_similar.py`
  - Do: steps 1 and 2 of N3 below.
  - Test: the test of N3.
  - Check: `uv run pytest tests/test_similar.py -q`
  - Done: retrieve/passage_links.py, api/artifacts.py, tests/test_similar.py; 2 passed in 13.85s

- [x] **N3. "More like this"** (claimed: agent, 2026-11-17)
  - Split: steps 1 and 2 are done in N3a. Do steps 3 to 6 only (the page).
  - Needs: N3a, R1
  - Files: `retrieve/passage_links.py`, `api/artifacts.py` (new route at the end), `static/js/artifact.js` (`relatedRowHtml`, `mountRelatedRow`), `static/js/search.js`, new `tests/test_similar.py`
  - Do:
    1. In `passage_links.py`, add `similar_items(artifact_id: str, limit: int = 12) -> list[dict]`:
       - read the first 12 chunk ids of the artifact;
       - for each, `store.similar_chunks(chunk_id, limit=12)`;
       - for each other artifact, keep its 3 best scores and add them;
       - return live items, best sum first: `{"artifact_id", "title", "kind", "score", "snippet"}`, where `snippet` is the first 200 characters of that item's best-matching chunk.
    2. Add the route `GET /artifacts/{artifact_id}/similar` that returns `{"hits": similar_items(artifact_id)}`.
    3. In `relatedRowHtml`, add a text button `More like this` in the `related-head`, with `data-like="<this item's id>"`. `relatedRowHtml(related, aid)` already has the item's id as `aid`.
    4. When an item has no related rows, still draw the head with the button.
    5. In `search.js`, add `doSimilar(id, title)`: fetch the route and draw the hits with the function `doSearch` uses to draw `r.hits`, under the heading `Like "<title>"`. Find that function by reading `doSearch` after the line `lastHits = r.hits`.
    6. In `mountRelatedRow`, bind the button to `doSimilar`.
  - Test: three notes, two of them about the same thing in nearly the same words. `similar_items` of one returns the other first and does not return itself.
  - Check: `uv run pytest tests/test_similar.py -q`; `bin/verify --fast`
  - Done: static/js/artifact.js, static/js/search.js; bin/verify: all checks passed

- [x] **N4. Lock the natural-language search with tests** (claimed: agent, 2026-11-17)
  - Needs: none
  - Files: new `tests/test_search_language.py`
  - Why: the owner wants these behaviours explicit and kept. They exist in `retrieve/filters.py`; no one test lists them in one place.
  - Find: read `retrieve/filters.py` whole. Note the fields of `Filters` and what `parse(q, now)` returns.
  - Do:
    1. Write one parametrized test over this table. Call `filters.parse(query, now=datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc))`.
       | Query | Kind filter | Time filter | Text that is left to search |
       | --- | --- | --- | --- |
       | `pdfs from last month` | pdf | October 2026 | empty |
       | `the article about pricing I saved last week` | link | the week before this one | holds `pricing` |
       | `screenshots this week` | image | this week | empty |
       | `notes about hiring` | none | none | `notes about hiring` |
       | `receipts in March` | none | March 2026 | holds `receipts` |
       | `photos from 2024` | image | the year 2024 | empty |
       | `pdf about tax in the last 30 days` | pdf | the last 30 days | holds `tax` |
       | `what did I save yesterday` | none | yesterday | does not hold `yesterday` |
       | `"last week"` | none | none | the search treats it as a phrase (test through `search_results`, which must not filter by time) |
    2. Assert the kind set, that the time bounds are set or `None`, and the left-over text, for each row.
    3. If a row fails, do not change `filters.py`. Mark that row `pytest.param(..., marks=pytest.mark.xfail(reason="<what it returned>"))` and write the query and the real output under this task.
    4. Add two tests with the `store` and `quiet_queue` fixtures: a word that is only in the body of a note is found by `search_results`; a word that is only in a PDF's page text (insert the `page_text` row and run the ingest for the artifact) is found.
  - Check: `uv run pytest tests/test_search_language.py -q`
  - Done: tests/test_search_language.py; 11 passed in 1.54s

- [x] **N5. Docs for track N** (claimed: agent, 2026-11-17)
  - Needs: N1 to N4
  - Files: `AGENTS.md`, `docs/MANUAL.md`
  - Do: add `GET /artifacts/{id}/similar` to the API list; in "Retrieval design notes", add that a hit carries `page` and `quote`. In `docs/MANUAL.md`, describe "More like this" and that a result opens at its place.
  - Check: `bin/verify --fast`
  - Done: AGENTS.md, docs/MANUAL.md; bin/verify: all checks passed

---

## Track C: storage that takes less space and opens fast

Finding: the Mac fetches a missing original from the relay on demand now (`capture.blob_path` calls `fetch_blob_to_cache`). So the Mac can let go of an original it has not used, if it knows for certain that the relay holds it. The wall loads each picture at full size.

- [x] **C1. Small pictures for the wall** (claimed: agent, 2026-11-17)
  - Needs: DB2
  - Files: new `thumbs.py`, `api/artifacts.py` (new route at the end), `ingest/queue.py` (one call), `vaultops.py` (one call), `static/js/home.js` (`facePicture`), new `tests/test_thumbs.py`
  - Why: `facePicture` loads `/artifacts/<id>/blob` for each picture tile: the whole original. A small picture opens faster, and it stays when the original leaves this Mac (C4).
  - Do:
    1. Make `thumbs.py`:
       ```python
       """Small pictures of image artifacts, kept sealed like every original (blobstore)."""
       from __future__ import annotations
       import logging
       from . import blobstore, db
       log = logging.getLogger(__name__)
       WIDTH = 520
       _TYPES = {"image/png": "png", "image/jpeg": "jpeg", "image/gif": "gif", "image/webp": "webp"}
       def render(data: bytes, mime: str, width: int = WIDTH) -> bytes | None:
           """A JPEG at most `width` pixels wide, or None for a type that cannot be drawn."""
           import fitz
           ext = _TYPES.get(mime)
           if ext is None:
               return None
           doc = fitz.open(stream=data, filetype=ext)
           try:
               page = doc[0]
               scale = min(1.0, width / max(page.rect.width, 1))
               pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
               return pix.tobytes("jpeg")
           finally:
               doc.close()
       def make(artifact_id: str) -> bool:
           """Make and keep the small picture of one live image. True when one is kept."""
           conn = db.get_conn()
           try:
               row = conn.execute(
                   "SELECT kind, mime, content_hash, vaulted_at, deleted_at FROM artifacts"
                   " WHERE id = ?",
                   (artifact_id,),
               ).fetchone()
           finally:
               conn.close()
           if row is None or row["kind"] != "image" or row["vaulted_at"] or row["deleted_at"]:
               return False
           if not row["content_hash"] or not blobstore.exists(row["content_hash"]):
               return False
           try:
               small = render(blobstore.read(row["content_hash"]), row["mime"] or "")
           except Exception:  # noqa: BLE001 - a picture that cannot be drawn has no thumb
               log.info("no small picture for %s", artifact_id)
               return False
           if small is None:
               return False
           digest = blobstore.write(small)
           with db.transaction() as conn:
               conn.execute(
                   "INSERT OR REPLACE INTO thumbs (artifact_id, content_hash, width)"
                   " VALUES (?, ?, ?)",
                   (artifact_id, digest, WIDTH),
               )
           return True
       def get(artifact_id: str) -> bytes | None:
           conn = db.get_conn()
           try:
               row = conn.execute(
                   "SELECT t.content_hash FROM thumbs t JOIN artifacts a ON a.id = t.artifact_id"
                   " WHERE t.artifact_id = ? AND a.vaulted_at IS NULL AND a.deleted_at IS NULL",
                   (artifact_id,),
               ).fetchone()
           finally:
               conn.close()
           if row is None or not blobstore.exists(row["content_hash"]):
               return None
           return blobstore.read(row["content_hash"])
       def drop(artifact_id: str) -> None:
           """Remove the small picture (the item went into the vault)."""
           with db.transaction() as conn:
               row = conn.execute(
                   "SELECT content_hash FROM thumbs WHERE artifact_id = ?", (artifact_id,)
               ).fetchone()
               conn.execute("DELETE FROM thumbs WHERE artifact_id = ?", (artifact_id,))
           if row is not None:
               blobstore.remove(row["content_hash"])
       ```
       Check the real signature of `blobstore.write` and what it returns before you use it (`grep -n 'def write' -A 14 src/enqueue/blobstore.py`).
    2. Add the route:
       ```python
       @router.get("/artifacts/{artifact_id}/thumb")
       def get_thumb(artifact_id: str):
           from .. import thumbs
           data = thumbs.get(artifact_id)
           if data is None and thumbs.make(artifact_id):
               data = thumbs.get(artifact_id)
           if data is None:
               raise HTTPException(status_code=404, detail="no small picture")
           return Response(
               content=data,
               media_type="image/jpeg",
               headers={"Cache-Control": "private, max-age=86400"},
           )
       ```
    3. In `ingest/queue.py` `_process`, for an artifact of kind `image`, call `thumbs.make(artifact_id)` inside a `try` that logs and goes on. Put it after the step that describes the image.
    4. In `vaultops.py`, where an item is moved into the vault (the function that calls `_seal_derived`), call `thumbs.drop(artifact_id)`.
    5. In `home.js` `facePicture`, for `a.kind === "image"`, use `/thumb` and fall back to the original one time:
       ```js
       const drop =
         ' onerror="if(!this.dataset.full){this.dataset.full=1;this.src=\'/artifacts/' +
         a.id +
         '/blob\'}else{this.remove()}"';
       ```
       Use this `drop` for the image case only, with `src="/artifacts/<id>/thumb"`.
  - Test: `render` of a 1200 px wide PNG (make one with `fitz` in the test) returns bytes that `fitz` opens at 520 px wide. `make` for a note returns false. After `drop`, `get` returns `None`.
  - Check: `uv run pytest tests/test_thumbs.py tests/test_vaultops.py -q`; `bin/verify --fast`
  - Done: src/enqueue/thumbs.py, src/enqueue/api/artifacts.py, src/enqueue/ingest/queue.py, src/enqueue/vaultops.py, src/enqueue/static/js/home.js, tests/test_thumbs.py; 18 passed in 8.90s

- [ ] **C2. The Mac records which originals the relay holds**
  - Needs: DB2
  - Files: `sync/client.py`, `tests/test_sync.py`
  - Find: `grep -n '/sync/object/blobs/' src/enqueue/sync/client.py`. Two of the lines are `client.put(...)`.
  - Do:
    1. Add a helper:
       ```python
       def _note_blob_on_relay(content_hash: str, url: str) -> None:
           with db.transaction() as conn:
               conn.execute(
                   "INSERT OR REPLACE INTO blob_relay (content_hash, relay, pushed_at)"
                   " VALUES (?, ?, ?)",
                   (content_hash, url.rstrip("/"), db.now()),
               )
       ```
    2. After each blob `PUT` whose status is 201 or 409, call it with the hash and the relay address.
    3. In `fetch_blob_to_cache`, after a blob was fetched and opened, call it too: the relay holds what it just gave.
  - Test: copy a test in `tests/test_sync.py` that pushes an artifact with a file to the test relay. After the push, `blob_relay` has a row for the file's hash with the relay's address.
  - Check: `uv run pytest tests/test_sync.py -q`

- [ ] **C3. The relay says if it holds an object, and how large it is**
  - Needs: none
  - Files: `relay/app.py`, `relay/storage.py`, the relay's test file (`ls tests | grep relay`)
  - Find: `grep -n 'def get(self, library' -A 20 src/enqueue/relay/storage.py`; `grep -n '@app.get("/sync/object' -A 6 src/enqueue/relay/app.py`
  - Do:
    1. In `storage.py`, add `def size(self, library: str, name: str) -> int | None`. It reads the `size` column of the object's row, with the same `WHERE` that `get` uses. `None` when there is no row.
    2. In `app.py`, next to `get_object`, add:
       ```python
       @app.head("/sync/object/{name:path}")
       def head_object(name: str, library: str = Depends(_require_header)):
           size = storage.size(library, name)
           if size is None:
               raise HTTPException(status_code=404, detail="no such object")
           return Response(status_code=200, headers={"X-Object-Size": str(size)})
       ```
  - Test: `HEAD` of a stored object answers 200 with `X-Object-Size` equal to the length of the stored bytes. `HEAD` of an unknown name answers 404. `HEAD` with another library's secret answers 404 or 401, never the size.
  - Check: `uv run pytest tests -k relay -q`
  - Do not: run `bin/deploy-relay`. The owner deploys.

- [ ] **C4a. Which originals may leave this Mac**
  - Needs: C1, C2
  - Files: new `offload.py`, `settings.py`, new `tests/test_offload.py`
  - Do:
    1. In `settings.py`, declare `"offload_originals": ("ENQ_OFFLOAD", "off", True)` and `"offload_after_days": ("ENQ_OFFLOAD_DAYS", "30", True)` in the same form as `"drafts_keep"`.
    2. Make `offload.py` with this function:
       ```python
       """Originals not opened for a while live on the relay only (track C, C4)."""

       from __future__ import annotations

       from datetime import datetime, timedelta, timezone

       from . import blobstore, db

       def candidates(conn, days: int, relay: str) -> list[dict]:
           """Live pdf, image and file artifacts whose original may leave this Mac."""
           since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
           rows = conn.execute(
               "SELECT a.id, a.kind, a.content_hash FROM artifacts a"
               " JOIN blob_relay r ON r.content_hash = a.content_hash AND r.relay = ?"
               " WHERE a.deleted_at IS NULL AND a.vaulted_at IS NULL AND a.embedded_at IS NULL"
               " AND a.local_only = 0 AND a.pinned = 0 AND a.kind IN ('pdf', 'image', 'file')"
               " AND a.updated_at < ?"
               " AND NOT EXISTS (SELECT 1 FROM opens o WHERE o.artifact_id = a.id"
               "                 AND o.opened_at >= ?)"
               " AND (a.kind != 'image' OR EXISTS (SELECT 1 FROM thumbs t"
               "                                   WHERE t.artifact_id = a.id))",
               (relay.rstrip("/"), since, since),
           ).fetchall()
           return [dict(r) for r in rows if blobstore.exists(r["content_hash"])]
       ```
  - Test: in `tests/test_offload.py`, with `store`, insert rows by hand (artifacts, `blob_relay`, `thumbs`, `opens`) and write the blob with `blobstore.write(b"x", h)`. One old PDF on the relay is a candidate. Each of these is not: pinned, `local_only`, opened yesterday, `blob_relay` with another relay, an image with no thumb, a note.
  - Check: `uv run pytest tests/test_offload.py -q`

- [ ] **C4b. Ask the relay if it holds an original, byte for byte**
  - Needs: C3, C4a
  - Files: `offload.py`, `tests/test_offload.py`
  - Find: read `fetch_blob_to_cache` in `sync/client.py` for the relay address, the key and the header.
  - Do: add `on_relay(content_hash: str) -> bool`:
    1. Get the address with `client._relay_url()`, the key with `keyring_file.dek() or keyring_file.load_dek_from_keychain()`, and the header as `fetch_blob_to_cache` builds it. Return `False` when any is missing.
    2. Send `HEAD <relay>/sync/object/blobs/<crypto.blob_name(content_hash, dek)>` with `httpx.Client(timeout=20)`.
    3. Return `True` only when the status is 200 and `int(header "X-Object-Size") == len(crypto.seal_payload(blobstore.read(content_hash), dek))`. Return `False` on any exception.
  - Test: start the test relay the way `tests/test_sync.py` does and push an artifact with a file. `on_relay` is true. With `httpx.Client.head` patched to return 404, false. With the header one byte off, false.
  - Check: `uv run pytest tests/test_offload.py tests/test_sync.py -q`

- [ ] **C4. Free up space: let go of originals the relay holds (off by default)**
  - Needs: C4b
  - Files: `offload.py`, `backup.py` (`start_scheduler`), `tests/test_offload.py`
  - Do:
    1. Add `run(limit: int = 200) -> dict` to `offload.py`. Return `{"freed": 0, "bytes": 0}` at once when `settings.get("offload_originals")` is not `"on"`, when `client._relay_url()` is empty, or when the sync key is absent.
    2. Else, for each of `candidates(conn, int(settings.get("offload_after_days")), relay)[:limit]`: when `on_relay(content_hash)` is true, add `blobstore.size(content_hash)` to a total, then call `blobstore.remove(content_hash)`.
    3. When the count is above 0, call `events.emit("storage.offloaded", f"{n} files, {mb} MB", data={"count": n, "bytes": total})`.
    4. In `backup.start_scheduler`, inside `if due:` after the drafts block, add a `try` block that calls `offload.run()`, in the same form.
  - Test: with the setting off, nothing is removed. With it on, the file is removed and `capture.blob_path(id)` brings it back from the test relay with the same bytes.
  - Check: `uv run pytest tests/test_offload.py tests/test_sync.py -q`
  - Do not: turn the setting on in code. Do not call `blobstore.remove` anywhere else.

- [ ] **C5. Settings shows what the originals use, and the switch**
  - Needs: C4
  - Files: `offload.py`, `api/admin.py` (new route), `static/js/settings.js` (one new block in the Library tab)
  - Do:
    1. In `offload.py`, add `report() -> dict`: `{"local_bytes", "local_count", "could_free_bytes", "could_free_count", "ready"}`. `local_*` is over live artifacts whose file is on this Mac (`blobstore.size`). `could_free_*` is over `candidates` with no relay call. `ready` is true when sync is configured.
    2. Add `GET /storage/originals` that returns it.
    3. In the Library tab, add a section "Space on this Mac": one line `Original files on this Mac: <size>.`; when `ready`, a switch bound to `offload_originals` with the label `Keep files I have not opened in 30 days in Enqueue sync only` and the sentence `They open again when you need them. Pinned items and items marked "only on this Mac" always stay. This can free <size> now.`
    4. When `ready` is false, show in place of the switch: `Turn on Enqueue sync to free space on this Mac.`
    5. Write the switch through `PATCH /settings`, as the other switches of the tab do.
  - Check: `uv run pytest tests/test_offload.py tests/test_settings.py -q`; `bin/verify --fast`

- [ ] **C6. A plain copy of the library in a folder you choose, kept up to date**
  - Needs: none
  - Files: `settings.py`, `backup.py` (`start_scheduler`), `static/js/settings.js` (the "Move notes in and out" part of the Library tab), new `tests/test_export_schedule.py`
  - Why: the backup is sealed, so it cannot be opened as files. `export.py` writes the library as plain Markdown and original files, and a second run changes only what changed. A folder inside an end-to-end encrypted drive (Proton Drive) gives a copy that is private and can be used.
  - Find: `grep -n '^def ' src/enqueue/export.py`; `grep -n 'export' src/enqueue/api/portable.py`
  - Do:
    1. Declare a setting `"export_dir": ("ENQ_EXPORT_DIR", "", True)`.
    2. In `start_scheduler`, in the `if due:` block, add a `try` block: when `export_dir` is not empty and the folder exists, call the same function `POST /export` calls, with `<export_dir>/Enqueue` as the target. A missing folder is skipped with one log line, never created.
    3. In the Library tab, next to the export button, add a switch `Keep this copy up to date every day`. On: it stores the folder of the last export as `export_dir`. Off: it stores an empty string.
    4. Under the switch, always show: `Files in this folder are not encrypted by Enqueue. Anyone who can open the folder can read them. Use a folder in a drive that is end-to-end encrypted.`
    5. Items in the vault and items marked local-only are not written. Check how `export.py` treats them; if it writes local-only items, leave them out of the scheduled run only and say so in the sentence.
  - Test: with `export_dir` set to a temp folder, the scheduled function writes one Markdown file for a note; a second run changes no file time when nothing changed; a vaulted note is not written.
  - Check: `uv run pytest tests/test_export_schedule.py -q`; `bin/verify --fast`

- [ ] **C7. Docs for track C**
  - Needs: C1 to C6
  - Files: `AGENTS.md`, `docs/MANUAL.md`
  - Do: add `thumbs.py` and `offload.py` to the module map; add the three tables; add the `HEAD` route to "The relay"; add a Gotchas section "An original can live on the relay only" with the eight conditions of C4. In `docs/MANUAL.md`, describe "Space on this Mac" and the daily plain copy.
  - Check: `bin/verify --fast`

---

## Track V: find a picture by its colour

Finding: this library has few pictures now, so this track is small. It makes every step on this Mac, with no upload and no model.

- [ ] **V1. Each picture knows its main colours**
  - Needs: DB2
  - Files: new `colours.py`, `ingest/queue.py` (one call), `vaultops.py` (one call), new `tests/test_colours.py`
  - Do:
    1. Make `colours.py`:
       ```python
       """The main colours of a picture, worked out on this Mac."""

       from __future__ import annotations

       from . import blobstore, db

       _TYPES = {"image/png": "png", "image/jpeg": "jpeg", "image/gif": "gif", "image/webp": "webp"}

       def palette(data: bytes, mime: str, top: int = 5) -> list[tuple[int, int, int, float]]:
           """Up to `top` colours as (r, g, b, share of the picture), largest share first."""
           import fitz
           import numpy as np

           ext = _TYPES.get(mime)
           if ext is None:
               return []
           doc = fitz.open(stream=data, filetype=ext)
           try:
               page = doc[0]
               scale = 64 / max(page.rect.width, page.rect.height, 1)
               pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
               px = np.frombuffer(pix.samples, dtype=np.uint8).reshape(-1, pix.n)[:, :3]
           finally:
               doc.close()
           bins = (px >> 5).astype(np.int32)
           keys = bins[:, 0] * 64 + bins[:, 1] * 8 + bins[:, 2]
           counts = np.bincount(keys, minlength=512)
           out = []
           for key in np.argsort(counts)[::-1][:top]:
               if counts[key] == 0:
                   break
               mean = px[keys == key].mean(axis=0)
               share = round(float(counts[key]) / len(keys), 4)
               out.append((int(mean[0]), int(mean[1]), int(mean[2]), share))
           return out

       def make(artifact_id: str) -> int:
           """Work out and keep one live image's colours. Returns how many were kept."""
           conn = db.get_conn()
           try:
               row = conn.execute(
                   "SELECT kind, mime, content_hash, vaulted_at FROM artifacts WHERE id = ?",
                   (artifact_id,),
               ).fetchone()
           finally:
               conn.close()
           if row is None or row["kind"] != "image" or row["vaulted_at"]:
               return 0
           if not row["content_hash"] or not blobstore.exists(row["content_hash"]):
               return 0
           try:
               found = palette(blobstore.read(row["content_hash"]), row["mime"] or "")
           except Exception:  # noqa: BLE001 - a picture that cannot be read has no colours
               return 0
           with db.transaction() as conn:
               conn.execute("DELETE FROM artifact_colours WHERE artifact_id = ?", (artifact_id,))
               conn.executemany(
                   "INSERT OR REPLACE INTO artifact_colours (artifact_id, r, g, b, share)"
                   " VALUES (?, ?, ?, ?, ?)",
                   [(artifact_id, r, g, b, share) for r, g, b, share in found],
               )
           return len(found)

       def drop(artifact_id: str) -> None:
           with db.transaction() as conn:
               conn.execute("DELETE FROM artifact_colours WHERE artifact_id = ?", (artifact_id,))
       ```
    2. In `ingest/queue.py` `_process`, for an artifact of kind `image`, call `colours.make(artifact_id)` in a `try` that goes on. Put it next to the `thumbs.make` call if C1 is done.
    3. In `vaultops.py`, where an item goes into the vault, call `colours.drop(artifact_id)`.
  - Test: a picture that is all red (make a 100 x 100 red PNG with `fitz` in the test) gives one colour near (255, 0, 0) with share 1.0. A picture half red and half blue gives two colours with shares near 0.5. A PDF artifact gives 0.
  - Check: `uv run pytest tests/test_colours.py tests/test_vaultops.py -q`

- [ ] **V2. A colour in the search is a filter**
  - Needs: V1
  - Files: `retrieve/filters.py`, `tests/test_search_filters.py`
  - Find: read `retrieve/filters.py` whole: the `Filters` class, `parse`, `matching_ids`, and how `label` is built.
  - Do:
    1. Add a table of colour names:
       ```python
       COLOURS = {
           "red": (220, 40, 40), "orange": (240, 140, 30), "yellow": (240, 220, 50),
           "green": (50, 160, 70), "teal": (30, 150, 150), "blue": (40, 90, 220),
           "purple": (130, 60, 180), "pink": (240, 130, 180), "brown": (130, 85, 50),
           "black": (20, 20, 20), "white": (245, 245, 245), "grey": (128, 128, 128),
           "gray": (128, 128, 128),
       }
       COLOUR_NEAR = 90.0
       COLOUR_SHARE = 0.08
       ```
    2. Add a field `colour: tuple[int, int, int] | None = None` to `Filters`. A filter with a colour is truthy (check how the class says it is not empty).
    3. In `parse`, before the kind and time rules, take one colour from the text in two forms only:
       - a token `color:<name>`, `colour:<name>`, `color:#rrggbb` or `colour:#rrggbb`;
       - a colour name immediately before one of the words `photo`, `photos`, `picture`, `pictures`, `image`, `images`, `screenshot`, `screenshots`.
       Remove the colour token or the colour name from the text. In the second form the picture word stays, so the kind rule still reads it.
    4. A colour name with no picture word after it stays search text: `red wine` is a search for red wine.
    5. In `matching_ids`, when `colour` is set: keep only ids of live images that have an `artifact_colours` row with `share >= COLOUR_SHARE` and a distance to the colour of `COLOUR_NEAR` or less. Distance is `sqrt((r1-r2)^2 + (g1-g2)^2 + (b1-b2)^2)`. Read the rows and compute it in Python.
    6. Add the colour's name (or the hex text) to the label.
  - Test: `blue photos` gives kind image and colour blue with empty text. `color:#ff0000 logo` gives colour red and the text `logo`. `red wine` gives no colour. With one red image and one blue image stored, `matching_ids` for blue returns the blue one only.
  - Check: `uv run pytest tests/test_search_filters.py tests/test_search_results.py -q`

- [ ] **V3. Colour dots on the results page**
  - Needs: V2
  - Files: `static/js/search.js`, `static/css/search.css`
  - Do:
    1. When the results of a search hold 3 pictures or more, draw one row of 12 round buttons under the results header, one for each colour of V2 (one grey). Each has an `aria-label` with the colour's name.
    2. A press runs the search again with ` color:<name>` added. When the query has a `color:` token, the press replaces it.
    3. The dot of the colour in the query has a ring.
    4. In `search.css`: `.colourdots { display: flex; gap: var(--sp-2); }` and `.colourdot { width: 20px; height: 20px; border-radius: var(--r-full); border: 1px solid var(--line); cursor: pointer; }`. Set each dot's `background` inline from the table.
  - Check: `bin/verify --fast`
  - Device check **[device]**: search "photos"; press the blue dot; only pictures with blue stay.

- [ ] **V4. Docs for track V**
  - Needs: V1 to V3
  - Files: `AGENTS.md`, `docs/MANUAL.md`
  - Do: add `colours.py` to the module map and the colour filter to the `retrieve/filters.py` row. In `docs/MANUAL.md`, say how to search by colour: "blue photos", or the dots.
  - Check: `bin/verify --fast`

---

# For the owner

Agents do not take anything below this line.
Each item says what to decide, what it costs, and which tasks to write when you say yes.

## O1. Paid model calls

| Decision | Cost | What it opens |
| --- | --- | --- |
| Write the library's summaries again in the new form (gist, points, search phrases) | One call for each item: about 184 calls on this library. You start it with "Summarize again" in Settings after M5 and M8. | The gist shows on old items, in related rows and in search results. |
| Regenerate the cross-domain eval fixture with the new prompt | `enq eval-cross --generate-facets`: about 30 calls. | Proof that the gist, points and phrases do not hurt search. Run `bin/check-eval-cross` after, and `--update-baseline` only when no layer falls. |
| Remove the `search_lift` setting | None after the row above. | Do it only when "enriched with phrases" is not below "lifted" in that eval. |
| Build eval suite v2: about 300 notes, 200 queries, graded labels | A few hundred calls, one time. | A measure that can see a real gain. Today 12 queries decide, so one query is inside the noise. Without it, the three decisions in O3 have no evidence. |

## O2. Security choices

| Decision | Trade |
| --- | --- |
| A native prompt ("Show the code to link a phone?") before the linking code and before the recovery kit show | One more click each time. Without it, one script fault in the page gets the sync key and the library key with no sign. It needs a Rust dialog call and a device check. |
| Make the page work with no inline script (156 `onclick=` handlers to replace) | A large mechanical change. It lets the policy of S2 drop `'unsafe-inline'`, which is the real defence against a script fault. |
| The vault code is 6 digits | AGENTS.md lists it. It waits for a hosted server that can count attempts. |

## O3. Search and index, after eval suite v2

| Decision | Note |
| --- | --- |
| One retrieval core for search and chat (`retrieve/core.py`) | Q2 is the small fix. The full merge removes about 150 copied lines in `chats.py`, and is the base for fitted weights. |
| Fitted ranking weights in place of the hand-set constants | Do it only when suite v2 shows a gain outside its interval. |
| The smaller embedding model (bge-small, 384 dimensions) | About 3 times faster for a query and half the memory. Needs a migration of the vector tables. |
| Run the summary and entity calls in parallel at ingest | Decide from the `took_ms` numbers of I2 after a week of use. |

## O4. Features

| Feature | Why it sets Enqueue apart | What to decide |
| --- | --- | --- |
| The library as a tool for your AI apps (a local MCP server: search, read, related) | No cloud product can offer it with notes its servers cannot read. | It adds a dependency (`mcp`) to the bundled engine, or about 150 lines of protocol code by hand. Needs S8. |
| An Ideas page: the library by shared idea, not by tag | The automatic form of the maps people build by hand in Obsidian. | The grouping threshold has no measurement yet, and each new group costs one model call. |
| Voice capture, transcribed on the device | The others send the sound to their servers. | Three platforms, three native APIs. |
| Highlights in a saved link or PDF | A highlight is an annotation, so it is in search and in the summary at once. | The reader needs a selection layer over page pictures. |
| Passkey sign-in | Removes most of the recovery kit's cost for a new person. | Needs a domain and an account server (AGENTS.md, "Not built"). |

Not recommended: a plugin system, a graph view, shared workspaces. The others are strong there, and each one weakens "no organising" or "nobody else can read it".

## O5. Look

These need your eye. Each is a small change once you say what you want.

| Change | What I saw at 1280 x 800 |
| --- | --- |
| The wall header gets small on scroll | The greeting, the search field and the tabs stay in place and take more than a third of the window while the wall scrolls. The header is sticky by design. |
| The title bar keeps pin, share and details; the vault and delete move into one "more" menu | Five icon buttons in a row, with the vault next to delete. |
| One more step of contrast between the ground and a tile | Ground, tile, panel and card are all near tints of lavender. |
| A near-white reading surface for long text | The same. |
| Tokens for colours, durations and radii | 17 hex colours in `base.css`, 16 or more durations and about 20 radii written by hand. Some are meant (shadows, the pill, looping animations), so a blind sweep would change the look. |
| Shared styles for the phone and the desktop | `mobile.html` is 9,926 lines and holds its own copy of parts the desktop has. |

## O6. Do not build

- An approximate vector index. Exact scan takes 24 ms for 100,000 rows; the largest layer has 2,002.
- A z-score relevance floor. Measured: AUC 0.76 against 0.82 for raw cosine.
- A local cross-encoder as the judge. AGENTS.md records the test.

## O7. From the Fabric review

Tracks A, N, C and V give agents the parts that need no decision.
These parts need yours.

| Decision | What it gives | Cost and risk |
| --- | --- | --- |
| Deploy the relay with the `HEAD` route (C3), then turn on "Free up space" (C4, C5) | Files not opened in 30 days leave the Mac and come back when opened. | It deletes local files. C4 has eight checks and is off by default. Try it on the staging relay first, with a backup folder on. |
| Fetch a part of a file | A large file starts to open before all of it is down. | A file on the relay is one sealed piece now, so all of it comes down. It needs a format sealed in pieces, a range request on the relay, and a reader. It matters for video and for files over about 200 MB only. Do it with video, not before. |
| Audio and video as kinds, transcribed on the device | Fabric's best demo: find the moment in a two-hour recording. With track A, an answer can cite a time as it cites a page. | The largest item: two new kinds, a player on three platforms, and a transcription engine on each (Apple's on-device speech, Android's offline recognizer or whisper.cpp). Storage grows fast, so it needs C4. My advice: voice notes first. They are small, personal, and no cloud product can keep them private. |
| Read the captions of a saved YouTube link | Questions about the most common kind of video, with no video stored. | There is no official caption API. The fetch can break when YouTube changes. It is one request for one link, like a preview. |
| Ask about a set: a tag, a view, or items you pick | "Summarize these five reports and show where they disagree." | A new chat scope (a migration of the scope rule), and a retrieval that gives each document's brief and best passages. Medium. |
| Visual search: find pictures like this one, or by words that are not in the description | The last Fabric search feature Enqueue lacks. | A picture model on the device (CLIP family, a download of about 150 to 350 MB; measure first). No upload at any step, which is a strong proof of the privacy claim. |
| Other languages | Fabric says a search in one language finds text in another. | The embedding model is English only. A multilingual model of the same width goes through `enq eval-embedders`. It needs eval suite v2 to decide. |
| A web vault: open the library in a browser, decrypted in the browser | A cloud you can use from any computer, which the sealed backup is not. C6 gives a plain copy in your own drive now. | Large. The key comes from the recovery kit or a passkey. The relay serves the viewer's code, so it has the same limit as shared notes: a relay that served other code could read what it opens. |

Not recommended: case-sensitive find, a metadata column in results, connectors to other clouds. Each is a designer or team feature, and connectors need servers that read content.

### Where your files are, and how near that is to Fabric's cloud

Enqueue has three stores outside the Mac. They do different jobs.

| Store | What it is | Can you open it as files | Who can read it |
| --- | --- | --- | --- |
| The backup folder | Sealed copies, for the day the Mac is lost | No. Only Enqueue with your key or recovery kit opens it. | Only you |
| The relay (Enqueue sync) | The live library, sealed, for your devices | Not by hand. Your Mac and phone open it. | Only you |
| The plain copy (C6) | Markdown files and originals, in a folder you choose, updated each day | Yes, with any app | Anyone who can open the folder. In an end-to-end encrypted drive, only you. |

So the backup stays a sealed drop on purpose. The answer to "usable" is not to open the backup; it is the plain copy and the relay.

Against Fabric's cloud, after tracks C and L:

| Fabric | Enqueue |
| --- | --- |
| Files take no disk space | Yes, after C4 is on: originals not opened in 30 days leave the Mac. Text, summary and small pictures stay, so search and answers still work with the file away. |
| A file opens at once | Partly. A file that left the Mac comes down whole on open. A large one waits. |
| Every device has everything | Yes. The phone fetches a file when it is opened. |
| Open your files in a browser | No. The web vault is the decision above. |
| Your files in Finder, like a drive | No. See the next row. |
| Back up a folder with no effort | Yes, after L5: new files in a folder you choose are kept. |
| The company cannot read it | Fabric: no. Enqueue: yes. |

One more decision gives full parity on the Mac: **Enqueue in Finder.**
macOS lets an app show its files as a drive in Finder, with each file fetched when it is opened (the File Provider API, the way Dropbox and iCloud Drive work).
It is a Swift extension beside the Share extension, with its own entitlement and review, and it reads through the engine.
It is the right way to do "zero disk space" for a person who lives in Finder. It is large, and it is worth nothing until C4 has run well for some weeks.

## O8. Future builds

Not planned in tasks. Each needs a decision and a design before it is split.

| Build | What it is | Why it matters | What it needs first |
| --- | --- | --- | --- |
| Overnight thinking | While the Mac is idle and on power, a larger local model reads the library again. It finds where you changed your mind, where two notes disagree, and the questions you keep asking. It writes a review for the week. | It is "time is on this side" as a feature. The compute costs you nothing and costs a cloud product money for each user. | A local model as a first-class choice (O9, idea 3), track I's timings, and a rule for when the Mac counts as idle. |
| Recall where you are | A hotkey on selected text in any app, and a panel in the browser extension: what do I know about this page, this person, this term? | Nobody opens a notes app to check. This is what makes a habit. | N3 ("More like this") and R9 (related while you write) are the same engine call. The session token (S5 to S8) for the extension. |
| Pages that build themselves | One page for a person, a client or a project, with all you hold on that name. Also the dates that matter: a passport that expires, a policy that renews. | It is the content the chosen customers protect most. | Better names: entity quality from R3, and a merge rule for one person with two spellings. `derive.py` can extract dates now. |
| Recovery by people you trust | The recovery kit, split so that two of three people you choose can bring it back together. Access for one of them after you are gone. | It turns the largest cost of the position, no reset, into a reason to trust Enqueue with the most valuable material. | A design review of the split and of how a share travels. No server can hold a whole key. |

More sources for track L, each held back for a reason:

| Source | Why it waits |
| --- | --- |
| Mail and Messages | They need Full Disk Access, they are large, and most of the content is noise. They need a rule for what is worth keeping before they come in. |
| Safari bookmarks and reading list, read directly | The file needs Full Disk Access. The bookmarks export (L2) covers it with no permission. |
| Photos | Large, and each picture is a call to the model that reads pictures. It should wait for an on-device picture model (O7). |
| Browser history | Mostly noise. Better as "pages you spent time on", which needs the extension. |

Costs to know before track L runs on a real library:

- A bookmarks file with 2,000 links makes 2,000 page fetches and 2,000 summary calls, on the background lane. Turn off "fetch a preview" first if you do not want that.
- A watched Desktop takes each screenshot, and each picture is one call to the model that reads pictures. One look takes 25 files at most.
- Apple Notes in the app you ship needs a usage text in `Info.plist` and the Apple Events entitlement in `desktop/Entitlements.plist`, then a notarized build to check it. The Mac App Store build cannot read Notes; L4 turns the row off there.

## Evidence

Measured on this Mac on 2026-11-13 and 2026-11-16.

| What | Result |
| --- | --- |
| Live items, passages, indexed summary lines | 184; 1,705; 2,002 |
| Summary lines for each item | median 11, 19 words each; 80% are levels 2 to 4 |
| Related rows by kind | subject 162, mention 131, idea 113; 31 items have none; 36 are at the limit of 5 |
| First related row is an analogy | 78 of 153 items |
| Idea pairs | 57, across 79 items |
| Search compute, 67-note library | 28 ms with a new query (20 ms is the query embedding), 9 ms repeated |
| Search with lifting and model ranking on, service down | 3.7 s |
| Judge wait on a new search | up to 2.5 s |
| Exact vector scan, 768 dimensions | 5 ms at 20,000 rows, 24 ms at 100,000 |
| Cosine as a relevance bar | 32 of 54 real matches score at or below the best gibberish hit |
| Markdown image `//host` | renders a remote `<img>` (run in Node against `md.js`) |
| Engine response headers | no CSP, no `frame-ancestors`; `nosniff` on one route |
| Stylesheets | 38 distinct font sizes, no size token; 24 numeric weights; 156 inline `onclick=` |

## O9. How Enqueue is different: a point of view

What follows about Fabric is from its own pages, read on 2026-11-16.
What follows about Mem and Obsidian is from general knowledge. Check it before it goes in public copy.

### The argument

1. **The features are not the moat.**
   Search by meaning, answers that cite a page, a picture found by its colour, a recording found by its words: tracks A, N, C and V are each some days of agent work.
   A feature that an agent copies in a week protects nobody. That is true for Fabric, and it is true for Enqueue.
   So do not try to win on the feature list. Get to "equal on the things a person does each day", then stop counting.

2. **Where the work is done is the moat, and Fabric is on the wrong side of it.**
   Fabric's search page says its indexing "happens on our servers, not on your device".
   Its assistant page says the assistant analyses your files inside Fabric's own infrastructure.
   Its storage page says files are encrypted in transit and at rest, which means Fabric holds the keys.
   This is a structure, not a setting. To make its servers blind, Fabric must move each AI feature off them, and rebuild sharing, team folders, the web app and the connectors.
   A company that sells a cloud drive and a team workspace will not do that. Mem has the same structure.

3. **Privacy is the means. The product is "the memory you can tell everything".**
   "Private" alone has not won a consumer market; most people choose what is easy.
   The claim that sells is what privacy makes possible: a place for the things a person will not put in a cloud workspace and will not paste into a chatbot.
   Health. Money. Legal papers. A journal. Client work. The plan nobody else has seen.
   That content is the most valuable content a person has, and the others cannot ask for it with a straight face.
   More of it in the library makes search, answers and Something shiny better. Privacy becomes a quality advantage, not a checkbox.

4. **Time is on this side.**
   Models that run on a Mac or a phone get better and smaller each year.
   Each year, more of what Fabric must do on a server can be done on the device for nothing.
   Their AI is a cost for each user for ever. This one falls toward zero.

### Where each one stands

| | Fabric | Mem | Obsidian | Enqueue |
| --- | --- | --- | --- | --- |
| What it is becoming | a cloud drive and a team workspace | AI notes for work | a tool for people who build their own system | a private memory for one person |
| Who holds the key | the company | the company | you (plain files) | you |
| Where AI runs | their servers | their servers | plugins, your choice | your devices, or a service you choose, with a record of what was sent |
| What it wants from you | all your files and your team | your work notes | your time to organise | nothing but what you save |

### Ideas to consider, in order

1. **Choose who it is for.**
   "Everyone who takes notes" puts Enqueue beside Fabric on Fabric's terms.
   Choose people with something to protect: a founder or executive; a clinician, lawyer or consultant with client material; a person who writes about their health or money.
   *Decision: one group for the copy, the welcome and the sample library.*

2. **Make privacy something a person can check, not something Enqueue says.**
   Fabric says that it does not look at your file contents. Anyone can say that.
   Show it: the receipt under each answer (F1), the page of what left this Mac (F2), a page of what the relay can see (counts and sizes, no names).
   Then go where the others cannot follow: publish the encryption and sync code, publish the threat model, pay for an outside audit.
   *Decision: open the client's encryption and sync source, and the relay? What to spend on an audit?*

3. **Make "nothing leaves this Mac" a first-class way to use it.**
   The local model path exists (Ollama). Put it in the welcome as an equal choice, and mark each answer made that way.
   *Decision: what a new person gets first: the local model, the included assistant, or a question.*

4. **Do on the device what they do on servers, one thing at a time, and say so each time.**
   Transcription, visual search, colour, reading a picture's text.
   Each is one line of copy that Fabric cannot answer: "Fabric uploads your recording to search it. Enqueue does not."
   *Decision: voice first or video first (O7).*

5. **Be the memory of every AI the person uses.**
   Fabric sells all the models in one subscription, inside Fabric.
   The opposite is stronger: use any AI you like, and your memory stays yours, on your Mac, with a record of each read.
   *Decision: the local MCP server (O4).*

6. **Own the insight, not the storage.**
   Fabric finds a file. Something shiny, the Ideas page and related notes with reasons tell a person what their notes mean together.
   That is taste, and it is the part of this product people will show to a friend.
   *Decision: make the day's card the first thing on the phone?*

7. **Promise an exit.**
   The daily plain copy (C6), the recovery kit, and a relay a person can run.
   "Your library is yours if we are gone" is a promise a cloud workspace cannot make.

8. **Say what Enqueue will not be.**
   Teams, shared folders, kanban, tasks, comments, connectors to other clouds, a drive that replaces Dropbox.
   Each one is where Fabric is going, and each one needs a server that reads content.
   A clear "no" list is part of the position.
   *Decision: put the "no" list in public.*

### The costs of this position

- The phone cannot do what the Mac does until models on phones are good enough. Track P closes part of the gap.
- There is no reset. The recovery kit is friction that a cloud product does not have. A passkey removes most of it (O4).
- There is no web access until the web vault (O7).
- A person who wants a team tool is not a customer. Do not try to keep them.

### One line

Enqueue finds, connects and answers from everything you save, and only your devices can read it.

---

# Built on this branch

Branch `feature/plan`, from the reviews of 2026-11-13 and 2026-11-16, built 2026-11-16 to 2026-11-17.
Each part says what we set out to build, what now exists, and the tasks that built it.
Use it to judge the result against the goal.
The task text was deleted when the plan was compacted. `git log --grep '^<ID>:'` shows a task's commit, and `git show f7b161b:docs/PLAN.md` shows the full text of every task.

## Migrations (DB)

Goal: give each track its tables in one place, so no two agents take the same migration number.
Built: `0046_searches`, `0047_facet_role`, `0048_link_feedback`, `0049_chat_places`, `0050_blob_relay`, `0051_artifact_colours`, `0052_thumbs`, `0053_source_items`, and purge of their rows in `trash.py`.
The tables for tracks C and V exist but nothing writes them yet.
Tasks: DB1, DB2, DB3.

## Security and privacy (S)

Goal: close the faults the review found in the engine's local surface, and seal what a vaulted item leaves in answers.
Built:
- A markdown image cannot load from another host.
- Each engine response carries security headers.
- The engine refuses a state-changing request that another website started (`Sec-Fetch-Site`).
- The file route serves an original as a download, never as a page that runs.
- A session token (`session.py`): the shell, the CLI and `bin/screenshots` send it, and the engine requires it.
- An answer that quoted a vaulted item is sealed with the item and opened again on unvault.

Open: the Content Security Policy for the phone page (S9, needs a device) and the docs (S11).
Tasks: S1 to S8, S10.

## The summary (M)

Goal: a summary that reads as a summary, not a list of loose statements, while search keeps its conceptual lines.
Built:
- Each summary line has a role: kind, subject, idea, bridge, gist, point or ask (`facets.role`).
- The model writes a one-sentence gist, 3 to 5 key points in the item's own words, and 5 to 8 search phrases.
- The Summary panel shows the gist, then Key points, then Ideas; bridges sit under "Also found by", closed; search phrases are never shown.
- The role rides the snapshot to the phone and back.
- One helper gives the gist of many items (`facets.gists`), and Settings says when summaries can be written in the new form.

Tasks: M1 to M10.

## Related notes (R)

Goal: related rows that say why two notes belong together, with fewer false links, and a way for the person to correct them.
Built:
- Rows in five named groups: Same subject, Named in, Same idea another field, Also mentions, You asked about both; then Close passages.
- A same-subject row shows the other note's gist.
- A shared name links two notes only when it matters to both.
- The judge takes the newest note first.
- 12 links are kept and 5 are shown, with Show all and a line while the judge is still working.
- "Named in" and "You asked about both" rows, read at open time with no model.
- Related notes appear in the margin while you write (`POST /artifacts/{id}/nearby`).
- Index-only lines (gist, point, ask) never propose a link.
- Keep and Not the same on an idea row (`link_feedback`); the judge, the links and Something shiny honour the verdict, and it rides the snapshot.

Tasks: R1 to R14.

## Search (Q)

Goal: search that answers at once, never waits on a model, and records enough to measure itself.
Built:
- Each search is recorded locally (`searches`) for the real-search eval.
- Chat reads more summary hits, with the passage that supports each, and the answer model sees why a passage is there.
- `/search` answers at once and the page draws a second time when the judge is done.
- Lifting and model ranking cannot hold a search.
- The embedder warms up when a search is about to come.
- Index-only lines do not reach the judge or the overview; a search-phrase hit says why it matched; a result shows the gist.

Open: the docs (Q11).
Tasks: Q1 to Q10.

## Something shiny (H)

Goal: a daily card that does not repeat itself and learns from the person.
Built:
- The card does not repeat a pair, and a pair with a fresh note comes first.
- Index-only lines do not count.
- Keep and Not the same on the card; the hunt does not bring back a refused pair.
- When cards are refused often, the model gets the passages.
- The links and the day's card go to the relay for the phone.

Open: the docs (H8).
Tasks: H1 to H7.

## Phone (P)

Goal: the phone gets what the Mac has: fast search, related notes, the day's card and feedback.
Built (data and bridge only):
- A keyword index in the phone's database, kept up to date by triggers and filled once for an older library; phone search uses it.
- The phone stores related rows, the day's card and the person's link verdicts, and sends verdicts back.
- Tauri commands for the page: `mobile_related`, `mobile_shiny`, `mobile_link_feedback`.

Open: every screen (P3 to P8) and the docs (P9).
Tasks: P1a, P1b, P1, P2, P6a, P6b, P7a, P7b, P8a, P8b.

## An answer shows where it came from (A)

Goal: match Fabric's cited answers on long documents: an answer points at the page and the words it used.
Built:
- Passages are numbered `[P3]`; the model writes the numbers in its answer and lists them in `used`; wrong numbers are dropped.
- Each used passage keeps its PDF page and first words (`chat_places`), which ride the chat snapshot and are removed when the item is vaulted.
- On the Mac, a `[P3]` mark is a "p. N" button that opens the PDF at that page with the words marked (`openArtifactAt`).

Owed device checks:
- A5: `openArtifactAt('<id of a PDF>', {page: 2, quote: '<six words from page 3>'})` scrolls to page 3 and marks the words.
- A6: an answer from a long PDF has "p. N" buttons, and a press opens the PDF at that page.

Open: the phone shows the marks raw (A7), and the docs (A8).
Tasks: A1 to A6.

## Fill the library from what is on this Mac (L)

Goal: a new person's library is full on the first day, from what is already on the Mac, with nothing sent to a service to read it.
Built:
- A link can be saved with its own date, on the background lane.
- A browser's bookmarks file comes in as links, with folders as tags.
- Kindle's `My Clippings.txt` comes in as one note per book.
- Apple Notes come in through JXA (not in the Mac App Store build), and come in again when they change (`source_items`, `importer._upsert`).
- New files in watched folders are kept (`watch.py`, `watch_dirs`).
- Settings > Library > From this Mac, its guide, and a row in the welcome.

Owed device checks:
- L6: add a watched folder, put a PDF in it, and wait for the next look; the PDF is on the wall.
- L7: open the welcome from the `?`; the row is there and its button opens the Library tab.

Limit: a file moved into a watched folder keeps its old modified time and is not taken.
Tasks: L1 to L8.

## Process

- Two rounds marked about 60 skipped tasks done each. `bin/check-plan` (in `bin/verify --fast` and the pre-commit hook) now refuses a done mark with no Done line, with "skipped", or with an open need.
- The third round closed 19 tasks with one commit each and no false marks.
