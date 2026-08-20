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

- [x] **CAP2.2 [AGENT]** DONE - human-verified on macOS 2026-08-20 (raven plays over the focused app, then dismisses). The earlier "steps 1-4" flight-overlay-window work had been LOST (the lib.rs half was never committed; only flight.html + the /flight route + the flight-overlay capability + flight_done.toml survived, all dangling). Rather than resurrect the dead overlay-window path, the chosen PIVOT is built: the raven now flies INSIDE the capture overlay, which already sits over the app the person captured from, then the overlay dismisses. `capture.html` plays a full-bleed `.capture-flight` raven (reused ANIM.4 keyframes) on every successful keep/paste/drop, hides the card during the flight, and calls `capture_dismiss` when it lands (reduced motion fades); no window resize, no always-on-top hacks. Removed the dead path entirely: `capture_done` (lib.rs + build.rs + the `allow-capture-done` capability + `capture_done.toml`), `flight_done`, `flight.html`, the `/flight` route, the `flight-overlay` capability + `flight_done.toml`, the main-window `capture-flight` listener in util.js, and flight.html from bin/verify's FILES. `cargo check` clean (0 warnings) and full `bin/verify` green (incl. Android build). REMAINING: the human macOS visual - capture via the global hotkey from another app (e.g. Chrome) and confirm the raven shows over that app, focus stays in the other app, and the overlay dismisses cleanly with no stuck window. The obsolete flight-overlay recipe below is kept only for history; do NOT rebuild it.
  Original task text (flight-overlay approach, now superseded by the pivot above):
  The capture-success raven must play over whatever app is
  focused, not only inside Enqueue. Today `capture_done` (`desktop/src/lib.rs` ~line
  1455) tells the `main` window to play the full-screen flight (CAP.3), but the main
  Enqueue window sits behind whatever app the person was in (e.g. Chrome) when they hit
  the global capture hotkey - so the raven plays on a window they cannot see. Build a
  dedicated flight overlay: a separate borderless, transparent, always-on-top,
  click-through (ignore-cursor-events) full-screen Tauri window that renders the raven
  flight over everything and closes itself when the animation ends. Fire it from
  `capture_done`. It must NOT steal focus (the person stays in their previous app) and
  must NOT intercept clicks. Reduced-motion still applies (a fade instead of the flight).
  Done when: with a different app (e.g. Chrome) focused, a global-hotkey capture shows
  the raven over that app without taking focus or blocking clicks, and it disappears on
  its own; capturing while Enqueue itself is focused still works; the overlay never
  lingers or leaves a stuck window.
  WHY THE CURRENT APPROACH FAILS (this is the whole bug): the flight renders in the
  `main` window (`capture_done` emits `capture-flight` -> `home.js`). The main window
  belongs to a BACKGROUND app (Enqueue is not frontmost after a global-hotkey capture
  from Chrome), and on macOS a background app's normal-level window sits BEHIND the
  frontmost app's windows. `always_on_top` alone does NOT fix this: Tauri's
  `always_on_top(true)` sets `NSFloatingWindowLevel` (3), which is not reliably above the
  active app, and Tauri's `.show()`/`.set_focus()` path calls `makeKeyAndOrderFront`,
  which ACTIVATES Enqueue (steals focus). So you either see nothing (behind Chrome) or
  you get yanked out of Chrome. The fix is a dedicated overlay whose NSWindow level is
  raised above the active app AND that is ordered front WITHOUT activating. This needs
  AppKit, extending the existing `#[cfg(target_os = "macos")] mod appkit` in
  `desktop/src/lib.rs` (it already has the `objc_msgSend`/`sel_registerName` machinery
  and an `activate()`/`hide_app()` pair - the flight must do the OPPOSITE of `activate`).

  IMPLEMENTATION STATUS (agent turn): steps 1-4 are DONE and compile-verified.
  `cargo check` (desktop, `--cfg desktop` active) is clean with zero warnings;
  `bin/verify` is green (JS parse of `flight.html` included, plus pytest, contrast, and the
  Android compile); `black`/`ruff` are clean on every edited file.
  Step 5 - the no-focus-steal / click-through / over-app / auto-close runtime behaviour -
  is human-only: there is no macOS display here, so a real Tauri window cannot be driven
  and judged. Per the "never ship unverified native-only Rust" rule, the native overlay (in
  `desktop/src/lib.rs`) is compile-checked but its runtime is left for human verification.
  The `CAP2.2` task box therefore stays unchecked.
  Files touched: `src/enqueue/static/flight.html` (new), `src/enqueue/api/static.py`,
  `desktop/tauri.conf.json`, `desktop/build.rs`,
  `desktop/permissions/autogenerated/flight_done.toml` (auto-generated by tauri-build),
  `desktop/src/lib.rs` (appkit fixups + `flight_done` / `open_flight_overlay` /
  `capture_done` rework + `flight_done` registered in `generate_handler!`), `bin/verify`
  (parses `flight.html`).
  The recipe below is unchanged; step 5 remains the human-only acceptance gate.

  IMPLEMENTATION (do it in this order; step 5 is the part only a human at the desktop
  can judge):
  1. Flight content surface `src/enqueue/static/flight.html`: a standalone page, FULLY
     transparent `html`/`body` background, that plays ONLY the ANIM.4 raven flight and
     nothing else. Reuse the existing asset `static/capture-bird.png` and the
     `.capture-flight` keyframes (today in `util.js captureFlight()` / `css/base.css`) -
     lift them into this page. On load, start the flight immediately; on `animationend`
     (or after the reduced-motion fade) call a new Tauri command `flight_done` (or
     `getCurrentWindow().close()`) to close the overlay. Add a JS safety timer (~2.5s)
     that closes it even if `animationend` never fires (a hidden/paused tab never fires
     it). `@media (prefers-reduced-motion: reduce)` -> a fade, not the flight.
  2. Register a `flight` window in `tauri.conf.json` loading `flight.html` (an app URL,
     no remote). Add a small capability (mirror `capture-overlay`) allowing `flight_done`
     - window close for the `flight` window. App-wide `transparent` already works via the
     existing `"macOSPrivateApi": true`.
  3. In `capture_done` (`desktop/src/lib.rs`), instead of emitting `capture-flight` to
     `main`, create+show the flight overlay. Builder flags: `.decorations(false)`,
     `.transparent(true)`, `.shadow(false)`, `.skip_taskbar(true)`, `.always_on_top(true)`,
     `.focused(false)`, `.resizable(false)`, `.closable(false)`. Size+position it to cover
     the CURRENT monitor (the one under the cursor; fall back to primary): set
     `.inner_size(w,h)` and `.position(x,y)` to that monitor's full frame. Do NOT use
     `.fullscreen(true)` - macOS native fullscreen opens a NEW Space and switches to it.
  4. AppKit fixups AFTER the window exists (the part `always_on_top` cannot do). Get the
     handle `let ns = window.ns_window()? as *mut c_void;` (cfg macos) and, via the
     `appkit` module's `objc_msgSend`/`sel_registerName`:
       - Raise above the active app: `[ns setLevel: 1000]` (NSScreenSaverWindowLevel;
         `objc_msgSend(ns, sel("setLevel:"), 1000 as c_int)`). NSStatusWindowLevel (25)
         is the minimum, 1000 is safest to clear fullscreen apps.
       - Appear on the current Space incl. other apps' fullscreen, without activating:
         `[ns setCollectionBehavior: 273]` where 273 = CanJoinAllSpaces(1) |
         Stationary(16) | FullScreenAuxiliary(256) (`objc_msgSend(ns, sel(
         "setCollectionBehavior:"), 273 as usize)`).
       - Click-through: Tauri `window.set_ignore_cursor_events(true)?` (or
         `[ns setIgnoresMouseEvents: YES]`).
       - Show WITHOUT activating - THE key to no-focus-steal: do NOT call Tauri `.show()`
         / `.set_focus()` and do NOT call `appkit::activate()`. Instead
         `[ns orderFrontRegardless]` (`objc_msgSend(ns, sel("orderFrontRegardless:"...` -
         note it takes no args: `objc_msgSend(ns, sel_registerName(
         b"orderFrontRegardless\0"...))`). This orders the window front while Chrome stays
         key.
  5. RUNTIME VERIFICATION (must be on the real macOS desktop, another app focused - this
     is why it is not agent-verifiable): focus Chrome, trigger a capture via the GLOBAL
     HOTKEY (not from the Enqueue window), then confirm ALL of: the raven flies over
     Chrome; Chrome stays key (type into Chrome mid-flight -> keys land in Chrome); a
     click during the flight goes THROUGH to Chrome; the overlay closes itself and leaves
     no stuck/black window; a second capture works (no leaked window); and capturing while
     Enqueue itself is focused still shows the flight. Multi-monitor: it appears on the
     monitor with the cursor.
  Done when: all of step 5 passes on the real desktop, and `bin/verify` is green
  (including the Android compile check, which now runs by default).

  PIVOT (2026-08-18, from live testing + user direction) - PREFER THIS over the
  floating-overlay above. The separate always-on-top overlay only shows when Enqueue is
  frontmost (the macOS window-level fight is unreliable). But the QUICK-CAPTURE OVERLAY
  window is ALREADY summoned over whatever app the person is in (that is how the global
  hotkey works - `open_capture` in `desktop/src/lib.rs` raises it above the frontmost app).
  So play the raven flight INSIDE the capture overlay and DELAY its dismissal, instead of
  firing a separate window: on a successful Keep, do NOT dismiss the capture window
  immediately - play the flight in the capture overlay (capture.html), hold ~1-1.5s, THEN
  dismiss. Because the capture window already sits over the person's previous app, the
  animation shows there with no separate always-on-top window and no focus/level hacks.
  The current flight is small in the 600x264 overlay ("barely see it") - so for the flight
  moment, briefly grow the capture window (or use a full-bleed flight layer inside it) so
  the raven reads, then dismiss. This supersedes the flight-overlay window (steps 1-4): the
  `flight` window / `flight_done` can be removed once this lands.
  Done when (pivot): capturing via the global hotkey from another app (e.g. Chrome) plays a
  visible raven flight over that app - because it plays in the capture overlay before it
  dismisses - then the overlay goes away and the person is back in their app; no separate
  always-on-top window is needed; reduced-motion still fades. Human device-verify (this is
  the macOS-display escalation #2 in the VERIFICATION PROTOCOL - everything buildable the
  agent verifies first: cargo build clean, bin/verify green, dead-code greps zero).

