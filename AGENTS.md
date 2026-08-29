# Enqueue - Agent Instructions

Project-specific instructions for AI coding agents working in Enqueue.
This file is engineering reference: architecture, module map, data flows, conventions, and gotchas.
For product behaviour, see [docs/PRODUCT.md](docs/PRODUCT.md).
For curation schemas and prompts, see [docs/CURATION.md](docs/CURATION.md).
For eval methodology, see [docs/EVAL.md](docs/EVAL.md).
For the current build status and task queue, see [docs/PROGRESS.md](docs/PROGRESS.md).

If you are here to write code, your work queue is [docs/PROGRESS.md](docs/PROGRESS.md).
Do one task per turn, in order, and verify each with the command in its "Done when" before checking the box.

## Resolved decisions

These came up while surveying the code against the old AGENTS.md, then confirmed with Minh.
They are recorded here so the next agent does not re-litigate them.

1. **Encryption at rest (the local DB) is planned, not built.**
The local database `~/.enqueue-poc/enqueue.db` is plain `sqlite3` today; encryption at rest for it is still a planned milestone and no scheme is chosen.
Treat the local store as plaintext and keep secret material out of the search index.
(Distinct from the SYNC payload, which IS end-to-end encrypted - see decision 2. The DEK/keyring crypto in `crypto.py`/`keyring_file.py` protects what goes to the relay, not the DB on disk.)

2. **Sync and E2E are built; the desktop SETUP flow is the missing piece.**
The model is fixed and implemented: `docs/e2e/E2E.md` specifies encrypted per-artifact snapshots with last-writer-wins per artifact (no event log, no logical clock), and a dumb end-to-end-encrypted relay plus SSE push for the mobile client. Do not resurrect the old event-log / multi-peer design; LWW-per-snapshot is the model. SQLite is the source of truth, not a materialised view of a log. (E2E.md predates two renames: use `saved_pivots` for its `exhibits`, and ignore its `lens_judgments`.)
What exists in code:

- Relay: `src/enqueue/relay/app.py` (`create_relay(data_dir, secret=...)`, Bearer-secret auth, stores opaque bytes only). `enq relay` command in `src/enqueue/cli.py` wraps this with uvicorn (flags: `--host`, `--port`, `--data-dir`, `--secret`; env: `RELAY_HOST`, `RELAY_PORT`, `RELAY_DATA_DIR`, `RELAY_SECRET`).
- Engine sync: `sync/client.py` (push/pull, `push_keyring`), `sync/snapshot.py` (LWW read/serialize/apply), `sync/worker.py` (SSE + timer pull), `sync/guard.py` (`SYNC_PLAINTEXT_PROTOTYPE = False`, now allows non-local relays because bytes are encrypted).
- E2E keyring (QR.1, passwordless): `keyring_file.py` writes `keyring.json` with the DEK wrapped ONLY under a recovery-phrase-KEK (the old password-KEK slot is removed - QR.1). The raw DEK persists in the macOS Keychain (`keyring.py`, service `enqueue-sync-dek`) or a mode-0600 file on non-macOS, and auto-loads on startup, so there is no per-launch unlock and no library password in the normal flow. The recovery phrase is recovery-code-only, for total-device-loss. `crypto.py` is the XSalsa20-Poly1305 boundary. NOTE: this is E2E for the SYNC payload; the local `~/.enqueue-poc/enqueue.db` at rest is still plain sqlite (see decision 1).
- Mobile (Rust, `desktop/src/sync.rs` + `lib.rs` mobile module): pulls the encrypted library into a local SQLite copy and decrypts on-device.
**Pairing model = QR-linked, hosted-relay, passwordless (decided 2026-08-16, superseding the earlier "Option A" paste-code+password model, which live SU.5 testing showed was too painful - USB-only relay, lock-on-restart, forgotten-password lockout). Now BUILT and device-verified (2026-08-19).** The model: (1) a HOSTED relay reachable over the internet (not localhost/USB), still storing only opaque ciphertext; (2) the desktop persists the DEK in the macOS Keychain (service `enqueue-sync-dek`) and auto-loads it on launch (no per-launch unlock, no password); (3) device linking is a Signal-style QR - the desktop `desktop_link_code` shows a locally-rendered QR, the phone camera scans it and receives the key in one step; (4) NO library password in the normal flow - the recovery phrase is a recovery-code-only artifact for total-device-loss. The QR carries key material, but it is camera-scanned + ephemeral + locally rendered (the WhatsApp/Signal/Proton device-linking threat model), never pasted, never sent to any external service. The Option A surface (paste-code + `mobile_pairing_setup` + the SU.7 `keyring-unlock` flow) is superseded - do not extend it.
**QR wire format (pinned - both sides parse exactly this):** compact UTF-8 JSON `{"v":1,"relay_url":"https://...","relay_secret":"...","dek":"<base64>"}`, where `dek` is RFC 4648 base64 (with padding) of the raw 32-byte DEK, and `v` is the format version (a parser seeing any other `v` refuses with a clear message). CAMERA-ONLY: there is no copyable/pasteable form of the payload anywhere, by decision - the raw DEK must never touch the clipboard or clipboard history. A Rust round-trip test (`rqrr` decode) pins the format.
**DEK-encoding gotcha (bit us on 2026-08-19):** the macOS Keychain stores `enqueue-sync-dek` ALREADY base64-encoded (44 chars = 32 raw bytes), so `desktop_link_code`/`load_link_credentials` must pass it into the QR VERBATIM. Re-encoding double-encodes it (the phone then base64-decodes to 44 bytes, not 32); `mobile_link_qr` must ERROR on a non-32-byte DEK, never silently zero it (a zero DEK links "successfully" but fails every decrypt).
**Known deviation (MOB.3b):** the mobile DEK/secret is stored in an app-sandboxed file at mode 0600 (`sync_config` in the app data dir, DEK as hex), NOT the Android Keystore - Tauri v2 exposes no Keystore JNI API. Documented honestly; not hardware-backed.
**What remains open (see `docs/PLAN.md`):** the code is built and the sync/decrypt/apply/render path is device-verified end to end; the open items are the hosted-relay deploy (Railway, RELAYHOST.1), the scanner camera-box containment (SCANUI.1), the cold-launch bootstrap race (MOBBOOT.1), the CAP2.2 capture-flight over-app pivot, and a handful of pending human device-verifies on already-committed work.

1. **The data directory is `~/.enqueue-poc` on purpose.**
The `-poc` suffix is intentional for the current phase.
Do not rename it without an explicit migration of user data.

2. **`instructor.Mode.JSON` is used for every adapter.**
All providers pass `mode=instructor.Mode.JSON` unconditionally.
This is correct for now, not a bug to fix.
Ollama's adapter calls it out in a comment because the default is `TOOLS`, which needs function-calling support that local servers often lack.

3. **Facet trust is a fixed multiplier, not a learning loop.**
`facets.trust` defaults to 0.5, is read in `retrieve/candidates.py` as `score * trust * 2.0`, and is never written after creation.
A trust-update mechanism (promote on save, demote on eject) is a planned feature, not an implemented one.
For now, trust is a flat constant and every facet contributes equally after the 0.5 weighting.

4. **There is no Lumo. The cloud backend is OpenRouter.**
The old docs name Proton's Lumo as a backend; it does not exist in the code.
The configured backends are `ollama` (default, local), `openrouter`, and `opencode-go` (OpenCode Go subscription, `https://opencode.ai/zen/go/v1`). The old `opencode` (Zen) and `custom` backends were removed; a stored `opencode` config migrates to `opencode-go`. Only Go chat-completions models work (the adapter speaks `/chat/completions` only; `/responses` and `/messages` models are refused with a clear message - see `config.py` GO_* sets and `providers/base.py`). Treat OpenRouter as the general cloud path. Remove any Lumo reference you find.

5. **crawl4ai may be added later.**
The old docs reference crawl4ai, marker, and whisper.cpp; none are in `pyproject.toml`.
crawl4ai may return for better link capture.
marker and whisper.cpp are not currently planned.
PDF parsing uses only pymupdf (fitz).

