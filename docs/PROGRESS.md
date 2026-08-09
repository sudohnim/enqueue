# Enqueue Desktop Design Overhaul

This file is the agent's work queue.
Do one task per turn, in order, and verify each with the command in its "Verify" line before checking the box.

# Phase K - the eye, centered artifacts, and grouping

Phase K shipped. The tasks below are recorded as the source of the patterns Phase L and M reuse (the eye markup, the wall grouping selector, collapsible pivot groups, the styled name modal, the routing hash). They are not re-opened.

- [x] K.1 Bold disc-less eye on the home view.
- [x] K.2 Eye follows cursor and blinks. (The follow broke again; see L.7 and M.4.)
- [x] K.3 Centered artifact column, action icons at the content edge.
- [x] K.4 Styled `askGroupName()` modal for naming a saved grouping.
- [x] K.5 Add-an-artifact-to-a-grouping drawer (this is the redundant collections path Phase M removes).
- [x] K.6 Wall grouping selector: Type / Last touch / Tags / Custom. Grid button removed from the pill.
- [x] K.7 Exhibit rename pencil (this is the redundant collections rename Phase M removes; the saved-pivot rename lives in L.3).
- [x] K.8 "Save grouping" / "Answer instead" moved above the grouped cards.
- [x] K.9 Hash router; restore route on reload.
- [x] K.10 Collapsible pivot group headers, state persisted per spec-hash.
- [x] K.11 Vision describe at ingest so images are searchable.

# Phase L - grouping polish pass

Surveyed against the code after Phase K shipped. Most tasks landed. Two did not.

- [x] L.1 Tag bar conditional on Tags mode. `home()` renders `.tagbar` with `hidden` unless `wallGroup === "tags"` at `src/enqueue/static/museum.html:5382-5408`; `setWallGroup()` flips `tagbar.hidden = mode !== "tags"` at `:4893-4894`. Code is in place. Minh reports it does not hide in practice; M.3 audits.
- [x] L.2 Add-to-grouping chip race fix. The drawer path Phase M deletes; the fix is moot.
- [x] L.3a `PATCH /pivots/{id}` rename endpoint at `src/enqueue/api.py:1356-1364`; `pivots_saved.rename()` exists.
- [x] L.3b Rename pencil on each saved grouping inside the L.5 custom modal (`museum.html:4962-4971`) and the `#g` list (`:8361`). `renameSavedGrouping()` at `:7212` posts the PATCH.
- [x] L.4 Collapsible Type/Tags wall headers. `wallSectionsHtml()` at `:4793`, `wallCollapsedSet()` at `:4826`, `mountWallGroups()` at `:4852`, called from `setWallGroup` at `:4900` and `home()` at `:5451`.
- [x] L.5 Custom opens a `<dialog>` modal, not inline. `openCustomPicker()` at `:4909`, called from `setWallGroup` at `:4877-4881`. The wall stays on its previous mode behind the dim. Code is in place. Minh reports it still lists inline; M.3 audits.
- [x] L.6a Move button on pivot cards posts `/derived/override` and re-runs. `pivotMove()` at `:7659`.
- [x] L.6b Remove-from-grouping: `pivotRemove()` at `:7589`, `removedSection()` at `:7526`, `POST /pivots/{id}/exclude` at `api.py:1383`, `excluded_ids` filtered at `pivot.py:138-140`.
- [x] L.6c Add-artifact-to-grouping picker: `addArtifactToGrouping()` at `:7660`, `pickArtifact()` at `:7698`, `POST /pivots/{id}/include` at `api.py:1415`, `included_ids` merged at `pivot.py:147-158`.
- [x] L.7 Eye follow fix. DONE via M.4. Root cause found by E2E: the follow and saccade wrote `translate(3.00 1.00)` - unitless, space-separated, invalid CSS inside the `transform` property, silently dropped by the browser, so the pupil never moved regardless of the reduced-motion guard. Fixed to `translate(X.XXpx, Y.YYpx)` (comma-separated lengths; 1px = 1 viewBox user unit, reach unchanged at 3.6). The `motionOk` guard now gates only the saccade and blink chains; the `pointermove` follow runs unconditionally (M.4). Verified with real CDP mouse moves under both motion settings; reduced-motion emulation keeps the follow and fires no blinks or saccades.

# Phase M - remove the redundant collections, finish the eye, audit the wall

Minh's request: the "collections" model (the `exhibits` + `exhibit_members` tables and every UI that touches them) was introduced by an earlier agent to paper over the L.2 add-to-grouping bug. It is now redundant because saved groupings (`saved_pivots`) carry the same concept and the L.5 custom modal already lists them. Remove the collections surface entirely and rewire the one place that still goes to exhibits (the wall's "Collections" shelf) to the saved groupings system.

