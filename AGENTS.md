# Enqueue - Agent Instructions

Project-specific instructions for AI coding agents working in Enqueue.
This file is engineering reference: architecture, module map, data flows, conventions, and gotchas.
For what the app does from a person's side, see [docs/MANUAL.md](docs/MANUAL.md).
For building, running, and configuration, see [docs/DEVELOPING.md](docs/DEVELOPING.md).
For the look and its rules, see [docs/DESIGN.md](docs/DESIGN.md); for sync, [docs/e2e/E2E.md](docs/e2e/E2E.md) and [docs/sync-relay.md](docs/sync-relay.md).
For the current build status and task queue, see [docs/PROGRESS.md](docs/PROGRESS.md) and [docs/PLAN.md](docs/PLAN.md).
The README is the public face (a marketing piece with screenshots from `bin/screenshots`); keep engineering detail out of it.
There is no docs/PRODUCT.md, CURATION.md or EVAL.md: the prompts live in `prompts.py`, the eval gates in `bin/check-eval*`.

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
One amendment (2026-09-29): when a structured call comes back 400, `OpenAICompatibleProvider.complete` asks once more in `Mode.MD_JSON` (no `response_format` on the request). OpenCode Go's `kimi-k3` refuses `response_format: json_object` for some inputs with a deterministic 400 "Upstream request failed: Invalid request parameters" (THC, income snowball), while the same request without it succeeds; a 400 is not transient, so without the fallback those summaries failed forever.

**Usage limits pause every model call (`providers/pause.py`, 2026-09-29).**
A 429 (OpenCode Go answers `GoUsageLimitError`, `limitName: "5 hour"`, with a `retry-after` header in seconds) trips ONE engine-wide pause until the retry-after (at least 30s; 15 min when the header is missing), and logs one `model.paused` activity row.
While paused, `complete`/`describe_image` raise `ModelPaused` without touching the network; it is a `ProviderError` and `is_transient` counts it, so owed work stays owed.
`_record_facet_retry` reschedules an owed summary to the pause end (plus up to 60s jitter) WITHOUT counting an attempt, and `_sweep_due` idles until the pause ends.
The first call after the pause goes out normally; a still-limited provider just trips it again.
`enq doctor` shows it as `model_pause` (null when not paused).
The pause is in-memory: a restart forgets it and the first call re-trips it.
Switching accounts ends it early: storing or removing the API key (`PUT`/`DELETE /settings/api-key`) or changing `llm_backend`/`llm_model`/`summarize_model`/`llm_url`/`llm_headers` calls `pause.lift()`, which clears the pause, brings every owed summary retry forward to now, and logs `model.resumed`.

3. **Facet trust is a fixed multiplier, not a learning loop.**
`facets.trust` defaults to 0.5, is read in `retrieve/candidates.py` as `score * trust * 2.0`, and is never written after creation.
A trust-update mechanism (promote on save, demote on eject) is a planned feature, not an implemented one.
For now, trust is a flat constant and every facet contributes equally after the 0.5 weighting.
Usage does feed ranking one level up, per artifact rather than per facet: see "Usage" under Retrieval design notes.

4. **There is no Lumo. The cloud backend is OpenRouter.**
The old docs name Proton's Lumo as a backend; it does not exist in the code.
The configured backends are `ollama` (default, local), `openrouter`, and `opencode-go` (OpenCode Go subscription, `https://opencode.ai/zen/go/v1`). The old `opencode` (Zen) and `custom` backends were removed; a stored `opencode` config migrates to `opencode-go`. Only Go chat-completions models work (the adapter speaks `/chat/completions` only; `/responses` and `/messages` models are refused with a clear message - see `config.py` GO_* sets and `providers/base.py`). Treat OpenRouter as the general cloud path. Remove any Lumo reference you find.

