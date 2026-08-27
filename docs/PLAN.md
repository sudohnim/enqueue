# PLAN.md - open work

Swept 2026-08-27: finished work folded into AGENTS.md and README.md; git history holds the raw detail.

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

## Phase MOBBOOT - cold-launch bootstrap race

- [~] **MOBBOOT.1 [AGENT]** REOPENED - device-verified BROKEN 2026-08-27, despite an earlier "[x] verified 2026-08-20". On the emulator with a CONFIGURED device (`mobile_status` returns configured:true, 48 artifacts synced in the DB), the UI STAYS STUCK ON THE SETUP SCREEN and never shows the library, even when `show('library')` is forced over CDP (0 `.card` elements). So the retry logic (`waitForInvokeAndStatus` in `bootstrap()`, `src/enqueue/static/mobile.html`) does NOT land a configured device on the library. The earlier "verified" only checked the UNconfigured case (fresh install correctly shows setup) - it never confirmed the configured case reaches the library.
  Fix: make a cold launch on a CONFIGURED device land on the library (never a stuck/flashing setup). Trace why, after `mobile_status` resolves configured:true, the library section is not shown/populated - check the bootstrap branch that calls `show('library')` + `renderLibrary()`, and whether a later handler resets to setup.
  Done when: force-stop + cold launch a configured emulator, and within a couple seconds (no manual `bootstrap()`/`show()` calls over CDP) the visible section is `library` with cards rendered. Verify over CDP + screencap, recorded in PROGRESS.md.

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

## Phase BACKFILL - auto-backfill on sync-enable (optional)

