# Enqueue Progress - Phase S (view persistence, copy cleanup, header freeze + fade, ribbon colorize, gradient alignment)

This file is the agent's work queue. Do one task per turn, in order, and verify each with its "Verify" line before checking the box. Do not implement anything that is not listed below.

All edits live in `~/enqueue/src/enqueue/static/museum.html` unless a task says otherwise. Line numbers are approximate; re-anchor on surrounding code before editing because earlier tasks in this phase shift lines.

Prior phases shipped: bold Kraken-purple theme, 5-up wall, eyeball PNG with iris-only cursor-follow (no blink), per-artifact add-to-view drawer, transparent eyeball background, ribbon delight (lavender hover on round buttons, keep disc glow), settings human touch, pivot card icon buttons, section-delete from saved views, vertical bar removal, settings containerization.

Ground truth sampled before this phase (do not re-derive):

- **View persistence bug**: `refreshIfStale()` at `museum.html:~5548-5564` runs on `window.focus` and `visibilitychange`. It handles three cases: `place === "wall"` (refreshes the wall), `scope.kind === "artifact"` (re-fetches the artifact), `scope.kind === "chat"` (re-fetches the chat). It does NOT handle the saved-view case. When a user opens a saved view via `runSavedGrouping(id)` at `:~8587`, that function calls `teardown()` + `setRoute("g/" + id)` + `renderPivot(...)` but NEVER calls `restorePill("inside")` and NEVER updates `scope`. So `place` stays `"wall"` (whatever it was before the view opened). When the app loses focus (user switches to another app) and regains it, `refreshIfStale` fires, sees `place === "wall"`, checks the artifact stamp, and if anything changed (or even if the stamp logic fires), calls `home({ keepScroll: true })` - which navigates back to the wall, abandoning the saved view. The route IS saved in the hash (`#g/<id>`) and `restoreRoute()` at `:~5590` handles it on a full page reload, but `refreshIfStale` short-circuits before the reload path. The fix: (1) call `restorePill("inside")` in `runSavedGrouping` so `place` becomes `"inside"`, and (2) add a pivot case to `refreshIfStale` that re-runs the current saved view if `pivotState` is active.
- **"These groups come from the assistant's knowledge"**: the text is at `museum.html:~7421-7422` inside `pivotGroupsHtml()`, gated by `const inferred = d.groups.some((g) => g.grounded === false)` at `:~7416`. The `.groundnote` CSS is at `:~862`. Both the JS block that emits the div and the CSS rule are to be removed.
- **"Add artifact to this view"**: the button is at `museum.html:~7576` inside `renderPivot()`: `'<div class="pivotactions"><button class="btn ghost" onclick="addArtifactToGrouping()">Add artifact to this view</button></div>'`, gated by `pivot_id` being truthy. The `addArtifactToGrouping()` function at `:~7803` becomes dead after removal. The `.pivotactions` CSS at `:~1038` also becomes dead.
- **Gradient + traffic lights**: the `.topbar` at `museum.html:~307-315` is a fixed 32px strip at the top of the window with `background: var(--bg)` (white). The macOS traffic light buttons (close/minimize/fullscreen) live in this 32px zone. The `main` element at `:~561-565` has `padding: calc(32px + var(--sp-5)) var(--sp-5) 160px` - that is `32px + 24px = 56px` of top padding before any content. The `.homehead` gradient at `:~380-384` starts at the top of `.homehead`, which sits 56px below the window top. Between the 32px topbar and the start of `.homehead` there is 24px of white space (`--sp-5`). The user wants the gradient to start right below the 32px traffic-light strip, eliminating that 24px gap, so the gradient meets the traffic lights with a natural demarcation.
- **Greeting + bird position**: the `.homehead` has `padding-top: var(--sp-6)` (32px) at `:~385`. The greeting + bird sit inside `.homehead` at the top. Moving the gradient up (S.4) also moves the greeting up because the gradient is the `.homehead` background. The user also wants the greeting + bird moved up "a bit" beyond what the gradient move alone does - this is a `padding-top` reduction on `.homehead`.
- **Sticky header with fade**: the user wants everything above a line a few pixels below the tagbar to freeze when scrolling. The frozen zone includes: the greeting, the bird, the searchbar, the groupbar (Last touch / Type / Tags / Custom), and the tagbar. The wall cards below should scroll under the frozen header with a fade effect (cards fade in/out as they enter/leave the header boundary) rather than a hard line. This requires `position: sticky` on `.homehead` plus a CSS `mask-image` gradient on the wall body to create the fade.
- **Ribbon button (pill) background + shadow**: the `.pill` at `museum.html:~1798-1815` has `background: var(--surface)` (white) and `box-shadow: var(--shadow-lifted)` (`0 8px 28px rgba(16,17,20,0.08)`). The user wants the pill to have a non-white background to denote it floats above the artifacts, plus a stronger shadow. The fix: change `background` to a slightly tinted surface (or `--surface-1`/`--surface-2`) and increase the shadow.
- **Tags + artifacts outside gradient bounds**: the `main` element has `padding: ... var(--sp-5) 160px` - that is 24px horizontal padding. The `.homehead` gradient fills the `.homehead` element, which is inside `main` and inherits the 24px horizontal padding. But the `.groupbar` at `:~2573` is `display: inline-flex` and sits centered (because `.homehead` has `text-align: center` at `:~407`). The wall grid (`.wall`) at `:~1384` spans the full `main` width (1200px - 48px padding = 1152px). The `.homehead` gradient is as wide as `.homehead`, which is as wide as `main`'s content area. The user perceives the tags and artifacts as "slightly outside" the gradient - likely because the gradient has `border-radius: var(--r-lg)` (12px) at `:~387` which rounds the corners, while the wall cards have square corners that extend to the full width. The fix: either remove the `border-radius` on `.homehead` or add horizontal `padding-inline` to the wall body to match the gradient's visual bounds.

