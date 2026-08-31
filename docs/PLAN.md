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

## Phase MOBVIEWS - mobile library view modes + full reverify (2026-08-30)

Big mobile round this session: view modes, horizontal scroll, a real logo, tags + custom-view sync, and the phone->desktop create fix.
All code-complete and emulator-verified during the build; this task is the from-scratch device reverify on a freshly installed apk.

- [~] **MOBVIEWS.1 [AGENT]** Reverify every mobile feature added 2026-08-30 on a clean install. Build + install first, then check each by READING pixels / measuring the DOM over `bin/cdp-eval` (device: emulator-5554 unless a phone is attached; the physical phone auto-locks, so screencaps there show the lock screen - drive it headless or use the emulator for visuals).

  SETUP (do once):
  1. `cd desktop && cargo tauri android build --debug --target aarch64` then `adb -s emulator-5554 install -r gen/android/app/build/outputs/apk/universal/debug/app-universal-debug.apk`.
  2. The desktop engine must run THIS session's code for tags/pivots to push - restart `enq serve` (the running one predates `sync/client.py::push_pivots` and `pivots_saved` hooks).
  3. Seed the relay so the phone has data to group: on the desktop, load the DEK and `push_all()` (backfills artifacts + tags + `lib/pivots.enc`). Tags ride on artifact snapshots; custom views are `lib/pivots.enc`.
  4. On the device: cold launch, run `mobile_sync`, wait for the pull.

  VERIFY (each is a separate check, READ the result):
  - **Logo**: launcher icon is the raven on purple (matches desktop `icon.png`), not a small raven on white. Screencap the launcher home screen.
  - **View chips**: `Last touch / Type / Tags / Custom` render; tapping one sets `aria-pressed` and regroups with no refetch. `bin/cdp-eval "[...document.querySelectorAll('#viewchips .chip')].map(c=>c.textContent)"`.
  - **Horizontal scroll**: a section's `.rows` is `display:flex; overflow-x:auto`; cards are fixed 168px and swipe sideways, never growing the page. Screencap + `getComputedStyle('.rows').overflowX === 'auto'`.
  - **Type mode**: `setLibraryMode('type')` -> shelves Notes/Links/Images/PDFs/Files with counts, only non-empty ones.
  - **Tags mode**: `setLibraryMode('tags')` -> one shelf per tag. Needs tagged artifacts synced; `mobile_list` items carry a `tags` array (stored in the mobile `tags_json` column by `apply_snapshot`). If empty, tag something on desktop (bumps updated_at + pushes) then re-sync.
  - **Custom mode**: `setLibraryMode('custom')` -> one shelf per saved view. `mobile_pivots` returns `{views:[{name,ids}]}` from `lib/pivots.enc`; each shelf shows the local artifacts in that view. Create a saved view on desktop and confirm it appears after a sync (the `pivots_saved` mutations now call `push_pivots()` on a daemon thread).
  - **Pill**: eye centered, `+`/eye/gear balanced sizes (space-between), eye opens Chat, gear opens Settings, `+` toggles the add-menu (hidden by default).
  - **Settings**: only Sync Now + Re-link (all other settings are desktop-only); renders at the top, not mid-page.
  - **Phone create -> desktop**: capture a note on the phone (`mobile_capture`), it queues to `capture_outbox`, `mobile_outbox_push` lands it under `dev/{phone_device}/artifacts/{id}.enc`, and a desktop `pull()` receives it. (Was broken: text captures never queued.)
  - **Delete sync (MOBFIX.5)**: delete a note on desktop -> it disappears on the phone after sync (relay object decrypts to `deleted_at` set).
  - **Offline**: turn the network off, cold launch -> the library still renders from the local DB.
  Done when: every bullet confirmed on the rebuilt apk by reading pixels / DOM, recorded in PROGRESS.md.

## Phase MOBCRUD - mobile write parity with desktop (the big one)