Phase M also audits the L.1 and L.5 reports (Minh sees tags not hiding and Custom listing inline despite the code being in place) and finishes L.7 (eye follow).

Two terms used precisely:

- **Exhibit / collection** (going away): `exhibits` + `exhibit_members` tables, `showExhibit()`, `#e/<id>` route, the wall "Collections" shelf, the drawer "Add to grouping" row, every `/exhibits*` endpoint, the `renameGrouping()` exhibit-rename function, the curate save path, the chat exhibit scope, the export of exhibits, the CLI curate counters, `schemas.Exhibit`.
- **Saved grouping** (stays): `saved_pivots` table, `/pivots*` endpoints, `openCustomPicker()`, `runSavedGrouping()`, `#g` and `#g/<id>` routes, `pivotMove` / `pivotRemove` / `pivotRestore` / `addArtifactToGrouping`, the "Save grouping" organize action.

## M.1 - remove the collections wall shelf

- [x] **M.1 [AGENT]** Stop rendering the "Collections" shelf on the wall and stop fetching `/exhibits` from `home()`. DONE: dropped the `exs` slot from `home()`'s `Promise.all` (kept/first/tagcloud remain) and deleted the whole `if (exs.items.length)` shelf block. Verified in the running build: home load makes exactly three GETs (`/artifacts?pinned=true`, `/artifacts?pinned=false`, `/tags`), and the wall renders no Collections shelf. `showExhibit()` still exists (M.6 deletes it); remaining `/exhibits` fetches live in `showArtifact()` and die in M.2.
  Anchor: `home()` at `src/enqueue/static/museum.html:5312-5450`.
  The `Promise.all` at `:5322-5327` fetches `api("/exhibits")` into `exs`; the `if (exs.items.length)` block at `:5413-5432` then renders the shelf with `showExhibit()` click handlers.
  Drop the `exs` slot from the `Promise.all` (keep `kept`, `first`, `tagcloud`), and delete the entire `if (exs.items.length)` block at `:5413-5432`. The wall header now goes straight from the `</div>` that closes `.homehead` into the `.wallbody` slot.
  Do NOT remove `showExhibit()` itself yet; it dies in M.9 with the `#e/<id>` route, but the function is referenced by `restoreRoute()` and the old wall markup until M.9 lands in the same pass.
  Verify: `home()` no longer calls `/exhibits`; the network tab shows three GETs on home load (`/artifacts?pinned=true`, `/artifacts?pinned=false`, `/tags`), not four; the wall renders no "Collections" shelf.

## M.2 - remove the "Add to grouping" drawer row

- [x] **M.2 [AGENT]** Remove the drawer's grouping row and its handlers. DONE: deleted `groupRowHtml`, `mountGroupRow`, `renderGroupRow`, `addToGrouping`, `removeFromGrouping`, `pickExhibit`, the `artifactExhibits` declaration and both assignments, the `GET /artifacts/{id}/exhibits` fetch in `showArtifact()`, the `groupRowHtml(artifactExhibits)` and `mountGroupRow(id)` calls in the drawer mount, and the now-dead `.grouprow` CSS. Verified in the running build: opening a real (non-chat) artifact renders a drawer with only the Tags row (chips + add-tag input), the Summary, and the close button - no "Add to grouping" control anywhere; no console error references a removed function.
  Anchor: `groupRowHtml()` at `src/enqueue/static/museum.html:5944-5980`, `mountGroupRow()` at `:5983-5995`, `renderGroupRow()` at `:5998-6010`, `addToGrouping()` at `:6012-6032`, `removeFromGrouping()` at `:6034-6044`, `pickExhibit()` at `:6048-6135`, the module-scope `artifactExhibits` declared at `:5952` and set at `:5996`, `:6178-6181` inside `showArtifact()`, the drawer markup at `:6347-6359` (specifically the `groupRowHtml(artifactExhibits)` call at `:6357` and the `mountGroupRow(id)` call at `:6363`), and the `restorePill`/`teardown` paths that reference the drawer.
  Delete:
  1. The `groupRowHtml`, `mountGroupRow`, `renderGroupRow`, `addToGrouping`, `removeFromGrouping`, `pickExhibit` functions in their entirety.
  2. The `let artifactExhibits = [];` declaration and both assignments.
  3. The `GET /artifacts/{id}/exhibits` fetch in `showArtifact()` at `:6178-6181`.
  4. The `groupRowHtml(artifactExhibits)` line at `:6357` and the `mountGroupRow(id)` call at `:6363` in the drawer mount.
  The drawer becomes Tags + Summary only (the `.drawer-top` "Tags" label, `tagRowHtml`, `summaryHtml`, the close button).
  Verify: opening an artifact drawer shows only the Tags row and the Summary; there is no "Add to grouping" control; an artifact that was previously a member of an exhibit still opens, and no console error references a removed function.

