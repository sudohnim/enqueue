# Enqueue Progress - Phase O (theme + wall headers + eye follow + density)

This file is the agent's work queue. Do one task per turn, in order, and verify each with its "Verify" line before checking the box. Do not implement anything that is not listed below.

All edits live in `~/enqueue/src/enqueue/static/museum.html` unless a task says otherwise. The whole UI is one inline CSS + inline JS file. Line numbers are approximate; re-anchor on the surrounding code before editing because earlier tasks in this phase shift lines.

Prior phases shipped: lavender token system, the eye-with-cursor-follow, 5-up wall grid (desktop default), collapsible pivot/wall section headers (`.wallgroup` + `.grouptoggle`), saved-view rename/move/remove/add, the `view` vocabulary pass, the eyeball PNG cursor-follow via `split_eye.py`. This phase is a small refinement pass from Minh's reports.

Ground truth sampled before this phase (do not re-derive):

- The wall grid CSS at `museum.html:~1376` is already `repeat(5, minmax(0, 1fr))` at desktop. The breakpoint ladder at `:~1647-1670` is: max-width 1440 -> 4-up, 1280 -> 3-up, 1024 -> 2-up, 768 -> 1-up. Minh sees 3-up, which means his window sits in the 1280 bucket. The fix in O.2 below pushes 5-up down to narrower widths.
- The eye already sits to the left of the greeting phrase (`.greetline` is a centered flex row with the `.greet-emblem` first, then the `<h1 class="display greeting">`). The placement requirement in O.3 is already satisfied; O.3 only reworks the follow mechanism.
- `~/enqueue/eyeball.png` is a 1024x1024 image replaced by Minh on 2026-08-09. The purple eye inside it is a roughly 70x69 pixel region, x in [511, 581], y in [367, 436], center about (546, 401). The iris centre pixel samples to `#60079f` (96, 7, 159). The sclera just outside the iris samples to about `#fcfdf6` (253, 254, 246).
- The design reference at `~/Downloads/DESIGN-kraken.md` pins a bold purple scale: primary `#7132f5`, dark `#5741d8`, deep `#5b1ecf`, subtle `rgba(133, 91, 251, 0.16)`. The macOS app icon `~/enqueue/desktop/icons/icon.png` (the logo) samples to a deep violet around `#7040a0`. All three sources live in the same bold-violet family; O.4 adopts the Kraken scale because it is the only one with explicit hex values, and it falls between the eyeball-iris purple and the logo purple.

---

## O.1 - make the "Last touch" wall headers match the other view headers, and uppercase all wall section labels

When the wall is grouped by Last touch (`wallGroup === "touched"`), the two section labels are bare `.shelf` caption divs - faint 12/500 text with no chevron, no count, no collapse. The Type and Tags modes render their sections as `.wallgroup` blocks with a `.grouptoggle` header (20/500 Title type, a 2px accent rule, a count, a chevron, and a click-to-fold behaviour). Minh wants the Last touch headers to read as the same control, and he wants all wall section labels in ALL CAPS (the example given: SAVED and EVERYTHING ELSE).

The decision behind the all-caps scope: only wall section headers go uppercase. Pivot-group headers (saved views run through `renderPivot`) are a different surface and stay as-is. The uppercase is applied through one CSS rule on the shared `.wallgroup .grouptoggle .shelf` selector so every wall section - Notes, Links, #tag, SAVED, EVERYTHING ELSE - reads in caps as one set.