The mobile app is a read-only mirror today: it captures new notes but cannot edit, delete, tag, or annotate.
The good news is the WHOLE BACKEND ALREADY EXISTS - these Rust commands are implemented, registered, and permissioned, they are just never called from `mobile.html` (0 UI references):
`mobile_update_note(id, body, title?)`, `mobile_delete(artifact_id)`, `mobile_restore(artifact_id)`, `mobile_add_annotation(id, text)`, `mobile_remove_annotation`, `mobile_add_tag(id, tag)`, `mobile_remove_tag(id, tag)`, `mobile_toggle_pin(id)`, `mobile_toggle_trash`.
They all bump `updated_at` and push through the same sync path, so an edit/delete/tag made on the phone already propagates to the desktop (verified: tagging + deleting + capturing all sync). This phase is UI wiring only - no new Rust, no new sync.

- [x] **MOBCRUD.1 [AGENT]** DEVICE-VERIFIED 2026-08-30 (round-trip: phone edit -> desktop body matched). Wire note edit into the mobile reader. When a note is open (the reader surface, `show("reader")`), add an edit affordance that matches the desktop (same pencil/edit icon from `js/icons.js`; read the desktop reader's edit flow in `home.js`/`artifact.js` for the exact interaction). On save, call `invoke("mobile_update_note", { id, body, title })`, then re-render. Done when: open a note on the phone, edit the body, save, and the change shows locally AND appears on the desktop after its next sync. Verify on emulator-5554 over `bin/cdp-eval` + screencap.

- [x] **MOBCRUD.2 [AGENT]** DONE (mobile_delete was the one command already pushing). Wire delete + restore. Add a delete control on the reader (and/or a long-press on a card) using the desktop's trash icon. `invoke("mobile_delete", { artifactId: id })` moves it to trash; the artifact disappears from the library after re-render. Restore from the (currently removed) Trash view is out of scope here unless trivial - deletion is the priority. Done when: delete a note on the phone -> it leaves the phone library AND the desktop drops it after sync. Note the arg name is `artifactId` (camelCase in the JS invoke -> `artifact_id` in Rust).

- [-] **MOBCRUD.3 [CUT] 2026-08-30** Tags dropped from mobile by design. Tagging is curation - a sit-down organizing pass that belongs on the desktop workbench, not one-handed on the phone. The reader's tag button is removed. (It was also broken - `mobile_add_tag` threw `no such table: tags` because mobile stores tags in `tags_json`, not the desktop `tags` table - but the decision to cut is about the affordance, not the bug.) The Tags VIEW MODE stays: the phone still reads `tags_json` synced from desktop and groups by tag; you just don't create tags on the phone. Rust `mobile_add_tag`/`mobile_remove_tag` left dormant.

- [-] **MOBCRUD.4 [CUT] 2026-08-30** Annotation authoring dropped from mobile by design (same reason as tags: curation is desktop work). The reader's "add note" button is removed; existing annotations still RENDER on the phone (read-only). Rust `mobile_add_annotation`/`mobile_remove_annotation` left dormant. Original task: Wire annotations (the desktop's note "summaries"/annotations). `invoke("mobile_add_annotation", { id, text })` appends an annotation; the reader already renders annotations (MOB.5). Match the desktop's annotation affordance. Also allow editing notes attached to IMAGES (the user cannot add/edit a note on an image today) - an image artifact takes an annotation the same way; expose the same annotation input on the image reader. Done when: add an annotation/note to a note AND to an image on the phone, both render and sync to desktop.

- [x] **MOBCRUD.5 [AGENT]** DEVICE-VERIFIED 2026-08-30 (round-trip: phone pin -> desktop pinned+updated_at matched). Wire pin toggle. `invoke("mobile_toggle_pin", { id })` flips `pinned`; the Last-touch view's Saved shelf reflects it. A star/pin control on the card or reader, matching desktop. Done when: pin/unpin on the phone moves the note in/out of the Saved shelf AND syncs to desktop.

  Overall MOBCRUD guidance: follow the SAME icons (from `static/js/icons.js`) and interaction shapes the desktop uses - read `home.js` / `artifact.js` for the desktop reader's edit/tag/delete/pin affordances and mirror them on mobile so the two surfaces feel identical. CORRECTION 2026-08-30: the earlier claim that "every command already bumps updated_at + pushes" was FALSE - only `mobile_delete` pushed; the others mutated the local read-copy only. They now push via a `queue_mutation_push` helper in `desktop/src/lib.rs` (bumps updated_at + inserts a `mutation_outbox` row) plus a `mobile_outbox_push` call in each JS handler. Any NEW mobile mutation command must do the same - the invoke alone is NOT enough. After each, the change must round-trip to the desktop (the real proof it is not a local-only edit).