---

## S.1 - persist the saved view when the app regains focus

- [x] **S.1a [AGENT]** Call `restorePill("inside")` in `runSavedGrouping` so `place` reflects the view.

  Anchor: `runSavedGrouping(id, name)` at `museum.html:~8587-8608`.

  Today the function calls `teardown()` then `setRoute("g/" + id)` but never sets `place`. Add `restorePill("inside")` right after `teardown()`:

  ```js
  async function runSavedGrouping(id, name) {
    teardown();
    restorePill("inside");
    setRoute("g/" + id);
    view.innerHTML = '<div class="state thinking">Building the view...</div>';
    // ... rest unchanged
  ```

  This sets `place = "inside"` so `refreshIfStale`'s `place === "wall"` branch does not fire and navigate away.

  Verify: open a saved view, switch to another app, switch back. The saved view stays on screen - `refreshIfStale` does not call `home()`.

- [x] **S.1b [AGENT]** Add a pivot re-run case to `refreshIfStale`.

  Anchor: `refreshIfStale()` at `museum.html:~5548-5564`.

  Today:

  ```js
  async function refreshIfStale() {
    if (document.hidden || !view) return;
    if (place === "wall") {
      // ... wall refresh
      return;
    }
    if (scope.kind === "artifact" && scope.id) {
      showArtifact(scope.id, false, window.scrollY);
    } else if (scope.kind === "chat" && scope.id) {
      showChat(scope.id);
    }
  }
  ```

  Add a pivot case before the artifact/chat cases:

  ```js
  async function refreshIfStale() {
    if (document.hidden || !view) return;
    if (place === "wall") {
      const peek = await api("/artifacts?limit=1&order=ingested").catch(
        () => null,
      );
      if (!peek) return;
      const stamp = peek.total + ":" + ((peek.items[0] || {}).id || "");
      if (stamp !== wallStamp) home({ keepScroll: true });
      return;
    }
    if (pivotState && pivotState.pivot_id) {
      // A saved view is open: re-run it with the current spec so a
      // capture elsewhere is reflected, keeping scroll position.
      const scrollY = window.scrollY;
      let next;
      try {
        next = await api("/pivot/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ spec: pivotState.spec }),
        });
      } catch (err) {
        return;
      }
      if (pivotState && pivotState.pivot_id) {
        renderPivot(next, pivotState.request, pivotState.spec, pivotState.pivot_id);
        window.scrollTo(0, scrollY);
      }
      return;
    }
    if (scope.kind === "artifact" && scope.id) {
      showArtifact(scope.id, false, window.scrollY);
    } else if (scope.kind === "chat" && scope.id) {
      showChat(scope.id);
    }
  }
  ```

  The pivot case re-runs the saved view's spec (which picks up any new artifacts that match the lens) and re-renders via `renderPivot`, preserving scroll position. The `pivotState` guard (`if (pivotState && pivotState.pivot_id)`) ensures this only fires when a saved view is actually open, not when the user is on the saved-views list (`showSavedGroupings` sets `place = "inside"` but `pivotState` stays `null` because `renderPivot` was never called).

  Verify: open a saved view, switch to another app, capture a note there, switch back. The saved view re-runs and the new artifact appears in the appropriate group if it matches the lens. Scroll position is preserved. If no capture happened, the view is unchanged.

