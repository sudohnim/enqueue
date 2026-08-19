# PLAN.md - the desktop sync setup flow

Clean-cut restart (2026-08-15). The prior PLAN/PROGRESS history was retired; durable
context (architecture, sync/E2E model, Option A pairing, mobile scope, deviations,
build commands) now lives in `AGENTS.md`, `docs/DESIGN.md`, and `README.md`. Read
those first. This file holds only open work.

## Context: what is built, and the one gap

Sync, E2E, and the Android app are built (see `AGENTS.md` "Resolved decisions" #2).
The relay, engine sync client/worker, snapshot LWW, the E2E keyring
(`keyring_file.py`: DEK wrapped under a password-KEK and a recovery-phrase-KEK), and
the mobile app all exist. The desktop can also SHOW a pairing code once configured.

The gap: **there is no way to CONFIGURE sync on the desktop in the first place.**

- `keyring_file.initialize(password)` (creates the DEK, returns the recovery phrase) is
  called by no CLI and no endpoint - the keyring can never be created from a surface.
- The Settings > Sync tab, when unconfigured, shows a dead-end "Not configured" message
  with no inputs (and stale copy: "import your keyring and recovery phrase on your
  mobile device").
- There is no `enq relay` command; the relay only runs via a raw uvicorn factory call.

Result: `keyring_file.dek()` is always None, sync stays locked, and the pairing code UI
(which assumes a configured, initialized library) is unreachable. This phase builds the
front door.

## Pairing model (SUPERSEDED - see Phase QRSYNC)

The old "Option A" model (paste a code + type a library password on each device) was
replaced on 2026-08-16 after live testing. The current model is QR-linked, hosted-relay,
passwordless - the desktop shows a camera-scan QR that carries the key, no password
anywhere. Full statement in Phase QRSYNC below and `AGENTS.md` decision #2. Do NOT build
against Option A; the SU / FIX phases below predate the switch and are kept only for
their (mostly done) engine/relay/keyring groundwork that QRSYNC reuses.

## Phase SU - the desktop sync setup flow

- [x] **SU.1 [AGENT]** An `enq relay` CLI command to run the relay locally.
  Wrap `enqueue.relay.app.create_relay(data_dir, secret=...)` in a CLI command
  (`src/enqueue/cli.py`) that serves it with uvicorn. Flags/env for port (default a
  fixed local port, documented), the Bearer secret (`RELAY_SECRET`), and the data dir
  (`RELAY_DATA_DIR`). Bind to `127.0.0.1` by default; a LAN/remote bind is an explicit
  opt-in (the payload is already encrypted, so `guard.py` allows non-local, but the
  default stays local). Document it in `README.md` (running the relay) and `AGENTS.md`
  (CLI surface).
  Done when: `enq relay` boots and answers on the documented local port; a wrong Bearer
  secret is rejected (401); `enq relay --help` shows the flags.

- [x] **SU.2 [AGENT]** An endpoint to initialize the library keyring.
  Add `POST /settings/keyring-init` taking `{password}` that calls
  `keyring_file.initialize(password)` and returns the recovery phrase ONCE in the
  response body. Guard with `keyring_file.is_initialized()`: refuse to re-initialize an
  existing keyring (that would orphan the current DEK and all synced data) unless an
  explicit destructive flag is passed, and say so in a human sentence. Security: the
  recovery phrase is returned exactly once and never logged, never persisted anywhere
  except its wrapped form inside `keyring.json`; the password is never logged or stored
  in plaintext. Also expose keyring state on `GET /settings` (initialized or not, and
  locked or unlocked) so the UI can branch.
  Done when: a fresh init returns a recovery phrase and writes `keyring.json` with both
  wrap slots; a second init without the destructive flag is refused with a clear
  message; the phrase never appears in any log; `keyring_file.dek()` is non-None after a
  subsequent unlock with that password.

- [x] **SU.3 [AGENT]** The Settings > Sync setup form (replaces the dead "Not
  configured" state in `static/js/settings.js`). When sync is not configured, render a
  real form, walking the person through, in order:
  1. Relay URL (default the local `enq relay` address from SU.1).
  2. Set a library password → calls SU.2, then displays the recovery phrase ONCE inside
     a clear "write this down, it is the only way to recover if you forget the password"
     panel with an explicit "I have saved it" confirmation before continuing. Never show
     the phrase again after this step.
  3. Set (or generate) the sync secret via the existing `PUT /settings/sync-secret`
     (which already calls `push_keyring()`), and persist the relay URL via
     `PATCH /settings` (`sync_relay_url`).
  On success the tab flips to the already-built "Configured" state (Relay URL / secret
  hint / device id + the Option A pairing code UI). If the keyring is already
  initialized but sync is unconfigured (e.g. re-pairing this same desktop), skip step 2
  and just collect relay URL + secret.
  Done when: from a fresh library, filling the form configures sync end to end - keyring
  created, recovery phrase shown once and confirmed, secret stored, keyring pushed to
  the relay - and the tab then shows the pairing code; reloading Settings shows the
  configured state; `bin/verify` passes.

- [x] **SU.4 [AGENT]** Fix the stale empty-state copy. Remove the pre-Option-A wording
  ("import your keyring and recovery phrase on your mobile device") from
  `settings.js`; the new SU.3 form replaces it. Grep for any other stale "import your
  keyring" / "scan the QR with your phone's camera" strings that imply removed flows and
  correct them to the Option A language (paste code + library password).
  Done when: no stale sync copy remains; the Sync tab reads consistently with Option A.

- [ ] **SU.5 [AGENT]** End-to-end verification, real devices. With `enq relay` running
  locally and a desktop configured via SU.3: capture an artifact on the desktop, show
  the pairing code, pair a physical phone (`bin/launch mobile`) by pasting the code and
  entering the library password, and confirm the artifact appears on the phone. Capture
  on the phone, confirm it syncs back to the desktop. Record the run in `PROGRESS.md`.
  Done when: an artifact made on either device appears on the other through the local
  relay, with the password never leaving its device and no key material in the pairing
  code.
  SUPERSEDED (2026-08-16) - this is the Option A paste-code + password flow, replaced by
  the camera-only QR link. Its real successor is QR.4b's done-when (scan the desktop QR,
  library appears on the phone). During live testing the mechanism WAS proven end to end:
  desktop->mobile synced and decrypted a note on the physical phone, and mobile->desktop
  pushed (it only failed to appear because the desktop had re-locked on restart - the
  exact pain QR.1's Keychain auto-load removes). Do not run SU.5 as written; validate
  sync via QR.4b instead.

- [x] **SU.7 [AGENT]** Desktop keyring unlock-on-launch (required; found trying to run
  SU.5). The DEK is held in memory only (`keyring_file._dek`), so every engine restart
  leaves an initialized keyring LOCKED (`keyring_file.dek()` is `None`, `GET /settings`
  reports `keyring_locked: true`) and sync cannot encrypt, push, or pull until it is
  unlocked. `keyring_file.unlock(password)` (keyring_file.py:122) exists but is wired to
  NOTHING - no endpoint, no CLI, no UI. `initialize()` unlocks at first-time creation,
  but nothing unlocks on any launch after. This is a hard blocker for sync surviving a
  restart, and it is why the relay has zero objects (the locked desktop never pushed).
  Build:
  1. `POST /settings/keyring-unlock` taking `{password}` -> calls
     `keyring_file.unlock(password)`; on success returns ok and the sync worker resumes;
     a wrong password returns a human-readable error and the keyring stays locked. Never
     log the password. (`GET /settings` already exposes `keyring_locked`.)
  2. Desktop Settings > Sync: when `keyring_initialized && keyring_locked`, show a
     "Sync is locked - enter your library password to unlock" form instead of the
     configured/pairing view; on unlock, flip to the configured/pairing state. Ideally
     also surface the locked state on launch (a prompt or a clear banner) so the person
     is not silently un-synced.
  3. Confirm the push/pull/worker paths (which already no-op while locked) resume once
     `dek()` is non-None.
  Only the desktop needs this: mobile stores the DEK in an app-sandboxed file (MOB.3b),
  so it survives restarts and does not re-lock.
  Done when: after an engine restart with an initialized keyring, `GET /settings` shows
  `keyring_locked: true`; entering the correct password via the new endpoint/UI unlocks
  it (`keyring_locked: false`); a wrong password shows a human error and stays locked;
  and a push/pull works after unlocking (verify an object reaches the relay).

## Phase FIX - bugs blocking SU.5 (found trying to run the real end-to-end test)

SU.5 could not run. Three defects surfaced, plus the gate gap that hid two of them.
SU.5 stays blocked until FIX.1 and FIX.2 are done. FIX.3 stops this class of bug from
hiding again.

- [x] **FIX.1 [AGENT] - RE-APPLIED + verified 2026-08-18. MUST BE COMMITTED (it has been
  lost twice as uncommitted working-tree changes).** Re-applied all 7 fixes to
  `desktop/src/lib.rs` (deleted the duplicate `run()` block, restored `#[tauri::command]`
  on `mobile_outbox_push`, `app.dialog().file().blocking_pick_file()` for the two dialog
  fns, `(200..300).contains(&status)` for ureq, `try_into` for the DEK, `app.handle()` in
  the setup closure, `[&id]` for the moved id). `cargo check --lib --target
  aarch64-linux-android` = 0 errors; full `bin/verify` green (JS, pytest, contrast,
  Android compile). COMMIT `desktop/src/lib.rs` NOW so it is not reverted a third time.
  The mobile module was previously broken because: `cargo check --lib --target aarch64-linux-android` = 15
  errors, the SAME ones this task originally fixed (duplicate `pub fn run()` in
  `mod mobile` - now at lib.rs:994 AND :1132; `mobile_outbox_push` missing its
  `#[tauri::command]` at lib.rs:938; `fetch_keyring` mis-nesting in sync.rs; ureq
  `is_success`/`into_json`; `DialogExt::file` E0782; moved `id`; `open_lib(&app)` in the
  setup closure). ROOT CAUSE: the original FIX.1 edits lived in the WORKING TREE and were
  never committed; a later commit/checkout reverted `lib.rs` to its broken pre-FIX.1
  state (`git status` shows lib.rs clean = HEAD is the broken version). This is why
  QR.5a/QR.4b could not be device-verified - the app cannot build. Re-apply the exact
  FIX.1 fixes (they are documented in the original PROGRESS "FIX.1 done" entry), then
  COMMIT them so they cannot be lost again. `bin/verify` (FIX.3 android check) MUST be run
  and MUST pass before checking this box - it would have caught this. The original task
  text follows for reference:
  The mobile app does not compile for Android - 16 Rust errors in
  the `#[cfg(mobile)] mod mobile` block of `desktop/src/lib.rs`. These were invisible
  because a desktop `cargo check`/`cargo build` excludes the mobile cfg, so the module
  never actually compiled; the apk on the phone is a stale Aug-14 build from an older
  tree. The current source has never built for Android. Errors seen (from
  `cargo tauri android build --debug --target aarch64`):
  - `resp.into_json()` - `ureq`'s `into_json` needs the `json` feature, which is not
    enabled (`ureq = "2"` in `desktop/Cargo.toml`). Enable `features = ["json"]` or
    parse the body manually. (~line 730, `mobile_chat`.)
  - `resp.status().is_success()` - `ureq` 2.x `status()` returns `u16`, which has no
    `is_success()`. Use an explicit range check (`(200..300).contains(&status)`). (~724.)
  - `use of moved value: id` / `borrow of moved value: id` - `id` moved into a rusqlite
    params array then used again; `.clone()` the id (or reorder). (~616-624, blob/outbox.)
  - plus E0308 (mismatched types, several), E0782, E0425, E0428, E0599 - work through
    each from the compiler output.
  Fix all 16 so `cargo tauri android build --debug --target aarch64` succeeds, then
  rebuild + install the apk on the phone.
  Done when: `cargo tauri android build --debug --target aarch64` compiles with zero
  errors and produces a fresh `app-arm64-debug.apk`; it installs and launches on the
  physical phone and shows the setup screen; the Connect flow does not crash (the
  duplicate-handler bug was already removed in mobile.html, so verify that fix is in the
  fresh build).

- [x] **FIX.2 [AGENT]** The desktop "Show pairing code" button errors with
  `desktop_pairing_code not allowed. Command not found` in the running app.
  `desktop_pairing_code` IS defined and registered in the `#[cfg(desktop)]`
  invoke_handler (`lib.rs:1541`/`:1634`), so the most likely cause is a stale desktop
  binary (the window predates the command). First: `bin/launch desktop` (always
  rebuilds now) and retry. If it still fails after a clean rebuild, it is a Tauri v2
  capabilities/permission gap - the command needs an allow entry in a capability file
  (mirror how the `mobile_*` commands got `desktop/permissions/autogenerated/*.toml`).
  Investigate and fix whichever it is; record the root cause in PROGRESS.
  Done when: from a freshly built + relaunched desktop, "Show pairing code" returns the
  locally-rendered QR + code with no error, and the code decodes to
  `{relay_url, secret}` only (no key material).

- [x] **FIX.3 [AGENT]** The verification gate does not catch Tauri or Android failures,
  which is why FIX.1 and FIX.2 passed as "done." `bin/verify` runs JS-parse + pytest +
  contrast - it never compiles the mobile cfg and never runs the desktop Tauri runtime,
  so a mobile module that does not compile and a desktop command that is unreachable
  both sail through. Add an Android compile check to the gate: `cargo check --lib
  --target aarch64-linux-android` (with the NDK env `bin/launch mobile` sets), skipped
  with a clear message when the Android toolchain/NDK is absent so non-mobile machines
  are not blocked. Document in AGENTS.md that a green `bin/verify` is NOT proof the app
  runs - the desktop window and a real device are the only proof (this is the AGENTS.md
  "reproduce in a real setting" rule applied to the shells).
  Done when: `bin/verify` fails when the mobile module does not compile for Android (and
  skips cleanly with a message when no NDK is present); AGENTS.md states the gate's
  limits.
  REOPENED (review 2026-08-16). The check was added and its failure path is correct
  (`cargo check` non-zero -> the gate exits 1), BUT it only runs when `ANDROID_HOME` AND
  `NDK_HOME` are exported as env vars - which they are NOT in a normal shell. So a plain
  `./bin/verify` prints "SKIPPED - NDK_HOME not set" and passes even with the mobile
  module broken - the exact hiding this task exists to stop, and the reason it did not
  catch FIX.1. The done-when says "skips cleanly when no NDK is PRESENT", but the NDK IS
  present (installed at `~/Library/Android/sdk/ndk/*`); it is just not in an env var, so
  it skips instead of running. Fix: auto-detect the toolchain from the standard install
  location the way `bin/launch mobile` already does - when the env vars are unset,
  default `ANDROID_HOME` to `~/Library/Android/sdk` and `NDK_HOME` to the newest
  `~/Library/Android/sdk/ndk/*` (sorted, take the last). Only skip when the SDK/NDK
  directory genuinely does not exist on disk. Re-verify by breaking the mobile module on
  purpose (e.g. a bad token in a `#[cfg(mobile)]` fn) and confirming a plain `./bin/verify`
  now FAILS, then reverting.

- [x] **FIX.4 [AGENT]** Desktop "reset sync" affordance. There is no way to reset or
  re-initialize sync from the UI, so a person who set a library password but did not
  record the recovery phrase (shown exactly once at creation, by design) cannot get a
  new one without hand-deleting `~/.enqueue-poc/keyring.json`. Add a "reset sync" control
  in Settings > Sync that calls `POST /settings/keyring-init` with `force=true` behind a
  clear destructive confirmation ("this wipes the current key and orphans anything
  already synced - only do this if nothing important has synced yet"), then shows the
  new recovery phrase once (the same one-time panel as first setup).
  Done when: from a configured library, a guarded reset re-initializes the keyring and
  shows a fresh recovery phrase once; the confirmation states the data-loss consequence
  plainly; cancelling changes nothing.

## Phase CAP2 - quick-capture UX fixes

- [x] **CAP2.1 [AGENT]** In the quick-capture overlay, a plain Enter should SAVE and
  Shift+Enter should insert a newline. Right now it is reversed: Enter inserts a newline
  and only the Keep button submits (a deliberate CAP.2 choice for markdown-as-you-type,
  `src/enqueue/static/capture.html` keydown handler ~line 759-769). Change to the dequeue
  feel: a plain Enter (no Shift/Cmd) calls the same path as the Keep button; Shift+Enter
  inserts a newline. Accepted tradeoff: multi-line notes and markdown lists now need
  Shift+Enter between lines - that is the intended behaviour. Leave Escape (dismiss
  without discarding) and image-paste unchanged.
  Done when: in the capture overlay, Enter saves the capture exactly as the Keep button
  does, Shift+Enter adds a newline, and Escape still dismisses without losing the draft.
  DONE (verified) - see PROGRESS: keydown now calls `keep()` on plain Enter (consumed
  => submits, no newline), allows the native newline on Shift+Enter, and leaves Escape
  unchanged. Verified via headless Chrome CDP; `bin/verify` green.

- [ ] **CAP2.2 [AGENT]** The capture-success raven must play over whatever app is
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

## Phase QRSYNC - QR-linked, hosted-relay, passwordless sync (the refactor)

Decided 2026-08-16 after live SU.5 testing. This REPLACES the Option A pairing model
(paste-code + per-device library password) and its whole surface. Two decisions, both
baked:

- **Hosted relay** (not localhost/USB): a dumb ciphertext relay reachable over the
  internet, so the phone syncs anywhere, not only on the same wifi or plugged in over
  USB. The relay still only ever stores/streams opaque encrypted bytes (E2E model
  unchanged, `guard.py` already allows non-local since bytes are encrypted).
- **QR carries the key, Signal-style**: the desktop shows a locally-rendered QR; the
  phone camera scans it and links + receives the encryption key in one step. There is
  NO library password in the normal flow. The old recovery phrase becomes a
  recovery-code-only artifact (shown once, used only to recover if every device is
  lost).

Why this supersedes the current sync UX (from live testing): the localhost relay only
reached the phone via `adb reverse` (USB), which defeats mobile; the in-memory DEK
locked on every desktop restart (SU.7) and a locked desktop silently failed to sync;
and forgetting the library password locked the user out with no in-UI recovery. The new
model removes passwords, unlock-on-restart, and paste-codes entirely.

SUPERSEDED by this phase (do NOT keep building on them): the mobile paste-code +
library-password setup surface (`mobile_pairing_setup`, the setup form in mobile.html);
the desktop SU.7 unlock flow and its `keyring-unlock` endpoint/UI (no password to unlock
anymore - the DEK auto-loads); the SU.2 `keyring-init` endpoint's `{password}` input and
the SU.3 setup form's "set a library password" step (key creation becomes passwordless,
see QR.1); the Option A pairing statement in AGENTS.md decision #2 (update it to this
model). FIX.2's `desktop_pairing_code` plumbing can be reused but its output changes (see
QR.3).

LOST-WORK RECOVERY MAP (2026-08-18): a git revert during development discarded the
QRSYNC *Rust/lib.rs* work while the JS / Python / permission-toml sides were committed,
so the committed tree is INCONSISTENT - JS calls Rust commands that no longer exist.
SURVIVED (committed, present): QR.1 Python (`keyring_file.initialize()` passwordless,
`keyring.dek_store`/`load_dek_from_keychain`, `enqueue-sync-dek`); QR.3 `settings.js`
`showLinkCode()` + `desktop_link_code.toml`; QR.4 `mobile.html` camera scan +
`invoke("mobile_link_qr")`; QR.6 `loading.png`; QR.7 pill. LOST (0 refs in
`desktop/src/lib.rs`, must be re-added + committed): `desktop_link_code` +
`build_link_payload` (QR.3), `mobile_link_qr` (QR.4b), `start/stop_sync_foreground_service`
(QR.5b). Net effect: QR.3's button and QR.4b's link both error "command not found" until
the Rust side is restored. THE META-FIX: run `bin/verify` (it has the Android compile
gate) before any "done", and COMMIT after every green run - this Rust work has been lost
twice now.

REAL DEPENDENCY GRAPH (2026-08-18, corrected twice - the strict serial order below
overstated the coupling; and the camera is now the NATIVE plugin, not a webview feed):
- CAMERA work: QR.4a = integrate `tauri-plugin-barcode-scanner` + rewrite the setup
  screen (see its DECISION block). This is the only item with real uncertainty - the
  plugin is spec'd but unproven on the physical phone. If it fights us like getUserMedia
  did, escalate back to a decision; do not hand-roll a CameraX Activity without asking.
- INDEPENDENT of the camera, do NOW (headless): QR.2 (hosted-relay config + docs - desktop
  side, no camera); QR.5b (Android foreground service - `start/stop_sync_foreground_service`
  are 0 refs = never restored; pure Rust/JNI). Neither needs a working camera to IMPLEMENT.
- VERIFIABLE WITHOUT THE CAMERA (by injecting a link payload via adb, bypassing the
  scanner): QR.4b's `mobile_link_qr` fix (the `mobile_link_qr` -> save_config -> sync path)
  and QR.5a (non-blocking sync). The agent injects `{relay_url, relay_secret,
  dek}` straight to `mobile_link_qr` to reach a synced state and confirm link + sync +
  non-blocking, independent of QR.4a. So do not treat these as camera-blocked.
- SEQUENCING NOTE (supersedes "QR.4b depends on QR.4a"): with the plugin pivot there is no
  webview feed for QR.4b to depend on. Do QR.4b's `mobile_link_qr` fix FIRST (headless,
  adb-injection verified), THEN QR.4a's plugin + setup screen (its done-when is end-to-end
  link+sync, which needs the fixed `mobile_link_qr`). QR.4a's step-3 parse is QR.4b item 2;
  the two land together but the link fix gates the device verify.

