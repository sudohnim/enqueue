# PLAN.md - open work

Swept 2026-08-28: finished work folded into AGENTS.md and README.md; git history holds the raw detail.

## How to execute (read first, every agent)

This file is the only work queue.
Do one task per turn.
Each task block is self-contained: pre-conditions, exact files/lines, exact tokens/CSS, exact verify commands, exact "Done when".

1. **Read AGENTS.md first** - especially "Verifying the Android app on a device (headless, over adb)". It is the authority on emulator vs phone, CDP, screencap, run-as, and when to escalate to a human.
2. **Headless-first.** Almost every mobile task is verifiable with NO phone attached. Boot the headless emulator (`bin/launch emulator`), install the debug apk, drive over CDP + screencap. Only the physical camera-aim and a final aesthetic glance need a human.
3. **Read app state with `bin/cdp-eval`, never a hand-rolled websocket loop.** `bin/cdp-eval "<js expr>"` does the pid/forward/suppress_origin/awaitPromise dance with a baked-in timeout so it cannot hang. A bare `ws.recv()` in a fixed-count loop blocks for the whole command budget (observed 3000s) when CDP sends fewer messages than assumed. Need more? add a flag to the helper.
4. **`bin/verify` is the gate, not the proof.** It runs JS parse, pytest, contrast, Android compile - all headless. Green `bin/verify` proves the code parses/tests/compiles; it does NOT prove the app runs. The emulator or phone is the only runtime proof.
5. **A UI claim is only true if you READ the rendered pixels.** Pixel-count heuristics ("N colorful pixels = it renders") are how broken UI keeps passing - the eye blob and the sun-gear both passed a count. Screencap it and look, or measure the actual DOM box over `bin/cdp-eval`.
6. **Marking done.** `[x]` only after "Done when" is met AND `bin/verify` is green AND the runtime claim is eyeballed. `[~]` = code-complete, awaiting rebuild/device-verify. `[ ]` = not started.
7. **Never commit/stage on the user's behalf.** Make working-tree changes and stop; the user reviews the raw diff and commits.
8. **Caveman mode on for this repo.** Code, commits, PRs, security warnings: write normal. Everything else: terse.

## Context

Sync, E2E, the QR device-linking flow, and the Android app are built; the sync/decrypt/apply/render path is device-verified end to end.
Durable context lives in AGENTS.md (the sync/relay/E2E model, the relay-immutability limitation, the device-verify protocol, `bin/cdp-eval`) and README.md.
This file holds only OPEN work.

A batch of fixes sits UNCOMMITTED in the working tree (both `mobile.html` copies, kept in sync).
None are baked into the installed apk yet - the emulator still runs old CSS.
The gating next step is MOBFIX.7: commit, rebuild the debug apk, install, then device-verify each fix by reading pixels.

## Phase MOBFIX.7 - commit + rebuild + device-verify the working-tree batch (DO THIS FIRST)

- [ ] **MOBFIX.7 [AGENT]** The following fixes are code-complete in the working tree but NOT baked into the apk and NOT device-verified. One rebuild verifies them all.
  Working-tree fixes to verify:
  - **eye blob (MOBILEUI.6)** - `.pill .pill-eye` was missing `position: relative`, so the absolute `.eye-socket` sized against a distant ancestor (141px) and painted a purple blob. Fixed 2026-08-28; live-proven over CDP (socket 141x39 -> 35x30, eye draws frame+pupil). Bake it.
  - **MOBILEUI.3** - cards square (`.row` `aspect-ratio: 1`, grid container).
  - **MOBILEUI.4** - kind-based card accents (`--kind-*` tokens).
  - **MOBFIX.3** - `#pill_menu_camera` -> `mobile_capture_camera` (live camera, not gallery). Kotlin/Rust committed in `8b4e0a2`; JS wiring uncommitted.
  - **MOBFIX.6** - launcher icon alpha-mask crop (raven fills icon).
  - **QRSCANFIX.1** - `errString(e)` helper (no more "[object Object]").
  Steps:
  1. User commits the working tree (agent stops at the diff).
  2. Build: `cd desktop && cargo tauri android build --debug --target aarch64`.
  3. Install: `adb install -r desktop/gen/android/app/build/outputs/apk/arm64/debug/app-arm64-debug.apk`.
  4. Verify each by READING pixels / measuring the DOM (not pixel counts):
     - eye: screencap the pill - a real eye (frame + pupil inside the lid), not a blob; `bin/cdp-eval "(()=>{const r=document.querySelector('#pillEye .eye-socket').getBoundingClientRect();return Math.round(r.width)+'x'+Math.round(r.height);})()"` ~35px wide.
     - MOBILEUI.3: `bin/cdp-eval "(()=>{const r=document.querySelector('.card').getBoundingClientRect();return (Math.abs(r.width-r.height)<1);})()"` -> true.
     - MOBILEUI.4: `bin/cdp-eval "getComputedStyle(document.querySelector('.card')).borderTopColor"` != the default border.
     - MOBFIX.3: `+` > Camera opens the camera Activity (`adb shell dumpsys media.camera`), captures a photo.
     - MOBFIX.6: screencap the launcher - raven fills the inner circle, no clipped wingtips.
     - QRSCANFIX.1: open scanner, Cancel -> status stays clean (no "[object Object]").
  Done when: all six confirmed on the emulator by eyeballing pixels / measuring the DOM; recorded in PROGRESS.md.