---

## S.2 - remove "These groups come from the assistant's knowledge" text

- [x] **S.2 [AGENT]** Delete the groundnote block and its CSS.

  Anchor: `museum.html:~7416-7422` inside `pivotGroupsHtml()`:

  ```js
  const inferred = d.groups.some((g) => g.grounded === false);

  let html = "";
  if (inferred) {
    html +=
      '<div class="groundnote" role="note">These groups come from the ' +
      "assistant's knowledge, not from text in your notes.</div>";
  }
  ```

  Delete the `const inferred = ...` line, the `let html = "";` stays, and delete the entire `if (inferred) { ... }` block. The `html` variable is already initialized to `""` before the `if`, so removing the `if` block is safe.

  Also delete the `.groundnote` CSS rule at `:~862` (search for `.groundnote {`).

  Verify: `rtk rg -an "groundnote\|assistant.*knowledge\|grounded" src/enqueue/static/museum.html` returns zero hits outside comments. A saved view with inferred groups renders without the disclaimer.

---

## S.3 - remove "Add artifact to this view" button from saved view

- [x] **S.3a [AGENT]** Delete the pivotactions button from `renderPivot`.

  Anchor: `museum.html:~7576` inside `renderPivot()`:

  ```js
  (pivot_id
    ? '<div class="pivotactions"><button class="btn ghost" onclick="addArtifactToGrouping()">Add artifact to this view</button></div>'
    : "");
  ```

  Delete this entire ternary expression. The `let html = back() + '<div class="h1">' ...` continues directly into the `'<div class="meta">'` line.

  Verify: a saved view no longer shows the "Add artifact to this view" button. Adding artifacts to a view is still possible from the artifact drawer's Views section (Phase P.1).

- [x] **S.3b [AGENT]** Delete the dead `addArtifactToGrouping` function and `.pivotactions` CSS.

  Anchor: `addArtifactToGrouping()` at `museum.html:~7803` (the entire function body) and `.pivotactions` CSS at `:~1038`.

  Delete both. Grep first to confirm no other call site references `addArtifactToGrouping`:

  ```bash
  rtk rg -an "addArtifactToGrouping" src/enqueue/static/museum.html
  ```

  If the only hits are the function definition and the (now-deleted) button onclick, delete the function. If other call sites exist, do NOT delete it.

  Verify: `rtk rg -an "addArtifactToGrouping\|pivotactions" src/enqueue/static/museum.html` returns zero hits.

---

## S.4 - move the gradient up to sit right below the macOS traffic-light buttons

The 32px `.topbar` (fixed, white, `--bg`) houses the macOS traffic lights. Below it is 24px of `main` padding (`--sp-5`), then `.homehead` starts with its gradient. The user wants the gradient to start right below the 32px strip, eliminating the 24px white gap.

- [x] **S.4a [AGENT]** Reduce `main`'s top padding so `.homehead` starts right below the 32px topbar.

  Anchor: `main` CSS at `museum.html:~561-565`:

  ```css
  main {
    max-width: 1200px;
    margin: 0 auto;
    padding: calc(32px + var(--sp-5)) var(--sp-5) 160px;
  }
  ```

  Change the top padding from `calc(32px + var(--sp-5))` (56px) to `32px`:

  ```css
  main {
    max-width: 1200px;
    margin: 0 auto;
    padding: 32px var(--sp-5) 160px;
  }
  ```

  Now `main`'s content starts at 32px from the window top - right below the topbar. The `.homehead` gradient begins immediately below the traffic-light strip.

  The horizontal padding (`var(--sp-5)` = 24px) and bottom padding (`160px` - clears the fixed pill) stay unchanged.

  Verify: the home page's lavender gradient starts right below the 32px traffic-light strip. No white gap between the traffic lights and the gradient. The greeting and bird sit at the top of the gradient.