## Phase MOBBOOT - cold-launch bootstrap race

- [~] **MOBBOOT.1 [AGENT]** bootstrap() retry logic implemented (waitForInvokeAndStatus polls for invoke + retries mobile_status on rejection). Only shows setup when mobile_status resolves configured:false. Code committed + looks correct. DEVICE-VERIFY BLOCKED by Phase RELEASE, not failing: on the debug apk a cold launch loads the dev-server URL and shows a "Failed to request .../mobile.html" error page, so mobile.html never loads and bootstrap never runs (the `__TAURI__` bridge still answers, but the DOM is the error page). Re-verify this on a RELEASE build that loads the embedded frontend. Prior finding (the race being fixed): shows the SETUP screen even when the phone is configured with 73 synced notes. Found during MOBRENDER.1 device-verify: after a cold launch the library was stuck on "Scan the linking QR", but CDP showed `mobile_status` = configured:true and calling `bootstrap()` again immediately rendered the library (4 shelves). So the data is fine; bootstrap just decided "setup" too early and never retried.
  Root cause in `src/enqueue/static/mobile.html` `function bootstrap()` (~line 2435): two paths fall through to `show("setup")` when the Tauri runtime is not ready yet, conflating "runtime/invoke not ready" with "genuinely not configured":
  1. `if (!invoke) { show("setup"); startCamera(); return; }` - if `window.__TAURI__` (and thus `invoke`) is not injected yet at the `bootstrap()` call on line ~2871, it gives up and shows setup.
  2. `invoke("mobile_status").then(...).catch(() => { show("setup"); startCamera(); })` - if the very first `mobile_status` call rejects because the runtime is still coming up, the catch shows setup.
  Fix: only show setup when `mobile_status` SUCCESSFULLY resolves `configured:false`. On a missing `invoke` or a rejected call, RETRY (e.g. a short backoff / poll for `window.__TAURI__` before the first call, and retry mobile_status a few times on rejection) instead of assuming unconfigured. Do NOT start the camera on a runtime-not-ready path.
  Done when: a cold launch on a configured phone lands directly on the library (never a flash of setup), and an unconfigured phone still shows setup. VERIFY headlessly: force-stop + launch, then CDP `bootstrap`-free - the visible section must be `library` within a couple seconds of load (poll the same `#setup`/`#library` hidden check used in the MOBRENDER.1 verify), with zero manual `bootstrap()` calls.