6. **API version string and package version are two different things.**
`pyproject.toml version = "0.1.0"` is the package release version.
`api.py FastAPI(version="0.2.0")` is just the string the OpenAPI docs page shows.
They are allowed to differ.
If you bump one for a release, bump the other to match, but a mismatch is not a bug.

7. **There is one view concept: the saved pivot.**
The `exhibits` / `exhibit_members` tables and the `/exhibits*` endpoints that an earlier agent introduced to paper over the L.2 add-to-grouping bug are removed.
`saved_pivots` and `/pivots*` carry the same concept with a re-runnable spec.
The wall has no ephemeral view surface; only a saved pivot persists a view.

8. **The SSE lens surface and curate are removed.**
`POST /lens` (Server-Sent Events), `POST /curate`, and the lens-cache endpoints were deleted in Phase M, along with the retrieve modules that powered them (`retrieve/expand.py`, `retrieve/rerank.py`, `retrieve/score.py`, `retrieve/lens.py`, `retrieve/judgments.py`, `retrieve/curate.py`), the lens settings, and the `lens_judgments` table (migration 0020).
Search is the retrieval path; the assistant organises material into views through `POST /pivot/plan` and `POST /pivot/run`.
Do not add SSE plumbing back unless asked.

9. **The browser extension is a future milestone; Android is in progress.**
No browser extension code exists; document it as future, do not build against it.
The Android app (Tauri v2 mobile, `desktop/gen/android`, crate builds as `enqueue_lib`) is built: it syncs the encrypted library through the relay into a local SQLite copy, captures, reads, writes (note edits, annotations, tags, pins, trash/restore), and chats by calling the configured LLM backend directly with keyword-only (FTS) grounding.
It never computes embeddings, facets, or entities; enrichment stays desktop-only. AI-derived data that has not synced down is absent quietly - never a placeholder or a fabricated summary.
Mobile UI lives in `src/enqueue/static/mobile.html` (relative asset paths). Layout: a single-column list under SAVED / EVERYTHING ELSE shelf headers, newest first; rows open a read-only Reader (note markdown, image with pinch-zoom, link preview card, PDF via vendored pdf.js); a bottom pill (capture in `--purple-bold`, search, the living raven eye for ask, menu). The capture "raven moment" is the ANIM.4 flight, or a fade under reduced motion.
Build/run the app with `bin/launch mobile` (physical phone only). What remains open is the desktop sync-setup flow (decision 2) and any items in the current `docs/PLAN.md`.
Sync/mobile scope boundaries (durable): one person, one library - no multi-user or shared libraries. Android-first; iOS is a follow-on. The relay is additive - with sync off, nothing about the desktop changes. `saved_pivots` (saved views) and chats do NOT cross the relay; mobile reads artifacts only, and mobile chat histories are device-local by decision.
Mobile linking is passwordless (QR.1/QRSYNC): the phone receives the DEK by camera-scanning the desktop QR and persists it in its sandboxed `sync_config`; there is deliberately NO password and NO recovery-phrase unlock path on the phone. The desktop is the single source of truth and the recovery anchor: lose the phone and you simply re-scan the desktop QR. Do not add a mobile password or recovery-phrase fallback.

10. **The user-facing concept is "view", not "grouping".**
We use the word "view" for the user-facing concept that was previously called "grouping", "saved grouping", and "collection".
The persistence layer keeps its names (`saved_pivots`, `pivots_saved`, `_PlannedSpec`, `/pivots*` endpoints).
Only user-facing strings and docs say "view".
This is a vocabulary pass, not a table rename.

---

## General Guidelines

- Never use the em dash. Use plain dash instead.
- When writing commit messages, never auto-add your agent name as co-author.
- Never manually modify CHANGELOG.md files or any files marked as auto-generated.
- When writing or substantially editing long Markdown files, put each full sentence on its own line.
- When making technical decisions, prefer quality, simplicity, robustness, scalability, and long-term maintainability over development cost.
- When doing bug fixes, always start by reproducing the bug in an end-to-end setting as closely aligned with how an end user would hit it.
- Be picky about the UI. If something looks off, even if unrelated to the current task, get it fixed.
- Engineering excellence: lint, test failures, and test flakiness must be fixed even if not caused by the current work.
- Python formatting is black, line-length 100. Non-negotiable.

---

## Architecture

### Shape

A local Python engine on macOS, with a Tauri desktop shell.

```
Tauri shell (desktop/)          native window, global hotkey, capture overlay
    |
    | localhost HTTP (127.0.0.1:8787)
    v
Engine (src/enqueue/)           FastAPI + background ingest worker, one process
    |
    +-- SQLite (~/.enqueue-poc/enqueue.db)    artifacts, text, chats
    +-- SQLite search index (vec0 + FTS5 tables inside enqueue.db)  vectors + text + ids
    +-- Blobs (~/.enqueue-poc/blobs/)         original files, content-addressed
```

Everything binds to loopback.
Nothing listens on a network interface.
The engine serves HTTP and drains the ingest queue in the same process.
No broker, no Redis, no second container.

### Processes on one machine

| Process | What it is | Bound to |
| --- | --- | --- |
| `enqueue-desktop` | Tauri shell. Native window, global hotkey, tray. | nothing |
| `enq serve` | Python engine. FastAPI plus a background worker. | `127.0.0.1:8787` |
| sqlite-vec | search index inside the SQLite file | embedded in engine |
| Ollama | local LLM backend (default) | `127.0.0.1:11434` |

The search index is sqlite-vec, living inside the SQLite file as vec0 + FTS5 tables.
There is no separate store directory, no sidecar, and no single-process directory lock.
Search is exact (brute-force) rather than approximate.

### Why Python

Every library that does the hard parts is Python: pymupdf for documents, instructor for structured output, fastembed for embeddings.

The engine sits behind a narrow localhost API.
Clients never know what language is behind it, which keeps a future port open.

### Desktop shell (Tauri)

The Tauri shell owns the window, the menu bar, the global hotkey, and the lifetime of the engine process.
Nothing about the app lives in the shell.
It speaks to localhost and does not know what language is behind it.

The shell spawns the engine via `uv run enq serve` from the repo directory.
A bundled .app would use a sidecar binary, but that packaging is unresolved.

Two windows:

- **main** - the home window (the wall), loaded from `http://127.0.0.1:8787/`
- **capture** - the quick-capture overlay, loaded from `http://127.0.0.1:8787/capture`

The capture overlay is a transparent, undecorated, always-on-top window summoned by a global hotkey (default `Alt+Shift+E`).
It is built once at startup and then only shown and hidden, so there is no webview boot between the keypress and the caret.
In the overlay, a plain Enter saves (the same path as the Keep button), Shift+Enter inserts a newline, and Escape dismisses without discarding the draft (CAP2.1).
On a successful capture the raven flight plays INSIDE the capture overlay, then it dismisses (CAP2.2). A separate always-on-top flight window was tried and abandoned: a background app's window cannot reliably float above the frontmost app on macOS (`NSFloatingWindowLevel` is not enough, and Tauri's `.show()`/`.set_focus()` steals focus), but the capture overlay is already summoned over whatever app the person was in, so playing the flight there needs no window-level hacks.

The shell uses `macOSPrivateApi: true` for the transparent capture window.
This is an App Review exposure to be aware of if the app is ever submitted to the App Store.

---

## Module map

One line per file, describing its job.

### Core