- [x] **O.1a [AGENT]** Uppercase every wall section header label via one CSS rule.

  Anchor: `.wallgroup .grouptoggle .shelf` CSS at `museum.html:~773-782` (currently `flex: 1; margin: 0; font-size: inherit; ...`).

  Add two declarations to that rule:

  ```css
  text-transform: uppercase;
  letter-spacing: 0.04em;
  ```

  The `0.04em` tracking stops the caps from going tight at Title size. Do not change pivot-group `.grouptoggle .shelf` selectors.

  Verify: in Type mode the headers read NOTES, LINKS, PDFS, IMAGES, FILES, CONVERSATIONS; in Tags mode they read the tag names in caps (for example #RESEARCH, UNTAGGED); in Last touch they read SAVED and EVERYTHING ELSE once O.1b lands.

- [x] **O.1b [AGENT]** Rebuild the Last touch wall body as two collapsible `.wallgroup` sections with uppercase labels and the same `.grouptoggle` header as Type/Tags.

  Anchor: `wallBodyHtml()` at `museum.html:~4853-4871`. Today the `if (wallGroup === "type")` / `"tags"` branches call `wallSectionsHtml`. The fall-through branch (Last touch) writes:

  ```
  '<div class="shelf center">saved</div>' +
  '<div class="wall wall--saved">' + wallKept.map(card).join("") + '</div>' +
  '<div class="shelf center">Everything else</div>' +
  '<div class="wall" id="wall">' + wallFirst.map(card).join("") + '</div><div id="wallEnd" class="aside"></div>';
  ```

  Replace that fall-through body with two `.wallgroup` sections built through a local helper. Each section reuses the SAME markup shape that `wallSectionsHtml` emits at `:~4927-4957`, so the look and the collapse plumbing are identical. Concretely, replace the fall-through `let body = ""; ... return body;` block with:

  ```js
  const sections = [];
  if (wallKept.length) sections.push(["SAVED", wallKept, true]);
  sections.push(["EVERYTHING ELSE", wallFirst, false]);
  const collapsed = wallCollapsedSet(wallGroup);
  let body = "";
  for (const [label, list, isSaved] of sections) {
    const key = label;
    const isCollapsed = collapsed.has(key);
    body +=
      '<section class="wallgroup' + (isCollapsed ? " collapsed" : "") +
      '" data-key="' + esc(key) + '">' +
      '<button class="grouptoggle" type="button" aria-expanded="' + String(!isCollapsed) +
      '" title="' + esc(isCollapsed ? groupPreview(list) : "") + '">' +
      '<span class="shelf center">' + esc(label) + '</span>' +
      '<span class="gmeta">' + list.length + '</span>' +
      '<span class="gchev" aria-hidden="true">' + svg("chev") + '</span>' +
      '</button>' +
      '<div class="wall' + (isSaved ? " wall--saved" : "") +
      (isSaved ? "" : '" id="wall') + '">' +
      list.map((a, i) => card(a, i)).join("") +
      '</div>' +
      (isSaved ? "" : '<div id="wallEnd" class="aside"></div>') +
      '</section>';
  }
  return body;
  ```

  Notes the dumb agent must keep:

  - The SAVED section keeps the `wall--saved` class and writes NO id.
  - The EVERYTHING ELSE section keeps `id="wall"` and the trailing `<div id="wallEnd" class="aside"></div>` because the pager (`watchWallEnd` at `:~5666`, only attached when `wallGroup === "touched"`) writes into `#wallEnd` and appends to `#wall`.
  - The labels are uppercase strings ("SAVED", "EVERYTHING ELSE") in the source. O.1a also uppercases via CSS, which is belt-and-braces; emit them uppercase in JS anyway so screen readers and the `title` tooltip already match.
  - `groupPreview`, `wallCollapsedSet`, `svg`, `esc`, `card` are all already in scope at this point in the file (used by `wallSectionsHtml` two screens up).

  Verify: with the wall in Last touch mode, the two headers look identical to a Type header - same 20/500 ink, same accent rule, same count chip, same chevron, same hover surface. Clicking SAVED folds just the kept shelf; clicking EVERYTHING ELSE folds the pager wall. The section state survives a mode switch and a reload (sessionStorage `enqueue.collapsedWall.touched`).

- [x] **O.1c [AGENT]** Wire the collapse handler into Last touch mode.

  Anchor: the mount line at `museum.html:~5617-5618`:

  ```
  if (wallGroup === "type" || wallGroup === "tags")
    mountWallGroups(wallGroup);
  ```

  Change the condition to include `touched`:

  ```js
  if (wallGroup === "type" || wallGroup === "tags" || wallGroup === "touched")
    mountWallGroups(wallGroup);
  ```

  `mountWallGroups` at `:~4988` already keyes its fold state on the mode string, so Last touch gets its own sessionStorage key (`enqueue.collapsedWall.touched`) and does not collide with Type or Tags.

  Verify: folding SAVED in Last touch, switching to Type and back to Last touch, keeps the SAVED fold. Reloading keeps it too.

---

## O.2 - push the 5-up wall density down to narrower windows and shrink the cards

The wall grid is already 5-up at desktop (`museum.html:~1376`), but Minh sees 3-up because his window is in the 1280px breakpoint bucket. The fix widens the 5-up range, tightens the card chrome so 5-up still reads, and steps the ladder down by one rung at every narrower width.

- [x] **O.2a [AGENT]** Shift the wall breakpoint ladder so 5-up persists through 1281px, and step every narrower rung down by one.

  Anchor: the four `@media (max-width: ...)` rules at `museum.html:~1647-1670`.

  Replace the ladder so it reads, in source order:

  ```css
  @media (max-width: 1280px) {
    .wall { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .card { padding: var(--sp-md); }
  }
  @media (max-width: 1024px) {
    .wall { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  }
  @media (max-width: 768px) {
    .wall {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: var(--sp-3);
    }
    .rail-h { gap: var(--sp-3); }
    .homehead .display {
      font-size: 30px;
      line-height: 35px;
      letter-spacing: -1px;
    }
  }
  @media (max-width: 480px) {
    .wall { grid-template-columns: minmax(0, 1fr); gap: var(--sp-3); }
  }
  ```

  Delete the old `@media (max-width: 1440px) { .wall { ... 4-up } }` block (the new 1280 rule supersedes it). Keep the 768 media block's `.rail-h`, `.homehead .display` rules (they were already there - do not drop them). Add the `480 -> 1-up` rung at the bottom so the ladder ends at 1, not 2.

  The net effect: default 5-up (no change), 1281-... keeps 5, 1025-1280 -> 4-up, 769-1024 -> 3-up, 481-768 -> 2-up, <=480 -> 1-up. Minh's 1280-class window now reads 5-up.

  Verify: resize the window across the ladder and confirm the column count steps 5/4/3/2/1 at 1280, 1024, 768, 480. No ladder jump skips a rung.

- [x] **O.2b [AGENT]** Shrink the card chrome so 5-up at the narrower width stays readable.

  Anchor: `.card` CSS at `museum.html:~1382-1420`.

  Change the card default:

  - `padding: var(--sp-md);` (16px) -> `padding: var(--sp-sm);` (12px).
  - `min-height: 152px;` -> `min-height: 140px;`.
  - `contain-intrinsic-size: auto 168px;` -> `contain-intrinsic-size: auto 150px;` (the intrinsic-size hint should track the real painted height within ~8px; the tighter padding drops the typical height by ~12-16px).

  The 1280 media rule from O.2a restores `padding: var(--sp-md)` (16px) at 4-up and below, so the denser default does not make every narrower rung feel cramped. Leave `content-visibility: auto`, `border`, `border-radius: var(--r-lg)`, and the hover block alone.

  Verify: at a 1300px-wide window the wall shows 5 cards per row, each card ~248px wide with 12px internal padding and a 140px floor; title and excerpt both still fit without clipping more than the existing line-clamp allows. At 1100px it drops to 4-up with the 16px padding restored.

- [x] **O.2c [AGENT]** Re-measure the card title line-clamp at the new 5-up width.

  Anchor: the `.card .title { -webkit-line-clamp: N }` rule (search `line-clamp` near the card-title CSS, around `:~1430+`).

  At ~248px card width with 12px padding, a title at the Title role (18px) wraps faster than it did at the old 4-up width. Audit the current clamp value. If the clamp is 2, raise it to 3 so a title that previously fit on 2 lines still shows its full text (now wrapped to 3). If it is already 3, leave it - going to 4 would crowd the excerpt.

  Verify: at 5-up, a long note title that previously fit on 2 lines now wraps to 3 and still shows all three lines before the ellipsis; nothing extra is clipped vs. the old 4-up behaviour.

---

## O.3 - the eye: only the purple iris follows the cursor

Minh wants the eyeball mark to sit next to the greeting (already done) and wants ONLY the purple iris to follow the cursor, not a chunk of the bird. The current mechanism (`desktop/icons/split_eye.py`) is clunky because the punched iris ellipse is inset far inside the real iris and the sliding "layer" is the whole eyeball pasted on a canvas-coloured disc, so what visibly travels is a shading patch of the bird, not the eye.

The rebuild in this task produces two clean alpha assets:

- `eye-frame.png` - the full eyeball image with the purple iris region replaced by the local sclera white, so the rest of the bird and the eye outline/lashes/ground stay put and never move.
- `eye-pupil.png` - ONLY the purple iris, extracted onto a small transparent canvas. This is the only thing that moves in the DOM.

The DOM stacks the clipped pupil under the frame, positioned exactly over the iris socket. `mountEye` translates only the pupil, clipped to a circle the size of the eye opening so the purple never spills past the lid. The frame stays stock-still.

- [x] **O.3a [AGENT]** Rewrite `desktop/icons/split_eye.py` to emit `eye-frame.png` and `eye-pupil.png` from the new `eyeball.png`.

  Anchor: `~/enqueue/desktop/icons/split_eye.py` (rewrite in place). Output paths stay `src/enqueue/static/eye-frame.png` and a new `src/enqueue/static/eye-pupil.png` (delete the old `src/enqueue/static/eye-iris.png` after the rewrite and remove its reference in the DOM - O.3b does that).

  Use these constants (measured from the new image):

  ```py
  SOURCE = STATIC / "eyeball.png"
  FRAME  = STATIC / "eye-frame.png"
  PUPIL  = STATIC / "eye-pupil.png"
  # Purple eye bbox in source pixels.
  IRIS_X0, IRIS_X1 = 511, 581
  IRIS_Y0, IRIS_Y1 = 367, 436
  # Sclera white sampled just outside the iris (do NOT include the purple fringe).
  SCLERA = (253, 254, 246, 255)
  # How far the pupil may travel in source pixels. The eye renders at
  # ~104 CSS px from an 857 px source (scale ~0.12), so 32 px is ~4 CSS px
  # of lean - a real iris shift without spilling the lid.
  SLIDE = 32
  ```

  Implementation (all in PIL, RGBA):

  1. `img = Image.open(SOURCE).convert("RGBA"); w, h = img.size`.

  2. Build a purple-mask: a boolean array over the resized-IRIS bounding box that marks pixels that are the iris purple. Use a colour gate `b > 110 and b > r + 30 and g < 130` (the iris centre is (96, 7, 159); this gate captures the purple body and rejects the white sclera, the green ground, and the dark lash ink). Feather the mask by 2px (a `GaussianBlur(radius=2)` on the L mask converted to "L" then thresholded at 128) so the frame hole has no hard seam.

  3. `frame = img.copy()`. Where the mask is set, composite `frame` pixels with `SCLERA` using the feathered mask alpha, so the hole fills with sclera white and feather into the lash edge. Save as `eye-frame.png`.

  4. `pupil = Image.new("RGBA", (IRIS_X1 - IRIS_X0 + 2 * SLIDE, IRIS_Y1 - IRIS_Y0 + 2 * SLIDE), (0, 0, 0, 0))`. Paste the iris crop `img.crop((IRIS_X0, IRIS_Y0, IRIS_X1, IRIS_Y1))` at `(SLIDE, SLIDE)`, then apply the SAME feathered purple mask so ONLY the purple pixels land (the rest of the crop - any lash/white fringe - is transparent). Save as `eye-pupil.png`.

  5. Print the two output sizes and the pupil paste offset so O.3b can use them: "wrote eye-frame.png (1024x1024), eye-pupil.png (WxH), pupil offset within frame (505, 335)" (use the real numbers).

  Keep the module docstring, update it to describe the new two-asset contract (frame + pupil, iris-only follow). Delete `eye-iris.png` from disk after the new assets write.

  Verify: `python3 desktop/icons/split_eye.py` writes both files; `eye-frame.png` is 1024x1024 with the iris region visually replaced by sclera white (open it and confirm the bird is intact minus the purple eye); `eye-pupil.png` is a small image whose only opaque pixels are the purple iris, on a transparent surround.

- [x] **O.3b [AGENT]** Rebuild the eye DOM so only the pupil moves, clipped to the eye socket.

  Anchor: the emblem markup at `museum.html:~5542-5547`:

  ```
  '<div class="greet-emblem eye" id="greetEye" aria-hidden="true">' +
  '<div class="eye-blinkwrap">' +
  '<img class="eye-iris" src="/static/eye-iris.png" alt="" draggable="false" />' +
  '<img class="eye-frame" src="/static/eye-frame.png" alt="" draggable="false" />' +
  '</div>' +
  '</div>' +
  ```

  Replace with:

  ```
  '<div class="greet-emblem eye" id="greetEye" aria-hidden="true">' +
  '<div class="eye-blinkwrap">' +
  '<div class="eye-socket">' +
  '<img class="eye-pupil" src="/static/eye-pupil.png" alt="" draggable="false" />' +
  '</div>' +
  '<img class="eye-frame" src="/static/eye-frame.png" alt="" draggable="false" />' +
  '</div>' +
  '</div>' +
  ```

  The DOM order matters: the `.eye-socket` (with the pupil) renders first, the `.eye-frame` renders after and on top, so the lashes and outline draw over the pupil at the lid edge.

  Notes the dumb agent must keep:

  - The pupil sits BEHIND the frame. The frame carries the eye outline, lashes, and ground; the pupil carries only the purple disk.
  - The blink squash still wraps both layers through `.eye-blinkwrap` (no change to the blink).

- [x] **O.3c [AGENT]** Re-style the eye CSS for the new two-asset DOM with a clipped socket.

  Anchor: the emblem CSS at `museum.html:~483-532`.

  Replace the `.greet-emblem .eye-iris { ... }` rule at `:~498-505` with this set of rules (keep `.greet-emblem`, `.greet-emblem .eye-blinkwrap`, `.eye-frame`, the blink `@keyframes`, and the hover/blink rules - only the iris layer rules change):

  ```css
  /* The socket is a circular clip box positioned exactly over the eye
     opening, so the sliding pupil can never paint past the lid. Its
     size and centre are set in source-image px as a fraction of the
     frame's display width, so they scale with the emblem. The frame's
     own art draws over the socket's edge, so the clip seam is hidden. */
  .greet-emblem .eye-socket {
    position: absolute;
    /* Centre the socket on the iris centre (~546, 401 of a 1024 image). */
    left: 53.3%;
    top: 39.2%;
    width: 9.5%;
    height: 9.5%;
    transform: translate(-50%, -50%);
    overflow: hidden;
    border-radius: 50%;
    /* The socket sits behind the frame (DOM order), no z-index needed. */
  }
  .greet-emblem .eye-pupil {
    position: absolute;
    /* Rest: centred on the socket. The pupil PNG is sized 2x SLIDE larger
       than the iris crop, so the -50% centring puts the iris at the
       socket centre while leaving travel headroom in every direction. */
    left: 50%;
    top: 50%;
    width: 100%;
    height: 100%;
    transform: translate(-50%, -50%);
    will-change: transform;
  }
  ```

  Tune the socket's `left/top/width/height` if the pupil does not line up with the hole at rest (see O.3d Verify). The values above use the measured iris centre (546/1024 = 53.3%, 401/1024 = 39.2%) and a socket diameter of roughly 98 source px / 1024 = 9.5% - slightly larger than the 70px purple iris so the pupil has travel room while staying clipped.

  Keep `.eye-frame` unchanged (it stays `width: clamp(84px, 11vw, 104px); height: auto; display: block;`). The blink `.eye-blinkwrap` squash stays unchanged.

  Verify: at rest, the composed eye looks identical to the source `eyeball.png` - the purple pupil fills the hole in the frame with no visible seam. Moving the cursor does not move the frame; only the purple disk slides.

- [x] **O.3d [AGENT]** Rewrite `mountEye` so it moves only `.eye-pupil`, only within the socket.

  Anchor: `mountEye()` at `museum.html:~5682-5772` and `tearDownEye()` at `:~5774`.

  In `mountEye`:

  - Change `const layer = el.querySelector(".eye-iris");` to `const layer = el.querySelector(".eye-pupil");`.
  - Keep the dead-zone pull logic and the hover-defers-to-blink behaviour exactly as written.
  - Replace the reach math. The old line:

    ```js
    const frame = el.querySelector(".eye-frame");
    const reach = 60 * (frame.getBoundingClientRect().width / 857);
    ```

    becomes:

    ```js
    const socket = el.querySelector(".eye-socket");
    const sock = socket.getBoundingClientRect();
    // Travel scales with the socket's display: ~30% of its half-width,
    // so the pupil leans within the lid without ever clearing it. The
    // clip box guarantees containment even if the math drifts.
    const reach = Math.min(sock.width, sock.height) * 0.30;
    ```

  - The `layer.style.transform` write stays a `translate(calc(-50% + Xpx), calc(-50% + Ypx))`; the `-50%` keeps the pupil centred on the socket while the offset slides it. The follow direction check before, keep as-is.

  - Keep `rest`, the rAF coalescing, the `:hover` re-checks, the `pointermove` + `mouseleave` listener registration, and the `eyeMove`/`eyeLeave` exports unchanged.

  - Keep `tearDownEye` unchanged except that it no longer references any `.eye-iris` (it already only clears the timer and the two listeners; verify no selector mentions `eye-iris`).

  Reduced-motion behaviour stays: the follow runs (it is functional, not decorative), only the blink chain is gated by `motionOk`.

  Verify (synthetic): with the wall open and the mouse 300px to the right of the eye, `getComputedStyle(el.querySelector('.eye-pupil')).transform` shows a real translate of roughly `translate(calc(-50% + 9px), calc(-50% + 0px))` (the exact px scales with the rendered socket width); moving to the left mirrors it; hovering the emblem centres the pupil; mouseleave rests it at the centred default. The frame's transform stays `none` throughout. With reduced-motion on, the pupil still follows the cursor; only the blink stops.

---

## O.4 - theme: replace the soft muted lavender with a bold purple

Minh wants the accent stepped up from the muted lavender `#5e6ad2` to a bolder purple. The reference sources are the eyeball.png iris (`#60079f`), the app icon logo (`#7040a0`), and `~/Downloads/DESIGN-kraken.md` (primary `#7132f5`, dark `#5741d8`, deep `#5b1ecf`, subtle `rgba(133, 91, 251, 0.16)`). The Kraken doc is the only source with explicit hex scales, so this task adopts the Kraken scale as the new token family. It is bolder and bluer than the current muted lavender, and it sits in the same bold-violet family as the brand art.

The agent replaces the accent/lavender token family in `:root`, hunts every literal hex and rgba that was the old muted lavender, mirrors the same edits into the three sibling HTML files that keep their own token copies, re-measures the WCAG contrast the comments document, and rewrites those comments to match the measured ratios. `bin/check-contrast` reads tokens live and will fail until the new text shades clear the floors; the agent fixes failures by darkening the text step, never by backing off the bold purple fill.

- [x] **O.4a [AGENT]** Replace the accent and lavender token family in `:root`.

  Anchor: the `:root` token block at `museum.html:~106-148`. Replace these tokens exactly:

  | token | old | new |
  | --- | --- | --- |
  | `--accent` | `#5e6ad2` | `#7132f5` |
  | `--accent-quiet` | `#5e69d1` | `#5741d8` |
  | `--accent-strong` | `#5e6ad2` | `#7132f5` |
  | `--accent-ink` | `#101114` | `#101114` (unchanged) |
  | `--accent-text` | `#4a51a8` | `#5741d8` |
  | `--lavender` | `#5e6ad2` | `#7132f5` |
  | `--lavender-hover` | `#828fff` | `#8b5cf6` |
  | `--lavender-focus` | `#5e69d1` | `#7132f5` |
  | `--lavender-deep` | `#4a51a8` | `#5b1ecf` |
  | `--lavender-subtle` | `rgba(94, 106, 210, 0.12)` | `rgba(113, 50, 245, 0.16)` |
  | `--on-lavender` | `#ffffff` | `#ffffff` (unchanged) |
  | `--link` | `#4a51a8` | `#5741d8` |
  | `--tint-note` | `rgba(94, 106, 210, 0.12)` | `rgba(113, 50, 245, 0.14)` |

  Do not change the neutral, surface, semantic, or radius tokens (they are not the purple family).

  Verify: `rtk rg -a -n "5e6ad2|5e69d1|828fff|4a51a8|94, 106, 210" src/enqueue/static/museum.html` returns no hits inside `:root`.

- [x] **O.4b [AGENT]** Replace every remaining literal of the old muted lavender outside `:root`.

  Anchor summary (grep returns the full list): literal `#5e6ad2`, `#5e69d1`, `#828fff`, `#4a51a8`, and `rgba(94, 106, 210, ...)` appear inside CSS comments and (rarely) inside component rules throughout `museum.html`.

  Replace each literal with the same token from the O.4a table:

  - `#5e6ad2` -> `#7132f5`
  - `#5e69d1` -> `#7132f5` (the focus step now equals the primary)
  - `#828fff` -> `#8b5cf6`
  - `#4a51a8` -> `#5741d8`
  - `rgba(94, 106, 210, 0.12)` -> `rgba(113, 50, 245, 0.16)`
  - `rgba(94, 106, 210, 0.14)` -> `rgba(113, 50, 245, 0.14)`

  Do it with a single set of `replaceAll`-style edits so every comment that quotes an old hex gets the new hex with it.

  Verify: `rtk rg -a -n "5e6ad2|5e69d1|828fff|4a51a8|94, ?106, ?210" src/enqueue/static/museum.html` returns zero hits anywhere in the file.

- [x] **O.4c [AGENT]** Mirror the same token changes into the three sibling HTML files.

  Anchor: `src/enqueue/static/capture.html:~63-67` and the parallel blocks in `src/enqueue/static/museum-plain.html` and `src/enqueue/static/capture-plain.html`. Each file keeps its own `:root` copy of the accent family.

  Apply the exact same token table from O.4a to each file. Also replace any literal of the old muted lavender in those files (the same literal list as O.4b).

  Verify: `rtk rg -a -n "5e6ad2|5e69d1|828fff|4a51a8|94, ?106, ?210" src/enqueue/static/capture.html src/enqueue/static/museum-plain.html src/enqueue/static/capture-plain.html` returns zero hits.

- [x] **O.4d [AGENT]** Re-measure the documented WCAG ratios and rewrite the `:root` comments to match; fix any `bin/check-contrast` failure by darkening the text step.

  Anchor: the comment blocks at `museum.html:~107-148` that document contrast ratios (eg "`#5e6ad2` clears the 3:1 sole-boundary rule on the canvas (4.70:1)"), and `bin/check-contrast` (the gate that reads the `:root` tokens live and fails the build on any WCAG miss).

  Steps:

  1. Run `bin/check-contrast` from `~/enqueue`. Note every failure line (it names the token and the failing ratio).
  2. For each text-type token (`--accent-text`, `--link`, any lavender token that the gate treats as text on a ground), if it fails 4.5:1 on its permitted ground, darken THAT token's new value one step at a time until it passes, keeping the value inside the bold-violet family. Suggested fallbacks, in order: `#5741d8` -> `#5b1ecf` -> `#4a1bb8` -> `#3d1299`. Do not darken the fill tokens `--accent`, `--lavender-hover`, `--lavender-subtle`; those are fills/rings/washes and the gate treats them at the 3:1 graphic tier, not the 4.5 text tier.
  3. For each boundary or graphic-pair failure (the lavender fill as a sole boundary, ink-on-lavender, white-on-lavender), if the bold fill fails the 3:1 sole-boundary tier or the white-on-fill 3:1 graphic tier, darken the fill itself one step (`#7132f5` -> `#6620e0` -> `#5b1ecf`). Prefer keeping `#7132f5` as `--accent` and `--lavender` if it passes; the gate is the source of truth.
  4. Once the gate passes, re-compute each documented ratio with the actual new hex values and rewrite the prose in the `:root` comments so the numbers match the new scale. The comments at `:~107-148` reference specific ratios (4.70:1, 6.92:1, 4.02:1, 4.38:1, 2.87:1); replace each with the real number for the new hex. Do not invent ratios - use the same WCAG relative-luminance math `bin/check-contrast` uses (`sRGB -> linear -> luminance -> (L1+0.05)/(L2+0.05)`).
  5. Apply the final (post-gate) `--accent-text` / `--link` / lavender text values back into O.4a/O.4b's replacements in all four HTML files so they stay consistent.

  Verify: `bin/check-contrast` exits 0, and the `:root` comment block quotes ratios that match the actual new hex values when recomputed by hand. `bin/verify` is green overall.

---

## O.X - eyeball measurement corrections (verified against eyeball.png)

Sampled against `~/enqueue/eyeball.png` before the agent starts. These supersede the constants written in O.3:

| value | written in O.3 | verified | notes |
| --- | --- | --- | --- |
| iris bbox | x[511,581] y[367,436] | x[512,581] y[368,436] | off by one, immaterial |
| iris center | (546, 401) | (546, 402) | immaterial |
| iris size | (not stated) | 70 x 69 px, solid `#60079f` | solid fill, not a gradient blob |
| violet streak above iris | (not in rewrite) | none exists | the OLD `split_eye.py` referenced `STREAK_CENTER = (411, 197)` against the previous image; the new image has no streak there. O.3a's rewrite is correct to punch ONLY the iris hole. |
| `SCLERA` constant | (253, 254, 246) | **(252, 253, 252)** | the old sample included a purple pixel; re-sampled a 50px ring around the iris bbox (15687 white pixels) and the average is neutral white with a hair cool tint - (252, 253, 252). Update O.3a's `SCLERA = (253, 254, 246, 255)` to `SCLERA = (252, 253, 252, 255)`. |
| socket clip box width/height | 9.5% x 9.5% | **18.0% x 13.7%** | 9.5% (~97 px) is the size of the iris itself, which would clip the pupil to barely larger than itself and kill any visible travel. The lid opening - the white sclera run bounded by the lash line - measures ~184 px wide x ~140 px tall at the iris center row/column. Use 184/1024 = 18.0% for width and 140/1024 = 13.7% for height. |
| socket clip box left/top | 53.3% / 39.2% | 53.3% / 39.3% | unchanged (iris center, where the pupil sits at rest) |
| travel reach | `min(w,h) * 0.30` | **cap at 25 source px** | with a 184x140 socket and a 70x69 pupil, vertical headroom is (140-69)/2 = 35 px and horizontal headroom is (184-70)/2 = 57 px. `min * 0.30` evaluates to 140 *0.30 = 42 px, which exceeds the 35 px vertical headroom and would visibly clip the pupil at the lower lid. Cap reach at 25 source px - it scales to the rendered socket automatically, and gives ~3 CSS px of lean at the 104 px display size (25/1024* 104 = 2.5 px). |
| `border-radius: 50%` on socket | (not stated as ellipse) | **keep 50%** | with an 18% x 13.7% box, `border-radius: 50%` produces an eye-shaped ellipse that matches the lid opening. Do NOT use a fixed px radius. |
| DOM z-index | "no z-index needed" | confirmed | `.greet-emblem` and `.eye-blinkwrap` create no stacking context (verified: no `transform`/`opacity`/`z-index`/`filter`/`will-change` on them), so DOM order is the paint order. The socket (first child) renders behind the frame (second child). The `will-change: transform` on `.eye-pupil` promotes only the pupil, not its parent, so it stays under the frame. |

### Corrected O.3c CSS rule

Replace the `.greet-emblem .eye-socket` rule in O.3c with:

```css
.greet-emblem .eye-socket {
  position: absolute;
  left: 53.3%;
  top: 39.3%;
  width: 18.0%;
  height: 13.7%;
  transform: translate(-50%, -50%);
  overflow: hidden;
  border-radius: 50%;
}
```

### Corrected O.3d reach math

Replace the reach lines in O.3d's `mountEye` with:

```js
const socket = el.querySelector(".eye-socket");
const sock = socket.getBoundingClientRect();
// Cap at 25 source px of travel, scaled by the rendered socket's
// width vs the 184 px source width. (140 px tall source pupil has
// 35 px of vertical headroom - 25 px keeps the pupil well inside the
// lid even when the lean runs along the diagonal.)
const reach = 25 * (sock.width / (184 * (el.getBoundingClientRect().width / 1024)));
```

The formula: `sock.width` is the displayed socket width; divide by `(el.displayed_width / 1024)` to recover the source-px scale of the socket, then `25 * (socket_in_source_px / 184)` gives the source-px reach displayed at the rendered scale.

### Mask gate note (no change needed)

The proposed purple gate `b > 110 and b > r + 30 and g < 130` was verified against the whole image - it selects 3775 px, ALL inside the iris bbox x[512,581] y[368,436]. No leakage into any other purple-ish region in the bird body. Keep the gate as written in O.3a. A 1-2 px purple fringe just outside the gate (at the lower lash line, pixels like `#5f347c` and `#4f1375`) will stay in the frame as fixed dark pixels - at the 104 px display size that is sub-pixel and invisible. Do not loosen the gate to catch the fringe; a looser gate picks up body art at y up to 865.

---

## O.5 - verification gate

After every O.x task lands, run from `~/enqueue`:

- `bin/verify` - JS parse on both HTML pages, pytest, and the contrast check (O.4d makes the contrast check green again).
- `bin/relaunch` (or `uv run enq serve` then open `http://127.0.0.1:8787/`) - manual sweep of each Verify line.
- `rtk rg -a -ic "5e6ad2|5e69d1|828fff|4a51a8|94, ?106, ?210" src/enqueue/static/museum.html src/enqueue/static/capture.html src/enqueue/static/museum-plain.html src/enqueue/static/capture-plain.html` returns 0 after O.4.

The phase closes when every box is checked and the running build shows:

- The Last touch wall header reads SAVED and EVERYTHING ELSE as the same collapsible Section header control Notes/Links use, and every wall section label is in caps.
- 5 cards per row at Minh's window width, with tighter card chrome and a correct title line-clamp.
- The eyeball sits to the left of the greeting; the bird never moves; only the purple iris slides inside the fixed socket as the cursor moves, clipped to the lid.
- The accent reads as a bold violet (`#7132f5` family) across every purple surface - links, focus rings, fills, hovers, pills, the greeting eye frame - and `bin/check-contrast` stays green.
