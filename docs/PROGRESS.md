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
  - Network OFF + cold launch -> 79 cards render immediately (bin/cdp-eval: 79 cards, loading hidden)
  - Network ON + cold launch -> sync completes, loading hidden, 79 cards
  - Fix: `renderLibrary()` in bootstrap configured branch + `sync-error` handler
  - Screencap: cards area 920 colorful pixels, pill visible, no offline banner
- **MOBILEUI.6 - pill eye** [x] VERIFIED 2026-08-29: `#pillEye .eye-socket` = 35px (was 141px), frame+pupil inside lid
- **MOBILEUI.3 - square cards** [x] VERIFIED 2026-08-29: `.card` 184x184, CDP `width===height` true
- **MOBILEUI.4 - kind accents** [x] VERIFIED 2026-08-29: `.card .dot` bg = `var(--kind)` (note=rgb(48,128,75))
- **SETUPBTN.1 - stray Setup button hidden** [x] VERIFIED 2026-08-29: header left dark pixels = 0
- **MOBFIX.6 - app icon** [x] VERIFIED 2026-08-29: launcher raven fills 70%, no clipped wingtips
- **QRSCANFIX.1 - errString** [x] VERIFIED 2026-08-29: `errString({message:"cancelled"})` -> "cancelled"

## Settings propagation - desktop config -> phone (MOB2.9, 2026-08-30)

- **SETTINGSYNC.1 - full desktop->mobile config propagation** [x] DEVICE-VERIFIED 2026-08-30:
  - The whole MOB2.9 settings-sync was DEAD: `push_settings` was never called on the
    desktop, and the mobile pull ignored `lib/settings/`. Wired both ends.
  - Desktop: `push_settings` ([sync/client.py]) now includes the effective LLM config
    (backend/model/url from `all_settings`) AND the provider `llm_api_key` (read from the
    Keychain via `config.llm_api_key()` - it is never in settings.json). It rides the same
    DEK-encrypted relay object, so the relay only sees ciphertext. Triggered on every
    settings change (`settings._resync_to_relay` in `settings.update`), on api-key
    store/forget ([api/settings.py]), and once at engine startup ([api/app.py]) so a
    freshly-linked phone gets the current config without waiting for an edit.
  - Mobile: the pull loop ([desktop/src/sync.rs]) decrypts `lib/settings/*.enc`, keeps the
    newest by `updated_at`, caches it in `sync_meta['settings']`. `mobile_chat` and
    `mobile_settings_get` ([desktop/src/lib.rs]) prefer the synced config over local, so
    the phone runs chat with the desktop's provider + key. Settings screen shows
    `managed_by_desktop: true` and reports only `llm_api_key_present`, never the key.
  - VERIFIED on physical phone: after sync, `mobile_settings_get` returned the desktop's
    `opencode-go` / `deepseek-v4-pro` / `api_key_present:true` / `managed_by_desktop:true`;
    `mobile_chat` made a REAL authenticated call to opencode.ai (got 429 rate-limit, i.e.
    the key worked - not 401/403). End-to-end propagation confirmed.
  - Note: desktop<->desktop settings sync (the old `pull_settings`) is still separate and
    uncalled; only desktop->mobile is wired here (what was asked).

## In-progress / needs real device

- **MOBFIX.3 - Camera wiring** [~] Code complete: JS -> `invoke("mobile_capture_camera")` -> JNI -> `MainActivity.captureImage()` -> `CameraHelper` -> `ACTION_IMAGE_CAPTURE`. Emulator invoke reaches `CameraHelper.kt:55` (crashes - no camera). Needs real device/emulator with camera for full verify.
- **MOBFIX.5 - sync create-only** [~] IMPLEMENTED 2026-08-29 (option a, mutable relay object). `relay/storage.py` `put()` upserts + assigns a fresh cursor on overwrite (so a device past the old cursor re-pulls the update); `relay/app.py` always 201; both push clients now propagate mutations. Tests green (overwrite-in-place, resurface-past-cursor, delete-tombstone-reaches-relay), `bin/verify` green. REMAINING: redeploy the Railway relay with the new storage.py (hosted relay still runs the 409 version), then on-device confirm (delete on desktop -> phone drops the note after sync).
- **MOBFIX.7 - full re-verify** [~] All emulator-verifiable items done. Awaiting MOBFIX.3 real-device verify for complete pass.

## Pending human-only checks

- SCANUI.1 - does the scanner camera preview look boxed (the camera layer is invisible to screencap).
- RELAYHOST.1 - a physical LTE scan (wifi off) - off-LAN sync is already proven over the internet, so this is confirmation only.
- The 10-second physical QR camera-aim, and a final aesthetic glance on a real device.

## MOBCRUD phase - mobile write parity (2026-08-30)

CORRECTION 2026-08-30: the earlier "[x] CODE COMPLETE" marks below were NOT faithful.
The UI was wired, but only `mobile_delete` enqueued to `mutation_outbox`; the other five
commands (`mobile_update_note`, `mobile_add_tag`, `mobile_remove_tag`, `mobile_toggle_pin`,
`mobile_add_annotation` / `mobile_remove_annotation`) mutated the local read-copy only and
never pushed, so a mobile edit stayed on the phone.
Fix: added a `queue_mutation_push` helper in `desktop/src/lib.rs` (bumps `updated_at` +
inserts a `mutation_outbox` row) called by all six commands, and each JS handler now fires
`mobile_outbox_push` immediately after the mutation for prompt propagation.

- **MOBCRUD.1 - note edit** [x] DEVICE-VERIFIED 2026-08-30:
  - Physical phone: edited note body -> `mobile_update_note` -> `mobile_outbox_push` ->
    desktop DB `body` matched the marker after pull. Round-trip confirmed.

- **MOBCRUD.2 - delete + restore** [x] CODE COMPLETE 2026-08-30:
  - `mobile_delete` already enqueued a 'delete' mutation (the one command that was correct).
  - Delete button, confirmation dialog, refreshes library. Push path unchanged.

- **MOBCRUD.3 - tags** [-] CUT from mobile by design 2026-08-30:
  - Tag CREATION dropped from the phone - tagging is curation, a desktop-workbench job,
    not a one-handed phone action. Reader tag button removed. (It was also broken:
    `mobile_add_tag` threw `no such table: tags`; mobile keeps tags in `tags_json`, not the
    desktop `tags` table. Cut is about the affordance, not the bug.)
  - The Tags VIEW MODE stays - the phone reads `tags_json` synced from desktop and groups
    by tag. You just don't make tags on the phone.

- **MOBCRUD.4 - annotations** [-] CUT from mobile by design 2026-08-30:
  - Annotation AUTHORING dropped from the phone (same reason as tags). Reader "add note"
    button removed; existing annotations still render read-only. Rust commands left dormant.

- **MOBCRUD.5 - pin toggle** [x] DEVICE-VERIFIED 2026-08-30:
  - Physical phone: `mobile_toggle_pin` -> `mobile_outbox_push` -> desktop `pinned` +
    `updated_at` matched after pull. (First push hit a transient relay failure and left the
    row in `mutation_outbox`, synced=0; the retry drained it `pushed:2` and desktop applied
    it - confirms the outbox is durable, not fire-and-forget.)

The Rust backend commands existed, but the five non-delete ones did not push - that was the
gap this correction closes. Changes in `desktop/src/lib.rs` (queue_mutation_push + six call
sites) and `src/enqueue/static/mobile.html` (six handlers fire mobile_outbox_push).