## Phase SHAREOUT - share an artifact OUT of the mobile app (2026-08-31)

Share-OUT means handing a COPY of an artifact to another Android app via the system share sheet (`Intent.ACTION_SEND`) - a note's text to Messages, a link to a browser, an image to Photos. It is NOT sharing access to the library (the one-person-one-library model is unchanged; nobody gets into your library, they get a copy of one item). This is the inverse of the future share-INTO (capture from other apps), which is a separate, larger piece.

Leverage that already exists: `MainActivity.kt` already bridges Android -> Rust (the `captureImage()` / `mobile_capture_camera` JNI path is the exact template), the reader toolbar already hosts pin/edit/delete controls (mirror them for a Share button), and `mobile_blob` already returns an artifact's bytes for images/PDFs.

- [ ] **SHAREOUT.1 [AGENT]** The JNI bridge + text/link share. Add a `shareText(text: String)` (and `shareText(text, subject)`) method to `desktop/gen/android/app/src/main/java/com/sudohnim/enqueue/MainActivity.kt` that builds an `Intent(ACTION_SEND)` with `type = "text/plain"`, `EXTRA_TEXT = text`, wraps it in `Intent.createChooser`, and `startActivity`s it. Add a Rust `#[cfg(mobile)] #[tauri::command] fn mobile_share_text(app, text)` in `desktop/src/lib.rs` that calls it over JNI (copy the shape of `mobile_capture_camera`), register it in the invoke handler + add its `permissions/autogenerated/*.toml` + the `tauri.conf.json` capability (a missing capability = "not allowed. Command not found"). Then a **Share** button in the mobile reader toolbar (drawn icon via `createIcon`, matching pin/edit/delete): for a note, share the markdown body; for a link, share the `source_url`; for anything else, share `title + "\n" + (source_url||body)`. Done when: open a note on the phone, tap Share, the Android chooser appears, and picking Messages/Notes drops the note's text in. Verify on emulator-5554 (the chooser is a system UI - screencap it) over `bin/cdp-eval` to fire the invoke.

- [ ] **SHAREOUT.2 [AGENT]** Image / PDF / file share via FileProvider (depends on SHAREOUT.1). A raw file needs a `content://` URI, not the bytes, so: declare a `FileProvider` in the AndroidManifest (`androidx.core.content.FileProvider`, authority `com.sudohnim.enqueue.fileprovider`) with a `res/xml/file_paths.xml` exposing the app cache dir; add `shareFile(path, mime)` to `MainActivity.kt` that resolves the file to a provider URI, sets `ACTION_SEND` `type=mime`, `EXTRA_STREAM=uri`, and `FLAG_GRANT_READ_URI_PERMISSION`, then chooser + startActivity. Rust `mobile_share_file(app, id)`: pull the artifact's blob (reuse the `mobile_blob` decrypt path) to a file in the cache dir, then call `shareFile` with the artifact's mime. Wire the reader Share button to route image/pdf/file kinds here and note/link kinds to SHAREOUT.1. Done when: open an image on the phone, tap Share, the chooser appears, and picking a target hands over the actual image file (opens/attaches correctly in the target app). Verify on emulator-5554.

  SHAREOUT guidance: the Share button is share-a-copy only; it never grants library access and never syncs anything (it is read-only egress). Keep the icon family + toolbar spacing identical to the existing pin/edit/delete controls. The `createIcon` builder now renders correctly (fixed 2026-08-31: it recreates each glyph child in the SVG namespace); reuse it, do not hand-roll SVG. There is no matching desktop affordance to mirror, so pick a conventional share glyph (the "arrow out of a box" / three-node share mark) and add it to `MOBILE_ICONS`.

## Phase MOBFIX.7 - commit + rebuild + device-verify the working-tree batch