## Phase SCANUI - contain the scanner camera in a box

- [~] **SCANUI.1 [AGENT]** Reverted to working full-screen scanner (transparent window + body.scanning { background: transparent }). Camera streams, scans QR. Pending human device-verify (aesthetics). The native scanner (QR.4a) works but the camera fills the WHOLE
  screen. The camera is CameraX rendered BEHIND a transparent WebView (window is
  `.transparent(true)`, and `body.scanning { background: transparent }` makes the whole page
  see-through), so the camera shows everywhere the page is transparent. Goal: show the
  camera only inside a centered rounded box, with the surrounding area opaque (a normal
  scanning chrome: a title, the box with a frame, a Cancel button).
  What was already tried and did NOT contain it (verified live 2026-08-18): giving the
  `#scan_overlay .frame` a fully-opaque `box-shadow: 0 0 0 4000px rgba(0,0,0,1)` while the
  body stayed transparent - the camera still filled the screen. So the box-shadow-cutout
  approach is insufficient here. Next approaches to try (on-device, since the camera layer
  does not appear in `adb screencap` - a HUMAN must look):
  (a) Keep the body OPAQUE during scan (do not make the whole page transparent); make ONLY
      a single centered box element transparent (its ancestors must ALL be transparent down
      to that box for the camera to show through just there), everything else opaque.
  (b) Build the surround from explicit opaque panels (top/bottom/left/right rectangles)
      around a transparent central box, rather than relying on box-shadow.
  (c) Confirm whether the plugin exposes any windowed/preview option; if it only supports a
      full-surface preview, (a)/(b) are the only levers. DO (c) FIRST, at the desk: read
      the vendored plugin source (`desktop/plugins/tauri-plugin-barcode-scanner/`) - the
      team's fork already added a `boxSize` option to `setupCamera()`, so check whether
      that path is live before rebuilding anything.
  Done when: on the phone, tapping "Scan QR" shows the camera INSIDE a centered box with an
  opaque surround (title + frame + Cancel), a QR still scans + links, and no camera bleeds
  outside the box. Verification is split per the VERIFICATION PROTOCOL (top of this file):
  the AGENT verifies programmatically - camera client active (`adb shell dumpsys
  media.camera | grep com.sudohnim.enqueue`), chrome/box geometry present around the
  center region (`uiautomator dump`), Cancel returns to setup and releases the camera,
  and a real desktop QR still scans + links. The HUMAN does only the final one-glance
  aesthetic check, because the camera surface itself does not appear in screencaps.
  VERIFY: `cargo tauri android build --debug --target aarch64` zero errors + `bin/verify`
  green; then the agent-side dumpsys/uiautomator/scan checks above, pasted into
  PROGRESS.md; then the single human glance.

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

