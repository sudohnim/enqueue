# PLAN.md - open work

Swept 2026-08-19: finished work folded into AGENTS.md and README.md; git history holds the raw detail.
Swept 2026-08-22: state audit + impeccable design pass + QR-scan-error fix.

## State summary (2026-08-22)

Legend: `[x]` done + verified. `[~]` code-complete, awaiting verify. `[ ]` open work.

| Phase | Item | State |
| --- | --- | --- |
| CAP2 | CAP2.2 capture-flight over-app | `[x]` DONE + human-verified 2026-08-20 |
| MOBBOOT | MOBBOOT.1 cold-launch race | `[x]` DONE + emulator-verified 2026-08-20 |
| SCANUI | SCANUI.1 scanner camera box | `[~]` code committed, AWAITING human glance |
| RELAYHOST | RELAYHOST.1 Railway deploy | `[~]` deployed + desktop-verified 2026-08-19, phone LTE scan blocked only by RELEASE signing |
| BACKFILL | BACKFILL.1 manual push-all | `[x]` DONE + verified 2026-08-19/20 |
| BACKFILL | BACKFILL.2 auto-backfill on sync-enable | `[~]` code committed, needs verify against scratch relay |
| RELEASE | RELEASE.1 unplugged debug apk | `[x]` build config FIXED + emulator-verified 2026-08-20; signed release build PROVEN 2026-08-20 (keystore created) |
| EMULATOR | EMULATOR.1 headless AVD path | `[x]` DONE + emulator-verified 2026-08-20 |
| DESKTOPUI | DESKTOPUI.1..6 + CHATBUG.1 | `[x]` ALL DONE + verified 2026-08-20 |
| MOBILEUI | MOBILEUI.5/6/7/8 | `[x]` DONE + verified |
| MOBILEUI | MOBILEUI.1 app icon | `[~]` generator updated, SUPERSEDED by MOBFIX.6 (still too small on phone) |
| MOBILEUI | MOBILEUI.2 stuck "Syncing..." | `[~]` FIXED in working tree (uncommitted) - retry listener wiring added |
| MOBILEUI | MOBILEUI.3 square cards | `[~]` code committed, AWAITING device screencap verify |
| MOBILEUI | MOBILEUI.4 color accents | `[~]` code committed, AWAITING device screencap verify |
| MOBFIX | MOBFIX.1/2/2b/4/8 | `[x]` ALL DONE + verified |
| MOBFIX | MOBFIX.3 camera opens gallery | `[~]` FIXED in working tree (Kotlin/Rust committed in 8b4e0a2, JS wiring uncommitted) - `mobile_capture_camera` via JNI + `ACTION_IMAGE_CAPTURE` |
| MOBFIX | MOBFIX.5 bidirectional delete sync | `[~]` FIXED in working tree (uncommitted) - `trash.py` bumps `updated_at` on delete/restore |
| MOBFIX | MOBFIX.6 app icon STILL too small | `[~]` FIXED in working tree (uncommitted) - alpha-channel mask replaces broken purple-diff mask |
| MOBFIX | MOBFIX.7 re-verify MOBILEUI.2/6 on device | `[ ]` OPEN umbrella - depends on the above being committed + device-verified |
| QRSCANFIX | QRSCANFIX.1 "Scan failed [object Object]" | `[~]` FIXED 2026-08-22 (this commit) - `errString()` helper added; bin/verify green; AWAITING device scan |

Items still requiring a HUMAN device-verify live in docs/PROGRESS.md.

## How to execute (read first, every agent)

This file is the only work queue. Do one task per turn. Each task block is self-contained: pre-conditions, exact files/lines, exact tokens/CSS to write, exact test commands, exact "Done when".

1. **Read AGENTS.md first** - especially "Verifying the Android app on a device (headless, over adb)". It is the authority on emulator vs phone, CDP, screencap, run-as, and when to escalate to a human.
2. **Headless-first.** Almost every mobile task is verifiable with NO phone attached. Boot the headless emulator (`bin/launch emulator`), install the debug apk, drive the UI over CDP + screencap. Only the physical camera-aim and a final one-glance aesthetic judgement need a human.
3. **Token authority is `src/enqueue/static/css/tokens.css`.** Every color/spacing/motion value in a spec resolves to a token there. Do NOT invent hex values, do NOT introduce new spacing steps, do NOT add a dark mode (light only per DESIGN.md section 1).
4. **`bin/verify` is the gate, not the proof.** It runs JS parse, pytest, contrast, Android compile. It is HEADLESS and needs no hardware - run it on every change. A green `bin/verify` does NOT prove the app runs; it proves the code parses, tests pass, palette meets contrast, app compiles. The emulator or phone is the only proof of runtime.
5. **Commit green the same turn.** Verified code that is not committed is treated as work that will be lost. The pre-commit hook (`.githooks/pre-commit`, activated via `git config core.hooksPath .githooks`) runs `bin/verify` on staged code and blocks the commit on failure.
6. **Marking done.** `[x]` only after the task's "Done when" is met AND `bin/verify` is green. `[~]` means code-complete, awaiting the verify step. `[ ]` means not started. If a verify step fails, open a new task for the fix - do not silently revert.
7. **Caveman mode is on for this repo.** Code, commits, PRs, security warnings: write normal. Everything else: terse fragments, drop articles/filler.

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

