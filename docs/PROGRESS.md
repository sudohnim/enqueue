# Enqueue Desktop Design Overhaul

# Phase K - the eye, centered artifacts, and grouping

This phase is a new feature batch, surveyed against the current code and the design system in `docs/DESIGN.md`.
It does not re-litigate Phase A-J; it builds on them.
Every task names its anchor (file:line), the change, and a "Verify" line the implementing agent checks before marking the box.

Three of the requests asked for a design skill to be run before deciding the shape.
The decision each skill would have produced is recorded here as a "Decision" block so the implementing agent does not re-derive it:

- **Clarify** (where the rename pencil lives, K.7) and **Shape** (add-to-grouping placement, K.5) and **Layout** (grouping selector on the wall, K.6) each chose between two placements.
  The chosen placement and the reason are written into the task. Implement the chosen placement unless Minh overrides it.
- **Delight and polish** (K.4) names the specific upgrade to the grouping modal.

Two product terms are used precisely in this phase, because the codebase has two different things the UI calls "grouping":

- **Exhibit** (a kept collection / room): a fixed membership list. Rows in `exhibit_members`. Shown on the wall as "Collections". This is what "add an artifact to a grouping" (K.5) and "rename a grouping" (K.7) operate on.
- **Saved grouping** (a pivot recipe): a stored `pivot.spec` re-run live. Rows in `saved_pivots`. Opened by the grid button. This is what "custom grouping" (K.6) lists.

The wall's flat last-touch list is the default "by last touch" view (K.6).

## K.1 - the eye: drop the disc, keep only the eye, very bold

- [x] **K.1 [AGENT]** Replace the 48px lavender disc emblem with a large, bold, disc-less eye.
  Anchor: `.greet-emblem` CSS at `src/enqueue/static/museum.html:445-548`, the emblem markup at `:4417-4424`, and `mountEye()` at `:4568`.
  Remove the disc: drop `background: var(--accent)`, `box-shadow: var(--shadow-card)`, and the `::before` ring (`:475-479`).
  The eye itself becomes the mark, at a bold scale: grow the `svg` from 26px to ~96-120px (a `vw`-aware clamp is fine), stroke `var(--ink)` (`#101114`) on the canvas, stroke-width ~2.4-3 so the lid reads heavy at a glance.
  The sclera outline (`.eye-outline`) stays ink-on-canvas; the iris (`.eye-iris`) fills ink; the glint (`.eye-glint`) becomes a canvas-colored circle (not lavender) so it still reads as a light reflection on a pure-ink eye.
  Keep the `.greetline` flex centering so the bold eye still sits above the greeting phrase, centered as a group.
  Re-prove contrast: ink `#101114` on canvas `#ffffff` is ~19:1, so no edge is needed (this is the point of dropping the disc - the eye no longer needs a lavender fill to read).
  Verify: the home view shows one large bold ink eye with no lavender disc behind it; the eye is the single boldest mark on the screen.

- [x] **K.2 [AGENT]** Make the eye follow the cursor and blink, and keep working after the disc is gone.
  Anchor: `mountEye()` at `src/enqueue/static/museum.html:4568` (the `step`/`saccade`/`blink` closures) and the `.eye-iris` `transform: var(--pupil, ...)` rule at `:496-507`.
  The follow and blink code already exists and is wired by `mountEye()` at the end of the home render (`:4511`). Two things break when the disc is removed in K.1, so fix them here:
  1. The `reach` constant (`:4604`, `2.2` viewBox units) was tuned for a 26px eye inside a disc. With a ~100px eye the iris travel looks tiny. Re-scale `reach` against the new svg viewBox so the pupil moves a visible fraction of the sclera (the iris `r=4.6` must never leave the outline).
  2. The blink (`@keyframes eye-blink` at `:542`) scales the `svg` from `transform-origin: 50% 88%`. Confirm the origin still lines up with the new larger eye's lower lid; adjust the origin if the squash pivots in the wrong place.
  Also confirm the bug Minh saw: the eye was not following or blinking at all. The likely cause is the `--pupil` custom property being cleared or never set because the disc removal changed the selector chain. After K.1, re-check that `.eye-iris { transform: var(--pupil, translate(0,0)); transition: transform 120ms var(--ease); }` still resolves `--pupil` set on `.greet-emblem` (custom properties inherit, so setting it on the emblem still reaches the iris). If the follow is still dead, move the `pointermove` listener from `document` to the emblem's container is NOT the fix - keep it on `document` so the eye tracks the cursor anywhere on the home view.
  Verify: moving the cursor anywhere on the home view makes the bold eye's pupil ease toward it; the eye blinks on its own every 5-20s and occasionally double-blinks; hovering the emblem centers the pupil and fires one blink.

## K.3 - center the artifact view, move action icons to the right of the artifact

- [x] **K.3 [AGENT]** Center the artifact page and pull the action icons in to the right edge of the content, not the far right of the app.
  Anchor: `showArtifact()` at `src/enqueue/static/museum.html:5002-5180`, the `.titlerow` CSS at `:1724`, `.title-action` at `:1739`, `.title-group` at `:1760`, `.bodygrid` at `:1817`, and `main`'s `max-width: 1200px` at `:573`.
  Today the title row stretches across the 930px `.bodygrid`, the title is left-aligned, and the pin / drawer / trash icons sit at the right edge of that 930px column - which reads as "far right of the app" because the reading column itself is left-weighted.
  Narrow the artifact to a true centered reading measure: set `.bodygrid { max-width: 720px; margin: 0 auto; }` (a comfortable long-form measure), and let `.titlerow` and `.bodycol` fill that 720px. The title, meta, body, and the action icons then all share one centered column, so the icons land just to the right of the title text, not at the app edge.
  Keep the `back` "Everything" button and the `kindrow` above the title inside the same 720px column so the whole page reads as one centered stack.
  The drawer (tags + summary) stays fixed to the right edge of the viewport; it covers the centered column when opened, unchanged. Only the reading column's width changes.
  Verify: opening an artifact shows the title, body, and the pin / drawer / trash icons all within a centered ~720px column; the icons sit a short distance to the right of the title, flush with the right edge of the content, not the far right of the window.