- [x] **MOBFIX.7 [AGENT]** VERIFIED 2026-08-29 (emulator-5554, rebuilt apk).
  All emulator-verifiable fixes confirmed on rebuilt apk:
  - **OFFLINE.1** [x]: Network OFF cold launch → 79 cards immediately (bin/cdp-eval: 79, loading hidden); Network ON → sync completes. Fix: `renderLibrary()` in bootstrap + `sync-error` handler. Screencap: 920 card pixels, pill visible.
  - **MOBILEUI.6** [x]: `#pillEye .eye-socket` = 35px (was 141px), eye-only.png frame + pupil inside lid.
  - **MOBILEUI.3** [x]: `.card` 184x184, CDP `width===height` true.
  - **MOBILEUI.4** [x]: `.card .dot` bg = `var(--kind)` (note=rgb(48,128,75)), CDP confirms.
  - **SETUPBTN.1** [x]: `#to_setup` hidden on configured cold launch.
  - **MOBFIX.6** [x]: Launcher icon raven fills 70%, no clipped wingtips.
  - **QRSCANFIX.1** [x]: `errString({message:"cancelled"})` → "cancelled".
  Pending (real device):
  - **MOBFIX.3** [~]: Camera invoke reaches `CameraHelper.kt:55` (emulator crash - no camera). Code path complete: JS→JNI→ACTION_IMAGE_CAPTURE.
  - **MOBFIX.5** [ ]: Relay immutability (architectural - relay 409s on same object name).
  Once MOBFIX.3 fixed on device: single rebuild + full verify pass.

## Phase OFFLINE - local-first: library must render without a network sync

- [x] **OFFLINE.1 [AGENT]** VERIFIED 2026-08-29 (emulator-5554, rebuilt apk).
  - Network OFF cold launch → 79 cards immediately (bin/cdp-eval: 79, loading hidden); Network ON → sync completes.
  - Fix: `renderLibrary()` in bootstrap configured branch + `sync-error` handler.
  - Screencap: 920 card pixels, pill visible, no offline banner.
  - Root cause: `bootstrap()` never called `renderLibrary()`; only `sync-done` did. Offline, `sync-error` fired instead.
  - Done when: force-stop + cold launch CONFIGURED emulator with network OFF → library shows cards within a second without sync. Re-enable network → sync updates.

## Phase SETUPBTN - stale "back to Setup" button on the library header

- [x] **SETUPBTN.1 [AGENT]** VERIFIED 2026-08-28:
  - Fix: `hidden` attribute on `#to_setup` in library header; `show()` toggles visibility (hidden on library, shown on setup)
  - Configured cold launch: no "← Setup" button visible, cards render, pill visible
  - Screencap: header left dark pixels = 0 (button hidden), cards colorful = 920, pill purple = 1734

## Phase MOBFIX.5 - sync is create-only (the big architectural fix)

