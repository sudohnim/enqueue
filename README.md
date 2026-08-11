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
You can then open `http://127.0.0.1:8787/` in a browser to see the "museum" (the main wall view), or `http://127.0.0.1:8787/capture` for the quick-capture overlay.

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
| `enq curate "lens" --keep 15 --pool 150 --save` | Build a "room" on a theme. Slow; involves multiple model calls. |
| `enq lens-eval --corpus --baseline 0.933` | Measure how the lens threshold places true matches (CI guard once a pipeline exists). |
| `enq lens-cache clear\|stats` | Clear or inspect the lens judgment cache. |
| `enq facets --limit 0 --redo` | Generate conceptual facets for eligible artifacts. Slow, resumable. |
| `enq facet-gate` | Decide which artifacts are eligible for facet generation. |
| `enq index` | Rebuild the search index from the database. |
| `enq reindex` | Rebuild the search index with visible progress. Resumable. |
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

Runs three checks in sequence: JS parse validation on both served HTML pages, pytest, and a WCAG contrast check on the color palette in `museum.html`.
Use this before committing UI changes.

---

## Contrast check

```bash
bin/check-contrast
```

Parses the `:root` color tokens from `src/enqueue/static/museum.html` and verifies WCAG contrast ratios (4.5:1 for text, 3.0:1 for strong lines).
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

## Where your data lives

Everything is stored under `~/.enqueue-poc`:

| Path | Contents |
| --- | --- |
| `enqueue.db` | SQLite database: artifacts, versions, chunks, facets, chats, exhibits, trash, secrets, and the search index (sqlite-vec + FTS5 tables). |
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
    check-contrast     # WCAG contrast validation on museum.html palette
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
      chunk.py         # Text chunking (chonkie)
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
      candidates.py    # Candidate retrieval for curation
      curate.py        # Room/exhibit building
      expand.py        # Query expansion
      rerank.py        # LLM-based reranking
    providers/
      base.py          # Provider protocol + error handling
      ollama.py        # Ollama adapter
    migrations/
      versions/        # 0001-0008 Alembic migrations
    static/
      museum.html      # Main wall view (inline JS/CSS)
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

- `GET /` - The museum (main HTML view)
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
- `POST /curate` - Build a room (deep: expansion, candidate pool, model judgments, synthesis)
- `POST /lens` - Split the wall by a topic, streamed (cheap: free scoring, bounded judgments; SSE)
- `POST /exhibits` - Save a room or a lens view as an exhibit
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
- **The wall does not page beyond 120 items.** The API supports `limit` and `offset`, but the museum HTML view does not implement infinite scroll or pagination.
- **No encryption at rest (planned).** The database and blobs are plaintext today. Encryption is a planned milestone.
- **No sync (planned).** One machine only today. Sync is a planned milestone.
- **The default local model (`llama3.1:8b`) is weak.** Roughly three of four rerank judgments fail their validators. Conversations work; rooms are unreliable until you point at a better model.
- **Search is brute-force.** sqlite-vec does exact nearest-neighbour search over the 768-dim embeddings in `enqueue.db`. At this library's scale that is fast (Phase 19 measured p95 21 ms); at a few hundred thousand chunks it will need quantization or an approximate index.
- **No Windows or Linux support.** The desktop shell uses macOS-specific AppKit calls (activation, hiding). The Keychain wrapper is macOS-only.

---

## License

See `LICENSE` in the repo root.
