# Enqueue Progress

Swept 2026-08-19: the finished-work log was folded into AGENTS.md and README.md; git history holds the raw detail.
This file now holds only the current state and what still needs a human device pass.
Active agent work is in docs/PLAN.md.

## Current state

Sync, E2E, the QR device-linking flow, and the Android app are built.
On 2026-08-19 the desktop->phone path was device-verified end to end over adb + CDP: a freshly built apk links from the QR-derived DEK, `mobile_sync` pulls the full library (73 artifacts), decrypts and applies them on-device, and the library renders.
The four MOBRENDER.1 root causes (mobile_sync reading relay/secret from the empty arg, two null-listener init crashes, and the DEK double-encode) are fixed and committed in `72d7f60`.
The durable engineering context for all of this now lives in AGENTS.md (the "Sync (relay, E2E, device linking)" subsection and "Verifying the Android app on a device"); the QR wire format and the DEK-verbatim gotcha are in "Resolved decisions" #2.

Open agent work is in docs/PLAN.md: CAP2.2 (capture-flight over-app pivot), MOBBOOT.1 (cold-launch bootstrap race), SCANUI.1 (scanner camera-box containment), RELAYHOST.1 (Railway deploy).

## Pending human device-verify

These items are code-complete and committed; each awaits one human pass on a real device (the agent has done the headless verification it can). If a pass fails, open a new PLAN.md task for the fix.

- **RELAYHOST.1 / QR.2** - DONE + verified from the desktop 2026-08-19. Live at `https://enqueue-production-cd3d.up.railway.app`: 401 without the secret, 200 with, 90 objects over TLS; the phone pulled 74 artifacts over the public internet (off-LAN sync proven without the wifi-off test). Remaining is not a RELAYHOST step: the full library needs BACKFILL.1, and the standalone phone run needs RELEASE.1.
- **QR.3** - one glance that the linking QR visibly renders in desktop Settings > Sync (the Rust rqrr round-trip test already pins the wire format).
- **QR.4a** - the 10-second physical act: aim the phone camera at the desktop QR and confirm the scan links (camera-active + scanner already proven via dumpsys/CDP).
- **QR.4b** - a real end-to-end scan -> link -> sync with no typing.
- **QR.5a** - scroll/capture/read stays smooth mid-sync; the "Syncing..." indicator clears on `sync-done`.
- **QR.5b** - lock the screen and background the app mid-sync without loss (foreground-service notification visible while active); an airplane-mode capture pushes when the network returns.
- **LINKSTAY.1** - with a loopback relay URL, Settings > Sync shows the "only reachable from this Mac" error instead of a QR.
- **LINKSTAY.2** - phone unplugged (relay unreachable): cold-launch shows the cached library + offline banner, zero alerts, no setup screen; reattach syncs without rescanning.
- **CRUDSYNC.1** - deleting/restoring/pinning/tagging/annotating on the desktop each produce a relay object for that artifact.
- **CRUDSYNC.2** - one delete in EACH direction propagates to the other device.
- **MOBUI1.1** - the pill menu shows only Settings; Settings > Trash lists trashed notes with a working Restore.
- **MOBUI1.2** - the library renders every card (including image thumbnails) with zero console exceptions (insertBefore fix); exercised during the MOBRENDER.1 render check, still worth one clean CDP console pass.
- **FULL.1 -> BACKFILL.1 (NOT done, code gap found 2026-08-19)** - `push_all()` exists but has ZERO callers, so the full library never backfills. Desktop 143 artifacts, Railway 90, phone 74. Needs the wiring in Phase BACKFILL (a CLI + a sync-enable trigger) + one run. This is agent work, not a human verify.
- **RELEASE.1 (NOT done, found 2026-08-19)** - the debug apk bakes a dev-server URL and shows an error page on a standalone cold launch, so the phone cannot run unplugged and MOBBOOT.1 + bidirectional capture cannot be device-verified. Needs a release/embedded build (Android signing). See Phase RELEASE.
- **CAP2.2** - PIVOT IMPLEMENTED 2026-08-19 (raven flies inside the capture overlay over the app, then dismisses; the dead flight-overlay-window path was removed; cargo check + bin/verify green). Human macOS visual left: global-hotkey capture from another app (e.g. Chrome) shows the raven over that app, focus stays in the other app, overlay dismisses with no stuck window.