## K.4 - delight and polish the save-grouping modal

- [x] **K.4 [AGENT]** Replace the bare `askText` prompt for naming a saved grouping with a designed modal that matches the rest of the app.
  Anchor: `askText()` at `src/enqueue/static/museum.html:3872`, the `dialog.ask` CSS at `:2893-2939`, and `saveGrouping()` at `:6565`.
  Today naming a grouping is the same shell as a destructive confirm: a plain `<h2>`, a single outline-less text input, and a Cancel/Save row. It reads as primitive next to the rest of the app.
  Upgrade the modal without touching the other `ask()`/`askText()` callers (delete confirm, move picker still use the same shell - keep them simple; only the grouping-name modal gets the rich treatment). Add a dedicated `dialog.ask.name` variant:
  - A short eyebrow or subhead line under the title: "Saved groupings re-run live as your library grows" (one sentence, `Body SM`, `--text-mute`), so the modal explains what saving means instead of only asking for a name.
  - A properly styled input: `--surface-1` ground, `1px --line-strong` border, `--r-md` corners, `8px 12px` padding, the mandated 2px lavender-focus ring at 50% on focus (reuse `.searchbar:focus-within`'s `box-shadow`). Not a bare underline.
  - A primary lavender Save button (`btn primary`) and a ghost Cancel; Save takes focus only after the person types, so an empty Enter does not submit (keep the existing trim/empty-guard).
  - The `lift` entrance and `--scrim` backdrop already on `dialog.ask` carry over; add a 120ms focus ring fade-in on the field.
  Reuse the existing promise/cancel/Escape plumbing in `askText` - only the inner markup and the field styling change. Give the grouping-name call its own entry point (`askGroupName()`) so `askText` stays the plain prompt for any other caller.
  Verify: clicking "Save grouping" on an organize turn opens a modal with a styled input, an explanatory line, and a lavender Save button; it reads as part of the app, not a platform prompt.

## K.5 - add an artifact to a grouping (an exhibit), in the drawer

Decision (Shape skill): place "Add to grouping" in the right-side drawer, under the Tags row and above the Summary - NOT as another icon next to pin/drawer/trash in the title row. The title row already carries three icons and a download link; a fourth affordance there crowds the header and dilutes the pin/trash pair. The drawer is already the "work on this artifact" surface (tags + summary), so adding-to-a-grouping lives there as a labeled control, below tags and above the summary.

- [x] **K.5a [AGENT]** Add a backend endpoint to add one artifact to an existing exhibit.
  Anchor: `save_exhibit()` at `src/enqueue/api.py:980`, `exhibit_members` schema at `migrations/versions/0001_baseline.py:121`, and `retrieve/curate.py:save()` at `:84` (the only place members are written today).
  Add `POST /exhibits/{exhibit_id}/members` taking `{ "artifact_id": str }`.
  It inserts one `exhibit_members` row with the next `rank` (max rank + 1), `origin='added'`, a placeholder `placard` (the artifact title), and empty `evidence`/`strength`. It is idempotent: re-adding an artifact already in the exhibit (and not ejected) is a no-op returning 200. It 404s on an unknown exhibit and 400s on an unknown artifact.
  Add a small `curate.add_member(exhibit_id, artifact_id)` helper rather than inline SQL, so the write path stays with the rest of the exhibit code.
  Verify: `curl -X POST .../exhibits/<id>/members -d {"artifact_id":"<id>"}` adds the artifact; re-adding does not duplicate; the exhibit then lists it in `GET /exhibits/<id>`.

- [x] **K.5b [AGENT]** Add an "Add to grouping" control in the artifact drawer.
  Anchor: `showArtifact()` drawer markup at `src/enqueue/static/museum.html:5160-5170` (the `aside.drawer` with `drawer-top` + `tagRowHtml` + `summaryHtml`), and `tagRowHtml()` / `mountTagRow()`.
  Insert a new section between `tagRowHtml(id)` and `summaryHtml` in the drawer body: a `shelf` label "Add to grouping" and a control that opens a picker of the person's exhibits (from `GET /exhibits`).
  Reuse the `pickGroup()` modal shape (`:6230`) as the picker: a `dialog.ask` with a `.pickgroups` list of exhibits, plus a "Create new" row at the bottom that names a new exhibit and adds the artifact as its first member (POST /exhibits is not suitable for this - add a `POST /exhibits` body that accepts a name + seed artifact, or a `POST /exhibits` minimal-create path; pick the smaller change and document it).
  After a pick, `POST /exhibits/<id>/members` and toast "Added to <name>". The control then shows the exhibit name(s) this artifact belongs to as removable chips (a `GET /exhibits` scan for membership, or a new `GET /artifacts/<id>/exhibits`), so the drawer reflects current state.
  Verify: on an artifact, opening the drawer shows "Add to grouping" under Tags and above Summary; choosing an exhibit adds the artifact and shows it as a chip; the chip's X removes it (ejects the member).

## K.6 - grouping selector on the wall; remove the grid button from the pill

Decision (Layout skill): put the grouping selector as a quiet segmented control on the wall header, next to the search bar - not in the bottom pill, not as a dropdown menu. It is a view-mode switch for the wall, so it belongs where the wall is framed. The bottom pill's four-squares (saved-groupings) button is removed; saved groupings ("custom") become one of the selector's modes.

- [x] **K.6a [AGENT]** Remove the four-squares (saved groupings) button from the bottom pill.
  Anchor: `restorePill()` wall branch at `src/enqueue/static/museum.html:3643-3660`, specifically the `aria-label="Saved groupings"` button at `:3650`.
  Delete that one `button.round` from the wall pill markup. Keep `showSavedGroupings()` and `runSavedGrouping()` - they are reused by K.6c's "custom" mode. The pill becomes Plus + Search + Eye + Settings.
  Verify: the bottom pill has four buttons, not five; there is no four-squares icon.

- [x] **K.6b [AGENT]** Add a wall grouping selector with four modes: Type, Last touch, Tags, Custom.
  Anchor: the home header render at `src/enqueue/static/museum.html:4415-4468` (the `.homehead` / `.greetline` / `.searchbar` / `.tagbar` block) and the wall render at `:4480-4498`.
  Add a `.groupbar` control directly under the `.searchbar` (above the existing `.tagbar`) holding a segmented control: [Type] [Last touch] [Tags] [Custom]. Default selection: Last touch (the current wall).
  - **Last touch**: the wall as it is today (flat grid ordered by `updated_at DESC`). No change to the cards.
  - **Type**: group the wall's cards into sections by `kind` (note, link, pdf, image, file), each section a `.shelf` header + `.wall`. This is a pure client-side group-by over the already-fetched `first.items`/`kept.items` (the `kind` is on every wall item), so no new endpoint and no model calls. (The backend `field: kind` pivot exists at `fields.py:39` if a live re-group is ever wanted, but the wall already has the rows.)
  - **Tags**: group the wall's cards by tag. Tags are multi-valued (an artifact can carry several), so an artifact appears under each of its tags. Requires the wall items to carry their tags: add tags to `_wall_item()` at `api.py:255` (a single `SELECT artifact_id, tag FROM artifact_tags WHERE artifact_id IN (...)` batch, the same pattern as `_link_images`). Render one `.shelf` per tag, in tag-count order, with the untagged artifacts under an "Untagged" shelf at the end. No model calls.
  - **Custom**: render the saved groupings list (reuse `showSavedGroupings()` markup) inline as the wall body - each saved grouping as a card that runs `runSavedGrouping()` on click. This is the old grid-button destination, now a wall mode.
  Persist the selected mode in `localStorage` (`enqueue.wallGroup`) so a tab-back keeps the view. Re-render the wall in the chosen mode without re-fetching for Type/Tags/Last-touch; only Custom fetches `/pivots`.
  Verify: a segmented control sits under the search bar; switching modes regroups the wall; Last touch is the default; the choice survives a reload; the bottom pill no longer has the grid button.

## K.7 - rename a grouping (an exhibit), with a pencil

Decision (Clarify skill): put the rename pencil on the exhibit's own page, inline next to the exhibit title - not in the saved-groupings list and not on the wall. Rename is an act on one specific grouping while you are looking at it, so the affordance lives where the title lives. A pencil next to the title is the conventional, low-surprise placement; a settings-gear or a list-row menu would hide it.

- [x] **K.7a [AGENT]** Add a backend endpoint to rename an exhibit.
  Anchor: `list_exhibits()` / `get_exhibit()` at `src/enqueue/api.py:990-1013` and the `exhibits` table.
  Add `PATCH /exhibits/{exhibit_id}` taking `{ "name": str }` (and optionally `"through_line": str`). It trims, rejects empty, 404s on unknown. Returns the updated exhibit row.
  Verify: `curl -X PATCH .../exhibits/<id> -d '{"name":"New"}'` renames it and the list reflects the new name.

- [x] **K.7b [AGENT]** Add a rename pencil next to the exhibit title in `showExhibit()`.
  Anchor: `showExhibit()` at `src/enqueue/static/museum.html:5940-5968`, the `.h1` title render at `:5949`.
  Replace the bare `.h1` with a title row: the name as an `.h1`, then a ghost `.title-action` pencil (`ICONS` has no pencil yet - add a `pencil` path to the `ICONS` map at `:3556`) that opens an `askGroupName()`-style modal (reuse K.4's styled name modal) seeded with the current name. On save, `PATCH /exhibits/<id>` and re-render the exhibit page.
  Verify: opening an exhibit shows a pencil next to its title; clicking it opens the styled name modal; saving renames the exhibit and the title updates in place.

## K.8 - move "Save grouping" / "Answer instead" to the top of the organize results

- [x] **K.8 [AGENT]** Render the organize-turn actions above the groups, not below.
  Anchor: `organizeSlotHtml()` at `src/enqueue/static/museum.html:6543-6562` (it currently appends `.org-actions` after `pivotGroupsHtml`) and the `.org-actions` CSS at `:684`.
  Move the `.org-actions` row (Save grouping / Answer instead) to BEFORE the `pivotGroupsHtml(...)` output inside `organizeSlotHtml`. Update the comment that says the controls sit "below the label bubble".
  Visually, the two ghost buttons sit on their own row at the top of the turn's result, above the first `.pivotgroup`. Keep them as `.btn ghost` (they are reversible, not primary).
  Verify: in a chat, an organize turn shows "Save grouping" and "Answer instead" at the top of the result, above the grouped cards.

## K.9 - stay on the artifact when the app loses and regains focus

- [x] **K.9 [AGENT]** Stop the app from resetting to the wall when the museum window is hidden then re-shown; restore the open view on reload.
  Anchor: `refreshIfStale()` at `src/enqueue/static/museum.html:4354-4369` (the focus/visibility handler) and the single `home()` call that boots the page at `:7933`.
  Root cause: the museum is a single-page app with all view state in memory and no URL. When the WKWebView reloads (macOS can reclaim a hidden webview, and the capture flow hides the museum via `open_capture` in `desktop/src/main.rs`), the page re-inits and the only boot call is `home()`, so every reload lands on the wall. `refreshIfStale` is correctly gated to `place === "wall"`, so it is NOT the cause; the cause is reload losing the route.
  Fix with a lightweight hash router:
  - On every navigation (`showArtifact`, `showChat`, `showExhibit`, `showSavedGroupings`, `runSavedGrouping`, `home`, `doSearch`), set `location.hash` to a route token: `#a/<id>`, `#c/<id>`, `#e/<id>`, `#g/<id>` (saved grouping), `#s/<query>` (search), and `` (empty for the wall).
  - Replace the boot `home()` at `:7933` with a `restoreRoute()` that reads `location.hash` and calls the matching show function, falling back to `home()` only when the hash is empty. The chat's pending-turn poller restarts on `#c/<id>` restore.
  - Listen to `hashchange` only if a second window ever drives the same museum (not needed today, but cheap).
  This also fixes the stale-data gap: after a capture made in the overlay, `refreshIfStale` already refreshes the wall; for an open artifact, add a no-op-or-refresh of the current view on focus (re-fetch the current artifact only, keeping scroll) so a note captured elsewhere does not leave the open page stale.
  Verify: open an artifact or a grouping, hide the app (press the capture hotkey or Cmd-Tab away and back, or close-and-reopen the window); the app returns to the same artifact/grouping, not the wall.

## K.10 - collapsible group headers in a grouping

- [x] **K.10 [AGENT]** Make each group header in a grouping view collapsible.
  Anchor: `pivotGroupsHtml()` at `src/enqueue/static/museum.html:6118-6145` (the `.pivotgroup` section with its `.h2` header and `.wall` of cards) and the `.pivotgroup` CSS at `:671`.
  Turn the `.h2` group header into a button that toggles a `.collapsed` class on its `.pivotgroup`. When collapsed, hide the `.wall` and the item-count `.meta`, and rotate a chevron on the header (reuse `ICONS.chev` at `:3569`). Persist the collapsed state per group key in `sessionStorage` (`enqueue.collapsedGroups.<spec-hash>`) so a re-run preserves the person's choices for the run.
  Apply the same treatment to the in-chat organize turn (it shares `pivotGroupsHtml`, so it gets it for free) and to the exhibit page's member list if it grows sections later.
  Verify: clicking a group header in a grouping collapses its cards; clicking again expands; the chevron rotates; the collapsed state survives a re-run of the same grouping.

## K.11 - image context at ingest (why "find a picture of tony tony chopper" failed)

- [x] **K.11 [AGENT]** Make images searchable by describing them at ingest with a vision model, and optionally OCR.
  Anchor: `capture.upload()` at `src/enqueue/capture.py` (sets `status='text_only'`, `body=NULL` for images), `capture.extract_text()` (the text/PDF branch only - images return 0), `ingest/queue.process()` at `ingest/queue.py:75` (chunks + facets + entities all skip when there are no chunks), the facet eligibility gate at `ingest/facets.py:267-290` (skips every non-`note` kind), and the text-only `OpenAICompatibleProvider.complete()` at `providers/ollama.py`.
  Root cause: a captured image is stored as bytes with no extracted text, no body, no facets, and no entities. The title is only the filename stem, so a semantic search or an "ask" for "a picture of tony tony chopper" has nothing to match - the image is invisible to retrieval. The facet gate skips it by `kind`, and the ingest worker produces zero chunks for it.
  The fix, in order:
  1. Add a vision-capable describe step. Add a `Provider.describe_image(bytes, mime) -> str` method (or a sibling `vision.py` provider) that sends the image as a base64 data URL in an OpenAI vision message (`{"type":"image_url","image_url":{"url":"data:<mime>;base64,<b64>"}}`) and asks for a concise factual description: what the image shows, any visible text, and the subject. This needs a vision model on the configured backend (Ollama `llava`/`moondream`, or an OpenRouter vision model); document the model requirement in Settings. For a `local_only` image, route to the local vision model only, the same rule as text.
  2. In `ingest/queue.process()`, after `capture.extract_text()`, add an image branch: when `kind == 'image'` and there is no body, call the vision describe, store the description as the artifact `body` (so it chunks and indexes like a note), and run optional OCR (tesseract if available, else rely on the vision model's "visible text" output). Set `status='ok'` once a description is written.
  3. Relax the facet eligibility gate for images: an image with a generated description now has a body, so remove the blanket `kind != 'note'` skip for images that have a body (keep skipping pure captures with no text). Concretely, in `apply_eligibility_gate()` at `ingest/facets.py:267`, gate on "has a body OR has page_text", not on `kind == 'note'`.
  4. Re-index existing images: add a one-line `enq index --images` (or extend `submit_all()`) that re-queues every `kind='image'` artifact so libraries built before this change get descriptions retroactively. Best-effort, same as facets.
  Keep the capture response instant (hard rule 7): the vision call runs on the ingest worker, behind the response, exactly like PDF text extraction and facet generation.
  Verify: capture an image of a known subject; after the ingest worker runs, the image has a `body` description; searching or asking for the subject finds the image and returns it as a hit; the description shows in the artifact's summary.

# Phase L - grouping polish pass

This phase addresses bugs and feature gaps Minh reported after Phase K shipped.
Each task names its anchor (file:line), the change, and a "Verify" line the implementing agent checks before marking the box.

The exhibit-vs-saved-grouping distinction from Phase K's intro (lines 16-19) applies throughout:

- **Exhibit** (a kept collection / room): a fixed membership list. Rows in `exhibit_members`. Shown on the wall as "Collections".
- **Saved grouping** (a pivot recipe): a stored `pivot.spec` re-run live. Rows in `saved_pivots`. Opened by the "Custom" wall mode.
Phrases Minh uses that map to one or the other are disambiguated per task.

## L.1 - tag bar only shows when the wall mode is Tags

- [x] **L.1 [AGENT]** Conditionalize the home tag bar on the "tags" wall mode.
  Anchor: the tag bar markup at `src/enqueue/static/museum.html:4937-4966` (the `.tagbar` block inside the `homehead` render in `home()`), the wall mode variable `wallGroup` read at `:4593`, and `setWallGroup()` at `:4593-4615`.
  Today the tag bar is rendered unconditionally whenever `tagcloud.tags.length > 0` (the `if (allTags.length)` gate at `:4937`).
  Change `home()` so the tag bar block (`:4940-4965`) is only appended to `html` when `wallGroup === "tags"` at initial render.
  In `setWallGroup()` at `:4593-4615`, after the wall body re-renders, toggle the `.tagbar` element's visibility to match the new mode: show it for `"tags"`, hide it for all others.
  Because the tag cloud is already fetched up front (`:4888`) and the tag bar is already in the DOM from the initial render when the mode is tags, `setWallGroup` can `tagbar.classList.toggle` between show/hide without a refetch.
  When the initial mode is not `"tags"`, the tag bar is never in the DOM, so `setWallGroup` must create or remove the `.tagbar` element at mode-switch time, OR always render it hidden and toggle a `hidden` class. Pick the approach that avoids a refetch and does not lose the "all tags" expander state (`:5033-5042`).
  The tag bar's chip-click behavior (`:5024-5031`, runs `doSearch("#" + name)`) is unchanged.
  Verify: on the home view with tags present, switching to "Tags" shows the tag bar below the groupbar; switching to Type, Last touch, or Custom hides it; switching back to Tags shows it again; the "all tags" expander still works.

## L.2 - "Add to grouping" does not register after picking an exhibit

- [x] **L.2 [AGENT]** Fix the add-to-grouping drawer flow so the membership chips update after adding.
  Anchor: `addToGrouping()` at `src/enqueue/static/museum.html:5547-5566`, `renderGroupRow()` at `:5534-5545`, `mountGroupRow()` at `:5518-5530`, the module-scope `artifactExhibits` declared at `:5486` and set at `:5539` and `:5713`, and `pickExhibit()` at `:5583-5671`.
  Symptom: the picker resolves, the POST succeeds (or `quick_create` seeds the member), the toast says "Added to X", but the chip does not appear in the drawer, so it looks like nothing registered.
  Reproduce end-to-end first: open an artifact, open the drawer, click "Add to grouping", choose an existing collection, and confirm whether the chip appears. Then "Create new", name a collection, and confirm whether the chip appears.
  `renderGroupRow` captures `slot = document.getElementById("grouprow")` at `:5535`, then `await`s the fetch at `:5538`, then sets `slot.outerHTML = groupRowHtml(artifactExhibits)` at `:5543`.
  Two race conditions can make this silently fail:
  1. If the view was re-rendered during the `await` (a focus-restored refresh, a stale-data poll), the captured `slot` is detached and the `outerHTML` assignment writes to a detached node, so the DOM never updates.
  2. `addToGrouping` at `:5565` calls `renderGroupRow(id)` without `await`, so the chip update is fire-and-forget and can race any subsequent UI change.
  Fix approach: rewrite `renderGroupRow` to re-query `document.getElementById("grouprow")` AFTER the `await` (not before) and bail early if it is gone. Add `await` to the `renderGroupRow(id)` call inside `addToGrouping` so the chip update is sequenced.
  Also confirm the fetch at `:5538` actually returns the new membership: if the POST at `:5555` completed but the fetch returns stale data, the catch at `:5540-5542` swallows the error and re-renders the OLD chips. Check the `/artifacts/{id}/exhibits` endpoint at `api.py:556` returns the membership immediately after the transaction commits.
  Verify: adding an artifact to an existing collection shows the chip immediately in the drawer; creating a new collection via the picker shows the chip immediately; the chip's X removes it and re-renders; navigating away and back to the artifact shows the chip still present.

## L.3 - rename a saved grouping (a saved pivot), with a pencil

- [x] **L.3a [AGENT]** Add a backend endpoint to rename a saved pivot.
  Anchor: `src/enqueue/pivots_saved.py` (entire file, 83 lines: has `save`, `listing`, `get`, `delete`, and no `update` or `rename`), and the saved-pivot API endpoints at `src/enqueue/api.py:1309-1347` (only `POST /pivots`, `GET /pivots`, `GET /pivots/{id}`, and `DELETE /pivots/{id}`).
  Add `def rename(pivot_id: str, name: str) -> dict` in `pivots_saved.py`:
  trim the name, reject empty with `ValueError`, run `UPDATE saved_pivots SET name = ? WHERE id = ?` inside a `db.transaction()`, raise `KeyError` if no row was affected, and return the updated row as a dict (`id`, `name`, `created_at`).
  Add a `PivotRename(BaseModel)` schema with `name: str` in `api.py`.
  Add `@app.patch("/pivots/{pivot_id}")` after the `GET` at `:1334` and before the `DELETE` at `:1343`.
  It calls `pivots_saved.rename(pivot_id, req.name)`, returns `{"pivot": updated}`, 404 on `KeyError`, 400 on `ValueError`.
  Mirror the `ExhibitRename` / `PATCH /exhibits/{id}` shape at `api.py:1084-1105`.
  Verify: `curl -X PATCH .../pivots/<id> -d '{"name":"New"}'` renames the saved grouping and `GET /pivots` reflects the new name.

- [x] **L.3b [AGENT]** Add a rename pencil to each saved grouping in the custom wall and the saved-groupings list.
  Anchor: `renderCustomWall()` at `src/enqueue/static/museum.html:4616-4650` (each saved grouping is a `.card` with a title and a "forget" `.movebtn`), `showSavedGroupings()` at `:7543-7581` (same card markup), the exhibit rename pencil pattern at `:6663-6668` (the `.title-action` pencil in `showExhibit`'s `.h1row`), `renameGrouping()` at `:6715-6737` (the exhibit rename modal that posts `PATCH /exhibits/{id}`), `askGroupName()` (the styled name modal from K.4), and `svg("pencil")` (already in the `ICONS` map for the exhibit pencil).
  Note: `renameGrouping(id)` at `:6715` is the EXHIBIT rename function. Do NOT reuse it as-is for saved pivots; it posts to `/exhibits/{id}`. Write a `renameSavedGrouping(id)` function that posts to `PATCH /pivots/{id}` and re-renders the appropriate list.
  Add a pencil `.title-action` button beside each saved grouping card's title in both `renderCustomWall` and `showSavedGroupings`.
  The pencil opens the `askGroupName()` modal (from K.4) seeded with the current name; on save, `PATCH /pivots/{id}` and re-render: `renderCustomWall(slot)` for the wall, or `showSavedGroupings()` for the sub-view.
  The "forget" button stays; the pencil sits beside it.
  Reuse the existing `askGroupName` modal plumbing; do not build a new modal.
  If L.5 implements a custom-mode popup that carries the pencil, this task's pencil lives in that popup for the custom wall instead of the inline card. The `showSavedGroupings` sub-view still gets the pencil on the card.
  Verify: in the custom wall mode (or the custom popup from L.5) and the `#g` saved-groupings view, a pencil sits beside each grouping name; clicking it opens the styled name modal; saving renames the grouping and the list updates in place.

## L.4 - collapsible headers in Type and Tags wall modes

- [x] **L.4 [AGENT]** Make the shelf headers in Type and Tags wall modes collapsible, mirroring the pivot group collapse.
  Anchor: `wallSectionsHtml()` at `src/enqueue/static/museum.html:4577-4588` (renders a `.shelf center` header + `.wall` per section, no toggle), `kindSections()` at `:4539-4551` (Type mode sections), `tagSections()` at `:4556-4575` (Tags mode sections), `setWallGroup()` at `:4593-4615`, and the collapsible pivot group pattern to mirror: `pivotGroupsHtml()` at `:6850-6909`, `mountPivotGroups()` at `:6950-6964`, `.pivotgroup` CSS at `:658-698`, and the sessionStorage collapse pattern at `:6914-6946` (`specHash` / `collapsedSet` / `saveCollapsed`).
  Today only pivot groups (saved grouping runs) have collapsible headers.
  The Type and Tags wall modes use `.shelf center` + `.wall` sections with no toggle, so every section is always expanded.
  Wrap each section in a `<section class="wallgroup" data-key="...">` with a button header: the shelf label + item count + a chevron, mirroring `.pivotgroup` / `.grouptoggle` / `.gchev`.
  Rewrite `wallSectionsHtml` to emit this section-and-toggle markup instead of the bare `.shelf` + `.wall` pair.
  Add `.wallgroup` CSS mirroring `.pivotgroup` at `:658`: `.wallgroup .grouptoggle` (button reset), `.wallgroup .gchev` (chevron that rotates 180deg when expanded), `.wallgroup.collapsed .wall, .wallgroup.collapsed .meta { display: none; }`.
  Persist collapsed state in `sessionStorage` under `enqueue.collapsedWall.<mode>` (a `Set` of section keys) so a re-render keeps the person's choices within the session. Use the same `collapsedSet` / `saveCollapsed` plumbing (or a sibling pair keyed on the mode string instead of a spec hash).
  Add a `mountWallGroups(mode)` function that binds `.grouptoggle` clicks inside wall sections, parallel to `mountPivotGroups`.
  Call it from `setWallGroup` at `:4593-4615` after the body re-renders for type/tags mode.
  Keep the `.shelf center` visual style for the headers so they read as the same shelves, just now clickable.
  Verify: in Type mode, clicking "Notes" collapses the Notes shelf and hides its cards; clicking again expands; the chevron rotates; the collapsed state survives a mode switch and switch back within the session; Tags mode behaves identically per tag shelf.

## L.5 - custom wall mode opens as a modal popup with dimmed backdrop

- [x] **L.5 [AGENT]** When the user clicks "Custom" in the wall grouping, open a modal popup listing saved groupings, with the rest of the app dimmed darker.
  Anchor: `setWallGroup()` at `src/enqueue/static/museum.html:4593-4615` (the custom branch at `:5004` calls `renderCustomWall(bodySlot)`), `renderCustomWall()` at `:4616-4650` (renders saved groupings inline in the wall body), and the existing `dialog.ask` modal CSS at `:2893-2939` with its `--scrim` backdrop (the scrim dims the page behind a modal; the drop overlay at `:5258` uses the same pattern).
  Today selecting "Custom" replaces the wall body with the saved groupings list rendered inline.
  Change it so selecting "Custom" opens a `<dialog>` modal instead.
  The modal lists each saved grouping as a row: the name (clicking runs `runSavedGrouping`), a pencil icon (L.3b rename), and a "forget" button (existing `forgetSavedGrouping`).
  Use the `dialog.ask` shell with its `--scrim` backdrop so the rest of the app dims darker behind it, matching other modals.
  The wall body behind the modal should NOT be replaced with the custom list; keep the last non-custom wall view (Type, Tags, or Last touch) visible behind the dim, so when the modal closes the wall is still showing something useful.
  On closing the modal (Cancel, Escape, or backdrop click), the wall returns to the previously selected non-custom mode; do not leave "Custom" as the active groupbar selection if no grouping was opened.
  Save the previous mode before opening the modal and restore it (or just leave it) on close.
  The wall mode stays on "Custom" only when the person opens a grouping via `runSavedGrouping` and navigates into it; the `#g/<id>` route then owns the view.
  Each saved-grouping row in the modal gets the pencil from L.3b and the "forget" button from the existing `forgetSavedGrouping`.
  If the saved groupings list is empty, the modal shows the "Nothing saved yet" aside at `:4620-4623`.
  Verify: clicking "Custom" opens a dimmed modal with the saved groupings list; the rest of the app is dimmed darker; each row has a name, a pencil, and a forget button; closing the modal returns to the previous wall mode; clicking a name navigates to the saved grouping run.

## L.6 - move and remove artifacts within a saved grouping

- [x] **L.6a [AGENT]** Confirm and fix the existing "move" button on each pivot card in the saved-grouping view.
  Anchor: `pivotGroupsHtml()` at `src/enqueue/static/museum.html:6850-6909` (renders a `.movebtn` per `.pivotcard` at `:6897-6901`), `pivotMove()` at `:6998-7042` (posts `/derived/override` with `attribute = d.group_by` on the artifact, then re-runs the spec and calls `renderPivot`), `renderPivot()` at `:6966-6991` (the standalone view called by `runSavedGrouping` at `:7586-7607`), and `mountPivotGroups()` at `:6950-6964`.
  The move button and the `/derived/override` endpoint (`api.py:1296`) already exist; Minh reports he can only "move sections" (collapse/expand groups) but not move individual artifacts.
  Reproduce end-to-end first: open a saved grouping (`runSavedGrouping`), click "move" on a card, choose a target group, and confirm whether the card moves.
  If the button renders but the override does not take, investigate: the `value` posted is `d.group_by` (the attribute the pivot grouped by) and the `target` key returned by `pickGroup`. Confirm the backend `derive.override()` at `derive.py:296` writes the row and `_read()` at `derive.py:52` prefers `source='user'` on re-run.
  If the button is not visible, check the `.movebtn` CSS (it should be a small button on the `.pivotcard`); it may be hidden by a CSS rule or clipped by the card frame.
  If the re-run after override does not reflect the move, check that `pivotRun` at `api.py:1254` consults `derive._read` for user overrides on the `group_by` attribute during the enrich/extract steps.
  Verify: opening a saved grouping, clicking "move" on a card, and choosing a group moves the card to that group; the move survives re-running the same saved grouping via `runSavedGrouping`.

- [x] **L.6b [AGENT]** Add a "remove from grouping" action to each pivot card.
  Anchor: `pivotGroupsHtml()` at `src/enqueue/static/museum.html:6850-6909` (the `.movebtn` at `:6897` is the per-card action to mirror), `pivotMove()` at `:6998-7042` (the move flow via `/derived/override`), `_PlannedSpec` in `src/enqueue/pivot.py:49` (the spec model: subset, steps, group_by, bucketize), `pivot.run()` at `pivot.py:104` (the pipeline that groups artifacts), `pivots_saved.save()` / `get()` in `pivots_saved.py`, and the `POST /pivots` / `GET /pivots/{id}` endpoints at `api.py:1314-1340`.
  "Remove from grouping" means the artifact no longer appears in this saved grouping when re-run.
  A saved grouping is a computed pivot: its members are whatever the spec produces over the current library, so removing an artifact requires an exclusion mechanism, not a membership delete.
  Implement option (a): extend `_PlannedSpec` at `pivot.py:49` with an optional `excluded_ids: list[str] = []` field (default empty so existing specs still parse). Have `pivot.run` at `:104` filter those ids out of the result set before grouping (after `resolve_subset` at `:57`, before the group-by step). Returning the spec with the excluded list round-trips through `spec_json`.
  Add a `POST /pivots/{pivot_id}/exclude` endpoint in `api.py` taking `{ "artifact_id": str, "undo": bool }` that reads the stored spec, appends (or, if `undo`, removes) the artifact id from `excluded_ids`, and saves it back via a new `pivots_saved.update_spec()` helper (or reuse `save` with the same id; simplest is an `UPDATE saved_pivots SET spec_json = ? WHERE id = ?`).
  Add a `.removebtn` next to `.movebtn` on each `.pivotcard` in `pivotGroupsHtml`. The button calls the exclude endpoint, then re-runs the spec (`POST /pivot/run`) and calls `renderPivot` to refresh, mirroring `pivotMove`'s re-run pattern at `:7029-7041`.
  Toast: "Removed from this grouping."
  Provide a way to see or restore removed artifacts: either a "Removed" collapsible section at the bottom of the grouping showing excluded cards with a "restore" button (calls the same endpoint with `undo: true`), or a toast with an undo action. The "Removed" section fetches the full excluded list from the spec, runs each artifact id through the wall-item hydration (`_wall_item` at `api.py:243`), and renders the cards with a restore button.
  The artifact is never deleted from the library; it is only excluded from this saved grouping.
  Verify: in a saved grouping, clicking "remove" on a card removes it from the view; re-running the grouping keeps it removed; the artifact still appears on the wall and in the library; a path exists to restore it to the grouping.

- [x] **L.6c [AGENT]** Add an "add artifact to this grouping" entry point.
  Anchor: `pivotGroupsHtml()` at `src/enqueue/static/museum.html:6850-6909`, `_PlannedSpec` at `src/enqueue/pivot.py:49`, `pivot.resolve_subset()` at `pivot.py:57` (the subset kinds: `search` / `tags` / `ids`), and the exclude endpoint pattern from L.6b.
  A saved grouping's subset filters the library; adding an artifact that does not match the subset requires forcing it in.
  Extend `_PlannedSpec` at `pivot.py:49` with an optional `included_ids: list[str] = []` field (default empty). Have `pivot.run` at `:104` merge those ids into the result set (fetch their wall items via `_wall_item`) before the group-by step, after `resolve_subset`.
  Add a "add to this grouping" entry point on the saved-grouping view: a button at the top of the grouping (in the header area of `renderPivot` at `:6969-6981`) that opens an artifact picker (reuse the `pickGroup` / `pickExhibit` modal shape) listing the person's artifacts, or a search box that filters them.
  Choosing an artifact calls a `POST /pivots/{pivot_id}/include` endpoint (same shape as L.6b's exclude, with `artifact_id` and optional `undo`), which appends the id to `included_ids` in the stored spec, then re-runs and re-renders.
  The added artifact lands in whichever group its `group_by` attribute resolves to; if the attribute is unset, consult the extract/enrich steps or place it in the "Not determined" group.
  Verify: in a saved grouping, clicking "add artifact" opens a picker; choosing an artifact adds it to the correct group; re-running the grouping keeps it; the artifact appears with the same card + move/remove actions as the computed members.

## L.7 - the eye does not follow the cursor

- [x] **L.7 [AGENT]** Fix the eye-follow so the pupil tracks the cursor on the home view.
  Anchor: `mountEye()` at `src/enqueue/static/museum.html:5070-5196`, the `.eye-iris` CSS at `:483-490` (`transform: var(--pupil, translate(0, 0))` + `transition: transform 120ms var(--ease)`), the `:hover` override at `:503-504` (`transform: translate(0, 0)` with higher specificity), the SVG markup at `:4915-4921` (`<g class="eye-iris">` with `<circle>` + `.eye-glint`), the reduced-motion gate `motionOk` at `:5068`, and the `tearDownEye()` call in `teardown()` at `:7129`.
  The follow code is present: a `pointermove` listener on `document` at `:5131`, an rAF-throttled `step()` at `:5085` computing `--pupil` from the eye's `getBoundingClientRect()` center, and a saccade chain at `:5141`.
  Minh reports the eye is still not following the cursor.
  Root cause investigation (confirm at runtime, not by reading code alone):
  1. Confirm `mountEye()` is reached: it is called at `:5001` after `view.innerHTML = html` at `:5000`. If `motionOk` is `false` at `:5068` (reduced motion is on), the function returns early at `:5071` and no listener is bound. Check whether the OS or WKWebView reports `prefers-reduced-motion: reduce`.
  2. Confirm `el = document.getElementById("greetEye")` at `:5072` resolves to the `.greet-emblem.eye` div that is in the DOM.
  3. Confirm the `pointermove` listener fires: add a temporary `console.log` inside `step()` and check the Tauri/WKWebView console for events.
  4. Confirm `--pupil` is set: after moving the cursor, inspect `el.style.cssText` for the custom property, or check via `getComputedStyle(el).getPropertyValue("--pupil")`.
  5. Confirm the CSS applies the transform: `.eye-iris { transform: var(--pupil, translate(0,0)); }` at `:489` should pick up the inherited custom property. If WKWebView does not support CSS custom properties inside the `transform` shorthand on SVG `<g>` elements, switch from `var(--pupil)` on `.eye-iris` to setting `transform` directly on the iris group element via `el.querySelector(".eye-iris").style.transform` inside the rAF callback. This bypasses the custom-property chain entirely.
  6. Confirm the `:hover` rule at `:503-504` does not permanently override: it has higher specificity (`.greet-emblem:hover .eye-iris` = 3 classes vs `.greet-emblem .eye-iris` = 2 classes) but only applies while hovering. The `step()` function checks `el.matches(":hover")` at `:5087` and returns early when hovering, so the two do not fight.
  Likely culprits (in order): (a) `motionOk` is `false` so `mountEye` never binds the listener; (b) the CSS custom property is not applied to the SVG transform in WKWebView; (c) the `pointermove` event does not fire in the WKWebView environment the way it does in a desktop browser.
  If `motionOk` is the issue, gate only the saccade and blink cosmetic chains on reduced motion, and keep the cursor follow always on (the follow is functional, not decorative): move the `if (!motionOk) return;` guard at `:5071` to wrap only the saccade and blink setup, not the pointermove binding.
  If the custom property is the issue, set the transform directly on `.eye-iris` via `el.querySelector(".eye-iris").style.transform` in the rAF callback, and remove the reliance on `--pupil` for the follow (keep the `:hover` rule in CSS, which does not depend on `--pupil`).
  Verify: on the home view, moving the cursor anywhere makes the bold eye's pupil ease toward it; the eye blinks on its own every 5-20s; hovering the emblem centers the pupil and fires one blink; the behavior survives navigating away and back to the home view.