5. **crawl4ai is the opt-in browser fallback for link previews (2026-09-29).**
It is a dependency, used only by `preview._read_browser` when the `preview_browser` setting is on (see "Link previews").
The Chromium it drives is a separate download that `bin/setup` installs.
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
The Android app (Tauri v2 mobile, `desktop/gen/android`, crate builds as `enqueue_lib`) is built: it syncs the encrypted library through the relay into a local SQLite copy, captures, reads, does the light in-the-moment writes (edit note, delete, pin - tagging and annotating are deliberately desktop-only), and chats by calling the configured LLM backend directly with keyword-only (FTS) grounding.
It never computes embeddings, facets, or entities; enrichment stays desktop-only. AI-derived data that has not synced down is absent quietly - never a placeholder or a fabricated summary.
Mobile UI lives in `src/enqueue/static/mobile.html` (relative asset paths). Layout: a single-column list under SAVED / EVERYTHING ELSE shelf headers, newest first; rows open a Reader (note markdown, where a tap on the text opens the writing page, image with pinch-zoom, link preview card, PDF via vendored pdf.js); a bottom pill (capture in `--purple-bold`, search, the living raven eye for ask, menu). The capture "raven moment" is the ANIM.4 flight, or a fade under reduced motion.
Writing a note on the phone is one full-screen page (`#writer` in `mobile.html`), for a new note (the pill's "Note") and for an existing one (a tap anywhere in a note's text in the reader - there is no pencil; the caret lands where the finger did, via `rawOffsetAt`, and links keep their link bar).
The page is sized to the VISUAL viewport (`fitWriter` sets `--writer-top`/`--writer-h` from `visualViewport`), so the keyboard shrinks it instead of covering it, and the tool bar (lists, heading, indent, Done) sits on the keyboard; `keepCaretVisible` scrolls the body to the caret with a mirror measurement when the box shrinks.
It saves as you type (`saveWriter`, debounced, serialized): a new note is created on its first non-empty save through `mobile_capture` with `as_note: true` (so an address inside it never turns it into a link), then updated with `mobile_update_note`; a title is sent only when the person typed one (`null` keeps an explicit title). An empty new page leaves nothing behind. Closing lands on the note's reader (existing) or the library with the raven flight (new).
The Android Back gesture asks the page first: `MainActivity.handleBackInThePage` calls `window.__enqBack()`, which closes the innermost layer (writing page, pill menu, details panel, any screen but the library) and answers whether it did; only a "no" sends the app to the background (`moveTaskToBack`). Do not rely on web history for Back: Chromium skips history entries a page pushes on its own, so WryActivity's `canGoBack()` was false and Back closed the app from the reader and the writing page.
The quick-capture bottom sheet the pill used to open is gone: in the app, a note is written on this page; the one-thought flow over another app is the launcher's popup below.
The launcher shortcut (long-press the app icon, "Quick capture", `res/xml/shortcuts.xml`) opens `QuickCaptureActivity` instead: a native, translucent sheet in its own task (Dequeue's QuickAddActivity model) that floats over whatever app is in front, so Enqueue never comes forward.
It cannot reach the library (a Tauri app has one WebView, owned by `MainActivity`), so Save writes the text to `QuickCaptureInbox` (one file per capture under `filesDir/quick_capture`) and closes; the page files each one through `mobile_capture` and only then acknowledges it (`drainQuickInbox` over the `EnqueueAndroid` bridge's `quickCaptures()`/`ackQuickCapture(id)`), at boot, whenever the app comes to the front, and at once when the app is already running (`MainActivity.drainQuickCaptures`).
A capture made while the app is not running reaches the library and the relay the next time the app opens.
Dismissing the popup keeps its draft. Its look (raven and "Capture your thoughts." centred, a white field, Save) matches the desktop capture overlay.
Build/run the app with `bin/launch mobile` (physical phone only) or `bin/launch emulator` (headless AVD, one-shot build + adb install + exit, for agent device-verify); the raw build is `cargo tauri android build --debug --target aarch64` with the apk at `desktop/gen/android/app/build/outputs/apk/universal/debug/app-universal-debug.apk`. NEVER use `cargo tauri android dev` for headless verify - it hangs on device-pick. What remains open is any items in the current `docs/PLAN.md`.
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
In the overlay, a plain Enter saves (the same path as the Save button), Shift+Enter inserts a newline, and Escape dismisses without discarding the draft (CAP2.1).
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
| `api/guard.py` | `LocalOnlyGuard`: answers only loopback Host names (`config.ALLOWED_HOSTS`, else 421) and refuses a state-changing request whose Origin is not the engine's own (`config.ALLOWED_ORIGINS`, port included, else 403), so no other website can reach the engine, even through DNS rebinding. Requests with no Origin (CLI, the shell's health check) pass. Tests add `testserver` via conftest. |
| `privacy.py` | What may go to which model. `is_remote(provider)` (endpoint not loopback), `shareable(items, provider)` drops local-only artifacts from anything shown to a remote model: chat passages, the gray-zone judge, model re-ranking. A chat scoped to a local-only artifact, and attribute extraction from one, use the local model. The phone's chat does the same through `sync::chat_sources`. |
| `outbound.py` | What went to remote models: `OpenAICompatibleProvider` counts every structured call and image description to a non-loopback endpoint (service, model, purpose by response model, characters, credentials blanked), never the text, and writes one `model.sent` Activity row per service every 10 minutes and at shutdown, so a reprocess does not bury the log. |
| `settings.py` | Three-layer settings (env > settings.json > default). Writable fields, storage report. |
| `db.py` | SQLite access + Alembic migration at startup. `get_conn()`, `transaction()`, `count()`. |
| `greeting.py` | The wall's greeting: one model phrase per four-hour bucket, generated in the background. |
| `schemas.py` | Pydantic models for every model call. Validators are the quality floor. |
| `prompts.py` | System prompts. Authoritative copies are in docs/CURATION.md. |
| `keyring.py` | macOS Keychain for the API key. `/usr/bin/security`. No-op on non-macOS. |
| `capture.py` | Captures: links, file uploads. Content-addressed dedupe. PDF text extraction and page rendering. |
| `notes.py` | Notes: create, edit (versioned), annotate. Secret scanning before model calls. |
| `preview.py` | Link previews: one opt-in fetch, parse og:meta, download image locally. |
| `chats.py` | Conversations: submit (write pending turn + queue), scoped retrieval, grounded answers, topics, titles, chat sync push. |
| `chats_worker.py` | The answer worker: a `Worker` thread that routes, answers, commits (retrying transient DB locks), logs `ask.answered`/`ask.failed`, and pushes. `sweep_orphaned_pending` at startup. |
| `events.py` | The activity log: `emit()`/`recent()` over the persisted `events` table. Never raises. Backs the Settings Activity tab and the vault decoy. |
| `worker.py` | Shared single-thread queue lifecycle used by the ingest queue and the answer worker; two lanes (the person's work before background upkeep). |
| `trash.py` | Soft delete with retention window. Purge is the only destructive operation. |
| `backup.py` | Backups into a cloud drive's folder (Proton Drive): daily + on clean shutdown + on demand, `VACUUM INTO` a temp file then atomic rename, search index emptied in the copy, blobs mirrored, 7 daily + 4 weekly kept; `restore()` sets the current library aside. |
| `opens.py` | Records each artifact open (`opens` table): source (search/wall/related/chat/other), and for a search open its query and 1-based rank. `usage_boost` turns opens, chat citations and pins into a small ranking multiplier. The interface reports opens through `POST /artifacts/{id}/opened` (`reportOpen` in `static/js/util.js`). Local only, never synced. |
| `resurface.py` | Daily resurfacing: one artifact saved 14+ days ago and not opened in 14 days comes back above the wall. It prefers one linked (`related`) to something saved in the last 7 days, rotating daily through the top 3 links, else a stable hash pick for the day. `GET /resurface` returns it as a wall item plus the reason; `refreshResurface` in `static/js/home.js` draws the strip, and "Not today" hides it until tomorrow (localStorage, this browser only). Opening it records an open with source `resurface`, which also takes it out of the pool. No model call. |
| `eval_embedders.py` | `enq eval-embedders`: rebuilds both eval libraries with each candidate embedding model and reports main recall@10/MRR/Nothing-OK, cross-domain passes, and floor bars fitted to that model's scale. See "Embedding models". |
| `eval_real.py` | The real-search eval: every search followed by an open is a case, scored against the live library. See "Real-search eval". |

### Ingest

| File | Job |
| --- | --- |
| `ingest/queue.py` | In-memory work queue. One daemon thread. `submit()` returns immediately. Model steps run sections -> facets -> entities -> contexts; each skips work already current (facets/entities written by the current ingest model from the current body; contexts only for chunks missing one, and `chunk_artifact` carries contexts over unchanged chunk text), and a transient failure in any of them (`source.Owed`) owes the artifact a `facet_retry`, so a rate-limited reprocess finishes itself later at the cost of only what was missing. "Rebuild concepts" is how to force facets with the same model. A vision describe failure marks the image `status='failed'` and surfaces in `/doctor` (`images_without_body`) instead of failing silently. |
| `ingest/chunk.py` | Markdown chunker. Headings, lists, code fences kept whole. Prose merged to a floor. Anything over `CHUNK_MAX_TOKENS` (counted with the embedder's own tokenizer) is split at line, then sentence, then word boundaries. Chunk source includes the artifact's current annotation text; a bodyless capture falls back to its title + filename so it always has at least one chunk. |
| `ingest/facets.py` | Facet generation via the summary provider, fed page_text + annotations. Eligibility gate, proper-noun self-reference check, retry/backoff. Also the user-edit surface: `edit_facet`/`add_facet`/`delete_facet`/`regenerate` + `sync_facets` (push to other devices). |
| `ingest/source.py` | The text every ingest writer reads: `ingest_text()` = the body (notes) or extracted `page_text` (links, PDFs, images), plus current annotations marked "(your note)". A document over `FACET_INPUT_CHARS` is map-reduced: split into sections of up to 10k characters on paragraph boundaries (at most 24), each summarized by the ingest model (cached in `derived_values`, scope `section_summary`, per section hash and model), and read as ordered summaries. The summaries are also written to `sections` (stamped with ingest model and body version; left untouched when unchanged, since facets, entities and contexts each read through here) and indexed as their own search layer by the ingest queue. A section that fails for a reason that will pass (rate limit, outage; `providers.base.is_transient`) raises `SummariesOwed` so the artifact is retried instead of written from its opening; any other failure falls back to the capped opening; `text_only` text is never mapped. Facets, entities and chunk contexts all read through it. |
| `ingest/context.py` | Contextual chunks: for an artifact with 2+ chunks, the ingest model writes one or two sentences per chunk placing it in the document (batches of 30). Stored in `chunks.context`, embedded and keyword-indexed with the chunk (not in the trigram table). Skips `text_only` artifacts. |
| `ingest/related.py` | Related artifacts, precision first: a missing link costs nothing, an invented one costs trust. Three kinds. **Subject links:** each of an artifact's subject lines (facet level 1, `SUBJECT_LEVEL`) searches the facet index and only another artifact's subject lines count; kept at or above `RELATED_MIN` 0.66, with `related.point` = the related artifact's subject line that matched (each direction holds the line of the artifact it points at). **Mention links:** another artifact whose current entities name the same person, place or thing (case-insensitive) scores 0.7 and stores the name in `related.via`; a name more than 8 artifacts share never links, nor does a link's own site name ("Medium" on an article saved from medium.com, read from its preview or its address). **Idea links** (cross-field): similarity between lines ABOVE the subject level only proposes pairs (`IDEA_MIN` 0.72, the closest `IDEA_CANDIDATES` 8), and the ingest model judges each with `prompts.RELATED_JUDGE` (one call per artifact); only a yes links, and its `point` is the model's plain "Both ..." sentence. Similarity alone cannot do this: the prompt's "bridge" lines borrow another field's words on purpose (a piano essay gets a line about codebases) and abstract sentences match on shape ("X beats Y"), which linked a data-modeling note to a piano essay and a tax letter. The judge FAILS CLOSED (an unjudged pair is not a link), the opposite of search's gray-zone judge. Verdicts are cached in `derived_values` (scope `related_judge`, subject `a|b` ids in order, attribute = a stamp of both items' level 0-1 lines, so a changed subject asks again). `compute(id)` never calls a model: cached verdicts only, and it marks the artifact pending (scope `related_pending`). `compute(id, judge=True)` is called by the ingest worker (`queue._related_artifact`, when facets or entities were just written or the artifact is pending); a transient failure raises `JudgeOwed` after writing every link that needs no judge, and the worker records a `facet_retry` so the pause/backoff machinery finishes it later. A facet edit (`facets._reindex`, a request thread) computes without the judge and hands a pending artifact to the background lane. A pair with a local-only item goes to the local model only. `VERSION` (kept in `index_meta.related_version`) makes `refresh_if_outdated()` recompute every artifact once at startup on the ingest worker (no model), and at every startup it queues the pending ones in the background lane. `enq doctor` reports `related_pending`. The top 5 are stored in `related` in both directions; stale facets and entities never count. `GET /artifacts/{id}` returns `related` (each with `via` and `point`), shown as a Related section under the note (`relatedRowHtml` in `static/js/artifact.js`). The phone has no related data (it does not ride the snapshot). |
| `ingest/secrets.py` | Credential pattern scanner. Runs before any text reaches a model. |

### Retrieve

| File | Job |
| --- | --- |
| `retrieve/lift.py` | Query lifting: the search model restates a search as 2-4 facet-style claims, each also searched against facets (dense similarity counts for the floor; never lexical). Cached in `derived_values` (scope `query_lift`). Chat always lifts; `/search` only with the `search_lift` setting (Settings > Features > Search, default off). Tests stub it via an autouse conftest fixture. |
| `retrieve/decompose.py` | Two-sided questions: "compare X and/with Y", "the difference between X and Y", "how does X compare to Y", "X vs Y" split into their sides (each 1-12 words; plain rules, no model call). `chats.passages` searches each side on its own (`_library_passages`), interleaves them rank by rank so both sides reach the answer, then fills leftover slots from the whole question. |
| `retrieve/passage_links.py` | Passage connections: for each of an artifact's first 40 chunks, its stored vector finds the nearest chunks in other live artifacts (`store.similar_chunks`); those at or above `PASSAGE_MIN` (0.78 cosine, about a quarter of eval-corpus passages link) become up to 3 connections per passage. On demand, nothing stored, no model call. `GET /artifacts/{id}/connections`; the drawer's "Passages that connect" section (`mountConnections` in `static/js/artifact.js`) shows each passage's opening words and its linked notes. |
| `retrieve/filters.py` | Filters in the words of a search: an unambiguous kind word (pdf, link/article, image/photo/screenshot; never "note") and a time phrase (today, yesterday, this/last week/month/year, the last N days/weeks/months, in March [2025], in 2024) become exact filters on kind and `created_at`, and the rest is searched. Plain rules, no model call. `search_results` intersects them with `#tag` filters into one `allowed` set (empty means no results, never the whole library); a filter with no other words lists what it allows. `/search` returns the understood filters as `filters` ("PDFs · saved last month") for the results header. A quoted phrase is never parsed. |
| `retrieve/model_rank.py` | Model re-ranking: the search model reads the top `WINDOW` (20) floor survivors (title, snippet, facets) and returns them best first; missing ids keep their fused order, a failure keeps the whole fused order. Cached in `derived_values` (scope `model_rank`) per query, candidate set and model. Opt-in via the `search_model_rank` setting (Settings > Features > Search, default off); runs after the R.9 cross-encoder when both are on. |
| `retrieve/candidates.py` | `/search` rollup: dense + FTS5 keyword fused with RRF, plus trigram substring recall, a fuzzy short-field branch (titles, entities, annotations), and exact quoted-phrase pinning. One row per artifact. |

### Index

| File | Job |
| --- | --- |
| `index/embed.py` | Local embeddings via fastembed. Dense (BAAI/bge-base-en-v1.5, 768d). `embed()` for passages, `embed_query()` for searches (adds `EMBED_QUERY_PREFIX`), `token_count()` for the chunker. |
| `index/store.py` | `VectorStore` interface + `get_store()` factory. One instance per process. |
| `index/store_sqlite.py` | sqlite-vec backend: vec0 + FTS5 tables (unicode61 keyword + trigram substring), hybrid search fused with RRF. `search_legs()` returns the fused list plus the raw dense/keyword/trigram legs from one pass on one connection; callers that need both (the relevance floor in `/search` and `chats.passages`) must use it rather than re-running `search_dense`/`search_keyword`. |
| `index/fusion.py` | Reciprocal rank fusion as a pure function. |
| `index/bootstrap.py` | Startup index build (no manual step) + cutover cleanup. |

### Providers

| File | Job |
| --- | --- |
| `providers/base.py` | `Provider` protocol, `get_provider()`, error translation to sentences. |
| `providers/ollama.py` | `OpenAICompatibleProvider`. One adapter for all OpenAI-protocol endpoints; falls back to `Mode.MD_JSON` on a 400. |
| `providers/pause.py` | The engine-wide pause on model calls after a 429 usage limit (until `retry-after`); `lift()` on a key or model change. |

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
| `migrations/versions/0038_related_point.py` | `related.point`: the related artifact's summary line behind an idea link (NULL for a name-only link). |
| `migrations/versions/0037_related_via.py` | `related.via`: the shared name behind a "both mention" link (NULL for an idea link). |
| `migrations/versions/0036_sections.py` | `sections` (artifact_id, ordinal, summary, model_version, body_version): section summaries of long documents, a search layer. Purge deletes an artifact's rows. |
| `migrations/versions/0035_opens.py` | `opens` (artifact_id, source, query, rank, opened_at): the open log behind the real-search eval. No foreign keys; purge deletes an artifact's rows. |
| `migrations/versions/0034_related.py` | `related` (artifact_id, related_id, score, model_version): derived links, no foreign keys; purge deletes both directions. |
| `migrations/versions/0033_chunk_context.py` | `chunks.context` and `chunks.context_model` (contextual chunks). |
| `migrations/versions/0009` .. `0037` | One revision per schema change, applied at startup (latest: `0037_related_via`). Notable: 0010 index tables, 0019 below, 0031 `facets.edited`, 0032 `events`, 0036 `sections`. Read the directory for the rest. |
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
| `bin/setup` | Make a fresh machine buildable: install/update Rust to a stable >= MSRV 1.88 (`rustup update stable --no-self-update`), install `uv` + pin Python 3.12, check Node. `--android` also checks SDK/NDK/JDK, installs tauri-cli, adds the aarch64-linux-android target. Idempotent, no sudo. Run it when `bin/launch` fails on toolchain (e.g. `rustc <ver> is not supported`). |
| `bin/verify` | `--fast`: black, ruff, JS parse on the HTML pages and contrast (seconds; the pre-commit hook). Full: adds pytest (`-n auto`), desktop Rust unit tests (`cargo test --lib` on the host target when any `desktop/**/*.rs` changed - the Android check builds for the android target and cannot run tests), and an Android build check (auto-detects the NDK; runs a full `cargo tauri android build` when Rust/Kotlin/`gen/android` changed, else `cargo check --lib`). `--desktop-tests` and `--android` run just that one check, unconditionally, and fail rather than skip without a toolchain (what CI calls). `.githooks/pre-commit` runs `--fast` on every code commit; CI runs everything else. |
| `bin/check-contrast` | WCAG contrast check on the palette tokens in `static/css/tokens.css`, including the night ground. |
| `bin/screenshots` | Regenerate the README screenshots from a demo library: a second engine on its own port and a throwaway data folder (never the real library, Keychain key or relay), seeded, then shot with headless Chromium. Before writing anything it checks that the engine answering reports the scratch folder as its `data_dir` and refuses otherwise: on 2026-10-01 its engine failed to bind (the port was held by a preview proxy to the real engine), it carried on, and 15 demo items landed in the real library. Any script that seeds an engine must prove which engine it is talking to first. |
| `bin/launch desktop` | Rebuild shell, kill engine + shell, launch, wait for health, bring to front. |
| `bin/launch mobile` | One-shot build + `adb install` + launch on a plugged-in Android phone, then EXIT (no `cargo tauri android dev`, so no held Gradle lock; emulator rejected). |
| `bin/launch emulator` | Boot a headless AVD, one-shot build the debug apk, `adb install` + launch, then exit (for headless device-verify over CDP/screencap). |
| `bin/cdp-eval` | Evaluate JS inside the running Android WebView over CDP (the supported way to read on-device runtime state); `--serial <device>`. |
| `bin/check-eval-cross` | Cross-domain search gate (CI `eval` job): runs `enq eval-cross`, fails if a layer makes results worse than the one below it (enriched vs chunks, lifted vs enriched) or if any query that passed in `evals/results/cross-domain.json` now fails. `--update-baseline` rewrites the baseline. |
| `bin/deploy-relay` | Deploy the sync relay to Railway (dev/prod), gated on the relay tests, polls `/health`. |

### Static

| File | Job |
| --- | --- |
| `static/home.html` | The home shell: meta, font preloads, the `#topbar`/`#view`/`#pill`/`#dropover` skeleton, ordered `<link>` to `css/*.css` and `<script src="/static/js/...">` tags. Split from the old single-file museum.html in M.8: one global scope, no build step, no ES modules. |
| `static/css/` | The home interface stylesheets, split by surface (M.8): `tokens.css` (palette), `base.css` (type/buttons/callouts/rows), `home.css` (topbar/searchbar/homehead/eye/wall/cards/groupbar/tagbar), `artifact.css` (artifact+drawer+editor+docpane), `reader.css` (reader+findbox+folio), `chat.css` (transcript), `settings.css`, `pill.css` (pill+menu+toast+dialog+dropover+animations), `eyepanel.css` (the ask panel), `linkpop.css`, `tour.css` (the tour; shared with the phone), `bird.css` (the flying raven loader, `.flybird`; shared with the phone). |
| `static/js/` | The home interface JS, split by surface (M.8). Load order: `util`, `icons`, `eyemood` (the pill eye's moods), `ground` (the page colour drifting through the day), `md` (markdown render + serialize), `linkpop` (the copy/open bar for links in content), `tour` (the ? tour), `dialogs`, `pill`, `morph`, `home`, `artifact`, `search`, `pivot`, `manual` (views arranged by hand: the page, the drag, the picker), `chat`, `trash`, `settings`, with the boot call last. One global scope; no ES modules. |
| `static/capture.html` | The capture overlay. Separate page with its own token copy. |
| `static/fonts/` | IBM Plex Sans woff2/ttf, served locally. No CDN. |

---

## Key data flows

### Capture -> ingest -> index

1. **Capture** (`capture.py` or `notes.py`): create an artifact row, write blob if applicable, return immediately.
2. **Queue** (`ingest/queue.py`): `submit(artifact_id)` puts it on an in-memory queue. Returns before processing.
3. **Worker thread**: for links, optionally fetch preview; for PDFs, extract text via pymupdf; chunk the text; index into the sqlite-vec store. An image whose vision describe fails is marked `status='failed'` and surfaced in `/doctor` rather than failing silently.
4. **Chunk** (`ingest/chunk.py`): markdown-aware splitting. Headings, lists, code fences are coherent units. Loose prose merged to a floor of 120 words. A unit over `CHUNK_MAX_TOKENS` (400, counted with the embedder's tokenizer via `embed.token_count`) is split at line, then sentence, then word boundaries, each piece opening with up to 60 tokens of the one before. bge-base reads 512 tokens and silently drops the rest, and the embedded text is title + context line + chunk, so the 112-token remainder is the title's and context's budget (`tests/test_chunk.py` pins it). Text of at most 400 characters skips the tokenizer, since a token covers at least one character. The chunk source includes the artifact's current annotation text (superseded annotations excluded), and a bodyless capture falls back to its title + filename so every artifact has at least one chunk.
5. **Index** (`index/store_sqlite.py`): embed chunks (dense), upsert into `vec_chunks`, `fts_chunks`, and the trigram `fts_chunks_tri`. Title prepended for indexing only. Writing an annotation re-queues the artifact so its new text is searchable.
6. **Facets, entities, chunk context** run after the first index, behind the capture: facets and entities from `ingest/source.py` text, then (multi-chunk artifacts only) chunk contexts, after which the artifact is re-indexed so the contexts are embedded. A quoted exact-phrase search only matches a chunk's own words, never its context.

### Facet generation

1. **Eligibility gate** (`ingest/facets.py`): `apply_eligibility_gate()` marks artifacts that should not get facets (too short, not a note, text_only status).
2. **Generate** (`ingest/facets.py` `generate_for_artifact`): feeds the model the artifact's page_text (not just the body, capped at `FACET_INPUT_CHARS`) PLUS its annotations marked "(your note)", so a person's notes shape the summary. Calls `get_provider(summarize=True)` (the summary model), stores facets stamped with `provider.model` and a trust derived from the model's confidence. DELETE-before-insert only removes rows `WHERE edited=0`, preserving hand-edited lines.
3. **Index** (`index/store_sqlite.py`): `index_facets_artifact()` embeds facet statements, upserts into `vec_facets` and `fts_facets`. Search drops a facet whose `model_version` no longer matches the active summary model, so switching models never surfaces stale summaries.

**Re-summarizing after a summary-model switch runs on the ingest worker.** Search only uses facets from the active summary model, so a switch empties the conceptual layer until the library is re-summarized. `backfill_summaries()` (every startup) queues every live item whose facets are not `facets.is_current` - none, another model, or an older body - so a switch finishes on its own across restarts. "Rebuild concepts" / `POST /facets` / `enq facets` call `queue_summary_refresh(redo)`, which queues the same set (or, with `redo`, every item, forced via `facets.force`) and returns at once; it used to run `generate_all` inside the request for hours, which a restart killed. `enq doctor` reports `summaries: {model, current, stale, retrying}`. The retry sweeper (`_sweep_due`) never re-queues an artifact already waiting in the queue: a due row only moves once the worker processes it, and re-queuing it every 30s while the worker was busy produced bursts of back-to-back re-ingests ("33 chunks, 0 facets" every ~13s).

**Editing the summary (facets are user-editable).** `ingest/facets.py` exposes `edit_facet(facet_id, statement)` (marks `edited=1`, full trust, reindexes), `add_facet(artifact_id, statement, level)`, `delete_facet(facet_id)`, and `regenerate(artifact_id)` (clears skip/retry, regenerates machine lines, keeps edited ones). Each is wired to an endpoint (`PATCH /facets/{id}`, `POST /artifacts/{id}/facets`, `DELETE /facets/{id}`, `POST /artifacts/{id}/facets/regenerate`) and to a mobile Tauri command (`mobile_facet_edit`, `mobile_facet_delete`). An edit bumps the artifact's `updated_at` and pushes so it wins LWW and reaches the other device; a background generation pushes without bumping (equal-key re-apply carries the new facets to the phone). The `facets.edited` column (migration `0031_facet_edited`) is what regeneration reads to decide which rows it may delete.

**Link previews ride the snapshot too.** `read_artifact_snapshot` carries a `link_preview` child (the `link_previews` row), applied on both sides only when present, so a phone-authored snapshot never wipes the desktop's preview. The preview picture goes up as a blob by `image_hash` (`sync/client.py::_blob_hashes`), and `preview.fetch` re-pushes the artifact once the preview lands. `backfill_link_previews()` re-pushed every existing link once at startup (the `sync_link_previews_backfilled` setting). The phone's `list_artifacts` joins the preview so link tiles show the picture, site and description.

**Facets ride the artifact snapshot to the phone.** The phone cannot generate its own, so facets are a child of the artifact snapshot (`sync/snapshot.py` `read_artifact_snapshot` includes them; apply is guarded to a non-empty facet list so a facet-less snapshot never wipes locally-generated facets on an equal-key re-apply). A summary edited on the phone syncs back, and `sync/client.py::pull()` reindexes any artifact whose pulled snapshot carried facets, so a phone edit becomes findable on the desktop.

### Curate and the lens view (removed)

The SSE lens surface (`POST /lens`), the curate flow (`POST /curate`), and the
modules that powered them were deleted in Phase M. The wall has no ephemeral
split or room surface: `/search` is the retrieval path, and a saved pivot is
the only persistent view. What survives from that era is the conceptual layer -
facets still give search a conceptual channel - and the assistant path that
organises material into views through `POST /pivot/plan` and `POST /pivot/run`.

### Chat

Asking is submitted, not computed inline. `chats.ask`/`chats._submit` writes the user turn plus a pending assistant turn in one transaction, logs `ask.submitted`, and hands the work to the answer worker (`chats_worker.py`, an in-memory `Worker` thread); the request returns immediately with a visible pending turn. On startup `sweep_orphaned_pending` resolves any turn left pending by a killed worker to `failed` (Rule 2: a pending turn always resolves).

`chats_worker.compute(job)`:
1. **Route** (`assistant.route`): pick the skill (an LLM call unless a skill is forced).
2. **Answer** (`chats.py` via the skill): retrieve passages (scoped chats do not search; everything-scope uses hybrid search on chunks + facet hits) and have the model answer from them. `Answer` schema enforces grounded/cited consistency. The passage header MUST carry the artifact id (`[kind] (id: <id>) title`): the validator rejects any cited id it was not offered, so if the model only sees the title it cites the title and the turn fails validation as "cited artifacts that were not provided" (CHATBUG.1).
3. **Commit** via `_commit_answer`, which retries a transient `database is locked` a few times so a busy moment (a sync applying a batch) does not throw away a real answer.
4. **Title + topics** (`chats.py`): best-effort, non-blocking, after the answer commits. Topics regenerated from whole transcript each turn.
5. **Log + push**: emit `ask.answered` (question, answer, cited artifacts, `model`, per-stage timing) or `ask.failed` (with the error), and push the conversation to the relay.

**Conversations sync** over the same relay (`sync/snapshot.py` `read_chat_snapshot`/`apply_chat_snapshot`, LWW by `(updated_at, _device_id)`, terminal tombstone). A chat's messages/citations/topics are replaced wholesale on apply. The mobile side (`mobile_chat_send` in `desktop/src/lib.rs`) computes the answer inline with keyword retrieval + a direct LLM call, then pushes.

Structured-output gotchas (CHATBUG.1, 2026-08-20): `config.MODEL_RETRIES` is instructor's `max_retries` = TOTAL attempts, not retries-after-first; it defaults to 3, because a thinking model (e.g. opencode-go `deepseek-v4-pro`) answers in prose on the first try and needs a reprompt to emit the schema, and reprompts only fire on a validation failure so the happy path costs nothing. Do NOT switch instructor mode to fix a schema failure: opencode-go rejects `Mode.TOOLS`/`TOOLS_STRICT`/`JSON_SCHEMA` ("Thinking mode does not support tool_choice", "response_format unavailable"); `Mode.JSON` (or `MD_JSON`) is the only mode it accepts, and it works once the retries and the passage-id are right.

### Activity log (events)

`events.py` is a persisted activity log (migration `0032_events_log`, the `events` table): `emit(kind, detail, data=None, duration_ms=None)` inserts a row (never raises; trims to a bounded size), `recent(limit)` reads newest-first with the JSON `data` parsed. Emit sites: `ask.submitted`/`ask.answered`/`ask.failed` (chats + chats_worker), `capture.note` (notes.py), `facet.regenerated`/`facet.edited` (facets.py, carrying model + source), `ingest` (queue.py, only when it produced chunks/facets/entities - an empty re-ingest is not logged), `model.sent` (outbound.py, what went to remote models, added up per 10 minutes), `sync.pull`, `start`. `GET /events?limit=N` serves it; the Settings "Events"/Activity tab (`static/js/settings.js` desktop, `mobile.html` mobile) renders each row expandable to its full record with clickable artifact links, folds runs of sync pulls, and polls to stay live while open. It is local diagnostics only (never synced) and is also the decoy front door to the vault (VAULT.6). Mobile has its own `events` table in `desktop/src/sync.rs` (`log_event`/`read_events`) written by the Rust ask/facet/capture/sync paths and read by `mobile_events`.

### Sync (relay, E2E, device linking)

The desktop engine and the Android app share one E2E model: per-artifact snapshots, last-writer-wins, pushed as opaque ciphertext to a dumb relay, pulled and decrypted on-device.

- **Engine side (Python):** `sync/client.py` (`push_artifact` on every write, `push_all()` for an initial full-library backfill), `sync/snapshot.py` (LWW serialize/apply), `sync/worker.py` (SSE + timer pull). Every desktop write path (`notes.py`, `capture.py`, `trash.py` delete/restore, `api/artifacts.py` pin/tag/annotate) calls `push_artifact(id)`. Purge is local-only and final (no row left to snapshot).
- **Mutations propagate both ways (MOBFIX.5, was create-only).** The relay object is now an UPSERT: `relay/storage.py::put()` overwrites in place by name and assigns a FRESH cursor on overwrite (so a device already past the old cursor re-pulls the update), and `relay/app.py` always returns 201. The object name is still id-based (`dev/{device}/artifacts/{id}.enc`), so a later `push_artifact` for the same id rewrites the same object and the newer snapshot lands; the pull's LWW-by-`(updated_at, device_id)` then decides the winner. A mutation only propagates if it BUMPS `updated_at` - the whole current snapshot travels, so the mutation "type" is just a label. On the mobile side the same applies: every write helper must bump `updated_at` and enqueue to `mutation_outbox` (see `queue_mutation_push` in `desktop/src/lib.rs`); the invoke alone does not sync. NOTE: the hosted Railway relay must be running the upsert `storage.py` (redeploy with `bin/deploy-relay` if it still 409s).
- **Mobile side (Rust):** `desktop/src/sync.rs` reimplements the same crypto (XSalsa20-Poly1305 secretbox: nonce(24)||ct||tag; Argon2id KEK) and the relay pull/apply, so it cross-compiles for Android. `desktop/src/lib.rs` `#[cfg(mobile)] mod mobile` holds the Tauri commands: `mobile_link_qr` (persists relay_url + secret + DEK-as-hex via `save_config` into the app-data `sync_config` file), `mobile_sync` (spawns `sync_library` on a background thread, emits `sync-started`/`sync-progress`/`sync-done`/`sync-error`; falls back to the saved config when called with `config:"{}"`), `mobile_status`, `mobile_list`, `mobile_capture`/`mobile_capture_image`/`mobile_save_cropped_image` (write locally + `capture_outbox`), `mobile_outbox_push` (kicks the background outbox worker and returns at once), the write helpers `mobile_update_note`/`mobile_delete`/`mobile_restore`/`mobile_toggle_pin` (each bumps `updated_at` + enqueues a mutation via `queue_mutation_push`), the summary edits `mobile_facet_edit`/`mobile_facet_delete` (bump + queue via `push_artifact_now`), the conversation commands `mobile_chats_list`/`mobile_chat_get`/`mobile_chat_send` (`mobile_chat_send` keyword-retrieves over the local copy and calls `call_llm_mobile` directly - which sends the synced `llm_headers`, e.g. `x-opencode-session`, and surfaces a non-2xx body instead of swallowing it), and `mobile_events` (the local activity log). **The phone is local-first (2026-09-30):** no phone command waits on the network. Every write lands in the phone's SQLite and an outbox row (`capture_outbox` for new items, `mutation_outbox` for changes) and returns; the relay gets it from ONE background worker (`kick_outbox` -> `drain_outbox`, guarded by `OUTBOX_RUNNING`/`OUTBOX_AGAIN` so a burst of kicks costs one or two passes). A drain pushes each artifact once however many rows it has queued (a snapshot is the whole current state) and clears the rows it covered up to a cutoff taken before the snapshot. Offline, rows simply wait: the next write, `sync-done`, app resume or the `online` event (`window.mobileSyncAndReconcile`) kicks the worker again. Before this, `mobile_capture` and the photo saves pushed to the relay inline and `mobile_outbox_push` ran the whole drain as a plain (main-thread) Tauri command, so every save froze the UI for a network round trip. Plain `#[tauri::command] fn` runs on the MAIN thread in Tauri v2: never do network I/O in one, and make hot write paths `async fn` (`mobile_capture`, `mobile_update_note`, `mobile_save_cropped_image`) so even the local write stays off the UI thread. `mobile_sync` and the SSE listener share the `SYNC_RUNNING` guard, so only one pull runs at a time.
New Tauri commands need registration in THREE places: `build.rs`'s `commands(&[...])`, the `tauri.conf.json` capability (`allow-<command-dashed>`), AND the `generate_handler!`; a missing ACL reads as "not allowed. Command not found", not a missing handler.
- **Settings propagate desktop -> mobile, live (MOB2.9, was "as of linking" only).** The desktop pushes its effective LLM config - backend/model/url AND the provider `llm_api_key` from the Keychain - as a DEK-encrypted `lib/settings/{ts}-{device}.enc` object (`sync/client.py::push_settings`), triggered on every settings change (`settings._resync_to_relay`), on api-key store/forget (`api/settings.py`), and once at engine startup (`api/app.py`). The mobile pull (`desktop/src/sync.rs`) decrypts the newest by `updated_at` into `sync_meta['settings']`; `mobile_chat` and `mobile_settings_get` prefer it over the phone-local config, so the phone runs chat with the desktop's provider + key without re-entering anything. The Settings screen is read-only (`managed_by_desktop: true`) and reports only `llm_api_key_present`, never the value. The api_key leaving the Mac is intentional and E2E-encrypted - the phone needs it to call the provider directly. Tags/annotations are deliberately NOT mobile-writable (curation is desktop work); the phone reader is edit/delete/pin only.
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
| `chunks` | literal layer for search | text, ordinal, chunker name; `context` + `context_model` (model-written placement line, multi-chunk artifacts only) |
| `facets` | conceptual layer for search | level 0-4, statement, model_version, trust (default 0.5), `edited` (1 = hand-written/edited, protected from regeneration; migration 0031) |
| `facet_skips` | artifacts excluded from facet generation | reason: too_short/kind/text_only |
| `facet_retry` | an artifact owed a retry after a transient model failure in any ingest step (sections, facets, entities, contexts) | attempts, next_at, last_error; retried with backoff (30s doubling to 24h) by the sweeper, which re-runs the whole artifact; cleared only by a run in which no step owed |
| `events` | the activity log (migration 0032) | ts, kind, detail, JSON `data`, duration_ms. Local-only, never synced. Bounded/trimmed. |
| `secret_hits` | credential patterns found in artifact text | redacted excerpts only |
| `page_text` | extracted text per PDF page | derived, rebuildable |
| `link_previews` | what a saved link turns out to be | status, title, description, site_name, image_hash |
| `chats` | conversations | scoped to everything/artifact. pinned. |
| `chat_messages` | one turn | append-only. grounded flag. |
| `chat_citations` | what an answer was built from | message to artifact, ranked |
| `chat_topics` | concepts a conversation circles | derived, regenerable |
| `related` | links between artifacts about the same subject, naming the same thing (`via`), or judged to make the same point; `point` is the reason shown | derived at ingest, both directions, filtered to live artifacts on read |
| `sections` | the ingest model's summary of each section of a long document | derived at map-reduce ingest, searched as its own layer, staled like facets |
| `opens` | each time an artifact was opened, from where, and for which search | local only, never synced; purge deletes an artifact's rows |

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
| `vec_chunks` / `vec_facets` / `vec_entities` / `vec_sections` | sqlite-vec (vec0) tables: id + 768-dim embedding |
| `fts_chunks` / `fts_facets` / `fts_entities` / `fts_sections` | FTS5 tables: the indexed text, with the id as an unindexed reference |
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
| `ENQ_LLM_BACKEND` | `ollama` | Which backend to use: ollama, openrouter, opencode-go |
| `ENQ_LLM_MODEL` | `llama3.1:8b` | The interactive model id (chat, routing, gray-zone judge). Placeholder, known bad at structured output. |
| `ENQ_SUMMARIZE_MODEL` | (empty) | The ingestion model (facets, entities), `role="ingest"`. Empty falls back to `llm_model`. See "Model roles". |
| `ENQ_SEARCH_MODEL` | (empty) | The search model (gray-zone relevance judge), `role="search"`. Empty falls back to `llm_model`. |
| `ENQ_OLLAMA_URL` | `http://127.0.0.1:11434/v1` | LLM endpoint URL |
| `ENQ_LLM_API_KEY` | `ollama` (ignored by Ollama) | API key for hosted backends |
| `ENQ_LLM_HEADERS` | (empty) | Extra provider headers, one `Name: value` per line. Required for `opencode-go` (`x-opencode-session: <uuid>`). Synced to the phone so mobile chat can call the same endpoint. |
| `ENQ_VECTOR_STORE` | `sqlite-vec` | The search index backend. `sqlite-vec` is the only backend after the cutover. |
| `ENQ_MODEL_RETRIES` | `3` | TOTAL attempts per structured call (instructor's `max_retries`); 1 = one shot, no reprompt |
| `ENQ_PREVIEW_BROWSER` | `off` | Open a refused or script-only link once in headless Chromium (crawl4ai) |
| `ENQ_BACKUP_DIR` | (empty) | The cloud-drive folder backups go into; empty = backups off |
| `ENQ_USER_AGENT` | `Enqueue/0.2 (...)` | User agent for preview fetches |
| `ENQ_HOTKEY` | `Alt+Shift+E` | Global capture hotkey |
| `ENQ_AUTO_PREVIEW` | `on` | Whether saving a link auto-fetches a preview |
| `ENQ_TRASH_DAYS` | `30` | Trash retention window in days |
| `ENQ_SEARCH_MODEL_RANK` | `off` | The `search_model_rank` setting: the search model re-orders the top 20 results of `/search` (`retrieve/model_rank.py`). |
| `ENQ_SEARCH_JUDGE_WAIT` | `2.5` | Seconds `/search` waits for the gray-zone judge before answering without it. |
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
| opencode-go | `https://opencode.ai/zen/go/v1` | no | yes + `x-opencode-session` header |

All backends speak the OpenAI-compatible protocol.
One adapter (`OpenAICompatibleProvider`) covers all of them; it sends `ENQ_LLM_HEADERS` (the `llm_headers` setting) as extra headers.
`opencode-go` returns `400 MissingSessionID` without an `x-opencode-session: <uuid>` header - set it via `llm_headers`. The header lives in the setting, the api_key in the Keychain; both sync to the phone (`sync/client.py::push_settings` includes `llm_headers`) so mobile chat can reach the same endpoint. Mobile parses and sends them in `call_llm_mobile` (`desktop/src/lib.rs`).

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

`get_provider(local_only=False, summarize=False)` returns the configured provider.
Local-only artifacts always route to ollama, regardless of the configured backend.
This is the one rule that is not a preference: marking something local-only is a promise that its text never leaves the machine.

**Model roles.** `get_provider(role=...)` picks one of three models, all on the same backend, key and headers (`providers/base.py` `ROLE_SETTINGS`, `model_for`):
- `chat` (`llm_model`): chat answers, titles/topics, `assistant.route`, pivot planning and `derive`.
- `ingest` (`summarize_model`, UI label "Ingestion"): facets and entities. `summarize=True` is the older spelling of `role="ingest"`. The storage name stays `summarize_model` because it syncs and lives in existing settings files.
- `search` (`search_model`): the gray-zone relevance judge.
Blank `ingest`/`search` fall back to `llm_model`, so a single-model setup is unchanged. Local-only artifacts ignore every role and use the local model. A facet is stamped with the ingest model that wrote it, and retrieval drops facets whose `model_version` no longer matches the current ingest model, so changing it marks concepts stale until "Rebuild concepts". The Settings AI tab has a "Models" group (Chat, Ingestion, Search, Images) with a picker of the backend's known models. `test_model_split.py` covers the routing.

The adapter builds its OpenAI/instructor client lazily on the first model call, so `get_provider().model` is free (the search staleness checks read it on every query; building the client costs ~50 ms plus a Keychain subprocess on macOS).

The adapter uses `instructor.Mode.JSON` for all endpoints.
The old AGENTS.md specified different modes per adapter, but the code does not.
See the questions section above.

Adapter gotchas:

- The API key is resolved per provider instance, not at import, so a key stored in Settings applies on the next question.
- `llm_headers` is one `Name: value` per line; a line without a colon is dropped rather than sent.
- A call with an empty `user` folds `system` into the user message, because Gemini and others reject an empty user turn.

All model-call failures are caught in `OpenAICompatibleProvider.complete()` and translated to a `ProviderError` carrying one human-readable sentence.
The translation walks the exception chain to find the most specific OpenAI exception type, because the useful exception is often below the one that was caught.

### Which stage runs where

| Stage | Backend | Why |
| --- | --- | --- |
| Embeddings | always local (fastembed) | No network, strictly more private |
| Facet + entity generation | the **ingest** model (`summarize_model`, else `llm_model`) | The moat. Bad facets are permanent pollution. |
| Rerank | the configured backend | Low volume, high value |
| Synthesis | the configured backend | The room: through-line, tensions, view sections (internally grouped) |
| Chat answer / routing | the **chat** model (`llm_model`) | |
| Gray-zone search judge | the **search** model (`search_model`, else `llm_model`) | Runs per query; fast beats clever. |
| Chat title/topics | the interactive model | Best-effort, non-blocking |

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
| `enq backup` | Back up now into the folder chosen in Settings, and wait for it |
| `enq restore <dir or .db>` | Put a backup in place (engine must be stopped; works on the files directly, like `migrate`) |
| `enq eval-embedders [--models a,b]` | Compare embedding models on both evals and suggest each one's floor bars |
| `enq eval-real [--update-baseline]` | Score your real searches against your library; fails when a baseline query now fails |

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
GET    /resurface                   today's older note for the wall (wall item + reason), or null
GET    /greeting                    the wall's greeting for the current four-hour bucket (cached or fallback)
GET    /artifacts                   list, newest first. ?limit&offset&order&pinned
GET    /artifacts/{id}              detail, body, annotations, facets, versions
GET    /artifacts/{id}/text         readable text, with page numbers for PDFs
GET    /artifacts/{id}/connections  per passage, the other notes that say something close
GET    /artifacts/{id}/blob         original bytes
GET    /artifacts/{id}/versions/{vid}  one saved body
GET    /artifacts/{id}/find?q=      phrase locations in a PDF (page fractions)
GET    /artifacts/{id}/preview-image  link's stored picture
GET    /artifacts/{id}/page/{n}     rendered PNG of a PDF page
GET    /search?q=                   hybrid search, no model calls; kind/time words become filters (returned as `filters`)
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
GET    /events?limit=N              the activity log, newest first, each with its full record
GET    /backup                      backup folder, detected Proton Drive folders, last backup, the kept backups
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
POST   /pivots/manual                 create a view arranged by hand (optionally from another view's groups)
PUT    /pivots/{id}/layout            replace a hand-arranged view's headers and order
POST   /pivots/{id}/remove            remove artifacts from a locked view (recorded; no recompute)
POST   /pivots/{id}/restore           put removed artifacts back in the groups they left
POST   /pivots/{id}/refresh           Rebuild: re-run the spec and re-freeze the result
GET    /pivots/{id}/open              the frozen view, cards hydrated fresh
POST   /chunk                        rebuild all chunks
POST   /facet-gate                   re-evaluate facet eligibility
POST   /facets                       generate facets
POST   /artifacts/{id}/facets/regenerate  regenerate an artifact's summary (keeps edited lines)
POST   /artifacts/{id}/facets        add a hand-written summary line
PATCH  /facets/{fid}                 edit one summary line (marks edited, reindexes)
DELETE /facets/{fid}                 delete one summary line
POST   /index                        rebuild the search index
POST   /reprocess                    re-extract, re-chunk, re-index everything
POST   /ingest/wait                  block until queue drains (for tests)
POST   /artifacts/{id}/opened        record an open (source, and a search open's query + rank)
POST   /eval/real                    run the real-search eval (?update_baseline=true stores it)
PUT    /settings/api-key             store key in Keychain
DELETE /settings/api-key             remove key from Keychain
PATCH  /settings                     update writable settings
POST   /backup                       back up now (background; GET /backup shows it land)
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
4. **Section summaries** (the long-document layer). For a document too long to read in one pass, the ingest model's summary of each ~10k-character section, embedded and keyword-indexed. A long PDF becomes findable by what each part is about, not only by its sentences; in chat a section hit pulls the chunk from that part of the document (section i of n sits about i/n of the way through).

Each layer has its own vec0 + FTS5 tables (`chunks`, `facets`, `entities`, `sections`); facets, entities and sections share one per-artifact indexing path (`_index_layer_artifact`). See the index-tables section.

**Query lowers concepts toward artifacts.**
`retrieve/candidates.py::search_results` runs eight legs, each a ranked list, and fuses them:

1. **Dense** - query embedding against chunk vectors.
2. **Keyword** - FTS5 BM25 over chunk text, title column weighted 10x (`bm25(fts_chunks, 1.0, 10.0, 1.0)`).
3. **Trigram** - the `fts_chunks_tri` trigram table for substrings and partial words.
4. **Fuzzy** - `SequenceMatcher` over short fields (titles, entity names, current annotation lines) for one-edit typos trigram cannot see (R.7).
5. **Exact phrase** - quoted phrases pinned (R.10).
6. **Facets** - the conceptual channel, hits weighted by trust (`score * trust * 2.0`).
7. **Entities** - the named-thing channel.
8. **Sections** - long-document section summaries, weighted like an untrusted facet and staled the same way.

Fuse with RRF (canonical k=60, M.5g), apply the R.8 recency multiplier, optionally rerank the top window with the bge-reranker cross-encoder (R.9, off by default), then roll up to one row per artifact.

### Three granularities

| Layer | Unit | Powers |
| --- | --- | --- |
| Literal | chunk | Search, citation to passage |
| Conceptual | facet | Search's conceptual channel, weighted by trust |
| Named-thing | entity | Search's world-vocabulary channel |
| Section | section summary | Long documents found by what each part is about |

### The relevance floor (Q.3, in progress)

Dense kNN always returns a nearest neighbor however far, so a no-match query would return a wall. The floor is a two-tier gate on the raw legs (not the fused score): any lexical leg or `dense_similarity >= KEEP_ABOVE` keeps; `< DROP_BELOW` drops; the gray zone is settled by one batched model judgment (`judge_gray_zone`), failing open. A search with zero survivors returns `[]`. `chats.passages()` applies the same `_floor_verdict` gate (Q.5 chunks, Q.10 facets/entities) so the answer path refuses honestly. Calibration (the two constants + the gray-zone judge) is the active work in `docs/PLAN.md` Phase Q.

### Retrieval design notes

These used to live as long comments in `retrieve/candidates.py`, `index/store_sqlite.py` and `chats.py`.

**Relevance floor (Q.3 / Q.3b / Q.7).**
One dense threshold cannot work: the eval showed the weakest real matches (cosine ~0.518) sit below the strongest gibberish neighbors (~0.668).
So the floor has two bars on the true-cosine scale, `KEEP_ABOVE = 0.68` and `DROP_BELOW = 0.40`, and a gray zone between them decided by one batched model call.
The bars are on the scale of a PREFIXED query (see "Query prefix"): the prefix lowers every query-to-passage cosine by about 0.07 (real matches: weakest 0.516 -> 0.427, median 0.624 -> 0.564; strongest gibberish 0.665 -> 0.597), so the old unprefixed bars (0.75/0.45) moved down by the same margin.
The bars live per model in `config.EMBED_MODELS` (`keep_above`, `drop_below`) and are read into `KEEP_ABOVE`/`DROP_BELOW`; recalibrate them whenever the model or its prefix changes: `evals/queries.yaml` real-match minimum must stay above `DROP_BELOW`, and every "nothing" query's best hit below `KEEP_ABOVE` (`enq eval-embedders` prints fitted values).
The bars are start values for the Phase Q.4 eval (all 42 real-match queries passing, Nothing-OK toward 8/8), not final answers.
Lexical legs that bypass the floor: chunk FTS5 keyword (with prefix recall), fuzzy, exact phrase, and the FTS5 keyword branch of a facet or entity.
The trigram leg is recall only, not lexical (Minh's decision): a 3-character overlap like "pie" in "pieces" is noise, and partial words are already covered by the keyword prefix query.
A dense-only facet/entity hit is a semantic neighbor and faces the gate like a chunk (Q.7 fixed a leak where "pecan pie recipes" surfaced an unrelated note through an entity vector at 0.409).
The gray-zone judge (`judge_gray_zone`) is fail-open (a raising or malformed call keeps what it did not clearly judge), is cached in `derived_values` (scope `gray_judge`) per (query, artifact_id, model_version), and is shown each item's facets because they state its subject better than one snippet.
Floor survivors keep their order: the floor removes, it never reorders.

**Query prefix.**
bge v1.5 is trained to read a search with `config.EMBED_QUERY_PREFIX` ("Represent this sentence for searching relevant passages: ") in front, and passages bare.
Every search embeds through `embed.embed_query` (the dense leg of `/search`, chat passages, lifted claims); indexing uses `embed()` with no prefix.
Passage-to-passage similarity (related notes, `ingest/related.py`) passes `as_query=False` to `search_dense` so it stays on the unprefixed scale `RELATED_MIN` was set on.
Measured on adding it: cross-domain 3/12 -> 7/12 (with the recalibrated floor), main eval MRR 0.928 -> 0.945 at unchanged recall.

**Embedding models.**
`config.EMBED_MODELS` is the registry the engine can run on, selected by `ENQ_EMBED_MODEL` (default bge-base-en-v1.5): per model its index `version` (a change triggers the automatic index rebuild in `index/bootstrap.py`), `query_prefix`, `doc_prefix` (prepended to every indexed passage and to passage-to-passage comparisons, e.g. nomic's "search_document: "), and its floor bars.
Only 768-dimensional models fit, because the vec0 tables are built at that width; another width is a migration.
To evaluate a switch, run `enq eval-embedders` on a machine that can reach Hugging Face (each candidate downloads once): it lists the 768-d fastembed candidates in `eval_embedders.CANDIDATES` (bge-base, nomic-embed-text-v1.5, arctic-embed-m and m-long, gte-base, jina-v2-base-en) with main recall@10/MRR/Nothing-OK, cross-domain passes, and fitted bars, with the gray-zone judge held fail-open so it compares embedders only.
A winner joins `EMBED_MODELS` with its fitted bars; then set `ENQ_EMBED_MODEL`, let the index rebuild, rerun both eval gates and `enq eval-real`, and refresh the committed baselines.

**Dense score scale (Q.2b).**
vec0 stores L2 distance over unit-norm embeddings, so cosine is `1 - d^2/2`, clamped to [0, 1].
This changes the reported number only, never the ranking.

**Fusion.**
RRF uses the canonical k=60 (Phase M.5g; the old k=1 only matched the removed lens threshold).
RRF reads ranks only, so the 10x bm25 title weight (R.5) acts through keyword order: on an RRF tie, the keyword leg reorders only when its best beats the runner-up by `KEYWORD_MARGIN` (20%).
FTS5 bm25 weights map to every column including UNINDEXED ones, hence `bm25(fts_chunks, 1.0, 10.0, 1.0)` on `(chunk_id, title, text)`.
The fts text drops a leading `# {title}` heading so the title term counts only in the title column.
Trigram hits are appended after the fused list with score 0: fusing them regressed the R.5 title test, and substring noise ("grow" in "growing") would outrank real hits.

**Title pin.**
An unquoted search that IS an artifact's title (case, punctuation and spacing aside) puts that artifact first, then titles containing the query as a whole-word phrase (two or more words only), newest first, ahead of the fused list (`_title_hits`, `why: "title"`).
Fusion alone does not honour a typed name: "The good life" ranked the note called The Good Life second, behind one whose summary sat closer.

**The judge never holds a search.**
`_apply_floor` waits `config.SEARCH_JUDGE_WAIT_S` (2.5s, `ENQ_SEARCH_JUDGE_WAIT`) for the gray-zone judge (`_judge_in_time`); past that the search answers from cached verdicts, keeps what was never judged as `loose` (shown last, under the page's line that says so), and the judge finishes in the background and caches, so the same search is exact next time.
At most two judges run on past their search (`_JUDGES`); a search that finds both busy answers without one.
A thinking model with reprompts once held a search for an exact title for 94 seconds.
Chat's passages still wait for the judge: an answer is computed off the request anyway.

**Fuzzy leg (R.7).**
`FUZZY_BASE_SCORE = 0.02` sits between a single-leg rank-1 RRF hit (~0.016) and a dual-leg one (~0.033), so a typo match wins only when the hybrid was weak.
It is a full Python scan of titles, entity names and current annotations, gated by `_needs_fuzzy` (PERF.1), and pruned by upper bounds on `SequenceMatcher.ratio`.

**Recency (R.8).**
A note touched today scores 1.5x, one from 180 days ago is unchanged; relevance still dominates.

**Usage.**
`opens.usage_boost` multiplies a hit's fused score by `1 + 0.2 * use / (use + 3)`, where `use` is the decayed count (tau 90 days) of the artifact's opens (any source) and chat citations, plus 3 if it is pinned.
It saturates below 1.2x and stays under the recency boost, so relevance still decides and one burst of use fades; it only reorders, never adds or floors a hit.
The committed evals have no opens, so it cannot move them; `enq eval-real` is where to watch it.

**Rerank (R.9).**
The cross-encoder runs on CPU only: a second CoreML model in the process leaks contexts until the OS kills it (SIGKILL, "Context leak detected").

**Staleness.**
A facet or entity hit counts only while its `body_version` matches the artifact's latest `artifact_versions` row and its `model_version` matches the current SUMMARY model (not the chat model; keying it to the chat model once voided every facet on a chat-model swap).

**Chat passages.**
At most `CHUNKS_PER_ARTIFACT` chunks per note so one long note cannot take the whole `PASSAGES` budget (the "do I have notes on a president" case).
A facet or entity hit pulls its artifact's opening chunk in, so the answer has literal text to stand on.
A scoped chat does no retrieval: the artifact is the candidate set.
A two-sided question is searched per side and interleaved (`retrieve/decompose.py`), because one embedding of "X vs Y" lands on whichever side dominates.

### Cross-domain eval

`evals/cross_domain.yaml` holds 10 queries phrased in one field (software, teams, habits) whose target note is from another (a willow in a storm, a relay baton, mise en place), plus 5 lexical decoys that share the queries' words but not their idea.
Each target must not contain its query's key words; `tests/test_eval_cross.py` enforces that, so the suite can only be passed on meaning.
`enq eval-cross` (`src/enqueue/eval_cross.py`) loads the suite plus the 50-note main corpus into `evals/test-data-cross/`, then runs every query through `search_results` four times: `chunks` (chunks only), `enriched` (plus facets and entities), `lifted` (plus query lifting) and `ranked` (plus model re-ranking). A query passes when its target ranks in the top 3.
Facets, entities, section summaries, lifts and ranking orders come from the committed fixture `evals/cross_domain_facets.json` (`{"facets": {artifact_id: [...]}, "entities": {artifact_id: [...]}, "sections": {artifact_id: [summaries in order]}, "lifts": {query_id: [...]}, "ranks": {query_id: [artifact ids, best first]}}`; facets and entities are stamped with the current ingest model on load so the staleness check keeps them; lifts and ranking orders are served from the fixture, so the eval never calls a model; `bin/check-eval-cross` fails if any layer scores below the one before it). `enq eval-cross --generate-facets` rewrites the whole fixture with the live ingestion and search models; after a facet-prompt or ingest-model change, regenerate it, then refresh the baseline with `bin/check-eval-cross --update-baseline` and commit both.
Two targets are long: `pad_with` prepends main-corpus documents so the idea sits ~56,000 characters in, past the read limit, which only map-reduced ingestion can reach (`test_long_targets_put_their_idea_past_the_read_limit`).
This suite is separate from the main 50-note eval on purpose: adding its notes there would shift the main baseline.

### Real-search eval

The two committed evals use made-up queries; this one uses the person's own.
Every time a search result is opened, the interface records the query and the result's rank (`opens`, source `search`).
Each distinct query (case- and space-insensitive) becomes a case expecting any live artifact opened from it, and passes when one of them ranks in the top 3 of the live `/search` rollup (`eval_real.py`, same `PASS_RANK`/`score` as the cross-domain eval).
It runs inside the engine against the real library (`POST /eval/real`, `enq eval-real`), because the cases are private: they never leave the machine and are never committed.
The baseline is stored at `~/.enqueue-poc/evals/real-baseline.json`; `enq eval-real` exits non-zero when a query that passed there fails now, and `--update-baseline` replaces it.
Run it on the laptop before and after any retrieval change (model swap, re-rank, ranking signals).
Its blind spot: a person only opens what search already showed, so it measures ranking among surfaced results, not recall of notes search never surfaced; the cross-domain eval covers that.

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

Two lanes on that one thread (`worker.py`, 2026-09-29).
`submit(id)` is the person's own work (a capture, an edit, a preview "Try again") and always runs first; `submit_background(id)` is bulk upkeep (the summary backfill/refresh, the retry sweeper, `submit_all`, `submit_images`) and waits until no foreground item is queued.
Before this, a library-wide summary refresh put a fresh capture hours behind it.
The I5.1 coalescing counts only copies submitted AFTER the running one as "newer", so an older background copy still waiting never makes a fresh foreground run skip its model calls.

### Per type

| Type | Path |
| --- | --- |
| Web page (link) | save URL only. Preview is opt-in (one request). Text comes from preview metadata. |
| PDF | pymupdf extracts text per page. Pages rendered as PNG on demand. |
| Image | stored as blob; a vision model describes it at ingest (K.11) and the description is chunked. A failed describe marks it `failed` and shows in `/doctor`. |
| Note | body is markdown, chunked directly. |
| File (text) | decoded and chunked (txt, md, csv, json, html). |

### Dedupe

Content hash (sha256) on the extracted bytes or URL.
Same content captured twice does not create a second artifact.
Re-saving an existing artifact moves it to the front of the wall (updates `updated_at`).

### Secret scanning

`ingest/secrets.py` knows the credential shapes: password assignments, AWS access keys, private keys (the whole PEM block), bearer tokens, Slack tokens, GitHub tokens.
`scan` records a note's or a link page's hits for the Settings list (excerpts with the value replaced by `***`) and marks the artifact `status = 'text_only'`.
`redact` blanks the same shapes out of every prompt sent to a remote model, in `OpenAICompatibleProvider.complete`, the one place every structured call passes, so a credential in a note, a PDF or a page never leaves the machine while the rest of the text still gets its facets and entities.
The phone does the same in `call_llm_mobile` (`sync::redact_secrets`); keep the two pattern lists in step.
A local model is sent the text as written.

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
6. **Only public addresses are fetched.** `preview._refuse_private` runs before every request, redirects included, and refuses a host that resolves to a loopback, private, link-local or otherwise non-global address, so a saved link (or one synced from the phone) can never read the router, another local service or the engine itself.

Auto-preview is controlled by the `auto_preview` setting (default on).
When on, the ingest worker fetches the preview in the background after capture.

**Browser fallback (`preview_browser`, default off).**
Some sites refuse any non-browser client (Medium's bot wall answers 403 to httpx every time, whatever the user agent).
With the setting on, a refusal (401/403), or a page with no title and no description until its scripts run, is opened once more in headless Chromium through crawl4ai (`preview._read_browser`), and its HTML goes through the same `parse` and `_extract_body`.
The line from rule "Not a browser string" still holds: a real browser loading a page is not a disguise, faking one is.
So none of crawl4ai's anti-detection is enabled (no `enable_stealth`, `magic`, `simulate_user`, `override_navigator`, or random user agent); a page that still refuses a real browser stays refused.
crawl4ai's cache lives under the data dir (`CRAWL4_AI_BASE_DIRECTORY`), not `~/.crawl4ai`.
A missing Chromium fails with "run bin/setup" rather than silently.

**A shared link's name is its title.**
A capture of exactly "Title" on one line and the address alone on the next (what a share sheet or "copy link" hands over) saves the line as the link's title, not as a note (`capture.html` `splitLink`, `sync.rs` `shared_link_title` for the phone, `LinkCreate.title`).
Before this, the page name landed as the link's first note and read like something the person wrote.

---

## Backups (Proton Drive)

`backup.py`, decided 2026-09-30. The live library stays at `~/.enqueue-poc`; the cloud drive only ever holds backups.
A live SQLite file in a File Provider folder is unsafe: WAL is three files a sync client can upload mid-write (a torn copy), the drive can evict a quiet file to a cloud-only placeholder under the engine, and the ~400 MB file (mostly the search index) would re-upload on every write.

- `backup_dir` setting (empty = off; Settings > Storage offers the detected `~/Library/CloudStorage/ProtonDrive-*` folder). Backups go in `<backup_dir>/Enqueue Backup/`.
- A run: `VACUUM INTO` a `.partial` file (one consistent snapshot while writers continue), empty every index table from `store_sqlite._DDL` and delete `index_meta.embed_version` in the copy, `VACUUM`, `PRAGMA integrity_check`, then `os.replace` into `library/enqueue-YYYY-MM-DD.db` - the drive never sees a half-written file. Blobs are mirrored by hash (copy only new ones); `settings.json` and `keyring.json` (DEK wrapped under the recovery phrase) are copied; `manifest.json` describes the latest. The API key stays in the Keychain, never backed up. Measured on a 410 MB library (332 items): a 5.7 MB copy in 2.4 s; a restore rebuilt the index in ~20 min, during which browsing works and search waits.
- When: the scheduler thread checks hourly (first after 5 min) and runs once a day if the change stamp (counts + latest timestamps of what a person writes) moved; a clean engine shutdown runs one more; choosing a folder runs the first at once; `POST /backup` / `enq backup` on demand. Keeps 7 daily + the newest of 4 earlier weeks.
- `restore()` (`enq restore`): refuses while the engine answers on 127.0.0.1:8787, quick-checks the file, moves the live `enqueue.db` (+ wal/shm) to `before-restore-<time>/` (never deleted), copies the backup in, fills missing blobs, and fills `settings.json`/`keyring.json` only when absent (a new Mac). The next start migrates and, with no recorded embed version, rebuilds the index (index/bootstrap.py).
- Events: `backup` (with the record) and `backup.failed` in the Activity log.

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
| `tests/test_chats_worker.py` | The answer worker: submit/compute, orphaned-pending sweep, failure path. |
| `tests/test_ingest.py` | Secret scanning, proper noun extraction, facet/judgment validators. |
| `tests/test_facet_retry.py` | Facet retry/backoff; a hand edit surviving regenerate; annotations feeding generation. |
| `tests/test_model_split.py` | `get_provider(summarize=True)` routing to `summarize_model` vs `llm_model`. |
| `tests/test_sync.py` / `test_snapshot.py` | E2E sync: artifact/chat snapshots, LWW, facets riding the snapshot, apply guards. |
| `tests/test_providers.py` | Malformed HTTP responses, error translation, exception chain walking. |
| `tests/test_settings.py` | API key never touches disk, keychain guards, extra headers parsing. |
| `tests/test_migrations.py` | Fresh DB reaches head, pre-migration DB is adopted, capture can never hold a body. |
| `tests/test_trash.py` | Delete is reversible, purge destroys, retention window, blob sharing guard. |
| `tests/test_preview.py` | Parse, image URL resolution, fetch guards, preview indexing, the browser fallback. |
| `tests/test_model_pause.py` | The usage-limit pause: trip on 429, no call while paused, retries rescheduled, lifted by a new key. |
| `tests/test_backup.py` | Backups: copy without the index, change stamp, retention, no partial files, restore sets the library aside. |
| `tests/test_md_roundtrip.py` + `tests/js/md_roundtrip.js` | md() and htmlToMd() round-trip a note unchanged (run under node). |

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
# Fresh machine: install/verify the toolchain (Rust >= 1.88, uv + Python 3.12, Node).
# Idempotent, no sudo. Add --android for the mobile toolchain. Fixes the
# "rustc <ver> is not supported ... requires rustc 1.88.0" build error.
bin/setup

# Install dependencies (uv manages everything)
uv sync

# Run the engine
uv run enq serve

# Run the CLI against a running engine
uv run enq health
uv run enq search "antifragility"

# Run tests (parallel; pytest-xdist)
uv run pytest -q -n auto

# Format check
uv run black --check src/ tests/

# Lint gate, seconds (what the pre-commit hook runs)
bin/verify --fast

# Full verification gate (lint + JS parse + pytest + contrast + desktop Rust + Android compile)
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

`bin/launch desktop` always rebuilds the shell with `cargo build` first (incremental, near-instant when unchanged; a compile error stops it rather than launching a stale binary), kills the shell and engine, writes the repo path to `~/.enqueue-poc/repo`, launches the shell, waits for the engine health check, and brings the window to front. `bin/launch mobile` requires a real phone on USB (USB debugging on) - an emulator is rejected on purpose - then does a one-shot build + `adb install` + launch and EXITS (no `cargo tauri android dev`, so no held Gradle lock).

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

`bin/verify` runs JS parse, pytest, contrast check, the desktop Rust unit tests (`cargo test --lib` on the host target, run whenever any `desktop/**/*.rs` changed since the Android check builds for the android target and cannot run tests), and an Android build check. The Android check auto-detects the SDK/NDK from the standard install location (`~/Library/Android/sdk`, newest `ndk/*`) when `ANDROID_HOME`/`NDK_HOME` are unset (FIX.3), so it runs on a plain `./bin/verify` instead of silently skipping; it skips cleanly only when no SDK/NDK exists on disk. When Rust, Kotlin, or `desktop/gen/android/**` files changed, it runs the full `cargo tauri android build` (GATE.1) rather than just `cargo check --lib`, because `cargo check` never compiles Kotlin/gradle and a broken `.kt` used to pass the gate green. A green `bin/verify` is still NOT proof the app runs on a device - it proves the code parses, tests pass, the palette meets contrast, and the app compiles for Android. The desktop window (`bin/launch desktop`) and a real device (see "Verifying the Android app" above) are the only proof the app runs. A pre-commit hook (`.githooks/pre-commit`, activated via `git config core.hooksPath .githooks`) runs `bin/verify --fast` (black, ruff, JS parse, contrast; about two seconds) when code is staged and blocks the commit on failure; docs-only commits stay instant.
CI (`.github/workflows/ci.yml`) runs on pull requests and on direct pushes to main (a PR's merge commit is not re-checked).
A `changes` job decides which of five parallel jobs run, from the files the change touches: `test` (`bin/verify --fast` + `pytest -n auto`, any Python/tests/bin change), `eval` and `eval-cross` (the two eval gates, only when retrieval, index, ingest or what feeds them changed), `rust` (`bin/verify --desktop-tests` on Linux, desktop Rust changes) and `android` (`bin/verify --android`, the full debug apk, any `desktop/` change).
A run takes as long as its slowest relevant job; a docs-only change runs nothing. A job skipped by its filter counts as passed, so any of them can be required.
uv, the fastembed models, Cargo and Gradle are cached between runs, and superseded runs are cancelled. Changing the workflow or `bin/verify` runs every job.

## Working agreement: verification split + commit discipline (do not skip)

Verified work has been lost twice to uncommitted-then-reverted working trees, and a broken mobile module was committed after `bin/verify` was skipped. Two rules prevent the recurrence:

1. **Lint gates every commit (enforced by git), and CI gates every PR.** The pre-commit hook runs `bin/verify --fast`; CI runs the tests, both evals, the desktop Rust tests and the Android build, each when its files change. Run the full `bin/verify` locally when you can, since it is faster than waiting on CI. A broken `cargo check --lib --target aarch64-linux-android` is a failure, not a "device blocker."

2. **Commit the same turn work goes green - never leave verified code uncommitted.** The loss happened in the gap between "it works in the working tree" and "someone commits it." Close that gap: as soon as `bin/verify` is green, the working tree is committed (the human commits after each green turn; or, if agreed, an agent commits its own verified work to a branch the human reviews). Uncommitted verified work is treated as work that will be lost.

**The verification split** (why "I can't run the device" is never a reason to stop): implementing code, `cargo check`, and `bin/verify` are HEADLESS and need no hardware - do all of it. The final runtime check on a physical phone / desktop window ("Done when: on the device...") is done by the HUMAN TESTER, who has the device. So the loop is: agent implements + `bin/verify` green + commit, leaving the box UNCHECKED with a "code-complete, pending device verify" note; the human runs the device pass and checks the box. Never stop a turn merely because the device runtime is out of reach - there is almost always headless implementation + gate + commit work to finish first.

---

## Verifying the Android app on a device (headless, over adb)

A harness with no macOS display can still drive the PHYSICAL PHONE or a headless EMULATOR end to end over adb, and did on 2026-08-19 (proved MOBRENDER.1's full sync/decrypt/apply/render path from the shell alone). "Headless" means no desktop window; it does NOT block device verification - the device is the display. Default to driving it yourself; escalate to the human ONLY for a truly visual check that adb cannot see (below).

**NEVER run raw `cargo tauri android dev`.** It is a dev-server WATCH LOOP that never exits - it hangs indefinitely (often on "pick a device"), holds the Gradle lock so the next `cargo tauri android build` deadlocks, and piping it to `| tail` makes the whole command look frozen because tail waits for an EOF that never arrives. It is a hot-reload dev tool, not a build. For verification use a ONE-SHOT `cargo tauri android build --debug` then `adb install` (below), which exits and lets you drive the app over adb. Both `bin/launch mobile` and `bin/launch emulator` now do exactly this (build, install, launch, EXIT), so they are safe to run; only the raw `cargo tauri android dev` is banned.

The adb toolkit (phone on USB or emulator, package `com.sudohnim.enqueue`):

- **Build + install:** `cargo tauri android build --debug --target aarch64` (a one-shot that EXITS), then `adb install -r desktop/gen/android/app/build/outputs/apk/universal/debug/app-universal-debug.apk`. The apk loads the embedded frontend at `tauri.localhost`: `frontendDist` (`src/enqueue/static`) is compiled into the Rust `.so` by `generate_context!` and served from there, so a web-only edit (mobile.html, js, css) reaches the device on the next build with no copy step. `gen/android/app/src/main/assets` is NOT the webview source (verified 2026-09-26: a stale `mobile.html` planted there got packaged into the apk but never served) - never sync static files into it; a copy there only bloats the apk. It runs unplugged: `devUrl` is OMITTED from `tauri.conf.json` on purpose (RELEASE.1) - setting it to `""` crashes tauri-build ("relative URL without a base"), and a real LAN dev URL makes a standalone cold launch show a "Failed to request .../mobile.html" error page. So never add `devUrl` back, and never put `apk`/`aab` in `bundle.targets` (invalid enum). A SIGNED release (`cargo tauri android build`, no `--debug`) needs `desktop/gen/android/key.properties` (or the `RELEASE_*` env vars) + the keystore; the gradle `signingConfigs.release` is guarded by `hasReleaseSigning` so debug stays unsigned. A release apk is NOT debuggable (no run-as / CDP) - always verify on the DEBUG apk.
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

### Index rows are found through their source rows

An index row (vec0 or FTS5) carries only its chunk/facet/entity/section id, so the only way to find a row's index entries is through the row.
Anything that replaces or deletes rows must drop their entries while the rows still exist: `ingest/queue.py` drops an artifact's chunk entries before re-chunking it, and trash delete/purge and vaulting drop an artifact's entries before deleting its chunks.
Before that fix every reprocess, edit and retry left a full set of orphans behind (one library reached 52,891 orphaned chunk rows for 1,071 chunks), and orphans still take slots in a search's shortlist; a vaulted note's text also stayed in `fts_chunks`.
Ingest skips a trashed, vaulted or embedded artifact instead of chunking it back.
`queue.prune_index` runs each time the ingest queue drains (the `Worker` `on_idle` hook) and once at engine startup: it deletes chunks of trashed or vaulted artifacts, removes any entry whose row is gone (`store.prune_orphans()`; regenerated facets, entities and sections take new ids), and indexes any row with no entry (`store.index_missing()`, e.g. after an interrupted rebuild).
`enq index` rebuilds every layer from the tables.
`enq doctor` compares the chunk index with `indexable_chunk_count` (chunks of live artifacts), not every chunk.
A full rebuild and the prune run on the ingest worker's thread between two artifacts (`Worker.run_exclusive`, ahead of anything queued): run beside ingest they fought it for SQLite's single writer, failed with "database is locked", and left the index half-built with search blocked.

### Find inside an artifact is ours, not the webview's

The shell window has no Edit menu, so the webview never binds a find of its own.
Cmd/Ctrl+F on any artifact page opens the find field in the pill (`openFind` in `static/js/artifact.js`): a PDF asks the engine where the words are (`GET /artifacts/{id}/find`) and draws boxes over the page pictures; everything else is searched in `.bodycol` and marked with the CSS Custom Highlight API (`::highlight(enqueue-find)`), never `<mark>` elements, which the editor would serialise into the note on the next save.
`restorePill` clears the marks, so closing the field by any road removes them.
A match cannot span two text nodes (a phrase half in bold is not found).

### A view can be arranged by hand (no recipe, no model)

One view concept, two ways to make it. A manual view is a `saved_pivots` row whose spec is `{"manual": true, ...}` and whose frozen `result_json` IS the arrangement: headers in the person's order, each with its artifact ids in the person's order (`pivots_saved.save_manual` / `set_layout` / `is_manual`). An empty header is kept; an artifact sits under one header only; two headers cannot share a name (case-insensitive).
`POST /pivots/manual {name, from_id?}` creates one (`from_id` copies another view's groups - "Arrange by hand" on an assistant view); `PUT /pivots/{id}/layout {groups}` replaces the WHOLE layout and is the only write the page makes, so add, drag, rename, move and delete share one path. `/open` never runs a recipe for it and `/refresh` is a 409. `GET /pivots` rows carry `manual`; `all_specs` carries `manual_ids` (membership for the artifact drawer, in the same single query).
The page is `static/js/manual.js` (`renderPivot` hands over when `spec.manual`). It renders first and saves behind (`manualSave`, serialized; a failed save reloads the view), and reads the layout back from the DOM (`manualReadDom`), so a drag and the state cannot disagree. Dragging is pointer events, NOT HTML5 drag and drop (the desktop WebView handles that inconsistently and owns file drops): the real node moves as the pointer does, a clone rides the pointer, neighbours slide with a small FLIP, and a header drag folds every shelf to its header. Keyboard: arrow keys on a grip, Alt+Left/Right on a tile, and the move button's header chooser.
`push_pivots` keeps a manual view's order (recipe views sort their ids), so the phone's Custom mode shows the same shelves in the same order. The phone does not arrange (desk work).

### A saved view is locked; removing and restoring edit it in place

Opening a saved view serves its frozen `result_json`; it never recomputes on its own (not on open, not on window focus). `Rebuild` (`POST /pivots/{id}/refresh`) is the one deliberate re-run, and the only path that pays for model judgments.
Removing a card (`POST /pivots/{id}/remove`) edits the frozen groups AND records the removal twice: in the spec's `excluded_ids` (the Removed shelf draws from it, and a Rebuild honours it) and in the result's `removed` map of id -> the group it left. Restoring (`POST /pivots/{id}/restore`) puts the card back in that group and ends the exclusion; `set_result` carries the map across a Rebuild.
A card with no recorded group (an old exclusion, or an add) is placed by `pivot.place_from_cache`, which walks the spec's steps reading only the row and the derive cache - never a model - and falls back to "" ("Not determined").
`pivot.run` folds group keys that differ only in case or spacing ("Non-fiction" / "non-fiction") into one group, shown in the commonest spelling.
On the page, `pivotState` is cleared in `teardown()` and every late re-render checks `onSavedView(id)`: a view left set used to redraw itself over whichever page was open when the window regained focus.

### The phone's fingerprint lock is two separate locks (BIO.1)

Both are checked by the Android shell (`MainActivity.kt` + `Biometrics.kt`, `androidx.biometric`), reached from the page through the `EnqueueAndroid` bridge.
A prompt answers later, so `setAppLock` / `vaultSecretCreate` / `vaultSecretRead` take a request id and answer through `window.__enqLockReply(id, {ok, reason, secret?})`; `lockStatus()` is the one synchronous call.

**The app lock** (Settings > Lock, a `SharedPreferences` flag) is a gate, not encryption: the phone's `library.db` is still plain SQLite.
It is a NATIVE cover (`res/layout/view_app_lock.xml`) added to the decor view in `onCreate`, so the library never paints first and nothing depends on the page booting.
It accepts a fingerprint or the phone's screen lock (`BIOMETRIC_WEAK | DEVICE_CREDENTIAL`, the one fallback combination every supported Android version accepts), so a sensor lockout cannot shut the owner out.
It asks once per trip to the front and locks again after `LOCK_GRACE_MS` (60s) in the background, so the camera, the file picker or a link opened in the browser do not ask again on the way back.
If the phone has no fingerprint and no screen lock left, the lock switches itself off instead of trapping the owner.
While it is on, the recents thumbnail is hidden (`setRecentsScreenshotEnabled(false)` on Android 13+, `FLAG_SECURE` below).
`QuickCaptureActivity` is not locked: it can only add a thought.
The lock button is an `AppCompatButton` by name, because under the Material theme a plain `<Button>` becomes a `MaterialButton` that ignores `android:background`.

**Vault fingerprint unlock** (the "Open with fingerprint" switch INSIDE the vault, never in open Settings, so nothing outside says a vault exists) does not hand the vault key to Kotlin or the page.
The Android Keystore holds an AES-GCM key that needs a strong fingerprint for every use and dies when a new fingerprint is enrolled; it guards a random 32-byte secret.
The Rust side keeps the vault key sealed under that secret in the app-data file `vault_bio` (`sync::vault_bio_seal` / `vault_bio_open`, commands `mobile_vault_bio_enroll` / `_unlock` / `_clear`), bound to the PIN's own wrap by `vault_meta_tag`.
So a PIN changed on ANOTHER device turns fingerprint unlock off here ("changed"), while a PIN changed on this phone re-points the record (`vault_bio_retag`); a newly enrolled fingerprint answers "invalidated" and both halves are cleared.
The PIN always still works, and enrolling needs an unlocked vault.
The prompt's words come from the page, because the vault's door is the "Diagnostics" decoy and the prompt must not name it.
The two locks are deliberately not merged: the touch that opens the app does not open the vault, which keeps locking itself whenever the app leaves the screen.
The page's lock-on-hidden handlers skip while a prompt is open (`fingerprintPromptOpen()`), since the prompt itself can report the page hidden.

**The switches and their dialogs** live in `mobile.html`.
Each lock is one `.mswitch-row` (the whole row is a `role="switch"` button, the phone's version of the desktop `.toggle`): `#settings_app_lock` in Settings > Lock and `#vault_fingerprint` inside the vault.
Turning one ON shows `mobileSheet` (a title, a few lines, two buttons, built from the confirm dialog's parts) explaining what it does before the system prompt; turning one OFF shows it as a confirmation.
Each is also offered once: the app lock the first time the library is on screen on a phone that can use it (`maybeOfferAppLock`, never over another sheet, the writing page or a reader), and the vault's right after the code opens it (`maybeOfferVaultFingerprint`), from EITHER door: Diagnostics, or locking an item away from its page (`vaultMobileArtifact`). It needs the vault open (the key in memory), not the vault page on screen; when only the Diagnostics door offered it, someone who only ever locked items away was asked for the code every time.
The "already offered" marks are `localStorage` keys `enq.lockOffered` and `enq.diagOffered` (the second named for the decoy); a phone with no screen lock is not asked, and is not marked, so it is asked once it has one.
The Back gesture closes an open `.mconfirm-backdrop` first (`window.__enqBack` sends it `enq-cancel`, which the plain `mobileConfirm` listens for too).

Tested on the emulator without hardware: `adb shell locksettings set-pin 1111`, enroll through `am start -a android.settings.FINGERPRINT_ENROLL` with `adb emu finger touch 1` repeated, then `adb emu finger touch <n>` answers any prompt (a different `n` is a wrong finger).
System prompts are black in `screencap`; read them with `uiautomator dump`.
`locksettings clear --old 1111` puts the emulator back.

### The tour behind the ? is one deck for both apps (TOUR.1)

`static/js/tour.js` + `static/css/tour.css` are loaded by the desktop home and by `mobile.html`, the way `linkpop` is, so the words, the order and the examples exist once (Dequeue's lesson: its two clients had drifted to different tours).
A card only changes the words that are true of one device (`opts.platform`: click or tap, the hotkey or the + menu); the desktop passes the capture hotkey as it is actually set (`Tour.set({hotkey})` once `/settings` answers).
It opens only from the `?` (`[data-tour-open]`, top right of `.homehead` and of the phone's `.lib-hero`), never by itself; an accent bead sits on the `?` until it has been opened once (`localStorage` `enq.tourSeen.v1`, `VERSION` in tour.js: bump it to bring the bead back after a real change).
Seven cards, each with a working demo on made-up artifacts (type into the capture box, pick a search, ask, rewrite a summary line, gather a view); nothing in it reads or writes the library.
The vault is left out on purpose: its door is unmarked, and a tour anyone holding the device can open must not mark it.
While open, everything else in `<body>` is `inert` and `html.tour-on` stops the page scrolling; Esc, the close button, the last card's button and the Android Back gesture (`window.__enqBack`) close it, arrow keys and a sideways swipe turn the card (`.tour-body` needs `touch-action: pan-y` or the browser cancels the touch before the swipe lands).
Icons inside it are sized per place: keep the shared `.tour-ico` rule at one-class specificity or it outranks them.
Adding a feature worth showing means editing `cards()` and its demo, not adding an eighth card by reflex: seven is already the ceiling.

### A note must round-trip through md() and htmlToMd() unchanged

`static/js/md.js` renders a note (desktop editor, phone reader) and `htmlToMd` writes the desktop editor back; a note opened and saved with no edits must come back byte for byte, or it changes shape on its own each time it is touched.
`tests/js/md_roundtrip.js` (run by `tests/test_md_roundtrip.py`, needs node) pins it: nested and mixed lists, empty bullets (an item, not a list break), dividers (a line of three or more dashes renders as `<hr data-dashes=N>` and is written back with the same count), ordered lists keeping their start, multi-line quotes, code fences, and blocks written with NO blank line between them - md() marks those `data-tight` and the serializer writes them back tight, so lines typed on the phone do not grow blank lines after a desktop save.
Add a case there for every rendering bug fixed.
The desktop editor saves as you type (debounced) and on window blur, and `refreshIfStale` never rebuilds an editor holding unsaved words (it re-reads the page only when the store changed elsewhere): rebuilding it on window focus used to drop the words typed since the last blur.

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
| fastembed | local embeddings | BAAI/bge-base-en-v1.5 (dense, 768d) by default; any 768-d model in `config.EMBED_MODELS`. |
| sqlite-vec | search index | vec0 + FTS5 tables inside the SQLite file; hybrid fused with RRF. |
| pymupdf (fitz) | PDF parsing | Text extraction, page rendering, page counting, phrase search. |
| beautifulsoup4 + lxml | HTML parsing | For link preview metadata extraction. |
| httpx | HTTP client | HTTP/2 enabled for preview fetches. |
| Alembic | migrations | Runs at startup. Config built in code, not from ini. |
