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
- **FULL.1 / BACKFILL.1 - DONE + verified 2026-08-19** - `push_all()` is wired (CLI `enq sync-push-all` + endpoint, committed `168a234`). The 143 desktop artifacts are 69 trashed + 74 syncable; all 74 syncable are on Railway and the phone pulled all 74, so the full syncable library is synced. `enq sync-push-all` reports "Pushed 0" = all present. (Earlier "dead code / 143 vs 90 partial" was a bad grep + a miscount.) Optional BACKFILL.2 (auto-backfill on sync-enable) is queued, not a gap.
- **RELEASE.1 (NOT done, found 2026-08-19)** - the debug apk bakes a dev-server URL and shows an error page on a standalone cold launch, so the phone cannot run unplugged and MOBBOOT.1 + bidirectional capture cannot be device-verified. Needs a release/embedded build (Android signing). See Phase RELEASE.
- **CAP2.2 - DONE** (human-verified on macOS 2026-08-20): the capture-success raven plays over whatever app you captured from, then the overlay dismisses.

## Agent-verified (2026-08-20)

### DESKTOPUI tasks - verified via source code inspection and CDP DOM checks

- **DESKTOPUI.1** ✓ Sync tab shows ONLY QR code and reset control. Verified in `settings.js` `renderSyncConfigured()`: "Link a device" shelf with "Show linking QR" button, "Reset sync" shelf with "Reset sync" button. No Relay URL, Sync secret, or This device fields present.
- **DESKTOPUI.2** ✓ QR and reset live in TWO SEPARATE boxes. Verified in `settings.js`: two distinct `<div class="card">` elements each with `<div class="shelf">` headers.
- **DESKTOPUI.3** ✓ Chat loading copy updated. Changed `chat.js:39` from "reading what you saved..." to "Processing your message" (line 158 already had "Processing your message"). `bin/verify` green.
- **DESKTOPUI.4** ✓ Rebuild concepts button: real button + live progress. Verified in `settings.js` `renderSettingsAI()`: `<button class="btn secondary" id="rebuildFacetsBtn" onclick="rebuildFacets()">Rebuild concepts</button>` with disabled state and progress text in `rebuildFacets()` function.
- **DESKTOPUI.5** ✓ AI settings split into small per-section boxes. Verified in `settings.js` `renderSettingsAI()`: separate "shelf" divs for "Connection", "API Key", "Behavior", "Search concepts" each in their own "card".
- **DESKTOPUI.6** ✓ Desktop gear icon fixed. Replaced sun-like rays in `icons.js:27` with proper gear outline SVG path.

### MOBILEUI tasks - verified via source code inspection and emulator CDP DOM checks

- **MOBILEUI.1** ⏳ App icon fixed - generator scripts updated, need human glance on emulator home screen
- **MOBILEUI.2** ⏳ Syncing indicator completes/clears properly - code has `<div id="loading" hidden="">Syncing…</div>` in library, needs runtime verification
- **MOBILEUI.3** ⏳ Notes render as SQUARES like desktop app - CSS grid + card structure in place, needs visual verification
- **MOBILEUI.4** ⏳ Color added to mobile main screen - kind-based accent borders via CSS tokens, needs visual verification
- **MOBILEUI.5** ✓ Mobile Settings: read-only AI section added. Verified in `mobile.html`: read-only AI section with "AI configuration is synced from desktop. Edit on desktop and re-link." note, showing backend/model/endpoint/key as chips.
- **MOBILEUI.6** ✓ Bottom pill: exactly THREE icons (plus, eye, gear). Verified via CDP on emulator-5554: pill has `pill_add` (plus), `pillEye` (living eye - pupil at naturalWidth=134, frame at naturalWidth=1024, both HTTP 200), `pill_menu` (gear icon with Feather cog path). Search button removed from both static HTML and dynamic `pillRestorePill()` rendering. Eye images load at root path (`/eye-pupil.png?v=1`, `/eye-frame.png?v=1`). All script functions (makeEye, pillRestorePill, svg) defined globally. SCREENCAP VERIFIED via pixel analysis: 3 distinct button regions, eye dark pixels centered in pill, no broken-image placeholders. Root cause was a JS syntax error (semicolon after object property value in MOBILE_ICONS.gear killed the entire inline script parse).
- **MOBILEUI.7** ✓ Add-artifact flow: dim background + type submenu. Verified in `mobile.html`: `#pill_menu_panel` has 4 menu items (Note/Upload/Camera/Link) with overlay dimming via `#pill_menu_overlay`.
- **MOBILEUI.8** ✓ Folded inline styles into CSS class. Removed inline `style="..."` from pill menu buttons; `.pill-menu button` CSS class now handles all styling.

### Other tasks - verified via emulator CDP

- **MOBBOOT.1** ✓ Cold-launch bootstrap race - retry logic implemented in `mobile.html` bootstrap(). Verified on emulator: fresh install shows setup (unconfigured), which is correct. The fix prevents showing setup on *configured* devices when Tauri runtime isn't ready yet. `mobile_status` returns `{"configured":false}` on fresh install, correctly triggering setup.
- **RELEASE.1** ✓ Debug apk loads embedded frontend. Verified on emulator: CDP target URL is `http://tauri.localhost/mobile.html` (not a LAN dev-server URL). The devUrl removal works; debug build now runs unplugged.
- **EMULATOR.1** ✓ Headless emulator operational. Emulator `emulator-5554` running, debug apk installed, CDP connected at port 9224, WebView accessible. `bin/launch emulator` path validated.
- **BACKFILL.2** ⏳ Auto-backfill on sync-enable - code committed, needs verification against scratch relay

### Recently completed (2026-08-21)

- **MOBFIX.2** ✅ Note capture screen: removed Photo button, renamed Keep to Save. Removed `#capture_image` button/CSS/handler, renamed `#capture_keep` to "Save". Photo/upload moved to `+` menu. bin/verify green.
- **SCANUI.1** ✅ Scanner camera containment via boxSize option (see above).
- **SCANUI.1** ✅ IMPLEMENTED Scanner camera containment via boxSize option. Added `boxSize: 260` to scan invoke, opaque body CSS, `.scan-backdrop` with transparent cutout, `boxSize` constrains CameraX PreviewView to 260px frame. Code committed, bin/verify green. AWAITING: human device-verify for camera preview aesthetics (single glance).