## M.3 - audit the "tags don't hide" and "Custom lists inline" reports

- [x] **M.3 [AGENT]** Reproduce L.1 and L.5 in a running build, then either confirm or fix. CONFIRMED AS DESIGNED on a fresh build (`http://127.0.0.1:8787/`, hard reload): **L.1** - clicking Tags shows the tag bar under the grouping bar; clicking Type, Last touch, or Custom all hide it (`tagbar.hidden` toggles; the element stays in the DOM, so no null-capture issue). **L.5** - clicking Custom opens a `dialog.ask` modal titled "Saved groupings" listing the saved pivots, the `::backdrop` dims the page with the `--scrim` colour (`rgba(16,17,20,0.32)`), and the wall behind stays on its previous mode (Last touch), not an inline "Saved groupings" shelf; aria-pressed on the bar is untouched. No code bug found; the reports were a stale WKWebView - the fix is a `bin/relaunch` (kills the window, so the page reloads fresh).
  The code for both is in place; Minh still sees the old behaviour, so the most likely cause is a stale build OR a runtime bug the audit surfaces. Do both halves before editing:
  - **Reproduce L.1**: launch the museum (`bin/relaunch` or `uv run enq serve` + open `http://127.0.0.1:8787/`). Click "Tags" in the wall grouping bar: the tag bar should appear under the bar. Click "Type": the tag bar should hide. Click "Last touch": should hide. Click "Custom": should hide. Report what actually happens.
  - **Reproduce L.5**: click "Custom" in the wall grouping bar. A `<dialog>` modal should open with the saved groupings list, the rest of the app dimmed by the `--scrim` backdrop. The wall behind it should still show the previous mode (Type/Tags/Last touch), not a "Saved groupings" inline shelf. Report what actually happens.
  If both reproduce as designed, the fix is `bin/relaunch --build` (or whatever Minh uses to hard-refresh the WKWebView); record the outcome and close the task.
  If L.1 reproduces wrong (tags stay visible after switching away from Tags), the bug is one of:
    1. `setWallGroup()` at `:4871-4902` is not being called on the click. Verify `groupBarHtml()` buttons are bound. The binding is at the `gbar` block near `:5468` (search for `gbar.querySelectorAll("button")` in `home()`).
    2. The `tagbar` element captured at `:4893` is null because the initial mode was not `tags`, so `home()` did not render the tag bar markup, so `setWallGroup("tags")` has nothing to show. If this is the case, fix by ALWAYS rendering the `.tagbar` (hidden when `wallGroup !== "tags"`) so the toggle path finds the element. The current home render at `:5377-5409` already gates on `allTags.length` but emits with `(wallGroup === "tags" ? "" : " hidden")`, so the element exists when there are tags. Confirm `allTags.length` is truthy in the repro.
    3. `tagbar.hidden = mode !== "tags"` at `:4894` runs but a later `home()` re-render on focus restoration resets the attribute. Check `refreshIfStale()` and any `home({ keepScroll: true })` call paths.
  If L.5 reproduces wrong (Custom lists inline in the wall body instead of opening a modal), the bug is:
    4. `setWallGroup()` is not the click handler. Verify the groupbar binding.
    5. `openCustomPicker()` at `:4909` is not being awaited, or the wall body is being replaced before the modal opens. Confirm `setWallGroup` at `:4871-4902` does `if (mode === "custom") { const pick = await openCustomPicker(); ... return; }` and does NOT fall through to `slot.innerHTML = wallBodyHtml()` for the custom case.
  Edit only if a real bug is found; otherwise record the repro outcome and close.
  Verify: on a fresh build, switching from Tags to Type hides the tag bar; clicking Custom opens the dimmed modal over an unchanged wall. State both outcomes explicitly.

## M.4 - finish L.7: narrow the `motionOk` guard so the eye always follows