| File | Job |
| --- | --- |
| `cli.py` | Thin Typer CLI over the engine API. Every command calls `httpx` against localhost. |
| `api/` | FastAPI app split into one router per domain (M.9): `static.py` (shell, capture, health), `artifacts.py` (wall, artifact, tags, capture writes), `wall.py` (shared wall-shaping helpers), `write.py` (re-chunk, facets, index rebuild), `admin.py` (doctor, index counts, ingest wait), `search.py`, `chats.py`, `settings.py`, `pivots.py`. `app.py` has `create_app()` + `serve()` and binds 127.0.0.1:8787. |
| `config.py` | Constants: paths, model names, backends, env overrides. No logic. |
| `settings.py` | Three-layer settings (env > settings.json > default). Writable fields, storage report. |
| `db.py` | SQLite access + Alembic migration at startup. `get_conn()`, `transaction()`, `count()`. |
| `greeting.py` | The wall's greeting: one model phrase per four-hour bucket, generated in the background. |
| `schemas.py` | Pydantic models for every model call. Validators are the quality floor. |
| `prompts.py` | System prompts. Authoritative copies are in docs/CURATION.md. |
| `keyring.py` | macOS Keychain for the API key. `/usr/bin/security`. No-op on non-macOS. |
| `capture.py` | Captures: links, file uploads. Content-addressed dedupe. PDF text extraction and page rendering. |
| `notes.py` | Notes: create, edit (versioned), annotate. Secret scanning before model calls. |
| `preview.py` | Link previews: one opt-in fetch, parse og:meta, download image locally. |
| `chats.py` | Conversations: scoped retrieval, grounded answers, topics, titles. |
| `trash.py` | Soft delete with retention window. Purge is the only destructive operation. |

### Ingest

| File | Job |
| --- | --- |
| `ingest/queue.py` | In-memory work queue. One daemon thread. `submit()` returns immediately. A vision describe failure marks the image `status='failed'` and surfaces in `/doctor` (`images_without_body`) instead of failing silently. |
| `ingest/chunk.py` | Markdown chunker. Headings, lists, code fences kept whole. Prose merged to a floor. Chunk source includes the artifact's current annotation text; a bodyless capture falls back to its title + filename so it always has at least one chunk. |
| `ingest/facets.py` | Facet generation via provider. Eligibility gate. Proper noun extraction. |
| `ingest/secrets.py` | Credential pattern scanner. Runs before any text reaches a model. |

### Retrieve

| File | Job |
| --- | --- |
| `retrieve/candidates.py` | `/search` rollup: dense + FTS5 keyword fused with RRF, plus trigram substring recall, a fuzzy short-field branch (titles, entities, annotations), and exact quoted-phrase pinning. One row per artifact. |

### Index

| File | Job |
| --- | --- |
| `index/embed.py` | Local embeddings via fastembed. Dense (BAAI/bge-base-en-v1.5, 768d). |
| `index/store.py` | `VectorStore` interface + `get_store()` factory. One instance per process. |
| `index/store_sqlite.py` | sqlite-vec backend: vec0 + FTS5 tables (unicode61 keyword + trigram substring), hybrid search fused with RRF. |
| `index/fusion.py` | Reciprocal rank fusion as a pure function. |
| `index/bootstrap.py` | Startup index build (no manual step) + cutover cleanup. |

### Providers

| File | Job |
| --- | --- |
| `providers/base.py` | `Provider` protocol, `get_provider()`, error translation to sentences. |
| `providers/ollama.py` | `OpenAICompatibleProvider`. One adapter for all OpenAI-protocol endpoints. |

### Migrations

| File | Job |
| --- | --- |
| `migrations/env.py` | Alembic env. Reads DB path from `enqueue.config`. |
| `migrations/versions/0001_baseline.py` | Core tables: artifacts, versions, annotations, chunks, facets. |
| `migrations/versions/0002_link_previews.py` | link_previews table. |
| `migrations/versions/0003_chats.py` | chats, chat_messages, chat_citations, chat_topics. |
| `migrations/versions/0004_pinned_chats.py` | chats.pinned column. |
| `migrations/versions/0005_pinned_artifacts.py` | artifacts.pinned, page_text table. |
| `migrations/versions/0006_trash.py` | artifacts.deleted_at. |
| `migrations/versions/0007_preview_images.py` | link_previews.image_hash, image_mime. |
| `migrations/versions/0008_page_count.py` | artifacts.pages (PDF page count, cached). |
| `migrations/versions/0019_drop_exhibits.py` | Drops the exhibits and exhibit_members tables; chat scope_kind CHECK rewritten without 'exhibit' (exhibit-scoped rows become everything-scoped). |

### Desktop

| File | Job |
| --- | --- |
| `desktop/src/main.rs` | Tauri shell: window creation, hotkey, engine lifecycle, capture overlay, AppKit calls. |
| `desktop/src/lib.rs` | The crate library (`enqueue_lib`). Holds the desktop commands + `#[cfg(target_os="macos")] mod appkit` AND the `#[cfg(mobile)] mod mobile` Tauri commands (link/sync/capture/list/outbox). Both shells load this. |
| `desktop/src/sync.rs` | Pure-Rust mobile sync: relay pull/apply + the E2E crypto (XSalsa20-Poly1305 secretbox, Argon2id KEK), cross-compiled for Android. |
| `desktop/build.rs` | Registers Tauri commands for the ACL. |
| `desktop/tauri.conf.json` | App config, capabilities, CSP, bundle settings. |
| `desktop/Cargo.toml` | Rust dependencies: tauri 2, global-shortcut plugin, serde_json, the sync/crypto crates, `tauri-plugin-barcode-scanner`, `rqrr` (QR round-trip test). |
| `desktop/plugins/tauri-plugin-barcode-scanner/` | Vendored ML Kit QR scanner (renders CameraX behind the transparent WebView). |

### Bin

| File | Job |
| --- | --- |
| `bin/verify` | JS parse on the HTML pages, pytest, contrast check, and an Android build check (auto-detects the NDK; runs a full `cargo tauri android build` when Rust/Kotlin/`gen/android` changed, else `cargo check --lib`). Gated on every code commit by `.githooks/pre-commit`. |
| `bin/check-contrast` | WCAG contrast check on home.html palette tokens. |
| `bin/launch desktop` | Rebuild shell, kill engine + shell, launch, wait for health, bring to front. |
| `bin/launch mobile` | Build + install + run on a plugged-in Android phone (emulator rejected). |

### Static

| File | Job |
| --- | --- |
| `static/home.html` | The home shell: meta, font preloads, the `#topbar`/`#view`/`#pill`/`#dropover` skeleton, ordered `<link>` to `css/*.css` and `<script src="/static/js/...">` tags. Split from the old single-file museum.html in M.8: one global scope, no build step, no ES modules. |
| `static/css/` | The home interface stylesheets, split by surface (M.8): `tokens.css` (palette), `base.css` (type/buttons/callouts/rows), `home.css` (topbar/searchbar/homehead/eye/wall/cards/groupbar/tagbar), `artifact.css` (artifact+drawer+editor+docpane), `reader.css` (reader+findbox+folio), `chat.css` (transcript), `settings.css`, `pill.css` (pill+menu+toast+dialog+dropover+animations). |
| `static/js/` | The home interface JS, split by surface (M.8). Load order: `util`, `icons`, `md`, `dialogs`, `pill`, `morph`, `home`, `artifact`, `search`, `pivot`, `chat`, `trash`, `settings`, with the boot call last. One global scope; no ES modules. |
| `static/capture.html` | The capture overlay. Separate page with its own token copy. |
| `static/fonts/` | IBM Plex Sans woff2/ttf, served locally. No CDN. |

---

## Key data flows

### Capture -> ingest -> index

1. **Capture** (`capture.py` or `notes.py`): create an artifact row, write blob if applicable, return immediately.
2. **Queue** (`ingest/queue.py`): `submit(artifact_id)` puts it on an in-memory queue. Returns before processing.
3. **Worker thread**: for links, optionally fetch preview; for PDFs, extract text via pymupdf; chunk the text; index into the sqlite-vec store. An image whose vision describe fails is marked `status='failed'` and surfaced in `/doctor` rather than failing silently.
4. **Chunk** (`ingest/chunk.py`): markdown-aware splitting. Headings, lists, code fences are coherent units. Loose prose merged to a floor of 120 words. Long chunks split at 380 words with 60-word overlap. The chunk source includes the artifact's current annotation text (superseded annotations excluded), and a bodyless capture falls back to its title + filename so every artifact has at least one chunk.
5. **Index** (`index/store_sqlite.py`): embed chunks (dense), upsert into `vec_chunks`, `fts_chunks`, and the trigram `fts_chunks_tri`. Title prepended for indexing only. Writing an annotation re-queues the artifact so its new text is searchable.