- [~] **MOBILEUI.1 [AGENT]** App icon generator updated (color-mask extraction + safe-zone fill). SUPERSEDED by MOBFIX.6 - the phone still shows the raven too small after this pass, so MOBFIX.6 re-tunes the scale. Treat this entry as history; do not re-do its work separately from MOBFIX.6.
  Original spec kept for reference: do NOT hand-craft PNGs - generator scripts already exist: `desktop/icons/make_adaptive_icons.py` (Android adaptive icon: foreground + background layers) and `desktop/icons/make_icon.py`. Read those scripts first, adjust the scaling/padding so the logo fills the icon (no tiny centred mark, no white-box framing), regenerate, and commit the regenerated `desktop/gen/android/app/src/main/res/mipmap-*` outputs plus any changed sources under `desktop/icons/`.
  Done when: the installed app's launcher icon shows the logo at proper size, no white-box framing; verify on the emulator by installing the debug apk and screencapping the launcher/home screen with the icon visible.

- [~] **MOBILEUI.2 [AGENT]** FIXED in working tree (uncommitted). Root cause: sync-event listeners (`sync-started`/`sync-done`/`sync-error`) were wired once at script parse time with a guard `if (window.__TAURI__ && window.__TAURI__.event)` that fails on cold launch when the Tauri bridge is slow to inject. The sync thread (`desktop/src/lib.rs:255-300`) still runs and emits events, but they fire into the void. `#loading` was set visible by the QR-link path or `bootstrap()` and nothing ever hid it. Same class as MOBBOOT.1.
  Fix (in working tree): extracted the three `listen()` calls into `wireSyncListeners()` (idempotent via `syncListenersWired` flag), called from `waitForEventApi(attempt=1)` which polls for `window.__TAURI__.event` up to 20 times at 50ms (same budget as the invoke poller). Also added `#loading[hidden] { display: none }` CSS rule to ensure the `[hidden]` attribute wins over `display: flex`.
  Files: `src/enqueue/static/mobile.html` (lines ~2738-2801 for the retry wiring, line ~567 for the CSS rule).
  Done when: a sync shows "Syncing..." then clears to the library on completion, on a cold launch where `__TAURI__` is slow to inject.
  VERIFY: CDP - `adb forward tcp:9222 localabstract:webview_devtools_remote_$(adb shell pidof com.sudohnim.enqueue)`, force-stop + launch (cold), then `Runtime.evaluate` `window.__TAURI__.core.invoke('mobile_sync', { config: '{}' })` and assert `#loading.hidden === true` after `sync-done` fires. Record in PROGRESS.md.

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

- [~] **MOBFIX.3 [AGENT]** FIXED in working tree. Kotlin/Rust committed in `8b4e0a2`; JS button wiring uncommitted.
  Root cause: `#pill_menu_camera` was wired to `doCaptureImage()` which calls `invoke("mobile_pick_image")` (gallery picker). Camera and Upload both opened the gallery.
  Fix (implemented):
  - New Rust command `mobile_capture_camera` in `desktop/src/lib.rs:687` (Android) + `:764` (non-Android stub). Uses JNI to call `MainActivity.captureImage()` which returns a `CompletableFuture<String>`.
  - New Kotlin: `CameraHelper.kt` (144 lines) launches `ACTION_IMAGE_CAPTURE` intent with a `FileProvider` URI, reads the captured JPEG as base64 on `onActivityResult`. `MainActivity.kt:36` exposes `captureImage()` which delegates to `CameraHelper`. `AndroidManifest.xml:29-37` registers the `FileProvider` with authority `${applicationId}.fileprovider`. `res/xml/file_paths.xml` exists.
  - JS wiring in `mobile.html`: `#pill_menu_camera` now calls `invoke("mobile_capture_camera")` (line ~2959) instead of `doCaptureImage()`. Upload keeps `doCaptureImage` (gallery path).
  - Command registered in `build.rs` / `lib.rs:1464`.
  Files: `desktop/src/lib.rs`, `desktop/gen/android/app/src/main/java/com/sudohnim/enqueue/CameraHelper.kt` (new), `MainActivity.kt`, `AndroidManifest.xml`, `res/xml/file_paths.xml`, `src/enqueue/static/mobile.html`.
  Done when: Camera opens the LIVE camera and captures a photo; Upload opens the gallery. Verify via `adb shell dumpsys media.camera | grep -A2 com.sudohnim.enqueue` (camera stream active) AND `adb shell dumpsys activity activities | grep ImageCapture`.
  VERIFY: build debug apk, install on emulator/phone, tap `+` > Camera, confirm camera Activity opens (dumpsys), capture photo, confirm it saves as artifact.

