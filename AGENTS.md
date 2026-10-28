# Enqueue - Agent Instructions

The engineering reference for Enqueue, for the people who work on it and their coding agents: how to build, run and test it, how it fits together, and the rules the code keeps.
What the app does from a person's side is [docs/MANUAL.md](docs/MANUAL.md); its look and the rules of its design are [docs/DESIGN.md](docs/DESIGN.md); how the pieces and the data fit together, as diagrams, is [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
The README is the public face (a marketing piece with screenshots from `bin/screenshots`); keep engineering detail out of it.
There is no task-queue file: open work is under [Known gaps](#known-gaps) and in the issues.
Prompts live in `prompts.py`, the eval gates in `bin/check-eval*`.

## Start here

**What it is.** A private second brain: capture anything (notes, links, PDFs, images, files) without organising it, then find it again by search or by asking.
A Python engine on the Mac holds the library in one SQLite file and does the thinking; a Tauri shell gives it a window and a global capture hotkey; a Tauri mobile app holds an encrypted copy on the phone, synced through a relay that only ever sees ciphertext.
Zero-knowledge: nothing that leaves a device can be read without a key only the owner holds (see [Encryption and keys](#encryption-and-keys)).

**The repo.**

```
bin/            setup, launch, verify, screenshots, deploy-relay, cdp-eval, check-contrast, check-eval*
desktop/        the Tauri shell (Rust): src/lib.rs (desktop + mobile commands), src/sync.rs (the phone's sync and crypto)
  gen/android/  the Android project (Kotlin: MainActivity, StoreKey, Biometrics, QuickCapture*)
src/enqueue/    the Python engine: api/ ingest/ index/ retrieve/ providers/ sync/ relay/ migrations/
  static/       the interface: home.html + css/ + js/ (desktop), capture.html, mobile.html (the phone)
tests/          pytest; tests/js holds the JS cases (markdown round trip, diff, tabs, guides), run under Node
docs/           MANUAL.md (using it), DESIGN.md (the design system), ARCHITECTURE.md (the diagrams)
assets/         the logo, source art, and the README screenshots
```

**Set up and run.** Everything goes through `bin/`; each script is safe to run again.

| Where | Once | Every time |
| --- | --- | --- |
| Mac (engine + window) | `bin/setup` (Rust >= 1.88, uv + Python 3.12, Node, Chromium for `bin/screenshots`; no sudo) | `bin/launch desktop` (rebuilds the shell, restarts engine and window, waits for health) |
| Android phone (USB debugging on) | `bin/setup --android` (checks SDK/NDK/JDK, installs the Tauri CLI and the target) | `bin/launch mobile` (one-shot build, `adb install`, launch, exit) |
| Android emulator (headless) | an AVD named `enqueue` (the script prints how) | `bin/launch emulator` |
| iPhone (plugged in, Developer Mode on) | Xcode, then `bin/setup --ios` | `bin/launch ios` |
| iOS Simulator | Xcode, then `bin/setup --ios` | `bin/launch simulator` (no camera: linking needs a real iPhone) |
| Engine alone | `uv sync` | `uv run enq serve` (127.0.0.1:8787; open it in a browser) |
| Relay, locally | | `uv run enq relay` (127.0.0.1:8788, secret `dev-secret`) |

Engine output goes to `$TMPDIR/enqueue-app.log`.
A model is optional: capture and search work without one; summaries and answers use the assistant included with Enqueue (signed in under Sync) an online service with your own key, or Ollama on this Mac (Settings > Assistant). Enqueue ships no model; the Ollama helper finds Ollama, starts it and downloads one (`local_model.py`).
The phone starts empty; link it to the Mac over a relay both can reach (Settings > Sync shows a QR the phone scans; see [The relay](#the-relay)).

**Testing on an iPhone.** For whoever holds the iPhone, and their agent:

1. **Get it on the phone.** `bin/setup --ios` once (it checks Xcode, the iOS Rust targets and the simulator runtime), then plug the iPhone in, unlock it, trust the Mac, turn on Developer Mode (Settings > Privacy & Security), and run `bin/launch ios`. The signing team is `bundle.iOS.developmentTeam` in `desktop/tauri.conf.json`; a tester on another Apple account changes it to their own team (Xcode > Settings > Accounts shows the id) and does not commit that change.
2. **Link it.** On the Mac that holds the library: Settings > Phone shows a QR (the relay must be a public `https://` address). In the app, Scan QR. The library downloads; captures, edits, deletes and pins made on the phone come back to the Mac.
3. **What to try.** Read every kind of item (note, link, PDF, image); write and edit a note (tabs and drafts too); capture a thought; ask the eye a question; delete and restore; lock the phone, wait, open the app again; quit the app and open it again; turn on airplane mode, change something, turn it off.
4. **What iOS adds** (worth trying): Quick capture from the Home Screen (press and hold the icon), the Face ID lock (Settings > Lock), Face ID for the vault, the swipe from the left edge as Back, and sync while the app is closed. See [The iOS app](#the-ios-app).
5. **Reporting.** A screenshot of the screen, what you did just before, and the app's log: Xcode > Window > Devices and Simulators > the phone > Open Console, filtered to `Enqueue`, or Safari > Develop > the phone > the page for the web view's console. There is no `bin/cdp-eval` on iOS.

**The gate.** `bin/verify` is lint (black 100, ruff), a JS parse of every page, pytest, the contrast check, the desktop Rust tests when Rust changed, and an Android build when anything under `desktop/` changed.
`bin/verify --fast` is the static part, and what the pre-commit hook runs: enable it once with `git config core.hooksPath .githooks`.
Green proves it parses, passes and compiles; only running it on the Mac or a device proves it works (see [Verifying the Android app on a device](#verifying-the-android-app-on-a-device-headless-over-adb)).

**Where the data lives.** Everything is under `~/Library/Application Support/Enqueue` (`config.DATA_DIR`; `ENQ_DATA_DIR` overrides; an old `~/.enqueue-poc` is moved there at the first start):

| Path | What it is |
| --- | --- |
| `enqueue.db` | the library and its search index (vec0 + FTS5 tables); SQLCipher once the recovery kit is saved |
| `blobs/` | original files, by content hash |
| `settings.json` | preferences, never secrets (mode 0600) |
| `keyring.json` | the sync key, wrapped under the library key and the recovery phrase |
| `recovery-kit.json`, `backup.json`, `device_id`, `sync_cursor` | small state |
| `repo`, `capture-position` | pointers the desktop shell reads |

The Keychain holds the library key (`enqueue-library-key`), the sync key (`enqueue-sync-dek`), the relay secret and the model API keys (one per service, `enqueue-llm-api-key.<backend>`).
Tests never touch any of it: `tests/conftest.py` points the process at a temporary folder and fakes the Keychain.

**Releasing.** Store releases go through fastlane (`fastlane/`, run as `bundle exec fastlane <platform> <lane>` after `bundle install`; setup and keys in `fastlane/README.md`).
`bin/deploy` is the front door (Dequeue's): `bin/deploy android dev` runs the `android dev` lane, which builds the signed `.aab` with a fresh versionCode and releases it to Play's internal testing track, completed, so testers get it; `bin/deploy android prod` runs `android prod` after asking; `bin/deploy desktop` runs `mac release`, then, after asking, `mac publish` (see "The Mac app updates itself" under Build notes). `bin/release` alone only builds, so an upload is always its own step. The Play key is Dequeue's `google-play@sudohnim-play-billing` service account (`desktop/play-store-svc.json`, gitignored), invited to Enqueue per app in Play Console.
`android prod` does the same to production; `ANDROID_PROD_ROLLOUT=0.1` makes it a staged rollout.
`android next_code` prints the versionCode the next upload would use and changes nothing.
`mac release` builds the Developer ID signed, notarized and stapled `.dmg`; the Mac app ships outside the App Store, so nothing is uploaded.
`ios beta` uploads a build to TestFlight and `ios metadata` the App Store listing (see [The iOS app](#the-ios-app)).
The Play lanes need the service account key at `desktop/play-store-svc.json` (gitignored, or `PLAY_JSON_KEY`), and that account invited to the Enqueue app in Play Console.
The Actions tab's `release` workflow (run by hand with a tag) still builds an APK; it is debug-signed unless the `RELEASE_*` secrets are set.
The Mac app is `bin/release desktop`: a `.app` and `.dmg` that carry their own engine (see "The Mac app bundle" under Build notes), signed with the Developer ID certificate when `APPLE_SIGNING_IDENTITY` is set and notarized when `NOTARY_PROFILE` names a `notarytool` keychain profile.

## Known gaps

- **Hosted sign-in with a passkey is not built.** The paid tier's "sign in and your library arrives" needs a domain, an account server and a signed app entitlement; the steps are under [Encryption and keys](#encryption-and-keys).
- **The included models were not chosen by a bake-off.** A library starts on Claude Haiku 5.5 through the relay (`included_ai.DEFAULT_MODEL`). The plan (2026-10-16) was a cheap OpenRouter pair, one model for ingestion and one for chat, picked by a bake-off on the eval notes (real cost with reprompts, quality-gate failures, both search evals) between `qwen/qwen3.7-flash`, `deepseek/deepseek-v4-flash` and `anthropic/claude-haiku-5.5` for ingestion, and `deepseek/deepseek-v4-pro`, `qwen/qwen3.7-plus` and `anthropic/claude-sonnet-5.5` for chat. Set the OpenRouter account to refuse providers that train on data before other people's notes pass through it.
- **The paid tier is planned, not built (decided 2026-10-20).**
  Bring-your-own-key works for everyone, free or paid, with no limit Enqueue sets: the device calls the provider with the person's key, as today.
  Without a key, Enqueue includes AI: a small, cheap model with a small monthly cap on the free tier; Pro (about $4-6 a month) gets the choice of better models and higher caps. Pro is caps and usage, never a feature that free cannot touch.
  Enqueue sync is free for one Mac and one phone up to about 1 GB; Pro raises storage and devices.
  Built (2026-10-20): plans, purchase and enforcement for sync (see "Enqueue Pro" under Gotchas).
  Built the same day: the included assistant (see "The assistant included with Enqueue" under Gotchas).
  Built 2026-10-26: the bring-your-own-key model pickers list what the service serves and refuse anything else (`catalog.py`).
  Built 2026-10-27: the Apple side (`tauri-plugin-billing`, RevenueCat's App Store app with both Apple keys, and App Store server notifications sent to RevenueCat).
- **A smaller embedding model is an option, not done.** bge-small-en-v1.5 (384 dimensions), measured 2026-10-27 beside today's bge-base on the CPU: a query in 4.8 ms against 13.8, 32 long passages in 2.5 s against 8.1, about half the memory, a 66 MB download against 218, and half the vector index. Its published English retrieval scores are about two points lower. It needs a migration of the vec0 tables (built at 768), new floor bars from `enq eval-embedders`, and both eval gates and their baselines.
- **Search is exact (brute force)** over 768-dim vectors: fast at this scale, needs an approximate index at a few hundred thousand chunks.
- **macOS only on the desktop** (AppKit calls, the Keychain).

## Resolved decisions

These came up while surveying the code against the old AGENTS.md, then confirmed with Minh.
They are recorded here so the next agent does not re-litigate them.

1. **Zero-knowledge, with one library key at the root (built 2026-10-14).**
The local database is a SQLCipher file once the recovery kit is saved, backups are sealed, the relay sees only padded ciphertext under hashed names, and the phone keeps its library under a key that never leaves it.
Every connection goes through `db.connect` on SQLCipher's driver (`sqlite.py`): never import the standard library's `sqlite3` for the library, its error classes are different ones.
The whole design is under [Encryption and keys](#encryption-and-keys).

2. **Sync is end-to-end encrypted, and last-writer-wins per snapshot is the model.**
The model is fixed and implemented: encrypted per-artifact snapshots with last-writer-wins per artifact (the key is `(updated_at, _device_id)`, compared as strings; no event log, no logical clock), and a dumb end-to-end-encrypted relay plus SSE push for the mobile client. Do not resurrect the old event-log / multi-peer design; LWW-per-snapshot is the model. SQLite is the source of truth, not a materialised view of a log. A snapshot is canonical JSON (`sync/snapshot.py` `serialize`): the `artifacts` row plus its annotations, page text, drafts, tags, facets and link preview, each child list in a fixed order, so every device writes byte-identical state for the same row.
What exists in code:

- Relay: `src/enqueue/relay/app.py` (`create_relay(data_dir, secret=...)`, Bearer-secret auth, stores opaque bytes only). `enq relay` command in `src/enqueue/cli.py` wraps this with uvicorn (flags: `--host`, `--port`, `--data-dir`, `--secret`; env: `RELAY_HOST`, `RELAY_PORT`, `RELAY_DATA_DIR`, `RELAY_SECRET`).
- Engine sync: `sync/client.py` (push/pull, `push_keyring`), `sync/snapshot.py` (LWW read/serialize/apply), `sync/worker.py` (SSE + timer pull), `sync/guard.py` (`SYNC_PLAINTEXT_PROTOTYPE = False`, now allows non-local relays because bytes are encrypted).
- E2E keyring (QR.1, passwordless): `keyring_file.py` writes `keyring.json` with the DEK wrapped ONLY under a recovery-phrase-KEK (the old password-KEK slot is removed - QR.1). The raw DEK persists in the macOS Keychain (`keyring.py`, service `enqueue-sync-dek`) or a mode-0600 file on non-macOS, and auto-loads on startup, so there is no per-launch unlock and no library password in the normal flow. The recovery phrase is recovery-code-only, for total-device-loss. `crypto.py` is the XSalsa20-Poly1305 boundary. The DEK is also wrapped under the library key (`dek_by_library`), so the recovery kit brings sync back on a new Mac.
- Mobile (Rust, `desktop/src/sync.rs` + `lib.rs` mobile module): pulls the encrypted library into a local SQLite copy and decrypts on-device.
**Pairing model = QR-linked, hosted-relay, passwordless (decided 2026-08-16, superseding the earlier "Option A" paste-code+password model, which live SU.5 testing showed was too painful - USB-only relay, lock-on-restart, forgotten-password lockout). Now BUILT and device-verified (2026-08-19).** The model: (1) a HOSTED relay reachable over the internet (not localhost/USB), still storing only opaque ciphertext; (2) the desktop persists the DEK in the macOS Keychain (service `enqueue-sync-dek`) and auto-loads it on launch (no per-launch unlock, no password); (3) device linking is a Signal-style QR - the desktop `desktop_link_code` shows a locally-rendered QR, the phone camera scans it and receives the key in one step; (4) NO library password in the normal flow - the recovery phrase is a recovery-code-only artifact for total-device-loss. The QR carries key material, but it is camera-scanned + ephemeral + locally rendered (the WhatsApp/Signal/Proton device-linking threat model), never pasted, never sent to any external service. The Option A surface (paste-code, `mobile_pairing_setup`, the SU.7 keyring unlock) is removed - do not bring it back.
**QR wire format (pinned - both sides parse exactly this):** compact UTF-8 JSON `{"v":1,"relay_url":"https://...","relay_secret":"...","dek":"<base64>"}`, where `dek` is RFC 4648 base64 (with padding) of the raw 32-byte DEK, and `v` is the format version (a parser seeing any other `v` refuses with a clear message). CAMERA-ONLY: there is no copyable/pasteable form of the payload anywhere, by decision - the raw DEK must never touch the clipboard or clipboard history. A Rust round-trip test (`rqrr` decode) pins the format.
**DEK-encoding gotcha (bit us on 2026-08-19):** the macOS Keychain stores `enqueue-sync-dek` ALREADY base64-encoded (44 chars = 32 raw bytes), so `desktop_link_code`/`load_link_credentials` must pass it into the QR VERBATIM. Re-encoding double-encodes it (the phone then base64-decodes to 44 bytes, not 32); `mobile_link_qr` must ERROR on a non-32-byte DEK, never silently zero it (a zero DEK links "successfully" but fails every decrypt).
**Phone storage (2026-10-14, was MOB.3b's plain file):** the mobile DEK/secret is in `sync_config.sealed`, sealed under the phone's store key, which an Android Keystore key guards (`StoreKey.kt`, reached from Rust through the activity class cached at `JNI_OnLoad`: `store_key` in `lib.rs`). The phone's `library.db` is SQLCipher and its file cache is sealed under the same key (`blob_read`/`blob_write`).
The sync, decrypt, apply and render path is device-verified end to end, and a hosted relay runs on Railway (see [The relay](#the-relay)).

3. **The library lives in `~/Library/Application Support/Enqueue` (moved 2026-10-14).**
It was `~/.enqueue-poc` for the proof of concept; a product keeps its data where a Mac app does (`config.DATA_DIR`; the XDG data folder off macOS; `ENQ_DATA_DIR` overrides).
`datadir.move_legacy()` moves an old folder there at the engine's first start (`serve()`, and `enq migrate`/`enq restore`, which work on the files directly), before anything opens a file: one rename on one disk, never a copy, and never over a folder that already holds a library.
`~/.enqueue-poc` is left as a link to the new folder. The desktop shell reads its pointers (`repo`, `capture-position`) from the new folder and falls back to the old (`data_dir`/`library_file` in `desktop/src/lib.rs`); `bin/launch` writes them to the new one.
The path has a space in it: quote it in every script.

4. **`instructor.Mode.JSON` is used for every OpenAI-protocol backend.**
All providers pass `mode=instructor.Mode.JSON` unconditionally.
This is correct for now, not a bug to fix.
The adapter calls it out in a comment because the default is `TOOLS`, which needs function-calling support many endpoints lack.
One amendment (2026-09-29): when a structured call comes back 400, `OpenAICompatibleProvider.complete` asks once more in `Mode.MD_JSON` (no `response_format` on the request). OpenCode Go's `kimi-k3` refuses `response_format: json_object` for some inputs with a deterministic 400 "Upstream request failed: Invalid request parameters" (THC, income snowball), while the same request without it succeeds; a 400 is not transient, so without the fallback those summaries failed forever.

**Usage limits pause every model call (`providers/pause.py`, 2026-09-29).**
A 429 (OpenCode Go answers `GoUsageLimitError`, `limitName: "5 hour"`, with a `retry-after` header in seconds) trips ONE engine-wide pause until the retry-after (at least 30s; 15 min when the header is missing), and logs one `model.paused` activity row.
While paused, `complete`/`describe_image` raise `ModelPaused` without touching the network; it is a `ProviderError` and `is_transient` counts it, so owed work stays owed.
`_record_facet_retry` reschedules an owed summary to the pause end (plus up to 60s jitter) WITHOUT counting an attempt, and `_sweep_due` idles until the pause ends.
The first call after the pause goes out normally; a still-limited provider just trips it again.
`enq doctor` shows it as `model_pause` (null when not paused).
The pause is in-memory: a restart forgets it and the first call re-trips it.
Switching accounts ends it early: storing or removing the API key (`PUT`/`DELETE /settings/api-key`) or changing `llm_backend`/`llm_model`/`summarize_model`/`llm_url`/`llm_headers` calls `pause.lift()`, which clears the pause, brings every owed summary retry forward to now, and logs `model.resumed`.

5. **Facet trust is a fixed multiplier, not a learning loop.**
`facets.trust` defaults to 0.5, is read in `retrieve/candidates.py` as `score * trust * 2.0`, and is never written after creation.
A trust-update mechanism (promote on save, demote on eject) is a planned feature, not an implemented one.
For now, trust is a flat constant and every facet contributes equally after the 0.5 weighting.
Usage does feed ranking one level up, per artifact rather than per facet: see "Usage" under Retrieval design notes.

6. **There is no Lumo. The cloud backend is OpenRouter.**
The old docs name Proton's Lumo as a backend; it does not exist in the code.
The configured backends are `enqueue` (default: the assistant included with Enqueue, through the relay), `openrouter`, `anthropic` and `openai` (a person's own key, added 2026-10-28), and `opencode-go` (OpenCode Go subscription, `https://opencode.ai/zen/go/v1`). The old `opencode` (Zen), `custom` and `ollama` backends were removed; a stored `opencode` config migrates to `opencode-go`, and a stored `ollama` one is read as the defaults (`settings._stored`). Only Go chat-completions models work (the adapter speaks `/chat/completions` only; `/responses` and `/messages` models are refused with a clear message - see `config.py` GO_* sets and `providers/base.py`). Treat OpenRouter as the general cloud path. Remove any Lumo reference you find.

7. **The preview browser is the Mac's own WebKit (2026-10-26; crawl4ai and Chromium before).**
`webkit_page.py` opens a refused page in an off-screen WKWebView through `pyobjc-framework-WebKit` (29 MB in the app, where crawl4ai's Chromium was about 450 MB and never shipped), so it is on by default and in the Mac app (see "Link previews").
Playwright stays a dev dependency only for `bin/screenshots`.
marker and whisper.cpp are not currently planned.
PDF parsing uses only pymupdf (fitz).

8. **API version string and package version are two different things.**
`pyproject.toml version = "0.3.0"` is the package release version (with `desktop/Cargo.toml` and `desktop/tauri.conf.json`, bumped together for a release).
`api.py FastAPI(version="0.2.0")` is just the string the OpenAPI docs page shows.
They are allowed to differ.
If you bump one for a release, bump the other to match, but a mismatch is not a bug.

9. **There is one view concept: the saved pivot.**
The `exhibits` / `exhibit_members` tables and the `/exhibits*` endpoints that an earlier agent introduced to paper over the L.2 add-to-grouping bug are removed.
`saved_pivots` and `/pivots*` carry the same concept with a re-runnable spec.
The wall has no ephemeral view surface; only a saved pivot persists a view.

10. **The SSE lens surface and curate are removed.**
`POST /lens` (Server-Sent Events), `POST /curate`, and the lens-cache endpoints were deleted in Phase M, along with the retrieve modules that powered them (`retrieve/expand.py`, `retrieve/rerank.py`, `retrieve/score.py`, `retrieve/lens.py`, `retrieve/judgments.py`, `retrieve/curate.py`), the lens settings, and the `lens_judgments` table (migration 0020).
Search is the retrieval path; the assistant organises material into views (it plans a spec in chat, `pivot.plan`) and the page runs one with `POST /pivot/run`.
Do not add SSE plumbing back unless asked.

11. **The phone app is built; a browser extension is a future milestone.**
No browser extension code exists; document it as future, do not build against it.
The Android app (Tauri v2 mobile, `desktop/gen/android`, crate builds as `enqueue_lib`) is built: it syncs the encrypted library through the relay into a local SQLite copy, captures, reads, does the in-the-moment writes (edit note, delete, pin, tags, and notes on a capture; confirmed 2026-10-27), and chats by calling the configured LLM backend directly with keyword-only (FTS) grounding.
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
Build/run the app with `bin/launch mobile` (physical phone only) or `bin/launch emulator` (headless AVD, one-shot build + adb install + exit, for agent device-verify); the raw build is `cargo tauri android build --debug --target aarch64` with the apk at `desktop/gen/android/app/build/outputs/apk/universal/debug/app-universal-debug.apk`. NEVER use `cargo tauri android dev` for headless verify - it hangs on device-pick.
Sync/mobile scope boundaries (durable): one person, one library - no multi-user or shared libraries. Android-first; iOS is a follow-on. The relay is additive - with sync off, nothing about the desktop changes. `saved_pivots` (saved views) and chats do NOT cross the relay; mobile reads artifacts only, and mobile chat histories are device-local by decision.
Mobile linking is passwordless (QR.1/QRSYNC): the phone receives the DEK by camera-scanning the desktop QR and persists it in its sandboxed `sync_config`; there is deliberately NO password and NO recovery-phrase unlock path on the phone. The desktop is the single source of truth and the recovery anchor: lose the phone and you simply re-scan the desktop QR. Do not add a mobile password or recovery-phrase fallback.

12. **The user-facing concept is "view", not "grouping".**
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
    +-- SQLite (~/Library/Application Support/Enqueue/enqueue.db)    artifacts, text, chats
    +-- SQLite search index (vec0 + FTS5 tables inside enqueue.db)  vectors + text + ids
    +-- Blobs (~/Library/Application Support/Enqueue/blobs/)         original files, content-addressed
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
| `privacy.py` | What may go to which model. `is_remote(provider)` (endpoint not loopback), `shareable(items, provider)` drops local-only artifacts from anything shown to a remote model: chat passages, the gray-zone judge, model re-ranking. A chat scoped to a local-only artifact, and attribute extraction from one, get no model at all (`providers.base.LocalOnly`). The phone's chat does the same through `sync::chat_sources`. |
| `blobstore.py` | The original files on disk, sealed under a key from the library key once the kit is saved; every read and write goes through it. See "At rest" under Encryption and keys. |
| `netguard.py` | `is_public(host, port)`: whether a host resolves only to public addresses. What a link preview may reach, for the plain fetch and the WebKit reader alike. |
| `webkit_page.py` | The preview browser: one page in an off-screen WKWebView in a process of its own, HTML back once its scripts ran. See "Browser fallback" under Link previews. |
| `outbound.py` | What went to remote models: `OpenAICompatibleProvider` counts every structured call and image description to a non-loopback endpoint (service, model, purpose by response model, characters, credentials blanked), never the text, and writes one `model.sent` Activity row per service every 10 minutes and at shutdown, so a reprocess does not bury the log. |
| `settings.py` | Three-layer settings (env > settings.json > default). Writable fields, storage report. |
| `db.py` | SQLite access + Alembic migration at startup. `get_conn()` and `transaction()` for writes, `reader()` (one cached read-only connection per thread, sqlite-vec loaded) for searches, `count()`. |
| `greeting.py` | The wall's greeting: one model phrase per four-hour bucket, generated in the background. |
| `schemas.py` | Pydantic models for every model call. Validators are the quality floor. |
| `prompts.py` | System prompts, the one copy. |
| `keyring.py` | macOS Keychain for the API key. `/usr/bin/security`. No-op on non-macOS. |
| `capture.py` | Captures: links, file uploads. Content-addressed dedupe. PDF text extraction and page rendering. |
| `notes.py` | Notes: create, edit (versioned), annotate. Secret scanning before model calls. |
| `preview.py` | Link previews: one opt-in fetch, parse og:meta, download image locally. |
| `chats.py` | Conversations: submit (write pending turn + queue), scoped retrieval, grounded answers, topics, titles, chat sync push. |
| `chats_worker.py` | The answer worker: a `Worker` thread that routes, answers, commits (retrying transient DB locks), logs `ask.answered`/`ask.failed`, and pushes. `sweep_orphaned_pending` at startup. |
| `events.py` | The activity log: `emit()`/`recent()` over the persisted `events` table. Never raises. Backs the Settings Activity tab and the vault decoy. |
| `worker.py` | Shared single-thread queue lifecycle used by the ingest queue and the answer worker; two lanes (the person's work before background upkeep). |
| `trash.py` | Soft delete with retention window. Purge is the only destructive operation. |
| `backup.py` | Backups into any folder (a cloud drive's, typically): daily + on clean shutdown + on demand, every file encrypted with the library key before it reaches the folder, search index emptied in the copy, originals sealed under keyed-hash names, 7 daily + 4 weekly kept; `restore()` opens one with this Mac's key or the recovery kit and sets the current library aside. |
| `sqlite.py` | The SQLite driver for everything that opens the library: SQLCipher's build (`sqlcipher3`), re-exported. Reads plain files too; `db.connect` keys an encrypted one. |
| `libkey.py` | The library key: 32 random bytes made once, in the Keychain (`enqueue-library-key`), the root every other key is derived from (`derive`, HKDF-SHA256 per use); the recovery kit (`kit`/`from_kit`, 56 Crockford characters with a checksum) and whether the person said they saved it. |
| `opens.py` | Records each artifact open (`opens` table): source (search/wall/related/chat/other), and for a search open its query and 1-based rank. `usage_boost` turns opens, chat citations and pins into a small ranking multiplier. The interface reports opens through `POST /artifacts/{id}/opened` (`reportOpen` in `static/js/util.js`). Local only, never synced. |
| `reading.py` | How far the assistant is through reading the library (`GET /reading`), for the wall's "Reading your library" line. See "Reading your library" under Gotchas. |
| `catalog.py` | Which models an online service serves: OpenRouter's public list (`GET /api/v1/models`, no key), fetched at most every 12 hours into memory and `model-catalog.json`, OpenCode Go's from `config`; OpenAI's and Anthropic's from their `/v1/models` with the person's key (`KEYED`); Ollama's from `/api/tags` on this Mac, asked each time, never kept. `suggest` picks the model a service starts on from its own list (a cheap one: Haiku, an OpenAI "luna"/"mini"; for Ollama the best of `local_model.CHOICES` it holds), returned as `suggested`/`suggested_vision`; Settings and the welcome switch to it once a key is saved (`applySuggested` in `settings.js`). `GET /settings/models?backend=` feeds the Settings pickers; `settings.update` refuses a model the list lacks (a list a few minutes old is fetched again first, so a new model is not turned away); `/setup` says when a saved one is not offered (`model-unknown`), reading the kept list only. The images job needs a model that reads pictures. A list that cannot be fetched refuses nothing. Tests never fetch (`conftest._no_model_catalog_fetch`). |
| `local_model.py` | Ollama on this Mac, for the `local` backend: installed (`/Applications/Ollama.app` or the CLI), running (`/api/version`), the models it holds that answer (`/api/tags`, `/api/show` capabilities), `start()` (`open -a Ollama`), and the models Enqueue offers (`CHOICES`, the recommended one by `hw.memsize`), downloaded in the background through `/api/pull` (`pull`, `pull_state`, `cancel`). Routes `GET /settings/local`, `POST /settings/local/start`, `POST`/`DELETE /settings/local/pull`; the panel is `renderLocalPanel` in `static/js/settings.js`. Tests point `BASE` at a closed port (`conftest`). |
| `setup.py` | Where this installation stands: the three steps left to set up, the settings that need a look, and the one model answer about settings (`GET /setup`, `POST /setup/ask`). See "Settings explain themselves" under Gotchas. |
| `sync/join.py` | Device approval: a new Mac asks to join the account's library and one that holds the key seals it to the asker's public key. See "A new computer is approved from one that has the key" under Gotchas. |
| `account.py` | Enqueue sync from the Mac: sign in with Google (desktop PKCE, back to `/account/google/callback`) or Apple (the web flow, back through the relay to `/account/apple/done` with a one-time code), then a device token for this Mac becomes the sync secret (`sync/enable.py`). Keeps the relay's refresh token in the Keychain (`enqueue-account-session`) and who is signed in in settings; mints a token per phone (`desktop_link_code`) and per joining computer (`sync/pairing.py`); lists and removes devices, signs out, deletes the account. Routes in `api/account.py`. See "Enqueue sync" under Gotchas. |
| `shiny.py` | Something shiny (the idea is brain food: a glint found in the clutter), in place of resurfacing one old note: each day two or three notes from different fields that make the same point sit above the wall, with the idea they share, how each shows it, and a question to take it further (far analogies, Epstein's *Range*). The set comes from `related` idea links, the farthest first (`related.distance`), rotating daily through the top 7; a third note joins through another idea link; mention links across fields serve only when there is no idea link; subject links never. One call to the chat model per set writes the words (`prompts.SHINY`, shown titles and subject/mechanism/principle lines only, never the notes' text), in the background, cached in `derived_values` (scope `shiny`, subject the ids joined, attribute a stamp of what was shown); until then, or with no model, the card shows the link's own sentence. A set with a local-only note keeps the link's sentence (no model reads it); a failed call is not asked again that day. Vaulting and purge drop the cached words. `GET /shiny` returns the notes as wall items plus `food`, `links` and `writing`; "Find another" is `GET /shiny?n=N`: the day's order is the top 7 from today's turn, then every other pair, and `more` says whether one follows (after the last, the button says "Back to the first"); each set's words are written once, when first shown. `refreshShiny` in `static/js/home.js` draws the card, remembers today's `n` (localStorage `enqueue.shiny.at`) and asks again a few times while `writing`; "Not today" hides it until tomorrow (localStorage, this browser only). Opening a note records an open with source `shiny`. |
| `eval_embedders.py` | `enq eval-embedders`: rebuilds both eval libraries with each candidate embedding model and reports main recall@10/MRR/Nothing-OK, cross-domain passes, and floor bars fitted to that model's scale. See "Embedding models". |
| `eval_real.py` | The real-search eval: every search followed by an open is a case, scored against the live library. See "Real-search eval". |

### Ingest

| File | Job |
| --- | --- |
| `ingest/queue.py` | In-memory work queue. One daemon thread. `submit()` returns immediately. Model steps run sections -> facets -> entities -> contexts; each skips work already current (facets/entities written by the current ingest model from the current body; contexts only for chunks missing one, and `chunk_artifact` carries contexts over unchanged chunk text), and a transient failure in any of them (`source.Owed`) owes the artifact a `facet_retry`, so a rate-limited reprocess finishes itself later at the cost of only what was missing. "Rebuild concepts" is how to force facets with the same model. Chunks that would come out unchanged and are already indexed are kept, not re-chunked and re-embedded, and every run leaves its `facet_retry` row gone or due in the future (see Gotchas). A vision describe failure marks the image `status='failed'` and surfaces in `/doctor` (`images_without_body`) instead of failing silently. |
| `ingest/chunk.py` | Markdown chunker. Headings, lists, code fences kept whole. Prose merged to a floor. Anything over `CHUNK_MAX_TOKENS` (counted with the embedder's own tokenizer) is split at line, then sentence, then word boundaries. Chunk source includes the artifact's current annotation text; a bodyless capture falls back to its title + filename so it always has at least one chunk. |
| `ingest/facets.py` | Facet generation via the summary provider, fed page_text + annotations. Eligibility gate, proper-noun self-reference check, retry/backoff. Also the user-edit surface: `edit_facet`/`add_facet`/`delete_facet`/`regenerate` + `sync_facets` (push to other devices). |
| `ingest/source.py` | The text every ingest writer reads: `ingest_text()` = the body (notes) or extracted `page_text` (links, PDFs, images), plus current annotations marked "(your note)". A document over `FACET_INPUT_CHARS` is map-reduced: split into sections of up to 10k characters on paragraph boundaries (at most 24), each summarized by the ingest model (cached in `derived_values`, scope `section_summary`, per section hash and model), and read as ordered summaries. The summaries are also written to `sections` (stamped with ingest model and body version; left untouched when unchanged, since facets, entities and contexts each read through here) and indexed as their own search layer by the ingest queue. A section that fails for a reason that will pass (rate limit, outage; `providers.base.is_transient`) raises `SummariesOwed` so the artifact is retried instead of written from its opening; any other failure falls back to the capped opening; `text_only` text is never mapped. Facets, entities and chunk contexts all read through it. |
| `ingest/context.py` | Contextual chunks: for an artifact with 2+ chunks, the ingest model writes one or two sentences per chunk placing it in the document (batches of 30). Stored in `chunks.context`, embedded and keyword-indexed with the chunk (not in the trigram table). Skips `text_only` artifacts. |
| `ingest/related.py` | Related artifacts, precision first: a missing link costs nothing, an invented one costs trust. Three kinds. **Subject links:** each of an artifact's subject lines (facet level 1, `SUBJECT_LEVEL`) searches the facet index and only another artifact's subject lines count; kept at or above `RELATED_MIN` 0.66, with `related.point` = the related artifact's subject line that matched (each direction holds the line of the artifact it points at). **Mention links:** another artifact whose current entities name the same person, place or thing (case-insensitive) scores 0.7 and stores the name in `related.via`; a name more than 8 artifacts share never links, nor does a link's own site name ("Medium" on an article saved from medium.com, read from its preview or its address). **Idea links** (cross-field): similarity between lines ABOVE the subject level only proposes pairs (`IDEA_MIN` 0.72, the closest `IDEA_CANDIDATES` 8), and the ingest model judges each with `prompts.RELATED_JUDGE` (one call per artifact); only a yes links, and its `point` is the model's plain "Both ..." sentence. Similarity alone cannot do this: the prompt's "bridge" lines borrow another field's words on purpose (a piano essay gets a line about codebases) and abstract sentences match on shape ("X beats Y"), which linked a data-modeling note to a piano essay and a tax letter. The judge FAILS CLOSED (an unjudged pair is not a link), the opposite of search's gray-zone judge. Verdicts are cached in `derived_values` (scope `related_judge`, subject `a|b` ids in order, attribute = a stamp of both items' level 0-1 lines, so a changed subject asks again). `compute(id)` never calls a model: it links on cached verdicts only and marks an artifact with unjudged pairs in the `related_pending` table. Judging has its own worker (`start_judge`, one daemon thread, started at engine startup): `judge_next()` takes the longest-waiting pending artifact and makes one model call, returning `idle`/`judged`/`budget`/`paused`/`owed`, which the loop paces itself by. It stops for the day at `JUDGE_DAILY` calls (`ENQ_RELATED_JUDGE_DAILY`, default 40, 0 = off; counted per UTC day in `related_state`), waits out a usage pause without spending a call, and leaves the artifact pending when the model cannot be reached. Ingest never calls the judge: the first version sent each note back through the whole ingest pipeline (re-chunk, re-embed) to make one call, had no ceiling, ran a weekly usage limit dry, and woke the link-refetch loop (see Gotchas). A pair with a local-only item is settled as no link, with no model call. `VERSION` (kept in `related_state`) makes `refresh_if_outdated()` recompute every artifact once at startup on the ingest worker (no model). `enq doctor` reports `related_pending` and `related_judged_today`. Tests keep the worker off (`conftest._no_judge_worker`) and drive `judge_next` directly. Each link keeps its `kind` (subject, mention, idea) and `distance` (1 minus the closest subject-line similarity between the two: how far apart their fields are). Analogies are kept and listed first, the farthest first (`_rank`), then the rest closest first: the further a shared idea reaches, the more it is worth (far analogies, Epstein's *Range*). The top 5 are stored in `related` in both directions; stale facets and entities never count. `GET /artifacts/{id}` returns `related` (each with `via`, `point`, `link` and `distance`), shown as a Related section under the note (`relatedRowHtml` in `static/js/artifact.js`), where an analogy is labelled "Same idea, another field". That section is the "what else is this like" surface; there is no separate one. The phone has no related data (it does not ride the snapshot). |
| `ingest/secrets.py` | Credential pattern scanner. Runs before any text reaches a model. |

### Retrieve

| File | Job |
| --- | --- |
| `retrieve/lift.py` | Query lifting: the search model restates a search as 2-4 facet-style claims, each also searched against facets (dense similarity counts for the floor; never lexical). Cached in `derived_values` (scope `query_lift`). Chat always lifts; `/search` only with the `search_lift` setting (Settings > Capture > Search, default off). Tests stub it via an autouse conftest fixture. |
| `retrieve/decompose.py` | Two-sided questions: "compare X and/with Y", "the difference between X and Y", "how does X compare to Y", "X vs Y" split into their sides (each 1-12 words; plain rules, no model call). `chats.passages` searches each side on its own (`_library_passages`), interleaves them rank by rank so both sides reach the answer, then fills leftover slots from the whole question. |
| `retrieve/passage_links.py` | Passage connections: for each of an artifact's first 40 chunks, its stored vector finds the nearest chunks in other live artifacts (`store.similar_chunks`); those at or above `PASSAGE_MIN` (0.78 cosine, about a quarter of eval-corpus passages link) become up to 3 connections per passage. On demand, nothing stored, no model call. `GET /artifacts/{id}/connections`; the drawer's "Passages that connect" section (`mountConnections` in `static/js/artifact.js`) shows each passage's opening words and its linked notes. |
| `retrieve/filters.py` | Filters in the words of a search: an unambiguous kind word (pdf, link/article, image/photo/screenshot; never "note") and a time phrase (today, yesterday, this/last week/month/year, the last N days/weeks/months, in March [2025], in 2024) become exact filters on kind and `created_at`, and the rest is searched. Plain rules, no model call. `search_results` intersects them with `#tag` filters into one `allowed` set (empty means no results, never the whole library); a filter with no other words lists what it allows. `/search` returns the understood filters as `filters` ("PDFs · saved last month") for the results header. A quoted phrase is never parsed. |
| `retrieve/model_rank.py` | Model re-ranking: the search model reads the top `WINDOW` (20) floor survivors (title, snippet, facets) and returns them best first; missing ids keep their fused order, a failure keeps the whole fused order. Cached in `derived_values` (scope `model_rank`) per query, candidate set and model. Opt-in via the `search_model_rank` setting (Settings > Capture > Search, default off); runs after the R.9 cross-encoder when both are on. |
| `retrieve/candidates.py` | `/search` rollup: dense + FTS5 keyword fused with RRF, plus trigram substring recall, a fuzzy short-field branch (titles, entities, annotations), and exact quoted-phrase pinning. One row per artifact. |

### Index

| File | Job |
| --- | --- |
| `index/embed.py` | Local embeddings via fastembed. Dense (BAAI/bge-base-en-v1.5, 768d), on the CPU, loaded on first use and let go after `ENQ_EMBED_IDLE` seconds idle (see "Keeping it quick and small"). `embed()` for passages, `embed_query()` for searches (adds `EMBED_QUERY_PREFIX`), `token_count()` for the chunker. |
| `index/store.py` | `VectorStore` interface + `get_store()` factory. One instance per process. |
| `index/store_sqlite.py` | sqlite-vec backend: vec0 + FTS5 tables (unicode61 keyword + trigram substring), hybrid search fused with RRF. `search_legs()` returns the fused list plus the raw dense/keyword/trigram legs from one pass on one connection; callers that need both (the relevance floor in `/search` and `chats.passages`) must use it rather than re-running `search_dense`/`search_keyword`. |
| `index/fusion.py` | Reciprocal rank fusion as a pure function. |
| `index/bootstrap.py` | Startup index build (no manual step) + cutover cleanup. |

### Providers

| File | Job |
| --- | --- |
| `providers/base.py` | `Provider` protocol, `get_provider()`, error translation to sentences. |
| `providers/ollama.py` | `OpenAICompatibleProvider`. One adapter for all OpenAI-protocol endpoints; falls back to `Mode.MD_JSON` on a 400. |
| `providers/anthropic.py` | `AnthropicProvider`: the Messages API through the official `anthropic` SDK, for the `anthropic` backend. See "Anthropic" under Provider layer. |
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
| `migrations/versions/0041_related_kind.py` | `related.kind` (subject/mention/idea) and `related.distance` (how far apart the two subjects are). |
| `migrations/versions/0039_related_judge_state.py` | `related_pending` (artifacts with unjudged cross-field pairs), `related_state` (key/value: the link rule's version, the judge's calls today), `link_previews.body_tried` (fetched, no article in it; not in the sync snapshot). Moves what an earlier build had parked in `derived_values`. |
| `migrations/versions/0038_related_point.py` | `related.point`: the related artifact's summary line behind an idea link (NULL for a name-only link). |
| `migrations/versions/0037_related_via.py` | `related.via`: the shared name behind a "both mention" link (NULL for an idea link). |
| `migrations/versions/0036_sections.py` | `sections` (artifact_id, ordinal, summary, model_version, body_version): section summaries of long documents, a search layer. Purge deletes an artifact's rows. |
| `migrations/versions/0035_opens.py` | `opens` (artifact_id, source, query, rank, opened_at): the open log behind the real-search eval. No foreign keys; purge deletes an artifact's rows. |
| `migrations/versions/0034_related.py` | `related` (artifact_id, related_id, score, model_version): derived links, no foreign keys; purge deletes both directions. |
| `migrations/versions/0033_chunk_context.py` | `chunks.context` and `chunks.context_model` (contextual chunks). |
| `migrations/versions/0009` .. `0041` | One revision per schema change, applied at startup (latest: `0041_related_kind`). Notable: 0010 index tables, 0019 below, 0031 `facets.edited`, 0032 `events`, 0036 `sections`. Read the directory for the rest. |
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
| `bin/launch simulator` / `bin/launch ios` | One-shot build + install + launch in the iOS Simulator, or on a plugged-in iPhone, then exit. See "The iOS app" under Gotchas. |
| `bin/launch emulator` | Boot a headless AVD, one-shot build the debug apk, `adb install` + launch, then exit (for headless device-verify over CDP/screencap). |
| `bin/android-matrix` | Opens the app on five test emulators (Android 9, a small Android 15 phone, Android 15, 16 and a tablet) one at a time, and reports for each whether it stayed up, crashed or rendered its first screen; screenshots go to `$TMPDIR/enqueue-android-matrix`. `--create` makes the emulators (the system images come from `sdkmanager`), `--debug` tests the debug apk instead of the release one. |
| `bin/cdp-eval` | Evaluate JS inside the running Android WebView over CDP (the supported way to read on-device runtime state); `--serial <device>`. |
| `bin/check-eval-cross` | Cross-domain search gate (CI `eval` job): runs `enq eval-cross`, fails if a layer makes results worse than the one below it (enriched vs chunks, lifted vs enriched) or if any query that passed in `evals/results/cross-domain.json` now fails. `--update-baseline` rewrites the baseline. |
| `bin/release desktop` / `bin/release android` | Shippable builds: the Mac `.app` + `.dmg` with the engine inside (signed and notarized when the Apple settings are given), or the signed Android release `.apk`/`.aab` (`ANDROID_VERSION_CODE` overrides the versionCode). The fastlane lanes wrap both. |
| `bin/android-env` | Sourced, not run: the Android toolchain every build uses (SDK, NDK, JDK, and OpenSSL's `llvm-ar`/`llvm-ranlib`). |
| `bin/bundle-engine` | Vendors the relocatable engine into `desktop/engine` for the Mac app (325 MB); `bin/release desktop` runs it. It strips what the engine never imports and fails if a relay or test package leaks in. |
| `bin/deploy` | Ship a build through fastlane: `android dev` (Play internal testing), `android prod` (Play production, asks first; `-y` skips), `android code` (the next versionCode, read only), `desktop` (the notarized `.dmg`). Gems go to `vendor/bundle`. |
| `bin/deploy-relay` | Deploy the one hosted relay (Railway service `enqueue`) after the relay tests pass, asking first (`-y` skips), and wait for `/health`. |

### Static

| File | Job |
| --- | --- |
| `static/home.html` | The home shell: meta, font preloads, the `#topbar`/`#view`/`#pill`/`#dropover` skeleton, ordered `<link>` to `css/*.css` and `<script src="/static/js/...">` tags. Split from the old single-file museum.html in M.8: one global scope, no build step, no ES modules. |
| `static/css/` | The home interface stylesheets, split by surface (M.8): `tokens.css` (palette, the font faces, the weight tokens; never write a numeric `font-weight` in a stylesheet), `base.css` (type/buttons/callouts/rows), `home.css` (topbar/searchbar/homehead/eye/wall/cards/groupbar/tagbar), `artifact.css` (artifact+drawer+editor+docpane), `reader.css` (reader+findbox+folio), `chat.css` (transcript), `search.css` (the results page: one reading column, the field on top, each result's kind and age, title, why it matched and the lines holding the searched words, marked; Maybe related apart), `settings.css`, `pill.css` (pill+menu+toast+dialog+dropover+animations), `eyepanel.css` (the ask panel), `linkpop.css`, `tour.css` (the tour; shared with the phone), `welcome.css` (the first-run welcome), `bird.css` (the flying raven loader, `.flybird`, and the raven's flight after a capture, `.capture-flight`; shared with the phone and the capture overlay), `details.css` (the Details panel, `.dpanel`; shared with the phone), `notetype.css` (a note's own typography, `.notetype`: the desktop's note sheet, the phone's reader and both drafts comparisons; loaded after `artifact.css`; a note is written straight on the lavender ground on both apps, with no sheet, and its code and quotations sink into the deeper `--surface-3`). |
| `static/js/` | The home interface JS, split by surface (M.8). Load order: `util`, `icons` (the icon paths; the phone uses them too), `eye` (the living eye, mouse or finger, and `captureFlight`; shared with the phone), `eyemood` (the pill eye's moods), `ground` (the page colour drifting through the day), `md` (markdown render + serialize), `linkpop` (the copy/open bar for links in content), `suggest` (name matching for the search candidates; shared with the phone), `details` (the Details panel's voice and reactions; shared with the phone), `tour` (the ? tour), `dialogs`, `pill`, `morph`, `home`, `artifact`, `search`, `pivot`, `manual` (views arranged by hand: the page, the drag, the picker), `chat`, `trash`, `drafts`, `notetabs`, `settings_guide`, `welcome` (the first-run welcome), `approve` (device approval: the waiting screen and the approve prompt), `update` (the Mac app's update card: Update now, Update on close), `accountmenu` (the account at the top right of the wall: who, the plan and storage used, devices, Settings, How to use, sign out; signed out, the way to sign in), `settings`, with the boot call last. One global scope; no ES modules. |
| `static/capture.html` | The capture overlay, a page of its own. It shares only `css/tokens.css` and `css/bird.css` (the flight), never the home page's layout stylesheets, so a change over there cannot break it. |
| `static/fonts/` | Hanken Grotesk, variable woff2 (upright and italic; latin, latin-ext, vietnamese), served locally. No CDN. The one face; weights come from `--w-*` tokens (docs/DESIGN.md section 3). |

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
3. **Index** (`index/store_sqlite.py`): `index_facets_artifact()` embeds facet statements, upserts into `vec_facets` and `fts_facets`. Search drops a facet written from an older body; the model that wrote it does not matter (see "Two desktops read an item with the model once" under Gotchas).

**Re-summarizing runs on the ingest worker.** `backfill_summaries()` (every startup) queues every live item whose facets are not `facets.is_current` (none, or written from an older body), and every live item with no chunks (one pulled before pulls were ingested), so the library converges across restarts. A change of ingest model is the one thing that rewrites current summaries: `queue.refresh_on_model_change()` (at startup and on any model setting change) forces every item whose summary lines another model wrote through every model step, once; it only records the model the first time it runs. "Rebuild concepts" / `POST /facets` / `enq facets` call `queue_summary_refresh(redo)`, which queues the same set (or, with `redo`, every item, forced via `facets.force`) and returns at once; it used to run `generate_all` inside the request for hours, which a restart killed. `enq doctor` reports `summaries: {model, current, stale, retrying}`. The retry sweeper (`_sweep_due`) never re-queues an artifact already waiting in the queue or being processed (`_in_flight`): a due row only moves once the worker processes it, and re-queuing it every 30s while the worker was busy produced bursts of back-to-back re-ingests ("33 chunks, 0 facets" every ~13s). See "A retry run settles its row" under Gotchas.

**Editing the summary (facets are user-editable).** `ingest/facets.py` exposes `edit_facet(facet_id, statement)` (marks `edited=1`, full trust, reindexes), `add_facet(artifact_id, statement, level)`, `delete_facet(facet_id)`, and `regenerate(artifact_id)` (clears skip/retry, regenerates machine lines, keeps edited ones). Each is wired to an endpoint (`PATCH /facets/{id}`, `POST /artifacts/{id}/facets`, `DELETE /facets/{id}`, `POST /artifacts/{id}/facets/regenerate`) and to a mobile Tauri command (`mobile_facet_edit`, `mobile_facet_delete`). An edit bumps the artifact's `updated_at` and pushes so it wins LWW and reaches the other device; a background generation pushes without bumping (equal-key re-apply carries the new facets to the phone). The `facets.edited` column (migration `0031_facet_edited`) is what regeneration reads to decide which rows it may delete.

**Link previews ride the snapshot too.** `read_artifact_snapshot` carries a `link_preview` child (the `link_previews` row), applied on both sides only when present, so a phone-authored snapshot never wipes the desktop's preview. The preview picture goes up as a blob by `image_hash` (`sync/client.py::_blob_hashes`), and `preview.fetch` re-pushes the artifact once the preview lands. `backfill_link_previews()` re-pushed every existing link once at startup (the `sync_link_previews_backfilled` setting). The phone's `list_artifacts` joins the preview so link tiles show the picture, site and description.

**Facets ride the artifact snapshot to the phone.** The phone cannot generate its own, so facets are a child of the artifact snapshot (`sync/snapshot.py` `read_artifact_snapshot` includes them; apply is guarded to a non-empty facet list so a facet-less snapshot never wipes locally-generated facets on an equal-key re-apply). A summary edited on the phone syncs back, and `sync/client.py::pull()` reindexes any artifact whose pulled snapshot carried facets, so a phone edit becomes findable on the desktop.
Every other model-written layer rides along too (`derived_layers`): entities, section summaries and their per-section cache, passage contexts by the hash of the passage's text, and the related judge's verdicts, so a second desktop takes them instead of paying again. See "Two desktops read an item with the model once" under Gotchas.

### Chat

Asking is submitted, not computed inline. `chats.ask`/`chats._submit` writes the user turn plus a pending assistant turn in one transaction, logs `ask.submitted`, and hands the work to the answer worker (`chats_worker.py`, an in-memory `Worker` thread); the request returns immediately with a visible pending turn. On startup `sweep_orphaned_pending` resolves any turn left pending by a killed worker to `failed` (Rule 2: a pending turn always resolves).

`chats_worker.compute(job)`:
1. **Route** (`assistant.route`): pick the skill. A request with no word for rearranging (`_ORGANIZE_CUE`: organize, group, sort, arrange, cluster, categorize, classify, bucket) is `answer` with no model call; only one that has such a word asks the model. The call used to run before every answer and said `answer` nearly every time.
2. **Answer** (`chats.py` via the skill): restate a follow-up so it can be searched (`_standalone`), retrieve passages (a scoped chat reads its artifact, searched inside when it is long; everything-scope uses hybrid search on chunks + facet hits) and have the model answer from them. `Answer` schema enforces grounded/cited consistency. The passage header MUST carry the artifact id (`[kind] (id: <id>) title`): the validator rejects any cited id it was not offered, so if the model only sees the title it cites the title and the turn fails validation as "cited artifacts that were not provided" (CHATBUG.1).
3. **Commit** via `_commit_answer`, which retries a transient `database is locked` a few times so a busy moment (a sync applying a batch) does not throw away a real answer.
4. **Title + topics** (`chats.py`): best-effort, non-blocking, after the answer commits. Topics regenerated from whole transcript each turn.
5. **Log + push**: emit `ask.answered` (question, answer, cited artifacts, `model`, per-stage timing) or `ask.failed` (with the error), and push the conversation to the relay.

**Conversations sync** over the same relay (`sync/snapshot.py` `read_chat_snapshot`/`apply_chat_snapshot`, LWW by `(updated_at, _device_id)`, terminal tombstone). A chat's messages/citations/topics are replaced wholesale on apply. The mobile side (`mobile_chat_send` in `desktop/src/lib.rs`) computes the answer inline with keyword retrieval + a direct LLM call, then pushes.

Structured-output gotchas (CHATBUG.1, 2026-08-20): `config.MODEL_RETRIES` is instructor's `max_retries` = TOTAL attempts, not retries-after-first; it defaults to 3, because a thinking model (e.g. opencode-go `deepseek-v4-pro`) answers in prose on the first try and needs a reprompt to emit the schema, and reprompts only fire on a validation failure so the happy path costs nothing. Do NOT switch instructor mode to fix a schema failure: opencode-go rejects `Mode.TOOLS`/`TOOLS_STRICT`/`JSON_SCHEMA` ("Thinking mode does not support tool_choice", "response_format unavailable"); `Mode.JSON` (or `MD_JSON`) is the only mode it accepts, and it works once the retries and the passage-id are right.

### Activity log (events)

`events.py` is a persisted activity log (migration `0032_events_log`, the `events` table): `emit(kind, detail, data=None, duration_ms=None)` inserts a row (never raises; trims to a bounded size), `recent(limit)` reads newest-first with the JSON `data` parsed. Emit sites: `ask.submitted`/`ask.answered`/`ask.failed` (chats + chats_worker), `capture.note` (notes.py), `facet.regenerated`/`facet.edited` (facets.py, carrying model + source), `ingest` (queue.py, only when it produced chunks/facets/entities - an empty re-ingest is not logged), `model.sent` (outbound.py, what went to remote models, added up per 10 minutes), `sync.pull`, `start`. `GET /events?limit=N` serves it; the Settings "Events"/Activity tab (`static/js/settings.js` desktop, `mobile.html` mobile) renders each row expandable to its full record with clickable artifact links, folds runs of sync pulls, and polls to stay live while open. It is local diagnostics only (never synced) and is also the decoy front door to the vault (VAULT.6). Mobile has its own `events` table in `desktop/src/sync.rs` (`log_event`/`read_events`) written by the Rust ask/facet/capture/sync paths and read by `mobile_events`.

### Sync (relay, E2E, device linking)

The desktop engine and the Android app share one E2E model: per-artifact snapshots, last-writer-wins, pushed as opaque ciphertext to a dumb relay, pulled and decrypted on-device.

- **Engine side (Python):** `sync/client.py` (`push_artifact` on every write, `push_all()` for the backfill when sync is turned on, `push_everything()` when a library moves relay), `sync/snapshot.py` (LWW serialize/apply), `sync/worker.py` (SSE + timer pull). Every desktop write path (`notes.py`, `capture.py`, `trash.py` delete/restore, `api/artifacts.py` pin/tag/annotate) calls `push_artifact(id)`. Purge is local-only and final (no row left to snapshot).
- **Mutations propagate both ways (MOBFIX.5, was create-only).** The relay object is now an UPSERT: `relay/storage.py::put()` overwrites in place by name and assigns a FRESH cursor on overwrite (so a device already past the old cursor re-pulls the update), and `relay/app.py` always returns 201. The object name is still id-based (`dev/{device}/artifacts/{id}.enc`), so a later `push_artifact` for the same id rewrites the same object and the newer snapshot lands; the pull's LWW-by-`(updated_at, device_id)` then decides the winner. A mutation only propagates if it BUMPS `updated_at` - the whole current snapshot travels, so the mutation "type" is just a label. On the mobile side the same applies: every write helper must bump `updated_at` and enqueue to `mutation_outbox` (see `queue_mutation_push` in `desktop/src/lib.rs`); the invoke alone does not sync. NOTE: the hosted Railway relay must be running the upsert `storage.py` (redeploy with `bin/deploy-relay` if it still 409s).
- **Mobile side (Rust):** `desktop/src/sync.rs` reimplements the same crypto (XSalsa20-Poly1305 secretbox: nonce(24)||ct||tag; Argon2id KEK) and the relay pull/apply, so it cross-compiles for Android. `desktop/src/lib.rs` `#[cfg(mobile)] mod mobile` holds the Tauri commands: `mobile_link_qr` (persists relay_url + secret + DEK-as-hex via `save_config` into the app-data `sync_config` file), `mobile_sync` (spawns `sync_library` on a background thread, emits `sync-started`/`sync-progress`/`sync-done`/`sync-error`; falls back to the saved config when called with `config:"{}"`), `mobile_status`, `mobile_list`, `mobile_capture`/`mobile_capture_image`/`mobile_save_cropped_image` (write locally + `capture_outbox`), `mobile_outbox_push` (kicks the background outbox worker and returns at once), the write helpers `mobile_update_note`/`mobile_delete`/`mobile_restore`/`mobile_toggle_pin` (each bumps `updated_at` + enqueues a mutation via `queue_mutation_push`), the summary edits `mobile_facet_edit`/`mobile_facet_delete` (bump + queue via `push_artifact_now`), the conversation commands `mobile_chats_list`/`mobile_chat_get`/`mobile_chat_send` (`mobile_chat_send` keyword-retrieves over the local copy and calls `call_llm_mobile` directly - which sends the synced `llm_headers`, e.g. `x-opencode-session`, and surfaces a non-2xx body instead of swallowing it), and `mobile_events` (the local activity log). **The phone is local-first (2026-09-30):** no phone command waits on the network. Every write lands in the phone's SQLite and an outbox row (`capture_outbox` for new items, `mutation_outbox` for changes) and returns; the relay gets it from ONE background worker (`kick_outbox` -> `drain_outbox`, guarded by `OUTBOX_RUNNING`/`OUTBOX_AGAIN` so a burst of kicks costs one or two passes). A drain pushes each artifact once however many rows it has queued (a snapshot is the whole current state) and clears the rows it covered up to a cutoff taken before the snapshot. Offline, rows simply wait: the next write, `sync-done`, app resume or the `online` event (`window.mobileSyncAndReconcile`) kicks the worker again. Before this, `mobile_capture` and the photo saves pushed to the relay inline and `mobile_outbox_push` ran the whole drain as a plain (main-thread) Tauri command, so every save froze the UI for a network round trip. Plain `#[tauri::command] fn` runs on the MAIN thread in Tauri v2: never do network I/O in one, and make hot write paths `async fn` (`mobile_capture`, `mobile_update_note`, `mobile_save_cropped_image`) so even the local write stays off the UI thread. `mobile_sync` and the SSE listener share the `SYNC_RUNNING` guard, so only one pull runs at a time.
New Tauri commands need registration in THREE places: `build.rs`'s `commands(&[...])`, the `tauri.conf.json` capability (`allow-<command-dashed>`), AND the `generate_handler!`; a missing ACL reads as "not allowed. Command not found", not a missing handler.
- **Settings propagate desktop -> mobile, live (MOB2.9, was "as of linking" only).** The desktop pushes its effective LLM config - backend/model/url AND the provider `llm_api_key` from the Keychain - as a DEK-encrypted `lib/settings/{ts}-{device}.enc` object (`sync/client.py::push_settings`), triggered on every settings change (`settings._resync_to_relay`), on api-key store/forget (`api/settings.py`), and once at engine startup (`api/app.py`). The mobile pull (`desktop/src/sync.rs`) decrypts the newest by `updated_at` into `sync_meta['settings']`; `mobile_chat` and `mobile_settings_get` prefer it over the phone-local config, so the phone runs chat with the desktop's provider + key without re-entering anything. The Settings screen is read-only (`managed_by_desktop: true`) and reports only `llm_api_key_present`, never the value. The api_key leaving the Mac is intentional and E2E-encrypted - the phone needs it to call the provider directly. The phone writes tags and notes on a capture too (`mobile_add_tag`, `mobile_remove_tag`, `mobile_add_annotation`, from its Details panel); views and summary switches stay on the desktop.
- **Camera / QR scanner:** `tauri-plugin-barcode-scanner` (ML Kit on Android), vendored under `desktop/plugins/`. It renders the CameraX preview BEHIND a transparent WebView, so the scan handler in `mobile.html` makes the page transparent while scanning. `getUserMedia` is a dead end here: the wry Android WebView does not composite a MediaStream to a `<video>` element - do NOT try to bring it back.
- **Resilience + reachability:** a sync runs while the app is open and re-triggers on app resume and network-regained; while the app is closed, both phones push the outbox and pull through `background_sync` in `lib.rs`: Android from WorkManager every 30 minutes with a network (`SyncWorker.kt`, scheduled in `MainActivity.onCreate`, calling `SyncWorker.syncNow` over JNI in a process where Tauri never started), iOS from a background refresh (see [The iOS app](#the-ios-app)). So no helper the background path calls may take an `AppHandle`: the app's folder is `PHONE_DIR`, set by `setup` or by the JNI entry, and `sync_now(None)` emits no events. To run the Android worker on an emulator, its network must be validated or the constraint holds it; a one-time `OneTimeWorkRequest` with a delay is the easy test (verified 2026-10-27: a note captured offline reached the relay with the app closed). An Android foreground service was written once and never started (its JNI looked up the wrong class); it was removed on 2026-10-27. `desktop_link_code` REFUSES to render a QR for a loopback/127.0.0.1/localhost/LAN-private relay URL (a phone that leaves the house could never reach it) - set a hosted URL first. A transient sync failure must show a cached library + an offline banner, NEVER the setup screen (the phone stays linked; the config persists), and the `sync-error` handler must not `alert()`.
- **Gotcha (bit us 2026-08-19):** a null `getElementById(...).addEventListener` in `mobile.html` throws at init and aborts the WHOLE inline script, so the on-load `bootstrap()`/sync never runs and the library just spins. Guard every listener wiring with `?.` when the element may have been removed.

---

## Encryption and keys

Enqueue is zero-knowledge.
Nothing it stores off a device, and nothing it leaves on a device's disk once set up, can be read without a key only the person holds.
There is no reset: Enqueue keeps no copy of any key, so the recovery kit is the way back after every device is gone.

### The keys

| Key | What it is | Where it lives | What it locks |
| --- | --- | --- | --- |
| Library key | 32 random bytes, made once (`libkey.py`) | macOS Keychain, `enqueue-library-key` | the root: everything on the Mac derives from it or is wrapped under it |
| Disk key | derived from the library key, `disk` | nowhere; derived when needed | the library database on the Mac (SQLCipher) |
| Backup key, backup-names key | derived, `backup`, `backup-names` | nowhere | every file in the backup folder, and their names |
| Sync key (DEK) | 32 random bytes | Keychain `enqueue-sync-dek`; the phone's sealed config; `keyring.json` wrapped under the library key (`dek_by_library`) and under the old recovery phrase | everything on the relay |
| Relay names key | HMAC of the sync key, `enqueue relay names v1` | nowhere | the names of relay objects |
| Phone store key | 32 random bytes, made on the phone | Android: `filesDir/store_key`, encrypted by an Android Keystore key (`StoreKey.kt`); iOS: a Keychain item, this device only (`store_key` in `lib.rs`) | the phone's database (SQLCipher), its sealed secrets, its file cache |
| Vault key | 32 random bytes | wrapped under the 6-digit PIN (and a fingerprint-guarded Keystore secret on the phone) | vaulted items, a second lock inside everything above |

The recovery kit is the library key written as 56 Crockford base32 characters (with a checksum).
It recovers, on a new Mac: the backups, the library inside them, and the sync key (from the `keyring.json` in the backup), so sync comes back too.
The phone needs none of it: it is linked by scanning the Mac's code, which hands it the sync key, and its own store key never leaves it.

### At rest

- **Mac, library:** a SQLCipher database once the recovery kit is saved (`db.encrypt_library`, at the engine's start; checked by integrity and row counts before it replaces the plain file).
  Before the kit is saved the library stays plain on purpose: a lost Keychain would otherwise lose the library itself.
  Every connection comes from `db.connect`, on SQLCipher's driver (`sqlite.py`), which reads a plain file too.
- **Mac, original files (`blobs/`):** sealed once the recovery kit is saved (`blobstore.py`, 2026-10-26): each file under the `blobs` key derived from the library key, in the backups' secretstream format behind an `ENQF` header, named by the hash of its plaintext as before.
  Everything reads and writes through `blobstore` (`write`, `read`, `replace`, `size`, a `Handle` for the vault); a PDF opens from its bytes (`capture.open_pdf`), OCR gets the picture on stdin, the blob route serves the plaintext; nothing decrypted is written to disk. Plain files from before are sealed in place at engine start (`seal_all`, each read back before it replaces the plain copy), and a recently read file stays decrypted in memory (256 MB at most) so a PDF's pages do not decrypt the whole file each time.
  Before the kit is saved the files stay plain, like the database, so a lost Keychain cannot lose them. Backups take the sealed files as they are; the same library key opens them after a restore.
  Encrypting them means routing PDF rendering, previews and captures through a sealed reader; left for later.
- **Backups:** every file sealed (libsodium secretstream) under the backup key, named by keyed hashes, checked by opening it again (`backup.py`).
- **Phone (Android and iOS):** the database is SQLCipher (`bundled-sqlcipher-vendored-openssl`), the sync config and vault records are sealed files, and the file cache is sealed; all under keys derived from the store key.
  A plain database and plain files from an older build are converted the first time they are opened.
  The quick-capture inbox (thoughts written in the launcher popup before the app files them) is sealed with the Keystore key too (`QuickCaptureInbox`, `StoreKey.seal`), since the popup runs without Rust.

### In transit (the relay)

- Every object is sealed under the sync key, padded to a size bucket (a power of two from 256 bytes, then multiples of 64 KiB), and named by a keyed hash of its id (`crypto.seal_payload`, `crypto.object_name`; the same in `desktop/src/sync.rs`).
- The relay still sees: how many objects, their bucketed sizes, when they change, and which device namespace wrote them.
- Libraries synced before this were re-pushed once under the new names (`repush_relay_v2`), and each device's old id-named objects deleted, on a relay that has the DELETE route (redeploy the hosted relay with `bin/deploy-relay`).

### Not built: hosted sign-in with a passkey

The paid tier's promise is that a new device signs in with a passkey (Face ID, Touch ID, the phone's lock) and the library arrives, with no recovery kit typed.
The design: the library key is wrapped under a key the passkey derives with the WebAuthn PRF extension, and only that wrapped copy is stored on our server.
The server holds ciphertext; the passkey stays in the person's Apple or Google account.

What it needs, in order:

1. A domain for the service, serving `/.well-known/apple-app-site-association` and `/.well-known/assetlinks.json`.
2. An account server (beside the relay) that stores per account: the wrapped library key, the relay secret, and WebAuthn credentials; with WebAuthn registration and assertion endpoints.
3. The macOS app signed with an Associated Domains entitlement (`webcredentials:<domain>`), since a passkey in a non-Safari web view needs it; likely a small native bridge (ASAuthorizationController with the PRF extension) because WKWebView's WebAuthn support in an embedded app is limited.
4. The Android app with Credential Manager (`androidx.credentials`) and the PRF extension, and the asset links file.
5. A sign-in screen on both: "Sign in with a passkey" restores the library key, then the relay secret, then the sync key from `keyring.json` (or from the account record).
6. Server-side guess limits for the vault PIN, which the hosted server makes possible (the PIN's wrap stays the person's; the server only counts attempts, as Signal's secure value recovery does).

The free tier keeps working without any of it: the person runs their own relay and keeps their recovery kit.

## The relay

A dumb byte store (`src/enqueue/relay/`): objects keyed by name, a cursor that moves on every write, and a "something changed" stream.
It parses nothing, holds no key, and can decrypt nothing. The hosted one also keeps accounts (who signed in, and which device tokens open which library), never anything that opens a library.

- **Libraries.** One relay serves many libraries (2026-10-16). A library is known only by the SHA-256 of its relay secret (`storage.library_id`); every object, cursor and change notice belongs to one library, and nothing one library does is visible to another (cursors are per library, so not even how often it writes). Two libraries both writing `lib/vault.enc` never collide, and a DELETE reaches only the caller's own objects. The relay stores no secret, only hashes, so its database lets no one in.
- **Issuing libraries.** The secret the relay starts with (`RELAY_SECRET`) is the first library, and a relay from before libraries moves its objects into it on first start (resumable: the old table is dropped only once every row is copied). Others are made with `enq relay-admin add "<who>"` (prints the secret once), listed with `enq relay-admin list` (label, size, objects, live or revoked) and refused with `enq relay-admin revoke <id>`; these call `/admin/libraries`, which exists only when `RELAY_ADMIN_SECRET` is set (`RELAY_URL` and `RELAY_ADMIN_SECRET` in the environment, or `--url`/`--admin-secret`). An unknown or revoked secret is 401.
- **Accounts (the hosted relay, 2026-10-19).** With `DATABASE_URL` set (Railway Postgres; SQLite in tests), `relay/accounts.py` adds sign-in with Google or Apple and one relay token per device, after Dequeue's pattern (`~/dequeue/backend/app/auth.py`). A self-hosted relay without it has no accounts and never touches a database.
  Id tokens are verified, never just decoded: the provider's signature (its published keys), the issuer, the expiry, and an audience that is one of our clients (Google: `GOOGLE_CLIENT_ID`, the Web client, and `GOOGLE_DESKTOP_CLIENT_ID`; Apple: `APPLE_CLIENT_ID`, the Services ID, and `APPLE_BUNDLE_ID`). With no client ids set, sign-in answers 503 rather than accept a token issued to any app.
  The Mac's Google sign-in posts its one-time code to `POST /auth/google/desktop`, which does the exchange with `GOOGLE_DESKTOP_CLIENT_SECRET`, so no secret ships in the app.
  Apple's web flow (Services ID `com.sudohnim.enqueue.signin`) posts to `POST /auth/apple/callback`, which sends the browser on only to the Mac's own engine (`http://127.0.0.1:<port>/account/apple/done`, nothing else) with a one-time code; the engine swaps it at `POST /auth/handoff` (two minutes, one use, kept as a hash in `handoffs`). Dequeue put the tokens themselves in whatever address the request named.
  `POST /auth/google` / `/auth/apple` return a 15-minute access token and a refresh token that is a row (`refresh_tokens`): `/auth/refresh` swaps it (the old one keeps working 5 minutes, for a lost reply), `/auth/logout` ends its family, `/auth/logout-all` every one. Production refuses to start on a `JWT_SECRET` under 32 characters.
  `POST /account/devices` makes the account's library on first use (`storage.add_account_library`: a library no secret opens) and returns a device token (`enqd_...`, shown once, stored as a hash); the relay takes it where it takes a library secret, after the secrets (`app._library`), cached 15 seconds. `DELETE /account/devices/{id}` cancels one; `DELETE /account` ends every session and device and revokes the library.
  Sign-in proves who someone is and opens nothing: the library's key still reaches a device only from the Mac's QR code or the recovery kit. The tables are created at start (`metadata.create_all`); the first column added later starts an Alembic history for this database. `tests/test_relay_accounts.py` signs tokens with a key it makes in place of Google's and Apple's.
- **Where the bytes live (2026-10-20).** The relay's SQLite file (`relay.db` in `RELAY_DATA_DIR`) is the index: per object its library, name, cursor and `size`, and either the bytes (`data`, a self-hosted relay) or a `blob_key` into Cloudflare R2 (the hosted one), with `data` empty. R2 is on only when all four of `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` and `R2_BUCKET` are set (`relay/blobs.py`, boto3 from the `hosted` extra); some but not all refuses to start.
  A blob key is `<library id>/<SHA-256 of the name>/<random>`, a fresh one per write: `storage.put` uploads beside the old copy (outside the lock, off the event loop), switches the row in one transaction (quota checked again there), then deletes the old copy, so a reader never meets half an object and two writes of one name cannot leave the row's size and bytes disagreeing. Cursor, upsert, quota (`used_bytes` is a sum of `size`), `LibraryFull` and isolation are unchanged; `tests/test_relay_blobs.py` runs the same rules both ways and the adapter against moto.
  A failed upload changes nothing and answers 503 (`BlobStoreError`); a failed delete of a superseded copy only leaves an orphan, which costs storage, not data. A row whose copy is missing or the wrong size is a 503, never a 404.
  At every start `storage.start_upkeep` runs in a thread: it finishes interrupted purges, then moves bytes still in the file into R2 (`move_to_blob_store`), one object at a time, each copy read back and compared before its row lets go of the bytes, and only if no write replaced the row meanwhile; it stops at the first failure and resumes at the next start, and the relay serves from the file for anything not moved yet. It vacuums the file once something moved.
  **Revoking a library deletes what it holds** (`revoke_library`, which `enq relay-admin revoke` and account deletion call): its rows at once, then every R2 key under `<library id>/` (orphans included). A blob store that fails leaves `libraries.purged_at` empty and the next start finishes it; libraries revoked before this rule are cleared the same way. It cannot be undone, so `enq relay-admin revoke` asks first.
- **Limits.** An object over `RELAY_MAX_OBJECT_BYTES` (100 MiB) and a write past a library's storage limit (`RELAY_QUOTA_BYTES`, 5 GiB, or the library's own `--quota-gb`) are 413; at most 256 pairings wait at once. `enq relay` refuses to listen on anything but loopback with `dev-secret` or a secret under 24 characters.
- **Setup.** The desktop's sync setup asks for the relay password and checks it against the relay first (`PUT /settings/sync-secret` with `relay_url`, `api/settings._relay_refuses`), so a made-up one is refused there instead of failing every sync after. There is no "make one" any more: a relay only ever opened the secret it ran with.
- **Auth.** Each library's own secret (in each device's Keychain or sealed config): `Authorization: Bearer <secret>` on HTTP, `?token=<secret>` on the SSE stream (an `EventSource` cannot set headers); the relay blanks it in its access log (`app.hide_tokens_in_access_log`), which once held every library's password.
- **Routes.** `GET /sync/objects?since=<cursor>` lists names changed after a cursor (and the new cursor); `GET /sync/object/<name>` fetches one; `PUT /sync/object/<name>` stores or overwrites one (an upsert takes a fresh cursor, so a device past the old one pulls the update again); `DELETE /sync/object/<name>` removes one (a device clearing its own superseded copies); `GET /sync/events` streams a line per write; `PUT`/`GET /pair/<id>` carry a one-time sealed envelope for adding a computer.
- **Names.** `dev/<device_id>/artifacts/<hash>.enc` and `dev/<device_id>/chats/<hash>.enc` (the id hashed under the names key), `blobs/<hash>`, `lib/settings/<time>-<device>.enc` (the newest by its own `updated_at` wins), `lib/vault.enc`, `lib/pivots.enc`. A device writes only under its own `dev/<device_id>/`, and reads everything.
- **Running one.** `enq relay --host 0.0.0.0 --port <port> --secret <long random> [--admin-secret <long random>]` (or `RELAY_HOST`/`RELAY_PORT`/`RELAY_DATA_DIR`/`RELAY_SECRET`/`RELAY_ADMIN_SECRET`), behind TLS (Caddy, nginx, the host's own), on a data folder that survives restarts. With R2 the volume holds only the index (a few hundred bytes per object); the bucket `enqueue` is in the Cloudflare account, with an R2 API token scoped to Object Read & Write on that bucket alone, and the four `R2_*` variables are on the Railway service. `bin/deploy-relay` deploys the hosted one: the `enqueue` service in the `enqueue` Railway project, with a Postgres service beside it whose `DATABASE_URL` reaches the relay as a reference over Railway's private network. It is the live relay for every linked device. **Staging** (made 2026-10-26) is the `staging` environment of the same Railway project: the same services with their own volume, Postgres and secrets (in the Keychain as `enqueue-staging-relay-secret` and `enqueue-staging-relay-admin-secret`), no R2 (its bytes stay on its volume) and no purchase webhook, at `https://enqueue-staging.up.railway.app`. Deploy there first with `RAILWAY_ENVIRONMENT=staging bin/deploy-relay`; point a test Mac at it with `ENQ_HOSTED_RELAY_URL` and its own `ENQ_DATA_DIR`. Sign in with Apple needs the staging callback added to the Services ID before it works there. Wait for the new build before trusting `/health`, since the old one keeps answering while it rolls out. For a test, `enq relay` plus `cloudflared tunnel --url http://127.0.0.1:8788`. No CORS: every client is native (Python `httpx`, Rust `ureq`).
- **Reach.** A headless emulator reaches a relay on the Mac at `10.0.2.2:8788`; a phone that leaves the house needs a public `https://` address, and the desktop refuses to show a linking QR for a loopback or private one.

## Database schema

SQLite at `~/Library/Application Support/Enqueue/enqueue.db`.
WAL mode, foreign keys on.
Migrations run automatically at startup via Alembic.

### Tables

| Table | Purpose | Notes |
| --- | --- | --- |
| `artifacts` | the primary model | `kind` is note/link/pdf/image/file. `content_hash` UNIQUE for dedupe. Captures have `body IS NULL` (CHECK constraint). Notes have editable body. |
| `artifact_versions` | the drafts kept of a note's body | one per 5 minutes of writing, plus each stretch's start and the latest; the newest is rewritten in place until then |
| `annotations` | commentary on a captured artifact | append-only, superseding by id |
| `chunks` | literal layer for search | text, ordinal, chunker name; `context` + `context_model` (model-written placement line, multi-chunk artifacts only) |
| `facets` | conceptual layer for search | level 0-4, statement, model_version, trust (default 0.5), `edited` (1 = hand-written/edited, protected from regeneration; migration 0031) |
| `facet_skips` | artifacts excluded from facet generation | reason: too_short/kind/text_only/gate, or `off` (the person's switch; only `facets.set_summary` clears it) |
| `facet_retry` | an artifact owed a run of the model steps: after a transient failure in any of them (sections, facets, entities, contexts), or while a note is still being written (`last_error` = `queue.WAITING`) | attempts, next_at, last_error; retried with backoff (30s doubling to 24h) by the sweeper, which re-runs the whole artifact; cleared only by a run in which no step owed |
| `events` | the activity log (migration 0032) | ts, kind, detail, JSON `data`, duration_ms. Local-only, never synced. Bounded/trimmed. |
| `secret_hits` | credential patterns found in artifact text | redacted excerpts only |
| `page_text` | extracted text per PDF page | derived, rebuildable |
| `link_previews` | what a saved link turns out to be | status, title, description, site_name, image_hash |
| `chats` | conversations | scoped to everything/artifact. pinned. |
| `chat_messages` | one turn | append-only. grounded flag. |
| `chat_citations` | what an answer was built from | message to artifact, ranked |
| `chat_topics` | concepts a conversation circles | derived, regenerable |
| `related` | links between artifacts about the same subject, naming the same thing (`via`), or judged to make the same point; `point` is the reason shown, `kind` which of the three, `distance` how far apart their fields are | derived at ingest, both directions, filtered to live artifacts on read |
| `related_pending` | artifacts with cross-field pairs the judge has not ruled on | the judge worker's queue; survives restarts; purge deletes an artifact's row |
| `related_state` | key/value for related links: the rule's `version`, the judge's `judge_day` count | local only |
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
3. **What a person wrote can be gone back to.** Editing a note keeps a draft in `artifact_versions` before updating `artifacts.body`: the state at the start of every stretch of writing, one for each `config.DRAFT_EVERY_S` (5 minutes) of it, and the latest (see "A note being written keeps a slower clock"). It is not one row per save; the saves in between were seconds apart and are rewritten in place. Annotations are append-only. Purge is the only destructive operation, and only on trashed artifacts.
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
2. **settings.json** (`~/Library/Application Support/Enqueue/settings.json`) - what was chosen in the interface. Plaintext, chmod 0600.
3. **config.py default** - the built-in default.

### Key config values

| Variable | Default | What it controls |
| --- | --- | --- |
| `ENQ_LLM_BACKEND` | `enqueue` | Which backend to use: enqueue (included), openrouter, anthropic, openai, opencode-go |
| `ENQ_LLM_MODEL` | `anthropic/claude-haiku-5.5` | The interactive model id (chat, routing, gray-zone judge); the other roles fall back to it. |
| `ENQ_SUMMARIZE_MODEL` | (empty) | The ingestion model (facets, entities), `role="ingest"`. Empty falls back to `llm_model`. See "Model roles". |
| `ENQ_SEARCH_MODEL` | (empty) | The search model (gray-zone relevance judge), `role="search"`. Empty falls back to `llm_model`. |
| `ENQ_LLM_API_KEY` | (empty) | API key for a service of your own (OpenRouter, OpenCode Go) |
| `ENQ_LLM_HEADERS` | (empty) | Extra provider headers, one `Name: value` per line. Required for `opencode-go` (`x-opencode-session: <uuid>`). Synced to the phone so mobile chat can call the same endpoint. |
| `ENQ_VECTOR_STORE` | `sqlite-vec` | The search index backend. `sqlite-vec` is the only backend after the cutover. |
| `ENQ_MODEL_RETRIES` | `3` | TOTAL attempts per structured call (instructor's `max_retries`); 1 = one shot, no reprompt |
| `ENQ_PREVIEW_BROWSER` | `on` | Open a refused or script-only link once more in the Mac's own WebKit (`webkit_page.py`) |
| `ENQ_BACKUP_DIR` | (empty) | The cloud-drive folder backups go into; empty = backups off |
| `ENQ_USER_AGENT` | `Enqueue/0.2 (...)` | User agent for preview fetches |
| `ENQ_HOTKEY` | `Alt+Shift+E` | Global capture hotkey |
| `ENQ_AUTO_PREVIEW` | `on` | Whether saving a link auto-fetches a preview |
| `ENQ_TRASH_DAYS` | `30` | Trash retention window in days |
| `ENQ_SEARCH_MODEL_RANK` | `off` | The `search_model_rank` setting: the search model re-orders the top 20 results of `/search` (`retrieve/model_rank.py`). |
| `ENQ_SEARCH_JUDGE_WAIT` | `2.5` | Seconds `/search` waits for the gray-zone judge before answering without it. |
| `ENQ_DRAFTS_KEEP` | `thinned` | How many drafts are kept as they age (`drafts.py`): thinned, 30d or off. |
| `ENQ_DRAFT_EVERY` | `300` | Seconds between the drafts kept of a note while it is being written. 0 keeps one per save. |
| `ENQ_SUMMARY_QUIET` | `300` | Seconds a note must be left alone before the model reads it again. 0 summarizes at every save. |
| `ENQ_PEER_SUMMARY_WAIT` | `1800` | Seconds a desktop leaves an item another desktop wrote for that desktop to summarize, plus its own share of the same again. 0 summarizes pulled items at once. |
| `ENQ_PEER_PHONE_WAIT` | `600` | The spread over which desktops take turns summarizing an item a phone wrote. |
| `ENQ_CHAT_PREP_WAIT` | `8` | Seconds an answer waits for the search model to restate a follow-up or lift a question before retrieving without it. |
| `ENQ_SEARCH_RERANK` | off | Opt-in cross-encoder rerank of the top fused search candidates (R.9). Off by default; measured net-neutral on the golden set. |

### Where secrets live

The API key goes in the macOS Keychain via `/usr/bin/security`, never in settings.json.
`keyring.py` handles this.
Each service keeps its own key (`enqueue-llm-api-key.<backend>`; `keyring.get(backend)`, `config.llm_api_key(base_url)` finds the backend by its URL), so switching service never sends one service's key to another, and switching back finds the old key.
A key saved before the split (`enqueue-llm-api-key`) counts for openrouter and opencode-go only, the services there were then.
`PUT /settings/api-key` takes the `backend` a person picked but did not save yet; Settings sends it, and the key row follows the picked service (`paintKeyRow` in `static/js/settings.js`).
On non-macOS, `keyring.available()` returns false and the key must come from the environment.
The key is resolved per-call (not at import) so a key stored in Settings takes effect immediately.

### Backends

| Name | URL | Local | Needs key |
| --- | --- | --- | --- |
| enqueue | the relay's `/ai/v1` | no | no (this Mac's device token) |
| openrouter | `https://openrouter.ai/api/v1` | no | yes |
| anthropic | `https://api.anthropic.com` | no | yes (its own adapter) |
| local | `http://127.0.0.1:11434/v1` (Ollama) | yes | no |
| openai | `https://api.openai.com/v1` | no | yes |
| opencode-go | `https://opencode.ai/zen/go/v1` | no | yes + `x-opencode-session` header |

Every backend but `anthropic` speaks the OpenAI-compatible protocol (`protocol` in `config.BACKENDS` picks the adapter, `providers.base._provider`).
One adapter (`OpenAICompatibleProvider`) covers them; it sends `ENQ_LLM_HEADERS` (the `llm_headers` setting) as extra headers.
`opencode-go` returns `400 MissingSessionID` without an `x-opencode-session: <uuid>` header - set it via `llm_headers`. The header lives in the setting, the api_key in the Keychain; both sync to the phone (`sync/client.py::push_settings` includes `llm_headers`) so mobile chat can reach the same endpoint. Mobile parses and sends them in `call_llm_mobile` (`desktop/src/lib.rs`).

### Important: 127.0.0.1, never localhost

`config.py` binds to `127.0.0.1`, not `localhost`.
This machine may run a second Ollama in Docker bound to the IPv6 wildcard, and `localhost` resolves to IPv6 first.
This applies to the engine and every local address it calls.

---

## Provider layer

One narrow interface, two adapters: `OpenAICompatibleProvider` for every OpenAI-protocol backend, `AnthropicProvider` for Anthropic.

```python
class Provider(Protocol):
    name: str
    model: str
    def complete(self, system, user, response_model, context=None, max_retries=None) -> T: ...
```

`get_provider(local_only=False, summarize=False)` returns the configured provider.
Local-only artifacts reach only a model on this Mac: `get_provider(local_only=True)` raises `LocalOnly` unless the chosen backend is `local` (`base.local_model_on`), and otherwise ingest treats them like a switched-off summary (`facets.summary_off`); the related judge, Something shiny and image OCR follow the same switch. Choosing a backend runs `backfill_summaries`, so local-only items are read once Ollama answers. The phone cannot reach the Mac's model: with `local` chosen, `sync.client.phone_settings` gives the phone the included assistant.
This is the one rule that is not a preference: marking something local-only is a promise that its text never leaves the machine.

**Model roles.** `get_provider(role=...)` picks one of three models, all on the same backend, key and headers (`providers/base.py` `ROLE_SETTINGS`, `model_for`):
- `chat` (`llm_model`): chat answers, titles/topics, `assistant.route`, pivot planning and `derive`.
- `ingest` (`summarize_model`, UI label "Ingestion"): facets and entities. `summarize=True` is the older spelling of `role="ingest"`. The storage name stays `summarize_model` because it syncs and lives in existing settings files.
- `search` (`search_model`): the gray-zone relevance judge.
Blank `ingest`/`search` fall back to `llm_model`, so a single-model setup is unchanged. Local-only artifacts get no model in any role. A facet is stamped with the ingest model that wrote it; retrieval keeps it whichever model that was, and changing the ingest model rewrites the library once (`refresh_on_model_change`). The Settings AI tab has a "Models" group (Chat, Ingestion, Search, Images) with a picker of the backend's known models. `test_model_split.py` covers the routing.

The adapter builds its OpenAI/instructor client lazily on the first model call, so `get_provider().model` is free (the search staleness checks read it on every query; building the client costs ~50 ms plus a Keychain subprocess on macOS).

The adapter uses `instructor.Mode.JSON` for all endpoints.
The old AGENTS.md specified different modes per adapter, but the code does not.
See the questions section above.

**Anthropic (`providers/anthropic.py`, 2026-10-28).** The official SDK, not Anthropic's OpenAI-compatible endpoint. A structured call asks for `output_config.format` with `anthropic.transform_schema(response_model.model_json_schema())` (constraints the API cannot enforce are dropped from the schema and checked here), then validates with `model_validate_json(text, context=...)`, so the validators that read `context` (proper nouns, offered ids) run as they do under instructor. A reply they refuse is sent back with the error, up to `MODEL_RETRIES` attempts in all. No `temperature`/`top_p`/`top_k` (a 400 on current models), no `thinking` setting (each model's default), `max_tokens` 16000. A `refusal` stop or a cut-off reply is a `ProviderError`. `providers.base._is` names the OpenAI or the Anthropic SDK's error, so `why`, `is_transient`, `key_rejected` and the usage-limit pause treat both alike. The phone calls `/v1/messages` with `x-api-key` and `anthropic-version` (`call_llm_mobile`). Model lists: `catalog.KEYED` asks OpenAI and Anthropic with the person's key (only models with structured outputs from Anthropic; OpenAI's chat ids by prefix), so with no key nothing is refused.

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
| `enq restore <dir or file> [--kit KIT]` | Put a backup in place (engine must be stopped; works on the files directly, like `migrate`); asks for the recovery kit when this Mac does not hold the backup's key |
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
GET    /shiny?n=                    today's Something shiny (n: Find another): 2-3 notes from different fields (wall items), the idea they share, `more`
GET    /greeting                    the wall's greeting for the current four-hour bucket (cached or fallback)
GET    /artifacts                   list, newest first. ?limit&offset&order&pinned
GET    /artifacts/{id}              detail, body, annotations, facets, versions
GET    /artifacts/{id}/text         readable text, with page numbers for PDFs
GET    /artifacts/{id}/connections  per passage, the other notes that say something close
GET    /artifacts/{id}/blob         original bytes
GET    /artifacts/{id}/find?q=      phrase locations in a PDF (page fractions)
GET    /artifacts/{id}/preview-image  link's stored picture
GET    /artifacts/{id}/page/{n}     rendered PNG of a PDF page
GET    /titles                      every live artifact's id, title and kind, for name matching in the page
GET    /search?q=                   hybrid search, no model calls; kind/time words become filters (returned as `filters`)
GET    /chats                       conversations, pinned first
GET    /chats/ready                 whether there is anything to answer from
GET    /chats/{id}                  transcript, citations, topics
GET    /pivots                      saved views
GET    /pivots/{id}                 one saved view
GET    /settings                    all settings + storage + backends
GET    /secrets                     credential scan hits
GET    /trash                       what is in the trash
GET    /events?limit=N              the activity log, newest first, each with its full record
GET    /setup                       what is connected, what is left to set up, settings that need a look
GET    /reading                     how far the assistant is through reading the library (the wall's progress line)
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
POST   /capture/link                 save a URL, nothing fetched
POST   /capture/upload               multipart file upload
POST   /artifacts/{id}/preview       fetch what a saved link is (opt-in)
POST   /chats                        start a conversation (optionally with text)
POST   /chats/{id}/messages          one turn
PATCH  /chats/{id}                   rename / pin
DELETE /chats/{id}                   the one deletable object
POST   /pivot/run                     re-run a saved view spec
POST   /pivots                        create a saved view
PATCH  /pivots/{id}                   rename a saved view
DELETE /pivots/{id}                   forget a saved view
POST   /pivots/manual                 create a view arranged by hand (optionally from another view's groups)
PUT    /pivots/{id}/layout            replace a hand-arranged view's headers and order
POST   /pivots/{id}/remove            remove artifacts from a locked view (recorded; no recompute)
POST   /pivots/{id}/restore           put removed artifacts back in the groups they left
POST   /pivots/{id}/refresh           Rebuild: re-run the spec and re-freeze the result
GET    /pivots/{id}/open              the frozen view, cards hydrated fresh
POST   /chunk                        rebuild all chunks
POST   /facet-gate                   re-evaluate facet eligibility
POST   /facets                       generate facets
PUT    /artifacts/{id}/summary      switch the AI summary for one artifact ({on})
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
POST   /setup/ask                    answer a question about settings from the page's matched guides
POST   /backup                       back up now (background; GET /backup shows it land)
POST   /backup/kit                   the recovery kit, to show once (a POST, so only the engine's own page gets it)
POST   /backup/kit/saved             the person kept the kit (Settings stops asking)
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
4. **Fuzzy** - rapidfuzz's Indel ratio (difflib's ratio, in C) over short fields (titles, entity names, current annotation lines) for one-edit typos trigram cannot see (R.7).
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

Dense kNN always returns a nearest neighbor however far, so a no-match query would return a wall. The floor is a two-tier gate on the raw legs (not the fused score): any lexical leg or `dense_similarity >= KEEP_ABOVE` keeps; `< DROP_BELOW` drops; the gray zone is settled by one batched model judgment (`judge_gray_zone`), failing open. A search with zero survivors returns `[]`. `chats.passages()` applies the same `_floor_verdict` gate (Q.5 chunks, Q.10 facets/entities) without the judge call: below the floor is dropped, the gray zone is left to the answering model (see "The judge never holds a search"). The two constants and the gray-zone judge are tuned against the evals (see the notes below).

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
That holds for chat too: `chats._library_passages` once counted a trigram hit as lexical, so a question's filler words ("what", "the", "about") carried unrelated passages past the floor, filled the 8 slots, and left room for one judged passage.
It now judges the gray zone first and fills in ranked order.

**Keyword queries use content words (`store_sqlite._content_terms`).**
A search longer than `_NAME_WORDS` (3) is a question: filler words (`_FILLER`, the same list as `query_terms` in `desktop/src/sync.rs`) are dropped before the FTS5 and trigram queries are built, because every remaining word must match and "what did I save about X" never matched anything.
A search of up to three words is a name or a phrase and keeps every word ("the good life" is not "good life").
Bare punctuation is never a word.
Ranking rows that hold only SOME of a question's words (an OR fallback) was tried and dropped: it lifted the lexical decoys and took the cross-domain eval from 7/12 to 4/12.
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

**Naming a thing costs no search.**
`static/js/suggest.js` (shared by the desktop and the phone, like linkpop) ranks a list of `{id, title, kind}` against what has been typed, in the page: exact title, title prefix, every typed word starting a title word, substring (3+ characters), then every typed word within one slip of a title word (two in a word of 8+; none in a word under 4; a word still being typed is compared with the start of the title word), then letters run together.
No request per keystroke, no index, no embedding, no model.
On the desktop the home search bar drops the candidates down under the field (`mountSuggest` in `js/home.js`, an ARIA combobox/listbox), from `GET /titles` (every live artifact, refetched on focus when older than 20s); the last row is always "Search everything for ...".
Enter acts on the filled row: a confident match (`Suggest.STRONG`, 80+) is preselected and opens the artifact (recorded as an open with source `suggest`); anything looser, a misspelling included, is offered but leaves Enter on the full search, so Enter never opens something that was not named.
A `#tag`, `tag:` or quoted query shows no candidates.
The phone has no list of its own (its results are already live under the field): name matches from the full listing (`everyArt`) are put first and the keyword hits (`mobile_search`) follow.
`tests/js/suggest.js` (run by `tests/test_suggest.py`) pins the ranking.

**Title pin.**
An unquoted search that IS an artifact's title (case, punctuation and spacing aside) puts that artifact first, then titles containing the query as a whole-word phrase (two or more words only), newest first, ahead of the fused list (`_title_hits`, `why: "title"`).
Fusion alone does not honour a typed name: "The good life" ranked the note called The Good Life second, behind one whose summary sat closer.

**The judge never holds a search.**
`_apply_floor` waits `config.SEARCH_JUDGE_WAIT_S` (2.5s, `ENQ_SEARCH_JUDGE_WAIT`) for the gray-zone judge (`_judge_in_time`); past that the search answers from cached verdicts, keeps what was never judged as `loose` (shown last, under the page's line that says so), and the judge finishes in the background and caches, so the same search is exact next time.
At most two judges run on past their search (`_JUDGES`); a search that finds both busy answers without one.
A thinking model with reprompts once held a search for an exact title for 94 seconds.
Chat does not call the judge at all (2026-10-10): its gray zone goes to the answering model, which reads every passage and is told to refuse when none fits, so a judge before it was the same model ruling twice on less text, for one or two more round trips per answer.
`chats._library_passages` still drops below `DROP_BELOW` and still honours a verdict `/search` has cached (`_cached_verdicts`: a cached "no" drops the passage).

**A cross-encoder cannot be the judge (measured 2026-10-10).**
Three local rerankers were scored on every floor survivor of both evals and a real library: ms-marco-MiniLM-L-6 (80 MB, ~0.2 s a search), jina-reranker-v1-tiny (130 MB) and bge-reranker-base (1 GB, 2 to 6 s a search on CPU, slower than the model judge's wait).
All three score the cross-domain targets exactly like noise (MiniLM: targets -11.5 to -10.6, hits of "nothing" queries -11.4 to -11.1), because a cross-encoder reads shared words and the cross-domain suite is built to share none; used to drop, any of them deletes the matches the facet layer exists to find.
MiniLM can only confirm: no hit of a "nothing" query scored above -11.14, and 37 of 44 real matches did.
That would settle a few hits per search early and still leave the rest to the model judge, so it was not built: a third relevance mechanism for a small gain.

**Fuzzy leg (R.7).**
`FUZZY_BASE_SCORE = 0.02` sits between a single-leg rank-1 RRF hit (~0.016) and a dual-leg one (~0.033), so a typo match wins only when the hybrid was weak.
It scans titles, entity names and current annotations, gated by `_needs_fuzzy` (PERF.1), with rapidfuzz's `score_cutoff` doing the pruning. It was `difflib.SequenceMatcher` until 2026-10-27 (a quarter of a search); on the eval corpus the two agree on every typo pair at and above the bar.

**Recency (R.8).**
A note touched today scores 1.5x, one from 180 days ago is unchanged; relevance still dominates.

**Usage.**
`opens.usage_boost` multiplies a hit's fused score by `1 + 0.2 * use / (use + 3)`, where `use` is the decayed count (tau 90 days) of the artifact's opens (any source) and chat citations, plus 3 if it is pinned.
It saturates below 1.2x and stays under the recency boost, so relevance still decides and one burst of use fades; it only reorders, never adds or floors a hit.
The committed evals have no opens, so it cannot move them; `enq eval-real` is where to watch it.

**Rerank (R.9).**
The cross-encoder runs on CPU only: a second CoreML model in the process leaks contexts until the OS kills it (SIGKILL, "Context leak detected").

**Staleness.**
A facet, entity or section hit counts only while its `body_version` matches the artifact's latest `artifact_versions` row (`hit_is_stale`). The model that wrote it does not matter: it may have come from another device, and keying staleness to the model made a second desktop on another model rewrite the whole library (see "Two desktops read an item with the model once").
A line the person wrote or rewrote (`facets.edited`) is never stale: `add_facet` stamps it `model_version = 'edited'`, which matched no model, so hand-written lines never counted in search until `hit_is_stale` learned to pass them.

**Chat passages.**
The budget follows the answering model (`chats._budget`): a model on this machine gets `PASSAGES` (8) passages clipped to `PASSAGE_WORDS` (220), because a local 8B model given more summarizes instead; a hosted one gets `REMOTE_PASSAGES` (20) at `REMOTE_PASSAGE_WORDS` (400), which is every chunk whole.
At most `CHUNKS_PER_ARTIFACT` chunks per note so one long note cannot take the whole budget (the "do I have notes on a president" case).
A facet or entity hit pulls its artifact's opening chunk in, so the answer has literal text to stand on.
A scoped chat reads its artifact whole when it fits the budget, with no search.
One that does not fit (26% of one real library's artifacts, up to 81 chunks) used to be cut to its first 8 chunks, so nothing past the opening pages could be answered.
`_scoped_passages` now gives the answer the document in brief (`_overview`: its current section summaries, else its current summary lines, as one passage with id `overview:<artifact id>`), its opening chunk, and the chunks that best match the question (`store.search_within`: the artifact's own vectors against the query plus the keyword leg kept to its chunks, RRF), in document order.
An artifact not indexed yet falls back to its opening.

**A follow-up is searched as the question it stands for (`chats._standalone`).**
"What about the second one?" used to be searched for as those words: the conversation reached the answering model but never the search.
On any turn after the first, the search model reads the last `REWRITE_TURNS` (6) turns and the new message and returns the message as one self-contained question (`prompts.CHAT_REWRITE`, `schemas.Standalone`), together with the lifted claims for it, which are stored in the lift cache so retrieval does not ask again.
Retrieval runs on that question; the answering model still gets the message as typed, with the conversation above it.
A chat scoped to a local-only artifact is not answered.

**An answer's model calls.**
A first question costs two calls before it lands: the lift (search model) and the answer (chat model). It used to cost up to five: the router, the lift, a judge for gray chunks, a judge for gray summary hits, the answer.
A follow-up costs the same two: the restating call replaces the lift.
Both preparation calls run on a thread beside local retrieval and are waited for `config.CHAT_PREP_WAIT_S` at most (8s, `ENQ_CHAT_PREP_WAIT`, `chats._background`); past that, retrieval goes on without the claims, a short follow-up (under `SHORT_FOLLOW_UP_WORDS`) is searched together with the question before it, and the call finishes unattended and caches what it can.
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
The baseline is stored at `~/Library/Application Support/Enqueue/evals/real-baseline.json`; `enq eval-real` exits non-zero when a query that passed there fails now, and `--update-baseline` replaces it.
Run it on the laptop before and after any retrieval change (model swap, re-rank, ranking signals).
Its blind spot: a person only opens what search already showed, so it measures ranking among surfaced results, not recall of notes search never surfaced; the cross-domain eval covers that.

### Scope dial for chat

| Scope | Retrieval |
| --- | --- |
| One artifact | none when it fits the passage budget; searched inside when it does not. |
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

**Browser fallback (`preview_browser`, default on).**
Some sites refuse any non-browser client (Medium's bot wall answers 403 to httpx every time, whatever the user agent).
A refusal (401/403), or a page with no title and no description until its scripts run, is opened once more in the Mac's own WebKit (`preview._read_browser` -> `webkit_page.read`), and its HTML goes through the same `parse` and `_extract_body`.
The reader is its own short-lived process (`python -m enqueue.webkit_page <url> <timeout>`, one JSON line back): WebKit needs a main-thread run loop the engine does not have, and a page that hangs or crashes WebKit takes only that process, which `read` kills at the deadline. At most two run at once (`_BROWSERS`).
It keeps the plain fetch's lines: every navigation (redirects and frames too) is checked with `netguard.is_public`, the same check `_refuse_private` uses; a content rule list blocks the page's own requests to literal private addresses (one rule per range: WebKit's `url-filter` has no `|`, and a rule list that fails to compile fails the read); a non-persistent data store keeps no cookies; nothing plays; the user agent is WebKit's own, since a real browser loading a page is not a disguise and faking one is.
A page that still refuses a real browser stays refused ("even in a browser"). A computer that is not a Mac has no preview browser and is not offered the switch (`features.preview_browser`).

**A link's title before, or without, a preview (`capture.title_from_url`).**
A link is titled from its address until its page says its own name, and for good when the publisher refuses the fetch (Medium does).
The title is the article's words out of the last path segment, first letter capitalised, with the publisher's id dropped (a trailing 8 to 16 hex characters holding a digit, Medium's `-0b96b649edf4`) and without the site name, which the card already shows.
It used to be "the end of prestige ... 0b96b649edf4 - medium.com", which read as an address.
An address that names nothing (a bare domain, a one-word segment, a document id) is titled by its site.
`is_placeholder_title` knows every form a placeholder has had (the clean one, the old "slug - host", the bare address the phone saves), which is what lets a preview replace it; a title the page gave or the person set (`title_explicit`) is never touched.
`retitle_placeholders()` runs at engine startup and gives links still carrying an old placeholder the clean one, without touching `updated_at` (the wall keeps its order); the phone gets it because it applies a snapshot with an equal key.
The phone still titles a link it captures by the bare address until the desktop has seen it.

**A shared link's name is its title.**
A capture of exactly "Title" on one line and the address alone on the next (what a share sheet or "copy link" hands over) saves the line as the link's title, not as a note (`capture.html` `splitLink`, `sync.rs` `shared_link_title` for the phone, `LinkCreate.title`).
Before this, the page name landed as the link's first note and read like something the person wrote.

---

## Backups (Proton Drive)

`backup.py`, decided 2026-09-30, encrypted 2026-10-14. The live library stays at `~/Library/Application Support/Enqueue`; the cloud drive only ever holds backups.
A live SQLite file in a File Provider folder is unsafe: WAL is three files a sync client can upload mid-write (a torn copy), the drive can evict a quiet file to a cloud-only placeholder under the engine, and the ~400 MB file (mostly the search index) would re-upload on every write.

- `backup_dir` setting (empty = off; Settings > Library offers the detected `~/Library/CloudStorage/ProtonDrive-*` folder). Backups go in `<backup_dir>/Enqueue Backup/`.
- **Zero-knowledge.** Every file in the folder is encrypted with the `backup` key derived from the library key (libkey.py), so the drive, and whoever runs it, holds nothing readable (`test_nothing_in_the_drive_can_be_read` reads every byte for a note's words, an original file, a setting, a file name and the SQLite header). The format is libsodium's secretstream (XChaCha20-Poly1305, 1 MiB chunks, the last tagged final, so a cut-short file is refused) behind a 37-byte header: `ENQB`, a format byte, the 8-byte key id, the stream header. `manifest.json` stays readable: the format, the key id, the date and size of the latest.
- A run: `VACUUM INTO` a plain copy in `DATA_DIR/.backup-work/` (never in the drive), empty every index table from `store_sqlite._DDL` and delete `index_meta.embed_version` in it, `VACUUM`, `PRAGMA integrity_check`, seal it into `library/enqueue-YYYY-MM-DD.db.enc` through a partial file, then open the sealed file again and quick-check that before it counts. Originals go into `files/`, each sealed with its name as the first line and named by HMAC of its name under the `backup-names` key (only new ones); `settings.json` and `keyring.json` become `.enc`. The first sealed run removes what older versions left in the clear (`library/*.db`, `blobs/`, the plain json files), only after its own copy checked out. The API key stays in the Keychain, never backed up. Measured on a 410 MB library (332 items): a 5.7 MB copy in 2.4 s; a restore rebuilt the index in ~20 min, during which browsing works and search waits.
- When: the scheduler thread checks hourly (first after 5 min) and runs once a day if the change stamp (counts + latest timestamps of what a person writes) moved; a clean engine shutdown runs one more; choosing a folder runs the first at once; `POST /backup` / `enq backup` on demand. Keeps 7 daily + the newest of 4 earlier weeks.
- **The recovery kit** is the only way into a backup on a Mac without the key: Enqueue keeps no other copy and cannot reset it. Settings > Library > Backup shows it on request (`POST /backup/kit`) with an amber dot until "I saved it", and the setup step stays a warning ("Save your recovery kit") until then. Restoring with a kit adopts that key as the new Mac's library key, so its next backups open with the same kit.
- `restore()` (`enq restore`): refuses while the engine answers on 127.0.0.1:8787, opens the backup (this Mac's key, else `--kit` or a prompt; `Locked` when neither, "a different library" when the kit's key id does not match), quick-checks the file, moves the live `enqueue.db` (+ wal/shm) to `before-restore-<time>/` (never deleted), copies the backup in, fills missing blobs, and fills `settings.json`/`keyring.json` only when absent (a new Mac). The next start migrates and, with no recorded embed version, rebuilds the index (index/bootstrap.py).
- Events: `backup` (with the record) and `backup.failed` in the Activity log.
- Settings > Library > Backup (`renderBackupSection` in `static/js/settings.js`) leads with when the last copy was made (a dot: green, amber when none or older than three days, pulsing while one runs) and Back up now; then what is kept (a bar per copy, weekly ones paler), where, and how to restore. Any folder works; a detected Proton Drive folder is only a shortcut. The folder is chosen with the Mac's own picker (`tauri-plugin-dialog`, registered on the desktop shell and allowed for the home window as `dialog:allow-open`); a plain browser gets a text field instead.

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
| `tests/test_summarize_once.py` | Two desktops: the second takes every model-written layer and makes no model call; a pulled note waits for its author; a phone's note is summarized by one desktop; a phone or vaulted snapshot never leaves the wrong layers behind. |
| `tests/test_backup.py` | Backups: copy without the index, nothing readable in the folder, the plain leftovers removed, a cut-short or changed file refused, change stamp, retention, no partial files, restore sets the library aside, a new Mac opens one with the recovery kit. |
| `tests/test_md_roundtrip.py` + `tests/js/md_roundtrip.js` | md() and htmlToMd() round-trip a note unchanged (run under node). |

### Conventions

- `store` fixture: monkeypatches `config.DATA_DIR`, `config.DB_PATH`, `config.BLOB_DIR` to tmp_path, then calls `db.migrate()`.
- `quiet_queue` fixture: replaces `ingest_queue.submit` with a list append, so ingest work is synchronous.
- Tests assert on validators rejecting bad output, not on happy paths.
- `FakeProvider` in `test_chats.py` takes scripted replies by response_model name and can raise exceptions.
- `test_providers.py` runs a real HTTP server on 127.0.0.1 to test malformed responses end-to-end.

---

## Build notes

Setting up and running are under [Start here](#start-here). What else is worth knowing:

- `bin/launch desktop` rebuilds the shell with `cargo build` (a compile error stops it rather than launching a stale binary), kills the shell and engine, writes the repo path to the data folder's `repo`, starts the shell and waits for `/health`.
- `bin/launch mobile` refuses an emulator on purpose and never runs `cargo tauri android dev` (that watch loop never exits and holds the Gradle lock); it builds once, installs, launches and exits.
- The shell finds the engine repo through `ENQUEUE_REPO`, else the data folder's `repo` file, else the parent of the current directory.

### The Mac app bundle

`bin/release desktop` runs `bin/bundle-engine`, then `cargo tauri build --config tauri.release.conf.json`, which copies `desktop/engine` into `Enqueue.app/Contents/Resources/engine`.
The engine is a relocatable CPython 3.12 (python-build-standalone, the one uv manages) plus a `site/` folder; the shell finds it next to its own executable and runs `python3.12 -m enqueue serve` with `PYTHONPATH` set to it (`bundled_engine_command` in `desktop/src/lib.rs`), so the app needs no repo, no uv and no system Python. Without a bundled engine (a dev build) the shell runs `uv run enq serve` from the repo as before.
- **Exactly the locked versions.** `site/` is installed from `uv export --frozen --no-dev` (uv.lock), then the project itself with `--no-deps`; resolving fresh would ship whatever was newest that day.
- **Only what the engine imports.** `bin/bundle-engine` removes pyobjc-core's test suite, CPython's Tk, IDLE, ensurepip, headers and pip, and babel's CLDR locales except English (courlan imports babel, but only a language filter reads a locale, and Enqueue never sets one): 401 MB down to 325 MB on 2026-10-27. It fails if Playwright, crawl4ai or the relay's packages (`hosted` extra: boto3, psycopg, pyjwt) come back. SQLAlchemy stays: Alembic needs it for the startup migration.
- **The preview browser is the system's.** Link previews open refused pages in the Mac's own WebKit through `pyobjc-framework-WebKit` (about 29 MB); crawl4ai and its Chromium (over half the bundle, 814 MB against 356) are gone. Playwright is dev-only (`bin/screenshots`), and `bin/bundle-engine` fails if it leaks in.
- **First launch** downloads the embedding model once (about 200 MB from Hugging Face) into the data folder; search says "Updating your search index" until it is ready.
- **Signing.** With `APPLE_SIGNING_IDENTITY="Developer ID Application: Sudohnim, LLC (572NMYL3ZG)"` every Mach-O in the engine is signed inside-out with the hardened runtime and `desktop/Entitlements.plist` (library validation off, dyld variables, JIT), then Tauri signs the app.
- **Notarizing.** Once per Mac, `xcrun notarytool store-credentials enqueue-notary --apple-id <you> --team-id 572NMYL3ZG` (it asks for an app-specific password from appleid.apple.com, which stays in the keychain); then `NOTARY_PROFILE=enqueue-notary bin/release desktop` submits the `.dmg`, waits, staples it and checks it with `spctl`.

### The Mac app updates itself

A shipped app (one with a bundled engine) asks a feed for a newer version a minute after it starts and every six hours (`watch_for_updates` in `desktop/src/lib.rs`, `tauri-plugin-updater`).
An update whose signature checks out against the public key in `tauri.conf.json` (`plugins.updater.pubkey`) is downloaded and kept in memory (`PendingUpdate`), and the page shows a card at the bottom right, the way Claude's desktop app does: **Update now** (`app_restart`: put it in place, stop the engine and wait for it so the new shell does not attach to the old engine on its port, restart) or **Update on close**, which only puts the card away. Either way it is put in place when the app quits (`install_pending` on `RunEvent::Exit`), so an ignored card still updates (`js/update.js`, `window.__enqUpdateReady`, `update_ready`).
**The feed** is `latest.json` on a GitHub release tagged `mac-updates` (prerelease, never "latest", so an Android release cannot take its place); its `url` points at `Enqueue.app.tar.gz` on the versioned release `mac-v<version>`, which also carries the `.dmg` people download.
**The key.** The private half is `~/.tauri/enqueue-updater.key` (made 2026-10-26 with `cargo tauri signer generate`), its password in the Keychain as `enqueue-updater-key-password`; `bin/release desktop` reads both (`TAURI_UPDATER_KEY_FILE` and `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` override). Lose it and installed copies can never update again: a new key means a new public key in the app, which only a manual download brings. Keep a copy in a password manager.
**A release** (`bin/deploy desktop`): `bin/release desktop` builds and signs, notarizes and staples the `.dmg`, staples the `.app` (notarizing the `.dmg` registered it), makes the update bundle again from the stapled app and signs it, and writes `latest.json` (`write_update_feed`); after a yes, `fastlane mac publish` creates `mac-v<version>` with the `.dmg` and bundle and replaces `latest.json` on `mac-updates`. Bump the version in `pyproject.toml`, `desktop/Cargo.toml` and `desktop/tauri.conf.json` first: an app updates only to a higher version.
Only Apple silicon is built (`darwin-aarch64`): the bundled Python is arm64.
Notarizing needs the `enqueue-notary` profile once per Mac (`xcrun notarytool store-credentials enqueue-notary --apple-id <you> --team-id 572NMYL3ZG`).

### The Android release build

`bin/release android` makes the signed release `.apk` and `.aab` (signed with `desktop/gen/android/key.properties` + `release.keystore`, both gitignored). A release build differs from the debug one every other script makes in three ways, each of which broke it once (2026-10-17):
- **OpenSSL archives with `llvm-ar`/`llvm-ranlib`.** SQLCipher's vendored OpenSSL looks for `aarch64-linux-android-ranlib`, which NDK r23+ no longer ships; `bin/android-env` (sourced by `bin/launch` and `bin/release`, mirrored in `bin/verify`) exports `AR_`/`RANLIB_<triple>` pointing at the NDK's llvm tools. A clean debug build needs it too: until 2026-10-21 only `bin/release` set it, and a warm cache hid that every clean debug build failed.
- **R8 keeps the app's own classes** (`proguard-rules.pro`): Rust calls `MainActivity.storeKey`, `getCurrentActivity` and the sync service by name over JNI, and the page calls the `@JavascriptInterface` bridge, so a shrunk build renamed them away and the app died at launch with "store key: Java exception was thrown". Verify a release build by installing it and opening it, not by its build passing.
- **Native code aligned to 16 KB pages** (`desktop/.cargo/config.toml`, `-z max-page-size=16384` for the Android targets): Play refuses a production release whose `.so` loads at 4 KB ("Your app does not support 16 KB memory page sizes"), the NDK's default; internal testing let 3003 through, production did not (2026-10-21). Check with `llvm-readelf -lW` on the `.so` inside the `.aab`: every LOAD line must end `0x4000`.
- **No typedef-annotation extraction** for the plugin modules (`build.gradle.kts`, `allprojects`): it only matters for publishing an AAR, and the lint tooling it downloads was cut off mid-download by Google's CDN on every attempt.
**Version codes.** Tauri derives the versionCode from `tauri.conf.json`'s version (major * 1000000 + minor * 1000 + patch, so 0.3.0 is 3000) and writes it to `gen/android/app/tauri.properties`, which is gitignored and rewritten on every build.
Play refuses a code it has seen, so `bin/release android` takes `ANDROID_VERSION_CODE` and merges it into the Tauri config for that build only (`--config '{"bundle":{"android":{"versionCode":N}}}'`); nothing in the repo changes per release.
The fastlane Android lanes pick N as one more than the highest of every code Play lists (bundles, APKs, every track) and the code in `tauri.properties` (the last one this checkout attempted), after Dequeue's `next_android_version_code`.
The local half matters because Play reserves a code the moment a bundle is uploaded, even when the upload fails, and never lists it.
The lane refuses to upload when the built code is not the one it asked for, and sends the R8 map (`outputs/mapping/universalRelease/mapping.txt`) with the bundle so Play can read crashes.
A plain `bin/release android` without the variable still builds with the derived code, which Play will refuse once that code is taken.

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

**The verification split** (why "I can't run the device" is never a reason to stop): implementing code, `cargo check`, and `bin/verify` are headless and need no hardware - do all of it. The runtime check on a physical phone or the desktop window is done by whoever holds the device: the agent implements, gets `bin/verify` green, says plainly what is verified headlessly and what still needs a device, and the person with the device runs that pass. Never stop a turn merely because the device runtime is out of reach - there is almost always headless implementation and gate work to finish first.

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
- **App state (debug build):** the phone's `library.db` is SQLCipher and `sync_config.sealed` is sealed, so neither reads off the device any more. Ask the running app instead: `bin/cdp-eval "await window.__TAURI__.core.invoke('mobile_status')"`, or `mobile_list` to count applied artifacts. This is how you tell a decrypt/apply failure (cursor advances, 0 rows) from a render bug.
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
`queue.prune_index` runs each time the ingest queue drains (the `Worker` `on_idle` hook) and once at engine startup: it deletes chunks of trashed or vaulted artifacts, removes any entry whose row is gone or belongs to an artifact that is not live (`store.prune_orphans()`; regenerated facets, entities and sections take new ids, and a trashed or vaulted artifact keeps its summary rows), and indexes any row with no entry (`store.index_missing()`, e.g. after an interrupted rebuild).
`enq index` rebuilds every layer from the tables, live artifacts only: the facet, entity and section rebuilds once had no such filter, and one library's summary index was 57% rows of trashed artifacts, which took a third to a half of every search's facet shortlist.
`enq doctor` compares the chunk index with `indexable_chunk_count` (chunks of live artifacts), not every chunk.
A full rebuild and the prune run on the ingest worker's thread between two artifacts (`Worker.run_exclusive`, ahead of anything queued): run beside ingest they fought it for SQLite's single writer, failed with "database is locked", and left the index half-built with search blocked.

### A note being written keeps a slower clock

The editor saves 1.5 seconds after the typing pauses, on blur and on Cmd+S, and every save used to do two expensive things at once.

**Drafts (`notes._append_version`, `config.DRAFT_EVERY_S`, 300s).**
A draft per save made 149 near-identical drafts of one note, and the whole list rides every sync snapshot.
Now the newest draft follows the writing (rewritten in place, `created_at` moved) until `DRAFT_EVERY_S` has passed since the draft before it; then it stands and a new one starts.
So an accidental deletion is never more than five minutes from a draft that still has the text, and a note written in one sitting keeps its start, one draft per five minutes, and its end.
`MAX(created_at)` of a note's drafts is still its body version (what facets, entities and sections are stamped with), and it still moves on every save.
The phone follows the same clock (`keep_draft` / `DRAFT_EVERY_S` in `desktop/src/sync.rs`, called by `update_note_body`), and like the desktop it keeps the NEW body as the draft; it used to keep the body before the edit, one per save.
A note first written on the phone has no draft until its first edit, so that edit also keeps the text as it was (stamped with the note's `created_at`).
Keep the two rules in step: drafts replace each other wholesale when a snapshot is applied, so whichever device wrote last decides the list.

**The model (`queue._wait_for_quiet`, `config.SUMMARY_QUIET_S`, 300s).**
Every save comes through ingest, and each pause re-summarized the note: 56 model calls in ten minutes of writing one note, which is what ran the weekly limit dry.
Chunking and indexing still happen at every save, so the words are searchable at once.
The model steps (sections, facets, entities, contexts) are skipped while the note's newest draft is younger than `SUMMARY_QUIET_S`, and the artifact is owed a run at the moment it will have been quiet that long: a `facet_retry` row whose `last_error` is `queue.WAITING`, which the sweeper submits when due.
An edit in the meantime comes back through ingest and moves the row.
Only notes wait; a capture has no body being typed. "Regenerate" (`facets.force`) never waits.
`GET /artifacts/{id}` reports `summary_waiting`, the Details panel says so, and `enq doctor` counts these under `summaries.waiting`, apart from `retrying`.
Tests run with both clocks at 0 (`conftest._every_save_counts`); `tests/test_writing_pace.py` turns them on.

### Two desktops read an item with the model once (2026-10-15)

A person with two Macs on one library (work and personal) paid for every item twice: only the summary lines rode the snapshot, so the second Mac wrote its own entities, section summaries and passage contexts for everything it pulled, and, on a different ingest model, rewrote the summary lines at every startup because another model's lines counted as stale.
Three rules end it.

**Every model-written layer rides the snapshot** (`sync/snapshot.py` `derived_layers` / `_apply_derived_layers`): `entities`, `sections`, `section_cache` (the per-section summaries `source._map_reduce` looks up, keyed by the hash of the section's text), `chunk_contexts` (keyed by the hash of the passage's text, since chunk ids differ per device; kept in `derived_values` scope `chunk_context`, where `chunk.chunk_artifact` finds them when it cuts the passages) and `related_verdicts`.
A layer is replaced only when the snapshot carries it (a phone's snapshot carries none of these keys), except that a vaulted snapshot clears them all. The model's work is pushed once, at the end of an ingest run that wrote anything (`queue._process`), and after each judge call (`related.judge_next`).

**A layer counts as current by the body it was written from, not the model** (`facets.is_current`, `entities.is_current`, `hit_is_stale`, `context.generate_for_artifact`, the section cache, `related._verdict_read`).
Changing the ingest model is the deliberate rewrite: `queue.refresh_on_model_change()` forces every item whose lines another model wrote through every model step (`_redo_in_run`), and the other devices take the result.

**A pulled item waits for the device that wrote it.** A pull now sends what it applied through ingest on the background lane (`client._ingest_pulled`: entities and sections indexed, related links derived, passages cut and indexed); before, a pulled item was indexed only at the next startup, and never when its summary already looked current.
An item whose summary is not current yet holds its model steps (`queue.await_peer`, a `facet_retry` row with `last_error` = `queue.AWAITING`): `PEER_SUMMARY_WAIT_S` plus a per-device share of it when a desktop wrote it, only a per-device share of `PEER_PHONE_WAIT_S` when a phone did (a phone's snapshot has no `entities` key), so the desktops take turns.
The wait ends the moment the summary arrives (`_awaiting_peer` checks `is_current`); if it never does, this device summarizes when the row comes due.

### Enqueue sync: signing in gives each device a pass of its own (2026-10-19)

Settings > Sync offers Enqueue sync first (sign in with Google or Apple; the relay is ours) and a relay of your own under "Use a relay of your own" (address, then its password, as before).
Signing in needs the library's key first: a Mac without one makes it and shows the recovery phrase, then opens the sign-in (`startAccountSignIn` in `static/js/settings.js`).
The sign-in runs in the system browser (`open_external`) and comes back to the engine, not the page; the page polls `GET /account` until `sign_in.state` is `done` or `failed`. Both return addresses check the `state` the engine made (`account.begin`, ten minutes, one use), so a page that sends the browser there on its own finishes nothing.
What the sync client sends as its relay password is then a device token (`enqd_...`), not a shared secret: this Mac's own, a fresh one in every phone linking code (`desktop_link_code` asks `POST /account/device-token`, so it is async and off the main thread), and a fresh one for a computer joining (`pairing.create_offer`). Each shows under Devices and can be removed alone; signing out cancels this Mac's and clears its sync settings; deleting the account ends them all and the relay drops the library. Nothing changes on the phone: it reads `relay_secret` from the code as always.
Showing the code twice makes two phone tokens; one never scanned stays "not synced yet" under Devices until removed.
A Mac already on a relay of its own switches with the same sign-in ("Switch to Enqueue sync" on the configured Sync tab): `account._move_library` stores the new device token, forgets the pull cursor (the account's library counts from its own start), restarts the sync worker (`worker.restart`, which retires the old loops by generation, since the change stream can sit in a read on the old relay), and pushes everything once (`client.push_everything`: artifacts, views, conversations, settings, the vault's wrap; the keyring goes up as the password is stored), logged as `sync.moved`. The key is the same, so nothing new is written down. Settings asks to link the phone again until a phone code is made (`account_relink_phone`); the phone forgets its own cursor on every link (`mobile_link_qr`), for the same reason. The old library stays on the old relay until `enq relay-admin revoke`.
Google and Apple are set up in the `enqueue-sudohnim` Google Cloud project and Apple team 572NMYL3ZG; the relay's variables (client ids, the desktop client secret, `JWT_SECRET`, `DATABASE_URL`) are on the Railway `enqueue` service, and the Sign in with Apple key (`66CTHBC793`) is in the Keychain as `enqueue-apple-siwa-key` until the relay needs it (Apple's token revocation on account deletion).
`tests/test_account.py` runs the Mac's side against the real relay code.

### A new computer is approved from one that has the key (2026-10-21)

Signing in proves who someone is; it never carries the library's key (see [Encryption and keys](#encryption-and-keys)).
So what a Mac does after signing in depends on the account's library (`account._adopt`, which reads the relay's `lib/keyring.enc` with the new device token):

- **The library has a key and this Mac has none:** it asks to join (`sync/join.py`). It makes a Curve25519 key pair, posts the public half (`POST /account/joins`, device token) and shows a six-digit code made from it (`crypto.join_code`). Every signed-in Mac polls `GET /account/joins` every 10 seconds while its window is up (`watchApprovals` in `js/approve.js`) and shows "<name> wants to join your library" with the same code, worked out on that Mac from the public key the relay lists. Approve seals the key to that public key (`crypto.seal_to`, libsodium's sealed box) and posts the sealed bytes; the asker collects them once (`GET /account/joins/{id}`), takes the keyring from the relay and starts syncing. The relay holds a public key and ciphertext only; a relay that swapped in its own key would show a different code, which is why the person compares them. An ask lasts ten minutes (`JOIN_TTL_S`); the private half lives in the engine's memory only, so a restart means asking again.
- **The account has no library key yet:** sign-in ends in `needs_key`; the page makes the key and shows the recovery phrase, then `POST /account/finish` turns sync on.
- **This Mac has a key for a different library:** refused, and the device the sign-in made is cancelled. Making the key BEFORE signing in (the flow until today) gave a second Mac a second key that could not read the first one's library, and its `push_keyring` overwrote the account's keyring.

The pairing code (`sync/pairing.py`, a typed phrase) stays for a relay of your own, where there is no account.
**The phone takes part (2026-10-26).** It can sign in with Google instead of scanning (`SignIn.kt`, Credential Manager, an id token for the Web client; `mobile_sign_in` trades it at `/auth/google`, makes a phone device, and asks to join), shows the code and waits (`mobile_join_status`, every 3 seconds), and is then linked exactly as a QR link leaves it. A linked phone approves other devices too: it looks for asks when it comes to the front and every 15 seconds (`mobile_joins`, `mobile_join_decide`). The sealed box is `crypto_box` in `sync.rs` (`join_keypair`, `join_code`, `approval_for`, `dek_from_approval`), pinned against PyNaCl by a test vector. An account with no library key yet tells the phone to set the Mac up first.
On iOS the same button is Sign in with Apple (`apple` in the native plugin, `ASAuthorizationAppleIDProvider`; `/auth/apple` takes the identity token with `APPLE_BUNDLE_ID` as its audience; the entitlement is in `Enqueue_iOS.entitlements` and `project.yml`).
Google on Android needs one OAuth Android client per signing certificate in `enqueue-sudohnim`: debug, upload and Play's app signing key are each registered (2026-10-27).
The phone can delete the account (App Store rule 5.1.1(v)): Settings > Plan, or "Delete an Enqueue account" on the setup screen. `mobile_delete_account` signs in again for a fresh token, calls `DELETE /account`, and clears the phone's library and sealed config.
Google issues the token only once the Android OAuth client (package `com.sudohnim.enqueue` and the SHA-1 of every signing certificate: debug, upload and Play's app signing key) is registered in the `enqueue-sudohnim` Google Cloud project.
The free plan's one computer still applies: a second computer is refused at `POST /account/devices` (402) before it can ask.
`tests/test_device_approval.py` runs the relay rules and the whole Mac side against the real relay code.

### A pull never steps past what it did not receive (2026-10-22)

The phone's pull (`sync_library` in `desktop/src/sync.rs`) fetches the changed objects in parallel (`fetch_snapshots_parallel`).
An object it could not fetch (no network, the relay down or busy) used to be skipped while the cursor moved past it, so that change never came again: two notes trashed on the Mac stayed on the phone for good.
Now a missed fetch counts like a failed apply and the cursor stays put until every object arrives; an object gone since the listing (404) or sealed under another key is still skipped, since asking again cannot help.
Phones on older builds pull everything once after updating (`FULL_PULL_KEY` in `sync_library`), which re-applies what is already there as no-ops and catches whatever they stepped past.
Bump `FULL_PULL_KEY` to make every phone do that again.

### One thread at a time opens or closes the library (2026-10-22)

The engine froze whole (`/health` too, 0% CPU) when one thread opened a connection to the library while another closed one under load: SQLite's file locks (`findReusableFd` on open, `unixLock` in `sqlite3WalClose` on close) each waited on the same inode mutex forever, one of them holding Python's global lock.
It showed after turning on "Try harder" for link previews, which only added load: a throwaway engine under capture and search load froze every time with the preview browser on or off, the same two stacks each time.
`db.connect` opens under a process-wide lock (`_OPEN_CLOSE`) and returns a `_Connection` whose `close()` (and finalizer) takes the same lock; with it the same load ran 16,000 rounds clean.
Every connection to the library must come from `db.connect` (it already must, for the key).
Search reads through `db.reader()`: one connection per thread, opened once through `db.connect` with sqlite-vec loaded and `query_only` set, whose `close()` keeps it open. A search used to open about seven connections, each loading the extension and setting WAL, nearly half its time. The cached connection follows `config.DB_PATH`, and `db.forget_readers()` (called after a restore or `encrypt_library` replaces the file) makes every thread open a new one.
A frozen engine's stacks: `kill -USR1 <pid>` writes every thread's Python stack to the log; `sample <pid>` shows where they wait inside SQLite.

### A Keychain that cannot answer is not a missing key (2026-10-21)

`keyring._read` tells "no such item" (`security` exits 44) from "the Keychain did not answer" (a permission prompt waiting or refused, a locked keychain, a timeout), which raises `KeychainUnavailable`.
`libkey` reads strictly (`_get(..., strict=True)`): it MAKES the library key when there is none, and a failed read used to count as none, so the next ask (the daily backup, the recovery kit, the sync wrap) stored a new key over the real one, which locks an encrypted library for good.
Other secrets still read a failed read as absent, without caching it.
The engine answers a `KeychainUnavailable` with a 503 that says to choose Always Allow (`api/app.py`), and the wall says so after eight seconds of opening instead of spinning without a word.
`tests/test_keychain_unanswered.py` pins it.

### The first-run welcome (desktop) and the phone's first screen (2026-10-20)

A fresh library opens on `js/welcome.js` (styles in `css/welcome.css`) instead of the empty wall: `home()` calls `maybeWelcome()` when the wall is empty, and it shows when the `welcome_done` setting is false and the three `GET /setup` steps are not all done.
Five skippable steps: Overview, the assistant, sync, the recovery kit, the phone; finishing or skipping sets `welcome_done` (a setting, not localStorage, so a cleared webview does not bring it back).
The Overview is a hub with two halves: the tour (`js/tour.js`, the live-demo cards (eight on the Mac), played as one card, `welcomePlayTour`, whose last button says "Set it up" and continues to the Assistant step through `Tour.open({label, then})`) and a setup list (`welcomeChecklist`), one row per step with where this Mac stands, read from `/settings`, `/setup` and `/backup`.
The `?` at the top right of the home header opens the same welcome on demand (`openWelcome`, `welcomeTriggerHtml`), each step showing where this Mac stands, with Close and Done in place of Skip; the tour has no `?` of its own on the desktop; it is played from the hub. `refreshIfStale` leaves an open welcome alone, since its sign-in round trip through the browser brings the window back into focus.
It adds no machinery: the assistant step writes `llm_backend`/`llm_model` (from `BACKEND_MODELS`) and `PUT /settings/api-key`, the sync step renders the real Sync tab into its own `#settingsTabPane` through `renderSettingsTab("sync")` (so `startAccountSignIn`, the recovery phrase, the browser sign-in and joining another computer run unchanged), the kit step uses `backupKitHtml`/`showRecoveryKit` (`recoveryKitSaved` re-renders the welcome when it is open), and the phone step uses the Sync tab's `linkShowBtn`/`toggleLinkCode` ids.
The page wears `.settings-page` so the embedded Sync tab looks as it does in Settings; the guide marks are hidden there because their plate belongs to the Settings page.
A sync flow that ends by calling `renderSettingsTab` lands back in the welcome only because the pane id is the same: keep new sync steps rendering through `renderSettingsTab(currentSettingsTab)`.
The phone's `#setup` screen in `mobile.html` is a short welcome (what Enqueue is, then "On your Mac, open Settings, Sync, and press Show the code") above the scan button; the scan flow's ids (`setup_camera`, `scan_qr_btn`, `scan_status`, `setup_no_camera`, `retry_camera`, `status`) are unchanged.

### "Reading your library" on the wall (2026-10-20)

`reading.py` (`GET /reading`) says how far the assistant is through a big read: `total`/`done` are the doctor's summary counts in one aggregate query, `state` is `reading` (the ingest queue is busy, `queue.busy()`), `retrying` (owed `facet_retry` rows, queue idle), `paused` (`providers/pause.py`, with `paused_until`), `key` (the provider refused the key) or `idle`, and `show` is true from `SHOW_FROM` (10) items left while work is owed or blocked.
A note still being typed (`queue.WAITING`) is not owed work there.
`refreshReading` in `js/home.js` draws one quiet line above the wall on every wall render and polls every 8 seconds only while it is up; once up it stays until nothing is left, so it does not blink off near the end; `teardown()` stops the poll.
The refused key is `pause.key_refused()`: `OpenAICompatibleProvider` calls `pause.note_failure` on a failed call (true for a 401 that is not OpenCode Go's unknown-model 401, `base.key_rejected`) and `pause.note_success` on one that went through; `pause.lift` (a new key or model) clears it.
It is in memory like the pause, and `/setup` reports it as the `key-refused` alert.
`tests/test_reading.py` pins both.

### Enqueue Pro: bought on the phone, kept by the relay (2026-10-20)

Dequeue's pattern: the phone sells, RevenueCat tells the relay, and every device reads the plan; the Mac sells nothing.
**Plans** are `PLANS` in `relay/accounts.py`: free is one computer, one phone and 1 GiB on Enqueue sync; Pro is five of each and 50 GiB. Bring-your-own-key AI is never part of a plan.
**What makes an account Pro** is `accounts.pro_until`: Pro while it is in the future. Only two things write it: RevenueCat's webhook (`POST /webhooks/revenuecat`, checked against `REVENUECAT_WEBHOOK_AUTH`, closed while that is unset) and the admin grant (`enq relay-admin pro <email> [--days N]`, `PUT /admin/accounts/pro`).
The webhook sets `pro_until` from the event's own expiry, whatever the event is called: a cancellation keeps Pro to the end of the paid period, a refund (a cancellation whose expiry is now) and an expiration end it, a billing problem keeps it through the grace period. Only events naming the `pro` entitlement count; an event older than the last one applied (`pro_event_at`) is ignored, since RevenueCat may deliver out of order; a TRANSFER moves the Pro time to the other account. Dequeue switched on event names and dropped Pro at a mere cancellation.
**The RevenueCat user is the Enqueue sync account id.** The phone has no session, only its device token, so it asks `GET /account/plan` with that token (`mobile_plan` in `desktop/src/lib.rs`, null on a relay of its own) and starts RevenueCat for the account (`Billing.kt`, bridged as `EnqueueAndroid.billing*`, answering through `window.__enqBillingReply`). Settings > Plan on the phone (`paintPlan`, `goPro`, `restorePro` in `mobile.html`) shows the plan and the paywall; the Mac shows it under Enqueue sync (`planRow` in `settings.js`, from `account._keep_plan`).
**Enforcement is on the relay.** A device token carries its `kind` (computer or phone). A computer past the plan is refused at `POST /account/devices` with a 402 that says what to do. A phone never is: the new one replaces the least recently used once it first syncs (`_replace_phones`, in `library_for_device`), so a code shown and never scanned cuts nobody off. Storage is the library's own quota (`storage.set_quota`), set when the plan changes; going back to free removes nothing and only refuses new writes past the limit.
RevenueCat: project "Enqueue" (`1abb2acc`), app "Enqueue (Play Store)", entitlement `pro`; the public SDK key is in `Billing.kt` (public by design). The Play service account is Dequeue's `revenuecat@sudohnim-play-billing`, which has account-wide Play Console access.
`tests/test_relay_plans.py` pins all of it.

### The assistant included with Enqueue (2026-10-20)

A Mac or phone signed in to Enqueue sync can use an assistant with no key of its own: the `enqueue` backend ("Included with Enqueue", `config.BACKENDS`), an OpenAI-compatible endpoint on the relay at `/ai/v1` (`relay/ai.py`), reached with the device's own token.
`included_ai.py` is the one list both sides read: the models, the plan each needs, whether it can read pictures, its price, and the monthly cap per plan (free $0.50, Pro $3.00 of model cost). Free: Claude Haiku 5.5, GPT-6 Luna, Gemini 3.1 Flash Lite. Pro adds Claude Sonnet 5.5, GPT-6.1 Sol, Gemini 3.8 Flash, DeepSeek V4 Pro, Qwen 3.7 Plus. Opus, Fable and GPT-6 Astra are left out on purpose: one long chat would cost more than a month of Pro.
The relay checks the device token (401), the model against the plan (403), and the month's spend against the cap (429 with a `Retry-After` to the start of next month, which the engine's usage-limit pause already obeys); then it calls OpenRouter with Enqueue's key (`OPENROUTER_API_KEY` on the Railway service), forcing `provider.data_collection: deny` and usage accounting, and adds what OpenRouter says the call cost to `ai_usage` (account, month, cost, requests, tokens). Nothing of a prompt or an answer is stored or logged. OpenRouter refusing Enqueue's own key or credit becomes a 503, so no device tells its owner their key was refused. Streaming is refused.
On the Mac, `config.llm_api_key(base_url)` returns the device token for the included endpoint and the pasted key for everything else, so the pasted key never reaches the relay and the device token never reaches a third party; `push_settings` still sends the phone only the pasted key. The phone answers with its own token (`included_ai` in `desktop/src/lib.rs`).
Settings shows the included backend first; its model pickers are dropdowns of the plan's models, Pro ones visible but not choosable on free (`includedModelsGroup` in `settings.js`). `setup.py` says when it needs a sign-in, when a chosen model needs Pro, and when a model is not one it offers. The welcome's Assistant step offers it first. Local-only items never take this path. `GET /account/plan` carries the month's use as `ai`.
`tests/test_relay_ai.py` (with a fake OpenRouter), `tests/test_included_ai.py` and `tests/test_setup.py` pin it.

### Keeping it quick and small (2026-10-20 sweep)

- **The search path, 2026-10-27** (the 70-note cross-domain library, judge stubbed): one cached read connection per thread (`db.reader()`) and rapidfuzz in the fuzzy leg took a search from a 21 ms median (28 ms mean) to about 5 ms (10 ms).
- **The embedding model, 2026-10-27.** It runs on the CPU only (CoreML measured no faster: 18 ms a query either way, 9.6 s against 10.9 s for 32 passages), with ONNX's memory arena off and batches of at most 16 (the default 256 peaked at 1.1 GB), and is let go after `ENQ_EMBED_IDLE` seconds (300) with no use; the next search loads it again in about half a second. Live memory after embedding fell from 702 to 294 MB, and to 250 MB once let go. The vectors are identical (max difference 0.0), so the index is unchanged.

- **Keychain reads are cached** (`keyring._get`, `_CACHE`): each read is a `security` subprocess (~30 ms), and the library key was read on every database connection, 15 times per search (470 of 627 ms). Hits are kept 5 minutes, misses 30 seconds; `_set`/`_clear` update the cache, so a key changed in Settings applies at once. A search went from about 0.65 s to 0.1 s; `/setup` from 350 ms to 10 ms.
- **The gray-zone judge is not waited for when it cannot make it** (`candidates._judge_wait`): a moving average of the search model's real judge calls (over 0.3 s, so cached ones do not count); when it is above `SEARCH_JUDGE_WAIT_S` the search answers at once and the judge finishes behind it. A thinking model on a busy service made every new search wait the full 2.5 s for nothing.
- **The keyword index is compacted daily** (`store.compact`, `queue.compact_index_if_due` on the backup scheduler's hourly beat, stamped `compacted_at` in `index_meta`): FTS5 keeps a deleted entry until segments merge, and every re-index added more. One library's trigram index was 128 MB over 0.8 MB of text and the file 210 MB; `optimize` on every keyword table plus a `VACUUM` when a quarter of the file is free brought it to 41 MB. Logged as `index.compacted`.
- **A page's window and document listeners end with the page.** The note formatting bar's `selectionchange`/`resize` listeners take an `AbortController` signal that `teardown()` aborts (`stopEdbars`); they used to remove themselves only on their next event, so each note opened kept its editor alive. To check: wrap `EventTarget.prototype.addEventListener` for `window`/`document` in the page, cycle the screens, and compare counts per event type.
- **The chat panel is not a page**: `teardown()` leaves the open conversation and its poller alone while the panel is open (`eyeOpen`); a wall refresh used to stop the poller and leave the panel on "Loading..." until the person navigated away.
- **The relay's in-memory maps are bounded**: the sign-in and included-AI rate limiters drop idle entries past 1024 keys, and the device-token cache keeps only tokens that open a library (refusals were cached, so made-up tokens grew it without end).

### The AI summary can be switched off for one artifact

The Summary section of the Details panel carries a switch (`setSummary` in `js/artifact.js`, `PUT /artifacts/{id}/summary`, `facets.set_summary`), for a scratch pad or a log that needs no reading.
Off is a `facet_skips` row with reason `off`, so everything that already honours a skip does (the facet and entity steps, the backfill, "Rebuild concepts", the doctor's counts), and `queue._process` also holds back sections and chunk contexts: no model call is made for the artifact at all.
Switching off removes what the model wrote (machine summary lines, entities, section summaries), because it would go stale at the next edit and then sit in the panel without counting in search.
Lines the person wrote (`edited`) stay and are never stale, so "off, plus one line of my own" is how to keep a log findable by what it is.
It is the person's decision: `apply_eligibility_gate` keeps `off` rows, `regenerate` refuses, and only the switch turns it back on (which sends the artifact through ingest).
An artifact held out for a credential (`text_only`) shows no switch.
The switch is desktop-only and does not sync; the phone never generates summaries.
`tests/test_summary_switch.py` pins it.

### Adding a tag offers the tags already in use

The "Add tag" field in the Details panel drops a list under it (`mountTagSuggest` in `js/artifact.js`, `.tagsuggest` in `css/details.css`): every tag from `GET /tags`, most used first, without the ones the artifact already carries, at most 8.
Typing narrows it to names starting with what was typed, then names containing it.
Arrow keys light a row; Enter adds the lit row, or what was typed when none is lit, so a new tag is still a word and Enter.
After an add the field keeps the focus for the next tag.

### A retry run settles its row, and unchanged chunks are kept

`queue.process` ends every run with the artifact's `facet_retry` row either deleted (no step owed, no newer copy queued) or due in the future (`_settle_retry`, in a `finally`, so a run that raised is covered too).
A row left due is queued again by every 30s sweep.
That happened for a week-limit leftover on an 81-chunk link (2026-10-09): its run took longer than one sweep, the sweeper saw a due row and an empty queue (the worker had already taken the item, and `_pending` from another thread counts queued copies only), and queued a second copy.
The newer copy made the running one skip every model step and leave the row alone, and the next sweep did the same to that copy: one full re-chunk and re-embed a minute, 887 "81 chunks, 0 facets" rows, the note out of search for part of each minute.
So the sweeper also skips the artifact being processed (`_in_flight`, set for the length of `process`), and a run that cannot settle the row itself pushes a due one out by 30s without counting an attempt (`_defer_due_retry`).
Separately, a run whose chunks would come out exactly as stored (`chunk.plan` equals `chunk.stored`) and are indexed as they would be written now (`store.chunks_indexed`: a vector and a trigram row each, and the keyword row holding today's title, context and text) keeps them: no drop, no new chunk ids, no embedding.
A retry that only owes a model step, a sync re-apply and a reprocess of unchanged text now cost a comparison, and such a run writes no `ingest` Activity row unless a step wrote something.
A body, annotation, title or context change still re-chunks or re-indexes as before.

### A link whose page has no article is fetched once

`preview.needs_fetch` lets an old link heal itself: a preview that succeeded but kept no article body is fetched again on its next pass through ingest.
A page can be fetched perfectly and still have no article in it (an Instagram post, an app shell), and such a link used to count as needing a fetch forever.
Since `fetch` re-queues the artifact and ingest fetches whatever needs it, one such link fetched its page, re-ingested and re-pushed itself to the relay every second or two for as long as the engine ran (353 times in ten minutes), which also startled the phone's eye at every pull.
`link_previews.body_tried` records a fetch that found no body, so the heal is tried once; "Try again" still forces a fetch.
Anything that re-queues an artifact from inside ingest needs a condition that ingest itself makes false.

### The iOS app

The same Tauri mobile shell and the same `mobile.html` as Android, built for iOS: `bin/setup --ios` readies the toolchain, `bin/launch simulator` builds, installs and opens it in the iOS Simulator, `bin/launch ios` does the same on a plugged-in iPhone (written, not yet run on a device).
The Xcode project is `desktop/gen/apple` (from `cargo tauri ios init`; its own `.gitignore` drops `build/` and `Externals/`); the signing team is `bundle.iOS.developmentTeam` in `tauri.conf.json` (Sudohnim, LLC), the minimum is iOS 16.
What it took, each of which breaks the build or the screen if undone:

- **`desktop/vendor/swift-rs` is a patched copy** (`[patch.crates-io]` in `desktop/Cargo.toml`). Xcode 27 made the Swift Build engine SwiftPM's default; it prelinks each static library into one object, which turns Tauri's `@_cdecl` entry points (`_register_plugin`, `_init_plugin_*`, `_on_webview_created`) into local symbols, and the app fails to link with "Undefined symbols". The patch is one argument, `--build-system native`, under Xcode 27. Drop the copy when swift-rs or Tauri handles it. swift-rs below 1.0.9 does not build under Xcode 27 at all.
- **Tauri refuses to build without the simulator runtime matching the SDK** ("Xcode Simulator SDK 27.0 is not installed"): `xcodebuild -downloadPlatform iOS`.
- **`jni` and `ndk-context` are Android-only dependencies.** Anything new that touches JNI must be `#[cfg(target_os = "android")]`, not `#[cfg(mobile)]`.
- **The web view must not inset the page.** WKWebView insets its content by the safe area on its own, which left a black band under the page and made `env(safe-area-inset-*)` read 0. The mobile `setup` sets the scroll view's `contentInsetAdjustmentBehavior` to never and has the web view recompute its insets (`objc2`, iOS only); the page then pads itself as it does on Android.
- **`cargo tauri ios build` fails with "Directory not empty"** when the last build's `gen/apple/build/<arch>/Enqueue.app` is still there; `bin/launch` removes it first.
- `Info.plist` carries `NSCameraUsageDescription` (the QR scanner crashes on a device without it); it is also in `project.yml`, which regenerates the plist. The icons in `Assets.xcassets` are cut from `assets/logo.png` (full bleed, no alpha) with `cargo tauri icon`.

- **iOS 27 needs a scene life cycle.** `Info.plist` declares `UIApplicationSceneManifest` with `TaoSceneDelegate`, and `UIApplicationSupportsMultipleScenes` must be true: tao puts its window on a scene only then, and with false the screen stays black.
- **A `<header>` rule in `mobile.html` must not reach the Details panel.** The reader toolbar's rule pulls a header up by the status bar's height; it is written `header:not(:where(.dpanel-top))`, because `.dpanel-top` is a `<header>` too (its title went under the status bar), and `:where` keeps the rule weaker than `.lib-hero`.

**The native plugin** (`desktop/plugins/tauri-plugin-native`, Swift) is the iOS twin of the `EnqueueAndroid` bridge; the page reaches it as `plugin:native|<command>` wherever it would call the bridge (`iosLock` in `mobile.html`):

- **App lock** (`status`, `applock`): a native cover over the window, up before the page paints, lifted by Face ID or the passcode; it asks again after a minute away and covers the app switcher's snapshot. A phone with no passcode left switches it off. The cover's raven is `RavenMark` in `Assets.xcassets`.
- **Vault Face ID** (`create`, `read`, `clear`): 32 random bytes in a Keychain item only the current set of Face IDs can read (`biometryCurrentSet`); a new enrollment makes it unreadable, answered as "invalidated". The answers have Biometrics.kt's shapes, and `status` adds `biometry` ("Face ID", "Touch ID"), which the page uses in place of "fingerprint".
- **Quick capture** (`quick`): a Home Screen action (`UIApplicationShortcutItems`) that opens the writing page. UIKit hands it to the scene delegate, which tao owns, so `QuickAction` wraps `UISceneConfiguration`'s delegate class setter and puts in a subclass that also reads it. That must happen before the scene connects: Rust calls `enqueue_native_early` at the start of `run()`.
- **Sync while closed**: a `BGAppRefreshTask` (`com.sudohnim.enqueue.sync`, registered in `enqueue_native_early`, scheduled when the app leaves the screen) calls `enqueue_background_sync` in `lib.rs`, which pushes the outbox and pulls (`sync_now`). iOS decides when it runs; the Simulator never runs it.
- **Back**: a swipe in from the left edge calls `window.__enqBack()`, as Android's Back does.
- `NSFaceIDUsageDescription`, `BGTaskSchedulerPermittedIdentifiers` and `UIBackgroundModes: fetch` are in `Info.plist` and `project.yml`.

**Billing** is `desktop/plugins/tauri-plugin-billing` (RevenueCat over StoreKit, `plugin:billing|start|status|offerings|purchase|restore`, in Billing.kt's shapes); App Store Connect has the subscription `enqueue_pro_monthly` in the group "Enqueue Pro", linked in RevenueCat to the entitlement `pro`. The sample library's Settings shows the paywall too, so App Review can reach it.
**Releasing**: `bundle exec fastlane ios beta` builds, signs and uploads to TestFlight (the build number is kept in `fastlane/.ios-build-number`, since App Store Connect refuses one it has seen); `fastlane ios metadata` uploads the listing from `fastlane/metadata/ios` and the screenshots from `fastlane/screenshots/ios`. The review contact files are gitignored.
**The gate**: `bin/verify` builds the simulator app when Swift, plist or plugin files change and runs `cargo check` for the iOS target on other Rust changes (`check_ios_compile`); CI's `ios` job runs `bin/verify --ios` on macOS.

Not there yet: linking, vault Face ID and the background sync are untested on a real iPhone (the simulator has no camera and never runs background tasks).
At rest it matches Android: the library copy is SQLCipher (`bundled-sqlcipher-vendored-openssl` in the iOS table of `desktop/Cargo.toml`), and the store key that keys it and seals the secrets and the file cache is a Keychain item (`security-framework`, service `com.sudohnim.enqueue.store`, readable after first unlock on this device only, so never in iCloud Keychain or a restored backup; `store_key` in `lib.rs`). A plain library, plain secret files and a store-key file from an earlier iOS build are converted the first time the library opens.
There is no CDP on iOS: verify by screenshot (`xcrun simctl io booted screenshot`), or Safari's Web Inspector by hand.

### Settings look like the home page and talk like a person (2026-10-15)

One centred column (`.settings-page`, the last block of `css/settings.css`): the raven against the title, where things stand as one quiet line under it (`renderSetup` in `settings_guide.js` draws the steps as `.setup-line`), the home page's pill tabs, and settings as rows on the ground: a label and one plain sentence on the left, the control on the right (a `.field` is a two-column grid there), a hairline between rows. The backup status is the one tile.
A setting that needs a look shows only on its own tab (`#settingsNotes`, alerts filtered by `tab`).
Each tab ends with "More options" (`moreOptions` in `settings.js`, a `details.more`) for what most people never need: the model per job, retries, the user agent, the library folder, restoring, rebuilding search, starting sync over.
The tab ids are the old ones (`ai`, `features`, `storage`, `sync`, `trash`, `events`: the guides, routes and setup checks name them); the labels are Assistant, Capture, Library, Sync, Trash, Activity.
Words: what a person calls things, never the engine's (`SETTING_LABELS`, `EVENT_LABELS` for the Activity rows, the step titles and alert texts in `setup.py`). A setting fixed by an environment variable says "set outside Enqueue (NAME)".
Section headings are what `SHELF_GUIDES` keys on: rename one and update it there, or its `?` mark silently goes.

### Settings explain themselves: the marks, the guides, the eye (2026-10-13)

Three pieces, one source of words.

**The guides (`static/js/guides.js`, shared by the desktop and the phone like `tour.js`).**
Plain data: `what` it is, whether you `need` it, the `steps`, what is good to `know`, the guides it goes `also` with, and `words` (how people ask for it; matcher only, never shown).
`on` says which app a guide belongs to (desktop unless it says `["phone"]`), because a guide's steps name what is on that app's screen; the phone has its own five (`tab: "phone"`).
The same file draws the `?` (`Guides.mark`) and a guide's body (`Guides.html`), so neither app can drift from the other; `css/guide.css` styles both.
There is no guide for the vault, and `tests/js/guides.js` fails if one names it: its door is unmarked.

**The mark and the plate.**
A `?` sits beside a section heading only where the one-line note under a setting cannot do the job.
On the desktop nothing in `settings.js` knows about guides: `settings_guide.js` finds the headings after each tab renders (`SHELF_GUIDES`, heading text -> guide, per tab) and re-applies them whenever the pane changes (a `MutationObserver`, since the sync walk and the backup section re-render themselves).
So a new section gets its mark by adding one line to `SHELF_GUIDES`, and a renamed heading silently loses its mark: keep the two in step.
The guide opens in the Details plate (`.drawer.dpanel.guide`, appended to `#view`), the card it is about is lit (`.guide-lit`, found by `data-guide-for`), and the settings column narrows to clear the plate instead of running under it (`css/guide.css`, the `416px` rule).
A guide on another tab switches to that tab first.
`settings_guide.js` is loaded BEFORE `settings.js`, whose last line boots the app and may open Settings at once.
On the phone the marks are on the `.mset-title` of each `[data-guide-for]` group in `mobile.html`, and the plate is a second `.details-panel` (`#guide_panel`); the Back gesture closes it (`window.__enqBack`).
`const Guides` is not a property of `window`: test for it with `typeof Guides`, not `window.Guides` (that check made the phone's marks silently not appear).

**Where the installation stands (`setup.py`, `GET /setup`).**
Three steps (a model connected, a backup made, sync ready for a phone), each `done`/`todo`/`warn` with one line of detail and the guide that explains it; and `alerts`, settings that need a look because they stopped doing anything or something changed under them: a stored key or extra headers while answers come from this Mac, a model the service does not answer for, summaries waiting on a newly chosen model, images with no description, a relay only the home network reaches, a paused model service, the old password keyring.
Settings shows the steps as cards above the pane until all three are done, the alerts as one quiet list, and "to do" on the tabs concerned; each "Show me" opens the guide.
A guide's "Do you need it" section carries the line for this installation (`Guides.stand`).
No model call and no network request; `facts` (what the eye may be told) carries no secret: a key is present or absent, a relay is `hosted` or `local`, never the address.
Add a new check to `_alerts` with the guide that explains it, and a test in `tests/test_setup.py`.

**The eye in settings (desktop).**
`restorePill("settings")` gives the eye `openSettingsAsk()` instead of the library chat.
Typing ranks the guides in the page (`Guides.match`: no request, no index, no model) and Enter opens the closest one.
The model is asked only on purpose (the "Ask: ..." row, offered when a model is connected) or when no guide matched at all: `POST /setup/ask` sends the question, the few closest guides and `facts` to the chat model (`prompts.SETTINGS_ANSWER`, `schemas.SettingsAnswer`), never the library, and the answer names the guide to go to.
A failed call falls back to the closest guides.
**The eye in settings (phone).**
While Settings is on screen the pill's eye opens the ask sheet instead of conversations (`pillEyePressed` in `mobile.html`).
The sheet is the guide plate in a second mode (`openSettingsAsk`): a field at its top, where the keyboard cannot cover it, the matched guides under it, and the same "Ask: ..." row; Enter opens the closest guide, and each guide's foot ("Ask about ...") leads back to the sheet.
The model call is `mobile_settings_ask` (`desktop/src/lib.rs`, async so the request stays off the main thread; registered in `build.rs`, `tauri.conf.json` and `generate_handler!`): the page sends the question plus a `context` of the closest guides and where the phone stands (`settingsFacts`: the sync line, the lock, the service and model, whether a key is present), and the command adds the instructions (`SETTINGS_ANSWER`, the same rules as the desktop's prompt).
There is no schema on this path, so the model names its guide on a last line, `GUIDE: <id>`, which the page parses and strips.
A failed call falls back to the closest guides. iOS uses the same page and the same command.

### What vaulting covers, who can read the library, and what is never backed up (2026-10-13)

A security review found three holes; this is what closes them and what is still open.

**Vaulting reaches what was derived from the text (`vaultops._seal_derived`).**
It used to seal an artifact's own words (body, title, annotations, page text, drafts, blob) and leave everything derived from them readable: the summary lines, a link's preview, cached model output.
A summary says in plain words what the sealed text is about, so that was the vault leaking.
Now what a model wrote is REMOVED (machine summary lines, entities, section summaries, `related` rows, `derived_values` keyed by the artifact, its retry and pending rows), since it can be written again, and what the person or the page said is SEALED (hand-written summary lines, the preview's title, description, site and picture) and opened again on the way out (`_open_derived`).
Anything new that stores text about an artifact must be added to one of those two lists, and to `tests/test_vaultops.py`, whose test reads the database file for the words.
`vaultops.scrub()` brings items vaulted by an older build up to this: at startup it removes the model's rows (no key needed), and when the vault is unlocked (`POST /vault/unlock`) it seals the rest; it vacuums and pushes each cleaned item so the readable copy leaves the other devices.
A vaulted snapshot replaces a device's summary lines even when it carries none (`sync/snapshot.py` and `apply_snapshot` in `desktop/src/sync.rs`); every other snapshot still leaves local lines alone when it has none.
The phone does the same when it vaults (`vault_apply` in `desktop/src/lib.rs`) and removes leftover model lines beside vaulted items at each launch (`init_schema`).
Still readable about a vaulted item: its tags, its kind and dates, and any conversation that quoted it before it was vaulted.

**The library is its owner's only (`db.restrict_permissions`, at engine startup).**
The data folder is 0700 and the files in it 0600; they were 0755 and 0644, readable by every account on the Mac.
The folder is the gate; blob files inside `blobs/` keep their mode and are unreachable through it.
The phone's key file (`secure_store_set`) is written 0600.

**Nothing of the phone app's is backed up by the system.**
Android: `allowBackup="false"` and `res/xml/data_extraction_rules.xml` (which also stops the phone-to-phone transfer on Android 12+, which `allowBackup` alone does not).
iOS: the app data folder carries `NSURLIsExcludedFromBackupKey`, set in the mobile `setup` (`objc2`).
The files hold the sync key and a readable copy of the library; a new phone is linked by scanning the code on the Mac, so a backup of them buys nothing.

**Not built: encryption at rest.** The database, the blobs and the backups are still plain files (Resolved decision 1), and the phone's key is in a file, not the Keystore or Keychain.
The search index holds every word, so field-level encryption would be theatre; it has to be the whole database.
The sync key must not be the disk key: it exists only once sync is set up, "Reset sync" discards it, and the phone holds a copy.
The shape that fits is one library key born at first run, with separate keys for the disk, the relay and the backups derived from or wrapped under it.
Other findings left open: the vault PIN is 6 digits (a million guesses against the wrapped key), one key both encrypts relay objects and names them, and the relay sees counts, sizes and timing.

### What vaulting covers, who can read the library, and what is never backed up (2026-10-13)

A security review found three holes; this is what closes them and what is still open.

**Vaulting reaches what was derived from the text (`vaultops._seal_derived`).**
It used to seal an artifact's own words (body, title, annotations, page text, drafts, blob) and leave everything derived from them readable: the summary lines, a link's preview, cached model output.
A summary says in plain words what the sealed text is about, so that was the vault leaking.
Now what a model wrote is REMOVED (machine summary lines, entities, section summaries, `related` rows, `derived_values` keyed by the artifact, its retry and pending rows), since it can be written again, and what the person or the page said is SEALED (hand-written summary lines, the preview's title, description, site and picture) and opened again on the way out (`_open_derived`).
Anything new that stores text about an artifact must be added to one of those two lists, and to `tests/test_vaultops.py`, whose test reads the database file for the words.
`vaultops.scrub()` brings items vaulted by an older build up to this: at startup it removes the model's rows (no key needed), and when the vault is unlocked (`POST /vault/unlock`) it seals the rest; it vacuums and pushes each cleaned item so the readable copy leaves the other devices.
A vaulted snapshot replaces a device's summary lines even when it carries none (`sync/snapshot.py` and `apply_snapshot` in `desktop/src/sync.rs`); every other snapshot still leaves local lines alone when it has none.
The phone does the same when it vaults (`vault_apply` in `desktop/src/lib.rs`) and removes leftover model lines beside vaulted items at each launch (`init_schema`).
Still readable about a vaulted item: its tags, its kind and dates, and any conversation that quoted it before it was vaulted.

**The library is its owner's only (`db.restrict_permissions`, at engine startup).**
The data folder is 0700 and the files in it 0600; they were 0755 and 0644, readable by every account on the Mac.
The folder is the gate; blob files inside `blobs/` keep their mode and are unreachable through it.
The phone's key file (`secure_store_set`) is written 0600.

**Nothing of the phone app's is backed up by the system.**
Android: `allowBackup="false"` and `res/xml/data_extraction_rules.xml` (which also stops the phone-to-phone transfer on Android 12+, which `allowBackup` alone does not).
iOS (on the iOS branch): the app data folder carries `NSURLIsExcludedFromBackupKey`, set in the mobile `setup`.
The files hold the sync key and a readable copy of the library; a new phone is linked by scanning the code on the Mac, so a backup of them buys nothing.

**Encryption at rest and the key hierarchy: built 2026-10-14 (see [Encryption and keys](#encryption-and-keys)).** One library key (`libkey.py`), the root: the disk key and the backup keys are derived from it, the sync key is wrapped under it (`keyring_file.dek_by_library`), and the recovery kit is it written out.
The search index holds every word, so the whole database is encrypted (SQLCipher), not fields.
Relay objects are padded to size buckets and named by a keyed hash under their own names key (`crypto.seal_payload`/`object_name`, mirrored in `sync.rs`; a cross-language test pins them).
Still open: the vault PIN is 6 digits (a million guesses against the wrapped key, until a hosted server can count attempts), the relay sees counts, bucketed sizes and timing, the Mac's `blobs/` rely on FileVault, and hosted passkey sign-in needs a domain and an account server.

### A note's drafts: kept by a policy, compared, restored (2026-10-14)

Drafts are `artifact_versions` rows (written by `notes._append_version`, see "A note being written keeps a slower clock"); `drafts.py` decides which are kept, lists them and restores one.
**What is kept** is the `drafts_keep` setting (Settings > Library > Drafts): `thinned` (default: every draft from the last day, the latest per hour for a week, per day for 90 days, per week after; `drafts.LADDER`), `30d`, or `off`.
A note always keeps its latest draft, which is its body version (summaries and search are stamped with it), and, unless drafts are off, its first.
A note's own switch (`artifacts.keep_drafts`, migration 0040; Details panel and the drafts list) turns it off for that note: only the latest is kept and rewritten in place, and switching off removes the rest after a confirmation.
Thinning (`drafts.thin`) runs on the backup scheduler's daily beat, after the backup, and on demand (`POST /drafts/thin`, "Apply now"). Changing the policy removes nothing until then.
**Restoring** (`POST /artifacts/{id}/drafts/{vid}/restore`) goes through `notes.edit(..., keep_current=True)`: the next draft is forced to stand on its own instead of rewriting the newest, so the text the restore replaces stays a draft. Going back can never lose anything.
**The screens** are `js/drafts.js` + `css/drafts.css` (desktop): "N drafts" under the sheet opens the list in a second `.drawer.dpanel` (one plate at a time with Details), each row with the first words it changed and `+added −removed` (word counts against the draft before, `drafts._changed`). Choosing one turns the sheet into a comparison: the editor, its bar and foot are hidden, never rebuilt, so nothing is typed into or saved from a draft.
**The diff** is `js/diff.js` (shared, no page or engine; `tests/js/diff.js`): lines are aligned first, then a removed line looks ahead for the line it became (alike in words, else the same kind of list item) and its words are diffed; marks are private-use characters until `md()` has run, then `<ins>`/`<del>`, and never cross a line or wrap a line's markdown prefix or a code fence, so the marked note renders in its own shape.
A vaulted note's drafts are sealed: the list opens only while the vault is unlocked (409 otherwise).
**On the phone** (`mobile.html`, the `#drafts` screen; `mobile_drafts`, `mobile_draft_restore`, `mobile_drafts_keep` in `desktop/src/lib.rs` over `list_drafts`/`restore_draft`/`set_keep_drafts` in `sync.rs`): Details shows the count and the note's switch, the drafts screen lists them (word counts and first words computed in the page from the drafts' text) and compares one with the note through the same `diff.js`, with Restore (a fresh draft, as on the desktop). The library policy is the Mac's alone; the phone follows the list the Mac sends.
**Keeping the two lists in step.** Drafts replace each other wholesale when a snapshot is applied, so a device that removes drafts must push: `drafts.thin` pushes every note it removed drafts from, and `set_keep` pushes the switch, without moving the note's date (an equal key is applied); unpushed, the phone's next edit carried every removed draft back. `keep_drafts` rides the snapshot both ways (the phone's `build_snapshot` sends it, its apply takes it when present, and the desktop's apply leaves a column a snapshot omits alone), and the phone's draft clock honours it (`keep_draft` in `sync.rs`, the desktop's `_append_version` rule).
A tab's marker line is never marked in a diff (`diff.js` `TAB`): marked, md() no longer read it as a tab and showed the comment itself.

### Tabs inside a note (2026-10-14)

A note can be split into named tabs (the travel note: steps, prompt, candidates). One title, one set of tags, one summary, one set of drafts; the tabs are parts of it.
**Kept in the note's own markdown** (`static/js/tabs.js`, shared; `tests/js/tabs.js`): each tab starts at a marker line `<!-- tab: Name -->`, an HTML comment, so another markdown app shows nothing and an exported note still reads. What comes before the first marker (the title heading) is the preamble every tab shares. A marker inside a code fence is code. A note with one tab is a plain note again (`Tabs.join` drops the markers), which is how deleting or popping out the second-to-last tab ends tabs.
Search, summaries, sync and drafts see one note with marker lines in it; nothing on the engine knows about tabs.
`md()` renders a marker as a small label (`.md-tab`) and `htmlToMd` writes it back, so a draft compared, the phone's reader, or anything else that renders the whole note shows the tabs one after another under their names.
**On the desktop** (`static/js/notetabs.js`, styles in `css/artifact.css`): the editor holds ONE tab's text; `ctx.tabs` keeps the others and `ctx.tabAt` which is open (remembered per note in `sessionStorage`). Everything that reads the note's text goes through `noteText(ed)`, which puts the note back together: the save, the dirty check, the live title, the title edit, the drafts comparison. Reading `htmlToMd(ed)` directly on a note now reads one tab only.
Folder tabs on the sheet's top edge; click switches, double-click (or Enter/F2) renames inline, dragging reorders (pointer events, neighbours slide aside), and on the open tab two tools show on hover: make it its own note (a new note titled by the tab, holding its text) and delete (asks when the tab has text; the text stays in the note's drafts). The formatting bar's last button adds a tab; the first press turns the note so far into a tab named "Notes" and opens a new one with its name ready to type.
Changes to the tabs themselves are saved at once; typing inside one is saved like any note.
A search hit opens on the tab it came from: the search page keeps each hit's snippet, and `NoteTabs.hint` hands it to the next opening, where `Tabs.find` picks the tab a marker in the snippet names, else the tab holding the snippet's opening words, else the one holding most of the query's words, else the tab last open. A snippet is read with `Tabs.plain`, which shows a marker as its tab's name.
**On the phone** (`mobile.html`: `renderNoteBody`, `writerText`, `tabSheet`): the reader shows one tab under a strip of their names (tap, or a sideways swipe over the text), and a tap in the text opens the writing page on that tab with the caret where the finger landed. The writing page edits one tab's text; `writerText()` puts the note back together for every save, so anything that reads the writing page's text must go through it. Its tool bar has "Add a tab" (the first press turns the note into a "Notes" tab, as on the desktop), the strip has a +, and a long press on a tab opens a bottom sheet sized to the visual viewport (so the keyboard does not cover it): its name (kept as typed when the sheet closes), make it its own note, delete. Reordering stays on the desktop. The strip stops its own taps (`stopPropagation`): it redraws itself, and a tap bubbling on to the note found a detached button and opened the writing page.

### Something shiny holds still all day (2026-10-26)

The day's sets are chosen once and kept (`shiny.pick`, `derived_values` scope `shiny_day`); a day with none yet is not kept, so the first connection shows at once. Recomputing on every wall refresh had the card change under the person every few seconds while the related judge kept finding links.
`shiny.prepare()` runs on the backup scheduler's hourly beat and does the day's work once: it chooses the sets and has the model write the first one's words, so the card is ready when the wall opens.
The card (`drawShiny` in `js/home.js`) is one tile: the tilted raven with a gold coin in its beak and stars that twinkle round it (`shinyRavenHtml`, the `--gold` tokens), the shared idea as its headline, the notes as plain rows, the question and one way on. "Find another" walks the day's sets; at the end it becomes "Look for new ones" (`POST /shiny/again`, `shiny.look_again`), which chooses the day's sets again from the connections found since. It redraws only when what it shows changed.
The greeting's raven is the on-demand way in (`mountShinyCall`, `callShiny`, `flyCoin` in `js/home.js`; `.shiny-call` in `css/home.css`): a `<button>` with no label beyond its `aria-label`, whose beak glints on hover and focus, and once a day when no card shows (`enqueue.shiny.nudged`). A press clears "Not today" and hunts for a fresh connection (`POST /shiny/hunt`, `shiny.hunt`): a seed note not used in `SEED_REST_DAYS` (drawn from new notes, old ones or anything), the notes whose idea lines (levels 2-3) come within `HUNT_MIN` of the seed's while their subject lines stay below `RELATED_MIN` (`_candidates`, the farthest first), and one call to the chat model (`prompts.SHINY_HUNT`) that keeps the truest candidate or none, and writes the words; at most `HUNT_SEEDS` calls a press, failing closed. Every pair shown, by the day's card (`today`) or a hunt, is remembered for `REMEMBER_DAYS` (`derived_values` scope `shiny_shown`; seeds in `shiny_seed`; purge drops both) and never hunted again in that time. The day's card holds still underneath; a hunted card stays up in that tab for the day (`sessionStorage` `enqueue.shiny.hunted`), and its "Find another" hunts again. The raven pecks while it waits, a coin flies from its beak to the card raven's and sparkles on landing, and with nothing found it shakes its head and a toast says why (nothing, a paused service, a failed call). Local-only notes never seed or join a hunt. Desktop only: the phone has no related notes.

### The wall's Type and Tags shelves cover the whole library (2026-10-26)

`GET /artifacts/groups?by=kind|tags` returns each shelf's true count and its first 12 items; a shelf's "Show more" pages it through `GET /artifacts` with `kind`, `tags` or `untagged` (`renderWallBody`, `moreOnShelf` in `js/home.js`). They used to be built in the page from the newest 48 items. Last touch pages as it scrolls, as before. The wall's staleness check counts and dates its newest item (`wallStampOf`) and looks again every 30 seconds while the wall shows, unless someone is typing or a menu is open, so an edit made on the phone reorders it.

### The pill keeps its own ground

The page was lightened in October 2026 (lavender ground and tiles, light type; docs/DESIGN.md) and the capture pill deliberately was not: its own lavender glass and bold eye are what hold it over the tiles.
`.pill` (in `css/pill.css` and again in `mobile.html`) redefines `--bg`, `--surface`, `--surface-3`, `--line` and the inks for everything inside it, reading `--pill-ground` / `--pill-tile` / `--pill-well`, which `js/ground.js` sets from `PILL_KEYS` (the earlier day ladder) beside the page's own `KEYS`.
A token change on `:root` therefore does not reach the pill; change the pill on `.pill`, and only on purpose.
Its left button is "+" on the wall and Home on every other screen: the desktop decides in `setRoute` (an empty route is the wall), the phone in `show()` (`library` is the wall).
`bin/check-contrast` reads the night ground from `KEYS` only. `capture.html` links `tokens.css`, so it has no copy of the tokens to keep in step.

### The Details panel is one component for both apps

`css/details.css` (`.dpanel`) and `js/details.js` (`Details.voice/arrive/nod/claim`) are loaded by the desktop and by `mobile.html`, and both emit the same markup and class names: `.dpanel-top` (title, the raven's line, the perched raven, close), `.dpanel-body`, `.dsec` sections, `.tagrow`/`.tagchip`/`.tagx`/`.tagadd`, `.facet-list`/`.facet`/`.facet-text`/`.facet-del`/`.facet-edit`.
Only where the panel sits is per app: `.drawer` in `css/artifact.css`, `.details-panel` in `mobile.html`.
The phone's root carries `data-touch`, which swaps the size variables at the top of the file, shows the controls a pointer reveals on hover, gives the remove a 44px target and lets the summary scroll with the panel.
Change the panel in the shared files, never in one app's stylesheet: the phone's copy had been rewritten by hand to match the desktop's and would have drifted.
On the phone the sections are `<div class="dsec">`, not `<section>`: a `<section>` is a full-height screen in that page.

### The back button goes back, not home

Every page's back button (`back()` in `static/js/settings.js`, used by the artifact page, search, views and settings) calls `goBack()` in `static/js/home.js` and is labelled with the page it goes to (`backLabel`: "Everything", the tag or search, "View", "Back" for another artifact).
It used to be `home()` everywhere, so tags -> books -> a note -> back landed on the wall, which the pill's home button already does.
The trail is kept where every navigation already passes, `setRoute` (`navArrive`): the route tokens come through, each with where it was scrolled when the person last pressed something (a view is torn down before its successor sets the route, so the scroll is read at `pointerdown`/`keydown`).
Arriving on the wall starts the trail over; going back never adds to it (`navReturning`).
It lives in `sessionStorage` (`enqueue.navTrail`), so a reclaimed webview still knows the way back.
Browser history is still not used (`replaceState`): the app has no `popstate` handling.
A vaulted artifact's back still goes to the vault, which keeps it unlocked.

### A note scrolls inside its sheet, under a formatting bar

A note's sheet (`.docpane.notesheet`, desktop; edgeless, on the ground, its text fading out over the editor's own top and bottom padding through a CSS mask) is as tall as the window allows and no taller: `max-height` is the viewport minus where the sheet starts (`--sheet-top`, set by `mountEdbar` and on resize) minus 88px (it ends 10px above the pill; a page holding a note trims its bottom padding to match), and the `.editor` inside it is the scroller.
It used to grow with the note, pushing its own end down the page.
Anything that scrolled the window to a place in a note must scroll the editor instead: find-in-note does (`showFindHit`), and `showArtifact` carries the editor's `scrollTop` across a re-render of the same note.
Your notes on a capture (the second `.docpane`) are short and still grow.
The bar (`edbarHtml`, `EDBAR` in `js/artifact.js`): bold, italic, heading (h2), subheading (h3), bulleted and numbered list, out and in a level, quotation, code block (`toggleCode`: the selected blocks become one bare `<pre>`, a line each, formatting dropped; pressed again, its lines come back out as plain lines).
The first heading of a note is its title, so the bar offers h2 and h3, not h1.
Text put into a code block, by Enter or by paste, goes through `insertIntoCode`, which rebuilds the block's text with the insertion at the caret's offset.
Never `execCommand("insertText")` there: WebKit (the desktop window) reads each newline in it as a new paragraph, so a pasted snippet became one code block per line, and Chrome emits a `<br>` the serializer drops.
A block rendered from markdown ends in one newline the browser does not show as a line; a caret after it counts as the end of the last line, or every insert there grows an empty line.
A code block keeps every newline and space and wraps a long line (`white-space: pre-wrap`, desktop `.md pre`/`.editor pre` and the phone's `#reader_body pre`): it is as often a prompt as a program, and a 500-character line behind a sideways scroll read as one clipped blob.
Every command builds the DOM the typing shorthand and `md()` already build (`toggleList`, `shiftItem`, `formatBlock`), so `htmlToMd` meets no new shape; list commands act on every block a selection touches and join a neighbouring list of the same kind.
`keepingCaret` restores the selection after a move, twice (Chrome re-anchors it a tick later); Tab and Shift+Tab go through the same `shiftItem`.
Buttons carry `aria-pressed` for what the caret is in and `aria-disabled` (never `disabled`, which swallows the press) for what cannot apply; the state is re-read at each press, and a press never takes the selection (`mousedown` is prevented).
The phone's writing page has its own tool bar and is unchanged.

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

### The phone page needs WebView 111 or newer (2026-10-19)

The page runs in the phone's Android System WebView, which Android updates through the Play Store apart from the OS, so the Android version does not say which browser it gets.
`mobile.html` needs Chrome 111 (CSS `color-mix`; `:has` needs 105, `?.` 80); on an older one its scripts fail to parse and it opened half-built (the pill alone at the top, no linking screen).
The first script in the page, written in the JavaScript an old WebView can read, checks for those three and otherwise replaces the page with what to do: update Android System WebView in the Play Store.
`bin/android-matrix`'s Android 9 emulator (WebView 66, no Play Store) is the case that found it and the one that checks the guard; the other four check the page itself.
A newer CSS or JavaScript feature the page starts to need goes into that check.

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

### The tour: the phone's ?, and the desktop welcome's first step (TOUR.1)

`static/js/tour.js` + `static/css/tour.css` are loaded by the desktop home and by `mobile.html`, the way `linkpop` is, so the words, the order and the examples exist once (Dequeue's lesson: its two clients had drifted to different tours).
A card only changes the words that are true of one device (`opts.platform`: click or tap, the hotkey or the + menu); the desktop passes the capture hotkey as it is actually set (`Tour.set({hotkey})` once `/settings` answers).
It opens only from the `?` (`[data-tour-open]`, top right of `.homehead` and of the phone's `.lib-hero`), never by itself; an accent bead sits on the `?` until it has been opened once (`localStorage` `enq.tourSeen.v1`, `VERSION` in tour.js: bump it to bring the bead back after a real change).
Eight cards on the Mac and seven on the phone (Something shiny is the Mac's only: the phone has no related notes), each with a working demo on made-up artifacts (type into the capture box, pick a search, ask, rewrite a summary line, ask the raven for another shiny thing, gather a view); nothing in it reads or writes the library. The first card's "N cards" line is counted, not written.
The vault is left out on purpose: its door is unmarked, and a tour anyone holding the device can open must not mark it.
While open, everything else in `<body>` is `inert` and `html.tour-on` stops the page scrolling; Esc, the close button, the last card's button and the Android Back gesture (`window.__enqBack`) close it, arrow keys and a sideways swipe turn the card (`.tour-body` needs `touch-action: pan-y` or the browser cancels the touch before the swipe lands).
Icons inside it are sized per place: keep the shared `.tour-ico` rule at one-class specificity or it outranks them.
Adding a feature worth showing means editing `cards()` and its demo, not adding a card by reflex: eight is already the ceiling (the eighth, Something shiny, was asked for on purpose).

### A note must round-trip through md() and htmlToMd() unchanged

`static/js/md.js` renders a note (desktop editor, phone reader) and `htmlToMd` writes the desktop editor back; a note opened and saved with no edits must come back byte for byte, or it changes shape on its own each time it is touched.
`tests/js/md_roundtrip.js` (run by `tests/test_md_roundtrip.py`, needs node) pins it: nested and mixed lists, empty bullets (an item, not a list break), dividers (a line of three or more dashes renders as `<hr data-dashes=N>` and is written back with the same count), ordered lists keeping their start, multi-line quotes, code fences, and blocks written with NO blank line between them - md() marks those `data-tight` and the serializer writes them back tight, so lines typed on the phone do not grow blank lines after a desktop save.
Tables are GFM (`| a | b |` over a dash line), kept as written: the dash line rides in `data-sep`; a numbered list written `1.` on every item keeps it (`data-same`); and markdown source another tool exports, a backslash escape (`\~`), an HTML entity (`&gt;`) or a line-ending backslash, shows as what it means inside a `span.md-src` whose `data-md` holds the source, written back while its text is unchanged.
Add a case there for every rendering bug fixed.

### The clipboard is read and written as markdown

`md.js` holds it for every editor (the note editor in `artifact.js`, the capture overlay): `clipToMd(text, html)` turns the clipboard into markdown, `pasteMd(ed, src)` puts it in, `clipOfRange(range)` is what a copy hands over (used by the copy handler in `util.js`).
Pasting used to type the text in with `insertText`: every line became its own paragraph (a blank line between each on save), only the last "- " line became a bullet, and another app's "•" stayed a literal character.
Now one plain line is still typed at the caret, and anything with lines or a list is pasted as markdown: the note is serialized with the caret marked (U+E000), the paste is spliced in (`spliceMd`: text at the caret, a list as lines of its own at the depth of the item it lands in), and the whole editor is rendered again from that, so the screen shows exactly what a reload would.
It goes in through `execCommand("insertHTML")` to stay one undo step, and falls back to setting the HTML when the browser's result does not serialize back to the same markdown.
`clipTextToMd` maps other apps' bullets ("•", "◦", "1)") to markdown markers, any indent width to two spaces a level, and drops blank lines between items.
Clipboard HTML is read only when it holds a list or a table (a web page's list has no markers in its plain text, and a table's plain text puts every cell on its own line); everything else still pastes as text, so styled HTML cannot bring in tags the serializer has no words for.
Copying used to hand over bare `<li>` elements with no list around them and plain text with no markers: items now get their `<ul>`/`<ol>` back (a numbered one keeps its number), and the plain text is markdown whenever the selection holds a list.
A page that pastes must define `esc` (md() needs it): the home has it in `util.js`, `capture.html` and `mobile.html` define their own.
`tests/js/clip.js` pins the text side; the DOM side needs a browser.

### Links in a note: made by pasting, edited from the link bar

Pasting an address over selected words links the words (`md.js linkSelection`, called first by the paste handlers in `artifact.js` and `capture.html`): `createLink` so it is one undo step, then the `<a>` is given md()'s own shape (`class="mdlink"`, `target`, `rel`) and the caret is put after it.
It declines, and the paste goes on as usual, when nothing is selected, the clipboard is not exactly one `http(s)` address, the selected words are themselves an address, or the selection crosses blocks or sits in code.
Pasting over words that are already a link changes where it goes.
The link bar (`js/linkpop.js`) has a third action, Edit, shown only when the link is in a note being edited (`isContentEditable`; never in the reader, a chat answer or on the phone, whose writing page is plain markdown).
It swaps the bar for a small form: Text, Link, "Remove link" (the words stay as plain text) and Done; Enter applies, Escape closes.
The form's fields must be able to take focus, so the bar's `mousedown` guard skips inputs, and a scroll inside a field does not dismiss the bar.
An edit dispatches `input` on the editor, which is what saves it.
The desktop editor saves as you type (debounced) and on window blur, and `refreshIfStale` never rebuilds an editor holding unsaved words (it re-reads the page only when the store changed elsewhere): rebuilding it on window focus used to drop the words typed since the last blur.

### The title is prepended for indexing only

`index_chunks` prepends the artifact title to the chunk text before embedding.
The stored chunk text stays clean.
This exists because a note whose title is the only place a name appears is otherwise unfindable by that name.

### Instructor context keyword

instructor >= 1.9 renamed `validation_context` to `context`.
The keyword is what carries `proper_nouns` and `artifact_text` into the validators.
Getting it wrong silently disables every context-dependent check.

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
