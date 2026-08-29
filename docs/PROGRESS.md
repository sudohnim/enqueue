# Enqueue Progress

Swept 2026-08-27: the finished-work log was folded into AGENTS.md and README.md; git history holds the raw detail.
This file holds only the current state and what still needs verification.
Active work is in docs/PLAN.md.

## Current state

Sync, E2E, the QR device-linking flow, and the Android app are built and device-verified end to end (desktop -> phone: link from the QR-derived DEK, `mobile_sync` pulls the library, decrypts and applies on-device, the library renders).
A hosted relay is deployed on Railway; the desktop points at it and the phone syncs over the public internet.
The desktop Settings/chat polish (DESKTOPUI.1-5, CHATBUG.1) and the first mobile-UI round (MOBILEUI.5/7/8, MOBFIX.1/2/2b/4) are done and verified.
Durable engineering context (the relay/E2E model, the relay immutability limitation, the QR wire format and DEK-verbatim gotcha, the chat/structured-output gotchas, the Android device-verify protocol, the devUrl/build facts) lives in AGENTS.md; user-facing status is in README.md.

## Known-broken / in-flight (see docs/PLAN.md for the tasks)

- **MOBFIX.5 - sync is create-only for the mobile client.** Edits/deletes to an already-synced artifact do NOT propagate: the relay is immutable by object name (id-based), so a second push for the same id is refused (409). Verified 2026-08-27 (deleted a note on desktop, the relay object still decrypts to `deleted_at=None`, the phone kept it). This invalidates the old "CRUDSYNC both ways" claims for synced artifacts.
- **MOBBOOT.1 - configured device stuck on setup** [x] VERIFIED 2026-08-28:
  - Root cause: setup section in initial HTML + WebView compositor not repainting on hide
  - Fix: dynamic setup injection via `SETUP_HTML` template + `waitForInvokeAndStatus()` + `waitForSyncListeners()`
  - Verified on emulator-5554: cold launch on configured device shows Library (not setup), cards render, pill visible
  - Screencap: header left-aligned, loading hidden, cards rendered, pill visible
- **MOBILEUI.2 - "Syncing..." indicator sticks** [x] VERIFIED 2026-08-28: sync-started → sync-done events wired via retry poller; #loading hides on sync-done.
- **SETUPBTN.1 - stray "← Setup" button on library header** [x] VERIFIED 2026-08-28: added `hidden` to `#to_setup`; `show()` toggles visibility. Configured cold launch: no back button, cards render, pill visible.
- **MOBILEUI.6 - pill defects** [x] VERIFIED 2026-08-28: plus disc, eye (frame+pupil), gear all render; navigation works.
- **MOBFIX.3 (camera opens gallery), MOBFIX.6 (icon size)** - fixes in the working tree, uncommitted, need a build + emulator verify (MOBFIX.7 umbrella).
- **QRSCANFIX.1** - the "[object Object]" scan error is fixed (errString helper); a real camera scan still needs the phone.

## Pending human-only checks

- SCANUI.1 - does the scanner camera preview look boxed (the camera layer is invisible to screencap).
- RELAYHOST.1 - a physical LTE scan (wifi off) - off-LAN sync is already proven over the internet, so this is confirmation only.
- The 10-second physical QR camera-aim, and a final aesthetic glance on a real device.
