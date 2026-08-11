# Enqueue

A local-first tool for capturing anything and organising it later, by concept.

Save articles, PDFs, images, links, and notes without being asked for a folder, tag, or title.
The organising happens afterwards, when a subject is on your mind, and the app pulls together everything that speaks to that subject, including things that never used those words.

It runs entirely on your own Mac.
Nothing is uploaded anywhere unless you deliberately point it at an outside model.

---

## Prerequisites

- **macOS.** The desktop shell uses Tauri with macOS-specific APIs, and the API key store uses the macOS Keychain.
- **Python >= 3.12.** The engine is Python and targets 3.12 exactly (see `.python-version`).
- **[uv](https://docs.astral.sh/uv/).** All commands in this repo and in the desktop shell go through `uv run`, so it must be on your PATH. The shell looks for it at `/opt/homebrew/bin/uv` or `/usr/local/bin/uv`.
- **[Rust](https://www.rust-lang.org/) and [Tauri](https://v2.tauri.app/) prerequisites**, only if you want to build the desktop window from source. The pre-built binary at `desktop/target/debug/enqueue-desktop` is what `bin/relaunch` runs.
- **[Node.js](https://nodejs.org/)**, only for the JS parse check that `bin/relaunch` and `bin/verify` run before launching. If `node` is not on the PATH, the check is skipped silently.
- **[Ollama](https://ollama.com/)** running locally, if you want the default AI backend (model: `llama3.1:8b`). Not required for capture, search, or browsing; only for conversations and rooms.

---

## Install

```bash
git clone <repo-url> enqueue
cd enqueue
uv sync
```

This installs all Python dependencies from `pyproject.toml`, including `fastembed` and `sqlite-vec` for the search index.
There is no separate `--extra index` install step; the index dependencies are in the main dependency list.

If you want to build the desktop shell:

```bash
cd desktop
cargo build
cd ..
```

That produces `desktop/target/debug/enqueue-desktop`, which `bin/relaunch` expects.

---

## Running the desktop app

The easiest way to run everything:

```bash
bin/relaunch
```

This starts the Python engine (`enq serve`), waits for it to answer on `127.0.0.1:8787`, then launches the Tauri desktop window and brings it to the front.

After editing Rust code in `desktop/src/`:

```bash
bin/relaunch --build
```

This rebuilds the shell with `cargo build` before relaunching.

The script kills any existing `enqueue-desktop` and `enq serve` processes first, so engine and window always come up together.
Engine output is logged to `$TMPDIR/enqueue-app.log` (or `/tmp/enqueue-app.log`).

---

## Running the engine only

```bash
uv run enq serve
```

This starts the FastAPI/uvicorn server on `127.0.0.1:8787`.
You can then open `http://127.0.0.1:8787/` in a browser to see the home page (the main wall view), or `http://127.0.0.1:8787/capture` for the quick-capture overlay.

The engine binds to `127.0.0.1` only, never to `0.0.0.0`.

---

## CLI commands

The entry point is `enq`, registered in `pyproject.toml` as `enqueue.cli:app`.
All commands except `serve`, `migrate`, and `version` are thin HTTP clients over the running engine; if the engine is not running they print an error and exit.

| Command | What it does |
| --- | --- |
| `enq serve` | Start the engine on `127.0.0.1:8787`. |
| `enq version` | Print the installed package version. |
| `enq health` | Engine status and row counts (artifacts, versions, chunks, facets, chats). |
| `enq migrate` | Bring the SQLite database to the newest Alembic revision. Runs automatically at engine startup. |
| `enq note --body "text"` | Create a note (markdown body, stays editable). |
| `enq link "https://example.com"` | Save a URL. Nothing is fetched. |
| `enq artifacts --limit 20` | List artifacts, newest first. |
| `enq preview "ARTIFACT_ID"` | Fetch the title/description/image for a saved link. One request, because you asked. |
| `enq search "query" --limit 10` | Hybrid dense+sparse search. No model calls. |
| `enq chat "question" --chat-id "ID"` | Ask the collection something. Starts a new conversation or continues one. |
| `enq chats --limit 20` | List conversations, newest first. |
| `enq facets --limit 0 --redo` | Generate conceptual facets for eligible artifacts. Slow, resumable. |
| `enq facet-gate` | Decide which artifacts are eligible for facet generation. |
| `enq index` | Rebuild the search index from the database. |
| `enq doctor` | Index health: artifact/chunk counts, index row counts, embedding version, sync with the chunks table. |
| `enq chunk` | Rebuild text chunks from note bodies. |

Every command takes `--help` for full argument details.

---

## Running tests

```bash
uv run pytest -q
```

Tests live in `tests/` and cover chats, ingest, migrations, preview, providers, settings, and trash.
The test suite uses an in-memory or temporary database, not your real `~/.enqueue-poc` data.

---

## Lint

```bash
uv run black --check .
```

Or to format:

```bash
uv run black .
```

Black is configured in `pyproject.toml`: line length 100, target Python 3.12.

---

## Verification script

```bash
bin/verify
```

Runs three checks in sequence: JS parse validation on both served HTML pages, pytest, and a WCAG contrast check on the color palette in `home.html`.
Use this before committing UI changes.

---

## Contrast check

```bash
bin/check-contrast
```

Parses the `:root` color tokens from `src/enqueue/static/home.html` and verifies WCAG contrast ratios (4.5:1 for text, 3.0:1 for strong lines).
Exits non-zero if any token fails.

---

## Environment variables

All environment variables use the `ENQ_` prefix and can override `settings.json` at runtime.
The precedence is: environment variable > `settings.json` > built-in default.

| Variable | Default | Purpose |
|---|---|
| `ENQ_LLM_BACKEND` | `ollama` | Which model backend to use. One of: `ollama`, `openrouter`, `opencode`, `custom`. |
| `ENQ_LLM_MODEL` | `llama3.1:8b` | The model name to send to the backend. |
| `ENQ_OLLAMA_URL` | `http://127.0.0.1:11434/v1` | URL for the Ollama backend. Also used as `llm_url` in settings. |
| `ENQ_LLM_API_KEY` | `ollama` (placeholder) | API key for non-local backends. Falls back to the macOS Keychain if not set. |
| `ENQ_MODEL_RETRIES` | `1` | Extra retry attempts after the first model call (1 = two tries total). |
| `ENQ_VECTOR_STORE` | `sqlite-vec` | The search index backend. `sqlite-vec` is the only backend after the cutover. |
| `ENQ_USER_AGENT` | `Enqueue/0.2 (personal link preview; one request per saved link)` | User agent string sent when fetching link previews. |
| `ENQ_HOTKEY` | `Alt+Shift+E` | Global capture hotkey. |
| `ENQ_AUTO_PREVIEW` | `on` | Whether saving a link automatically fetches its preview. |
| `ENQ_LLM_HEADERS` | (empty) | Extra headers for model calls, one `Name: value` per line. |
| `ENQ_TRASH_DAYS` | `30` | Days before a trashed artifact is permanently destroyed. Minimum 1. |
| `ENQUEUE_REPO` | (detected) | Path to the repo, used by the desktop shell to find `uv run enq serve`. Written to `~/.enqueue-poc/repo` by `bin/relaunch`. |

Settings are also writable through the API (`PATCH /settings`) and stored in `~/.enqueue-poc/settings.json` with `0600` permissions.
No secret is ever written to that file; the API key lives in the macOS Keychain (via `/usr/bin/security`).

---

## Model backends

The engine speaks the OpenAI-compatible protocol to all backends through a single adapter (`src/enqueue/providers/`).

| Backend | URL | Local? | Needs key? |
| --- | --- | --- | --- |
| `ollama` | `http://127.0.0.1:11434/v1` | Yes | No |
| `openrouter` | `https://openrouter.ai/api/v1` | No | Yes (`ENQ_LLM_API_KEY`) |
| `opencode` | `https://opencode.ai/zen/v1` | No | Yes (`ENQ_LLM_API_KEY`) |
| `opencode-go` | `https://opencode.ai/zen/go/v1` | No | Yes (`ENQ_LLM_API_KEY`) |
| `custom` | (set via `ENQ_OLLAMA_URL`) | No | Yes (`ENQ_LLM_API_KEY`) |

Anything other than `ollama` sends the text of your artifacts to somebody else's computer.
Artifacts marked `local_only` never go to an outside service, even when one is configured.

---

## How search works

Search is the part of Enqueue that has to be good, because the whole promise is that you can find a thing later even when you have forgotten what you called it.
It follows three principles that the strong second-brain apps (mem, Fabric, mymind) converge on:

1. **Index everything you can see.** The headline search failures are gaps in what got indexed, not bad ranking. So annotations, image descriptions, PDF page text, and link previews all become searchable, not just the note body.
2. **Lexical and vector together, always.** Never vector-only. Exact words, typos, and meaning each have a channel, and the channels are fused.
3. **"Nothing found" is a real answer.** If you search for something you never saved, the honest result is empty, not a wall of loosely-related cards.

### Three layers, built at capture time

When you save something, the engine builds three searchable layers from it, behind the response (capture never waits):

| Layer | What it is | The gap it closes |
| --- | --- | --- |
| **Chunks** | the literal text, split into passages and embedded. Fed from the note body, a PDF's page text, a link's preview text, your annotations on an image, and a vision model's description of an image. | finding by the words that are actually there |
| **Facets** | 5 to 15 model-written statements of *what this could be an example of*, climbing from literal to abstract (levels 0-4), each embedded. | finding by a concept the item never names ("antifragility" reaching a furniture article about surviving stress) |
| **Entities** | the named things in the text, each enriched with a one-line world-knowledge fact ("Theodore Roosevelt - 26th US President"), embedded. | finding a named thing by a fact it never states (a Roosevelt biography reached by "president") |

Facets and entities are what make Enqueue different from plain RAG: they raise each artifact *up* toward the concepts you might search by, so the query does not have to share vocabulary with the note.

### Seven legs, one fused ranking

A free-text search runs several retrieval legs in parallel, each producing a ranked list, then fuses them with Reciprocal Rank Fusion (RRF, the canonical k=60):

- **Dense** - the query embedding against chunk vectors (meaning, paraphrase).
- **Keyword** - FTS5 BM25 over chunk text, with the **title weighted 10x** (exact words; a title match outranks a body match).
- **Trigram** - a trigram-tokenized index for substrings and partial words ("hydro" finds "hydroponics").
- **Fuzzy** - edit-distance matching over short fields (titles, entity names, annotation lines) for one-character typos that trigram misses ("copper" for "chopper").
- **Exact phrase** - a quoted `"grand alliance"` pins items containing that literal phrase.
- **Facets** - the conceptual channel, weighted by each facet's trust score.
- **Entities** - the named-thing channel.

After fusion, a light **recency** multiplier nudges newer items up, and an **opt-in cross-encoder reranker** can re-score the top window for extra precision. Results roll up to one row per artifact (six chunks of one note come back as one card), with a snippet from the best-matching passage.

### The relevance floor

Vector search always returns *some* nearest neighbor, however far. So a query for something you never saved would otherwise return a confident wall of unrelated notes. The floor stops that: a result survives only if it has a real lexical hit **or** a dense neighbor that is genuinely close; the ambiguous middle is settled by a single model judgment, failing open (a stray result is safer than hiding one of your own notes). A search with nothing close returns empty.

### Example flows - the breadth and depth

Each row is a different *kind* of query and the leg that carries it. The last two are the point of the whole system.

| You search | What happens | Leg |
| --- | --- | --- |
| `ziggurat` | a rare word that appears verbatim in one note - exact match, rank 1 | keyword (BM25) |
| `hydro` | a partial word - the trigram index matches "hydroponics" even though you typed a fragment | trigram |
| `tony tony copper` | a typo - fuzzy matching catches the one-character edit over the annotation "tony tony chopper" that keyword and trigram both miss | fuzzy |
| `"grand alliance"` | the quotes force a literal phrase - only items containing those exact words survive | exact phrase |
| a name that is only in the title | the title is weighted 10x and also prepended to the chunk index, so a name that appears nowhere in the body still finds the note | keyword (title) |
| `what survives being stressed` | a paraphrase sharing no words with a note about a chair that survives being sat on - matched by meaning | dense |
| `notes on a president` | the note is a Roosevelt biography that never says "president"; a **facet** ("effective governance requires a leader") and an **entity** ("Theodore Roosevelt - 26th US President") both bridge the gap | facets + entities |
| `hyperdimensional cheese grater` | you never saved this; no lexical leg fires and the nearest vector is far, so the floor returns **nothing found** instead of a wall | relevance floor |

The first five are lexical breadth - exact, partial, typo, phrase, and field-weighted. The sixth is semantic. The seventh is the conceptual bridge that plain RAG cannot cross, and the eighth is the honesty that keeps the tool trustworthy.

Search runs entirely on your Mac, over the one SQLite file. The dense search is exact (brute-force) nearest-neighbor, which is fast at this scale; only the optional gray-zone judge and the cross-encoder reranker ever call a model, and only for the searches that need them.

---

## Where your data lives

Everything is stored under `~/.enqueue-poc`:

| Path | Contents |
| --- | --- |
| `enqueue.db` | SQLite database: artifacts, versions, chunks, facets, entities, chats, trash, secrets, and the search index (sqlite-vec + FTS5 tables). |
| `blobs/` | Original uploaded files, unmodified. |
| `settings.json` | User preferences (not secrets). |
| `repo` | One-line pointer to the repo path, written by `bin/relaunch` so the desktop shell can find the engine. |
| `capture-position` | Last screen position of the capture overlay. |

To back up Enqueue, copy that folder.
Your original files are in `blobs/` byte for byte, so they stay readable by other programs even if Enqueue disappears.

---

## Project layout

```
enqueue/
  bin/
    relaunch           # Restart engine + desktop window together
    verify             # JS parse + pytest + contrast check
    check-contrast     # WCAG contrast validation on home.html palette
  desktop/
    src/main.rs        # Tauri shell: window, hotkey, engine lifecycle, capture overlay
    Cargo.toml         # Tauri 2 + global-shortcut plugin
    tauri.conf.json    # Window config, capabilities, CSP
  src/enqueue/
    cli.py             # `enq` entry point (Typer)
    api.py             # FastAPI engine: all HTTP endpoints
    config.py          # Constants: paths, models, backends, env var overrides
    settings.py        # settings.json read/write, three-layer resolution
    db.py              # SQLite + Alembic migration at startup
    notes.py           # Note CRUD, versioning, annotations
    capture.py         # File/link upload, PDF rendering, text extraction
    chats.py           # Conversations: retrieval-augmented Q&A
    preview.py         # Link preview fetching (OG tags, images)
    trash.py           # Soft delete with retention window
    keyring.py         # macOS Keychain wrapper for API keys
    prompts.py         # LLM prompt templates
    schemas.py         # Pydantic models
    ingest/
      chunk.py         # Text chunking
      facets.py        # Conceptual facet generation
      queue.py         # Background ingest queue
      secrets.py       # Credential scanning
    index/
      embed.py         # Dense embeddings (fastembed)
      store.py         # VectorStore interface + get_store() factory
      store_sqlite.py  # sqlite-vec backend (vec0 + FTS5, RRF fusion)
      fusion.py        # Reciprocal rank fusion, pure
      bootstrap.py     # Startup index build + cutover cleanup
    retrieve/
      candidates.py    # /search candidate retrieval and rerank
    providers/
      base.py          # Provider protocol + error handling
      ollama.py        # Ollama adapter
    migrations/
      versions/        # 0001-0020 Alembic migrations
    static/
      home.html        # Main wall view (inline JS/CSS)
      capture.html     # Quick-capture overlay
      fonts/           # IBM Plex Sans
  tests/
    conftest.py
    test_chats.py
    test_ingest.py
    test_migrations.py
    test_preview.py
    test_providers.py
    test_settings.py
    test_trash.py
  docs/
    PRODUCT.md         # Product spec
    DESIGN.md          # Design system
    CURATION.md        # How curation/rooms work
    EVAL.md            # Evaluation methodology
    OPEN.md            # Open questions
    PROGRESS.md        # Development log
  pyproject.toml
  alembic.ini
  .python-version
```

---

## API overview

The engine exposes a REST API on `127.0.0.1:8787`.
Key endpoints:

- `GET /` - The home page (main HTML view)
- `GET /capture` - The capture overlay (HTML)
- `GET /health` - Status and counts
- `GET /artifacts` - List artifacts (paginated, sortable, filterable by pinned)
- `GET /artifacts/{id}` - Full artifact detail
- `POST /notes` - Create a note
- `POST /capture/link` - Save a URL
- `POST /capture/upload` - Upload a file
- `POST /artifacts/{id}/preview` - Fetch link preview
- `GET /search?q=...` - Hybrid search
- `POST /chats` - Start or continue a conversation
- `GET /settings` - Read all settings + storage info
- `PATCH /settings` - Update settings
- `PUT /settings/api-key` - Store API key in Keychain
- `DELETE /settings/api-key` - Remove API key from Keychain
- `POST /index` - Rebuild the search index
- `POST /reprocess` - Re-ingest everything
- `GET /trash` - List trashed artifacts
- `DELETE /trash/{id}` - Permanently destroy one artifact

---

## Known gaps

- **No bundled `.app` yet.** The desktop shell runs from `desktop/target/debug/enqueue-desktop` and spawns the engine via `uv run enq serve` from the repo. There is no packaged sidecar binary, so the app cannot be distributed as a double-clickable `.app` without the repo and `uv` present.
- **No CI pipeline.** There is no GitHub Actions or other CI configuration in the repo. `bin/verify` is the closest thing to a pre-commit gate.
- **The global capture hotkey opens a window, but that window is the capture overlay, not a full capture flow.** The hotkey is functional (registered via `tauri-plugin-global-shortcut`), but the overlay is a small note-input box, not a full capture interface.
- **The wall does not page beyond 120 items.** The API supports `limit` and `offset`, but the home HTML view does not implement infinite scroll or pagination.
- **No encryption at rest (planned).** The database and blobs are plaintext today. Encryption is a planned milestone.
- **No sync (planned).** One machine only today. The design is scoped in `docs/e2e/E2E.md` (encrypted per-artifact snapshots, last-writer-wins) and `docs/MOBILE.md` (a relay plus a mobile client), but no sync code exists yet.
- **The default local model (`llama3.1:8b`) is weak.** Roughly three of four model outputs fail their validators. Conversations work; a better model is needed for reliable chat answers and facet generation.
- **Search is brute-force.** sqlite-vec does exact nearest-neighbour search over the 768-dim embeddings in `enqueue.db`. At this library's scale that is fast (Phase 19 measured p95 21 ms); at a few hundred thousand chunks it will need quantization or an approximate index.
- **No Windows or Linux support.** The desktop shell uses macOS-specific AppKit calls (activation, hiding). The Keychain wrapper is macOS-only.

---

## License

See `LICENSE` in the repo root.