- [x] **S.4b [AGENT]** Move the greeting and bird up by reducing `.homehead`'s top padding.

  Anchor: `.homehead` CSS at `museum.html:~385`:

  ```css
  padding-top: var(--sp-6);
  ```

  Change from `var(--sp-6)` (32px) to `var(--sp-3)` (12px):

  ```css
  padding-top: var(--sp-3);
  ```

  The greeting + bird now sit 12px below the top of the gradient (which itself starts at 32px from the window top). The total distance from window top to greeting is `32px + 12px = 44px` - tight to the traffic lights without being cramped. The `padding-bottom` stays `var(--sp-6)` (32px) so the gradient still fades gracefully before the wall.

  Verify: the greeting and bird sit visibly higher on the page, just below the traffic-light zone. The gradient wraps them tightly. No visual crowding - the 12px padding gives a breath between the traffic lights and the greeting.

---

## S.5 - sticky header with fade effect on scroll

The user wants the home header (greeting + bird + searchbar + groupbar + tagbar) to freeze when scrolling, with the wall cards fading in/out as they scroll under the header boundary. No hard line.

- [x] **S.5a [AGENT]** Make `.homehead` sticky so it stays visible on scroll.

  Anchor: `.homehead` CSS at `museum.html:~373-388`.

  Add `position: sticky` and `top: 0` to `.homehead`, plus a `z-index` so it sits above the wall cards:

  ```css
  .homehead {
    position: sticky;
    top: 0;
    z-index: var(--z-sticky);
    margin-bottom: var(--sp-7);
    background: linear-gradient(
      180deg,
      var(--lavender-subtle) 0%,
      transparent 100%
    );
    padding-top: var(--sp-3);
    padding-bottom: var(--sp-6);
    border-radius: var(--r-lg);
  }
  ```

  Add a `--z-sticky` token to the `:root` block if one does not exist. Check the existing z-index tokens (search for `--z-` in the `:root` block). Set `--z-sticky` to a value above the wall cards but below the pill and modal. The pill is `--z-pill` (search for its value); set `--z-sticky: 5;` or whatever sits below `--z-pill`.

  The sticky header's background gradient is semi-transparent (the lavender-subtle at the top is 16% opacity, fading to transparent). When the wall scrolls under it, the cards will show through the gradient's transparent bottom - which is the fade effect the user wants. The cards appear to fade as they pass under the gradient's bottom edge.

  BUT: a semi-transparent sticky header means the wall cards show through the ENTIRE header, not just the bottom. The greeting and searchbar would have cards visible behind them. To prevent that, the header needs an opaque or near-opaque background on its main area, with the fade only at the bottom edge.

  Revise: use a two-layer background - an opaque surface for the header content, plus a fade gradient at the bottom edge:

  ```css
  .homehead {
    position: sticky;
    top: 0;
    z-index: var(--z-sticky);
    margin-bottom: var(--sp-7);
    /* The header sits on the canvas colour, with the lavender wash on top.
       The bottom fade is a separate gradient that blends the header's
       bottom edge into the page so scrolling cards fade under it. */
    background:
      linear-gradient(180deg, var(--bg) 0%, var(--bg) 85%, transparent 100%),
      linear-gradient(180deg, var(--lavender-subtle) 0%, transparent 60%);
    padding-top: var(--sp-3);
    padding-bottom: var(--sp-6);
  }
  ```

  The first gradient layer is opaque `--bg` (white) from the top to 85% down, then fades to transparent in the last 15% - this is the fade effect. The second gradient layer is the lavender wash, visible through the first layer's opaque portion (the first layer covers it from 0-85%, but the lavender is at the top where the first layer is fully opaque white, so the lavender is hidden). Wait - this does not work because the first layer paints OVER the lavender.

  Correct approach: use the lavender wash as the base, then an opaque fade ONLY at the bottom:

  ```css
  .homehead {
    position: sticky;
    top: 0;
    z-index: var(--z-sticky);
    margin-bottom: var(--sp-7);
    background: linear-gradient(
      180deg,
      var(--lavender-subtle) 0%,
      var(--bg) 40%,
      var(--bg) 85%,
      transparent 100%
    );
    padding-top: var(--sp-3);
    padding-bottom: var(--sp-6);
  }
  ```

  This gradient: lavender-subtle at the very top, fading to `--bg` (white) by 40% down, staying white through 85%, then fading to transparent in the last 15%. The top portion has the lavender tint; the middle is opaque white (hides scrolling cards behind the searchbar/groupbar/tagbar); the bottom 15% fades to transparent (cards scroll through a soft fade, no hard line).

  Remove the `border-radius: var(--r-lg)` from `.homehead` - a sticky element with rounded top corners would look odd when the scroll content meets it. The gradient should go edge-to-edge.

  Verify: scroll down on the home page. The greeting, bird, searchbar, groupbar, and tagbar stay fixed at the top. The wall cards scroll under the header and fade out as they pass behind the header's bottom edge. No hard line - the fade is a smooth gradient. The lavender tint is visible at the very top of the header.