- [x] **M.4 [AGENT]** Gate only the saccade and blink cosmetic chains on `prefers-reduced-motion`; the `pointermove` follow runs unconditionally. DONE - see L.7 note. Changes: removed the `if (!motionOk) return;` early return; gated the saccade and blink timer chains on `motionOk`. E2E also found and fixed the real reason the eye never followed: both transform writes emitted unitless space-separated `translate(X.XX Y.YY)`, invalid CSS for the `transform` property (the `translate()` function needs comma-separated lengths), so the browser silently dropped them. Rewrote both writes as `translate(X.XXpx, Y.YYpx)` (1px = 1 viewBox unit, reach stays 3.6).
  Anchor: `mountEye()` at `src/enqueue/static/museum.html:5516-5660` and `motionOk` at `:5514`.
  Today `if (!motionOk) return;` at `:5517` blocks the whole function, so under `prefers-reduced-motion: reduce` no `pointermove` listener is bound and the eye sits dead. The follow is functional, not decorative, so it should always be on.
  Change:
  1. Remove the `if (!motionOk) return;` early return at `:5517` entirely.
  2. Keep the `pointermove` binding (`document.addEventListener("pointermove", step, ...)` at `:5597`), the `mouseleave` relax at `:5598`, and the `step` / `relax` closures unconditional.
  3. Gate the saccade chain: wrap the `saccadeTimer = setTimeout(saccade, ...)` line at `:5646` in `if (motionOk)`. Inside `saccade()` at `:5607`, the existing `el.matches(":hover") || performance.now() - lastMove < 600` early return is fine; nothing else changes.
  4. Gate the blink chain: wrap the `eyeTimer = setTimeout(blink, ...)` line at `:5659` in `if (motionOk)`. The `blink()` function at `:5647` stays as-is.
  The `iris.style.transform` direct writes (`:5580`, `:5595`, `:5618`, `:5631`) are already correct and stay; they bypass `var(--pupil)` so WKWebView's SVG custom-property gap is not a problem.
  Also verify the `:hover` CSS rule at `:503-504` does not fight the follow when the cursor is over the emblem: `step()` at `:5534-5540` already clears `iris.style.transform` while hovering, so the stylesheet `translate(0,0)` takes over. Keep this behaviour.
  Verify: on a machine with reduced motion ON (System Settings > Accessibility > Display > Reduce motion, OR `defaults read com.apple.universalaccess reduceMotion` returns 1), loading the home view, the eye's pupil still eases toward the cursor as it moves anywhere on the page; no saccades or blinks fire. On a machine with reduced motion OFF, the follow, saccades, and blinks all run as before.

## M.5 - remove the saved-groupings sub-view (`#g`) is already the replacement; confirm

- [x] **M.5 [AGENT]** Confirm `showSavedGroupings()` still works after M.1-M.2 removed the wall "Collections" shelf. SMOKE CHECK PASSED in the running build: `#g` renders the "Saved groupings" list (3 rows, rename pencil and forget buttons intact on each); clicking a row runs the grouping and lands on `#g/<id>` (Regions of the World, 3 groups); reload on `#g/<id>` restores the grouping run via `restoreRoute()`; the Custom wall selector still opens the modal (M.3).
  Anchor: `showSavedGroupings()` (search for the function definition; it powers the `#g` route via `restoreRoute()` at `:5280`), `runSavedGrouping()` at `:8384`-ish (powers `#g/<id>` at `:5281`), and the `openCustomPicker()` at `:4909` which is what M.3's audit concerns.
  The "Custom" wall selector opens `openCustomPicker()` (the L.5 modal). The `#g` sub-view is a separate route that lists saved groupings full-screen, reached only via `restoreRoute()` on reload. Both must still work after the collections shelf is gone.
  There is nothing to delete here; the task is a smoke check after M.1 and M.2 land.
  Verify: in a running build, navigate to `#g` directly; the saved-groupings list renders ( pencils and forget buttons intact ); clicking a row runs the grouping at `#g/<id>`; the "Custom" wall selector still opens the modal; reload on `#g/<id>` restores the grouping run.

## M.6 - remove the `showExhibit()` page and `#e/<id>` route

- [x] **M.6 [AGENT]** Delete the exhibit page and its route token. DONE: removed `showExhibit()`, the exhibit `renameGrouping(id)` (saved-pivot `renameSavedGrouping` untouched), the `kind === "e" && id` token and its doc-comment line in `restoreRoute()`, plus the two remaining call sites - the `refreshIfStale()` exhibit branch and the chat scoped-chip `showExhibit` branch (the chip now renders the artifact scope only). Also simplified the dead `asked.kind === "exhibit"` chat-scope check to artifact-or-everything. Verified: zero `showExhibit(` / `setRoute("e/` sites in the JS; a real page load on `#e/<old-exhibit-id>` lands on the wall, not an error state (restoreRoute falls back to `home()`, which clears the hash).
  Anchor: `showExhibit()` (search for the function definition around line 7118-7178), `renameGrouping()` at `:7183-7205` (the EXHIBIT rename function; the saved-pivot rename is `renameSavedGrouping` at `:7212` and stays), the route token `kind === "e" && id` at `:5279` in `restoreRoute()`, the route doc comment at `:5256-5258`, and any `showExhibit` call sites (M.1 has already removed the wall shelf call; search for the rest).
  Delete:
  1. The `showExhibit()` function.
  2. The exhibit `renameGrouping(id)` function (NOT `renameSavedGrouping`).
  3. The `if (kind === "e" && id) return showExhibit(id);` line at `:5279` inside `restoreRoute()`.
  4. The `#e/<id>` mention in the route doc comment at `:5257`.
  5. Any `setRoute("e/" + id)` call site (search for `"e/"`); M.1 already removed the wall shelf's call, but a stray one could exist.
  The `#e/<id>` route becomes unrecognised; `restoreRoute()` at `:5289` falls back to `home()`, which is the right behaviour for an old bookmark to a deleted concept.
  Verify: opening `#e/<some-exhibit-id>` in a running build lands on the wall, not an error state; no `showExhibit` call sites remain in the museum JS.