### Facet generation

1. **Eligibility gate** (`ingest/facets.py`): `apply_eligibility_gate()` marks artifacts that should not get facets (too short, not a note, text_only status).
2. **Generate** (`ingest/facets.py`): `generate_all()` iterates eligible artifacts, calls provider with `FACET_GENERATION` prompt, stores facets with trust=0.5.
3. **Index** (`index/store_sqlite.py`): `upsert_facets()` embeds facet statements, upserts into `vec_facets` and `fts_facets`.

### Curate and the lens view (removed)

The SSE lens surface (`POST /lens`), the curate flow (`POST /curate`), and the
modules that powered them were deleted in Phase M. The wall has no ephemeral
split or room surface: `/search` is the retrieval path, and a saved pivot is
the only persistent view. What survives from that era is the conceptual layer -
facets still give search a conceptual channel - and the assistant path that
organises material into views through `POST /pivot/plan` and `POST /pivot/run`.

### Chat

1. **Passages** (`chats.py`): retrieve chunks for the question. Scoped chats (artifact) do not search. Everything scope uses hybrid search on chunks + facet hits (dense + FTS5 keyword + the trigram recall net).
2. **Answer** (`chats.py`): model answers from passages. `Answer` schema enforces grounded/cited consistency. The passage header MUST carry the artifact id (`[kind] (id: <id>) title`, `chats.py::_ask_model`): the `Answer` validator rejects any cited id it was not offered, so if the model only sees the title it cites the title and the turn fails validation as "cited artifacts that were not provided" (CHATBUG.1).
3. **Title + topics** (`chats.py`): best-effort, non-blocking. Topics regenerated from whole transcript each turn.

Structured-output gotchas (CHATBUG.1, 2026-08-20): `config.MODEL_RETRIES` is instructor's `max_retries` = TOTAL attempts, not retries-after-first; it defaults to 3, because a thinking model (e.g. opencode-go `deepseek-v4-pro`) answers in prose on the first try and needs a reprompt to emit the schema, and reprompts only fire on a validation failure so the happy path costs nothing. Do NOT switch instructor mode to fix a schema failure: opencode-go rejects `Mode.TOOLS`/`TOOLS_STRICT`/`JSON_SCHEMA` ("Thinking mode does not support tool_choice", "response_format unavailable"); `Mode.JSON` (or `MD_JSON`) is the only mode it accepts, and it works once the retries and the passage-id are right.

### Sync (relay, E2E, device linking)

The desktop engine and the Android app share one E2E model: per-artifact snapshots, last-writer-wins, pushed as opaque ciphertext to a dumb relay, pulled and decrypted on-device.

