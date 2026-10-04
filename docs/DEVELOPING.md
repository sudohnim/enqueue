# Developing Enqueue

Building, running, and testing Enqueue from source.
For using the app, see the [manual](MANUAL.md); for the architecture and conventions, see [AGENTS.md](../AGENTS.md).

---

## Prerequisites

`bin/setup` installs and verifies everything below (Rust, uv, Node, and the headless Chromium used for link previews) on a fresh machine, so you normally do not install these by hand - see [Install](#install).
The list is here so you know what it sets up and why.

- **macOS.** The desktop shell uses Tauri with macOS-specific APIs, and the API key store uses the macOS Keychain.
- **Python >= 3.12.** The engine is Python and targets 3.12 exactly (see `.python-version`). `uv` fetches and pins this for you, so no system Python is required.
- **[uv](https://docs.astral.sh/uv/).** All commands in this repo and in the desktop shell go through `uv run`, so it must be on your PATH. The shell looks for it at `/opt/homebrew/bin/uv` or `/usr/local/bin/uv`.
- **[Rust](https://www.rust-lang.org/) >= 1.88 and the [Tauri v2](https://v2.tauri.app/) prerequisites**, to build the desktop window from source. `bin/launch desktop` runs `cargo build` and then launches the binary at `desktop/target/debug/Enqueue`. The dependency tree has a minimum supported Rust of 1.88, so an older toolchain fails the build with `rustc <version> is not supported`; `bin/setup` runs `rustup update stable` to keep you current.
- **[Node.js](https://nodejs.org/)**, only for the JS parse check that `bin/launch` and `bin/verify` run before launching. If `node` is not on the PATH, the check is skipped silently.
- **[Ollama](https://ollama.com/)** running locally, if you want the default AI backend (model: `llama3.1:8b`). Not required for capture, search, or browsing; only for conversations and rooms.

### Extra prerequisites for the Android app

The Android app is optional. You only need these to build and run it; the desktop app and engine do not.

- **[Android Studio](https://developer.android.com/studio)** (or a standalone Android SDK). The build looks for the SDK at `$ANDROID_HOME`, defaulting to `~/Library/Android/sdk`.
- **Android NDK.** Install it through Android Studio's SDK Manager. The build auto-selects the newest one under `$ANDROID_HOME/ndk/*` unless `NDK_HOME` is set.
- **A JDK.** The build defaults `JAVA_HOME` to the JBR that ships with Android Studio (`/Applications/Android Studio.app/Contents/jbr/Contents/Home`).
- **The Tauri CLI and the Android Rust targets:**

  ```bash
  cargo install tauri-cli --version '^2'
  rustup target add aarch64-linux-android armv7-linux-androideabi i686-linux-android x86_64-linux-android
  ```

`bin/setup --android` checks the SDK / NDK / JDK, installs the Tauri CLI, and adds the `aarch64-linux-android` target for you (it does not install Android Studio itself).

The generated Android project is committed at `desktop/gen/android`, so you do not need to run `cargo tauri android init` on a fresh clone.

---

## Install

```bash
git clone <repo-url> enqueue
cd enqueue
bin/setup
```

`bin/setup` makes a fresh machine ready: it installs or updates Rust (to a stable >= the 1.88 the build needs), installs `uv` and pins Python 3.12, and checks for Node.
It is safe to run repeatedly - every step checks first and only acts when something is missing or too old - and it uses no `sudo`.
Add `--android` to also set up the mobile toolchain (`bin/setup --android`).

Then install the Python dependencies:

```bash
uv sync
```

This installs all Python dependencies from `pyproject.toml`, including `fastembed` and `sqlite-vec` for the search index and `crawl4ai` for the optional browser fallback on link previews.
The Chromium that fallback drives is a separate download, which `bin/setup` installs (`python -m playwright install chromium`).

If you want to build the desktop shell:

```bash
cd desktop
cargo build
cd ..
```

That produces `desktop/target/debug/Enqueue`, which `bin/launch desktop` expects.
(`bin/launch desktop` also runs `cargo build` for you, so this manual build is optional.)

---

## Running the desktop app

The easiest way to run everything:

```bash
bin/launch desktop
```

This rebuilds the shell with `cargo build` first (incremental, so it is near-instant when nothing changed, and a compile error stops it rather than launching a stale binary), starts the Python engine (`enq serve`), waits for it to answer on `127.0.0.1:8787`, then launches the Tauri desktop window and brings it to the front.

The script kills any existing `Enqueue` and `enq serve` processes first, so engine and window always come up together.
Engine output is logged to `$TMPDIR/enqueue-app.log` (or `/tmp/enqueue-app.log`).

To run on Android, see [Running on Android](#running-on-android) below.

---

## Running on Android

The Android app is a Tauri v2 mobile build of the same Rust shell that runs the desktop window.
It syncs the desktop library to the phone over an end-to-end-encrypted relay, then reads, captures, and chats offline against the local copy.
It never runs the engine itself; the phone holds a decrypted SQLite copy of the library and calls the configured LLM backend directly.

Make sure the [Android prerequisites](#extra-prerequisites-for-the-android-app) are installed first.

### On a plugged-in phone

Plug in an Android phone with USB debugging enabled, accept the pairing prompt, then:

```bash
bin/launch mobile
```

This builds the debug apk once, installs it on the phone, launches it, and exits - it does not run `cargo tauri android dev` (that watch loop never returns and holds the Gradle lock, which then deadlocks the next build). Re-run the command to push a new build.
An emulator is rejected here on purpose - `bin/launch mobile` means "put it on my real phone."

### On an emulator (headless)

```bash
bin/launch emulator
```

This boots a headless AVD (named `enqueue` by default, override with `ENQUEUE_AVD`), builds a debug apk once, installs it, launches it, and then exits - the emulator keeps running in the background so you can drive it over `adb`.
If the AVD does not exist, the script prints the one-time `avdmanager` command to create it.

### Building the apk by hand

If you just want the debug apk to install yourself:

```bash
cd desktop
export ANDROID_HOME="$HOME/Library/Android/sdk"
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
export NDK_HOME="$(ls -d "$ANDROID_HOME"/ndk/* | sort -V | tail -1)"
cargo tauri android build --debug --target aarch64
```

The apk lands at `desktop/gen/android/app/build/outputs/apk/universal/debug/app-universal-debug.apk`.
Install it with `adb install -r <apk>` and launch with `adb shell am start -n com.sudohnim.enqueue/.MainActivity`.

### Linking the phone to the desktop

The phone starts empty.
To fill it, link it to a running desktop over a relay both can reach (a phone that leaves the house cannot reach a `127.0.0.1` relay, so use a hosted relay - see [Running the sync relay](#running-the-sync-relay) and [sync-relay.md](sync-relay.md)).

1. On the desktop, open the sync panel; it renders a QR that encodes the relay URL, the sync secret, and the encryption key (DEK).
2. In the phone app, scan that QR. The phone stores the credentials in its app-sandboxed config and pulls the library.

After linking, the desktop's LLM settings - backend, model, API key, and any extra headers (like OpenCode's `x-opencode-session`) - propagate to the phone (encrypted end to end), so mobile chat uses the same provider without re-entering anything.
Mobile writes (edit a note, delete, pin, hand-edit or delete a summary line) sync back to the desktop; tagging, annotating, and summary regeneration are deliberately desktop-only (curation is a sit-down job).

---

## Running the engine only

```bash
uv run enq serve
```

This starts the FastAPI/uvicorn server on `127.0.0.1:8787`.
You can then open `http://127.0.0.1:8787/` in a browser to see the home page (the main wall view), or `http://127.0.0.1:8787/capture` for the quick-capture overlay.

The engine binds to `127.0.0.1` only, never to `0.0.0.0`.

---

## Running the sync relay

The sync relay is a standalone service that stores end-to-end encrypted snapshots
and serves them to paired devices. It is a dumb byte store - it cannot decrypt
anything.

```bash
uv run enq relay
```

This starts the relay on `127.0.0.1:8788` with a default data directory of
`./relay-data` and a default Bearer secret of `dev-secret`.

Options:

- `--host` - Bind address (default `127.0.0.1`, use `0.0.0.0` for LAN access)
- `--port` - Port to listen on (default `8788`)
- `--data-dir` - Directory for object storage (default `./relay-data`)
- `--secret` - Bearer secret for authentication (default `dev-secret`)

Environment variables can also be used:

- `RELAY_HOST` - Bind address
- `RELAY_PORT` - Port
- `RELAY_DATA_DIR` - Data directory
- `RELAY_SECRET` - Bearer secret

The relay authenticates all requests with a Bearer token. A wrong secret returns
`401 Unauthorized`.

`enq relay` binds to `127.0.0.1` by default, which only the same Mac can reach (a headless emulator reaches it at `10.0.2.2:8788`).
To sync a phone from anywhere, run the relay on a reachable host: [sync-relay.md](sync-relay.md) covers a Railway deploy (`bin/deploy-relay`) and a cloudflared/ngrok dev tunnel.
The desktop refuses to show a linking QR for a loopback or LAN relay, because a phone that leaves the house could never reach it.

---

## CLI commands

The entry point is `enq`, registered in `pyproject.toml` as `enqueue.cli:app`.
All commands except `serve`, `relay`, `migrate`, `restore`, and `version` are thin HTTP clients over the running engine; if the engine is not running they print an error and exit.

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
| `enq relay` | Run the sync relay locally (default `127.0.0.1:8788`). |
| `enq facet-gate` | Decide which artifacts are eligible for facet generation. |
| `enq index` | Rebuild the search index from the database. |
| `enq doctor` | Index health: artifact/chunk counts, index row counts, embedding version, sync with the chunks table. |
| `enq chunk` | Rebuild text chunks from note bodies. |
| `enq backup` | Back the library up now into the folder chosen in Settings (see [Backups](#backups)). |
| `enq restore <folder or .db>` | Put a backup in place as the library. Quit Enqueue first; the current library is set aside, never deleted. |

Every command takes `--help` for full argument details.

---

## Running tests

```bash
uv run pytest -q
```

Tests live in `tests/` and never touch the network, a model, or your real `~/.enqueue-poc` data: each runs against a temporary database, and model calls are scripted.
`tests/test_md_roundtrip.py` runs the markdown round-trip cases in `tests/js/md_roundtrip.js` under Node (skipped when `node` is missing).
`uv run pytest -q -n auto` runs them in parallel, as CI does.

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

The full gate: Python lint (black, ruff), a JS parse check on every page and script, pytest, the WCAG contrast check, the desktop Rust unit tests when Rust changed, and an Android compile check (a full `cargo tauri android build` when Rust, Kotlin, or the Android project changed).
`bin/verify --fast` runs only the static checks (lint, JS parse, contrast) and is what the pre-commit hook runs (`.githooks/pre-commit`, enabled with `git config core.hooksPath .githooks`).
A green `bin/verify` proves the code parses, the tests pass, and the app compiles; only running it on the desktop or a device proves it works.

---

## Contrast check

```bash
bin/check-contrast
```

Parses the `:root` color tokens from `src/enqueue/static/css/tokens.css` and verifies WCAG contrast ratios (4.5:1 for text, 3.0:1 for strong lines), including against the darkest ground the page drifts to at night.
Exits non-zero if any token fails.

---

## Publishing a release (maintainers)

Cutting a release is on-demand and publishes the Android APK.
Nothing publishes automatically; no push to `main` ever triggers it.

1. Make sure `.github/workflows/release.yml` is on the default branch (the manual trigger only appears once the workflow exists on `main`).
2. On GitHub, go to the **Actions** tab, pick the **release** workflow, and choose **Run workflow**.
3. Enter the version tag to publish under (for example `v0.1.0`) and start it.
4. The runner installs the Android + Rust toolchain, builds the APK, creates the release for that tag if it does not exist, and attaches `enqueue-<tag>-android.apk`.

The build takes roughly five to ten minutes.
The APK is debug-signed, so it installs on any device with "install unknown apps" enabled, but it is not signed with a Play Store key.
To publish a signed release APK instead, set the `RELEASE_KEYSTORE` (base64), `RELEASE_STORE_PASSWORD`, `RELEASE_KEY_PASSWORD`, and `RELEASE_KEY_ALIAS` repository secrets and switch the build to the release variant, as noted in the workflow.

The macOS desktop app is not part of a release yet.
It is distributed as source, because its Python engine is not yet bundled as a standalone binary; see [Known gaps](#known-gaps).

---

## Environment variables

All environment variables use the `ENQ_` prefix and can override `settings.json` at runtime.
The precedence is: environment variable > `settings.json` > built-in default.

| Variable | Default | Purpose |
|---|---|
| `ENQ_LLM_BACKEND` | `ollama` | Which model backend to use. One of: `ollama`, `openrouter`, `opencode-go`. |
| `ENQ_LLM_MODEL` | `llama3.1:8b` | The model for interactive work: chat answers, routing, the search gray-zone judge. |
| `ENQ_SUMMARIZE_MODEL` | (empty) | Optional second model for background summary (facet) generation. When set, facets use it while chat still uses `ENQ_LLM_MODEL`; when empty, both use `ENQ_LLM_MODEL`. Lets a cheap model answer and a capable one summarize (or vice versa). |
| `ENQ_OLLAMA_URL` | `http://127.0.0.1:11434/v1` | URL for the Ollama backend. Also used as `llm_url` in settings. |
| `ENQ_LLM_API_KEY` | `ollama` (placeholder) | API key for non-local backends. Falls back to the macOS Keychain if not set. |
| `ENQ_MODEL_RETRIES` | `3` | Total attempts per structured model call (the first try plus reprompts on a validation failure). `1` is one shot, no reprompt. |
| `ENQ_VECTOR_STORE` | `sqlite-vec` | The search index backend. `sqlite-vec` is the only backend after the cutover. |
| `ENQ_USER_AGENT` | `Enqueue/0.2 (personal link preview; one request per saved link)` | User agent string sent when fetching link previews. |
| `ENQ_HOTKEY` | `Alt+Shift+E` | Global capture hotkey. |
| `ENQ_AUTO_PREVIEW` | `on` | Whether saving a link automatically fetches its preview. |
| `ENQ_PREVIEW_BROWSER` | `off` | Open a link the site refuses to a plain request (or whose page is empty until its scripts run) once more in headless Chromium. |
| `ENQ_BACKUP_DIR` | (empty) | The folder backups go into (a cloud drive's folder). Empty means backups are off. |
| `ENQ_LLM_HEADERS` | (empty) | Extra headers for model calls, one `Name: value` per line. Required for `opencode-go`, which rejects a request without an `x-opencode-session: <uuid>` header (400 `MissingSessionID`). These headers sync to the phone so mobile chat can call the same endpoint. |
| `ENQ_TRASH_DAYS` | `30` | Days before a trashed artifact is permanently destroyed. Minimum 1. |
| `ENQUEUE_REPO` | (detected) | Path to the repo, used by the desktop shell to find `uv run enq serve`. Written to `~/.enqueue-poc/repo` by `bin/launch desktop`. |

Settings are also writable through the API (`PATCH /settings`) and stored in `~/.enqueue-poc/settings.json` with `0600` permissions.
No secret is ever written to that file; the API key lives in the macOS Keychain (via `/usr/bin/security`).

---

## Model backends

The engine speaks the OpenAI-compatible protocol to all backends through a single adapter (`src/enqueue/providers/`).

| Backend | URL | Local? | Needs key? |
| --- | --- | --- | --- |
| `ollama` | `http://127.0.0.1:11434/v1` | Yes | No |
| `openrouter` | `https://openrouter.ai/api/v1` | No | Yes (`ENQ_LLM_API_KEY`) |
| `opencode-go` | `https://opencode.ai/zen/go/v1` | No | Yes (`ENQ_LLM_API_KEY`) |

Anything other than `ollama` sends the text of your artifacts to somebody else's computer.
Artifacts marked `local_only` never go to an outside service, even when one is configured.

`opencode-go` additionally requires an `x-opencode-session: <uuid>` header (set it via `ENQ_LLM_HEADERS`); without it the endpoint returns `400 MissingSessionID`.

**Two models, split by job.** The engine resolves a provider per call site through `get_provider()`: interactive work (chat answers, skill routing, the search gray-zone judge) uses `llm_model`, while background summary (facet) generation uses `summarize_model` when one is set (`get_provider(summarize=True)`), falling back to `llm_model` otherwise. This lets a fast, cheap model handle chat while a stronger, slower one writes the summaries that drive conceptual search - or the reverse. A facet is tagged with the model that wrote it, and search drops facets whose model no longer matches the active summary model, so switching models does not surface stale summaries.

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
| `repo` | One-line pointer to the repo path, written by `bin/launch desktop` so the desktop shell can find the engine. |
| `capture-position` | Last screen position of the capture overlay. |

| `backup.json` | When the last backup ran and where it went. |
| `keyring.json` | The sync key, wrapped under your recovery phrase. |

Your original files are in `blobs/` byte for byte, so they stay readable by other programs even if Enqueue disappears.

## Backups

`src/enqueue/backup.py` backs the library up into a folder a cloud drive syncs (Proton Drive by design, so the copy is end-to-end encrypted off the Mac).
The live library never moves into that folder: a SQLite database in WAL mode is three files written together, and a sync client can upload them mid-write.
Instead, once a day (when something changed), on a clean shutdown, and on demand, the engine writes one consistent copy with `VACUUM INTO` under a temporary name, empties the rebuildable search index in the copy, checks its integrity, and renames it into place.
A 410 MB library backs up as about 6 MB in a couple of seconds; restoring rebuilds the search index on first start (about 20 minutes for that library).
It keeps 7 daily backups and one for each of 4 earlier weeks.

```bash
uv run enq backup                 # back up now
uv run enq restore "<backup folder>"   # engine stopped; sets the current library aside
```

---

## Project layout

```
enqueue/
  bin/            setup, launch, verify, check-contrast, screenshots, deploy-relay, cdp-eval
  desktop/        the Tauri shell (Rust): desktop window + the Android app (gen/android)
  src/enqueue/    the Python engine: api/, ingest/, index/, retrieve/, providers/, sync/, relay/
    static/       the interface: home.html + css/ + js/ (desktop), capture.html, mobile.html
    migrations/   Alembic revisions, applied at startup
  tests/          pytest; tests/js holds the markdown round-trip cases (run under Node)
  docs/           MANUAL.md (using it), DEVELOPING.md (this file), DESIGN.md, sync-relay.md, e2e/
```

The file-by-file map, the data flows, and the invariants are in [AGENTS.md](../AGENTS.md); it is the engineering reference and is kept current with the code.

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
- `POST /chats` - Start a conversation (with `text`) or create an empty one
- `POST /chats/{id}/messages` - Continue a conversation
- `DELETE /chats/{id}` - Soft-delete a conversation (tombstone syncs to other devices)
- `POST /artifacts/{id}/facets/regenerate` - Regenerate the machine-written summary (keeps hand-edited lines)
- `POST /artifacts/{id}/facets` - Add a hand-written summary line
- `PATCH /facets/{id}` - Edit one summary line (marks it `edited`, reindexes)
- `DELETE /facets/{id}` - Remove one summary line
- `GET /events?limit=N` - The activity log, newest first, each with its full record
- `GET /settings` - Read all settings + storage info
- `PATCH /settings` - Update settings
- `GET /backup` / `POST /backup` - Backup status / back up now
- `PUT /settings/api-key` - Store API key in Keychain
- `DELETE /settings/api-key` - Remove API key from Keychain
- `POST /index` - Rebuild the search index
- `POST /reprocess` - Re-ingest everything
- `GET /trash` - List trashed artifacts
- `DELETE /trash/{id}` - Permanently destroy one artifact

---

## Known gaps

- **No bundled `.app` yet.** The desktop shell runs from `desktop/target/debug/Enqueue` and spawns the engine via `uv run enq serve` from the repo. There is no packaged sidecar binary, so the app cannot be distributed as a double-clickable `.app` without the repo and `uv` present.
- **CI runs lint, tests, and an eval gate** (`.github/workflows/ci.yml`); an on-demand workflow builds and publishes the Android APK to a release (`.github/workflows/release.yml`, run manually from the Actions tab). `bin/verify` is the local pre-commit gate.
- **The wall does not page beyond 120 items.** The API supports `limit` and `offset`, but the home HTML view does not implement infinite scroll or pagination.
- **No encryption at rest on the Mac (planned).** The live database and blobs are plaintext on disk (FileVault is what protects them). What leaves the Mac is encrypted: sync snapshots end to end, and backups by the drive you put them in. Items moved to the vault are encrypted at rest under their own PIN.
- **Sync and the Android app are built and device-verified; a hosted relay is deployed.** End-to-end-encrypted sync (per-artifact snapshots, last-writer-wins, a dumb ciphertext relay) and a Tauri Android app exist: link the phone by scanning a QR the desktop shows, and the desktop library syncs to the phone over a hosted relay (a Railway deploy is running; `enq relay` remains the localhost/self-host option, see [sync-relay.md](sync-relay.md)). Mutations now propagate both ways - an edit, delete, or pin on either side reaches the other after sync (the relay object is an upsert, not create-only), and the desktop's LLM settings (backend, model, API key) propagate to the phone end-to-end.
- **The default local model (`llama3.1:8b`) is weak.** Roughly three of four model outputs fail their validators. Conversations work; a better model is needed for reliable chat answers and facet generation.
- **Search is brute-force.** sqlite-vec does exact nearest-neighbour search over the 768-dim embeddings in `enqueue.db`. At this library's scale that is fast (Phase 19 measured p95 21 ms); at a few hundred thousand chunks it will need quantization or an approximate index.
- **No Windows or Linux support.** The desktop shell uses macOS-specific AppKit calls (activation, hiding). The Keychain wrapper is macOS-only.

---
