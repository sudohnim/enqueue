# PLAN.md - performance + quality backlog

This file holds only OPEN work.
Each task is self-contained: file:line evidence, the exact fix, and an exact Done-when.
Wait `bin/verify` green for each. Check a box only after the runtime claim is eyeballed.

## How to execute (read first, every agent)

1. One task per turn.
2. Use the exact file/line in the task; do not invent unrelated work.
3. `[x]` only after "Done when" is met AND `bin/verify` is green.
4. `[~]` = code-complete pending device verify.
5. `[ ]` = not started.
6. Never commit/stage.

---

## Phase PERF - low-hanging performance (quickest impact first)

These are concrete bottlenecks found in the search, sync, and answer paths. Each is fix-only.

- [x] **PERF.1 [AGENT] Fuzzy leg loads ALL titles/entities/annotations into Python.** `src/enqueue/retrieve/candidates.py:361-406` `_fuzzy_hits` executes three separate full-table SELECTs (artifacts, entities, annotations) then runs `SequenceMatcher` on every row. For a library of a few thousand artifacts this is O(N) Python per query and the worst per-query cost in the search pipeline (even when the hybrid already has a hit). Fix: skip the fuzzy branch when the query is not ambiguous - only run `_fuzzy_hits` when the fused (dense+keyword) result is empty OR when the top hit is weak (e.g. hybrid max score < KEEP_ABOVE). Implement by calling `_fuzzy_hits` from `_merge_fuzzy` only when `merge_AB_threshold` says results are needed; keep the call lazy otherwise. Verify: `enq search "chopper"` works the same; the `/search` endpoint latency for a fixed query drops by the fuzzy cost (measure via `time.enq search` if instrumented).
Done when: bin/verify green, query latency test shows fuzzy skipped for non-ambiguous queries.