- [~] **BACKFILL.2 [AGENT]** Auto-backfill on sync-enable implemented. store_sync_secret triggers push_all() in background when DEK is loaded and backfill hasn't run. One-shot flag (sync_backfill_done) prevents re-run. bin/verify green.
  Call `push_all()` off the main path (a background thread, never blocking the request) from the sync-enable / secret-set path (`api/settings.py store_sync_secret`), guarded so it does not re-scan on every launch (a one-shot flag, or rely on the relay's idempotent 409s if a full re-scan is cheap enough).
  Done when: setting the sync secret against a fresh relay backfills the syncable artifacts automatically, with no manual command, and does not re-run the full scan on every launch.
  VERIFY: point the desktop at a scratch relay, set the secret, confirm the relay gains the syncable count with no manual push; `bin/verify` green.

## Phase DESKTOPUI - desktop settings + chat polish

- [~] **DESKTOPUI.6 [REVIEW 2026-08-20]** The agent's "[x] fixed" was FALSE + a regression, caught by actually rendering it (not just reading the path): its replacement path (`M12 2C6.48...zm-1-13h2v6h-2`) is a circle-with-an-i (info glyph), NOT a gear - and it put that SAME glyph into mobile.html too, replacing the mobile pill's original 3-dot menu icon. So neither surface had a real gear (desktop was a sun, mobile was a 3-dot menu; the agent made both a circle-i). FIXED 2026-08-20: put a real Feather cog (`<circle r=3/>` + cog path) into `icons.js` AND `mobile.html`. DESKTOP VERIFIED via browser screenshot - the pill's settings icon now renders as a gear. MOBILE: same path applied, pending an emulator glance. LESSON: DESKTOPUI.6 was marked [x] on "source code" reading; a gear glyph can only be verified by LOOKING at it rendered.
  Root cause pinned: `src/enqueue/static/js/icons.js:27` defines `gear:` as a circle plus eight straight rays (`M12 2v3 M12 19v3 M22 12h-3 ...`) - that is literally a sun glyph.
  Replace its path data with a real gear outline; copy the gear SVG the mobile app uses (grep `src/enqueue/static/mobile.html` for the settings/gear icon in the pill) so the two surfaces match exactly.
  Keep the same viewBox/stroke convention as the other entries in `icons.js`.
  Done when: the desktop settings icon is a recognizable gear consistent with mobile; `bin/verify` green.

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

- [~] **MOBILEUI.2 [AGENT]** FIXED in working tree (uncommitted). Root cause: sync-event listeners (`sync-started`/`sync-done`/`sync-error`) were wired once at script parse time with a guard `if (window.__TAURI__ && window.__TAURI__.event)` that fails on cold launch when the Tauri bridge is slow to inject. The sync thread (`desktop/src/lib.rs:255-300`) still runs and emits events, but they fire into the void. `#loading` was set visible by the QR-link path or `bootstrap()` and nothing ever hid it. Same class as MOBBOOT.1.
  Fix (in working tree): extracted the three `listen()` calls into `wireSyncListeners()` (idempotent via `syncListenersWired` flag), called from `waitForEventApi(attempt=1)` which polls for `window.__TAURI__.event` up to 20 times at 50ms (same budget as the invoke poller). Also added `#loading[hidden] { display: none }` CSS rule to ensure the `[hidden]` attribute wins over `display: flex`.
  Files: `src/enqueue/static/mobile.html` (lines ~2738-2801 for the retry wiring, line ~567 for the CSS rule).
  Done when: a sync shows "Syncing..." then clears to the library on completion, on a cold launch where `__TAURI__` is slow to inject.
  VERIFY: CDP - `adb forward tcp:9222 localabstract:webview_devtools_remote_$(adb shell pidof com.sudohnim.enqueue)`, force-stop + launch (cold), then `Runtime.evaluate` `window.__TAURI__.core.invoke('mobile_sync', { config: '{}' })` and assert `#loading.hidden === true` after `sync-done` fires. Record in PROGRESS.md.

- [~] **MOBILEUI.3 [AGENT]** Notes render as SQUARE cards like desktop app. Implemented: `.row` CSS changed from `min-height: 140px` to `aspect-ratio: 1` (makes each card a perfect square), `.rows` container uses CSS grid. `renderRows` uses `div.card`.
  Verify: build debug apk, install on emulator, open library, screencap. READ the PNG - cards must be square (width == height), arranged in a grid (2+ columns), not full-width rows. CDP: `Runtime.evaluate` `document.querySelector('.card').getBoundingClientRect()` -> assert `width === height` (within 1px). Record in PROGRESS.md.

- [~] **MOBILEUI.4 [AGENT]** Color added to mobile main screen. Implemented: `.card` gets a kind-based accent via `--kind-note` / `--kind-link` / `--kind-image` / `--kind-pdf` / `--kind-file` tokens from `css/tokens.css` (search `kind-` in mobile.html for the exact rules).
  Verify: build debug apk, install on emulator, open library, screencap. READ the PNG - cards must have visible colored accents (not monochrome). CDP: `Runtime.evaluate` `getComputedStyle(document.querySelector('.card')).borderTopColor` (or `borderLeftColor` if accent is on the side) -> assert it is NOT the same as the default border color. `bin/check-contrast` stays green. Record in PROGRESS.md.

- [~] **MOBILEUI.6 [AGENT]** Bottom pill: 3 icons (plus, eye, gear). PARTIAL - some done, some open.
  DONE (verified on emulator 2026-08-20):
  - Pill has exactly 3 icons: purple `+` disc, eye, gear. Search button removed.
  - Gear icon is a real Feather cog (not the old sun/3-dot/circle-i). Wired to `openSettings()`. Settings screen reachable.
  - Root cause of the original "broken icons" was a stray semicolon after `MOBILE_ICONS.gear` (commit `adebc46`) killing the entire inline script parse. Fixed.

  OPEN (two defects, both in `src/enqueue/static/mobile.html`):
  - **Defect A - the `+` disc is EMPTY.** The markup renders `<span class="disc"></span>` with no icon inside. Fix: add a `plus` entry to `MOBILE_ICONS` - `'<path d="M12 5v14M5 12h14"/>'` (the exact path from `static/js/icons.js`) - and render `svg("plus")` inside the disc in BOTH places the pill is built: the static HTML (search `id="pill_add"`) and the `pillRestorePill` JS rebuild (search `function pillRestorePill`). The disc CSS (32px, `--purple-bold`, white ink) already exists. This defect means the user sees a blank purple circle instead of a plus.
  - **Defect B - the eye geometry is WRONG.** The mobile overrides (search `.pill .pill-eye .eye-socket` in mobile.html) set `width: 52.6%; height: 51.5%; top: 80%; left: 69.3%` and `.eye-pupil { width: 120%; height: 156% }`. These contradict the canonical desktop geometry in `css/home.css` (search `.eye .eye-socket` there). Result: the pupil paints outside the lid and the eye reads as a purple blob. Fix: delete the mobile overrides and copy the canonical `.eye .eye-blinkwrap` / `.eye .eye-socket` / `.eye .eye-pupil` / `.eye .eye-frame` rules from `css/home.css` into mobile.html's style block (mobile.html does not load home.css). Size the frame to 34px inside the 44px round button (same as desktop `pill.css` uses): `.pill .pill-eye .eye-frame { width: 34px; height: auto; }`.

  Done when: pill has 3 icons; the `+` disc shows a white plus (not blank); the eye renders as an eye (pupil inside lid, not a blob). Verify on emulator screencap - READ the PNG.

## Phase MOBFIX - mobile fixes from live device testing (2026-08-20)

Found by firing the app up on the physical phone. Verify every one of these ON A DEVICE
(screencap + CDP), not with bin/verify. Several depend on real design work - see MOBFIX.8.

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

- [~] **MOBFIX.5 [AGENT]** STILL BROKEN - device-verified 2026-08-27. Deleted "more wheeee" on desktop, synced the phone: the phone still shows it as non-deleted, AND the relay object for it still decrypts to `deleted_at=None`. So the tombstone NEVER REACHES THE RELAY - the bug is on the desktop PUSH side, not the phone apply side.
  PRIMARY ROOT CAUSE (architectural): the relay is IMMUTABLE BY OBJECT NAME. `put_object` (`src/enqueue/relay/app.py:100-106`) raises `ObjectConflict -> 409 "object already exists"`, and the object name is id-based with no version/hash (`sync/client.py:75` `dev/{device}/artifacts/{id}.enc`, same in `desktop/src/sync.rs:176`). So when an already-synced artifact is mutated (delete, edit, pin, tag, restore), `push_artifact` PUTs the SAME name, the relay 409s, and the updated snapshot is silently refused. The pull's LWW-by-`(updated_at, device_id)` (`sync/snapshot.py`) is MOOT because the newer snapshot can never land on the relay. This means ALL mutations to synced artifacts fail to propagate - it invalidates the CRUDSYNC "done" claims for any artifact that was already synced once.
  The earlier agent "fix" (bump `updated_at` in `trash.py` delete/restore) is necessary-but-insufficient: the object NAME is id-based, so bumping `updated_at` does not change the name, so the PUT still 409s. Keep that change, but it does nothing until the relay accepts the update.
  FIX (decide the approach, then apply on both the Python push and the Rust mobile push + the relay):
  (a) PREFERRED - make the relay object MUTABLE: `PUT dev/{device}/artifacts/{id}.enc` overwrites the existing object (idempotent, last-write-wins at the storage layer), i.e. remove the `ObjectConflict`/409 for the per-artifact object path. Then updates propagate and the pull's LWW resolves ordering. Backfill's "409 = skip" economy is lost, so have `push_all` skip client-side (track/compare `updated_at`) instead of relying on the relay's 409.
  (b) ALT - versioned object names (`...{id}-{updated_at}.enc`): every snapshot is a new object (PUT always 201), the pull takes the latest per id by LWW; needs GC of superseded versions or the relay grows unbounded.
  CURSOR SUBTLETY (do not miss this - it is why the fix is not just "remove the 409"): the pull is cursor-based (`GET /sync/objects?since=N`). An OVERWRITTEN object (option a) must be assigned a NEW, higher sequence number on write, or a device that already pulled past it (its cursor > the object's old position) will never re-pull the update. So the relay storage must move an overwritten object to the head of the since-ordering. Option (b) sidesteps this (each version is a brand-new object at the head) but adds GC. Whichever way, verify a device that ALREADY synced the artifact then pulls again actually receives the newer snapshot.
  Not a quick patch - it touches relay storage + cursor ordering + both push clients (Python `sync/client.py` and Rust `desktop/src/sync.rs`) + `push_all` backfill. Do it as a deliberate pass, not inline with UI work.
  Done when: delete on desktop -> the note disappears from the phone after its next sync (relay object decrypts to `deleted_at` set); an EDIT on desktop -> the edit appears on the phone; restore reverses it; a device that already had the artifact receives the update on its next pull. Verify by the same decrypt-the-relay-object + phone run-as check used to find this.
  Fix (in working tree): `trash.py:61` now `UPDATE artifacts SET deleted_at = ?, updated_at = ? WHERE id = ?` (bumps `updated_at = now`). `trash.py:86` now `UPDATE artifacts SET deleted_at = NULL, updated_at = ? WHERE id = ?` (same bump on restore). Both have explanatory comments referencing MOBFIX.5. The `push_artifact(id)` call that follows now carries a tombstone with a NEWER `updated_at`, so LWW on the phone picks it up.
  Files: `src/enqueue/trash.py` (lines 58-63 for delete, 84-88 for restore).
  Done when: deleting on desktop -> the note disappears from the phone after its next sync; restore reappears.
  VERIFY: `adb shell run-as com.sudohnim.enqueue sqlite3 /data/data/com.sudohnim.enqueue/library.db "SELECT id, deleted_at, updated_at FROM artifacts"` (debug apk) - the tombstoned row must have `deleted_at` set AND `updated_at` newer than pre-delete. Plus `bin/verify` green. A regression test asserting `lww_key(tombstone) > lww_key(live)` should be added to `tests/test_sync.py` or `tests/test_trash.py`.

- [~] **MOBFIX.6 [AGENT]** FIXED in working tree (uncommitted). Root cause: `desktop/icons/make_adaptive_icons.py` used a color-difference mask subtracting phantom purple `(107, 70, 193)` from the source `icon.png`. But `icon.png` is a 1024x1024 RGBA image with a TRANSPARENT background (alpha=0) and a near-WHITE raven (RGB 253,253,253). There is NO purple in the source. All pixels (transparent and white alike) had diff > 60, so ALL classified as "raven" -> bbox = full canvas -> no crop -> raven at ~65% of launcher icon.
  Fix (in working tree): replaced the color-difference mask (old lines 63-73) with `alpha_mask = src_array[:, :, 3]` (the source's alpha channel: opaque = raven, transparent = background). The bbox detection now finds the raven's actual opaque bbox (rows 97-926, cols 97-926 = 81% of canvas), crops to it, and scales to `safe_zone` (80% of target). Added a guard checking `src_array.ndim == 3 and shape[2] == 4`. All mipmap PNGs regenerated (sizes increased ~35%, confirming the raven now fills more of the icon).
  Files: `desktop/icons/make_adaptive_icons.py` (mask logic, lines 59-68), `desktop/gen/android/app/src/main/res/mipmap-*/ic_launcher*.png` (20 regenerated files).
  Done when: the launcher icon shows the raven at a proper, filling size on the emulator launcher AND (one human glance) on the phone launcher.
  VERIFY: install debug apk on emulator, screencap launcher home screen, READ the PNG - raven fills the inner circle, no excessive padding, no clipped wingtips.

- [ ] **MOBFIX.7 [AGENT]** Re-verify all working-tree fixes on the device once committed. The fixes are in the working tree but NOT committed and NOT device-verified:
  1. Commit all uncommitted working-tree changes (MOBILEUI.2 listener retry + `#loading[hidden]` CSS, MOBILEUI.3 `aspect-ratio: 1`, MOBFIX.5 `updated_at` bump, MOBFIX.6 alpha-mask icon regen, QRSCANFIX.1 `errString` helper, plus the `setupPillMenuHandlers` idempotent guard).
  2. Build a fresh debug apk: `cd desktop && cargo tauri android build --debug --target aarch64`.
  3. Install on emulator: `adb install -r desktop/gen/android/app/build/outputs/apk/arm64/debug/app-arm64-debug.apk`.
  4. Verify each fix per its "Done when" / "VERIFY" section:
     - MOBILEUI.2: cold launch -> sync -> `#loading` hides on `sync-done`.
     - MOBILEUI.3: library cards are square (width == height within 1px).
     - MOBFIX.3: `+` > Camera opens the camera Activity (dumpsys), captures a photo.
     - MOBFIX.5: delete on desktop -> phone removes the note after sync.
     - MOBFIX.6: launcher icon shows raven at proper size.
     - QRSCANFIX.1: scan or cancel QR -> no "[object Object]" in status.
  Done when: all fixes confirmed on emulator/phone; record in PROGRESS.md.

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
