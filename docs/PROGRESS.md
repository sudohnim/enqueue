# Enqueue Progress

Swept 2026-08-27: the finished-work log was folded into AGENTS.md and README.md; git history holds the raw detail.
This file holds only the current state and what still needs verification.
Active work is in docs/PLAN.md.

## Current state

Sync, E2E, the QR device-linking flow, and the Android app are built and device-verified end to end (desktop -> phone: link from the QR-derived DEK, `mobile_sync` pulls the library, decrypts and applies on-device, the library renders).
A hosted relay is deployed on Railway; the desktop points at it and the phone syncs over the public internet.
The desktop Settings/chat polish (DESKTOPUI.1-5, CHATBUG.1) and the first mobile-UI round (MOBILEUI.5/7/8, MOBFIX.1/2/2b/4) are done and verified.
Durable engineering context (the relay/E2E model, the relay immutability limitation, the QR wire format and DEK-verbatim gotcha, the chat/structured-output gotchas, the Android device-verify protocol, the devUrl/build facts) lives in AGENTS.md; user-facing status is in README.md.

## Verified on emulator-5554 (rebuild 2026-08-29)

- **OFFLINE.1 - library shows cards offline** [x] VERIFIED 2026-08-29:
  - Network OFF + cold launch → 79 cards render immediately (bin/cdp-eval: 79 cards, loading hidden)
  - Network ON + cold launch → sync completes, loading hidden, 79 cards
  - Fix: `renderLibrary()` in bootstrap configured branch + `sync-error` handler
  - Screencap: cards area 920 colorful pixels, pill visible, no offline banner
- **MOBILEUI.6 - pill eye** [x] VERIFIED 2026-08-29: `#pillEye .eye-socket` = 35px (was 141px), frame+pupil inside lid
- **MOBILEUI.3 - square cards** [x] VERIFIED 2026-08-29: `.card` 184x184, CDP `width===height` true
- **MOBILEUI.4 - kind accents** [x] VERIFIED 2026-08-29: `.card .dot` bg = `var(--kind)` (note=rgb(48,128,75))
- **SETUPBTN.1 - stray Setup button hidden** [x] VERIFIED 2026-08-29: header left dark pixels = 0
- **MOBFIX.6 - app icon** [x] VERIFIED 2026-08-29: launcher raven fills 70%, no clipped wingtips
- **QRSCANFIX.1 - errString** [x] VERIFIED 2026-08-29: `errString({message:"cancelled"})` → "cancelled"

## In-progress / needs real device

- **MOBFIX.3 - Camera wiring** [~] Code complete: JS → `invoke("mobile_capture_camera")` → JNI → `MainActivity.captureImage()` → `CameraHelper` → `ACTION_IMAGE_CAPTURE`. Emulator invoke reaches `CameraHelper.kt:55` (crashes - no camera). Needs real device/emulator with camera for full verify.
- **MOBFIX.5 - sync create-only** [~] IMPLEMENTED 2026-08-29 (option a, mutable relay object). `relay/storage.py` `put()` upserts + assigns a fresh cursor on overwrite (so a device past the old cursor re-pulls the update); `relay/app.py` always 201; both push clients now propagate mutations. Tests green (overwrite-in-place, resurface-past-cursor, delete-tombstone-reaches-relay), `bin/verify` green. REMAINING: redeploy the Railway relay with the new storage.py (hosted relay still runs the 409 version), then on-device confirm (delete on desktop -> phone drops the note after sync).
- **MOBFIX.7 - full re-verify** [~] All emulator-verifiable items done. Awaiting MOBFIX.3 real-device verify for complete pass.

## Pending human-only checks

- SCANUI.1 - does the scanner camera preview look boxed (the camera layer is invisible to screencap).
- RELAYHOST.1 - a physical LTE scan (wifi off) - off-LAN sync is already proven over the internet, so this is confirmation only.
- The 10-second physical QR camera-aim, and a final aesthetic glance on a real device.