- [~] **PERF.2 [AGENT] Push/pull N+1 fetches (1+N HTTP round trips per pull).** In `desktop/src/sync.rs` `sync_library` loops over each changed object and GETs `/sync/object/{name}` per object. With 500 artifacts this is 501 round trips so a cold unlock + pull over the internet takes ~50s (100ms each). The relay `/sync/objects` list endpoint earlier returns both name and data in ONE page (verification: the note is not that there's a batch endpoint - the fix is to have the SYNC client consume `objects[]` without needing N GETs when names come with data). Fix in the MOBILE sync (`desktop/src/sync.rs` `sync_library`, the `for obj in body["objects"]` loop): for each object name containing `data`, decrypt in place; only fall back to a per-object GET for blobs. Also do the same on the desktop `sync/client.py` pull path if it has the same loop. Verify: full backfill takes < 3s over LAN (95 artifacts vs 300ms each sequentially).
Done when: on-device with tethered `enq` server, pull of <300 artifacts takes <3s.
DONE (code-complete, device-verify pending) - via PARALLELIZE, not byte-bundling: the wire-format ban only forbids folding object bytes into the `/sync/objects` listing. The real cost was hundreds of SEQUENTIAL blocking `ureq::get` calls in `sync_library`. New `fetch_snapshots_parallel` (desktop/src/sync.rs) collects the `dev/*.enc` names during the listing walk, fetches + decrypts them across an 8-worker `std::thread::scope` pool (network + decrypt touch no DB), then the caller applies the snapshots on the single conn - `apply_snapshot` is LWW per artifact so order is irrelevant. Same per-object GET, same wire format, just not serialized: N round trips -> ~N/8 wall-clock. cargo check + bin/verify (incl Android compile) green. Left [~] until a real-device backfill confirms the <3s target.

- [x] **PERF.3 [AGENT] Push client opens/closes a fresh httpx.Client per artifact.** `src/enqueue/sync/client.py:push_all` opens `httpx.Client()` inside the loop per artifact (not per push). Fix: create ONE `httpx.Client` for the whole push_all (or push_artifact) and reuse it. Verify: push_all throughput of 100 notes measured via time spent.
Done when: bin/verify green, push_all is millis faster.

- [ ] **PERF.4 [AGENT] Relay leaf/snapshot re-read patterns.** `src/enqueue/sync/snapshot.py:read_artifact_snapshot` issues 5 separate queries per artifact (artifact + annotations + page_text + versions + tags). In `push_all`, this is 5 queries/artifact x N artifacts. Fix: annotate/select-related join to one query (fetch artifact + latest annotations/page_text/versions/tags in ONE join, then map to snapshot). Do NOT change the snapshot shape (mobile pulls the wire format). Verify: `push_all` costs N queries + 5 joins instead of 5N.
Done when: `push_all` timing improves; snapshot shape identical.

- [x] **PERF.5 [AGENT] Title lookup N+1 on ranked fuzzy.** `src/enqueue/retrieve/candidates.py:474-483` `_merge_fuzzy` attaches titles by executing per-artifact `SELECT title, kind FROM artifacts WHERE id = ?` for each fuzzy-only hit. Fix: batch via the same json_each pattern used elsewhere (one SELECT `WHERE id IN (SELECT value FROM json_each(?))`). Also, the ranked ids list in `candidates()` at line 753-760 fetched titles the same way and then still passes `title=None` on fuzzy-only; unify with the batch. Verify: binary search shows fewer SQL round-trips.
Done when: bin/verify green, no per-id title lookups remain.

- [x] **PERF.6 [AGENT] Re-decrypt + discard stale pull snapshots.** `desktop/src/sync.rs` `sync_library`'s per-object GET decrypts and deserializes full JSON just to extract `(updated_at, _device_id)` for the LWW no-op check. Fix: before decrypt, try to extract only those two fields from the JSON wrapper (if the serialize layer writes them first) and only decrypt/apply if the LWW key is fresh. If the wire format doesn't allow partial reads, accept this as a partial win (skip decrypt only when the name alone encodes updated_at; otherwise add a comment explaining why). Verify: pull of a library with 50 stale docs shows CPU drop.
Done when: bin/verify green; one comment recorded why partial extract is (not) viable.

- [ ] **PERF.7 [AGENT] Gray-zone judge fires per sub-query instead of batched.** `src/enqueue/chats.py:300` collects gray-zone chunks per query, then `judge_gray_zone` per sub-query (the expanded flow re-enters `passages` per sub-query). Fix: collect gray chunks from all sub-queries in ONE variable then `judge_gray_zone` once in `passages`. Verify: unit test asserts one judge call for 3 sub-queries.
Done when: bin/verify green, only one judge call per pass.
SKIPPED (premise wrong): `passages()` already batches - it accumulates all gray chunks into one `gray_chunks` list and calls `judge_gray_zone` exactly ONCE (chats.py:311-341), plus one more batched call for gray facet/entity hits (chats.py:425-434). There is no per-sub-query loop: `passages` has a single caller (chats.py:675) invoked once per question, and no query-expansion path re-enters it. Nothing to batch.

---

## Phase DEADCODE - dead code removals (safest cleanup, ship-zero)

Each item is exact-removal guidance. All verified no callers.

- [ ] **DEAD.1 [AGENT] Unused Python constant.** `src/enqueue/api/wall.py:58` `_ARTIFACT_COLUMNS = (...)"` is never referenced (grep shows only the definition). Delete the constant.
Done when: bin/verify green.
SKIPPED (premise wrong): `_ARTIFACT_COLUMNS` IS imported and used by `src/enqueue/api/pivots.py:15,61`. Not dead. Do not delete.

- [x] **DEAD.2 [AGENT] Unused Python constant.** `src/enqueue/cli.py:607` `RESULTS_DIR = EVALS_DIR / "results"` is never referenced. Delete.
Done when: bin/verify green.

- [x] **DEAD.3 [AGENT] Unused JS function.** `src/enqueue/static/js/settings.js:1001` `copyPairingCode()` is defined but never referenced. Delete the function.
Done when: bin/verify green.

- [x] **DEAD.4 [AGENT] Unused CSS class.** `src/enqueue/static/css/base.css:270-276` `.btn.inverse` and `.btn.inverse:hover` apply to a selector that no element has. Delete the rule.
Done when: bin/verify green.

- [x] **DEAD.5 [AGENT] Unused CSS class.** `src/enqueue/static/css/chat.css:40-54` `.said.streaming` (with ::before animation) is never used. Delete.
Done when: bin/verify green.

- [x] **DEAD.6 [AGENT] Fetch missing-CSS (mobile).** `src/enqueue/static/mobile.html` has `document.getElementById("capture_btn")?.addEventListener(...)` guarded with `?.` because the element was removed; safe-cleanup by removing the capture_btn guard entirely (was already a dead-element guard).
Done when: bin/verify green.

- [x] **DEAD.7 [AGENT] `### Dangerous no-ops` in Rust device-config.** `desktop/src/lib.rs:mobile_capture_image` and `mobile_save_cropped_image`: the "If push succeeded" block does a full relay HTTP GET to check the object exists, then unconditionally `UPDATE artifacts SET status='ok'` and `DELETE FROM capture_outbox`. This GET-per-push is an extra round trip whose result is already known (the push returned OK). Fix: rely on the push result only (if push_snapshot returned Ok, the object is on the relay; no need to GET it back). Verify: build and verify passes.
Done when: bin/verify green, dead-code note removed.

---

## Phase UIUX - UI/UX performance (desktop + mobile)

Listener-leak fixes come first. After each fix, re-render-only-after-listener-cleanup.

- [ ] **UIUX.1 [AGENT] mountCollapsible re-attaches listeners on every wall switch.** `src/enqueue/static/js/home.js:222` `mountCollapsible()` adds `.grouptoggle` click listeners per section each time `setWallGroup()` runs (home.js:747, 772). On every Type/Tags switch, listeners stack. Fix: clear old listeners by cloning nodes (standard pattern: `view.querySelectorAll(".grouptoggle").forEach(btn => btn.replaceWith(btn.cloneNode(true)))` BEFORE binding) or use event delegation (one listener on `.wallgroup` switching based on `e.target.closest('.grouptoggle')`). Verify: 10 successive mode switches in the desktop show no listener stacking (use `getListeners` via CDP or just verify no duplicate clicks).
Done when: bin/verify green, no duplicate listener fires.
SKIPPED/REVERTED (premise wrong, like UIUX.2): `setWallGroup` rebuilds `#wallbody` via `slot.innerHTML = wallBodyHtml()` (home.js:285) on every Type/Tags switch, so the `.grouptoggle` buttons are fresh nodes each time and old listeners are GC'd - they never stacked. The clone-replace "fix" was pure DOM churn against an already-fresh tree and showed up as switch lag; reverted to a plain addEventListener.

- [ ] **UIUX.2 [AGENT] Tag chip listeners re-attached on every artifact page load.** `src/enqueue/static/js/artifact.js:203-206` and `:225-232` (`mountTagRow` + `mountViewsRow`) re-attach `.tagx`/`.viewchip .tagx` listeners on `showArtifact(id)`.
Fix: convert to event delegation at the drawer level OR remove/bare reset first: query old `.tagchip` and stripe off old listeners before adding (or use `container.replaceChildren()` to trash compared DOM before adding fresh chips). Try the delegation approach: bind one `click` on `drawer` with `if (e.target.closest('.tagx'))`.
Verify: no duplicate remove/tag handlers on a second showArtifact.
Done when: bin/verify green, handlers are idempotent.
SKIPPED (premise wrong): `showArtifact` at artifact.js:492 does `view.innerHTML = html` - a full DOM replace - before `mountTagRow`/`mountViewsRow`. The old `.tagrow`/`.viewchip` nodes and their listeners are destroyed and GC'd, so each render gets fresh nodes with exactly one listener. No stacking. addTag/removeTag re-render via the same full-replace showArtifact. Nothing to fix.

- [x] **UIUX.3 [AGENT] Input rules run on every keystroke; debounce missing.** `src/enqueue/static/js/artifact.js:1134` editor `input` handler runs `applyInputRules` (5 regex scans) AND `refreshTitleHeader` on every keystroke. Fix: debounce `applyInputRules` by 150ms (or run it on `change` on contenteditable blur; but debouncing is better for live-markdown responsiveness). Also debounce title checkbox. Verify: typing 200 chars executes applyInputRules ~1 time instead of 60.
Done when: bin/verify green, visual correctness same.

- [x] **UIUX.4 [AGENT] Polling with no exponential backoff.** `src/enqueue/static/js/search.js:35` reloads `/doctor` every 1s with fixed interval until `index_state === "ready"`. `src/enqueue/static/js/chat.js:627` polls `/chats/<id>` every 2s fixed until assistant finishes. Fix: exponential backoff with 5s cap (factor 1.5x, max 5s), and abort on navigation/test teardown. Implement as a generic `poll(fn, {min, max, factor})` util in `util.js`, then use in both sites. Verify: first poll no later, later polls slower.
Done when: bin/verify green.

- [ ] **UIUX.5 [AGENT] Library renders all cards on sync event.** `src/enqueue/static/mobile.html` `sync-done` handler calls `renderLibrary()` which renders ALL cards/shelves from scratch. Fix: incremental - only append new cards (need artifact ids from sync event). `renderLibrary` is re-rendering known data additionally; events include `artifact_ids` (from `list_artifact_ids`) so compute diff and insert missing ones. Leverage already-known DOM node roughly by id.
Verify: cold-trigger a sync with only new documents in browser and count DOM rebuilds (simulate via cdp or manual test).
Done when: bin/verify green.
SKIPPED (same as SYNC.5): the coalesce + pulled-guard already cap this to one rebuild per frame and only when a pull applied. A bespoke incremental card-diff renderer is a second rendering paradigm for marginal gain at card counts the surface won't hit - fails the simplicity/maintainability bar. See SYNC.5 note.

- [ ] **UIUX.6 [AGENT] Layout thrash (offsetWidth).** `src/enqueue/static/js/home.js:797` and `src/enqueue/static/js/artifact.js:1380` read `offsetWidth` to retrigger a CSS animation. Fix: use `getAnimations()` API or re-insert the element level; safest fix is to give the previously animated element a class ONCE without needing the reflow (simply skip retriggering on same class). Verify: re-run the swap path via browser snapshot to confirm new class applied.
Done when: bin/verify green, no forced sync reads.
SKIPPED (working as intended): both sites use the canonical remove-class -> `void offsetWidth` -> add-class idiom to REPLAY a CSS animation, and each fires once per discrete user event (a new greeting phrase, a save landing) - one synchronous layout read, not per-frame thrash. The reflow is exactly what forces the animation to restart on a repeat event; `getAnimations().cancel()` is more code and flakier in Android WebView, and the "skip on same class" alternative would defeat the replay. Left as-is.

---

## Phase SYNC - mobile <-> desktop (the highest benefit at scale)

Do NOT change the E2E model (LWW per snapshot, per-device names). Only make push/pull cheaper.

- [ ] **SYNC.1 [AGENT] Missing client-side high-water mark.** `src/enqueue/sync/client.py:push_all` and `push_artifact` create snapshots for EVERY artifact, no client-side dedup (PLAN.md shows a planned `synced_snapshots(name, updated_at)`). Fix: on push success write `synced_snapshots(name, updated_at)`; on push attempt, skip if `synced_snapshots[name] == updated_at`. Migration: add this table via a NEW migration version (do a NEW revision - never edit stored migration code e.g. existing migration files). Sources: `shiny.synced_snapshots` name / description("TRACK table"). Note push_all is one-shot by BACKFILL.2, so this matters for REBACKFILL or second device, not initial; the docs say so.
Verify: `push_all` twice in a row skips all (2nd run is a no-op).
Done when: bin/verify green, synced_snapshots delta logic confirmed.
SKIPPED (correctness hazard > one-shot micro-opt): `push_all` is one-shot (BACKFILL.2's `sync_backfill_done` guard); its own docstring notes the ONLY re-run contexts target a fresh or switched relay, where pushing every artifact is exactly the intent. A `synced_snapshots(name, updated_at)` high-water table would be a second source of truth that must be invalidated on that very relay-switch path - a stale entry (`name@updated_at` marked synced) would wrongly SKIP a push the new/empty relay needs, silently corrupting the rebackfill it is meant to speed up. That coupling fails robustness + simplicity for a path that runs once. Per-mutation pushes already go through `push_artifact` on each edit, so steady-state is not re-pushing everything anyway. Not worth a new table + migration + invalidation logic.

- [x] **SYNC.2 [AGENT] Relay storage missing index on cursor.** `src/enqueue/relay/storage.py:58-65` `list_changed(since)` reads objects WHERE cursor > ? ORDER BY cursor with no index. At scale (thousands) this is a full scan. Fix: add `CREATE INDEX IF NOT EXISTS idx_objects_cursor ON objects(cursor)`. Verify: `sqlite3 EXPLAIN` shows INDEX search.
Done when: bin/verify green, query plan uses index.

- [ ] **SYNC.3 [AGENT] SSE listener duplication on reconnect.** `src/enqueue/relay/app.py:hub` allows duplicate queues per device when a client keeps reconnecting (no dedup on device_id in `subscribe`). Old queues are abandoned, new queues accumulate (each fire events twice, and the mobile app fires sync per event). Fix: on `subscribe`, purge any stale queue keyed by the same device_id, and reuse the device queue instead of spawning another. Or replace with per-device single-assignment. Verify: reconnect from the same device 5 times does not produce 5 sync triggers.
Done when: bin/verify green.
SKIPPED (fix conflicts with the relay's zero-metadata design; leak already bounded): (1) the relay is deliberately identity-free - every device shares ONE bearer secret and "the object name is the only metadata it ever sees" (storage.py). The SSE endpoint has no device_id to key on, so "purge the stale queue for this device_id" cannot be implemented without ADDING client identity the relay is designed never to hold - a privacy regression, not a cleanup. (2) The accumulation premise does not hold: `_sse_stream` runs `finally: hub.unsubscribe(queue)` on disconnect, and the 15s heartbeat write fails on a half-open socket and triggers that same cleanup, so a dropped/reconnected client's old queue is removed within ~15s. Duplicates require TWO concurrently-live connections, which EventSource reconnect does not create. (3) The residual (a device gets its OWN push echoed back) is already absorbed client-side: mobile `sync-done` only re-renders when `pulled > 0` (mobile.html:3881), so a self-echo no-op sync is silent. Net: no change worth trading the relay's metadata-free property for.

- [ ] **SYNC.4 [AGENT] Blob re-upload on title-only edit.** `desktop/src/lib.rs::mobile_update_note`/`mobile_save_cropped_image` (try to) re-pushes the blob on title edit (if the artifact kind is image/pdf/file). Fix: check `content_hash` unchanged → skip blob push. (Blob changes only on fresh edit/crop.) Verify: tagging an image file does not re-encrypted and re-upload the blob.
Done when: bin/verify green, no blob re-encryption on metadata edit.
SKIPPED (premise moot for the title-edit case): no mobile mutation path pushes blob bytes. `mobile_update_note`/`mobile_add_tag`/etc. call `queue_mutation_push` -> the outbox drains via `push_snapshot`, which only PUTs the metadata `.enc` object (desktop/src/sync.rs:187) - never blob bytes. A title/tag edit therefore cannot re-encrypt or re-upload a blob. No content_hash guard needed.
BUT this analysis surfaced a real, separate BUG (now FIXED): the capture paths (`mobile_capture_image`, `mobile_save_cropped_image`) and the outbox drainer (`mobile_outbox_push`) ALSO pushed snapshot-only - they stored the blob locally but never uploaded it to the relay. So a picture taken/uploaded on the phone never reached any other device (notes/links have no blob, which is why they synced fine). Added `crate::sync::push_blob` + a `push_capture_blob` helper; all three sites now upload the encrypted, content-addressed blob and only clear the outbox row once it lands (else it retries). See resolution log.

- [ ] **SYNC.5 [AGENT] Mobile library render doesn't incremental-update.** `src/enqueue/static/mobile.html:3870` `sync-done` re-renders the ENTIRE library (all shelves + cards) on every small sync. Fix: id-set diff → only `insertAfter` or `replaceChild` new/changed cards. Implementation hint: keep a `document.querySelectorAll('[data-id]')` map; on sync, render once at end of loop with patch (don't re-render EVERY shelf). Must intersect with UIUX.5 (desktop).
Done when: bin/verify green.
SKIPPED (cheap wins already landed; diff-render fails the lean bar): the two real wins are in place - `sync-done` only re-renders when `pulled > 0` AND the library is visible (mobile.html:3881), and `renderLibrary` coalesces a burst of triggers into ONE rAF repaint (mobile.html:2679). What remains - a per-card id-diff renderer - is a SECOND rendering paradigm beside the full rebuild (shelf-membership reassignment when a pin moves, ordering, stale-node tracking), a permanent maintainability tax for a gain that only shows at card counts a phone will not reach near-term. Against the stated "keep it lean, simpler data models" north star, the full rebuild (a few ms for hundreds of cards, fired at most once/frame) is the right call. Cost-bias check: this would still be the pick at 10x effort - the reason is simplicity/maintainability (one render path), not that the diff is more work.

- [x] **SYNC.6 [AGENT] Decrypt+discard on stale gaps reduced before calling LWW check.** Add a pre-check before full decrypt: try parse plain text wrapper first; only decrypt when really needed. (PERF.6 already covers this; this is tracking explicitly for mobile pull.)
Done when: bin/verify green; PERF.6 done.

---

## Phase SEARCH - quicker answers + quicker searches

Avoid touching schema. All API-only performance.

- [ ] **SEARCH.1 [AGENT] `/search` endpoint no cursor pagination.** `GET /search?q=...&limit=N` returns top-N only. Do **not** add offset pagination (re-navigating a changing result list is worse than CLEARPagination). Instead cache + ETag the top result set. Fix: return the top 50 by default plus a `Link: </search/next>` cursor header based on ranked-order blob id + score, optional. Verify: `/search` latency for load + scroll drops slightly.
Done when: bin/verify green.

- [ ] **SEARCH.2 [AGENT] `/chats/passages` re-runs full retrieval when a query repeats.** `GET /chats/passages?q=...` runs the whole pipeline each call. Fix: append a short `Cache-Control: private,max-age=30s` (or 5s for lighter hold); or cache result hash per (query, scope) for a very short window (correct while ingest does not invalidate). Or both. Verify: a second request for the same question is cached.
Done when: bin/verify green; cache hit (2nd call) < first call.

- [x] **SEARCH.3 [AGENT] Titles/topics not parallelized with answer gen.** `chats_worker.py::compute` runs `_name`+`_retopic` AFTER the answer. Titles/topics generation is creative not blocking, but a model call per request in sequence. Fix: NONE - comment says their failure is best-effort, and any reordering fights the already-working `chats_worker`. Mark comment if doing. Keep this strict.
Done when: n/a.

- [x] **SEARCH.4 [AGENT] Gray-zone judge fires per sub-query.** PERF.7 covers it. Keep as tracked item.
Done when: PERF.7 done.

- [ ] **SEARCH.5 [AGENT] Facet/entity legs lack cross-collection LIMIT discipline.** `src/enqueue/retrieve/candidates.py:923-962` loosely overfetches and then truncates. It's fine at limit=20-ish or prefetch=100, but the facet and entity legs duplicate their budget (each returns `per_query` rather than splitting the total). Fix: split `per_query` across chunk/facet/entity legs (or just trust their weight in RRF). Mainly document how `per_query` indicates the intended window size; skip this if not concrete enough.

---

## Phase FACET - cross-functional/sectional linking (accuracy)

Accuracy PR task: improve topic relevance over topic-only hits, while leaving retrieval shape.

- [ ] **FACET.1 [AGENT] Why-not-in-context linkage.** `src/enqueue/retrieve/candidates.py:739-750` - hits only filtered by `hit_is_stale`, and `body_version/model_version` provenance clips things explicitly. Facet "statement" quality needs provenance gating. Fix: at generation time `ingest/facets.py::_artifact_is_model_stale` checks ONLY on model_version; the retrieval-time check `retrieve/candidates.py::hit_is_stale` checks (body_version, model_version). Add the same provenance gate to `ingest/facets.py::_artifact_is_model_stale` so a facet regen is triggered when the BODY moves, not only when the model changes.

- [ ] **FACET.2 [AGENT] `hit_is_stale` docstring clarifies wrapper.** Add comment at `src/enqueue/retrieve/candidates.py:617-622` and `src/enqueue/ingest/facets.py:165-200` clarifying `hit_is_stale`'s wrapper: provenance via `(body_version, model)` from `artifact_versions MAX(created_at)`. Currently `ingest/facets.py::_artifact_is_model_stale` uses the same query but only checking `model_version`, whereas the retrieval equivalent checks both. Already consistent; just label both.

---

## Phase DATA-MODEL - cleaner data-model shape (readability only)

Small structural doc-fixes, no schema changes.

- [x] **MODEL.1 [AGENT] `_fuzzy_hits` docstring.** `src/enqueue/retrieve/candidates.py:361-406`'s doc claims `Fuzzy matching over the whole corpus's chunk text is too slow` - but it loads ALL titles/entities/annotations too, which is not fully true: annotate aggregation as the issue and (PERF.1) the right fix direction in the docstring.

- [ ] **MODEL.2 [AGENT] `mobile.html` JS file size note.** Mobile.html is 4,000+ lines (inline JS + CSS + markup). The mobile JS + CSS files should move to `static/js/mobile.js` and `static/css/mobile.css` files (none exists now - everything inline). This would let pip/browsers reuse server-level caching headers (e.g. 1-year for fonts).
Done when: bin/verify green; move documentation for cleanliness (move UI; nothing else).

- [ ] **MODEL.3 [AGENT] `settings.js` pollers.** `src/enqueue/static/js/settings.js` has rendering code mixed with settings sources. A shared `settings` util in `static/js/util.js` could be used elsewhere; HTML delegation is right, so focus as not strictly performance but cleaner: separate the `linkQR` builders out.

---

## Phase VAULT - PIN-encrypted secret vault (new feature, scoped not built)

Hide chosen artifacts from every normal view and put them behind a PIN that actually encrypts them at rest.
This is a real vault, not a filter with a lock screen: the PIN is load-bearing.

### Decision record (settled with the user)

- The PIN is the vault key, not a view gate.
The PIN derives a KEK (argon2id) that unwraps a random per-library `vault_key`; vaulted content is encrypted at rest with `vault_key`, so nothing but the PIN decrypts it - not disk forensics, not another device, not the relay.
This is the "protect" branch from the tradeoff, chosen over obscurity-only because for a privacy-first product a vault that leaves plaintext at rest is a false promise (robustness / smallest-blast-radius).
- Reuse the existing recovery-phrase wrap verbatim: `crypto.derive_kek(pin, vault_salt)` + `crypto.wrap(vault_key, kek)` -> `vault_by_pin`, mirroring `keyring_file.unlock_with_recovery` and `dek_by_recovery`.
This adds no new crypto paradigm; it is the same mechanism the DEK recovery already uses.
- The wrapped `vault_by_pin` + `vault_salt` sync (like `dek_by_recovery`), so every device shares one vault unlocked by one PIN; the raw `vault_key` never touches the relay.
- Vaulting de-indexes (removes from embeddings + FTS) and un-vaulting re-indexes.
"Not in the index" is a hard guarantee; "filtered from every query" is a soft one that leaks the moment a site is missed.
- Access is a mundane, non-inviting Settings row (candidates: "Diagnostics", "Storage details", "Cache & data") that opens a PIN entry, not the contents.
- Mobile vault view is one infinite vertical scroll (virtualized, chronological); desktop vault view reuses the normal wall display filtered to vaulted-only.
- The vault auto-locks (drops the derived key from memory) on app background/close and after inactivity; re-entry needs the PIN again.

- [x] **VAULT.1 [AGENT] Data model: `vaulted_at` column + additive snapshot field.**
Add `vaulted_at TEXT` to `artifacts` via a NEW Python migration (next revision after 0024) and the Rust `init_schema` + duplicate-safe `ALTER TABLE ... ADD COLUMN` in `desktop/src/sync.rs`.
Carry it in `build_snapshot`/`read_artifact_snapshot` and `apply_snapshot` on both ends, copying the `purged_at` implementation line-for-line (snapshot.py:156-162, sync.rs:108-385).
Done when: bin/verify green; a vaulted artifact round-trips desktop<->mobile with `vaulted_at` intact.

- [x] **VAULT.2 [AGENT] Vault key: PIN-derived, wrapped, session-unlocked (local lifecycle).**
On first vault setup generate a random 32-byte `vault_key`; store `vault_salt` + `vault_by_pin = crypto.wrap(vault_key, crypto.derive_kek(pin, vault_salt))` in `keyring.json` (never the raw key).
`vault.unlock(pin)` (mirrors `keyring_file.unlock_with_recovery`) unwraps into process memory only; `vault.lock()` drops it.
DONE: `src/enqueue/vault.py` + `keyring_file.vault_wrap_{get,set,clear}`; 6-digit enforced; zero-knowledge (no recovery slot). Tests in `tests/test_vault.py` (8) green - wrong PIN fails, right PIN unwraps, raw key never on disk, lock clears memory, no recovery path. The inactivity/background auto-lock is wired at the UI in VAULT.6.

- [~] **VAULT.2b [AGENT] Sync the vault wrap cross-device (`lib/vault.enc`).**
Split from VAULT.2 so every paired device unlocks the same vault with the same PIN.
Push `{vault_salt, vault_by_pin}` as a DEK-encrypted relay object `lib/vault.enc`, mirroring `push_pivots`/`lib/pivots.enc`; on pull (desktop `client.pull`, mobile `desktop/src/sync.rs`), store it into the local keyring when absent/newer.
The object is PIN-wrapped THEN DEK-encrypted, so the relay still sees only ciphertext and the PIN never leaves the device.
Done when: setting up the vault on device A, then pulling on device B, lets B unlock with the same PIN; bin/verify green.

- [x] **VAULT.3 [AGENT] Encrypt vaulted content at rest.**
On vault: encrypt the artifact `body` (and, for image/pdf/file, the blob bytes) with `vault_key` and store the ciphertext in place; on unvault: decrypt back.
Define the exact protected set in the task (body + blob + any derived text that could leak); leave `id`, timestamps, and `vaulted_at` in clear so sync/LWW still work.
Requires the vault unlocked (VAULT.2); if locked, the toggle prompts for the PIN first.
Done when: a vaulted note's plaintext is absent from `enqueue.db` and the relay object; unvault restores it byte-identical.

- [x] **VAULT.4 [AGENT] Exclude vaulted from every live surface + de-index.**
Add `AND vaulted_at IS NULL` to every live-artifact query - the same ~8-10 sites that carry `deleted_at IS NULL` today: the wall/`api/artifacts.py`, `retrieve/candidates.py`, `index/store_sqlite.py`, chat passages (`chats.py`), `pivot.py`, `export.py`, and the 5 Rust query sites in `desktop/src/sync.rs`.
On vault, remove the artifact from the embeddings + FTS index; on unvault, re-index it.
Done when: a vaulted artifact appears in NO wall, search, chat answer, pivot, or export, on either surface, verified by test; un-vaulting brings it back everywhere.

- [~] **VAULT.5 [AGENT] Lock toggle + icon (both surfaces).**
Desktop: a lock action in the artifact title-action group (`static/js/artifact.js`, beside pin/trash); mobile: a lock action in the reader actions (`static/mobile.html`).
Wire an engine endpoint + a Tauri `mobile_set_vault` command that vaults/unvaults (calls VAULT.3 + VAULT.4), bumps `updated_at`, and pushes.
The toggle is disabled/prompts when the vault is locked.
Done when: clicking the lock removes the artifact from the current view and it reappears only in the vault; round-trips across devices.

- [~] **VAULT.6 [AGENT] Vault view + decoy entry, with the layout/shape spec below.**
A Settings row with a mundane label opens a PIN pad (not the contents); a correct PIN unlocks and routes to the vault view; a wrong PIN shows a quiet "incorrect" with no hint that a vault exists.
Build the two layouts to the shape spec below.
Done when: the decoy row reveals nothing without the PIN; the vault lists exactly the vaulted artifacts; leaving/backgrounding re-locks.

### VAULT layout + shape (the design the user asked to run)

Mobile - decoy is an "Events" section in Settings (same as desktop):

- Settings gains an "Events" section that shows the emitted events when tapped, plus a separate "Diagnostics" button that prompts for the 6-digit PIN; a correct PIN opens the vault view, a wrong PIN reads as a normal failed diagnostics action.

Mobile vault view - "infinite vertical scroll":

- One continuous, virtualized vertical feed (a single `FlatList`), chronological by `updated_at` desc, NOT the shelved Saved/Everything-else grouping the library uses.
- Reuse the existing card grammar (`renderNoteCard`/`renderImageCard`/etc.) so a vaulted card looks like a normal card, with the lock glyph swapped for an "un-vault" affordance and the kind dot tinted to read as vaulted.
- A slim sticky header: the mundane label as the title, a lock-now button, and the count; no search and no mode chips (the vault is a flat list, not the wall).
- Lazy-decrypt on scroll: decrypt each card's protected fields only as it enters the viewport (reuse the mobile blob-cache pattern), so unlocking the vault does not decrypt everything at once.
- Empty state: a boring, plausible line consistent with the decoy ("Nothing stored.") so a shoulder-surfer sees nothing remarkable.

Desktop - decoy is a real "Events" tab (settled with the user):

- Add a new Settings tab labeled "Events" that ACTUALLY works: it lists the events the app emits (the sync/SSE/ingest event stream), so the tab is genuinely useful and reads as ordinary diagnostics, not a hidden door.
- Inside the Events tab, a button labeled "Diagnostics" prompts for the 6-digit PIN; a correct PIN opens the vault view, a wrong PIN behaves like a normal failed diagnostics action (no hint a vault exists).
- The vault view itself reuses the normal wall display component scoped to `vaulted_at IS NOT NULL`, its own route (e.g. `#vault`); same cards/shelves, a persistent "Locked vault" label + lock-now control replace the greeting/hero; body/title are decrypted client-visible only while unlocked.
- No capture pill and no global search inside the vault route (nothing pushes a new artifact straight into the vault by accident).

### VAULT decisions (settled with the user)

- PIN is 6 digits.
Add a lockout/backoff after repeated wrong entries (exact N TBD during VAULT.6, default to escalating delay rather than hard lockout so a real owner is never permanently locked out).
- A forgotten PIN is UNRECOVERABLE by design.
The vault is zero-knowledge: `vault_key` is wrapped ONLY by the PIN, never by the recovery phrase, so no path (recovery phrase, relay, another device) can decrypt vaulted content without the PIN.
This is the honest guarantee; the UI must warn plainly at setup that losing the PIN loses the vaulted data.
- Any artifact kind is vaultable in v1, PDFs included, so blob-at-rest encryption (VAULT.3) is in scope from the start, not deferred.

---

## What NOT to do (durable context)

- Do not re-shuffle migration files (never edit migration files to add a new version).
- Do not change wire-format (the desktop/push/pivots JSON across sessions share strings).
- Do not change str= settings.json (this is used for the mobile app sync-link literal).
- Do not break `answer.shape`: ingestion of `GroupArtifact` consumes sentences of text; even when debugging passes the wrong shape back this planner must stand firm on wire validation.
- Do not modify the multi-queue snapshots to INCLUDE method get or to fetch bytes per object misconception (spec '/sync/objects?since=N&limit=500' by {name,sync,data}-mixes GET increments are optional).


---

## Resolution log (this pass - no commits)

Boxes flipped to [x] have code/comment landed and bin/verify green. Items left [ ] are deliberate SKIPs with reasons below (premise wrong, or the fix loses more than it gains under the quality/simplicity/robustness bar). None were dropped silently.

- **PERF.1/3/5, SYNC.2, DEAD.2-7** - DONE (code in tree; boxes reconciled after an external PLAN.md reset). DEAD.2 also required removing a stale `cli.RESULTS_DIR` monkeypatch in tests/test_eval_readiness.py.
- **DEAD.1** - SKIP: `_ARTIFACT_COLUMNS` is imported/used by api/pivots.py. Not dead.
- **PERF.2** - DONE (code-complete, device-verify pending): first read as SKIP (wire-format ban), then reconsidered - the ban is only about bundling bytes into the listing. The actual cost was sequential blocking GETs. `fetch_snapshots_parallel` pulls + decrypts the artifact objects across an 8-worker `std::thread::scope` pool, then applies on the single conn (LWW = order-free). No wire-format change. N round trips -> ~N/8.
- **PERF.4** - SKIP: annotations/page_text/versions/tags are four independent 1:N children; one join is a cartesian product needing Python dedup - more complex and slower for artifacts with many children. The 5 indexed point-queries are the correct shape. push_all is one-shot anyway.
- **PERF.6 / SYNC.6** - DONE (as comment, per PERF.6's own fallback): the payload is secretbox-encrypted, so the LWW key cannot be peeked before decrypt, and the only cleartext metadata (object name, cursor) does not encode updated_at. Comment recorded at desktop/src/sync.rs decrypt site. Not viable to skip decrypt without weakening the wire format.
- **PERF.7 / SEARCH.4** - SKIP (premise wrong): `passages()` already batches - one `judge_gray_zone` for chunks, one for facet/entity; single caller, no per-sub-query fanout.
- **UIUX.1** - REVERTED (premise wrong, like UIUX.2): setWallGroup rebuilds #wallbody via innerHTML on every switch, so toggles are fresh and listeners never stacked. The clone-replace was pure DOM churn = the Tags<->Last-touch switch lag the user reported. Back to plain addEventListener.
- **CAPTURE-BLOB (post-hoc bugfix, not a numbered item)** - FIXED: mobile image capture/upload never reached other devices because the capture paths + outbox drainer pushed the snapshot but not the blob. New `crate::sync::push_blob` + `push_capture_blob`; wired into mobile_capture_image, mobile_save_cropped_image, mobile_outbox_push. Outbox row now clears only after the blob lands (retry-safe). cargo check + bin/verify (incl Android compile) green.
- **CAPTURE/UPLOAD WIRING (post-hoc bugfix) - the actual "can't capture" cause** - FIXED: the + menu buttons were miswired in mobile.html. Camera invoked `mobile_capture_camera` but `.catch(() => {})` threw the returned {base64,mime} away, so a photo was taken and never became an artifact. Upload invoked `mobile_capture` (the TEXT-note command) with file args - a command+arg mismatch that silently failed. Both now route through the real image pipeline: Camera -> new `doCaptureCamera()`, Upload -> `doCaptureImage()`, both -> crop -> `mobile_save_cropped_image` (which now also uploads the blob). Notes/links worked only because they used correct commands.
- **MOBILE SWITCH LAG (post-hoc bugfix) - the phone lag, NOT UIUX.1** - FIXED + DEVICE-VERIFIED: the lag switching Last-touch<->Tags on the PHONE was `renderSections` rebuilding every card on each switch and re-invoking `mobile_blob` (IPC read + secretbox decrypt + base64 marshal) for every image/pdf/link-preview card each time. Added a session `_blobCache` (Map id->parsed blob Promise); all library + detail blob fetches go through `fetchBlob(id)`, so a blob is fetched once per session, not per render. On-device (phone 56250DLCH002C2) mode switches now measure 0-2ms via CDP. (Unrelated to the desktop UIUX.1 revert.)
- **CAMERA APPOP DENIAL (post-hoc bugfix) - the real "can't take a photo" cause, DEVICE-VERIFIED** - the manifest declares `android.permission.CAMERA` (needed by the QR scanner), and once a runtime permission is DECLARED the OS appop-denies `ACTION_IMAGE_CAPTURE` until it is GRANTED. logcat showed `Appop Denial ... requires android:camera` + start result 102; `pm grant ... CAMERA` cleared it and the camera app launched. Fix: `doCaptureCamera` now runs the same `plugin:barcode-scanner|check_permissions`/`request_permissions` gate the QR scanner uses before invoking `mobile_capture_camera`. (The earlier BAL_BLOCK seen via CDP was a test artifact - launching with no foreground window; `MainActivity.captureImage` already posts to the UI thread.)
- **UPLOAD PICKER - DEVICE-VERIFIED working**: `mobile_pick_image` launches the system photo picker cleanly (`BAL_ALLOW_VISIBLE_WINDOW`); with the Upload button now routed to `doCaptureImage` it runs picker -> crop -> `mobile_save_cropped_image` (save path also device-verified: created an image artifact end to end). No camera permission needed for upload.

## Mobile capture/sync - second round (all DEVICE-VERIFIED on phone + emulator)

- **show() missing sections** - `show(id)` iterated a hardcoded list that omitted `"crop"` and `"link_capture"`, so after a pick/capture `show("crop")` hid everything and never revealed the crop sheet (blank screen = "can't use upload/camera"). Added both. Verified crop sheet now shows.
- **CameraHelper Base64.DEFAULT -> NO_WRAP** - DEFAULT inserts newlines every 76 chars; those raw \n landed in the JSON string returned from the camera, so JS JSON.parse threw and the real photo silently vanished. Verified end-to-end: took a photo via the emulator camera (shutter+accept) -> cropData len=100872 -> saved.
- **Upload returned content:// URI** - `mobile_pick_image` matched only `FilePath::Path`; the Android photo picker returns `FilePath::Url` (content://), which it rejected, and std::fs::read can't open a content URI anyway. Split the command: Android reads the picked URI via the ContentResolver in Kotlin (new `CameraHelper.pickImage` + `MainActivity.pickImage`, JNI-called like the camera), desktop keeps the file dialog.
- **image detail ReferenceError** - `fetchBlob(id)` in `renderReader(a, data)` referenced a nonexistent `id` (the original `invoke(...,{id})` had the same latent bug). Now `fetchBlob(a.id)`. Verified image detail opens.
- **image sync stuck pending** - three compounding causes, all fixed: (1) transient DNS/TLS failures reaching Railway from the phone's flapping network -> added `put_object_with_retry` (3 attempts, backoff) around both `push_snapshot` and `push_blob`; (2) status flipped to 'ok' on snapshot success even when the blob push failed, leaving blob-less images (desktop text_only) -> now marked 'ok' only after BOTH snapshot and blob land; (3) orphaned `pending` artifacts with no `capture_outbox` row could never retry -> `mobile_outbox_push` now also drives off `status='pending'` in the artifacts table (backstop). Verified: pending images drained 3 -> 1 -> 0 on-device. Added `[sync]` eprintln logging on push failures for observability.
- **CAMERA permission gate** - `doCaptureCamera` requests CAMERA (via the barcode-scanner plugin) before launching; without a grant the OS appop-denies ACTION_IMAGE_CAPTURE.
- **PULL WEDGED on duplicate content_hash (THE root "nothing syncs mobile->desktop") - FIXED + verified** - the desktop pull was frozen: cursor stuck at 374 while the relay was at 417. A phone can push two artifacts that share a `content_hash` (identical bytes - e.g. the same image captured twice, or the 1x1 test PNGs), but the desktop's `artifacts.content_hash` is `NOT NULL UNIQUE`. `apply_pulled_snapshot` on the second threw `sqlite3.IntegrityError`, the exception escaped `pull()`'s loop, `_write_cursor(new_cursor)` never ran, and every subsequent pull re-listed from the same cursor and re-hit the same object - so NOTHING after it ever synced. Fixed in `client.pull()`: wrap each snapshot's decrypt+apply in try/except - log + skip the poison object, keep applying the rest, and advance the cursor past it. The object GET's transport errors are still left to propagate (so a transient download failure is retried, not skipped as data loss). Verified: cursor drained 374 -> 418, the duplicate test images skipped as dedup, the real 1.17 MB phone photo now present + its `/blob` returns 200. NOTE: the `content_hash UNIQUE` constraint is what forbids two artifacts sharing bytes; keeping it + skipping duplicate pulls is coherent dedup. Making duplicate images sync as separate artifacts would need a table-rebuild migration to drop the constraint - deferred; the resilient pull is the correct robustness fix regardless (no single object may wedge the feed).
- **image not reaching desktop (blob bytes) - FIXED + device-verified** - the mobile image SNAPSHOTS were reaching the desktop all along (rows present with the phone's `_device_id`), but the desktop had NO way to fetch the blob bytes: `capture.blob_path` served only the local `BLOB_DIR` and `/artifacts/{id}/blob` 404'd for any blob that lived only on the relay, so mobile photos showed as a row with no image. The mobile app fetches blobs on demand (`fetch_blob`); the desktop had no equivalent. Added `client.fetch_blob_to_cache(content_hash)` (GET the DEK-named object from the relay, decrypt, cache under the content hash) and made `capture.blob_path` fetch-on-miss. The blob name matches bidirectionally (`crypto.blob_name` == the Rust `blob_name` HMAC), which is why desktop->mobile already worked. Verified live: `/artifacts/{id}/blob` now returns 200 for phone-captured images, including a real 1.17 MB camera photo, and caches locally. Wall does not filter `status`, so the (cosmetically stale) 'pending' label does not hide them.
- **UIUX.2** - SKIP (premise wrong): showArtifact does a full `view.innerHTML =` rebuild; old nodes+listeners are GC'd, no stacking.
- **UIUX.3** - DONE: applyInputRules stays synchronous (caret-critical); the expensive refreshTitleHeader (serializes whole body) is debounced 150ms via new util `debounce`.
- **UIUX.4** - DONE: new util `poll(fn,{min,max,factor})` backoff; used in search.js index-wait; chat.js poll backs off 2s->8s.
- **UIUX.5 / SYNC.5** - SKIP: coalesce (one rAF repaint) + pulled>0 guard already landed; a per-card diff renderer is a second rendering paradigm (shelf reassignment, ordering) for a gain only at card counts a phone won't hit - fails the lean bar.
- **UIUX.6** - SKIP (working as intended): `void offsetWidth` is the canonical animation-replay idiom, fired once per discrete event, not per-frame thrash.
- **SYNC.1** - SKIP (correctness hazard): a synced_snapshots high-water table must be invalidated on the very relay-switch path push_all exists for; a stale entry would skip a push the new relay needs. Not worth it for a one-shot path.
- **SYNC.3** - SKIP: the relay is intentionally identity-free (one shared secret), so it cannot key queues by device_id without adding metadata it's designed not to hold; the finally-unsubscribe + 15s heartbeat already bound queue lifetime; self-echo is absorbed by the client pulled>0 guard.
- **SYNC.4** - SKIP (moot): no mobile mutation path pushes blob bytes; push_snapshot carries metadata only. A title/tag edit cannot re-upload a blob.
- **SEARCH.1** - SKIP: adds an ETag/cursor caching path with staleness risk against a live-changing index; the task itself marks it optional/marginal.
- **SEARCH.2** - SKIP: a short passages cache can serve stale results mid-ingest (the task admits "correct while ingest does not invalidate"); correctness > a 30s cache on a local call.
- **SEARCH.3** - DONE (n/a by design): the task's own instruction is "Fix: NONE - keep strict". Left as-is.
- **SEARCH.5** - SKIP: the task hedges "skip if not concrete enough"; RRF weighting already governs the leg budgets. Doc-only.
- **FACET.1** - SKIP (premise wrong): a body edit already regenerates facets via notes.edit -> ingest_queue.submit -> _facet_artifact -> generate_for_artifact, exactly as `_artifact_is_model_stale`'s docstring says (that fn is the model-upgrade batch catch-up only). Adding a body_version gate there would conflate two responsibilities.
- **FACET.2** - SKIP: the two staleness checks are already consistent; a pure doc-label change, low value.
- **MODEL.1** - DONE: `_fuzzy_hits` docstring now states it loads all short-field rows + SequenceMatcher (the real cost) and that callers gate it behind `_needs_fuzzy` (PERF.1).
- **MODEL.2** - SKIP: extracting 4,000 lines of inline JS/CSS to external files is a large, risky churn (changes the shell's load model + the verify concatenation checks) against the "keep it lean" north star; defer to a dedicated pass if caching headers become a real need.
- **MODEL.3** - SKIP: settings.js cleanliness refactor, no behavior/perf change.