- [x] **S.5b [AGENT]** Add a fade mask to the wall body so cards fade as they enter the sticky header zone.

  Anchor: the `.wallbody` element (the container that holds the wall cards, rendered at `museum.html:~5742`). There is no `.wallbody` CSS rule today - add one.

  Add a CSS rule for `.wallbody` that applies a `mask-image` gradient at the top, so cards fading behind the sticky header get a CSS mask fade:

  ```css
  .wallbody {
    /* The sticky header fades its own bottom edge. This mask on the wall
       body adds a complementary fade at the top of the card area, so
       cards appear to dissolve as they scroll under the header rather
       than clipping at a hard boundary. The mask is only at the very top
       (8px) so it does not affect cards in the body of the scroll. */
    -webkit-mask-image: linear-gradient(180deg, transparent 0%, black 8px);
    mask-image: linear-gradient(180deg, transparent 0%, black 8px);
  }
  ```

  This mask makes the top 8px of the wall body fully transparent, fading to fully visible by 8px down. As cards scroll up under the sticky header, their top edges fade out through this mask, complementing the header's own bottom fade. The effect is a soft dissolve, not a hard clip.

  If the mask makes the first row of cards partially invisible when NOT scrolling (the top 8px of the first row is masked), adjust the mask start to `black 0px` and the fade to `transparent 0%, black 8px` - the first 8px is always faded, but since the sticky header covers that zone, the fade is only visible during scrolling.

  Verify: scroll the wall. Cards fade smoothly as they pass under the sticky header. No hard line between the header and the scrolling content. When not scrolling, the first row of cards is fully visible (the mask zone is hidden behind the sticky header).

- [x] **S.5c [AGENT]** Ensure the sticky header does not break the wall's infinite scroll.

  Anchor: `watchWallEnd()` at `museum.html:~5755` (the IntersectionObserver that triggers the next page fetch when the sentinel comes into view).

  The sticky header changes the scroll context but should NOT affect the IntersectionObserver - the observer watches `#wallEnd` which is at the bottom of the wall body, far below the sticky header. Confirm the observer still fires by scrolling to the bottom of a wall with many cards and verifying the next page loads.

  If the sticky header's `z-index` or `position: sticky` interferes with the observer (it should not - sticky elements are in the normal flow, unlike fixed elements), add `pointer-events: none` to the `.homehead`'s bottom fade zone. But this should not be necessary.

  Verify: with a library of 100+ artifacts, scrolling to the bottom of the wall loads the next page. The sticky header stays fixed throughout. No scroll jumps or observer failures.

---

## S.6 - ribbon pill: non-white background + stronger shadow

- [x] **S.6 [AGENT]** Give the pill a tinted background and a bolder shadow.

  Anchor: `.pill` CSS at `museum.html:~1798-1815`.

  Today:

  ```css
  .pill {
    position: fixed;
    left: 50%;
    bottom: var(--sp-5);
    transform: translateX(-50%);
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    height: 56px;
    padding: 0 var(--sp-4);
    z-index: var(--z-pill);
    background: var(--surface);
    border: 0;
    border-radius: var(--r-full);
    box-shadow: var(--shadow-lifted);
  ```

  Change:

  ```css
  .pill {
    position: fixed;
    left: 50%;
    bottom: var(--sp-5);
    transform: translateX(-50%);
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    height: 56px;
    padding: 0 var(--sp-4);
    z-index: var(--z-pill);
    /* S.6: a tinted surface, not pure white, so the pill reads as a
       distinct object floating above the artifacts. --surface-1 is the
       first elevated rung - cool, not grey, slightly raised from the
       canvas. */
    background: var(--surface-1);
    border: 1px solid var(--line);
    border-radius: var(--r-full);
    /* A bolder shadow than the default --shadow-lifted so the pill pops
       above the card grid. The extra spread and opacity make it read as
       a physical object, not a CSS panel. */
    box-shadow:
      0 4px 12px rgba(16, 17, 20, 0.06),
      0 12px 36px rgba(16, 17, 20, 0.12);
  }
  ```

  Changes from the old CSS:
  - `background: var(--surface)` -> `var(--surface-1)` (a slightly raised, cool-tinted surface, not pure white).
  - `border: 0` -> `border: 1px solid var(--line)` (a hairline edge so the pill reads as a defined object against the artifacts, not just a shadow blur).
  - `box-shadow: var(--shadow-lifted)` -> a two-layer shadow: a tight 4px/12px for the contact shadow, and a wider 12px/36px for the elevation. The wider shadow's 0.12 opacity is 50% stronger than the old 0.08, making the pill pop.

  Do NOT change the hover lift (`:~1815-1817`) or the focus ring (`:~1821-1824`) - those stay. The hover lift's `translateY(-2px)` still works on top of the new shadow.

  Verify: the pill at the bottom of the screen reads as a distinct floating object - its background is slightly cooler/darker than the cards behind it, the hairline border defines its edge, and the bolder shadow lifts it off the page. It no longer blends into the wall as a white-on-white shape.

