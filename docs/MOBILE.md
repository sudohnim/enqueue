# MOBILE.md - the raven eye, sync, and a mobile Enqueue

This file is a work queue for an implementing agent, in the house style of `PROGRESS.md` and `docs/e2e/E2E.md`.
Do one checkbox per commit, verify each with its "Done when" line before checking the box, and keep every step atomic and idempotent.
`[AGENT]` is mechanical work an agent does; `[HUMAN]` is a stop-and-decide gate only Minh clears.
Never use the em dash; plain dash only.
Nothing here is started. This document is findings plus steps, not code.

There are three initiatives, in dependency order: the raven eye (independent, small), sync (the foundation), and the mobile app (needs sync first).

---

## Findings - how the three reference systems actually sync

Researched before scoping so the plan does not cargo-cult the wrong model.

### dequeue (the user's todo app) - cloud-authoritative, SSE push

- A cloud backend holds the canonical data; clients are thin. Not local-first.
- Live updates ride Server-Sent Events: `GET /events?token=<jwt>`, named events (`task`, `template`, `phrase_override`, `settings`), the server pushes "this changed" and the client re-fetches. `frontend/src/api/sync.ts`.
- The token is a query parameter because `EventSource` cannot send headers; validated on connect.
- Auto-reconnect on transient drops (the library's own `pollingInterval`; do not add a second reconnect loop on top); `403` is treated as terminal, `401` means refresh-and-retry once.
- Takeaway for Enqueue: borrow the SSE transport shape (query-token auth, named events, reconnect discipline), NOT the cloud-authoritative model. Enqueue is local-first and has no accounts.

### Obsidian Sync - local-first, E2E relay, per-file versions

- An off-site remote vault (a relay) holds encrypted copies; a full local copy is always on every device (works offline). Confirmed from the help page; the rest is the widely-known architecture.
- End-to-end encrypted: the client encrypts, the relay is a byte store that cannot read content.
- Live propagation over a persistent connection; per-file version history kept (encrypted) on the relay; selective sync by folder and size limits per file.
- Takeaway for Enqueue: this is the right spirit - local-first plus a dumb encrypted relay. It is what `E2E.md` already designed, minus a live-push relay.

### Enqueue today - local-first, no cloud, and a sync plan already written

- Local Python engine on `127.0.0.1:8787`, one SQLite library file, a Tauri v2 desktop shell (`desktop/`, `tauri = "2"`), static UI split into `src/enqueue/static/js/*` and `css/*`.
- `docs/e2e/E2E.md` already specifies sync: one encrypted canonical snapshot per artifact, last-writer-wins per artifact, no event log, provider-agnostic (any synced folder is a dumb byte replicator), PyNaCl / XChaCha20, phases E1 to E8.
- None of E1 to E8 is built. There is zero sync code in the repo today; every SYNC step below that names an E2E.md piece must build it first.
- E2E.md is stale in two places: it syncs `exhibits`/`exhibit_members` (dropped in migration 0019; `saved_pivots` carry that concept now) and it deletes `lens_judgments` rows on purge (the lens was removed in Phase M). Read E2E.md for the snapshot/LWW/crypto design only; substitute `saved_pivots` for exhibits wherever it says exhibits, and ignore the lens references.
- That design is Obsidian's model with a synced folder instead of a relay. A folder works desktop-to-desktop; it is awkward on iOS where app access to iCloud Drive or Dropbox folders is restricted.

### The synthesis this plan adopts

- Keep `E2E.md`'s per-artifact encrypted-snapshot LWW as the sync core. Do not re-design it.
- Add a dumb, end-to-end-encrypted relay as the transport (Obsidian's relay), because mobile cannot reliably use a shared folder. The relay stores `.enc` snapshots and content-addressed blobs and can read none of it.
- Give the relay an SSE stream for "something changed, pull" (dequeue's transport), so edits appear live instead of on a timer.
- Mobile runs no Python engine and no model. It captures (writes snapshots into sync) and reads (browses and reads the synced library plus keyword search). All AI enrichment - facets, entities, embeddings, chat - stays on the desktop and syncs down as derived data. This matches the user's ask: "very simple - capture links, pictures, notes, and read all the artifacts."

---

## The decisions to ratify before any sync or mobile code (HUMAN)

These are genuine forks; scoping both is cheap, guessing is not.

- [ ] **D.1 [HUMAN]** Relay vs synced-folder for the sync transport.
  Recommendation: a dumb E2E relay (Obsidian model), because it is the only transport that serves mobile cleanly and gives live push. The synced-folder path from `E2E.md` stays valid for desktop-to-desktop and can coexist.
  Decide: relay-first (this plan), folder-first (defer mobile), or both.

- [ ] **D.2 [HUMAN]** Where the relay runs.
  Options: self-hosted (a small container the user runs), or a hosted instance. Either way it is end-to-end encrypted and never sees plaintext (DEC-B, DEC-C in `E2E.md`).
  Decide the host so the mobile phase can point at a real URL.

- [ ] **D.3 [HUMAN]** Mobile platform.
  Recommendation: Tauri v2 mobile, iOS first, reusing the DESIGN.md system and a new simple mobile UI. One shell language (Rust) with the existing desktop, native capture plugins (share sheet, photo picker), a local SQLite read copy.
  Alternatives: a responsive PWA (fastest, weakest native capture), or fully native SwiftUI (most work). Decide before the mobile phase.

- [ ] **D.4 [HUMAN]** Ratify that mobile is capture-and-read only, with no model on device and no semantic search on device (keyword/FTS only), and that AI enrichment syncs down from the desktop. If mobile must do AI, that is a much larger plan and this one does not cover it.

---

## Phase EYE - the raven eye in the bottom ribbon (desktop UI only)

The home view already renders a living eye as the greeting emblem: a PNG eye whose pupil tracks the cursor (`src/enqueue/static/js/home.js`, the split frame plus pupil layer; assets `static/eye-frame.png`, `static/eye-pupil.png`, `static/eyeball.png`; styles in `css/home.css` under the greeting emblem).
The bottom ribbon's "Chat with AI" button still uses the flat SVG eye `svg("ask")` (`src/enqueue/static/js/pill.js`, two places: the wall ribbon and the in-chat ribbon).
This phase makes the ribbon eye the same living raven eye - purple pupil, cursor-tracking - and dials the weirdness up, with the click behavior unchanged. UI only.

- [ ] **EYE.1 [AGENT]** Extract the eye into a reusable piece.
  Anchor: the eye markup (`home.js` lines ~709-716: `.eye` > `.eye-blinkwrap` > `.eye-socket` > `.eye-pupil` plus `.eye-frame`) and the tracking logic (`mountEye`/`tearDownEye`, `home.js` lines ~794-888; the listeners are `pointermove` and `mouseleave` on `document`, not `mousemove`).
  Move both into one small factory, `makeEye(el)`, that injects the markup into a given element and wires its tracking. Put the factory in `js/icons.js` (it loads second, before `pill.js`, so the pill can call it). If a new `js/eye.js` is created instead, it must be added in TWO places or it silently never loads and is never checked: the `<script>` tags in `home.html` (before `pill.js`) and the hardcoded `JS_ORDER` list in `bin/verify`.
  Three constraints the factory must respect:
  - The travel math already self-scales from the socket's rendered size (`home.js` lines ~854-862), so the same code works at emblem size and ribbon-button size; keep that property.
  - Listener lifecycle: the pill re-renders its `innerHTML` on every navigation, so a naive mount adds a new `document` listener each render. Use ONE shared document-level `pointermove`/`mouseleave` pair that iterates all mounted eyes (or an equivalent idempotent mount). Never stack listeners per render.
  - `getElementById("greetEye")` is hardcoded today; the factory takes the element as an argument instead.
  Done when: the home greeting eye still tracks the cursor exactly as before (including hover-holds-centred and the dead-zone), the eye is produced by one shared function, no duplicate listeners accumulate across home renders, and `bin/verify` passes.

- [ ] **EYE.2 [AGENT]** Put the eye in the ribbon "ask" button.
  Anchor: the two `svg("ask")` uses in `pill.js` (aria-label "Chat with AI" on the wall, "Continue chat"/"Ask about this" inside a chat).
  Replace the static SVG with the shared eye at the ribbon button's size (the travel math self-scales, so no size-specific tuning); keep `onclick="openField('ask')"` and `chatOrAsk()` exactly as they are. Mount via the factory right after `pill.innerHTML` is set, once per rendered button, relying on EYE.1's shared listener so re-renders never stack listeners.
  Done when: the ribbon eye tracks the cursor, clicking it opens the ask field / continues the chat exactly as before, and the button's aria-label is unchanged.

**EYE.3 - folded into EYE.5, not a checkbox.** It was a verification step with no mechanical gate (`bin/check-contrast` cannot see PNGs), so an agent could tick it without looking. Its content - the pupil asset `eye-pupil.png` is ALREADY a vivid purple by design; do NOT mute it to lavender `#5e6ad2`; confirm it still reads purple at ribbon size - is now part of the human review.

- [ ] **EYE.4a [AGENT]** Dilation. The ribbon pupil dilates on hover and constricts on click.
  One reduced-motion rule covers all of EYE.4a-c, stated precisely because the doc trail conflicts: cursor tracking is ratified as functional, not decorative (L.7/M.4, comment in `mountEye`), and RUNS EVEN under `prefers-reduced-motion` - do not disable it. Gate only the new effects behind the media query.
  Done when: hover visibly dilates, click visibly constricts, tracking is unaffected, and under reduced motion neither happens; `bin/verify` passes.

- [ ] **EYE.4b [AGENT]** Idle saccades. When the cursor is still for several seconds, the eye glances to a random point, then returns to tracking.
  Done when: a still cursor produces an occasional glance that does not fight live tracking (a move during a saccade wins immediately), and reduced motion suppresses it; `bin/verify` passes.

- [ ] **EYE.4c [AGENT]** Blinking, built new. There is NO existing blink cadence anywhere in the codebase (`.eye-blinkwrap` is only a positioning wrapper; no blink keyframes exist) - build it, at irregular 5 to 20 second intervals, as a quick lid scale/clip on the blinkwrap.
  Done when: the eye blinks at irregular intervals in the 5 to 20 second band, never on a fixed metronome, and reduced motion suppresses it; `bin/verify` passes.

- [ ] **EYE.5 [HUMAN]** Desktop review: the ribbon eye reads as the raven watching, the weirdness is characterful not annoying, click behavior is identical, and reduced motion is respected. Purple check (from EYE.3): the pupil is still the same vivid purple as the home emblem and reads clearly purple at the ribbon button's small size; if the small render muddies it, the fix is a crisper asset, never a recolor toward lavender.

Verify (EYE.1 to EYE.4c): `bin/verify` (JS parse plus contrast) passes and the ribbon's ask/chat actions still work end to end.

---

## Phase SYNC - the relay and live transport (the foundation)

Gated on D.1, D.2. Build on `E2E.md` (read it first).

**This phase is built in two stages, plaintext first.** Encryption is a thin, separable layer: the snapshot format, the relay protocol, push, pull, SSE, and the LWW merge all move opaque bytes and do not care whether those bytes are encrypted. So the sync mechanics are proven with plaintext snapshots on a localhost/LAN relay (SYNC.1 to SYNC.7), and encryption is folded in afterward by wrapping the bytes at the relay boundary only (SYNC.8 to SYNC.9). Building this order de-risks the uncertain part (does sync actually converge across two devices?) without paying the crypto cost up front, and adds almost no rework because the two stages share the code.

What is deferred and what is not:

- **Deferred to stage two:** `E2E.md`'s E1 and E2 (crypto and keyring). The prototype does not encrypt.
- **NOT deferred, required in stage one:** `E2E.md`'s snapshot model and last-writer-wins merge (Phase E3: `sync/snapshot.py` plus its convergence property tests; sections 0 and 1 are the prose and glossary that define them). Encryption protects confidentiality; the LWW merge protects the data itself from silent loss. Dropping crypto for a test is fine. Dropping convergence correctness is not - that is the part that eats edits without telling you, and it is required from the first plaintext commit.

The relay stays a dumb byte store throughout: it holds per-device snapshot objects and content-addressed blobs, serves them back, and streams a "something changed" signal. It parses nothing. In stage one those bytes are plaintext canonical-JSON snapshots; in stage two they are the same bytes encrypted, and the relay code does not change.

- [ ] **SYNC.0 [HUMAN]** Ratify the two-stage order and the plaintext-prototype boundary.
  The prototype is localhost/LAN only, throwaway data, never a hosted relay, never real notes, never shipped. It exists to prove convergence and the live transport, then encryption (stage two) is mandatory before any real data or any non-localhost relay.
  Nothing from E2E.md is built yet. Confirm that E2E.md's Phase E3 (the snapshot model and LWW merge implementation, with its convergence property tests - not just sections 0 and 1, which are prose and glossary) is done or scheduled ahead of SYNC.4, because the prototype still needs it; only E1 and E2 (crypto) are deferred.
  Size this honestly: E3 - snapshot serialization, the LWW merge, and the convergence property tests - is the bulk of stage one's work, and it is checkboxed in E2E.md, not here. This phase's ten boxes are the relay and transport around it.

- [ ] **SYNC.1 [AGENT]** Specify the relay protocol as a short document `docs/sync-relay.md` before writing a server.
  It must define, concretely: the auth model (a per-library shared secret or device token, since there are no user accounts), the object namespace (`dev/<device_id>/artifacts/<id>.enc`, `blobs/<blob_name>`, mirroring `E2E.md`'s glossary except its `exhibits/` path - exhibits were dropped; saved-pivot sync is out of scope for this plan), and the four operations: list-changed-since, get-object, put-object (write-by-unique-name, never overwrite in place), and subscribe (SSE).
  Done when: `docs/sync-relay.md` names every endpoint, its request and response shape, and states plainly that the relay stores opaque bytes and can decrypt nothing.

- [ ] **SYNC.2 [AGENT]** Implement the relay as a standalone service (its own small FastAPI app, not inside the local engine).
  Endpoints from SYNC.1: `GET /sync/objects?since=<cursor>` (list changed object names plus a new cursor), `GET /sync/object/<name>` (bytes), `PUT /sync/object/<name>` (store bytes, reject overwrite of an existing name), `GET /sync/events?token=<secret>` (SSE stream emitting an event whenever any object changes).
  The relay stores objects on disk or object storage keyed by name; it parses none of them.
  Done when: a test can `PUT` an opaque blob, `GET` it back byte-identical, `list` shows it after a cursor, and an SSE client receives an event on the `PUT`.

- [ ] **SYNC.3 [AGENT]** Add a `SYNC_RELAY_URL` and a per-library sync secret to the engine's settings (alongside the existing settings, encrypted secret in the Keychain like the API key), plus a device token derived per `E2E.md`.
  Done when: `GET /settings` reports whether a relay is configured, and the secret is stored in the Keychain, never in a file.

- [ ] **SYNC.3b [AGENT]** The plaintext-prototype safety guard. Add a single module-level flag (for example `SYNC_PLAINTEXT_PROTOTYPE = True`) and a hard check on the push/pull path: when the flag is set, the sync client refuses to run against any `SYNC_RELAY_URL` whose host is not `127.0.0.1`, `localhost`, or a private-LAN address, raising a clear error rather than uploading.
  This makes it impossible for the unencrypted prototype to quietly graduate to a real or hosted relay. The flag flips to `False` only in SYNC.9, after encryption is in.
  Done when: pointing the sync client at a non-local URL while the flag is set raises and uploads nothing; pointing it at localhost works.

- [ ] **SYNC.4 [AGENT]** Push: when a local artifact snapshot is written, also `PUT` its snapshot object and any new blobs to the relay under this device's namespace. The snapshot producer does not exist yet - E2E.md Phase E3 (`src/enqueue/sync/snapshot.py`: `read_artifact_snapshot`, `serialize`, `winner`, `apply_snapshot`) must be implemented first, per SYNC.0. In the prototype the object is the plaintext canonical-JSON snapshot (`E2E.md` section 1); after SYNC.8 it is the same snapshot encrypted (`.enc`), and this push code is unchanged except for the one wrap call.
  Idempotent: re-pushing an unchanged snapshot is a no-op (same name, already present).
  Done when: editing an artifact on the desktop results in its snapshot object appearing on the relay, and re-running the push uploads nothing new.

- [ ] **SYNC.5 [AGENT]** Pull: a background sync worker (reuse the shared `Worker` class in `src/enqueue/worker.py`) that, on an SSE event or on a timer fallback, lists changed objects since its cursor, downloads them, and feeds them to the LWW merge from E2E.md Phase E3 (built in SYNC.4's prerequisite) to update local state.
  The SSE client mirrors dequeue's discipline: query-token auth, auto-reconnect on transient drop, a terminal state on auth rejection, a heartbeat.
  Done when: an artifact edited on device A appears on device B within seconds of the edit, with byte-identical local state (the E2E.md convergence invariant), and no polling storm when idle.

- [ ] **SYNC.6 [AGENT]** Conflict surface: when LWW discards a losing edit (DEC-A), keep the losing snapshot as a local version row (E2E.md already requires this) and surface it in the UI as a recoverable prior version, so a lost edit is never silently gone.
  Done when: two offline edits to one artifact resolve to the newer, and the older is visible and recoverable in that artifact's version history.

- [ ] **SYNC.7 [HUMAN]** Two-device desktop review of the PLAINTEXT prototype: edit on one, watch it land on the other live; go offline, edit both, reconnect, confirm LWW resolves and the losing edit is recoverable. This gate is load-bearing; convergence bugs are silent and destroy data. Stop here until convergence is proven; encryption below cannot fix a merge that loses edits.

### Stage two - fold in encryption (mandatory before any real data or non-localhost relay)

Only after SYNC.7 passes. This wraps the bytes at the relay boundary and touches nothing else - the snapshot model, LWW merge, relay, push, pull, and SSE are all unchanged.

- [ ] **SYNC.8 [AGENT]** Implement `E2E.md`'s E1 and E2 (crypto and keyring) if not already done, then wrap the boundary: `encrypt(snapshot_bytes, dek)` immediately before every `PUT`, `decrypt(bytes, dek)` immediately after every `GET`, and content-address blobs by `blob_name(content_hash, dek)` (all per `E2E.md`). The relay still stores and streams opaque bytes and its code does not change.
  Done when: relay objects are now ciphertext (a raw `GET` from the relay yields no readable JSON), and the two-device convergence test from SYNC.5/SYNC.7 still passes byte-identically through the encrypted path.

- [ ] **SYNC.9 [AGENT]** Flip `SYNC_PLAINTEXT_PROTOTYPE` to `False` (SYNC.3b) so a non-local relay is now allowed, since the bytes are encrypted. Re-run the E2E.md convergence property tests (E3) over the encrypted path.
  Done when: the flag is `False`, a non-local relay URL is accepted, a raw fetch from it is unreadable ciphertext, and E3 convergence still holds.

- [ ] **SYNC.10 [HUMAN]** Confirm on two devices through a real (non-local) relay that sync converges and the relay never holds plaintext (spot-check a raw object fetch is ciphertext). Only after this may sync carry real notes.

Verify (SYNC.2 to SYNC.6, plaintext stage): the relay's own test suite is green, `uv run pytest -q` is green, and a scripted two-engine LAN test shows convergence.
Verify (SYNC.8 to SYNC.9, encrypted stage): the same convergence test passes through ciphertext, a raw relay object is unreadable, and E2E.md's E3 property tests pass.

---

## Phase MOBILE - a simple capture-and-read Enqueue

Gated on D.3, D.4, and a working relay (Phase SYNC). Mobile is a thin client: it syncs the encrypted library from the relay into a local read copy, lets the person capture and read, and runs no model.

Scope, fixed: capture a link, capture a picture from storage or the camera, write a note; browse and read every artifact; keyword search over the synced text. Nothing else. No facets, no entities, no chat, no semantic search, no organize - those are desktop-only and arrive as synced derived data the mobile reader can display but not compute.

### Design (shape plus layout brief, no code)

Mode: Operate. The person reaches for mobile in two moments - to toss something in quickly (capture), and to look something up or read (browse/read). Both must be one thumb, two taps.

Visual world: inherit DESIGN.md exactly (light canvas, scarce muted lavender `#5e6ad2`, hairlines, whisper shadows, IBM Plex Sans). No new brand. The raven eye may appear as the app mark.

Structure (three surfaces, a bottom tab or a single scroll with a persistent capture control):
- Capture: the primary action, always one tap away (a large lavender capture button, or the share-sheet target so other apps push into Enqueue). One field, same four-outcomes logic as the desktop overlay (a URL becomes a link, text a note, an image an image) so behavior is identical across surfaces.
- Library: a vertical list or the square-card wall adapted to a single narrow column, newest first, each card tappable to read.
- Reader: the full artifact - note body, image, link preview, PDF pages - plus its synced summary and tags shown read-only.

Layout theses (from the layout lens): reading order is capture-first on the home surface, then the library; grouping by the SAVED / EVERYTHING ELSE shelves the desktop already uses; touch targets at least 44pt; safe-area insets respected; the capture control is the one fixed element, everything else scrolls.

- [ ] **MOB.1 [HUMAN]** Confirm the shape brief above (surfaces, capture-first, inherit DESIGN.md, read-only AI data). Adjust before any build.

- [ ] **MOB.2 [AGENT]** Stand up the mobile shell per D.3 (Tauri v2 mobile, iOS target), building and launching to the simulator with a blank screen carrying the DESIGN.md tokens.
  Done when: the app builds and launches on the iOS simulator showing the light canvas and the correct fonts, nothing else.

- [ ] **MOB.3 [AGENT]** Local library store on device: a local SQLite read copy plus the relay pull client (reuse the Phase SYNC pull path, no push-of-derived-data), so the phone holds the synced artifacts offline.
  Done when: after configuring the relay secret, the phone downloads and decrypts the library and can list artifact ids offline.

- [ ] **MOB.4 [AGENT]** The Library surface: a single-column list of artifacts, newest first, each row showing kind, title, and a snippet, tapping opens the Reader.
  Done when: every synced artifact appears in the list on the phone and opens.

- [ ] **MOB.5 [AGENT]** The Reader surface: render a note's markdown, an image, a link preview, and a PDF read-only, plus the synced summary and tags if present.
  Done when: each artifact kind reads correctly on the phone, and AI-derived summary/tags show when they exist and are absent quietly when they do not.

- [ ] **MOB.6 [AGENT]** Keyword search over the synced text (FTS over titles, bodies, annotations - no embeddings, no model).
  Done when: searching a word that appears in a synced note returns it; searching gibberish returns nothing (the same honesty as PLAN.md Phase Q, achieved trivially here because there is no dense leg).

- [ ] **MOB.7 [AGENT]** Capture on device: one field with the desktop overlay's four-outcomes logic (link, note, image), writing a new encrypted snapshot into sync (the push path) so it appears on every device.
  Wire the OS share sheet and the photo picker as capture entry points.
  Done when: capturing a link, a photo from the library, and a note on the phone each create an artifact that syncs to the desktop within seconds, and the desktop then enriches it (facets, entities) and syncs the derived data back for the phone to display.

- [ ] **MOB.8 [HUMAN]** Device review: capture from another app via the share sheet, from the photo library, and as a note; confirm each lands on the desktop and comes back enriched; browse and read the whole library offline; search by keyword. Confirm it feels very simple - two taps to capture, two to read.

Verify (MOB.2 to MOB.7): the app builds and launches on the simulator, capture round-trips to the desktop through the relay, and the library reads offline.

---

## Out of scope

- Any model, embedding, facet, entity, or chat computation on the phone. Mobile displays desktop-computed AI data; it never generates it.
- Multi-user or shared libraries. Sync is one person's devices, one library (the `E2E.md` assumption).
- The full event-sourced CRDT sync `E2E.md` explicitly rejected. LWW per artifact is the chosen model.
- Android, if D.3 picks iOS-first; it is a follow-on, not this plan.
- Changing the desktop's local-first engine. The relay is additive; with sync off, nothing about the desktop changes.
- Syncing `saved_pivots` (saved views) and chats. E2E.md synced exhibits, but exhibits were dropped; whether views sync is a follow-on decision. Mobile reads artifacts only.

## Dependency order

1. Phase EYE - independent, ship anytime.
2. Phase SYNC - needs E2E.md Phase E3 (snapshot core, unbuilt) before SYNC.4, and E1/E2 (crypto, unbuilt) before SYNC.8. Nothing else from E2E.md is a prerequisite.
3. Phase MOBILE - needs Phase SYNC working.

Ratify D.1 to D.4 before SYNC or MOBILE. EYE needs no decision.