## M.7 - remove the exhibit backend endpoints

- [x] **M.7 [AGENT]** Delete every `/exhibits*` route and the `curate` exhibit writers. DONE: removed `artifact_exhibits`, `ExhibitSave`, `POST/GET /exhibits`, `GET/PATCH /exhibits/{id}`, `POST /exhibits/{id}/members`, `DELETE .../members/{artifact_id}`, `ExhibitQuickCreate`, `POST /exhibits/quick`, the `save` param from `CurateRequest`, and the `/curate` save call in `api.py`; deleted `save()`, `_save()`, `add_member()`, `rename_exhibit()`, `eject_member()`, `quick_create()` from `retrieve/curate.py` and dropped `saved_id` from its result; renamed `schemas.Exhibit` -> `Room` (groupings/tensions validators kept) and the `/curate` response key `exhibit` -> `room`; dropped the `exhibit` chat scope from `chats.py` (validation, scope_label, passages, empty_scope_reason); removed the exhibit counters from `cli.py` export/curate echoes and the `--save` flag; removed the exhibit export block from `export.py` (no exhibits file, no manifest exhibits key, verify checks artifacts only); updated the frontend `r.exhibit` -> `r.room`; dropped `exhibit_members` from `trash.py` purge and `exhibits` from `settings.py` counts. Verified on a fresh server: `curl /exhibits` -> 404; `curl -X POST /curate` returns the synthesized room with no `saved_id`; `uv run pytest -q` green (370 passed) with M.8/M.9 landed; zero exhibit references remain in `api.py`, `curate.py`, `schemas.py`, `chats.py`.
  Anchor: `src/enqueue/api.py` - `GET /artifacts/{id}/exhibits` at `:561-579`, `POST /exhibits` (`save_exhibit`) at `:1047-1054`, `GET /exhibits` (`list_exhibits`) at `:1057-1064`, `GET /exhibits/{id}` (`get_exhibit`) at `:1067-1082`, `PATCH /exhibits/{id}` (`rename_exhibit`) at `:1084-1105`, `POST /exhibits/{id}/members` (`add_exhibit_member`) at `:1108-1122`, `DELETE /exhibits/{id}/members/{artifact_id}` (`eject_exhibit_member`) at `:1125-1134`, `POST /exhibits/quick` (`quick_create_exhibit`) at `:1137-1157`. The Pydantic schemas `ExhibitSave`, `ExhibitRename`, `ExhibitMember`, `ExhibitQuickCreate` live near these endpoints (search for each `class ...BaseModel`).
  In `src/enqueue/retrieve/curate.py`, delete: `save()` at `:84`, `_save()` at `:98`, `add_member()` at `:130`, `rename_exhibit()` at `:173`, `eject_member()` at `:201`, `quick_create()` at `:218`. The `run()` function at `:22` stays (it returns the synthesized room); drop the `save and exhibit` block at `:79-80` and the `saved_id` key from the result dict at `:75-80` so `/curate` returns the room without persisting anything. The `Exhibit` schema import from `schemas.py` dies with the save path.
  In `src/enqueue/schemas.py`, delete the `Exhibit` class and any related models only `curate` used (`SuggestedName`, etc., if they have no other consumer; grep before deleting).
  In `src/enqueue/chats.py`, the `exhibit` scope at `:63, :122-126, :243-252, :398-399` references the `exhibits` table to fetch member artifact ids. Decision: drop the `exhibit` scope entirely. Change the `scope_kind in ("everything", "artifact", "exhibit")` check at `:63` to `("everything", "artifact")`; remove the exhibit branches in the passages and answer paths; existing exhibit-scoped chats in the database become `everything`-scoped on read (or, if migration M.8 adds a column rewrite, they are rewritten). Document the migration behaviour in M.8.
  In `src/enqueue/cli.py` at `:178, :187, :219-239`, the curate command's counters and export fields reference exhibits. Drop the exhibit-specific output; curate's text result stays, the saved-id line goes.
  In `src/enqueue/export.py` at `:105-319`, the exhibit export block is removed; the export no longer writes an exhibits file. Saved groupings become the only persisted grouping concept; if export should serialise them, add a `saved_pivots.json` block (out of scope for this task; record as a follow-up in M.11).
  Keep this task focused on Python deletes; the migration is M.8.
  Verify: `uv run pytest -q` passes after the deletes (with M.8 landed in the same commit); `curl http://127.0.0.1:8787/exhibits` returns 404; `curl http://127.0.0.1:8787/curate -X POST -d '{"lens":"..."}'` still returns the synthesized room, with no `saved_id` key; no `import curate.add_member` style imports remain in `api.py`.