## Phase SETUPBTN - stale "back to Setup" button on the library header

- [ ] **SETUPBTN.1 [AGENT]** A configured, booted device shows a `<- Setup` back-button as the primary header element on the Library screen (`src/enqueue/static/mobile.html:1028`, `<button class="back" id="to_setup">`).
  It offers "go back to setup" from the home screen, which is wrong now that gear -> Settings is the real path and re-linking lives in Settings.
  Fix: hide `#to_setup` when the device is configured (only show it during the first-run/unconfigured flow), OR remove it entirely and reach re-link through Settings.
  Decide which with the user before ripping it out - re-linking must stay reachable somewhere.
  Done when: a configured cold launch shows the Library header with NO stray "Setup" button; setup is still reachable on an unconfigured device. Verify on emulator screencap.

## Phase MOBFIX.5 - sync is create-only (the big architectural fix)

- [ ] **MOBFIX.5 [AGENT]** Mutations to an already-synced artifact (delete, edit, pin, tag, restore) do NOT propagate. Device-verified broken 2026-08-27: deleted a note on desktop, the relay object still decrypts to `deleted_at=None`, the phone kept it.
  ROOT CAUSE (architectural): the relay is IMMUTABLE BY OBJECT NAME. `put_object` (`src/enqueue/relay/app.py:100`) raises 409 on an existing name, and names are id-based with no version (`sync/client.py:75`, `desktop/src/sync.rs:176` -> `dev/{device}/artifacts/{id}.enc`). A second PUT for the same id 409s, so the updated snapshot is silently refused. The pull's LWW-by-`(updated_at, device_id)` is moot because the newer snapshot never lands.
  The prior "bump `updated_at` in trash.py" change is necessary-but-insufficient: the name is id-based, so bumping `updated_at` does not change the name, so the PUT still 409s. Keep it, but it does nothing until the relay accepts the overwrite.
  FIX - decide the approach, then apply on the Python push (`sync/client.py`), the Rust mobile push (`desktop/src/sync.rs`), and the relay:
  - (a) PREFERRED - make the per-artifact object MUTABLE: `PUT dev/{device}/artifacts/{id}.enc` overwrites (LWW at storage). Move `push_all`'s "409 = skip" economy client-side (compare `updated_at` before pushing).
  - (b) ALT - versioned names (`...{id}-{updated_at}.enc`): every snapshot is a new object (always 201); pull takes latest-per-id by LWW; needs GC of superseded versions.
  CURSOR SUBTLETY (why this is not just "remove the 409"): the pull is cursor-based (`GET /sync/objects?since=N`). An overwritten object (option a) must get a NEW higher sequence number on write, or a device whose cursor already passed it never re-pulls the update. So an overwrite must move the object to the head of the since-ordering. Option (b) sidesteps this (each version is new at the head) but adds GC.
  Not a quick patch - touches relay storage + cursor ordering + both push clients + `push_all`. Do it as a deliberate pass, not inline with UI work.
  Done when: delete on desktop -> note disappears from the phone after its next sync (relay object decrypts to `deleted_at` set); an edit on desktop -> the edit appears; restore reverses it; a device that ALREADY synced the artifact receives the update on its next pull. Add a regression test asserting `lww_key(tombstone) > lww_key(live)`. Verify by the decrypt-the-relay-object + phone run-as check that found this.

## Phase SCANUI - contain the scanner camera in a box

- [~] **SCANUI.1 [AGENT->HUMAN]** Implemented: `boxSize: 260` passed to the scan invoke, opaque body during scan, `.scan-backdrop` dark overlay with a transparent center cutout. Code committed, `bin/verify` green.
  AWAITING: one human glance that the camera preview looks boxed (the camera layer is invisible to screencap).

## Phase BACKFILL - auto-backfill on sync-enable

- [~] **BACKFILL.2 [AGENT]** Implemented: `store_sync_secret` triggers `push_all()` on a background thread when the DEK is loaded, guarded by a one-shot `sync_backfill_done` flag. `bin/verify` green.
  Verify: point the desktop at a scratch relay, set the secret, confirm the relay gains the syncable count with no manual push, and that it does NOT re-scan on every launch. Record in PROGRESS.md.

## Phase DESKTOPUI - desktop settings + chat polish

- [~] **DESKTOPUI.6 [AGENT]** Real Feather cog put into `icons.js` AND `mobile.html` (both surfaces were wrong: desktop a sun, mobile a 3-dot/circle-i). Desktop verified via browser screenshot - the pill's settings icon renders as a gear.
  Remaining: one emulator glance that the mobile gear renders as a gear (folded into MOBFIX.7's screencap pass).

## Phase RELAYHOST - hosted relay (mostly done)

- [~] **RELAYHOST.1 [HUMAN]** Deployed + desktop-verified 2026-08-19 at `https://enqueue-production-cd3d.up.railway.app` (401 without the Bearer secret, 200 with it, holds the full syncable library; the phone pulled 74 artifacts over the public internet). Off-LAN sync is PROVEN.
  Remaining human step: the 10-second physical QR camera-aim on LTE (wifi off) once a standalone release apk exists (see the RELEASE notes in git). Confirmation only; the network path is already proven.

## Out of scope

Recorded in AGENTS.md decision #11: no model enrichment on the phone; one person / one library (no multi-user); iOS is a follow-on; the relay is additive (sync off = desktop unchanged); `saved_pivots` and chats do not cross the relay.