EXECUTION ORDER (default when tasks are truly serial): QR.1, QR.2, QR.3, QR.4a, QR.4b,
QR.5a, QR.5b, QR.6, QR.7 - but per the graph above, QR.2 and QR.5b are NOT gated by QR.4a
and should proceed in parallel rather than idling behind the camera.
QR.3 depends on the DEK existing via QR.1's passwordless keygen.
QR.4a/QR.4b depend on QR.3's pinned wire format.
QR.4a's device-verify depends on QR.4b's `mobile_link_qr` fix (do the link fix first);
QR.5b depends on QR.5a's threaded sync.
Do not start a later task until the previous task's "Done when" passes.
Every task has a VERIFY line: run it and paste the result into PROGRESS.md before
checking the box. A compile success is NOT the task's "Done when" - it is only the
minimum bar to attempt device verification.

VERIFICATION PROTOCOL (2026-08-19 - READ THIS BEFORE CLAIMING "HEADLESS, NEEDS A HUMAN"):
a harness without a display can still drive the PHYSICAL PHONE end to end over USB adb.
"Headless" only means no macOS window - it does NOT block phone verification. The phone
is the display. Default to driving it yourself; escalate to the human ONLY for the two
truly visual checks listed at the bottom, and say exactly WHICH check needs eyes.
The adb toolkit (phone plugged in via USB):
  - Build + install: `cargo tauri android build --debug --target aarch64`, then
    `adb install -r desktop/gen/android/app/build/outputs/apk/arm64/debug/app-arm64-debug.apk`.
  - Launch: `adb shell monkey -p com.sudohnim.enqueue -c android.intent.category.LAUNCHER 1`
    (or `am start -n com.sudohnim.enqueue/.MainActivity`).
  - Screenshot: `adb exec-out screencap -p > /tmp/shot.png` - then READ the PNG (the agent
    can see images; OCR/inspect it yourself, do not ask the human to describe the screen).
  - Drive the UI: `adb shell input tap <x> <y>` / `input swipe` / `input text`; get exact
    coordinates from `adb shell uiautomator dump /sdcard/ui.xml && adb pull /sdcard/ui.xml`
    (the XML has every element's bounds). Tap -> screencap -> assert = a full UI test loop.
  - WebView console + JS errors (the insertBefore class): forward the webview CDP socket
    `adb forward tcp:9222 localabstract:webview_devtools_remote_<pid>` (pid from
    `adb shell pidof com.sudohnim.enqueue`), then `curl localhost:9222/json` for targets
    and drive the websocket with any CDP client - console exceptions, network, JS eval,
    all programmatic. This replaces "chrome://inspect needs a human".
  - App state + secrets: `adb shell run-as com.sudohnim.enqueue ...` (debug build) - read
    `sync_config`, `library.db` (sqlite3 via run-as if available, else `run-as ... cat`
    into a local file), `device_id`.
  - Permissions: `adb shell dumpsys package com.sudohnim.enqueue | grep CAMERA`.
  - Camera actually streaming: `adb shell dumpsys media.camera | grep -A2
    com.sudohnim.enqueue` shows an active camera client - proves the stream is live even
    though the camera SURFACE does not appear in screencaps.
  - Logs: `adb logcat -d | grep -i enqueue` (Rust panics, plugin errors).
  - Engine/desktop state: plain `curl 127.0.0.1:8787/...` and `sqlite3
    ~/.enqueue-poc/enqueue.db`; relay state: curl the relay URL.
ESCALATE TO HUMAN only for: (1) the camera-preview VISUAL containment check in SCANUI.1
(does the feed LOOK boxed - screencap cannot see the camera layer; but verify
camera-active + box geometry via dumpsys/uiautomator first, so the human only judges
aesthetics), and (2) the CAP2.2 capture-flight visual on the macOS desktop. Everything
else - linking, syncing, deleting, rendering, permissions, offline behaviour - is
agent-verifiable with the toolkit above. When escalating, state the single unanswered
visual question, not "please test the app".

- [x] **QR.1 [AGENT]** Desktop: passwordless key creation, DEK persisted in the macOS
  Keychain, auto-load on launch. Three sub-changes:
  1. Passwordless keygen. Change `keyring_file.initialize()` (`keyring_file.py:79`) to
     take NO password argument: generate the DEK, wrap it ONLY under the recovery-KEK,
     write `keyring.json`, return the recovery phrase. Call it automatically the first
     time sync is enabled (and lazily from QR.3's link-code path if no keyring exists
     yet), so no human ever types a password. The SU.2 endpoint's `{password}` input and
     the SU.3 form's password step are superseded - remove them.
  2. Keyring file format. `keyring.json` drops the password-KEK wrap slot entirely; the
     recovery-KEK slot is the only wrap. No migration of the password slot - existing
     keyrings are pre-release dev installs only: on finding an old two-slot file, re-
     initialize in place (fresh DEK + fresh recovery phrase, same destructive semantics
     as FIX.4's guarded reset) rather than carrying the password slot forward.
  3. Keychain persistence. After keygen (and on every unlock), store the raw DEK in the
     macOS Keychain (reuse the `keyring.py` `/usr/bin/security` pattern, a distinct
     service e.g. `enqueue-sync-dek`); on engine startup, load it from the Keychain into
     `_dek` so sync is unlocked with no user action. Remove the password-unlock path from
     the normal flow. Non-macOS: fall back to the existing app-data file (mode 0600),
     same as mobile (MOB.3b).
  Done when: on a fresh library, enabling sync creates the keyring with no password
  prompt and shows the recovery phrase once (the same one-time panel); after an engine
  restart the desktop is NOT locked (`keyring_locked: false` with no prompt) and sync
  push/pull work immediately; the DEK never sits in a plaintext file on macOS; a recovery
  code still exists for total-device-loss recovery; an old two-slot `keyring.json` is
  re-initialized in place behind the destructive confirmation.
  VERIFY: `uv run pytest -q` AND `bin/verify` green; then restart the engine
  (`bin/launch desktop`) and confirm `curl -s 127.0.0.1:8787/settings` shows
  `keyring_locked: false` with no prompt.

- [ ] **QR.2 [AGENT]** Point sync at a hosted relay. The relay service already exists
  (`src/enqueue/relay/app.py`, `enq relay`). This task is the config + docs to run it as
  a reachable host, not localhost: document deploying it (a small always-on host - the
  user picks the provider) and that `sync_relay_url` is the public URL; keep `enq relay`
  for local/dev. For DEVELOPMENT/testing without deploying, document a tunnel
  (cloudflared/ngrok) exposing the local `enq relay`, and have the QR encode that URL.
  The relay must require its Bearer secret over TLS in the hosted case. No relay code
  change beyond confirming CORS/host binding for a public deploy.
  DEV-LOOP CLARIFICATION (the "app only works plugged in" confusion): `bin/launch mobile`
  runs `cargo tauri android dev`, whose dev-server connection is USB-tethered by design -
  that is the dev harness, not the app. To verify the app works unplugged, build the apk
  (`cargo tauri android build --debug --target aarch64`), install it, then launch it from
  the phone with USB disconnected and confirm sync over the hosted/tunnelled relay. Add
  this distinction to `docs/sync-relay.md` so no future agent treats the USB tether as a
  product requirement.
  Done when: with the relay reachable at a non-localhost URL over the network, a phone
  NOT on the same machine/USB can pull and push; the unplugged-run path above is verified
  once on the physical phone; `docs/sync-relay.md` documents the hosted deployment, the
  dev tunnel, and the dev-harness-vs-app USB distinction.
  VERIFY: from a shell on the DESKTOP, `curl -s -o /dev/null -w "%{http_code}"
  -H "Authorization: Bearer <secret>" <public-relay-url>/...` returns a non-000 response
  (TLS handshake + auth reached); then a real phone push/pull over that URL.
  STATUS: NOT IMPLEMENTED - blocked (docs + code-confirmation + LAN verification DONE).
  `docs/sync-relay.md` now documents the hosted deployment, the cloudflared/ngrok dev
  tunnel, and the dev-harness-vs-app USB distinction (bin/launch mobile is USB-tethered
  by design; verify unplugged via the installed apk). Relay code confirmed: every
  endpoint requires the Bearer secret, binding is uvicorn's host param, and NO CORS is
  needed because all sync clients are native (Python httpx / Rust ureq; mobile.html has
  no browser calls to the relay). Live LAN verification passed: relay on 0.0.0.0:8899
  answered at <http://192.168.86.126:8899> - wrong secret 401, correct secret 200, PUT 201,
  GET returned the opaque bytes (non-localhost URL + auth + byte round-trip proven).
  The two remaining literal clauses were: (a) a PUBLIC URL - SUPERSEDED by RELAYHOST.1
  (Railway deploy, no tunnel tool needed); (b) "physical-phone push/pull needs scrcpy" -
  WRONG, superseded by the VERIFICATION PROTOCOL (top of this file): the agent drives the
  phone over adb (install/launch/tap/screencap/CDP) with no scrcpy and no display. QR.2's
  remaining work is fully covered by RELAYHOST.1; once that lands, close QR.2.

- [ ] **QR.3 [AGENT] - CODE RESTORED + COMMITTED (2026-08-18); only device-verify remains.**
  `desktop_link_code` was lost in a revert, then restored in commit `6fa0134` and committed
  (`fn desktop_link_code` present in `desktop/src/lib.rs`, registered in the desktop
  `generate_handler!`, emitting the pinned wire format `{"v":1,"relay_url","relay_secret",
  "dek"}`, permission `desktop_link_code.toml` + `home-links` capability reference it). It
  compiles (Android 0 errors) and the wire format was confirmed consistent with QR.4b's
  parser. Do NOT re-add it. What remains is verification, and MOST of it is headless per
  the VERIFICATION PROTOCOL: add a Rust test that calls the payload builder (or
  `desktop_link_code` directly) and asserts the decoded JSON is exactly the pinned wire
  format (keys `v`/`relay_url`/`relay_secret`/`dek`, base64 DEK, no extra keys), and that
  the rendered QR decodes back to that same JSON (decode the generated image with the
  `rqrr` crate - pure Rust, no display needed). The only human step: one glance that the
  QR visibly renders in the Settings UI on the launched desktop (a macOS-display check,
  same class as CAP2.2). Box stays unchecked until both pass.
  Original task text follows:
  Desktop: show the linking QR. Desktop Settings > Sync (once set
  up) shows a locally-rendered QR (Rust `qrcode` crate, no external service - reuse the
  FIX.2 path) encoding the Signal-style linking payload. Reveal-gated (the QR IS the key
  now - treat like a secret: no logging, warn the user not to share/screenshot).
  CAMERA-ONLY - there is NO copyable/pasteable fallback code, by decision (2026-08-16):
  the payload carries the raw DEK, and putting the raw key into a copy-paste string would
  expose it to the clipboard and clipboard history (the Paste-app leak class we already
  hit). The QR is the only transport; camera-scanning it is ephemeral and never stored,
  which is the whole reason key-in-code is acceptable here. Do NOT render, offer, or log a
  textual form of the payload anywhere. `desktop_pairing_code` becomes `desktop_link_code`
  and RETURNS ONLY the rendered QR (SVG/PNG), never the underlying string; update its
  permission + capability.
  WIRE FORMAT (pinned - QR.4 parses exactly this, do not improvise): the QR encodes
  UTF-8 JSON, compact separators, exactly these keys:
  `{"v":1,"relay_url":"https://...","relay_secret":"...","dek":"<base64>"}` where `dek`
  is standard RFC 4648 base64 (with padding) of the raw 32-byte DEK. `v` is the format
  version integer, `1` for this version; a parser that sees any other `v` must refuse
  with a clear message.
  Done when: the desktop shows a QR that encodes the pinned payload above, rendered with
  zero external network calls; a reveal gate guards it; no textual/copyable form of the
  payload exists anywhere in the UI or logs; scanning it (QR.4) links a phone.
  VERIFY: `cd desktop && cargo build` clean, then `bin/launch desktop`, open Settings >
  Sync, reveal the QR, and decode it with any phone camera app or `zbarimg` on a
  screencap - the decoded text must be the pinned JSON exactly.

- [ ] **QR.4a [AGENT]** Mobile: live camera feed in the setup screen (no decode yet).
  Scope is ONLY a working camera preview inside the Tauri webview - do NOT touch decode,
  storage, or the old setup fields in this task. A fresh install's setup screen shows a
  "scan the QR on your desktop" area with the live camera picture in it. Permissions -
  ALL THREE are needed, in this order, and a missing one leaves the camera dead with no
  error: (a) `CAMERA` in the AndroidManifest
  (`desktop/gen/android/app/src/main/AndroidManifest.xml`); (b) the Android runtime
  permission request (`ActivityCompat.requestPermissions`) before opening the camera;
  (c) the webview-side grant - the Kotlin `WebChromeClient` must override
  `onPermissionRequest` and call `request.grant(...)` for `RESOURCE_VIDEO_CAPTURE`, or
  `getUserMedia` in the Tauri webview is silently denied. Check how the generated Tauri
  Kotlin app wires its WebChromeClient first; if Tauri's default already grants, verify
  with a real camera call and say so. If permission is denied or there is no camera,
  show a clear "camera required to link this device" state with a retry button (never a
  paste box - QR.3 decision).
  Done when: on the physical phone, the setup screen shows a live camera preview; the
  permission prompt appears exactly once and the feed starts after granting; denying shows
  the "camera required" state with working retry; no decode/linking behavior exists yet.
  VERIFY: `cargo tauri android build --debug --target aarch64` zero errors, install, run
  on the physical phone with USB disconnected, screencap the live preview
  (`adb exec-out screencap -p > qr4a.png`) and attach to PROGRESS.md.
  REVIEW ON THE PHYSICAL PHONE (2026-08-18) - NOT WORKING, two concrete bugs; the setup
  screen shows a GRAY play-button placeholder, not a live feed:
  1. Missing permission layer (b): the runtime CAMERA permission is never requested. The
     manifest has `CAMERA` (a) and the generated `RustWebChromeClient.onPermissionRequest`
     already grants the webview layer (c), but nothing calls `ActivityCompat.
     requestPermissions` - so the OS permission stays `granted=false`
     (`adb shell dumpsys package com.sudohnim.enqueue | grep CAMERA` confirmed
     `granted=false` on a fresh install) and `getUserMedia` is denied. Add the runtime
     request (Kotlin `MainActivity`, or trigger it before `startCamera`).
  2. Video will not autoplay in the WebView: `#scan_video` (mobile.html ~line 831) has
     `autoplay playsinline` but NO `muted`, and `startCamera` calls `video.play()`
     without awaiting/catching it. Android WebView's autoplay policy blocks the unmuted
     play, so even AFTER granting camera (I granted it manually via
     `adb shell pm grant ... CAMERA` and relaunched - still the gray placeholder) the feed
     never renders. Add `muted` to the `<video>` (a getUserMedia stream is video-only, so
     muting is harmless) and `await video.play().catch(...)`.
  Both must be fixed before QR.4a's done-when can pass; QR.4b/QR.5 are gated behind a
  working feed. Everything else on the setup screen is correct (the "Point your camera at
  the QR" copy, the camera-only layout with no paste/password fields, and the pill).
  RE-VERIFIED ON PHONE (2026-08-18) AFTER THE AGENT'S FIX - STILL BROKEN. The agent added
  the runtime permission request (MainActivity) and `muted` + `await video.play().catch()`
  (mobile.html), and OS camera is `granted=true`, and the WebChromeClient
  `onPermissionRequest` correctly grants `VIDEO_CAPTURE` - yet the `<video>` still shows the
  gray play-button placeholder, no live frames. ROOT CAUSE (next lever): the fix was at the
  wrong layer. Android WebView's `WebSettings.mediaPlaybackRequiresUserGesture` defaults to
  TRUE, which blocks autoplay of a `<video>` - even a MUTED one - without a user gesture,
  BELOW the JS `muted` attribute; the `.catch(()=>{})` swallows the resulting play()
  rejection so it looks silent. FIX: set `mediaPlaybackRequiresUserGesture = false` on the
  Tauri/wry Android WebView (a native WebSettings flag - Tauri v2 may need an
  `on_webview_created`/Kotlin hook or a wry setting, since the JS layer cannot reach it).
  ESCALATED (2026-08-18): the WebSettings fix was applied (`RustWebView.kt` sets
  `settings.mediaPlaybackRequiresUserGesture = false`; note that file is AUTO-GENERATED, so
  the setting needs a durable home - a wry/tauri config or a build-time patch, not a
  hand-edit that regen overwrites) and the camera was re-tested on the physical phone: STILL
  the gray placeholder. All standard levers are now exhausted (CAMERA permission x3 layers,
  `muted`, `await video.play()`, and the gesture flag). Diagnosis is conclusive: the setup
  shows the CAMERA box, not the "camera required" fallback, so `getUserMedia` did NOT throw -
  it returned a stream - but the `<video>` never renders frames. This is a wry/Android
  WebView limitation: it does not composite a getUserMedia MediaStream to a `<video>`
  element. It is NOT fixable in JS or WebSettings. DECISION REQUIRED - do not keep patching
  the WebView:
   DECISION: (a) native scanner, chosen 2026-08-18. Use the OFFICIAL Tauri v2 plugin
   `tauri-plugin-barcode-scanner` (ML Kit on Android, AVFoundation on iOS) - do NOT hand-roll
   a CameraX/ML Kit Activity (standards over bespoke). This becomes the replacement for the
   getUserMedia camera in QR.4a; QR.4a's "live camera feed in the webview" goal is dropped.
   Implementation:
   1. Add the plugin: `tauri-plugin-barcode-scanner` in `desktop/Cargo.toml` + `.plugin(...)`
      in the mobile builder; `@tauri-apps/plugin-barcode-scanner` (or the `window.__TAURI__`
      bridge) on the JS side; add its permission to the mobile capability. PIN BOTH SIDES:
      the crate and the npm package must be exact versions whose major matches the project's
      Tauri v2 major - record the chosen versions in PROGRESS.md. It brings its own CAMERA
      runtime-permission handling - drop the manual `MainActivity.kt` `requestPermissions`
      and the `mediaPlaybackRequiresUserGesture` edit in the generated `RustWebView.kt` (both
      were for the dead getUserMedia path; this also CLOSES the durable-home question for
      that WebSettings flag - no durable home needed anymore). Keep the manifest `CAMERA`
      entry - the plugin requests at runtime but the manifest declaration stays. Use the
      plugin's `checkPermissions()` / `requestPermissions()` JS API before `scan()` if the
      plugin exposes one.
   2. ML KIT DELIVERY MODE (check before first scan, it decides fresh-install behaviour):
      the plugin uses ML Kit barcode scanning on Android, which exists in BUNDLED (model
      inside the apk, works offline) and UNBUNDLED (Play Services downloads the model on
      first scan, so a first scan can fail with no network) flavours. Read the plugin's
      docs/manifest to determine which ships; if unbundled, add the
      `com.google.mlkit.vision.DEPENDENCIES` manifest meta-data so the model downloads at
      install time, not at first scan. Record which mode it is in PROGRESS.md.
   3. Rewrite the mobile.html setup screen: replace the `<video>` preview + jsQR loop + the
      `getUserMedia`/`startCamera`/`startScanLoop` code with a single "Scan QR" button that
      calls the plugin's `scan({ formats: ["QR_CODE"] })`; on a result, parse the pinned wire
      format (`{v, relay_url, relay_secret, dek}`, refuse unknown `v`), then invoke
      `mobile_link_qr` (already fixed to `save_config` all fields) and sync. Remove the
      vendored `jsQR` and the camera-required/retry UI that existed only for getUserMedia.
      ERROR PATHS (the plugin scan opens a native Activity): the user backing out / cancelling
      returns to the setup screen SILENTLY (no error toast); a scan that decodes but fails the
      wire-format parse shows a "not an Enqueue code - scan the QR shown in desktop Settings >
      Sync" message with a scan-again button.
   4. Keep it camera-only, no paste box - the plugin IS the camera path, and the DEK never
      touches the clipboard.
   5. CLEANUP PROOF (grep these, zero hits required): no `jsQR` file under
      `src/enqueue/static/vendor/`, and no `getUserMedia`, `startCamera`, `startScanLoop`,
      `scan_video`, or `jsQR` references in mobile.html; `MainActivity.kt` back to its
      generated state (no manual permission block).
   6. GATE FIX (the Kotlin-blind spot this pivot makes urgent): `bin/verify`'s Android check
      is `cargo check --lib` (Rust only) and never compiles Kotlin/gradle - the plugin adds
      gradle dependencies, so broken Kotlin would pass the gate. Extend the Android check to
      run the full `cargo tauri android build --debug --target aarch64` (or at minimum a
      gradle compile of the app module) when `desktop/gen/android/**`, `desktop/Cargo.toml`,
      or any Kotlin file has changed vs the last green run; keep the fast Rust-only check
      otherwise. This closes the GATE GAP noted below, not just for this task.
   7. QR DENSITY (cross-requirement on QR.3's renderer, verify here): the wire-format payload
      is ~200-300 chars, so the desktop QR must be rendered with error-correction level M or
      higher and displayed at 240px minimum or the phone scanner locks slowly. Confirm against
      the committed QR.3 code; if it renders smaller or at EC level L, fix it there.
   COMMIT AFTER GREEN: the plugin touches Cargo.toml, gradle, and lib.rs - exactly the class
   of Rust work lost twice (see LOST-WORK RECOVERY MAP). Commit immediately after a green
   full build, before device verification.
   Done when (split per the VERIFICATION PROTOCOL): the AGENT verifies programmatically -
   on a fresh install, tapping "Scan QR" (uiautomator-driven) opens the native scanner,
   the camera client goes active (dumpsys), cancel returns silently to setup, a
   wrong-payload injection shows the "not an Enqueue code" state, first scan works with no
   manual model-download step, and the cleanup-proof greps are zero. The HUMAN's only
   irreducible step is the 10-second physical act: aiming the phone camera at the desktop
   screen showing the QR - an agent cannot point a camera. Everything after the scan
   (config persisted, sync lands, library renders) the agent verifies via run-as +
   screencap + CDP.
  (b) Paste fallback was REJECTED (puts the raw DEK on the clipboard - the leak QR.3 avoided).
  DEVICE-VERIFIED 2026-08-18 - THE NATIVE PIVOT WORKS, one wiring fix left. Tapping "Scan
  QR" fires the plugin: logcat shows GMS resolving the ML Kit barcode modules
  (`MlkitBarcodeUi`, `VisionBarcode`) and the camera HAL activating - so the native scanner
  is genuinely running (unlike getUserMedia, which the WebView could never render). BUT no
  camera preview is visible: `tauri-plugin-barcode-scanner` on Android renders the CameraX
  preview BEHIND a transparent WebView, and the scan handler in `mobile.html` (~line 2036,
  `invoke("plugin:barcode-scanner|scan", ...)`) does NOT make the page transparent, so the
  opaque setup screen covers the camera and the user scans blind with nothing to aim.
  FIX (small, in mobile.html): before calling `scan()`, set the document/body background to
  transparent (e.g. add a `scanning` class that sets `html,body { background: transparent }`
  and hides the opaque setup UI), and show a minimal overlay - a scan-frame + a Cancel
  button that calls `plugin:barcode-scanner|cancel`. Restore the background/UI in a `finally`
  after the scan resolves, errors, or is cancelled. Then the camera shows through and the
  user can aim at the desktop QR. Everything else is correct (plugin added, getUserMedia/
  jsQR/`<video>` removed, "Scan QR" button, `mobile_link_qr` wired). After this fix the
  human re-verifies a real scan->link->sync on the phone.
  Also note a GATE GAP found here: the earlier broken `MainActivity.kt` webSettings edit
  (`webView.webSettings` / `android.R.id.web` - unresolved refs) compiled clean under
  `bin/verify` because its Android check is `cargo check --lib` (RUST ONLY) and never
  compiles the Kotlin. bin/verify's Android check should run the full `cargo tauri android
  build` (or a Kotlin/gradle compile) when Kotlin/`gen/android` files change, or Kotlin
  breakage keeps passing the gate. (The broken MainActivity.kt block was removed during this
  review so the apk builds; the durable-home question for the WebSettings flag stands.)
  RISK TO THE CAMERA-ONLY DECISION: if getUserMedia video cannot
  be made to render in the wry Android WebView, the camera-only setup has no path (we
  removed the paste fallback to keep the DEK off the clipboard). If the WebSettings flag
  does not fix it, escalate the decision: (a) a native QR scanner (ML Kit / a scanner
  Activity) feeding the payload to `mobile_link_qr` instead of getUserMedia, or (b)
  reconsider a guarded paste fallback. Do NOT keep patching the JS layer.

- [ ] **QR.4b [AGENT]** Mobile: link path + wire-format parse + password-field removal.
  SUPERSEDED SCOPE (2026-08-18): the original QR.4b was the jsQR/BarcodeDetector decode
  path over QR.4a's webview camera feed - BOTH are dead (getUserMedia does not composite
  in the wry WebView; QR.4a pivoted to `tauri-plugin-barcode-scanner`, whose native
  scanner returns the decoded string directly). DO NOT build jsQR, BarcodeDetector
  detection, canvas frame-grabbing, or any webview decode - none of it exists anymore.
  What remains of QR.4b is exactly three things:
  1. THE `mobile_link_qr` FIX (do this FIRST - it is headless-verifiable via the adb
     injection path in the dependency graph, no camera needed; see the REVIEW note below
     for the exact breakage and fix).
  2. The wire-format parse on the scan result: UTF-8 JSON, exact keys
     `v`/`relay_url`/`relay_secret`/`dek`, refuse unknown `v` with a clear message,
     base64-decode the DEK, pass to `mobile_link_qr`, trigger sync. This parse lives in
     QR.4a's setup-screen rewrite; this task owns making it correct.
  3. CAMERA-ONLY - REMOVE the paste-code AND library-password fields entirely. There is
     no pasteable fallback (QR.3 decision: the raw DEK must never touch the clipboard).
     Setup is scan-the-QR and nothing else; no password is ever entered on the phone.
  Done when: the adb-injection path (`mobile_link_qr` with a valid payload) reaches a
  fully synced state with relay URL + secret + DEK all persisted via `save_config`;
  scanning the real desktop QR end to end links + syncs the library with NO typing; a
  payload with unknown `v` is refused with a clear message; there is NO paste-code or
  password field anywhere in mobile.html.
  REVIEW 2026-08-18 - `mobile_link_qr` (desktop/src/lib.rs) is BROKEN at the link step,
  independent of the camera (found by code inspection while trying to verify the sync half):
  (1) it stores the DEK to `$HOME/.enqueue-poc/sync-dek.bin` (base64, a desktop-style path
  that does not exist on Android), but the whole mobile module reads config via
  `load_config` -> `app.path().app_data_dir()` with the DEK stored AS HEX INSIDE the config
  (`cfg.get("dek")...dek_from_hex`); so the DEK is written where nothing reads it. (2) It
  parses `relay_url` + `sync_secret` but NEVER persists them (no `save_config` call), so
  after "linking" `load_config` has no relay URL, no secret, and no DEK-in-config - sync
  cannot find the relay or the key. It returns `"linked"` while nothing is actually
  configured. FIX: mirror the old `mobile_pairing_setup` - call
  `save_config(&app, relay_url, sync_secret, keyring_json_or_empty, &dek)` so relay + secret
  + DEK (hex, in `app_data_dir`) are all persisted the way `load_config`/the sync path
  expect. Then trigger a sync (or confirm the bootstrap does). This must be fixed for QR.4b
  regardless of QR.4a's camera - a working camera would link to nothing today.
  VERIFY: `cargo tauri android build --debug --target aarch64` zero errors, install, run
  unplugged, scan the real desktop QR end to end, confirm the library appears on the
  phone; grep mobile.html for `pairing`/`password` inputs - zero hits outside comments.

- [ ] **QR.5a [AGENT]** Mobile: non-blocking sync (background thread + progress events).
  WHERE THE CODE IS (anchors, do not search blind): the sync engine is Rust,
  `desktop/src/sync.rs::sync_library`; it is invoked synchronously from the
  `mobile_sync` Tauri command (`desktop/src/lib.rs:113`), which mobile.html awaits - that
  await is what freezes the UI. Scope of THIS task is only the threading: `mobile_sync`
  spawns `sync_library` on a background thread (`std::thread::spawn` or tauri
  `async_runtime`), returns immediately, and reports progress/completion to the webview
  via `app.emit(...)` events (`sync-started` / `sync-progress` / `sync-done` /
  `sync-error`); mobile.html listens for the events instead of awaiting the command. The
  "Syncing…" indicator is driven by those events, so it clears on `sync-done` (it
  currently sticks - see QR.7). Guard against double-spawn: a second `mobile_sync` while
  one is running returns the in-flight status instead of starting a parallel sync. Do NOT
  do the foreground service or resume triggers here - that is QR.5b.
  Done when: with a multi-hundred-artifact library syncing, the phone UI scrolls,
  captures, and reads with no freeze; the indicator appears on `sync-started` and clears
  on `sync-done`; tapping Sync Now twice does not run two syncs.
  VERIFY: `cargo tauri android build --debug --target aarch64` zero errors, install, run
  unplugged; trigger a sync and screencap mid-sync scrolling; `adb logcat` shows the
  emit sequence started -> done exactly once per sync.

- [ ] **QR.5b [AGENT]** Mobile: lock/background resilience + resume triggers. Builds on
  QR.5a's threaded sync. Two changes:
  1. Lock/background resilience: an Android FOREGROUND SERVICE (decided - not
     WorkManager; the sync is short, user-triggered, and WorkManager's deferral is the
     wrong semantic) runs while a sync is active, with a persistent notification, so the
     process survives screen-lock and backgrounding. Start it when a sync begins, stop it
     when the cursor is caught up. This lives in the Kotlin side
     (`desktop/gen/android/app/src/main/java/.../`); declare the service +
     `FOREGROUND_SERVICE` permission in the manifest. The QR.5a background thread keeps
     running inside the service-held process.
  2. Resume: re-trigger sync on app resume/`visibilitychange` and on network-regained
     (ConnectivityManager callback, or the webview `online` event if simpler), so an
     offline capture pushes when the network returns. Sync must NOT require USB (hosted
     relay, QR.2).
  Done when: locking the screen mid-sync and returning loses nothing and the sync
  completes; backgrounding the app mid-sync does not abort it (the foreground-service
  notification is visible while active and gone when caught up); airplane-mode capture
  pushes when the network returns with no manual retry.
  VERIFY: `cargo tauri android build --debug --target aarch64` zero errors, install, run
  unplugged; three device tests matching the three done-when clauses, screencap the
  persistent notification, attach to PROGRESS.md.

- [x] **QR.6 [AGENT]** Loader transparency (desktop AND mobile). The spinning-raven
  loader shows a gray transparency-checkerboard behind it - a non-transparent PNG
  (same class as the old `capture-bird.png` checkerboard). THE ASSET IS
  `src/enqueue/static/loading.png`. It is referenced from: desktop `util.js spinner()`
  (util.js:121), and mobile.html three times (`#loading` first-sync screen ~line 959,
  `#chat_loading` ~line 1093, the pdf.js loading spinner ~line 1977). Fix `loading.png`
  so its background is truly transparent (regenerate or alpha-key it; do NOT swap in a
  CSS white/black box), and confirm all four call sites pick it up (they share the one
  file - no code change expected, but check none of them sets an opaque CSS background
  behind the img). Verify on the light canvas - no gray box.
  Done when: the loading raven has a transparent background on desktop and mobile; a
  screenshot on each shows no checkerboard/gray box.
  VERIFY: `bin/verify` green; then a pixel check - open the fixed PNG
  (`uv run python -c "from PIL import Image; im=Image.open('src/enqueue/static/loading.png').convert('RGBA'); print(im.getpixel((0,0)))"`)
  and confirm corner alpha is 0, plus one screencap each of the desktop spinner and the
  mobile first-sync loader on the light canvas.

- [x] **QR.7 [AGENT]** Mobile UI: the bottom bar is cut off and there is no pill. The
  reporter's screenshot shows the "Capture" button clipped at the bottom and no floating
  pill like desktop (MOB2.3 specified one). THE SCREENSHOT IS NOT IN THE REPO - first
  reproduce on the physical phone (`bin/launch mobile`, screenshot via
  `adb exec-out screencap`) to see the current geometry; if it does not reproduce, ask
  the user for the screenshot before touching markup. Fix the mobile bottom surface in
  `mobile.html`: render the MOB2.3 pill (capture in `--purple-bold`, search, the living
  raven eye, menu - mirror the desktop `pill.css` anatomy), padded with
  `env(safe-area-inset-bottom)` so nothing is clipped on a notched/gesture-nav phone, and
  check the webview viewport is not laid out under the system bars
  (`android:fitsSystemWindows` / edge-to-edge handling in the Tauri Android config).
  Reconcile with any existing bottom-bar markup (remove the clipped bar).
  Done when: the mobile bottom pill renders fully above the gesture bar / safe area,
  nothing is clipped, and it mirrors the desktop pill's anatomy; before/after screencaps
  are in PROGRESS.md.
  VERIFY: `bin/verify` green, `cargo tauri android build --debug --target aarch64` zero
  errors, then on the physical phone `adb exec-out screencap -p > qr7-after.png` showing
  the full pill above the gesture bar, attached to PROGRESS.md.

## Phase FULLSYNC - initial full-library backfill (found live 2026-08-18)

- [ ] **FULL.1 [AGENT]** Sync only pushes artifacts on WRITE (`sync/client.py::push_artifact`
  is called per-artifact when one is created/edited). There is NO initial backfill, so a
  freshly-linked device (or a fresh relay) only ever receives notes captured AFTER linking -
  the existing library never syncs. Confirmed live: desktop had 136 artifacts, the relay had
  2. The user's reasonable expectation ("syncing should sync all the contents") is unmet.
  Build a full-library push: when sync is first enabled (and idempotently on demand - a
  "sync now / push all" action), iterate every non-deleted artifact and `push_artifact` it
  (skip already-present objects via the relay's 409/idempotent PUT, so re-runs are cheap).
  Run it off the main path (the existing `Worker`) so it does not block. The pull side
  already applies whatever objects exist, so once the backfill lands, a new device pulls the
  whole library. Verify: on a fresh relay + fresh phone, after linking the phone shows the
  FULL desktop library, not just post-link captures.
  Done when: enabling sync (or triggering "push all") uploads every existing artifact, a
  freshly-linked phone receives the entire library, and re-running the backfill is a cheap
  no-op (no duplicate objects).

## Phase MOBRENDER - the phone pulls but never displays

- [ ] **MOBRENDER.1 [AGENT]** After linking, the phone shows only a stuck "Syncing…" spinner
  and NO artifacts, even though the pull is working. Verified live 2026-08-18: a desktop note
  reached the relay and DECRYPTS correctly with the DEK from the scanned QR (so pull + key +
  decrypt are all fine); the phone polls the relay at its caught-up cursor. So the data
  arrives - it just never renders. Two symptoms, likely related: (1) the "Syncing…" indicator
  never clears when the cursor is caught up (QR.5a's non-blocking sync left the status stuck);
  (2) applied snapshots do not appear in the library list. Debug with the WebView console
  via the CDP recipe in the VERIFICATION PROTOCOL (adb forward + CDP client -
  programmatic, NOT `adb screencap`, no human at chrome://inspect): confirm whether
  `apply_snapshot` writes the row to the local SQLite and whether `renderLibrary()`
  runs/throws (an earlier `insertBefore` NotFoundError was seen in this exact list
  render). Fix the render so pulled artifacts show, and clear "Syncing…" once caught up.
  DEPENDS ON QR.5a: the "Syncing…" indicator is driven by QR.5a's
  `sync-started`/`sync-done` events - if QR.5a is not landed, land it first or this
  task's indicator fix has nothing to listen to. The sync must also be BIDIRECTIONAL, not
  just desktop-to-phone: a note captured ON THE PHONE must push to the relay and appear
  on the desktop (the Rust `push_snapshot` path in `desktop/src/sync.rs` exists - confirm
  the phone's capture flow calls it, and the desktop pull applies it).
  Done when: after linking, pulled artifacts appear in the phone's library (title + body)
  and the "Syncing…" state ends when the cursor is caught up; a note captured on the
  desktop after linking shows up on the phone; AND a note captured on the phone shows up
  on the desktop after its next pull. (Depends on FULL.1 for the EXISTING library to
  appear too.)
  VERIFY: `cargo tauri android build --debug --target aarch64` zero errors; then on the
  physical phone with the webview CDP forwarded (VERIFICATION PROTOCOL recipe): linking
  renders the pulled library (console shows `renderLibrary()` completing, zero
  exceptions), "Syncing…" clears at caught-up cursor; then one capture in EACH direction
  confirmed visible on the other device.

## Phase SCANUI - contain the scanner camera in a box

- [ ] **SCANUI.1 [AGENT]** The native scanner (QR.4a) works but the camera fills the WHOLE
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

## Phase GATE - close the Kotlin/APK hole in bin/verify

- [ ] **GATE.1 [AGENT]** `bin/verify`'s Android check only runs `cargo check --lib
  --target aarch64-linux-android` - RUST ONLY. It never compiles the Kotlin
  (`gen/android/**/*.kt`, MainActivity, generated wry classes) or assembles the APK, so a
  Kotlin error passes the gate green while `cargo tauri android build` fails. This already
  bit us twice (the broken `mobile_scan_qr` era, and the QR.4a `MainActivity.kt`
  `webView.webSettings` edit that shipped "green"). Change the Android check so it catches
  Kotlin/gradle breakage: run the full `cargo tauri android build --debug --target aarch64`
  (authoritative but ~2min), OR a faster gradle `:app:compileDebugKotlin` /
  `assembleDebug`, when Rust/Kotlin/`desktop/gen/android` files are staged; keep the clean
  SKIP when no Android toolchain is present (GATE stays usable on non-mobile machines).
  Update the pre-commit hook path if needed so a Kotlin break blocks the commit like a Rust
  break does.
  Done when: a deliberately broken `.kt` (e.g. an unresolved reference in MainActivity.kt)
  makes a plain `./bin/verify` FAIL (not just a Rust break); it still skips cleanly with no
  Android toolchain; and `docs`-only commits stay instant.

## Phase LINKSTAY - scan once, stay linked (found live 2026-08-19)

DIAGNOSIS (confirmed via adb on the plugged-in phone): the link DOES persist -
`sync_config` (relay_url, secret, DEK hex) sits in the app data dir and bootstrap
(`mobile.html bootstrap()`) reloads it on launch. The rescan symptom is NOT lost
persistence: the scanned QR baked `relay_url: http://127.0.0.1:8788` into the config,
and loopback only reaches the desktop relay while `adb reverse` is active (USB plugged).
Unplug -> relay unreachable -> sync fails -> the phone LOOKS unlinked, so the user
rescans (while plugged in, so it works again). Two fixes: the QR must carry a reachable
URL, and transient sync failure must never look like an unlinked phone.

- [~] **LINKSTAY.1 [AGENT]** Refuse to bake an unreachable relay URL into the link QR (pending human verify - loopback error shown in desktop UI). Implemented: is_loopback_or_private_url() check in desktop_link_code. cargo build + android build green.
  In `desktop_link_code` (`desktop/src/lib.rs`), before rendering: read the configured
  `sync_relay_url`; if it is loopback/127.0.0.1/localhost/LAN-private (192.168/10.x/
  172.16-31), do NOT render the QR - return an error string the Settings UI shows:
  "This relay URL is only reachable from this Mac. Set a hosted relay URL first
  (Settings > Sync, see docs/sync-relay.md), then show the QR again." The QR exists to
  link a phone that will leave the house; a loopback QR is a broken promise.
  Done when: with a loopback relay URL, Settings > Sync shows the error instead of a QR;
  with a hosted URL set, the QR renders and its decoded payload contains that URL.
  VERIFY: `cd desktop && cargo build` clean; `curl -s -X POST 127.0.0.1:8787/...` (or the
  UI) with a loopback URL returns the error string; set a dummy public URL and decode the
  QR to confirm it carries it.

- [~] **LINKSTAY.2 [AGENT]** Sync failure must never look unlinked (pending human device-verify - phone cold-launch with USB detached). Implemented: offline_banner with Re-link button, sync-error no longer alerts, sync-started/done manage banner visibility. cargo tauri android build green.
  (a) `bootstrap()` shows the LIBRARY (from the local SQLite copy) whenever
  `mobile_status` reports configured, regardless of whether sync then succeeds - sync
  failure shows a small offline/"last synced X ago" banner, never the setup screen;
  (b) the `sync-error` handler must NOT `alert()` (an alert per failed background sync
  is spam when the relay is unreachable) - log to console + update the banner instead;
  (c) add a "re-link (scan again)" action in Settings so re-scanning is an explicit
  choice, not something the app forces by dumping the user into setup.
  Done when: phone unplugged from USB (relay unreachable), app relaunch shows the cached
  library + offline banner, zero alerts, no setup screen; plugging back in (or hosted
  relay up) syncs without rescanning.
  VERIFY: `cargo tauri android build --debug --target aarch64` clean; on the phone with
  USB detached: cold-launch the app, screencap the library-with-banner; reattach network
  path, confirm sync resumes with no scan.

## Phase RELAYHOST - run the relay on a public host (the "external database")

The user asked "do I need an externally hosted database?" - answer: not a database, the
EXISTING dumb relay (`src/enqueue/relay/app.py`, `enq relay`) on a public host. It stores
only ciphertext blobs, so the smallest always-on box is enough. Host chosen 2026-08-19:
Railway (user has an account; managed TLS + domain + restarts). QR.2's docs cover the
options (VPS, cloudflared tunnel); this phase is the atomic Railway recipe.

- [ ] **RELAYHOST.1 [HUMAN+AGENT]** Deploy the relay on Railway (chosen 2026-08-19 -
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

## Phase CRUDSYNC - all mutations propagate both ways

Current state (verified in code 2026-08-19): snapshots carry `deleted_at` and the mobile
apply path (`desktop/src/sync.rs:322`) honors it, so tombstones CAN propagate - but the
desktop only pushes on note create/edit (`notes.py:74,157`). Nothing pushes on delete,
restore, purge, pin, tag, or annotate. Mobile has no delete UI at all (only captures go
to `capture_outbox`).

- [~] **CRUDSYNC.1 [AGENT]** Desktop: every mutation pushes (pending human device-verify - relay object count confirmation). Implemented: push_artifact() on delete/restore/pin/tag/annotate/capture in trash.py, tags.py, notes.py, capture.py, api/artifacts.py. bin/verify green, 459 tests pass. Audit every write path and
  hook `push_artifact` (the existing notes.py pattern: import inside the function, push
  after commit): `trash.py` `delete()` / `restore()` / `purge_one` / `empty`; the pin /
  tag / annotation writers in `api/artifacts.py` and `notes.py::annotate`; capture
  creation in `capture.py`. Rule: any function that writes a column that the snapshot
  carries must end with `push_artifact(id)`. Purge note: a purged artifact has no row to
  snapshot, so the other device keeps its trashed copy - acceptable; document this in
  docs/sync-relay.md ("purge is local-only and final").
  Done when: deleting, restoring, pinning, tagging, and annotating on the desktop each
  produce a relay object for that artifact (relay object count increments per action).
  VERIFY: `bin/verify` green; then against a scratch relay: delete one artifact and
  confirm the relay gains an object whose decrypted snapshot has `deleted_at` set (reuse
  the decrypt helper from the SU.7/FULL.1 testing).

- [~] **CRUDSYNC.2 [AGENT]** Mobile: delete + restore propagate (pending human device-verify - cross-device sync confirmation). Implemented: mutation_outbox table, mobile_delete/mobile_restore commands, mobile_outbox_push processes mutations. cargo tauri android build green. (a) Add a trash action
  on the phone (long-press a card or a button in the reader - match the existing mobile
  idiom): writes `deleted_at` on the local row AND enqueues a mutation into
  `capture_outbox` (extend its schema with the fields needed, or add a sibling
  `mutation_outbox` table - whichever is simpler; the push path must upload the updated
  snapshot for that artifact id). (b) `mobile_outbox_push` already runs on `sync-done` -
  make sure mutation entries flow through it. (c) Pulled tombstones must HIDE the
  artifact from the library list (the list query already filters `deleted_at IS NULL` -
  confirm it applies after a pull that deletes). Restore works the same in reverse.
  Done when: delete on phone -> desktop trash shows it after its next pull; delete on
  desktop -> phone library hides it after sync; restore propagates both ways.
  VERIFY: `cargo tauri android build --debug --target aarch64` clean; one delete in EACH
  direction confirmed on the other device; `bin/verify` green.

## Phase MOBUI1 - pill menu cleanup + the insertBefore crash (from ui-bug.png)

Screenshot findings: the pill exists and renders, but its overflow menu
(`#pill_menu_panel`, mobile.html:862) floats above it holding Settings + Trash - user
direction: Trash moves INTO the Settings page, the pill menu keeps only Settings. The
cut-off error is `NotFoundError: Failed to execute 'insertBefore' on 'Node'` from the
card render.

- [~] **MOBUI1.1 [AGENT]** Trash lives in Settings only (pending human device-verify - phone screencap). Implemented: removed pill menu Trash button, Settings > Trash shows live list with Restore per item. bin/verify green. (a) Remove the Trash button from
  `#pill_menu_panel` (and its listener), leaving Settings as the only menu item.
  (b) Make the existing Settings > Trash row (mobile.html:1276, handler currently
  `alert("not yet implemented")` at :2666) open a real trash view: list trashed artifacts
  (title + deleted date) via a new `mobile_trash_list` command reading the local SQLite
  (`deleted_at NOT NULL`), each row offering Restore (wires into CRUDSYNC.2's restore).
  Purge stays desktop-only (matches CRUDSYNC.1's local-final rule).
  Done when: the pill menu shows only Settings; Settings > Trash opens a working trash
  list; restore from it propagates per CRUDSYNC.2.
  VERIFY: `bin/verify` green + phone: open the menu (screencap - one item), trash one
  note, see it in Settings > Trash, restore it, see it back in the library.

- [~] **MOBUI1.2 [AGENT]** Fix the insertBefore NotFoundError (pending human device-verify - phone CDP console check). Implemented: append kindDot before insertBefore in all three card renderers. bin/verify green. mobile.html:1458/1512/1562
  call `li.insertBefore(thumb, kindDot)`, but `kindDot` is not a child of `li` (it is
  appended to a different container), so every image/note card with a thumbnail throws
  NotFoundError - this is the error in the screenshot, and it aborts the render loop
  mid-list (the same failure MOBRENDER.1 saw). Fix: put the thumbnail where it belongs
  with a safe call - `content.prepend(thumb)` or append in the intended order - no
  insertBefore against a non-child. Same fix all three sites.
  Done when: a library containing image artifacts renders every card with zero console
  exceptions (seen via the CDP recipe) and no on-page Error text.
  VERIFY: `bin/verify` green; on the phone, webview CDP forwarded (VERIFICATION PROTOCOL)
  shows a clean console while scrolling the full library; screencap showing no error text.

## Out of scope

Same boundaries as before (now recorded in `AGENTS.md` decision #11): no model
enrichment on the phone; one person / one library (no multi-user); iOS is a follow-on;
the relay is additive (sync off = desktop unchanged); `saved_pivots` and chats do not
cross the relay.
