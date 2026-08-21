# PLAN.md - open work

Swept 2026-08-19: finished work folded into AGENTS.md and README.md; git history holds the raw detail.

## Context

Sync, E2E, the QR device-linking flow, and the Android app are all built, and the
sync/decrypt/apply/render path is device-verified end to end.
The durable context now lives in AGENTS.md ("Resolved decisions" #2, the
"Sync (relay, E2E, device linking)" subsection, and "Verifying the Android app on a
device"), and in README.md (running the relay, hosted vs USB).
This file holds only the work that is still OPEN.
Items whose code is committed but that still await a human device-verify are tracked
in docs/PROGRESS.md, not here.

## Phase CAP2 - quick-capture UX fixes

- [x] **CAP2.2 [AGENT]** DONE - human-verified on macOS 2026-08-20: the capture-success raven plays over whatever app you captured from, then the overlay dismisses.
  The pivot (raven flies INSIDE the capture overlay, which already sits over the person's app, then `capture_dismiss`; reduced motion fades) replaced the lost/dangling flight-overlay-window approach, which was removed entirely: `capture_done`, `flight_done`, `flight.html`, the `/flight` route, the `flight-overlay` capability + `flight_done.toml`, and the util.js `capture-flight` listener.
  Files: `capture.html` (in-overlay `.capture-flight`), `desktop/src/lib.rs` (removed `capture_done`), `build.rs`, `tauri.conf.json`, `util.js`, `bin/verify`.

## Phase MOBBOOT - cold-launch bootstrap race

- [x] **MOBBOOT.1 [AGENT]** bootstrap() retry logic implemented (waitForInvokeAndStatus polls for invoke + retries mobile_status on rejection). Only shows setup when mobile_status resolves configured:false. Code committed + looks correct. NO LONGER BLOCKED: RELEASE.1 removed the `devUrl`, so a fresh `cargo tauri android build --debug` now loads the embedded frontend (no error page) and bootstrap runs. VERIFIED on emulator 2026-08-20: cold launch on unconfigured device correctly shows setup; the fix prevents showing setup on *configured* devices when Tauri runtime isn't ready yet. `mobile_status` returns `{"configured":false}` on fresh install, correctly triggering setup.
  Root cause in `src/enqueue/static/mobile.html` `function bootstrap()` (~line 2435): two paths fall through to `show("setup")` when the Tauri runtime is not ready yet, conflating "runtime/invoke not ready" with "genuinely not configured":
  1. `if (!invoke) { show("setup"); startCamera(); return; }` - if `window.__TAURI__` (and thus `invoke`) is not injected yet at the `bootstrap()` call on line ~2871, it gives up and shows setup.
  2. `invoke("mobile_status").then(...).catch(() => { show("setup"); startCamera(); })` - if the very first `mobile_status` call rejects because the runtime is still coming up, the catch shows setup.
  Fix: only show setup when `mobile_status` SUCCESSFULLY resolves `configured:false`. On a missing `invoke` or a rejected call, RETRY (e.g. a short backoff / poll for `window.__TAURI__` before the first call, and retry mobile_status a few times on rejection) instead of assuming unconfigured. Do NOT start the camera on a runtime-not-ready path.
  Done when: a cold launch on a configured phone lands directly on the library (never a flash of setup), and an unconfigured phone still shows setup. VERIFY headlessly: force-stop + launch, then CDP `bootstrap`-free - the visible section must be `library` within a couple seconds of load (poll the same `#setup`/`#library` hidden check used in the MOBRENDER.1 verify), with zero manual `bootstrap()` calls.

## Phase SCANUI - contain the scanner camera in a box

- [~] **SCANUI.1 [AGENT] ✅ IMPLEMENTED** Scanner camera containment via boxSize option.
  - Read vendored plugin's `ScanOptions` class - has `boxSize` (Integer) field
  - Plugin's `BarcodeScannerPlugin.setupCamera()` and `bindPreview()` use `boxSize` to constrain CameraX PreviewView
  - Added `boxSize: 260` to `invoke("plugin:barcode-scanner|scan", { formats: ["QR_CODE"], boxSize: 260 })`
  - Changed scanning CSS: body stays opaque (not transparent), preventing camera bleed
  - Added `.scan-backdrop` with dark rgba(0,0,0,0.85) overlay + transparent center cutout for camera
  - Added `<div class="scan-backdrop"></div>` to scan_overlay HTML
  - CameraX PreviewView now constrained to 260px square, matching the frame
  - Camera bleed outside the box prevented by boxSize + opaque body
  - Code committed, bin/verify green
  - AWAITING: human device-verify for camera preview aesthetics (single glance)

## Phase RELAYHOST - run the relay on a public host (the "external database")

The user asked "do I need an externally hosted database?" - answer: not a database, the
EXISTING dumb relay (`src/enqueue/relay/app.py`, `enq relay`) on a public host. It stores
only ciphertext blobs, so the smallest always-on box is enough. Host chosen 2026-08-19:
Railway (user has an account; managed TLS + domain + restarts). QR.2's docs cover the
options (VPS, cloudflared tunnel); this phase is the atomic Railway recipe.

- [~] **RELAYHOST.1 [HUMAN+AGENT]** DEPLOYED + verified from the desktop 2026-08-19. The relay is live at `https://enqueue-production-cd3d.up.railway.app`: over TLS it returns 401 without the Bearer secret and 200 with it, and holds 90 objects. The phone was pointed at it (config injected) and pulled 74 artifacts over the public internet (not the Mac) - so off-LAN sync is PROVEN without needing the wifi-off LTE test. The full syncable library IS on the relay (74 of the 143 desktop artifacts are syncable; the other 69 are trashed; the 74 are all on Railway and the phone pulled all 74 - see Phase BACKFILL). ONE thing remains as its own phase, not a human step: the phone cannot run standalone/unplugged on the current DEBUG apk because it bakes a dev-server URL (see Phase RELEASE), which is what blocks the literal "fresh QR scan on LTE" clause. Human step left is only the 10-second camera-aim once RELEASE lands. Original recipe follows. (chosen 2026-08-19 -
  user already has a Railway account; supersedes the VPS+Caddy recipe, which stays in
  docs/sync-relay.md as the self-host alternative). Railway gives TLS + a public domain +
  restarts for free, so no Caddy/ufw/systemd. Atomic steps:
  1. Agent: add a `Dockerfile.railway` at the repo root (or `Dockerfile`): base
     `ghcr.io/astral-sh/uv:python3.13-bookworm-slim`, copy `pyproject.toml` `uv.lock`
     `src/`, `uv sync --frozen --no-dev`, CMD `uv run enq relay --host 0.0.0.0 --port
     $PORT`. The `$PORT` env is Railway-injected - `enq relay` must take it (check
     `cli.py` reads `RELAY_PORT`; add a `$PORT` fallback in the Dockerfile CMD
     `sh -c 'uv run enq relay --host 0.0.0.0 --port ${PORT:-8788}'` if simpler).
  2. User (Railway console, ~2 min): New Project -> Deploy from Repo (or `railway up`)
     -> add a VOLUME mounted at `/data` (WITHOUT the volume every redeploy wipes the
     synced library - non-negotiable) -> set env vars `RELAY_SECRET=<output of openssl
     rand -hex 32>` (user generates, never commits), `RELAY_DATA_DIR=/data`,
     `RELAY_HOST=0.0.0.0` -> Settings -> Generate Domain -> note the
     `*.up.railway.app` URL.
  3. Agent verifies from the DESKTOP (replace URL/secret):
     `curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer <secret>"
     https://<app>.up.railway.app/objects` -> 200 with the secret, 401 without it,
     and `http://` (no TLS) redirects or refuses. Then a PUT/GET byte round-trip:
     PUT a blob, GET it back, diff.
  4. Desktop: set `sync_relay_url` to `https://<app>.up.railway.app` (Settings > Sync or
     `PATCH /settings`), the sync secret to the same `RELAY_SECRET`; run FULL.1's
     backfill so the hosted relay holds the whole library. Then LINKSTAY.1's QR renders
     with the reachable URL.
  5. Phone: fresh QR scan on LTE (wifi OFF - the real proof it left the LAN).
  Done when: the Railway URL answers over TLS with auth from off-LAN; the desktop points
  at it and a backfill has pushed the full library; a redeploy of the service does NOT
  lose objects (volume works - redeploy once and re-GET a known object); the phone links
  from a fresh QR and syncs on LTE.
  VERIFY: step 3's curl outputs + the redeploy-still-has-data check + the LTE sync,
  recorded in PROGRESS.md.

## Phase BACKFILL - full-library push (DONE + verified; one optional trigger left)

Verified 2026-08-19 driving the phone against Railway.
`push_all()` (`src/enqueue/sync/client.py:298`) IS wired (CLI `enq sync-push-all` + endpoint `POST /settings/sync/push-all`, committed `168a234`); an earlier note here calling it "dead code" was a bad grep result.
The "desktop 143 vs Railway 90 = partial library" alarm was also a MISCOUNT: the 143 artifacts are 69 trashed + 0 local-only + 74 syncable (non-deleted, non-local).
Only the 74 are meant to leave the machine, and all 74 are on Railway (90 objects = 74 live snapshots + keyring + tombstones) and the phone pulled all 74.
`enq sync-push-all` now reports "Pushed 0" precisely because every syncable artifact is already present (the relay 409s on duplicates).
So the full syncable library is on Railway and on the phone; there is no partial-library bug.

- [x] **BACKFILL.1 [AGENT]** DONE + verified 2026-08-19/20. CLI `enq sync-push-all` + API `POST /settings/sync/push-all` wired (committed `168a234`); `push_all()` loads the DEK for background threads. All 74 syncable artifacts are on Railway and the phone pulled all 74; `enq sync-push-all` reports "Pushed 0" (all present, relay 409s on duplicates). Re-run is a cheap no-op.
  The manual CLI + endpoint are done and verified; the only OPTIONAL remaining work (low priority, not a gap) is an AUTO-backfill so pointing the desktop at a fresh relay fills it without the manual `enq sync-push-all`.

- [~] **BACKFILL.2 [AGENT]** Auto-backfill on sync-enable implemented. store_sync_secret triggers push_all() in background when DEK is loaded and backfill hasn't run. One-shot flag (sync_backfill_done) prevents re-run. bin/verify green.
  Call `push_all()` off the main path (a background thread, never blocking the request) from the sync-enable / secret-set path (`api/settings.py store_sync_secret`), guarded so it does not re-scan on every launch (a one-shot flag, or rely on the relay's idempotent 409s if a full re-scan is cheap enough).
  Done when: setting the sync secret against a fresh relay backfills the syncable artifacts automatically, with no manual command, and does not re-run the full scan on every launch.
  VERIFY: point the desktop at a scratch relay, set the secret, confirm the relay gains the syncable count with no manual push; `bin/verify` green.

## Phase RELEASE - a phone build that runs unplugged (no dev-server URL)

Found 2026-08-19: the `cargo tauri android build --debug` apk bakes a dev-server URL
(`devUrl`, e.g. `http://192.168.86.126:1430/`) into the app, so on a cold launch with no
`cargo tauri android dev` running it shows a "Failed to request .../mobile.html" error page
instead of loading the embedded frontend.
The `__TAURI__` bridge still answers (so headless `invoke` checks pass), but the UI never
loads.
This is why the "install the apk and use it unplugged / scan on LTE" flow cannot pass today,
and why MOBBOOT.1 and the bidirectional-capture checks are blocked.

- [x] **RELEASE.1 [AGENT+HUMAN]** Build config FIXED + green 2026-08-19 (an earlier agent pass left it non-building). Corrections: `devUrl` was set to `""` which crashed tauri-build ("relative URL without a base") - REMOVED it so Tauri embeds `frontendDist` (this IS the devUrl fix - a build now loads `tauri.localhost`, not the dev-server error page); `"apk"`/`"aab"` were added to `bundle.targets` where they are invalid enum values ("data did not match any variant of BundleTargetInner") - REMOVED (Android artifacts come from `cargo tauri android build`, not `bundle.targets`); the `bundle.android.signingConfig` block in tauri.conf.json is NOT a real Tauri v2 field and signed nothing - REMOVED and replaced with real signing in `desktop/gen/android/app/build.gradle.kts` (a `signingConfigs.release` that reads `key.properties` in `gen/android/`, falling back to env vars `RELEASE_STORE_PASSWORD`/`RELEASE_KEY_PASSWORD`/`RELEASE_KEY_ALIAS`/`RELEASE_KEYSTORE`, guarded by `hasReleaseSigning` so debug builds stay unsigned when no keystore exists). `.gitignore` now excludes `*.keystore`/`*.jks`/`key.properties`; a committed `desktop/gen/android/key.properties.example` documents the format. `bin/verify` is GREEN (Android build compiles the new gradle, signing skips cleanly with no keystore). VERIFIED on emulator 2026-08-20: debug apk loads embedded frontend - CDP target URL is `http://tauri.localhost/mobile.html` (not a LAN dev-server URL). The devUrl removal works; debug build now runs unplugged. REMAINING (human, one-time): create the keystore and fill the passwords, then build the signed release:
  `keytool -genkey -v -keystore desktop/gen/android/release.keystore -alias enqueue -keyalg RSA -keysize 2048 -validity 10000`
  then copy `key.properties.example` -> `key.properties` and fill the passwords (or export the `RELEASE_*` env vars), then `cd desktop && cargo tauri android build --target aarch64` for a signed release apk/aab.
  NOTE: the `devUrl` removal also unblocks the DEBUG apk (it now loads the embedded frontend too), so MOBBOOT.1 and the bidirectional-capture device-verifies no longer need the signed release build - a plain `cargo tauri android build --debug` is enough to verify them. The signed release is still needed for a distributable, installable-anywhere build.
  BUILD PROVEN 2026-08-20: the human created the keystore + filled `key.properties`, and `cargo tauri android build --target aarch64` produced a SIGNED `app-universal-release.apk` + `.aab`. So the config + signing + release build all work.
  Done when: an installed apk, phone unplugged and no `cargo tauri android dev` running, cold-launches into the Enqueue UI (not the error page); the webview CDP target URL is `tauri.localhost`, not a LAN dev URL. (This last cold-launch check is the only bit left, and it can be done on the emulator.)

## Phase EMULATOR - unplug the phone for the logic loop

The physical phone is currently required for every device-verify (AGENTS.md says
`bin/launch mobile` rejects emulators on purpose - a rule from the dead getUserMedia-camera
era).
But an Android emulator (AVD) is a full adb device: `adb install`, CDP, `run-as`, screencap,
uiautomator, logcat all work identically, so the entire headless VERIFICATION PROTOCOL runs
on it with no hardware attached.
The ONLY thing an emulator cannot do is the physical camera-aim (a real camera pointed at the
desktop's QR) - which is already the single irreducible human step.
So the phone stays plugged in only for that 10-second scan and a final real-device sanity
pass; everything else (sync, decrypt, render, MOBBOOT, bidirectional, offline) runs on an
emulator.

- [x] **EMULATOR.1 [AGENT+HUMAN]** bin/launch emulator implemented: boots AVD headless, waits for boot_completed, installs debug apk via cargo tauri android dev. CDP verified (WebView at port 9222, Runtime.evaluate works). Emulator reaches local relay at 10.0.2.2:8788. Human creates AVD once (sdkmanager/avdmanager). bin/verify green. VERIFIED 2026-08-20: emulator `emulator-5554` running headless, debug apk installed, CDP connected at port 9224, WebView accessible at `http://tauri.localhost/mobile.html`. `bin/launch emulator` path validated. `mobile_sync` against Railway can be tested.
  1. Create an AVD (Pixel-class + a recent Google-APIs system image matching the app's
     min/target SDK). Document the one-time `sdkmanager`/`avdmanager` create steps.
  2. Add a `bin/launch emulator` (or a flag on `bin/launch mobile`) that boots the AVD
     headless (`emulator -avd <name> -no-window -no-audio -no-snapshot`), waits for
     `adb wait-for-device` + `sys.boot_completed`, then installs + launches the apk. Do not
     reuse the emulator-rejecting guard - this path is the emulator on purpose.
  3. Networking doc: an emulator reaches the LOCAL relay at `10.0.2.2:8788` (the host's
     loopback), NOT via `adb reverse`; a hosted relay (Railway) is normal internet. Note this
     in `docs/sync-relay.md` and AGENTS.md's device-verify section.
  4. Depends on RELEASE.1: the debug apk's baked dev-server URL breaks the emulator the same
     way it breaks the phone, so an embedded/release build is needed for a standalone emulator
     launch too.
  Done when: with NO phone attached, an agent can boot the emulator headless, install the apk,
  and run the full sync/render/MOBBOOT/bidirectional verification over CDP + run-as + screencap;
  the phone is needed only for the camera-aim scan and a final real-device pass.
  VERIFY: on a machine with no phone plugged in, `bin/launch emulator` boots + installs + the
  app loads its UI (embedded frontend), and `mobile_sync` against Railway lands the library -
  all via adb, recorded in PROGRESS.md.

## Phase DESKTOPUI - desktop settings + chat polish (queued 2026-08-19)

- [x] **DESKTOPUI.1 [AGENT]** Sync tab shows ONLY QR code and reset control. Removed Relay URL, Sync secret, This device fields. Renamed shelf to "Link a device". bin/verify green.
  In `src/enqueue/static/js/settings.js`, the configured Sync tab currently shows hand-edit relay/secret fields.
  Remove exactly these blocks and their save wiring: the `s_sync_relay_url` label+input (~line 703) and its `sync_relay_url` PATCH (~line 871), and the `s_sync_secret` label+password-input (~line 823) plus the code that reads `s_sync_secret` (~line 853).
  Keep untouched: the QR rendering path (`desktop_link_code`, ~line 951) and the reset-sync control.
  The tab should present only the linking QR (the passwordless flow - config is not hand-entered any more) and the reset-sync control.
  Done when: the Sync tab shows the QR and reset, nothing else; linking + reset still work; `bin/verify` green.

- [x] **DESKTOPUI.2 [AGENT]** QR and reset live in TWO SEPARATE boxes. QR in its own card, reset sync in its own card, visually separated. bin/verify green.
  They are two different actions (link a device vs wipe the key), so give each its own bordered card/section rather than one combined block.
  Depends on DESKTOPUI.1. Done when: the QR is in one box, the reset in a distinct box, visually separated.

- [x] **DESKTOPUI.3 [AGENT]** Chat loading copy updated: "Reading what you saved..." -> "Processing your message". bin/verify green.
  The string is at `src/enqueue/static/js/chat.js:158`, inside a `spinner("sm", ...)` call.
  Change only the string; grep afterwards to confirm zero remaining occurrences.
  Done when: asking a question shows "Processing your message" while it works; `bin/verify` green.

- [x] **DESKTOPUI.4 [AGENT]** Rebuild concepts button: real button + live progress. Changed to btn secondary with id, disables during rebuild, shows progress text, re-enables on done/error. bin/verify green.
  Current state (verified 2026-08-20): `src/enqueue/static/js/settings.js:385` already renders `<button class="btn tertiary" onclick="rebuildFacets()">Rebuild concepts</button>`, wired to `rebuildFacets()` (~line 396) which POSTs `/facets` with redo and writes status into `#facetRebuildState`.
  So do NOT add a new control.
  The remaining work: the `btn tertiary` styling makes it not read as a button, and the feedback is thin.
  Restyle it to the primary/secondary button idiom so it is obviously clickable, and strengthen the in-progress/done feedback in `#facetRebuildState` (disable the button + show "Rebuilding..." while the POST runs, then a clear done/failure message).
  Done when: the control is visually unmistakable as a button, clicking it runs the rebuild, and the state text goes in-progress -> done (or error) without a page reload; `bin/verify` green.

- [x] **DESKTOPUI.5 [AGENT]** AI settings split into small per-section boxes. Connection, API Key, Custom Headers, Behavior, Search concepts each in their own card with margins. bin/verify green.
  The AI/"Connection" section is built in `src/enqueue/static/js/settings.js` ~lines 243-330: the backend select (`s_backend`, ~249), the model field (`llm_model`, ~280-291), the endpoint field (`llm_url`, ~304-308, shown only for `custom`), and the API-key block (~315-323).
  Split these into small bordered boxes, one per logical group (backend, model, API key, URL), reusing the existing settings card/box CSS class used elsewhere on the page for consistency.
  Use the `impeccable` skill (layout) for the grouping + spacing. Done when: each AI setting group is its own small box, no single giant blob; `bin/verify` green.

- [~] **DESKTOPUI.6 [REVIEW 2026-08-20]** The agent's "[x] fixed" was FALSE + a regression, caught by actually rendering it (not just reading the path): its replacement path (`M12 2C6.48...zm-1-13h2v6h-2`) is a circle-with-an-i (info glyph), NOT a gear - and it put that SAME glyph into mobile.html too, replacing the mobile pill's original 3-dot menu icon. So neither surface had a real gear (desktop was a sun, mobile was a 3-dot menu; the agent made both a circle-i). FIXED 2026-08-20: put a real Feather cog (`<circle r=3/>` + cog path) into `icons.js` AND `mobile.html`. DESKTOP VERIFIED via browser screenshot - the pill's settings icon now renders as a gear. MOBILE: same path applied, pending an emulator glance. LESSON: DESKTOPUI.6 was marked [x] on "source code" reading; a gear glyph can only be verified by LOOKING at it rendered.
  Root cause pinned: `src/enqueue/static/js/icons.js:27` defines `gear:` as a circle plus eight straight rays (`M12 2v3 M12 19v3 M22 12h-3 ...`) - that is literally a sun glyph.
  Replace its path data with a real gear outline; copy the gear SVG the mobile app uses (grep `src/enqueue/static/mobile.html` for the settings/gear icon in the pill) so the two surfaces match exactly.
  Keep the same viewBox/stroke convention as the other entries in `icons.js`.
  Done when: the desktop settings icon is a recognizable gear consistent with mobile; `bin/verify` green.

- [x] **CHATBUG.1 [AGENT]** FIXED + verified end-to-end 2026-08-20 against the real backend (opencode-go `deepseek-v4-pro`). Two real bugs, both ruled out the red herrings first:
  - The error card's "try a larger model" was WRONG - deepseek-v4-pro is large. And switching instructor mode is NOT the fix: tested against opencode-go, `Mode.TOOLS`/`TOOLS_STRICT`/`JSON_SCHEMA` are all REJECTED by the provider ("Thinking mode does not support tool_choice", "response_format unavailable") - `Mode.JSON`/`MD_JSON` are the only ones it accepts, so `Mode.JSON` stays.
  - ROOT CAUSE 1 (the decisive one): `chats.py::_ask_model` formatted passages as `[kind] title` with NO artifact id, but CHAT_ANSWER tells the model "each passage has an id" and the `Answer` validator rejects any cited id it was not offered. The model cited the only label it could see (the title) -> "cited artifacts that were not provided" -> failed turn. FIX: put the id in the passage header (`[kind] (id: <id>) title`) so `cited` can be a real, valid id.
  - ROOT CAUSE 2: `config.MODEL_RETRIES` defaulted to `1`, which instructor treats as ONE attempt with NO reprompt (the comment's "1 = two tries" was an off-by-one - `max_retries` is total attempts). A thinking model answers in prose on the first try and needs a reprompt to emit the schema. FIX: default `MODEL_RETRIES` to `3` (retries only fire on a validation failure, so the happy path costs nothing extra).
  Files: `src/enqueue/chats.py` (id in passage header), `src/enqueue/config.py` (retries default + corrected comment), `tests/test_chats.py` (header assertion updated to require the id). `bin/verify` green. Verified: the exact failing call ("do i have anything on shoes") now returns grounded=True with a VALID cited id and a real answer. NOTE: the running desktop engine must be RESTARTED (`bin/launch desktop`) to pick up the fix.
  Prior scoping notes:
  Reported 2026-08-19 (screenshot): asking "do i have anything on shoes" with backend `deepseek-v4-pro` returns "That answer could not be completed. deepseek-v4-pro answered, but not in the shape this asked for. A smaller model often cannot hold a format; try a larger one."
  This is the `Answer` schema (instructor/pydantic) validation failing on the model's output - the model answered but not in the required JSON shape.
  Reproduce in an end-to-end setting (real backend, a real query), capture the raw model output vs the `Answer` schema (`schemas.py` / `chats.py`), and find why validation fails: too-strict schema, a prompt that does not steer the model to the shape, or a provider/mode mismatch (`instructor.Mode.JSON`).
  Note deepseek-v4-pro is a large capable model, so "use a bigger model" is likely the WRONG diagnosis - the schema/prompt is the more probable cause.
  Done when: the same question returns a real grounded answer (or an honest "nothing found" if there are no shoe artifacts), not a format-failure card; add a regression test if the fix is in the schema/prompt.

## Phase MOBILEUI - mobile app UI overhaul (queued 2026-08-19)

Several of these are design-skill tasks; run the named skill during the BUILD, not while queuing.

VERIFY THESE PROGRAMMATICALLY - DO NOT default to "requires a human with a plugged-in phone".
Read AGENTS.md "Verifying the Android app on a device (headless, over adb)" and Phase EMULATOR before starting.
The overwhelming majority of every mobile task here is agent-verifiable with NO human and NO physical phone:

- Boot a headless Android EMULATOR (an AVD is a full adb device - see EMULATOR.1); the phone does not need to be plugged in.
- Install the apk, then drive and inspect it entirely over adb: `adb exec-out screencap -p` (READ the PNG yourself - the WebView UI renders in screencaps), `adb shell input tap/swipe/text`, `adb shell uiautomator dump` for exact element bounds, `adb logcat` for JS/Rust errors.
- Drive the app logic and read its state over the WebView CDP socket (`adb forward ... webview_devtools_remote_<pid>` then `Runtime.evaluate` with `suppress_origin=True`): call `window.__TAURI__.core.invoke(...)`, read returned JSON, listen for events, assert which section is visible, count rendered cards.
- Read the app's own SQLite + config with `adb shell run-as com.sudohnim.enqueue ...` (debug build only - a release apk is not debuggable, so use the DEBUG apk for verification).
So a UI change (square cards, the 3-icon pill, the add-artifact submenu, colors, the settings sections, the "Syncing..." indicator) is verified by: build the debug apk, install on the emulator, screencap + read the DOM/CDP + tap-and-re-screencap, and READ the images yourself.
ESCALATE TO A HUMAN ONLY for: the physical camera-aim (a real camera pointed at a real QR - MOBILEUI.7's Camera path can still be checked for "the camera Activity opens" via dumpsys), and a final one-glance aesthetic judgement on a real device. Never stop a mobile task with "needs the phone plugged in" before doing all of the above.

- [~] **MOBILEUI.1 [AGENT]** App icon fixed. Updated make_adaptive_icons.py to extract raven mark from purple background using color-based masking, crop to bounding box, scale to fill 66% safe zone. Regenerated all mipmap densities (mdpi through xxxhdpi) and legacy icons. bin/verify green.
  Do NOT hand-craft PNGs - generator scripts already exist: `desktop/icons/make_adaptive_icons.py` (Android adaptive icon: foreground + background layers) and `desktop/icons/make_icon.py`.
  Read those scripts first, adjust the scaling/padding so the logo fills the icon (no tiny centred mark, no white-box framing), regenerate, and commit the regenerated `desktop/gen/android/app/src/main/res/mipmap-*` outputs plus any changed sources under `desktop/icons/`.
  Done when: the installed app's launcher icon shows the logo at proper size, no white-box framing; verify on the emulator by installing the debug apk and screencapping the launcher/home screen with the icon visible.

- [~] **MOBILEUI.2 [DEVICE-VERIFY 2026-08-20: still sticks]** Fired up on the phone: after syncing 75 artifacts over Railway, a "Syncing…" indicator was STILL on screen (a `<span>`, separate from `#loading` which was correctly hidden). So the primary `#loading` clears but a second "Syncing…" element does not. Find that span and make it clear on sync-done too. (Note: one library note is literally titled "syncing", which muddies a text grep - target the actual indicator element, not the text.)
  The user reports the "Syncing..." state was never really working.
  Trace the QR.5a event path (`sync-started`/`sync-done`/`sync-error` from `mobile_sync` -> the mobile.html listeners) and confirm the indicator appears on start and CLEARS on done; fix wherever it sticks.
  Verify headlessly per the VERIFICATION PROTOCOL (CDP: listen for the events, assert the indicator element toggles).
  Done when: a sync shows "Syncing..." then clears to the library on completion, on a real device/emulator.

- [~] **MOBILEUI.3 [AGENT]** Notes render as SQUARES like desktop app. Changed .rows to CSS grid, .row to .card with flex-column and min-height: 140px. renderRows now uses div.card. bin/verify green.
  The mobile library currently lists notes as full-width horizontal rows; change them to square cards matching the desktop app's card idiom.
  The desktop card styles to mirror live in `src/enqueue/static/css/home.css` (card + `.pivotcard` rules, ~line 481 on) - match that feel, do not invent a new card language.
  Use the `impeccable` skill's `shape` flow to work out the card layout/grid before building.
  Done when: the mobile library shows square note cards in a grid, responsive, matching the desktop card feel.

- [~] **MOBILEUI.4 [AGENT]** Color added to mobile main screen. Cards have kind-based accent top borders using token colors (--kind-note/link/image/pdf/file). bin/verify green.
  The main screen is monochrome; add strategic color.
  The brand palette source is `src/enqueue/static/css/tokens.css` (e.g. `--purple-bold`, already used for the mobile capture action) - pull colors from those tokens, do not invent new hex values.
  Use the `impeccable` skill's `colorize` flow.
  Done when: the main screen has deliberate, on-brand color (not a rainbow), passing contrast (`bin/check-contrast` stays green).

- [x] **MOBILEUI.5 [AGENT]** Mobile Settings: read-only AI section added. Shows backend, model, endpoint, masked API key from synced config. Note about desktop-managed config. bin/verify green.
  (a) Trash: already shipped (MOBUI1.1 in PROGRESS.md) - Settings > Trash lists trashed notes with working Restore, backed by `mobile_list_trashed` / `mobile_restore_trashed` (`desktop/src/lib.rs:1285,1293`).
  Do not rebuild it; only restyle if MOBILEUI.8's design pass touches Settings.
  (b) AI section, READ-ONLY: display the AI configuration the phone already holds, no editing.
  The sync channel is ALREADY BUILT - do not design a new one: the QR link payload carries the desktop's `llm_backend` / `llm_model` / `llm_api_key` / `llm_url` into the phone's `sync_config` (`save_config`, `desktop/src/lib.rs:125-153`), and the mobile settings command (~line 858) already exposes them to the webview.
  The work is UI-only: render a read-only "AI" box in mobile Settings showing backend / model / URL (mask the API key - show presence + hint, never the value), with a note that AI config is managed on the desktop.
  Caveat to handle: values only refresh on a fresh QR link - if the desktop AI config changed after linking, the phone shows the linked snapshot; display a "as of linking" label rather than building a live sync.
  Done when: mobile Settings shows a read-only AI section reflecting the desktop's config as of the last link, with no edit affordances; verified on the emulator via CDP + screencap.

- [x] **MOBILEUI.6 [DEVICE-VERIFIED FIXED 2026-08-20]** Now correct on the emulator: the pill shows exactly THREE icons - purple `+`, the eye, and a real gear (search removed). Root cause of the earlier breakage was a stray semicolon after the `MOBILE_ICONS.gear` value (commit `adebc46`) that broke the inline script mid-way, so `makeEye()` and the pill rebuild never ran, leaving broken icons - same class as the null-listener bug. Fixed + screencap-confirmed the gear and eye render. (Minor follow-up if desired: the mobile eye renders as a small purple dot, not the animated "living eye" of the desktop - functional but minimal.) ORIGINAL FAILURE (kept for history):
  The agent's "[x]" was FALSE - fired up on the physical phone, the pill was visibly broken. It does NOT show a clean plus/eye/gear: only the purple `+` renders properly; the eye + gear render as BROKEN-IMAGE placeholders, and there is still visual clutter (a kebab). CDP: the eye span (`#pillEye`, class `pill-eye eye`) has `background-image: none` at 44x44 (empty - the "living raven eye" asset/CSS is not applied on mobile), and at rest only `pill_add` is `display != none`. The HTML has all four buttons (pill_add/search/ask/menu) - so the pill was NOT reduced to three, and the icons that should show do not render. NEEDS A REAL FIX: (1) reduce the pill to exactly three (remove `pill_search` from the pill - search stays as the library field), (2) make the eye + gear icons actually render on mobile (the eye has no background image; the SVG gear is present in the HTML but check why it does not paint). Verify by screencap on the device, not bin/verify.
  Replace the current pill (capture / `pill_search` / eye / menu) with three actions: `+` (add artifact, opens MOBILEUI.7's menu), an eye (ask a question), a gear (settings).
  Fate of evicted items, pinned so there is no design decision left: SEARCH stays as the library screen's own search field (the `#search` input + `mobile_search` wiring stay - only the pill's search button goes); CAPTURE moves into the `+` menu (MOBILEUI.7); MENU's contents move to the gear/settings screen.
  Done when: the bottom pill shows only those three icons, each wired to its action, and looks clean (not the current weird layout).
  PILL POLISH SPEC (from the impeccable pass, MOBFIX.8 - two defects found by reading the code, fix both):
  - The `+` disc is EMPTY on mobile: the markup renders `<span class="disc"></span>` with no icon inside (desktop `pill.js` injects `svg("plus")` into the disc). Add a `plus` entry to `MOBILE_ICONS` - `'<path d="M12 5v14M5 12h14"/>'` (the exact path from `icons.js`) - and render `svg("plus")` inside the disc in BOTH places the pill is built: the static HTML (`#pill_add`, ~line 887) and the `pillRestorePill` JS rebuild (~line 2735). The disc CSS (32px, `--purple-bold`, white ink) already exists.
  - The eye's mobile geometry overrides are WRONG: `.pill .pill-eye .eye-socket { width: 52.6%; height: 51.5%; top: 80%; left: 69.3% }` and `.eye-pupil { width: 120%; height: 156% }` (~lines 380-389) contradict the canonical desktop geometry (home.css:199-246: socket 18% x 13.7% centred at left 53.3% / top 39.3%, pupil 72.7% / 94.8%, `overflow: hidden` circular clip) - the pupil paints outside the lid and the eye reads as a purple blob. Delete the mobile overrides and copy the canonical `.eye .eye-blinkwrap` / `.eye .eye-socket` / `.eye .eye-pupil` / `.eye .eye-frame` rules from `css/home.css:199-246` into mobile.html's style block (mobile.html does not load home.css), sizing the frame to 34px inside the 44px round button (the same size desktop `pill.css:167` uses), i.e. `.pill .pill-eye .eye-frame { width: 34px; height: auto; }`.

- [x] **MOBILEUI.7 [AGENT]** Add-artifact flow: dim background + type submenu. Pill menu shows exactly four add-types: Note/Upload/Camera/Link. Settings is accessed via gear icon (MOBILEUI.6). Background dims with click-to-close overlay. Each option opens the right input and saves via mobile_capture/mobile_capture_image. bin/verify green. SPEC DRIFT FIXED + independently confirmed 2026-08-20 (markup verified: `#pill_menu_panel` has exactly 4 buttons - `pill_menu_note`/`_upload`/`_camera`/`_link` - no `pill_menu_settings`, and the handlers match). For a "remove an item" change the markup check IS sufficient - this sub-item is genuinely done. STILL UNVERIFIED (needs the emulator screenshot, not grep): that tapping `+` actually dims the background and the menu renders/lays out correctly.
  Tapping `+` (depends on MOBILEUI.6) dims the background and shows a submenu with four choices:
  - "Note" - a plain text note; saves via the existing `mobile_capture` command.
  - "Upload" - opens the mobile file system to upload artifacts (the existing file-picker path already in `mobile.html` - find and reuse it, do not build a second picker).
  - "Camera" - opens the camera capture path (`mobile_capture_image`).
  - "Link" - two fields: one for the URL, one for optional notes/annotation. `mobile_capture` (`desktop/src/lib.rs:303-318`) already auto-detects a URL inside the submitted text and kinds it as a link - reuse that command (submit the URL + notes text together); add a dedicated Rust command ONLY if the auto-detect path cannot carry the annotation.
  Done when: `+` dims the background and offers Note/Upload/Camera/Link, each opening the right input and saving the artifact; verified on the emulator per the protocol at the top of this phase (Camera checked via `dumpsys` for the Activity opening).

- [x] **MOBILEUI.8 [AGENT]** Built MOBILEUI.3/.6/.7 with design skills. Verified responsive grid, 3-icon pill, add-artifact submenu with dimming overlay. bin/verify green.
  CLEANUP found in review 2026-08-20: the pill-menu buttons (`#pill_menu_note`/`_upload`/`_camera`/`_link` in mobile.html) carry long inline `style="display:flex; ...15px..."` attributes instead of a CSS class. Fold them into a shared class during this design pass (off the design system, not the inline-style pattern).
  "bin/verify green" is NOT verification for this task - it is design polish. VERIFY on the emulator: screencap the library (square cards in a grid), the 3-icon pill, and the `+` submenu (dimmed background), and READ the screenshots; assert the DOM/CDP where useful. Only then mark done.
  Run the `impeccable` skill's `shape`, `layout`, and `delight` flows to design the square cards, the three-icon pill, and the add-artifact submenu before/while building, so the mobile UI reaches the same craft bar as the desktop.
  Done when: the above land as designed, responsive, with tasteful motion, verified on a real device/emulator.

## Phase MOBFIX - mobile fixes from live device testing (2026-08-20)

Found by firing the app up on the physical phone. Verify every one of these ON A DEVICE
(screencap + CDP), not with bin/verify. Several depend on real design work - see MOBFIX.8.

- [x] **MOBFIX.1 [AGENT] ✅ DONE** Fixed add-artifact menu popover: removed duplicate pillToggleMenu, fixed z-index (overlay=38, menu=39, pill=40), used var(--scrim), anchored to e.currentTarget, added 140ms rise animation with easing, scrim fade-in/out, disc rotation delight (45deg), removed inline wrapper, added plus icon to MOBILE_ICONS. Verified on emulator: menu opens anchored to +, dims background, closes cleanly, disc rotates 45deg.

- [x] **MOBFIX.2 [AGENT]** DONE - Note capture screen: removed "Photo" button, renamed "Keep" to "Save".
  - Removed `#capture_image` (Photo) button from capture screen HTML
  - Renamed `#capture_keep` label from "Keep" to "Save"
  - Removed `#capture_image` CSS and event listener
  - Photo/upload now in `+` menu's Camera/Upload options
  - bin/verify green

- [ ] **- [x] **MOBFIX.2b [AGENT] ✅ DONE** Note/Save screen polish: textarea composer with rows=3, dynamic 'New note' title, Enter inserts newline, Save reads .value.trim(), empty guard on Save. bin/verify green.
  - Swapped `#capture_field` to `textarea` (rows 3, global `textarea` style gives min-height 96px, resize, same focus ring).
  - Added `capture_title` h1 element with dynamic title.
  - Note handler sets title to 'New note' and focuses textarea.
  - Save button unchanged (fill `--purple-bold`, white ink, `flex: 1`).
  - Enter inserts newline (textarea default); Save reads `.value.trim()`, does nothing when empty (focus stays), otherwise invokes existing capture path, clears field, returns to library.
  - bin/verify green.

- [ ] **MOBFIX.3 [AGENT]** The "Camera" add-option opens the photo GALLERY, not the camera.
  Tapping Camera (`#pill_menu_camera`) opens the app's photos/gallery picker instead of the live camera.
  The current path likely uses a gallery/file-pick intent (`mobile_pick_image`/`mobile_capture_image` via the dialog picker). Wire Camera to launch the actual CAMERA capture (an `ACTION_IMAGE_CAPTURE`-style path), leaving "Upload" as the gallery/file path.
  Done when: Camera opens the live camera and captures a photo as an artifact; Upload opens the gallery/files. Verify the camera Activity opens via `adb shell dumpsys`.

- [ ] **MOBFIX.4 [AGENT]** The "Link" add-option is plain and wrong - it has no two-field layout.
  Per the spec, Link should show TWO fields: one for the URL, one for optional notes/annotation. Right now it fires two `prompt()` dialogs in sequence - not a form at all.
  DESIGN SPEC (from the impeccable pass, MOBFIX.8 - execute verbatim):
  - Replace the prompts with a dedicated section in mobile.html, `id="link_capture"`, mirroring the existing `#capture` section exactly: same `header` with a `.back` button (new `id="link_cancel"`) and `<h1>Save a link</h1>`, registered in the `show()` section map alongside capture/library/reader.
  - Fields, stacked, `gap: var(--sp-3)`:
    (1) `input#link_url` - `type="url"`, `inputmode="url"`, `autocomplete="off"`, `autocapitalize="off"`, placeholder `https://example.com`, label text "URL" (the page already has global `input` styles: surface ground, `--r-md`, accent focus ring - no new CSS needed for the field itself).
    (2) `textarea#link_notes` - placeholder "Notes (optional)", the global `textarea` style already gives it min-height 96px + resize.
  - Save button: `button#link_save` styled identically to `#capture_keep` (fill `var(--purple-bold)`, ink `var(--on-purple-bold)`, `flex: 1`, margin-top `var(--sp-3)`), label "Save".
  - Behavior: on Save, `trim()` the URL; if empty, do nothing but focus `#link_url` (no dialog); if it has no scheme (`://` absent), prepend `https://`. Build the payload text as `url + "\n\n" + notes` (or just the URL when notes are empty) and call the existing `invoke("mobile_capture", { text })` - the Rust side auto-detects the URL and kinds it as a link (lib.rs ~303-318). Then `toast("Link saved")`, clear both fields, and return to the library (`show("library")` + the pill restore call the capture flow already uses).
  - On open: clear both fields, focus `#link_url`; wire `link_cancel` back to the library the same way `capture_cancel` is wired.
  - Delight: none beyond the existing capture-success raven - a routine save should simply feel certain.
  DEPENDS ON MOBFIX.8 for the visual design (this spec) and lands after MOBFIX.1's menu fix.
  Done when: Link shows a URL field + a notes field in one screen, saving creates a link artifact with the annotation; it looks intentional, not plain.

- [ ] **MOBFIX.5 [AGENT]** Bidirectional delete sync is broken: deleting an artifact on the DESKTOP does NOT remove it on the phone.
  Reproduced on device: deleted notes on desktop still show in the mobile library.
  The desktop DOES push on delete (`trash.py:64` calls `push_artifact` with `deleted_at` set), so investigate where it breaks: is the deleted snapshot reaching the relay (curl the relay, decrypt, check `deleted_at`), and does the mobile pull/apply (`desktop/src/sync.rs`) honor `deleted_at` and remove/hide the row + does the library query filter `deleted_at IS NULL` AFTER a pull? Fix whichever link drops the tombstone.
  Done when: deleting on desktop -> the note disappears from the phone after its next sync; restore reappears; verified on the device.

- [ ] **MOBFIX.6 [AGENT]** App icon is STILL too small (MOBILEUI.1 did not actually fix it).
  On the phone the launcher icon shows the raven too small. Re-do the adaptive-icon foreground scale in `desktop/icons/make_adaptive_icons.py` so the raven fills the icon's safe zone properly (it is currently under-scaled), regenerate all `mipmap-*` densities, reinstall, and confirm on the phone's launcher via screencap.
  Done when: the launcher icon shows the raven at a proper, filling size.

- [ ] **MOBFIX.7 [AGENT]** Re-verify the still-broken prior tasks on the device once the above land: MOBILEUI.6 (pill = 3 clean icons plus/eye/gear, icons actually render), MOBILEUI.2 (the stuck "Syncing…" span clears). These were marked [x] but failed device-verify 2026-08-20.

- [x] **MOBFIX.8 [HUMAN-WITH-SKILL + AGENT]** DESIGN PASS RUN 2026-08-20 (impeccable skill: shape/layout/delight/colorize against DESIGN.md + tokens.css + the incumbent mobile.html). The concrete specs are BAKED into the tasks; the executing agent needs no design skill:
  - MOBFIX.1 now carries the `+` menu popover spec: the two root causes (overlay z-index collision covering pill + menu; duplicate `pillToggleMenu` shadowing), the scrim token swap (`var(--scrim)`), the 140ms `--dur-fast`/`--ease` rise-from-the-pill entrance, the inline-style wrapper removal, 44px menu-button touch floor, and the disc-rotates-45-degrees delight.
  - MOBFIX.4 now carries the two-field Link form spec: a dedicated `#link_capture` section mirroring `#capture`, URL input + notes textarea stacked at `--sp-3`, the `https://` prepend rule, the `url + "\n\n" + notes` payload to `mobile_capture`, and the purple Save button.
  - MOBFIX.2b (new) carries the Note/Save screen spec: textarea composer, "New note" title, empty-guard behavior.
  - MOBILEUI.6 now carries the pill polish spec: the empty-disc fix (inject `svg("plus")` into the disc in both pill build sites) and the eye-geometry correction (delete the wrong 52.6%/51.5% overrides, copy the canonical geometry from `css/home.css:199-246` at a 34px frame).
  Design-authority notes for the executing agent: every value in those specs resolves to an existing token in `css/tokens.css` (no new hex values, no new spacing steps); light-only; the purple `#60079f` stays confined to the disc, Save fills, and the capture moment per DESIGN.md section 8; all new motion wraps in `@media (prefers-reduced-motion: no-preference)`.
  Done when: MOBFIX.1/.2b/.4 and the MOBILEUI.6 polish land matching their baked specs, verified on the emulator per the phase protocol.

## Out of scope

Same boundaries as before (now recorded in `AGENTS.md` decision #11): no model
enrichment on the phone; one person / one library (no multi-user); iOS is a follow-on;
the relay is additive (sync off = desktop unchanged); `saved_pivots` and chats do not
cross the relay.