- [~] **BACKFILL.1 [AGENT]** CLI `enq sync-push-all` + API POST /settings/sync/push-all added. push_all() fixed to call load_dek_from_keychain() for background threads. Full library already synced: 74/74 non-deleted non-local artifacts on Railway (409s). Headless verify: curl shows 90 objects (74 artifacts + blobs), re-run is no-op. Pending human device-verify (fresh phone pulls full library).
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

- [~] **RELEASE.1 [AGENT+HUMAN]** Build config FIXED + green 2026-08-19 (an earlier agent pass left it non-building). Corrections: `devUrl` was set to `""` which crashed tauri-build ("relative URL without a base") - REMOVED it so Tauri embeds `frontendDist` (this IS the devUrl fix - a build now loads `tauri.localhost`, not the dev-server error page); `"apk"`/`"aab"` were added to `bundle.targets` where they are invalid enum values ("data did not match any variant of BundleTargetInner") - REMOVED (Android artifacts come from `cargo tauri android build`, not `bundle.targets`); the `bundle.android.signingConfig` block in tauri.conf.json is NOT a real Tauri v2 field and signed nothing - REMOVED and replaced with real signing in `desktop/gen/android/app/build.gradle.kts` (a `signingConfigs.release` that reads `key.properties` in `gen/android/`, falling back to env vars `RELEASE_STORE_PASSWORD`/`RELEASE_KEY_PASSWORD`/`RELEASE_KEY_ALIAS`/`RELEASE_KEYSTORE`, guarded by `hasReleaseSigning` so debug builds stay unsigned when no keystore exists). `.gitignore` now excludes `*.keystore`/`*.jks`/`key.properties`; a committed `desktop/gen/android/key.properties.example` documents the format. `bin/verify` is GREEN (Android build compiles the new gradle, signing skips cleanly with no keystore). REMAINING (human, one-time): create the keystore and fill the passwords, then build the signed release:
  `keytool -genkey -v -keystore desktop/gen/android/release.keystore -alias enqueue -keyalg RSA -keysize 2048 -validity 10000`
  then copy `key.properties.example` -> `key.properties` and fill the passwords (or export the `RELEASE_*` env vars), then `cd desktop && cargo tauri android build --target aarch64` for a signed release apk/aab.
  NOTE: the `devUrl` removal also unblocks the DEBUG apk (it now loads the embedded frontend too), so MOBBOOT.1 and the bidirectional-capture device-verifies no longer need the signed release build - a plain `cargo tauri android build --debug` is enough to verify them. The signed release is still needed for a distributable, installable-anywhere build.
  Done when: an installed apk, phone unplugged and no `cargo tauri android dev` running, cold-launches into the Enqueue UI (not the error page); the webview CDP target URL is `tauri.localhost`, not a LAN dev URL.
  Figure out why the debug apk carries `devUrl` (the built `assets/tauri.conf.json` inside the
  apk has `"devUrl":"http://<lan-ip>:1430/"` even though `cargo tauri android build` is meant
  to embed `frontendDist`) and make a build that never points at the dev server: either a
  proper release build (`cargo tauri android build` without `--debug`) or a debug build with
  the dev URL stripped.
  A release build needs Android signing set up (a keystore + `signingConfig` in the gradle /
  `tauri.conf.json` bundle config); document the keystore steps for the human (the human
  creates/holds the keystore; the agent wires the config and the build command).
  Then install that apk and confirm it cold-launches straight into the app (the embedded
  `tauri.localhost/mobile.html`), unplugged, with no dev server running.
  Done when: an installed apk, phone unplugged and no `cargo tauri android dev` running,
  cold-launches into the Enqueue UI (not the error page); this unblocks the MOBBOOT.1 and
  bidirectional-capture device-verifies.
  VERIFY: install the apk, force-stop, launch, `adb exec-out screencap` shows the app UI (not
  "Failed to request"); the webview CDP target URL is `tauri.localhost`, not the LAN dev URL.

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