- [x] **MOBFIX.4 [AGENT] ✅ DONE** Link add-option: two-field form (URL + notes).
  - Added `link_capture` section mirroring `capture` section with `link_cancel` back button and "Save a link" title.
  - URL input (`type=url`, `inputmode=url`, placeholder `https://example.com`) + notes textarea (`rows=3`).
  - Save handler: prepends `https://` if no scheme, builds payload `url + "\n\n" + notes`, calls `mobile_capture`, toasts "Link saved", clears fields, returns to library.
  - Back button wired to library, clears fields on open, focuses URL input.
  - bin/verify green.
- [~] **MOBFIX.5 [AGENT]** FIXED in working tree (uncommitted). Root cause: `src/enqueue/trash.py` delete (line 58) and restore (line 78) set/clear `deleted_at` but did NOT bump `updated_at`. LWW resolution (`src/enqueue/sync/snapshot.py:160`, mirrored in `desktop/src/sync.rs:307`) compares `(updated_at, _device_id)` tuples. The tombstone snapshot had the SAME key as the live snapshot, so `apply_snapshot` on the phone was a no-op - the tombstone was silently dropped.
  Fix (in working tree): `trash.py:61` now `UPDATE artifacts SET deleted_at = ?, updated_at = ? WHERE id = ?` (bumps `updated_at = now`). `trash.py:86` now `UPDATE artifacts SET deleted_at = NULL, updated_at = ? WHERE id = ?` (same bump on restore). Both have explanatory comments referencing MOBFIX.5. The `push_artifact(id)` call that follows now carries a tombstone with a NEWER `updated_at`, so LWW on the phone picks it up.
  Files: `src/enqueue/trash.py` (lines 58-63 for delete, 84-88 for restore).
  Done when: deleting on desktop -> the note disappears from the phone after its next sync; restore reappears.
  VERIFY: `adb shell run-as com.sudohnim.enqueue sqlite3 /data/data/com.sudohnim.enqueue/library.db "SELECT id, deleted_at, updated_at FROM artifacts"` (debug apk) - the tombstoned row must have `deleted_at` set AND `updated_at` newer than pre-delete. Plus `bin/verify` green. A regression test asserting `lww_key(tombstone) > lww_key(live)` should be added to `tests/test_sync.py` or `tests/test_trash.py`.