## M.8 - drop the `exhibits` and `exhibit_members` tables in a new migration

- [x] **M.8 [AGENT]** Add an Alembic revision that drops the two tables. DONE: created `src/enqueue/migrations/versions/0019_drop_exhibits.py` (down_revision 0018). `upgrade()` rebuilds `chats` without `'exhibit'` in the scope_kind CHECK (SQLite cannot DROP CONSTRAINT, so copy-table -> drop -> rename, preserving the `pinned` column and recreating `idx_chats_updated`), rewrites `scope_kind='exhibit'` rows to `'everything'` with `scope_id=NULL` (the scope_id referenced a row about to be dropped), then drops `exhibit_members` before `exhibits`. `downgrade()` is empty with the "Downgrade not supported" comment. Verified on the real DB: `db.migrate()` advances 0018 -> 0019 without error; `sqlite_master` no longer lists `exhibits`/`exhibit_members`; no `scope_kind='exhibit'` rows remain; all 7 chats survive with messages intact. Fresh-DB path verified via a temp-dir test that builds a seeded 0018 DB (exhibit + members + exhibit-scoped chat + artifact-scoped chat), migrates to head, and asserts tables gone, chat rows rewritten, message rows intact, index recreated, and the new CHECK rejects `'exhibit'`.
  Anchor: the baseline migration at `src/enqueue/migrations/versions/0001_baseline.py` creates `exhibits` and `exhibit_members` (search the file). The migration runner is `db.migrate()` at `src/enqueue/db.py`. The migrations directory is `src/enqueue/migrations/versions/`; revisions are numbered (`0001_baseline.py`, ..., latest).
  Create `src/enqueue/migrations/versions/00XX_drop_exhibits.py` (use the next free number).
  `revision = "00XX_drop_exhibits"` (whatever the next id is), `down_revision = "<current head>"`.
  `upgrade()`: `op.drop_table("exhibit_members")` then `op.drop_table("exhibits")` (order matters; the members FK on exhibits goes first). SQLite's newer versions support `DROP TABLE` with foreign keys off; if the engine raises on a dangling FK, run `op.execute("PRAGMA foreign_keys=OFF")` before the drops and `PRAGMA foreign_keys=ON` after.
  `downgrade()`: leave empty (the schema cannot be restored without data). Add a comment: "Downgrade not supported; recreating exhibits would not restore membership".
  For the chat-scope column rewrite: the `chats.scope_kind` column was a CHECK-constrained string. If the CHECK includes `'exhibit'`, the new migration must drop and recreate the constraint without `'exhibit'`. Inspect `migrations/versions/0003_chats.py` for the constraint definition. SQLite cannot `ALTER TABLE ... DROP CONSTRAINT`; the migration must rebuild the table (the standard Alembic batch mode: `with op.batch_alter_table("chats") as b: ...`). Use `b.drop_constraint` if Alembic's batch mode detects the CHECK; otherwise copy the table, rewrite rows whose `scope_kind = 'exhibit'` to `'everything'`, drop the old, rename the new.
  Existing exhibit-scoped chat rows become `everything`-scoped during this migration: in `upgrade()`, before the constraint rewrite, `op.execute("UPDATE chats SET scope_kind = 'everything' WHERE scope_kind = 'exhibit'")`.
  Verify: on a database with existing exhibits, `enq migrate` runs the new revision without error; `SELECT name FROM sqlite_master WHERE name IN ('exhibits', 'exhibit_members')` returns empty; `SELECT scope_kind FROM chats WHERE scope_kind = 'exhibit'` returns empty; a fresh database (delete `~/.enqueue-poc/enqueue.db`, restart) reaches head and starts cleanly.

## M.9 - delete the exhibit tests