- [~] **EMULATOR.1 [AGENT+HUMAN]** bin/launch emulator implemented: boots AVD headless, waits for boot_completed, installs debug apk via cargo tauri android dev. CDP verified (WebView at port 9222, Runtime.evaluate works). Emulator reaches local relay at 10.0.2.2:8788. Human creates AVD once (sdkmanager/avdmanager). bin/verify green.
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

- [~] **DESKTOPUI.1 [AGENT]** Sync tab shows ONLY QR code and reset control. Removed Relay URL, Sync secret, This device fields. Renamed shelf to "Link a device". bin/verify green.
  In `src/enqueue/static/js/settings.js`, the configured Sync tab currently shows hand-edit relay/secret fields.
  Remove exactly these blocks and their save wiring: the `s_sync_relay_url` label+input (~line 703) and its `sync_relay_url` PATCH (~line 871), and the `s_sync_secret` label+password-input (~line 823) plus the code that reads `s_sync_secret` (~line 853).
  Keep untouched: the QR rendering path (`desktop_link_code`, ~line 951) and the reset-sync control.
  The tab should present only the linking QR (the passwordless flow - config is not hand-entered any more) and the reset-sync control.
  Done when: the Sync tab shows the QR and reset, nothing else; linking + reset still work; `bin/verify` green.

- [~] **DESKTOPUI.2 [AGENT]** QR and reset live in TWO SEPARATE boxes. QR in its own card, reset sync in its own card, visually separated. bin/verify green.
  They are two different actions (link a device vs wipe the key), so give each its own bordered card/section rather than one combined block.
  Depends on DESKTOPUI.1. Done when: the QR is in one box, the reset in a distinct box, visually separated.