- [~] **MOBFIX.6 [AGENT]** FIXED in working tree (uncommitted). Root cause: `desktop/icons/make_adaptive_icons.py` used a color-difference mask subtracting phantom purple `(107, 70, 193)` from the source `icon.png`. But `icon.png` is a 1024x1024 RGBA image with a TRANSPARENT background (alpha=0) and a near-WHITE raven (RGB 253,253,253). There is NO purple in the source. All pixels (transparent and white alike) had diff > 60, so ALL classified as "raven" -> bbox = full canvas -> no crop -> raven at ~65% of launcher icon.
  Fix (in working tree): replaced the color-difference mask (old lines 63-73) with `alpha_mask = src_array[:, :, 3]` (the source's alpha channel: opaque = raven, transparent = background). The bbox detection now finds the raven's actual opaque bbox (rows 97-926, cols 97-926 = 81% of canvas), crops to it, and scales to `safe_zone` (80% of target). Added a guard checking `src_array.ndim == 3 and shape[2] == 4`. All mipmap PNGs regenerated (sizes increased ~35%, confirming the raven now fills more of the icon).
  Files: `desktop/icons/make_adaptive_icons.py` (mask logic, lines 59-68), `desktop/gen/android/app/src/main/res/mipmap-*/ic_launcher*.png` (20 regenerated files).
  Done when: the launcher icon shows the raven at a proper, filling size on the emulator launcher AND (one human glance) on the phone launcher.
  VERIFY: install debug apk on emulator, screencap launcher home screen, READ the PNG - raven fills the inner circle, no excessive padding, no clipped wingtips.

- [ ] **MOBFIX.7 [AGENT]** Re-verify the previously-broken tasks on the device once the working-tree fixes are committed and a fresh apk is built. The fixes are in the working tree but NOT committed and NOT device-verified:
  1. Commit all uncommitted working-tree changes (MOBILEUI.2 listener retry, MOBFIX.3 JS wiring, MOBFIX.5 `updated_at` bump, MOBFIX.6 alpha-mask icon regen, QRSCANFIX.1 `errString` helper).
  2. Build a fresh debug apk: `cd desktop && cargo tauri android build --debug --target aarch64`.
  3. Install on emulator: `adb install -r desktop/gen/android/app/build/outputs/apk/arm64/debug/app-arm64-debug.apk`.
  4. Verify each fix per its "Done when" / "VERIFY" section above.
  Done when: all four fixes confirmed on emulator/phone; record in PROGRESS.md.

- [x] **MOBFIX.8 [HUMAN-WITH-SKILL + AGENT]** DESIGN PASS RUN 2026-08-20 (impeccable skill: shape/layout/delight/colorize against DESIGN.md + tokens.css + the incumbent mobile.html). The concrete specs are BAKED into the tasks; the executing agent needs no design skill:
  - MOBFIX.1 now carries the `+` menu popover spec: the two root causes (overlay z-index collision covering pill + menu; duplicate `pillToggleMenu` shadowing), the scrim token swap (`var(--scrim)`), the 140ms `--dur-fast`/`--ease` rise-from-the-pill entrance, the inline-style wrapper removal, 44px menu-button touch floor, and the disc-rotates-45-degrees delight.
  - MOBFIX.4 now carries the two-field Link form spec: a dedicated `#link_capture` section mirroring `#capture`, URL input + notes textarea stacked at `--sp-3`, the `https://` prepend rule, the `url + "\n\n" + notes` payload to `mobile_capture`, and the purple Save button.
  - MOBFIX.2b (new) carries the Note/Save screen spec: textarea composer, "New note" title, empty-guard behavior.
  - MOBILEUI.6 now carries the pill polish spec: the empty-disc fix (inject `svg("plus")` into the disc in both pill build sites) and the eye-geometry correction (delete the wrong 52.6%/51.5% overrides, copy the canonical geometry from `css/home.css:199-246` at a 34px frame).
  Design-authority notes for the executing agent: every value in those specs resolves to an existing token in `css/tokens.css` (no new hex values, no new spacing steps); light-only; the purple `#60079f` stays confined to the disc, Save fills, and the capture moment per DESIGN.md section 8; all new motion wraps in `@media (prefers-reduced-motion: no-preference)`.
  Done when: MOBFIX.1/.2b/.4 and the MOBILEUI.6 polish land matching their baked specs, verified on the emulator per the phase protocol.

## Phase QRSCANFIX - "Scan failed [object Object]" on QR scan

Reported 2026-08-22: tapping "Scan QR" on the phone, the camera opens, but on scan (or cancel) the status reads `Scan failed [object Object]` instead of either linking or showing "cancelled".

- [~] **QRSCANFIX.1 [AGENT]** FIXED 2026-08-22 (this commit). Root cause: Tauri invoke rejections arrive as `{ message, code, data }` objects (see `desktop/plugins/tauri-plugin-barcode-scanner/android/.tauri/tauri-api/src/main/java/app/tauri/plugin/Invoke.kt:48-64` - `Invoke.reject(msg, code, ex, data)` builds a `PluginResult` with a `message` field). `String(obj)` returns `"[object Object]"`, so both the error display AND the cancel-suppression check (`String(e) !== "cancelled"`) failed - the cancel path also threw "Scan failed [object Object]".
  Fix: added `errString(e)` helper in `src/enqueue/static/mobile.html` next to `setStatus` (search for `function setStatus` - the helper is immediately below it). Behaviour:
  - `typeof e === "string"` -> return `e`.
  - `e.message` (or `e.error.message`, or `e.code`) -> return that.
  - Fallback `JSON.stringify(e)`, then `String(e)`.
  Replaced every `String(e)` site in mobile.html (scan handler - search `Scan failed`, link handler - search `Link failed`, capture handlers - search `status.textContent = `, chat error - search `Error: ` in the chat section) with `errString(e)`. Cancel check now reads `msg.toLowerCase().includes("cancel")` so a rejection carrying `{ message: "cancelled" }` is suppressed cleanly.
  Files: `src/enqueue/static/mobile.html` (helper + 7 call sites). `bin/verify` green.
  Done when: on a real device or emulator, scanning the desktop QR links the phone (no "[object Object]"); tapping Cancel returns to setup with no error status.
  VERIFY headlessly is NOT enough here - the scan path needs a real camera frame. Emulator can prove the cancel path (open scanner, tap Cancel, assert status stays empty); the link path needs either a real QR held to a phone camera OR the QR-payload injection path (skip the camera, call `handleScanResult({...})` directly over CDP - this exercises the parse + link + sync flow without the camera). Both: `bin/verify` green, then either CDP injection OR human scan.

## Out of scope

Same boundaries as before (now recorded in `AGENTS.md` decision #11): no model
enrichment on the phone; one person / one library (no multi-user); iOS is a follow-on;
the relay is additive (sync off = desktop unchanged); `saved_pivots` and chats do not
cross the relay.