- [x] **M.9 [AGENT]** Remove tests that exercise the exhibit surface; rewrite curate / chat tests that touch it. DONE: deleted `tests/test_exhibit_members.py` entirely; rewrote `tests/test_export.py` (dropped the `_exhibit` fixture, the exhibit from `_build_library`, the `first["exhibits"]` / `exhibits/` dir assertions, and the exhibit block of `test_export_survives_database_deletion`); removed the whole `TestSaveLensView` class from `tests/test_lens_api.py` plus the `test_ephemeral_writes_no_exhibits` test, and added `TestCurateHttp.test_curate_returns_room_and_writes_nothing` which asserts `POST /curate` returns the synthesized room (stubbed provider patched at all three `get_provider` import sites: rerank, expand, curate), `keep=2` truncates kept, and the response carries no `saved_id`; renamed `TestExhibitValidators` -> `TestRoomValidators` in `tests/test_ingest.py`, rewiring the two Exhibit tests to the surviving `Room` schema (same validators: through-line restates lens, thin must say why) and tightening the blind `pytest.raises(Exception)` to specific `ValueError` matches. Verified: `uv run pytest -q` green (370 passed); `grep` shows zero references to `add_member`/`eject_member`/`quick_create`/`rename_exhibit`/`save_exhibit`/`/exhibits`/`Exhibit` in `tests/`; `bin/verify` passes (JS parse both pages, pytest, contrast).
  Anchor: `tests/test_exhibit_members.py` (entire file - tests `add_member`, `eject_member`, `rename_exhibit`, `quick_create`), `tests/test_export.py` (rewrite: drop the exhibit fields from the fixtures and assertions; export tests should cover artifacts and chats, not exhibits), `tests/test_lens_api.py` (the `test_save_this_view_writes_an_exhibit_with_the_lens_as_theme` and `test_ephemeral_writes_no_exhibits` tests at `:99-238` are removed; the curate endpoint no longer saves, so the lens test becomes "the curate response carries the room and writes nothing").
  Run `uv run pytest -q` after the deletes. Any test that imports `from enqueue.retrieve.curate import save` or `add_member` or any removed symbol must be deleted or rewritten; do not skip-with-warning, just remove.
  Add one new test in `tests/test_lens_api.py` (or wherever the curate endpoint test lives) that asserts `POST /curate` returns the synthesized room and that `SELECT COUNT(*) FROM exhibits` (if the table existed) is untreated; since the table is gone, assert the response body has no `saved_id` key and `exhibit` is the ephemeral payload only.
  Verify: `uv run pytest -q` passes; no test references `add_member`, `eject_member`, `quick_create`, `rename_exhibit`, `save_exhibit`, the `/exhibits` endpoint, or the `Exhibit` schema; `bin/verify` (JS parse + pytest + contrast) passes.

## M.10 - update AGENTS.md

- [x] **M.10 [AGENT]** Strip the exhibit references from the engineering reference. DONE: removed "exhibits" from the architecture diagram SQLite line; dropped "Saves exhibits." from the curate module map; updated the 0001_baseline row to "...chunks, facets." and added a 0019_drop_exhibits row documenting the drop; rewrote the Lens section (curate is ephemeral, Save This View no longer persists, saved pivots are the only persistent groupings); narrowed chat scope to artifact/everything in Passages, the chats table row, and the scope-dial table ("One exhibit" row deleted); deleted the `exhibits`/`exhibit_members` table rows and invariant 5 (`exhibits.theme` is immutable); dropped "exhibits, exhibit_members" from the sacred-tables sentence; changed the Synthesis row to "The room: through-line, tensions, groupings"; dropped `[--save]` from `enq curate`; removed the three `/exhibits*` lines from the API surface and added the `/pivots*`, `/pivot/plan`, `/pivot/run` lines; "That is the exhibit." -> "That is the room."; tests map -> "facet/judgment validators"; added resolved decision 9 (one grouping concept: the saved pivot). Verify: `grep -n exhibit AGENTS.md` returns only the resolved-decisions entry and the historical 0019 migration row.
  Anchor: `/Users/minhmai/enqueue/AGENTS.md` lines 103, 194, 221, 296-298, 302, 326-327, 330, 347, 367, 458, 486, 521-522, 551, 596, 617, 708 (grep `exhibit` to find them all; the line numbers shift as you edit).
  Changes:
  - The architecture diagram at `:103`: drop "exhibits" from the SQLite list.
  - `retrieve/curate.py` module map at `:194`: "Orchestrates expand -> candidates -> rerank -> synthesise." drop "Saves exhibits."
  - `0001_baseline.py` migration map at `:221`: keep the row but change "Core tables: artifacts, versions, annotations, chunks, facets, exhibits." to remove "exhibits" and note the new revision drops them. The migration file itself stays (it is history); the docstring says what it created at the time, but the AGENTS.md map should reflect the current head.
  - Lens section at `:296-298`: rewrite "An exhibit is the saved form: Save This View posts the lens and its judged related list through the existing `/exhibits` path" to reflect that the curate flow is ephemeral and Save This View no longer persists. If Save This View is removed from the UI as part of M.11, the AGENTS.md description follows.
  - Chat scope dial at `:302` and `:617`: drop the "One exhibit" row; scopes are now "One artifact" and "Everything" only.
  - Database tables at `:326-327`: remove `exhibits` and `exhibit_members` rows.
  - `chats` table row at `:330`: drop "exhibit" from "scoped to everything/artifact/exhibit. pinned."
  - Invariant 5 at `:347`: delete "`exhibits.theme` is immutable. Reshaping means a new exhibit." (the invariant is gone with the table).
  - Sacred tables at `:367`: drop "exhibits, exhibit_members" from the additive-only list.
  - "Synthesis" row in the per-stage table at `:458`: drop "Where exhibit quality is decided" (curate still synthesises, but no exhibit is the output).
  - CLI map at `:486`: `enq chat` docstring "Ask the collection something" - the lowercase "collection" is fine; leave.
  - API surface at `:521-522, :551`: remove every `/exhibits*` line. Add the `/pivots*` lines if they are not already listed (the L.3 rename, L.6b exclude, L.6c include).
  - Tests map at `:708`: drop "facet/judgment/exhibit validators" - rewrite to "facet/judgment validators".
  Also add a "Resolved decisions" entry: "There is one grouping concept: the saved pivot. The `exhibits` / `exhibit_members` tables and the `/exhibits*` endpoints that an earlier agent introduced to paper over the L.2 add-to-grouping bug are removed. `saved_pivots` and `/pivots*` carry the same concept with a re-runnable spec."
  Verify: `rtk rg -n "exhibit" /Users/minhmai/enqueue/AGENTS.md` returns only the residual mentions in the resolved-decisions entry and the historical `0001_baseline.py` migration row that calls out the drop.