- [~] **DESKTOPUI.3 [AGENT]** Chat loading copy updated: "Reading what you saved..." -> "Processing your message". bin/verify green.
  The string is at `src/enqueue/static/js/chat.js:158`, inside a `spinner("sm", ...)` call.
  Change only the string; grep afterwards to confirm zero remaining occurrences.
  Done when: asking a question shows "Processing your message" while it works; `bin/verify` green.

- [~] **DESKTOPUI.4 [AGENT]** Rebuild concepts button: real button + live progress. Changed to btn secondary with id, disables during rebuild, shows progress text, re-enables on done/error. bin/verify green.
  Current state (verified 2026-08-20): `src/enqueue/static/js/settings.js:385` already renders `<button class="btn tertiary" onclick="rebuildFacets()">Rebuild concepts</button>`, wired to `rebuildFacets()` (~line 396) which POSTs `/facets` with redo and writes status into `#facetRebuildState`.
  So do NOT add a new control.
  The remaining work: the `btn tertiary` styling makes it not read as a button, and the feedback is thin.
  Restyle it to the primary/secondary button idiom so it is obviously clickable, and strengthen the in-progress/done feedback in `#facetRebuildState` (disable the button + show "Rebuilding..." while the POST runs, then a clear done/failure message).
  Done when: the control is visually unmistakable as a button, clicking it runs the rebuild, and the state text goes in-progress -> done (or error) without a page reload; `bin/verify` green.

- [~] **DESKTOPUI.5 [AGENT]** AI settings split into small per-section boxes. Connection, API Key, Custom Headers, Behavior each in their own card with margins. bin/verify green.
  The AI/"Connection" section is built in `src/enqueue/static/js/settings.js` ~lines 243-330: the backend select (`s_backend`, ~249), the model field (`llm_model`, ~280-291), the endpoint field (`llm_url`, ~304-308, shown only for `custom`), and the API-key block (~315-323).
  Split these into small bordered boxes, one per logical group (backend, model, API key, URL), reusing the existing settings card/box CSS class used elsewhere on the page for consistency.
  Use the `impeccable` skill (layout) for the grouping + spacing. Done when: each AI setting group is its own small box, no single giant blob; `bin/verify` green.

- [~] **DESKTOPUI.6 [AGENT]** Desktop gear icon fixed. Replaced sun-like rays with proper gear teeth in icons.js. Mobile pill uses same svg("gear") so both surfaces match. bin/verify green.
  Root cause pinned: `src/enqueue/static/js/icons.js:27` defines `gear:` as a circle plus eight straight rays (`M12 2v3 M12 19v3 M22 12h-3 ...`) - that is literally a sun glyph.
  Replace its path data with a real gear outline; copy the gear SVG the mobile app uses (grep `src/enqueue/static/mobile.html` for the settings/gear icon in the pill) so the two surfaces match exactly.
  Keep the same viewBox/stroke convention as the other entries in `icons.js`.
  Done when: the desktop settings icon is a recognizable gear consistent with mobile; `bin/verify` green.

- [~] **CHATBUG.1 [AGENT]** FIXED + verified end-to-end 2026-08-20 against the real backend (opencode-go `deepseek-v4-pro`). Two real bugs, both ruled out the red herrings first:
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

- [ ] **MOBILEUI.2 [AGENT]** "Syncing..." indicator never actually completes/clears.
  The user reports the "Syncing..." state was never really working.
  Trace the QR.5a event path (`sync-started`/`sync-done`/`sync-error` from `mobile_sync` -> the mobile.html listeners) and confirm the indicator appears on start and CLEARS on done; fix wherever it sticks.
  Verify headlessly per the VERIFICATION PROTOCOL (CDP: listen for the events, assert the indicator element toggles).
  Done when: a sync shows "Syncing..." then clears to the library on completion, on a real device/emulator.

- [ ] **MOBILEUI.3 [AGENT]** Notes should render as SQUARES (like the desktop app), not horizontal bars.
  The mobile library currently lists notes as full-width horizontal rows; change them to square cards matching the desktop app's card idiom.
  The desktop card styles to mirror live in `src/enqueue/static/css/home.css` (card + `.pivotcard` rules, ~line 481 on) - match that feel, do not invent a new card language.
  Use the `impeccable` skill's `shape` flow to work out the card layout/grid before building.
  Done when: the mobile library shows square note cards in a grid, responsive, matching the desktop card feel.