- **Engine side (Python):** `sync/client.py` (`push_artifact` on every write, `push_all()` for an initial full-library backfill), `sync/snapshot.py` (LWW serialize/apply), `sync/worker.py` (SSE + timer pull). Every desktop write path (`notes.py`, `capture.py`, `trash.py` delete/restore, `api/artifacts.py` pin/tag/annotate) calls `push_artifact(id)`. Purge is local-only and final (no row left to snapshot).
- **KNOWN LIMITATION - the relay is IMMUTABLE BY OBJECT NAME, so mutations to already-synced artifacts do NOT propagate (delete, edit, pin, tag, restore).** `relay/app.py::put_object` raises `ObjectConflict -> 409 "object already exists"`, and the object name is id-based with no version (`sync/client.py` `dev/{device}/artifacts/{id}.enc`, mirrored in `desktop/src/sync.rs`). An artifact is pushed ONCE on create; a later `push_artifact` for the same id PUTs the same name, the relay 409s, and the updated snapshot is silently refused. The pull's LWW-by-`(updated_at, device_id)` is therefore moot for updates - a newer snapshot never lands. Backfill relies on this 409 as a cheap "already present, skip." Fixing mutation-sync (make the object mutable / versioned names + advance the pull cursor on rewrite) is open work in `docs/PLAN.md` MOBFIX.5. Until then, treat sync as create-only for the mobile client.
- **Mobile side (Rust):** `desktop/src/sync.rs` reimplements the same crypto (XSalsa20-Poly1305 secretbox: nonce(24)||ct||tag; Argon2id KEK) and the relay pull/apply, so it cross-compiles for Android. `desktop/src/lib.rs` `#[cfg(mobile)] mod mobile` holds the Tauri commands: `mobile_link_qr` (persists relay_url + secret + DEK-as-hex - plus the desktop's llm config: backend/model/api_key/url - via `save_config` into the app-data `sync_config` file, so mobile Settings shows AI config read-only "as of linking"; the desktop is the source and there is no live AI-config sync, MOBILEUI.5), `mobile_sync` (spawns `sync_library` on a background thread, emits `sync-started`/`sync-progress`/`sync-done`/`sync-error`; falls back to the saved config when called with `config:"{}"`), `mobile_status`, `mobile_list`, `mobile_capture`/`mobile_capture_image` (write locally + `push_snapshot`), and `mobile_outbox_push` (drains `capture_outbox` + `mutation_outbox`), `mobile_delete`/`mobile_restore` (enqueue a mutation).
- **Camera / QR scanner:** `tauri-plugin-barcode-scanner` (ML Kit on Android), vendored under `desktop/plugins/`. It renders the CameraX preview BEHIND a transparent WebView, so the scan handler in `mobile.html` makes the page transparent while scanning. `getUserMedia` is a dead end here: the wry Android WebView does not composite a MediaStream to a `<video>` element - do NOT try to bring it back.
- **Resilience + reachability:** an Android foreground service (not WorkManager) keeps a sync alive under screen-lock and backgrounding, started when a sync begins and stopped at caught-up cursor; sync re-triggers on app resume and network-regained. `desktop_link_code` REFUSES to render a QR for a loopback/127.0.0.1/localhost/LAN-private relay URL (a phone that leaves the house could never reach it) - set a hosted URL first. A transient sync failure must show a cached library + an offline banner, NEVER the setup screen (the phone stays linked; the config persists), and the `sync-error` handler must not `alert()`.
- **Gotcha (bit us 2026-08-19):** a null `getElementById(...).addEventListener` in `mobile.html` throws at init and aborts the WHOLE inline script, so the on-load `bootstrap()`/sync never runs and the library just spins. Guard every listener wiring with `?.` when the element may have been removed.

---

## Database schema

SQLite at `~/.enqueue-poc/enqueue.db`.
WAL mode, foreign keys on.
Migrations run automatically at startup via Alembic.

### Tables

| Table | Purpose | Notes |
| --- | --- | --- |
| `artifacts` | the primary model | `kind` is note/link/pdf/image/file. `content_hash` UNIQUE for dedupe. Captures have `body IS NULL` (CHECK constraint). Notes have editable body. |
| `artifact_versions` | every saved state of a note's body | append-only, before each update |
| `annotations` | commentary on a captured artifact | append-only, superseding by id |
| `chunks` | literal layer for search | text, ordinal, chunker name |
| `facets` | conceptual layer for search | level 0-4, statement, model_version, trust (default 0.5) |
| `facet_skips` | artifacts excluded from facet generation | reason: too_short/kind/text_only |
| `secret_hits` | credential patterns found in artifact text | redacted excerpts only |
| `page_text` | extracted text per PDF page | derived, rebuildable |
| `link_previews` | what a saved link turns out to be | status, title, description, site_name, image_hash |
| `chats` | conversations | scoped to everything/artifact. pinned. |
| `chat_messages` | one turn | append-only. grounded flag. |
| `chat_citations` | what an answer was built from | message to artifact, ranked |
| `chat_topics` | concepts a conversation circles | derived, regenerable |

### Invariants

These are enforced by the schema or by code, and breaking them breaks the product.

1. **The index holds ids, embeddings, and search text, all in the one SQLite file.**
The vec0 tables carry id + embedding; the FTS5 tables carry the text they index.
Unlike the old Qdrant directory there is no second unencrypted store to leak: the
index lives inside `enqueue.db`, the same file as the library. Text is fetched by id
after retrieval.
2. **A capture's body is NULL.** Enforced by a CHECK constraint: `kind = 'note' OR body IS NULL`. Captures are frozen because fidelity to the source is why they were saved.
3. **No user-authored text is ever destroyed.** Editing a note appends to `artifact_versions` before updating `artifacts.body`. Annotations are append-only. Purge is the only destructive operation, and only on trashed artifacts.
4. **Every vector is stamped with its embedding model version.** A model change means re-embedding, and stamping makes that incremental.
5. **Derived rows carry the model or tool version that produced them.** Anything derived can be regenerated.
6. **Schema changes are Alembic revisions.** Never a `CREATE TABLE` in application code, never a hand edit. A pre-migration database is stamped at baseline and upgraded, never rebuilt.
7. **An answer states whether it is grounded, and the citations must back it.** Enforced in `schemas.Answer`.

### Index tables

| Table | What it holds |
| --- | --- |
| `vec_chunks` / `vec_facets` | sqlite-vec (vec0) tables: id + 768-dim embedding |
| `fts_chunks` / `fts_facets` | FTS5 tables: the indexed text, with the id as an unindexed reference |
| `fts_chunks_tri` | FTS5 trigram table over chunk text: substring matches unicode61 cannot see ("hopper" inside "chopper") |
| `index_meta` | key/value: the embedding version the index was built at |

Search runs dense + keyword branches and fuses with Reciprocal Rank Fusion (RRF). The trigram table
is a recall net that only adds hits the hybrid missed. Sparse matters because
dense embeddings blur proper nouns: "Find that thing from Epictetus" is a proper noun,
and FTS5 BM25 nails it while dense does not.

### Migration story

Migrations are additive-only for sacred tables (artifacts, versions, annotations).
Derived tables (chunks, facets, page_text, etc.) can be dropped and rebuilt.
A database that predates Alembic (created by the old `schema.sql`) is stamped at baseline (`0001`) rather than replayed.
`db.migrate()` is safe to call repeatedly.
`db.reset_migration_state()` exists for tests that repoint `config.DB_PATH`.

---

## Config and settings

### Three layers (falling precedence)

1. **Environment variable** - explicit intent, always wins, locks the field in the UI.
2. **settings.json** (`~/.enqueue-poc/settings.json`) - what was chosen in the interface. Plaintext, chmod 0600.
3. **config.py default** - the built-in default.

### Key config values

| Variable | Default | What it controls |
| --- | --- | --- |
| `ENQ_LLM_BACKEND` | `ollama` | Which backend to use: ollama, openrouter, opencode, custom |
| `ENQ_LLM_MODEL` | `llama3.1:8b` | The model id (placeholder, known to be bad at structured output) |
| `ENQ_OLLAMA_URL` | `http://127.0.0.1:11434/v1` | LLM endpoint URL |
| `ENQ_LLM_API_KEY` | `ollama` (ignored by Ollama) | API key for hosted backends |
| `ENQ_VECTOR_STORE` | `sqlite-vec` | The search index backend. `sqlite-vec` is the only backend after the cutover. |
| `ENQ_MODEL_RETRIES` | `1` | Retries after first attempt (1 = two tries) |
| `ENQ_USER_AGENT` | `Enqueue/0.2 (...)` | User agent for preview fetches |
| `ENQ_HOTKEY` | `Alt+Shift+E` | Global capture hotkey |
| `ENQ_AUTO_PREVIEW` | `on` | Whether saving a link auto-fetches a preview |
| `ENQ_TRASH_DAYS` | `30` | Trash retention window in days |
| `ENQ_SEARCH_RERANK` | off | Opt-in cross-encoder rerank of the top fused search candidates (R.9). Off by default; measured net-neutral on the golden set. |

### Where secrets live

The API key goes in the macOS Keychain via `/usr/bin/security`, never in settings.json.
`keyring.py` handles this.
On non-macOS, `keyring.available()` returns false and the key must come from the environment.
The key is resolved per-call (not at import) so a key stored in Settings takes effect immediately.

### Backends

| Name | URL | Local | Needs key |
| --- | --- | --- | --- |
| ollama | `http://127.0.0.1:11434/v1` | yes | no |
| openrouter | `https://openrouter.ai/api/v1` | no | yes |
| opencode | `https://opencode.ai/zen/v1` | no | yes |
| opencode-go | `https://opencode.ai/zen/go/v1` | no | yes |
| custom | (user-set) | no | yes |

All backends speak the OpenAI-compatible protocol.
One adapter (`OpenAICompatibleProvider`) covers all of them.

### Important: 127.0.0.1, never localhost

`config.py` binds to `127.0.0.1`, not `localhost`.
This machine may run a second Ollama in Docker bound to the IPv6 wildcard, and `localhost` resolves to IPv6 first.
This applies to both the engine and the Ollama URL.

---

## Provider layer

One narrow interface, one adapter.

```python
class Provider(Protocol):
    name: str
    model: str
    def complete(self, system, user, response_model, context=None, max_retries=None) -> T: ...
```

`get_provider(local_only=False)` returns the configured provider.
Local-only artifacts always route to ollama, regardless of the configured backend.
This is the one rule that is not a preference: marking something local-only is a promise that its text never leaves the machine.

The adapter uses `instructor.Mode.JSON` for all endpoints.
The old AGENTS.md specified different modes per adapter, but the code does not.
See the questions section above.

All model-call failures are caught in `OpenAICompatibleProvider.complete()` and translated to a `ProviderError` carrying one human-readable sentence.
The translation walks the exception chain to find the most specific OpenAI exception type, because the useful exception is often below the one that was caught.

### Which stage runs where

| Stage | Backend | Why |
| --- | --- | --- |
| Embeddings | always local (fastembed) | No network, strictly more private |
| Facet generation | the configured backend | The moat. Bad facets are permanent pollution. |
| Rerank | the configured backend | Low volume, high value |
| Synthesis | the configured backend | The room: through-line, tensions, view sections (internally grouped) |
| Chat answer | the configured backend | |
| Chat title/topics | the configured backend | Best-effort, non-blocking |

---

## CLI surface

`enq` is the entry point (`pyproject.toml`: `enq = "enqueue.cli:app"`).

| Command | What it does |
| --- | --- |
| `enq serve` | Run the engine on 127.0.0.1:8787 |
| `enq version` | Print package version |
| `enq health` | Engine status and row counts |
| `enq migrate` | Bring the database to head (engine does this at startup too) |
| `enq facets [--limit N] [--redo]` | Generate facets for eligible artifacts |
| `enq index` | Rebuild the search index from the database |
| `enq doctor` | Index health: counts, embedding version, sync with the chunks table |
| `enq search <query> [--limit N]` | Hybrid search, no model calls |
| `enq note [--body TEXT]` | Write a note |
| `enq link <url>` | Save a URL (nothing is fetched) |
| `enq artifacts [--limit N]` | List artifacts, newest first |
| `enq preview <artifact_id>` | Fetch what a saved link is |
| `enq chat <question> [--chat-id ID]` | Ask the collection something |
| `enq chats [--limit N]` | List conversations |
| `enq chunk` | Rebuild chunks from note bodies |
| `enq facet-gate` | Decide which artifacts never get facets |

The CLI never touches the database directly.
Every command calls `httpx` against `http://127.0.0.1:8787`.
If the engine is not running, it says so rather than reaching around the boundary.

---

## API surface

All endpoints on `127.0.0.1:8787`.

### Read

```
GET    /                            home HTML
GET    /capture                     capture overlay HTML
GET    /health                      status + row counts
GET    /greeting                    the wall's greeting for the current four-hour bucket (cached or fallback)
GET    /artifacts                   list, newest first. ?limit&offset&order&pinned
GET    /artifacts/{id}              detail, body, annotations, facets, versions
GET    /artifacts/{id}/text         readable text, with page numbers for PDFs
GET    /artifacts/{id}/blob         original bytes
GET    /artifacts/{id}/versions/{vid}  one saved body
GET    /artifacts/{id}/find?q=      phrase locations in a PDF (page fractions)
GET    /artifacts/{id}/preview-image  link's stored picture
GET    /artifacts/{id}/page/{n}     rendered PNG of a PDF page
GET    /search?q=                   hybrid search, no model calls
GET    /chats                       conversations, pinned first
GET    /chats/ready                 whether there is anything to answer from
GET    /chats/passages?q=           what an answer would be allowed to read
GET    /chats/{id}                  transcript, citations, topics
GET    /pivots                      saved views
GET    /pivots/{id}                 one saved view
GET    /settings                    all settings + storage + backends
GET    /secrets                     credential scan hits
GET    /index/counts                search index table counts
GET    /trash                       what is in the trash
GET    /fonts/{name}                font files (cached 1 year)
```

### Write

```
POST   /notes                        create a note
PATCH  /artifacts/{id}/body          edit a note (captures reject)
POST   /artifacts/{id}/annotations   commentary on a capture
PATCH  /artifacts/{id}               flags only (pinned, local_only)
DELETE /artifacts/{id}               move to trash
POST   /artifacts/{id}/restore       restore from trash
DELETE /trash/{id}                   purge one (irreversible)
DELETE /trash                        empty trash (irreversible)
POST   /trash/purge                  purge expired only
POST   /capture/link                 save a URL, nothing fetched
POST   /capture/upload               multipart file upload
POST   /artifacts/{id}/preview       fetch what a saved link is (opt-in)
POST   /chats                        start a conversation (optionally with text)
POST   /chats/{id}/messages          one turn
PATCH  /chats/{id}                   rename / pin
DELETE /chats/{id}                   the one deletable object
POST   /pivot/plan                    plan a saved view from a request
POST   /pivot/run                     re-run a saved view spec
POST   /pivots                        create a saved view
PATCH  /pivots/{id}                   rename a saved view
DELETE /pivots/{id}                   forget a saved view
POST   /pivots/{id}/exclude           remove an artifact from a view
POST   /pivots/{id}/exclude-many      remove (or, with undo, restore) several artifacts in one request (P.3b)
POST   /pivots/{id}/include           add an artifact to a view
POST   /chunk                        rebuild all chunks
POST   /facet-gate                   re-evaluate facet eligibility
POST   /facets                       generate facets
POST   /index                        rebuild the search index
POST   /reprocess                    re-extract, re-chunk, re-index everything
POST   /ingest/wait                  block until queue drains (for tests)
PUT    /settings/api-key             store key in Keychain
DELETE /settings/api-key             remove key from Keychain
PATCH  /settings                     update writable settings
```

---

## Retrieval architecture

The core differentiator.
If this is mediocre, Enqueue is a worse Fabric.

### The problem

Plain RAG fails the core case structurally.
"Antifragility" embeds near Taleb, black swans, and convexity.
A hand-built furniture article embeds near joinery, grain, and hand tools.
Cosine similarity between them is near zero, so the furniture article never enters top-k.

This is the semantic-to-conceptual gap, not the lexical-to-semantic gap that RAG closes.

### The design: meet in the middle

Two moves from opposite ends.

**Ingest raises artifacts toward concepts.**
Per artifact, once, re-runnable, all behind the capture response (`ingest/queue.py::process`):

1. **Chunks** (the literal layer). Chunk the text with the markdown chunker and embed each chunk locally (bge-base, 768-dim). Chunk text is fed from the note body, PDF page text, link preview text, image annotations (R.2), and a vision model's image description (K.11). The title is prepended for indexing only (see gotchas).
2. **Facets** (the conceptual layer). 5-15 model-written statements of what the artifact could be an example of, climbing levels 0-4, each embedded. Per-facet quality gate; best effort. Bridges the semantic-to-conceptual gap.
3. **Entities** (the named-thing layer). Named things in the body, each enriched with a one-line world-knowledge fact and embedded. Bridges a query in the world's vocabulary to a note that never uses it ("presidents" reaching a Roosevelt biography).

Each layer has its own vec0 + FTS5 tables (`chunks`, `facets`, `entities`); see the index-tables section.

**Query lowers concepts toward artifacts.**
`retrieve/candidates.py::search_results` runs seven legs, each a ranked list, and fuses them:

1. **Dense** - query embedding against chunk vectors.
2. **Keyword** - FTS5 BM25 over chunk text, title column weighted 10x (`bm25(fts_chunks, 1.0, 10.0, 1.0)`).
3. **Trigram** - the `fts_chunks_tri` trigram table for substrings and partial words.
4. **Fuzzy** - `SequenceMatcher` over short fields (titles, entity names, current annotation lines) for one-edit typos trigram cannot see (R.7).
5. **Exact phrase** - quoted phrases pinned (R.10).
6. **Facets** - the conceptual channel, hits weighted by trust (`score * trust * 2.0`).
7. **Entities** - the named-thing channel.

Fuse with RRF (canonical k=60, M.5g), apply the R.8 recency multiplier, optionally rerank the top window with the bge-reranker cross-encoder (R.9, off by default), then roll up to one row per artifact.

### Three granularities

| Layer | Unit | Powers |
| --- | --- | --- |
| Literal | chunk | Search, citation to passage |
| Conceptual | facet | Search's conceptual channel, weighted by trust |
| Named-thing | entity | Search's world-vocabulary channel |

### The relevance floor (Q.3, in progress)

Dense kNN always returns a nearest neighbor however far, so a no-match query would return a wall. The floor is a two-tier gate on the raw legs (not the fused score): any lexical leg or `dense_similarity >= KEEP_ABOVE` keeps; `< DROP_BELOW` drops; the gray zone is settled by one batched model judgment (`judge_gray_zone`), failing open. A search with zero survivors returns `[]`. `chats.passages()` shares the same `passes_relevance_floor` predicate so the answer path refuses honestly. Calibration (the two constants + the gray-zone judge) is the active work in `docs/PLAN.md` Phase Q.

### Scope dial for chat

| Scope | Retrieval |
| --- | --- |
| One artifact | none. The artifact fits in context. |
| Everything | full pipeline |

---

## Ingest pipeline

Always asynchronous. Capture never blocks, never spins, never asks a question.

The queue is in-memory (`ingest/queue.py`).
If the engine dies with work outstanding, that work is lost and the artifact is unindexed until the next `enq index`.
That is the right trade for derived data: nothing the person wrote is ever at risk.

One worker thread, not a pool.
The search index lives inside the SQLite file and embedding models are large enough that a second engine is not free.

### Per type

| Type | Path |
| --- | --- |
| Web page (link) | save URL only. Preview is opt-in (one request). Text comes from preview metadata. |
| PDF | pymupdf extracts text per page. Pages rendered as PNG on demand. |
| Image | stored as blob. No OCR or captioning yet. |
| Note | body is markdown, chunked directly. |
| File (text) | decoded and chunked (txt, md, csv, json, html). |

### Dedupe

Content hash (sha256) on the extracted bytes or URL.
Same content captured twice does not create a second artifact.
Re-saving an existing artifact moves it to the front of the wall (updates `updated_at`).

### Secret scanning

`ingest/secrets.py` scans all text before it reaches a model.
Detects: password assignments, AWS access keys, private keys, bearer tokens, Slack tokens, GitHub tokens.
Excerpts are redacted (value replaced with `***`).
Artifacts with hits get `status = 'text_only'`, which excludes them from facet generation.

### Untrusted content

Captured pages become model input, and a malicious page can inject instructions.
All prompts treat artifact text as untrusted data, never as instructions.
A poisoned facet is written to the index permanently, not just a bad answer in one session.

---

## Link previews

Saving a link fetches nothing.
A preview is the opt-in deal: one request, for one link, because the person asked.

Rules:

1. **Nothing remote is ever referenced.** The `og:image` is downloaded and stored as a content hash in the blob store. Never a URL.
2. **The response is data, not instructions.** Parsed for four fields (title, description, site_name, image), rest discarded.
3. **SVG is refused as a preview picture.** It can carry script, and is served from the engine's own origin.
4. **Local-only links are never fetched.** Fetching would reach the network on their behalf.
5. **HTTP/2 is used** because some publishers (Wikimedia) treat clients that do not negotiate h2 as bots.

Auto-preview is controlled by the `auto_preview` setting (default on).
When on, the ingest worker fetches the preview in the background after capture.

---

## Trash

Deleting is two steps and a window, never one keystroke.

1. **delete** - marks `deleted_at`, drops derived rows (chunks, index points). Leaves every surface immediately.
2. **restore** - within the window, clears `deleted_at`, re-queues for ingest.
3. **purge** - after the window (default 30 days), destroys the artifact and all its rows. The only irreversible operation.

Blobs are content-addressed and shared, so the blob is only unlinked when the last artifact referencing it is purged.
Though currently `content_hash` is UNIQUE, so sharing cannot happen yet.
The guard in `purge` stays because it encodes that dependency explicitly.

`purge_expired()` runs at engine startup.
The retention window is configurable via `trash_days` setting, clamped to a minimum of 1.

---

## Testing

No network in tests.
Provider calls are replaced with a `FakeProvider` that returns scripted responses.

| File | What it tests |
| --- | --- |
| `tests/conftest.py` | `store` fixture: real DB per test in tmp_path. `quiet_queue` fixture: runs ingest inline. |
| `tests/test_chats.py` | Answer contract validators, naming, topics, pinning, turns, scope, deletion. |
| `tests/test_ingest.py` | Secret scanning, proper noun extraction, facet/judgment validators. |
| `tests/test_providers.py` | Malformed HTTP responses, error translation, exception chain walking. |
| `tests/test_settings.py` | API key never touches disk, keychain guards, extra headers parsing. |
| `tests/test_migrations.py` | Fresh DB reaches head, pre-migration DB is adopted, capture can never hold a body. |
| `tests/test_trash.py` | Delete is reversible, purge destroys, retention window, blob sharing guard. |
| `tests/test_preview.py` | Parse, image URL resolution, fetch guards, preview indexing. |

### Conventions

- `store` fixture: monkeypatches `config.DATA_DIR`, `config.DB_PATH`, `config.BLOB_DIR` to tmp_path, then calls `db.migrate()`.
- `quiet_queue` fixture: replaces `ingest_queue.submit` with a list append, so ingest work is synchronous.
- Tests assert on validators rejecting bad output, not on happy paths.
- `FakeProvider` in `test_chats.py` takes scripted replies by response_model name and can raise exceptions.
- `test_providers.py` runs a real HTTP server on 127.0.0.1 to test malformed responses end-to-end.

---

## Build and run commands

### Development

```bash
# Install dependencies (uv manages everything)
uv sync

# Run the engine
uv run enq serve

# Run the CLI against a running engine
uv run enq health
uv run enq search "antifragility"

# Run tests
uv run pytest -q

# Format check
uv run black --check src/ tests/

# Full verification gate (JS parse + pytest + contrast)
bin/verify
```

### Desktop shell

```bash
# Build the Tauri shell (first time or after editing desktop/src)
cd desktop && cargo build

# Launch everything (engine + shell); rebuilds the shell first
bin/launch desktop

# Put it on a plugged-in Android phone
bin/launch mobile
```

`bin/launch desktop` always rebuilds the shell with `cargo build` first (incremental, near-instant when unchanged; a compile error stops it rather than launching a stale binary), kills the shell and engine, writes the repo path to `~/.enqueue-poc/repo`, launches the shell, waits for the engine health check, and brings the window to front. `bin/launch mobile` requires a real phone on USB (USB debugging on) - an emulator is rejected on purpose - then builds, installs, and runs on it via `cargo tauri android dev`.

The shell finds the engine repo via (in order):

1. `ENQUEUE_REPO` env var
2. `~/.enqueue-poc/repo` file
3. Parent of the current directory (works when run from `desktop/`)

### Tauri build notes

- The shell spawns the engine via `uv run enq serve` from the repo directory.
- A double-clicked app inherits the launch daemon's PATH, which has no `/opt/homebrew/bin`. The shell searches for `uv` at `/opt/homebrew/bin/uv` and `/usr/local/bin/uv`.
- `macOSPrivateApi: true` is needed for the transparent capture window.
- Tauri commands: `capture_dismiss`, `capture_drag`, `open_external`, `window_drag`. Each needs both `generate_handler!` registration and a matching permission in `tauri.conf.json`.

### Verification gate limits

`bin/verify` runs JS parse, pytest, contrast check, and an Android build check. The Android check auto-detects the SDK/NDK from the standard install location (`~/Library/Android/sdk`, newest `ndk/*`) when `ANDROID_HOME`/`NDK_HOME` are unset (FIX.3), so it runs on a plain `./bin/verify` instead of silently skipping; it skips cleanly only when no SDK/NDK exists on disk. When Rust, Kotlin, or `desktop/gen/android/**` files changed, it runs the full `cargo tauri android build` (GATE.1) rather than just `cargo check --lib`, because `cargo check` never compiles Kotlin/gradle and a broken `.kt` used to pass the gate green. A green `bin/verify` is still NOT proof the app runs on a device - it proves the code parses, tests pass, the palette meets contrast, and the app compiles for Android. The desktop window (`bin/launch desktop`) and a real device (see "Verifying the Android app" above) are the only proof the app runs. A pre-commit hook (`.githooks/pre-commit`, activated via `git config core.hooksPath .githooks`) runs `bin/verify` when code is staged and blocks the commit on failure; docs-only commits stay instant.

## Working agreement: verification split + commit discipline (do not skip)

Verified work has been lost twice to uncommitted-then-reverted working trees, and a broken mobile module was committed after `bin/verify` was skipped. Two rules prevent the recurrence:

1. **`bin/verify` gates every commit, enforced by git.** A pre-commit hook (`.githooks/pre-commit`, activated with `git config core.hooksPath .githooks`) runs `bin/verify` whenever code is staged and blocks the commit if it fails. Run `bin/verify` yourself before claiming any task "done" - do not rely on the hook to find breakage late. A broken `cargo check --lib --target aarch64-linux-android` is a failure, not a "device blocker."

2. **Commit the same turn work goes green - never leave verified code uncommitted.** The loss happened in the gap between "it works in the working tree" and "someone commits it." Close that gap: as soon as `bin/verify` is green, the working tree is committed (the human commits after each green turn; or, if agreed, an agent commits its own verified work to a branch the human reviews). Uncommitted verified work is treated as work that will be lost.

**The verification split** (why "I can't run the device" is never a reason to stop): implementing code, `cargo check`, and `bin/verify` are HEADLESS and need no hardware - do all of it. The final runtime check on a physical phone / desktop window ("Done when: on the device...") is done by the HUMAN TESTER, who has the device. So the loop is: agent implements + `bin/verify` green + commit, leaving the box UNCHECKED with a "code-complete, pending device verify" note; the human runs the device pass and checks the box. Never stop a turn merely because the device runtime is out of reach - there is almost always headless implementation + gate + commit work to finish first.

---

## Verifying the Android app on a device (headless, over adb)

A harness with no macOS display can still drive the PHYSICAL PHONE or a headless EMULATOR end to end over adb, and did on 2026-08-19 (proved MOBRENDER.1's full sync/decrypt/apply/render path from the shell alone). "Headless" means no desktop window; it does NOT block device verification - the device is the display. Default to driving it yourself; escalate to the human ONLY for a truly visual check that adb cannot see (below).

**NEVER run `cargo tauri android dev` (nor `bin/launch mobile`) for verification.** It is a dev-server WATCH LOOP that never exits - it hangs indefinitely (often on "pick a device"), and piping it to `| tail` makes the whole command look frozen because tail waits for an EOF that never arrives. It is a hot-reload dev tool, not a build. For verification always use a ONE-SHOT `cargo tauri android build --debug` then `adb install` (below), which exits and lets you drive the app over adb. `bin/launch emulator` was rewritten to do exactly this (boot the AVD, build, install, launch, print the serial, and EXIT), so it is safe; the raw `cargo tauri android dev` is not.

The adb toolkit (phone on USB or emulator, package `com.sudohnim.enqueue`):

- **Build + install:** `cargo tauri android build --debug --target aarch64` (a one-shot that EXITS), then `adb install -r desktop/gen/android/app/build/outputs/apk/universal/debug/app-universal-debug.apk`. The apk loads the embedded frontend at `tauri.localhost` and runs unplugged: `devUrl` is OMITTED from `tauri.conf.json` on purpose (RELEASE.1) - setting it to `""` crashes tauri-build ("relative URL without a base"), and a real LAN dev URL makes a standalone cold launch show a "Failed to request .../mobile.html" error page. So never add `devUrl` back, and never put `apk`/`aab` in `bundle.targets` (invalid enum). A SIGNED release (`cargo tauri android build`, no `--debug`) needs `desktop/gen/android/key.properties` (or the `RELEASE_*` env vars) + the keystore; the gradle `signingConfigs.release` is guarded by `hasReleaseSigning` so debug stays unsigned. A release apk is NOT debuggable (no run-as / CDP) - always verify on the DEBUG apk.
- **Emulator relay reachability:** a headless emulator reaches the LOCAL relay at `10.0.2.2:8788` (the host's loopback from inside the emulator), NOT via `adb reverse`; a hosted relay (Railway) is normal internet from either device.
- **Verify visuals by RENDERING, never by reading source (DESKTOPUI.6 lesson):** a glyph/icon shape, a layout, a color, whether a screen is reachable - these can only be confirmed by looking at a screencap or asserting the runtime DOM/CDP. "The source path changed" is not verification; a wrong SVG that parses fine looks wrong on screen.
- **Launch:** `adb shell monkey -p com.sudohnim.enqueue -c android.intent.category.LAUNCHER 1`.
- **Screenshot:** `adb exec-out screencap -p > /tmp/shot.png`, then READ the PNG yourself (do not ask the human to describe the screen). The WebView UI renders in screencaps; the camera preview layer does NOT.
- **Drive the UI:** `adb shell input tap <x> <y>` / `input swipe` / `input text`; get coordinates from `adb shell uiautomator dump /sdcard/ui.xml && adb pull /sdcard/ui.xml`.
- **WebView console + JS + programmatic invoke (the real workhorse):** use `bin/cdp-eval "<js expr>"`. It does the whole dance - pid lookup, `adb forward`, `/json` target, `Runtime.evaluate` with `suppress_origin=True` (the Android DevTools endpoint 403s the default Origin), `awaitPromise` so `invoke(...)` resolves - and prints the JSON value. Examples: `bin/cdp-eval "document.getElementById('library').hidden"`, `bin/cdp-eval "await window.__TAURI__.core.invoke('mobile_status')"`, `bin/cdp-eval "(()=>{const r=document.querySelector('.card').getBoundingClientRect();return r.width+'x'+r.height;})()"`. Flags: `--serial`, `--timeout`, `--raw`.
  - **NEVER hand-roll the websocket loop.** The recurring failure is a bare `ws.recv()` with no timeout inside a fixed-count "drain" loop: CDP sends fewer messages than the loop assumed, so `recv()` blocks for the entire command budget (observed 3000s) and a bare `except` swallows it silently. `bin/cdp-eval` wraps every recv in a hard timeout - it returns a value or fails fast, it cannot hang. If you need something the helper does not cover, add a flag to it; do not write a fresh websocket loop.
- **App state + secrets (debug build):** `adb shell run-as com.sudohnim.enqueue cat /data/data/com.sudohnim.enqueue/sync_config` (relay_url, secret, DEK hex) and `... cat .../library.db` into a local file, then `sqlite3` it to count applied artifacts. This is how you tell a decrypt/apply failure (cursor advances, 0 rows) from a render bug.
- **Permissions / camera-active / logs:** `adb shell dumpsys package ... | grep CAMERA`; `adb shell dumpsys media.camera | grep -A2 com.sudohnim.enqueue` proves the camera stream is live even though it never shows in a screencap; `adb logcat -d | grep -iE 'Tauri/Console|enqueue|panic'` catches JS exceptions and Rust panics.
- **Relay / engine state:** plain `curl` against the relay URL (with the Bearer secret) and `127.0.0.1:8787`.

ESCALATE TO HUMAN only for a visual the camera layer hides or a macOS-display check: the SCANUI.1 camera-box aesthetics (the camera surface is invisible to screencap - verify camera-active + box geometry via dumpsys/uiautomator first, so the human judges only the look), the CAP2.2 capture-flight on the desktop, and the 10-second physical act of aiming the phone camera at the desktop QR. Everything else - linking, syncing, deleting, rendering, permissions, offline behaviour - is agent-verifiable. When escalating, state the single unanswered visual question, not "please test the app".

---

## Gotchas

### 127.0.0.1, not localhost

Always bind to `127.0.0.1`.
This machine may run Ollama in Docker bound to the IPv6 wildcard, and `localhost` resolves to IPv6 first.

### settings_path is resolved at call time

`settings.settings_path()` reads `config.DATA_DIR` each time it is called, not at import.
This is deliberate: a test that repoints `config.DATA_DIR` at a temp directory must read and write the temp settings file, not the developer's real one.

### The ingest queue is in-memory

If the engine crashes, queued work is lost.
The artifact is unindexed until the next `enq index` or `enq reprocess`.
This is acceptable for derived data.

### The search index lives inside the database

The vec0 and FTS5 tables live in `enqueue.db`, so there is no separate index
directory to keep in sync or lock. `get_store()` is still cached via `lru_cache`
so the engine holds one instance for its lifetime; the eval harness repoints it
via `get_store.cache_clear()`.

### The title is prepended for indexing only

`index_chunks` prepends the artifact title to the chunk text before embedding.
The stored chunk text stays clean.
This exists because a note whose title is the only place a name appears is otherwise unfindable by that name.

### Instructor context keyword

instructor >= 1.9 renamed `validation_context` to `context`.
The keyword is what carries `proper_nouns` and `artifact_text` into the validators.
Getting it wrong silently disables every context-dependent check.

### The old AGENTS.md is stale

Much of the old AGENTS.md described things that are not built: encryption at rest, sync, crawl4ai, marker, whisper.cpp, browser extension, Android, facet trust updates.
It also named a "Lumo" backend that never existed; the cloud path is OpenRouter.
This file documents what actually exists.
See the Resolved decisions section above for the status of each of these.

---

## Library decisions

| Library | Role | Notes |
| --- | --- | --- |
| FastAPI | HTTP API | Binds 127.0.0.1:8787. Serves static HTML + JSON API. |
| Typer | CLI | Thin client over the API. Never touches the DB. |
| Pydantic | schemas + validation | Validators are the quality floor. Instructor re-prompts on failure. |
| instructor | structured LLM output | Mode.JSON for all adapters. Wraps the OpenAI client. |
| openai | LLM client | Used for all OpenAI-compatible endpoints. |
| fastembed | local embeddings | BAAI/bge-base-en-v1.5 (dense, 768d). |
| sqlite-vec | search index | vec0 + FTS5 tables inside the SQLite file; hybrid fused with RRF. |
| pymupdf (fitz) | PDF parsing | Text extraction, page rendering, page counting, phrase search. |
| beautifulsoup4 + lxml | HTML parsing | For link preview metadata extraction. |
| httpx | HTTP client | HTTP/2 enabled for preview fetches. |
| Alembic | migrations | Runs at startup. Config built in code, not from ini. |