---

## S.7 - align tags and artifacts with the gradient's horizontal bounds

The `.homehead` gradient has `border-radius: var(--r-lg)` (12px) which rounds its corners. The wall grid and groupbar extend to the full `main` content width, making them appear to stick out past the gradient's rounded edges. The fix: remove the border-radius on `.homehead` (since it is now sticky and edge-to-edge from S.5), and add a small horizontal inset to the wall body so cards align with the gradient's visual bounds.

- [x] **S.7a [AGENT]** Remove the `border-radius` from `.homehead`.

  Anchor: `.homehead` CSS at `museum.html:~387`.

  In S.5a, the `border-radius: var(--r-lg)` was already removed from the sticky header. Confirm it is gone. If it is still there, delete it. A sticky header that goes edge-to-edge should not have rounded corners - the rounding creates a visual gap between the header and the viewport edges.

  Verify: `.homehead` has no `border-radius`. The gradient goes edge-to-edge horizontally.

- [x] **S.7b [AGENT]** Add a small horizontal inset to the wall body so cards and tags align inside the gradient's bounds.

  Anchor: the `main` CSS at `museum.html:~561-565` has `padding: 32px var(--sp-5) 160px` - that is 24px horizontal padding. The `.homehead` is inside `main`, so it is 24px inset from the viewport edges. The wall grid (`.wall`) is also inside `main` and uses the same 24px inset.

  But the user perceives the tags and artifacts as "slightly outside" the gradient. This is likely because the gradient's `border-radius` (now removed in S.7a) made the gradient narrower at the corners, while the cards extended full-width. With the radius removed, the gradient and the cards should align.

  If they still appear misaligned, add `padding-inline: var(--sp-2)` (8px) to `.wallbody`:

  ```css
  .wallbody {
    padding-inline: var(--sp-2);
    -webkit-mask-image: linear-gradient(180deg, transparent 0%, black 8px);
    mask-image: linear-gradient(180deg, transparent 0%, black 8px);
  }
  ```

  The 8px horizontal padding on `.wallbody` nudges the card grid inward so it sits inside the gradient's visual bounds. The groupbar and tagbar, which are centered inside `.homehead`, already sit inside the gradient.

  Verify: the wall cards, groupbar, and tagbar all sit within the horizontal bounds of the gradient. No card or tag extends past the gradient's left or right edge. The alignment is consistent from the greeting at the top through the cards at the bottom.

---

## S.8 - verification gate

After every S.x task lands, run from `~/enqueue`:

- `bin/verify` - JS parse + pytest + contrast check.
- `bin/relaunch` - manual sweep.
- `rtk rg -an "groundnote\|assistant.*knowledge" src/enqueue/static/museum.html` returns zero hits after S.2.
- `rtk rg -an "addArtifactToGrouping\|pivotactions" src/enqueue/static/museum.html` returns zero hits after S.3.
- `rtk rg -an "border-radius.*r-lg" src/enqueue/static/museum.html | rtk rg homehead` returns zero hits after S.7a (the homehead border-radius is removed).

The phase closes when every box is checked and the running build shows:

- Opening a saved view, switching to another app, and switching back keeps the saved view on screen. A capture while away is reflected in the view on return.
- A saved view no longer shows "These groups come from the assistant's knowledge..." or "Add artifact to this view".
- The lavender gradient starts right below the 32px traffic-light strip. The greeting and bird sit higher, just below the traffic lights.
- Scrolling the wall freezes the header (greeting, bird, search, groupbar, tagbar) at the top. Wall cards fade smoothly as they pass under the header - no hard line.
- The bottom ribbon pill has a non-white background and a bolder shadow that makes it pop above the artifacts.
- The wall cards and tags align horizontally within the gradient's bounds.
- `bin/verify` is green overall.