- [ ] **MOBILEUI.4 [AGENT]** Add color to the mobile main screen.
  The main screen is monochrome; add strategic color.
  The brand palette source is `src/enqueue/static/css/tokens.css` (e.g. `--purple-bold`, already used for the mobile capture action) - pull colors from those tokens, do not invent new hex values.
  Use the `impeccable` skill's `colorize` flow.
  Done when: the main screen has deliberate, on-brand color (not a rainbow), passing contrast (`bin/check-contrast` stays green).

- [ ] **MOBILEUI.5 [AGENT]** Mobile Settings: a READ-ONLY AI section (the Trash half is DONE).
  (a) Trash: already shipped (MOBUI1.1 in PROGRESS.md) - Settings > Trash lists trashed notes with working Restore, backed by `mobile_list_trashed` / `mobile_restore_trashed` (`desktop/src/lib.rs:1285,1293`).
  Do not rebuild it; only restyle if MOBILEUI.8's design pass touches Settings.
  (b) AI section, READ-ONLY: display the AI configuration the phone already holds, no editing.
  The sync channel is ALREADY BUILT - do not design a new one: the QR link payload carries the desktop's `llm_backend` / `llm_model` / `llm_api_key` / `llm_url` into the phone's `sync_config` (`save_config`, `desktop/src/lib.rs:125-153`), and the mobile settings command (~line 858) already exposes them to the webview.
  The work is UI-only: render a read-only "AI" box in mobile Settings showing backend / model / URL (mask the API key - show presence + hint, never the value), with a note that AI config is managed on the desktop.
  Caveat to handle: values only refresh on a fresh QR link - if the desktop AI config changed after linking, the phone shows the linked snapshot; display a "as of linking" label rather than building a live sync.
  Done when: mobile Settings shows a read-only AI section reflecting the desktop's config as of the last link, with no edit affordances; verified on the emulator via CDP + screencap.

- [ ] **MOBILEUI.6 [AGENT]** Bottom pill: exactly THREE icons - plus, eye, gear.
  Replace the current pill (capture / `pill_search` / eye / menu) with three actions: `+` (add artifact, opens MOBILEUI.7's menu), an eye (ask a question), a gear (settings).
  Fate of evicted items, pinned so there is no design decision left: SEARCH stays as the library screen's own search field (the `#search` input + `mobile_search` wiring stay - only the pill's search button goes); CAPTURE moves into the `+` menu (MOBILEUI.7); MENU's contents move to the gear/settings screen.
  Done when: the bottom pill shows only those three icons, each wired to its action, and looks clean (not the current weird layout).

- [ ] **MOBILEUI.7 [AGENT]** Add-artifact flow: dim the background + a type submenu.
  Tapping `+` (depends on MOBILEUI.6) dims the background and shows a submenu with four choices:
  - "Note" - a plain text note; saves via the existing `mobile_capture` command.
  - "Upload" - opens the mobile file system to upload artifacts (the existing file-picker path already in `mobile.html` - find and reuse it, do not build a second picker).
  - "Camera" - opens the camera capture path (`mobile_capture_image`).
  - "Link" - two fields: one for the URL, one for optional notes/annotation. `mobile_capture` (`desktop/src/lib.rs:303-318`) already auto-detects a URL inside the submitted text and kinds it as a link - reuse that command (submit the URL + notes text together); add a dedicated Rust command ONLY if the auto-detect path cannot carry the annotation.
  Done when: `+` dims the background and offers Note/Upload/Camera/Link, each opening the right input and saving the artifact; verified on the emulator per the protocol at the top of this phase (Camera checked via `dumpsys` for the Activity opening).

- [ ] **MOBILEUI.8 [AGENT]** Build MOBILEUI.3/.6/.7 with the design skills.
  Run the `impeccable` skill's `shape`, `layout`, and `delight` flows to design the square cards, the three-icon pill, and the add-artifact submenu before/while building, so the mobile UI reaches the same craft bar as the desktop.
  Done when: the above land as designed, responsive, with tasteful motion, verified on a real device/emulator.

## Out of scope

Same boundaries as before (now recorded in `AGENTS.md` decision #11): no model
enrichment on the phone; one person / one library (no multi-user); iOS is a follow-on;
the relay is additive (sync off = desktop unchanged); `saved_pivots` and chats do not
cross the relay.