## M.11 - decide Save This View's fate (follow-up, not blocking)

- [x] **M.11 [AGENT, OPTIONAL]** Either remove "Save This View" from the lens/curate UI, or rewire it to save a `saved_pivots` row. DONE - **Option A chosen** (the recommended, simpler option): removed the "Keep this room" button render (the `if (r.kept.length)` block at the end of the room view) and the `keepRoom()` handler that POSTed to the deleted `/exhibits` endpoint. The curate / lens flow is now purely ephemeral - you read the room, you do not keep it; to preserve the shape later, the person asks the assistant to organise and saves that pivot via the existing "Save grouping" action (consistent with the rest of the product: only saved pivots are persistent groupings). Verified in the running build (fresh server, real provider): `doCurate('ontologies and the semantic web, AI agents')` renders a populated room - "AI Agents and Structured Knowledge", "2 kept · 6 rejected · 10 considered", through-line and thin-reason present - with **no "Keep this room" button and no `btnKeep` element**; a thin room (0 kept) also renders clean. `grep` confirms zero `keepRoom`/`btnKeep`/`/exhibits` references remain in museum.html; `node --check` on the extracted JS passes. Follow-up recorded (from M.7): `export.py` does not serialise saved groupings; if export should write them, add a `saved_pivots.json` block later.
  Anchor: the lens/curate "Keep this room" / "Save This View" UI in `src/enqueue/static/museum.html` (search `keepRoom`, `saveExhibit`); the `POST /exhibits` endpoint at `api.py:1047` that M.7 removed; and the `POST /pivots` endpoint at `api.py:1356` saved-pivot creator that takes `{ name, spec }`.
  Post-M.7, `POST /exhibits` is gone, so "Save This View" will 404 in a running build. Pick one:
  - **Option A (simpler, recommended):** Remove the "Save This View" button and its handler. The curate / lens flow becomes purely ephemeral - you read the room, you do not keep it. To preserve the room later, the person asks the assistant to "organize" and saves that pivot via the existing "Save grouping" action. This is consistent with the rest of the product: only saved pivots are persistent groupings.
  - **Option B (more work):** Rewire "Save This View" to call `POST /pivots` with a minimal spec `{ subset: { kind: "ids", ids: kept_ids }, group_by: null, steps: [], included_ids: kept_ids }` so the saved pivot re-runs by re-hydrating the same ids. This means a saved pivot can now hold a pure id-list with no `group_by`; `pivot.run()` must handle a spec with `included_ids` and no `group_by` (render one group). Verify `_PlannedSpec.group_by` allows `None` and `pivotGroupsHtml` handles a single-group run.
  Choose A unless Minh says otherwise; record the choice in the task close-out.
  Verify: under Option A, the lens view shows no "Save This View" button; under Option B, clicking it creates a saved pivot that appears in the Custom modal and re-runs to the same artifacts.