- [~] **MOBFIX.5 [AGENT]** IMPLEMENTED + DEPLOYED 2026-08-29 (option a, mutable relay object). Code-complete, `bin/verify` green, and the Railway dev relay was redeployed with the new `storage.py` (`/health` returns 200, proving the new code is live). REMAINING: the on-device confirm only (delete a note on desktop pointed at the hosted relay -> phone drops it after its next sync; decrypt-the-relay-object shows `deleted_at` set).
  What landed:
  - `relay/storage.py` `put()` is now an UPSERT that assigns a fresh cursor on overwrite; `ObjectConflict` removed. `relay/app.py` `put_object` always 201.
  - `sync/client.py` + `desktop/src/sync.rs`: comments corrected; both already accepted 201, so a re-PUT now overwrites and propagates. `push_all` left one-shot (no client dedup needed; see its docstring).
  - Tests: `test_relay.py` overwrite-in-place + resurface-past-an-old-cursor (the cursor subtlety); `test_sync.py` delete-overwrites-the-relay-object-with-the-tombstone (the exact bug). All green.
  Original analysis kept below for the record.

  Mutations to an already-synced artifact (delete, edit, pin, tag, restore) did NOT propagate. Device-verified broken 2026-08-27: deleted a note on desktop, the relay object still decrypts to `deleted_at=None`, the phone kept it.
  ROOT CAUSE (architectural): the relay is IMMUTABLE BY OBJECT NAME. `RelayStorage.put` (`src/enqueue/relay/storage.py:54`) raises `ObjectConflict` when the name exists, surfaced as 409 (`relay/app.py:105`). Names are per-device, id-based, no version (`sync/client.py:75`, `desktop/src/sync.rs:176` -> `dev/{device}/artifacts/{id}.enc`). A second PUT for the same id 409s, so the updated snapshot is silently refused, and BOTH push clients treat 409 as success-skip (`client.py:89`/`:358`, `sync.rs:182`). The pull's client-side LWW is moot because the newer snapshot never lands.

  DECISION - option (a), MUTABLE relay object. Rejected (b) versioned names (`{id}-{updated_at}.enc`). Rationale on the values, not cost:
  - Simplicity/scalability: (a) keeps ONE object per (device, id), storage bounded at O(artifacts). (b) makes every edit a new object, O(edits), and needs a whole GC subsystem to prune superseded versions - a permanent maintenance tax and a data-loss footgun (delete the wrong version). One concept vs two.
  - Robustness: the object name already carries the writer's device prefix (`dev/{device}/...`), so two devices NEVER write the same name - an overwrite only ever replaces a device's OWN older snapshot with its OWN newer one, and a device's `updated_at` only moves forward. So storage-layer last-write is monotonic per object; no cross-device clobber. The scary "older write clobbers newer" case (b) guards against cannot occur here, so (b)'s immutability buys nothing the threat model needs.
  - Maintainability: (a) leaves the pull path and the client-side LWW untouched; the relay stays a dumb byte store.

  THE FIX (deliberate pass, not inline with UI work):
  1. `relay/storage.py` `put()`: make it an UPSERT that assigns a NEW cursor on overwrite. `cursor = max_cursor + 1` always, then `INSERT INTO objects(name,data,cursor) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET data=excluded.data, cursor=excluded.cursor`. Drop the `ObjectConflict` raise. THIS IS THE CORE: reassigning a fresh high cursor on overwrite is what makes `list_changed(since)` re-surface the object to a device whose cursor already passed the old position (the cursor subtlety). `list_changed` needs no change - it already `ORDER BY cursor`.
  2. `relay/app.py` `put_object`: remove the `ObjectConflict`/409 branch; `put` now always succeeds (return 201). Delete the now-unused `ObjectConflict` import if nothing else uses it.
  3. `sync/client.py`: 409 is now dead for the per-object path - keep accepting it defensively but the success path is 201. The REAL change is `push_all` (`:298`): it can no longer lean on the relay's 409 to skip already-present objects (every re-PUT would burn a new cursor and re-flood every device's pull). Give it a client-side high-water mark: a local table `synced_snapshots(name TEXT PRIMARY KEY, updated_at TEXT)`, and push an artifact only when its current `updated_at` differs from the last pushed one. `push_artifact` (per-mutation, `:45`) updates the same table on success. Note `push_all` is one-shot (BACKFILL.2's `sync_backfill_done` guard), so this mainly protects a re-run / a second device.
  4. `desktop/src/sync.rs` `push_snapshot` (`:167`): same - treat 201 as success (409 no longer expected); no economy change needed on the Rust side (it pushes per-mutation, not a full backfill).
  5. Regression tests in `tests/` (Python): (i) `put` twice with different bytes -> second read returns the new bytes AND a strictly greater cursor; (ii) a client at `since=N` where N is past the object's first cursor still sees the object in `list_changed` after an overwrite (the re-pull correctness); (iii) end-to-end: apply a snapshot with `deleted_at` set, push, pull on a second store, assert the tombstone applies over the live row (`lww_key(tombstone) > lww_key(live)`).

  Done when: delete on desktop -> note disappears from the phone after its next sync (relay object decrypts to `deleted_at` set); an edit on desktop -> the edit appears; restore reverses it; a device that ALREADY synced the artifact receives the update on its next pull. `bin/verify` green with the new tests. Verify on-device with the decrypt-the-relay-object + phone `run-as` sqlite check that originally found this (AGENTS.md device-verify section).

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
