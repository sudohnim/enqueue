# Enqueue POC - task list

Status: **chats shipped, on migrations.** 15 of 21 tasks.

Asking is now a conversation rather than a single shot, the schema is under Alembic, a saved link can be made to say what it is, and a PDF is read inside the app.

Remaining: V2 facet generation is still unrun, Phase H was never built, and curate is now measured and in trouble. See [Open questions](#open-questions).

```bash
cd desktop && ENQUEUE_REPO=/Users/minhmai/enqueue ./target/debug/enqueue-desktop
```

The shell spawns the engine, waits for it, and kills it on close. If an engine is already listening it attaches instead.

Work through the tasks **in order, one at a time**. Check a box only after its "Done when" is verified by actually running the command shown.

---

## What went wrong, and what it costs

The first build treated **every** artifact as an immutable capture with an editable note bolted on underneath.

That is correct for a web page, a PDF, or an image: those came from the world, and the promise is that what you saved is what the source actually said. It is wrong for a note you wrote. Your own markdown is not a capture. It is the artifact, and its body has to be editable like any other text you own.

The symptom was a note whose content could not be changed, only appended to. The cause was a data model that had no concept of authorship.

**The rule now:**

| Kind | Body | Why |
|---|---|---|
| `note` | **markdown, fully editable, versioned** | You wrote it. It is yours. |
| `link`, `pdf`, `image`, `file` | **immutable** | It came from the world. Fidelity is the point. |

A note attached to a captured artifact is an annotation and stays append-only. A note that *is* the artifact is just a document.

### Torn out

- `src/enqueue/ingest/fabric.py` (110 lines) - a TipTap HTML parser for a format nothing will produce again.
- `src/enqueue/ingest/importer.py` (325 lines) - Fabric-shaped import, folder-to-`local_only` conflation, blob-only markdown.
- `blocks` as the storage for authored content. A note is one markdown document, not a tree of immutable rows.
- 11 tests covering the above.

### Kept

`db`, `config`, `providers/*`, `schemas.py`, `prompts.py`, `secrets.py`, `index/*`, `retrieve/*`, and the API and CLI shells. The retrieval half of the system was never the problem.

`chunk.py` survives with its rule inverted: it chunked a block tree, and now chunks markdown. The claim-plus-elaboration insight still applies, it just reads headings and list nesting instead of `parent_id`.

### Honest state of the previous build

23 of 35 tasks were checked. All of phases A through G existed and ran end to end. Phase H, the evaluation harness, was never built. Facet generation completed on 6 of 52 artifacts before the corpus was discarded.

Four findings from that build are load-bearing and carry forward. They are recorded under [Carried findings](#carried-findings) rather than being rediscovered.

---

## Design brief: the capture control

Confirmed with the human before writing this.

**What it is.** One floating control, bottom centre, present on every surface. It replaces the top bar entirely. Three actions: `+` to capture, magnifier to search, question mark to ask.

**Primary action.** Capture. It is the precondition for everything else in the product, and the one interaction whose latency is non-negotiable.

**Direction.** Restrained, per PRODUCT.md. Existing tokens, no new palette. The scene is unchanged: a museum after hours, the walls receding so the objects fill the screen. Anchor reference is Fabric's floating pill, named by the human.

**Why the pill replaces the chrome.** A persistent top bar is a wall. Removing it is the same argument as removing the empty thumbnail: everything that is not an artifact should get out of the way.

### The `+` menu

Four items. Canvas and voice note are deliberately out of scope.

| Item | Produces | Editable |
|---|---|---|
| Note | a markdown document | yes, it is yours |
| Upload | a file, stored whole | no |
| Link | a URL, fetched later | no |
| Image | a file, stored whole | no |

### Ask follows context

The question mark asks about **whatever is on screen**: this artifact, this exhibit, or the whole museum from home. A visible control widens the scope. This makes "ask about this PDF" a cheap action instead of always paying for the full pipeline.

### States

| State | Behaviour |
|---|---|
| Rest | three glyphs, no labels |
| `+` open | four items rise; Escape or outside click dismisses |
| Search open | the pill becomes a field in place, results replace the view |
| Ask open | same, with the current scope named |
| Capturing | the control returns immediately; ingest is asynchronous and never blocks |
| Offline model | search and capture still work; ask and curate say what is unavailable |

### Anti-goals

Not a command palette. Not a dock with a growing row of icons. It never grows a fourth action without something else leaving.

---

## Carried findings

From the previous build. Each was invisible in the spec and cost real time to find.

1. **Facets came back as paraphrase, not abstraction.** Every level-2-plus statement opened "This writing demonstrates...", describing the artifact rather than making a claim, and passed every validator. Fixed by a self-reference ban in `schemas.py` and the prompt. This is the moat, and it was silently dead.
2. **`instructor` renamed `validation_context` to `context`** in 1.9. The wrong keyword does not raise, it silently disables every context-dependent validator including the proper-noun ban.
3. **Titles were never indexed.** A note whose title is the only place a name appears was unfindable by that name. Prepend the title at index time.
4. **Dense retrieval alone cannot find proper nouns.** Measured: "what did Epictetus say about control" returned The Prince. Hybrid dense-plus-sparse with RRF is load-bearing, not an optimisation.

Also carried: **strict validators plus a weak local model is pathological.** Four of ten rerank calls failed on `evidence is not a verbatim span`, each burning its retries. The validators are right and `llama3.1:8b` cannot satisfy them. See [OPEN.md](OPEN.md) item 0. Re-measured this session at 3 of 4; it is getting worse, not better.

Added this session:

5. **A prompt that only warns produces refusal.** The first chat prompt named the hallucination failure three times and never said what to do when the passages did answer, so the model refused a question whose answer was the top passage at a retrieval score of 1.0. A validator catches a wrong answer; nothing catches an answer that was never attempted. State the ordinary case first.
6. **Write the question and its answer together.** Appending the question first reads as natural and leaves an orphan when the model call fails, which the retry then duplicates. Found on the second turn of the first real conversation.
7. **Measure layout when you use it, not when you mount.** `clientWidth` at mount is 0 whenever the pane has not laid out, and a zero-width render is a blank screen with no error anywhere.

---

## Rules for the implementing agent

- **Do exactly one task per turn.** Report what changed and how you verified it.
- **Never commit.** The human commits.
- **If a task and a spec document disagree, the spec wins.** Specs are [PRODUCT.md](PRODUCT.md), [AGENTS.md](../AGENTS.md), [CURATION.md](CURATION.md), [EVAL.md](EVAL.md).
- **Do not invent libraries or model names.** Everything you need is written here.
- **Never use an em dash.** Plain dash.
- Format with `black` before reporting done.

## Hard rules

0. **Schema changes are migrations.** Never edit a table by hand and never add a `CREATE TABLE` to application code. A new revision in `src/enqueue/migrations/versions/`, or it does not happen.
1. **A note's body is editable. A capture's body is not.** This is the correction the rebuild exists for.
2. **Never put text in a Qdrant payload.** Ids only. Text lives in SQLite and is fetched after retrieval.
3. **Never use instructor's default `TOOLS` mode.** Pass the mode explicitly.
4. **Pass `context=`, not `validation_context=`.** The wrong keyword silently disables validators.
5. **Prepend the title when indexing.** Otherwise names in titles are unfindable.
6. **Run the secret scan before any text reaches a model.**
7. **Capture returns before processing.** Always. Ingest is a queue.

---

## Phase R - Rebuild the artifact model

### R1. Schema

- [x] **Files:** `src/enqueue/migrations/`, `src/enqueue/db.py`

Superseded by [M1](#m1-migrations). `schema.sql` is gone; revision `0001` is the same shape.

Replace `blocks` with a body on the artifact, and keep note history as versions.

```sql
CREATE TABLE artifacts (
  id           TEXT PRIMARY KEY,
  kind         TEXT NOT NULL,        -- note | link | pdf | image | file
  title        TEXT NOT NULL,
  body         TEXT,                 -- markdown. NOTES ONLY. NULL for captures.
  source_url   TEXT,
  content_hash TEXT NOT NULL UNIQUE,
  mime         TEXT,
  filename     TEXT,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL,
  local_only   INTEGER NOT NULL DEFAULT 0,
  status       TEXT NOT NULL         -- ok | pending | text_only | failed
);

-- Every saved state of a note's body. The note itself is mutable; this is the log
-- that makes two machines editing it lossless.
CREATE TABLE artifact_versions (
  id          TEXT PRIMARY KEY,
  artifact_id TEXT NOT NULL REFERENCES artifacts(id),
  body        TEXT NOT NULL,
  created_at  TEXT NOT NULL
);

-- Annotations on a CAPTURED artifact. Append-only, because they comment on
-- something immutable. A note's own body is not stored here.
CREATE TABLE annotations (
  id            TEXT PRIMARY KEY,
  artifact_id   TEXT NOT NULL REFERENCES artifacts(id),
  supersedes_id TEXT REFERENCES annotations(id),
  text          TEXT NOT NULL,
  created_at    TEXT NOT NULL
);
```

Keep `chunks`, `facets`, `facet_skips`, `secret_hits`, `exhibits`, `exhibit_members` as they are.

**Done when:** `enq init` applies cleanly twice and `.tables` lists the new set with no `blocks`.

### R2. Delete the Fabric layer

- [x] Remove `ingest/fabric.py`, `ingest/importer.py`, and the 11 tests that cover them. Remove the `import-fabric` and `import-bookmarks` commands and endpoints.

**Done when:** `uv run pytest` is green and `rg -i fabric src/` returns nothing.

### R3. Notes are documents

- [x] **Files:** `src/enqueue/notes.py`, endpoints on `api.py`

```
POST   /notes                {title?, body}      create, returns artifact
PATCH  /artifacts/{id}/body  {body}              edit. UPDATE the artifact,
                                                 append to artifact_versions
GET    /artifacts/{id}/versions
```

Editing a note **updates** `artifacts.body` and **appends** to `artifact_versions`. That is not a contradiction with append-only: the log is the history, the artifact is the current state.

Title defaults to the first heading or first line of the body.

**Done when:** create a note, edit it three times, read it back with the latest body and three versions.

### R4. Captures

- [x] **Files:** `src/enqueue/capture.py`

```
POST /capture/link    {url}              status pending, no fetch yet
POST /capture/upload  multipart          file, image, or pdf
```

Content-addressed by sha256. Dedupe on hash. Secret scan before anything is stored as text. `mime` and `filename` recorded. PDFs get page count via pymupdf.

**Done when:** upload a PDF and an image, post a link; all three appear with correct kinds, and re-posting any of them adds nothing.

### R5. Chunking, inverted

- [x] **File:** `src/enqueue/ingest/chunk.py`

Chunk markdown instead of a block tree. A heading plus its content is one chunk. Consecutive short paragraphs merge to a floor of 120 words. Oversized chunks split at 600.

The reasoning is unchanged from the previous build, where merging fixed a median chunk size of 17 words caused by paragraph-per-block shredding.

**Done when:** a 2,000-word markdown note produces chunks with a median above 80 words and none under 20.

---

## Phase U - The capture control

### U1. The pill

- [x] **File:** `src/enqueue/static/museum.html`

Three glyphs, bottom centre, fixed. Removes the top bar. Uses existing tokens and the 4pt scale already in the file.

**Done when:** it renders in both themes, is keyboard reachable, and the top bar is gone.

### U2. The `+` menu

- [x] Four items: note, upload, link, image. Escape and outside-click dismiss. Motion respects `prefers-reduced-motion`.

**Done when:** each item opens its capture path and the menu closes on Escape.

### U3. Note editor

- [x] Markdown source with live render, using the renderer already written. Saves on blur and Cmd+S. Editing the body of a note, not appending underneath it.

**Done when:** create a note, type markdown, watch it render, reload, and find the same text in the field.

### U4. Search and ask in the pill

- [x] Magnifier expands the pill into a field in place. Question mark does the same and names the current scope.

**Done when:** both work from home and from an artifact, and ask reports the scope it used.

---

## Phase V - Reconnect the engine

### V1. Index notes and captures

- [x] Chunk and embed on save. Title prepended at index time, per hard rule 5.

This was checked before it was true. Nothing called `chunk_artifact` on save and nothing indexed, so a note stayed invisible until someone ran `enq chunk && enq index` by hand. Found while building chats, which cannot retrieve anything from an index that is never written.

Now `ingest/queue.py` owns it: one worker thread, fed by `notes.create`, `notes.edit`, and `preview.fetch`. Capture still returns first, per hard rule 7. `qdrant.index_artifact` replaces one artifact's points instead of resetting the collection, because the full pass would drop the whole index on every keystroke that triggers a save.

**Done when:** a note is searchable within seconds of being written. Verified: a note written through the API was returned by `/search` about four seconds later with no manual step.

### V2. Facets

- [ ] Eligibility gate: skip under 40 words, skip captures with no extracted text, skip `text_only`.
- [ ] Generation on save, asynchronously.

**Done when:** a substantial note gets 5 to 15 facets, at least two at level 3 or above.

### V3. Curate

- [x] Unchanged from the previous build. Verify it still runs against the new model.

**Run, and the result is bad.** Four candidates, `keep=3`, on `llama3.1:8b`:

| | |
|---|---|
| wall clock | 4 minutes 4 seconds |
| judgments failed validation | 3 of 4 |
| kept | 1 |
| synthesis | failed, and the error was being swallowed |

The one surviving placard was good: "Antifragility through embracing potential harm and reversing its outcomes." The pipeline is correct. The model cannot drive it.

Two things were fixed rather than hidden: `_synthesise` now returns its error instead of `None`, and the curate view reports both the failure count and the synthesis error, so a thin room says whether the collection was thin or the model was.

Concurrency is not the lever. `RERANK_CONCURRENCY` is 4 and is used, but Ollama serves one request at a time by default, so the four judgments ran nose to tail. See [Open questions](#open-questions), question 1.

---

## Phase M - Migrations

### M1. Migrations

- [x] **Files:** `src/enqueue/migrations/`, `alembic.ini`, `src/enqueue/db.py`

Alembic, with SQLAlchemy present only to drive it. The runtime still talks to SQLite through `sqlite3`; there are no ORM models and autogenerate is deliberately unavailable, so every revision is written by hand.

`env.py` reads the database path from `enqueue.config` rather than from `alembic.ini`, so the CLI and the running engine can never disagree about which file they are migrating. `db._alembic_config` builds the config in code, so nothing depends on the process's working directory - the desktop shell starts the engine from wherever it happens to be, and a bundled app has no repo to find an ini file in.

The case worth caring about is a database that predates all this. It already has the baseline shape, so replaying `0001` would fail and recreating it would destroy everything the person ever saved. `db.migrate` stamps it at `0001` and upgrades from there. Verified against the real development database: 5 artifacts in, 5 artifacts out, four new tables added.

| Revision | What |
|---|---|
| `0001` | baseline, identical to the old `schema.sql` |
| `0002` | `link_previews` |
| `0003` | `chats`, `chat_messages`, `chat_citations`, `chat_topics` |

**Done when:** a fresh database reaches head, migrating twice is a no-op, and a pre-Alembic database keeps its rows. All three are tests in `tests/test_migrations.py`.

---

## Phase L - Links and files

### L1. Link previews

- [x] **Files:** `src/enqueue/preview.py`, `0002`, the link view

Saving a link still fetches nothing. A preview is opt-in, one request, because the person pressed the button. Only text is stored: an `og:image` kept as a URL would fetch from the publisher on every view forever, which is worse than the single request the default was avoiding.

The link view lost both blocks of prose that were on it. One was an implementation detail wearing the clothes of content ("Nothing was requested from the publisher, so nobody learned you read it"), and the other was a placeholder restating the label directly above it. What is left is the page's own description, and, when there is no preview yet, a button whose cost is written under it.

**Not every page will resolve.** Wikipedia refuses a client that does not carry a contact URL, and returns 403. That is their published policy working as intended, and the answer is to identify yourself, not to disguise the request, so `ENQ_USER_AGENT` exists and the default does not fabricate a URL. See [Open questions](#open-questions), question 3.

A previewed link is chunked and indexed like anything else, so it is findable by what the page says rather than only by its address.

**Done when:** a link resolves to a real title and description, the artifact's placeholder title is replaced, and the failure says something a person can act on. Verified on `fastapi.tiangolo.com` (resolved, title replaced, indexed) and `en.wikipedia.org` (refused, with the remedy named).

### L2. Read PDFs in the app

- [x] **Files:** the reader in `museum.html`, `GET /artifacts/{id}/page/{n}`

The external "open the file" link is gone. Pages are rasterised by the engine and read in place, lazily, at the screen's real pixel density. Only "keep a copy" remains, as a download.

Two bugs found by running it. The width was measured at mount, when the pane sometimes has not laid out, producing `?width=0` and a blank reader; it is now measured when a page is actually reached, and the endpoint clamps the width rather than returning 404. And one observer cannot do two jobs: loading wants to fire a screen early, the page counter wants to fire late and exactly, and sharing one made the counter read "2 / 9" while page one filled the screen. There are two observers now.

A page that will not render says so and stays in place. Removing it would silently renumber the document under the reader.

**Done when:** a nine-page PDF reads end to end in the app, sharp on a Retina display, with an accurate page counter. Verified.

---

## Phase C - Chats

### C1. Chats replace the single-shot ask

- [x] **Files:** `src/enqueue/chats.py`, `0003`, endpoints, the chat surface

The question mark no longer runs curate. It opens a conversation.

The reason is the premise of the product: the conceptualisation is usually not known in advance, so a single shot asks the person to name the thing they are trying to find. A conversation lets them circle it.

**Topics are why this is not just a transcript.** After each exchange, the concepts the conversation is circling are extracted and stored against the chat. A topic is the same kind of object a lens is, so it is clickable and hangs a room. They are regenerated from the whole transcript each time rather than appended to, because a conversation's real subject is often not visible until several turns in, and a list that only grows keeps its wrong early guesses forever. Topics that come back are kept by id, so one already used to hang a room does not change identity underneath it.

Three model calls, and only the first blocks the reply. A chat whose title or topics failed is a chat that works and is badly named.

**Done when:** a question is answered from the collection with citations, a follow-up keeps the thread, and an absent subject is refused. All verified against `llama3.1:8b`.

### C2. The answer contract

- [x] **File:** `src/enqueue/schemas.py`

The failure this exists for is the answer that reads as though it came from the museum and did not. A model that knows the subject will answer from what it knows, cite whatever it was shown, and produce something fluent and correct and unconnected to anything the person saved. It is indistinguishable from the good case from the outside, and it quietly makes the collection pointless.

So `grounded` is a claim the model has to make, and the citations have to back it: cite nothing while grounded, or cite while not grounded, and the answer is rejected and re-prompted. Citations naming an artifact that was never offered are rejected outright and dropped again on the way to the database.

**The first version of the prompt was wrong in the other direction.** It warned about hallucination three times and never said what to do when the passages did answer, so the model refused a question whose answer was sitting in the top passage at a retrieval score of 1.0. Rebalanced: grounded is the ordinary case, refusal is for no fit rather than imperfect fit. Same question, same corpus, correct answer with two citations.

### C3. The chat surface

- [x] **File:** `src/enqueue/static/museum.html`

A left rail of conversations, each named by what it was about, with the active one's topics beneath it in gold. It is the only persistent chrome in the product, and it earns that: a conversation you cannot find again is a conversation you did not have. Below 900px it slides away behind a control in the pill.

The pill becomes the composer. There is still exactly one input surface in the app.

**Done when:** a conversation renders, sends, shows its thinking, cites clickable artifacts, and lists its topics; and it holds up in both themes and at 860px. Verified.

### C4. Rooms are kept, not rebuilt

- [x] `POST /exhibits`, `GET /exhibits/{id}`

Clicking a topic hangs a room. Keeping it saves what was already computed rather than re-running three model passes to set a flag, and the payload is revalidated on the way in with the same context the generating call used, because it made a round trip through a client.

Saved exhibits used to render as a name and a through line with no artifacts in them, because nothing served their members. They render now.

---

## Phase H - Measure

Never built. Unchanged from the previous plan, and blocked on the same thing: a corpus with **planted analogies**. Junk data scores perfectly and means nothing. See [OPEN.md](OPEN.md) item 1.

- [ ] H1. Proposal pass, brute force, never using retrieval
- [ ] H2. Golden set, seven lenses, corrected by hand
- [ ] H3. Harness reporting `hard-hit@15`
- [ ] H4. First measurement, with the miss breakdown by cause

---

## Phase D - The macOS shell

### D1. Tauri window

- [x] **Files:** `desktop/Cargo.toml`, `desktop/src/main.rs`, `desktop/tauri.conf.json`

A native window over the same HTML the browser view uses, so the layout is shared and there is one client to maintain rather than two.

The shell owns three things and nothing else: the window, the menu bar, and the lifetime of the engine process. It spawns `uv run enq serve`, waits up to 30s for the port, and kills the child when the window closes. If an engine is already listening it attaches rather than starting a second one.

Title bar is `Overlay` with a hidden title, so the traffic lights float over the content. A visible title bar would be the wall the pill exists to remove.

**Done when:** the app opens, the museum renders, and closing it leaves no orphan engine.

### D2. Bundling - not done

- [ ] `cargo tauri build` needs the engine as a real sidecar binary rather than a `uv run` child, plus signing and notarisation.

This is the packaging problem AGENTS.md already flags: a bundled CPython that breaks on OS updates. Development runs from the repo, which is fine until it ships.

---

## Open questions

Six decisions I could not make for you, each with what I would do.

### 1. The local model cannot drive curate. Settled for now: it does not have to.

Measured this session: 3 of 4 rerank judgments failed validation, synthesis failed outright, four minutes for four candidates. The previous build measured 4 of 10 on the same validator. It is getting worse as the validators get stricter, and the validators are right.

This is [OPEN.md](OPEN.md) item 0, now with numbers.

**Decided: `llama3.1:8b` stays as a placeholder and the bad results are accepted.** The POC is being built, not judged, and tuning the model now would be optimising a number nobody is reading yet. A real model gets pointed at when there is something worth measuring; GLM 5.2 through opencode is the intended one.

Two things were done so that swap costs nothing later:

- **The adapter was already protocol-generic**, it just hardcoded the API key. It no longer does. Any OpenAI-compatible endpoint is now three environment variables and no code change: `ENQ_OLLAMA_URL`, `ENQ_LLM_MODEL`, `ENQ_LLM_API_KEY`.
- **Retries moved to `ENQ_MODEL_RETRIES`, default 1.** They were 2, meaning three attempts per judgment, which on a model that fails most of them is two extra generations bought for almost nothing. Re-measured on the same four candidates: 3 minutes 30 against 4 minutes 4, and 2 kept against 1. Set it to 0 for the fastest, worst run; raise it when the model is good enough for a retry to be worth waiting for.

The remaining latency is the placeholder generating slowly, and Ollama serving one request at a time, which nullifies `RERANK_CONCURRENCY`. `OLLAMA_NUM_PARALLEL=4` on the Ollama daemon would fix the second half without touching quality, if the wait becomes annoying before the model is replaced.

**Do not soften the evidence-verbatim validator to make the placeholder pass.** It is the thing standing between a placard and a plausible invention, and it is the reason the bad results are visibly bad instead of quietly wrong.

### 2. Should facets be generated on save?

`ingest/queue.py` chunks and indexes. It does not generate facets, so the facet layer is empty and conceptual retrieval is running on chunks alone. Every retrieval in this session was literal.

**Recommendation: still leave it off, and now for a sharper reason.** Question 1 settled on keeping a placeholder model, which makes this worse rather than better: a bad facet is written to the index permanently, so generating them from a model nobody trusts would poison the conceptual layer with junk that outlives the placeholder. Chat answers and curate rooms are read once and thrown away; facets are not.

The queue has the seam. Turn it on in the same change that points at the real model.

Meanwhile `enq facets` still works as a manual pass, and it is worth running once on a real corpus to see what the facet half actually buys.

### 3. Should the default user agent carry a contact URL?

Wikipedia and others refuse a client without one. Complying is identification, not evasion, and is exactly what their policy asks for. But I will not invent a URL that does not exist, so the default stays honest and those pages fail with the remedy named.

**Recommendation: set `ENQ_USER_AGENT` to something with a real contact URL once there is one** - a repo, a personal domain, anything you actually own. Until then the current behaviour is correct: it fails, and it says why.

### 4. Should chats sync?

Everything else in the data model is built for the encrypted append-only log. Chats are not in it yet, and I did not put them there, because their status is genuinely ambiguous. Messages are append-only and would sync cleanly. Topics are derived and should not sync at all. And a chat is the one object in this product that can be deleted, which is a shape the log does not currently have.

**Recommendation: sync messages, never sync topics, and treat deletion as a tombstone event.** But this touches the sync design in [AGENTS.md](../AGENTS.md), so it is a spec change before it is a code change.

### 5. Should an answer stream?

It does not. A question sits on "reading what you saved" for 15 to 30 seconds against the local model. The structured-output contract is what makes streaming awkward: `grounded` and `cited` are only meaningful once the whole object exists.

**Recommendation: leave it.** Streaming a grounded answer means streaming prose whose citations may not survive validation, which would show the person a paragraph and then retract it. If the wait becomes the complaint, the honest fix is showing which artifacts are being read while it thinks - the passages are already known before the model is called, and `GET /chats/passages` already returns them.

### 6. What happens to exhibits now that curate is reached only through a topic?

Rooms still work and are still saved. But nothing outside a chat can build one, so a lens that occurs to you in the shower has no door.

**Recommendation: leave it for now and watch whether you miss it.** The premise of the change is that people do not arrive knowing their lens. If that turns out to be wrong for you, the cheapest fix is a fourth pill action, and the pill's own rule says it never grows a fourth action without something else leaving.

---

## Not done

- **Phase H, the eval harness.** Unchanged and still blocked on a corpus with planted analogies. Everything measured this session was measured by hand on seven junk artifacts, which is enough to find bugs and not enough to score anything.
- **D2, bundling.** `cargo tauri build` still needs a real sidecar, signing, and notarisation.
- **Facet generation on save.** Question 2.
- **Chat sync.** Question 4.

---

## Specs updated

Done before R1, since the code would otherwise contradict them.

- **PRODUCT.md** - principle 6 now names three categories, the museum model gained a "Two kinds of artifact" table, and the decision log records why the first model was wrong.
- **AGENTS.md** - invariant 2 split by kind, invariant 3 restated as "no user-authored text is ever destroyed", `note_entries` replaced by `artifact_versions` plus `annotations`, sync events and conflict rules rewritten.
