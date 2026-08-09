# Phase audit findings

The enqueue desktop app is a single 244 KB inline HTML file (`museum.html`, 7453 lines) with all CSS and JS inline, plus a 15 KB `capture.html`.
The codebase already has a rigorous contrast-awareness culture (WCAG ratios in `:root` comments, a `prefers-reduced-motion` block, `aria-hidden` on decorative elements, `:focus-visible` with `:focus:not(:focus-visible)` suppression) and a working token system, but every token is still the old warm cream-and-amber palette that the new `docs/DESIGN.md` replaces.
The most urgent issues beyond the known `#828fff` hover gap (PROGRESS A.3) are a focus ring using near-black ink instead of lavender-focus, a pill input with no visible focus indicator, five floating surfaces pairing 1px borders with 48px-blur shadows (the ghost-card anti-pattern), breakpoints that do not match the new DESIGN.md spec, and 820 KB of TTF fonts when a woff2 file sits unused in the same directory.

## Audit health score

| # | Dimension | Score | Key finding |
| --- | ----------- | ------- | ------------- |
| 1 | Accessibility | 3 | `.pill input:focus` has `outline: none` and no alternative focus indicator |
| 2 | Performance | 3 | 820 KB of TTF fonts loaded; a woff2 file exists but is unused |
| 3 | Theming | 2 | Entire `:root` is old cream-and-amber; `--focus` is near-black, not lavender-focus |
| 4 | Responsive | 2 | Breakpoints (900/1080/760/460/820) do not match DESIGN.md (1440/1280/1024/768/480) |
| 5 | Anti-Patterns | 3 | Five floating surfaces pair 1px border + 48px-blur shadow (ghost-card ban) |
| **Total** | | **13/20** | **Acceptable - significant work needed** |

## Anti-patterns verdict

The app does not look AI-generated.
No gradient text, no glassmorphism, no side-stripe borders, no hero-metric template, no numbered section markers, no decorative grid backgrounds, no sketchy SVGs, no repeating-stripe backgrounds.
The wall of same-sized cards is the correct affordance for a notes wall (product UI, not marketing), not the "identical card grids" marketing anti-pattern.
The one impeccable ban that IS violated is the ghost-card pattern: five floating elements (`.pill`, `.menu`, `.folio`, `.toast`, `.dropcard`) pair `border: 1px solid var(--line)` with `box-shadow: var(--shadow-2)` (48px blur, far above the 16px threshold). The ban says pick one (border OR shadow ≤ 8px blur), never both as decoration.

## Detailed findings by severity

### P1 - Major

- [ ] **AU.1 [AGENT]** Replace the `--focus` token with lavender-focus and update the `:focus-visible` rule.
  Anchor: `--focus: #23251d` at `museum.html:144`, used by `:focus-visible { outline: 2px solid var(--focus); }` at `museum.html:639`.
  The focus ring is near-black ink on a light surface. DESIGN.md section 6 level 4 says the focus ring is a 2px `--lavender-focus` (`#5e69d1`) outline at 50% opacity. The current ring is fully opaque near-black, which is functional but not the design system's focus treatment.
  This is a theming and accessibility gap: the focus ring should be lavender per DESIGN.md, and the 50% opacity softens it so it does not overpower the content the way a solid near-black ring does.
  Verify: `:focus-visible` uses `var(--lavender-focus)` at 50% opacity (`outline-color: color-mix(in srgb, var(--lavender-focus) 50%, transparent)` or `rgba(94,105,209,0.5)`), and the `--focus` token is gone or repointed.

- [ ] **AU.2 [AGENT]** Add a visible focus indicator to the pill input.
  Anchor: `.pill input:focus { outline: none; }` at `museum.html:1279`.
  The pill input (the bottom ribbon's text field for capturing notes) suppresses `outline` on focus but provides no alternative indicator (no `border-color` change, no `box-shadow`, no `:focus-within` on a parent). A keyboard user tabbing into the pill cannot see where the cursor landed. This is a WCAG 2.4.7 (Focus Visible) violation.
  The `.searchbar` and `.tagadd` both handle this correctly: `.searchbar:focus-within` at line 249 changes `border-color` and adds a `box-shadow`, and `.tagadd:focus` at line 1691 changes `border-color`. The pill input should follow the same pattern.
  Verify: tabbing into the pill input shows a visible focus indicator (border or shadow change), and `outline: none` is either removed or paired with an alternative indicator.

- [ ] **AU.3 [AGENT]** Break the ghost-card pattern on five floating surfaces.
  Anchor: `.pill` (line ~1175), `.menu` (line ~1295), `.folio` (line ~2100), `.toast` (line ~2600), `.dropcard` (line ~2720) - all pair `border: 1px solid var(--line)` with `box-shadow: var(--shadow-2)` (48px blur).
  The impeccable skill bans `border: 1px solid X + box-shadow: 0 Npx Mpx ... with M >= 16px` on the same element. `--shadow-2` is `0 24px 48px rgba(35, 37, 29, 0.08)` - M=48, far above 16.
  DESIGN.md section 6 says depth comes from the surface ladder plus hairline borders plus whisper shadows. For floating surfaces that need elevation (pill, menu, toast, dropcard), the shadow is the right tool - so drop the border and let the shadow carry the separation. For `.folio` (a contained panel, not floating), the border is the right tool - so drop the shadow.
  Also: `--shadow-2` at 48px blur and `--shadow-3` at 96px blur are far above DESIGN.md's `--shadow-lifted: 0 8px 28px` (28px blur). The shadow tokens themselves need to move to the new cool, low-opacity scale from DESIGN.md section 6.
  Verify: no element pairs a visible border with a shadow ≥ 16px blur; floating surfaces use `--shadow-lifted` without a border; contained panels use a border without a shadow.

- [ ] **AU.4 [AGENT]** Align breakpoints with DESIGN.md.
  Anchor: `@media (max-width: 1080px)` at line 1062, `760px` at line 1067, `460px` at line 1076, `820px` at line 1632, `900px` at lines 189 and 2724.
  DESIGN.md section 9 specifies breakpoints at 1440, 1280, 1024, 768, 480. The current app uses 900, 1080, 760, 460, 820 - none match.
  The wall grid also needs a 2-up breakpoint: current goes 5-up (default) to 4-up (1080) to 3-up (760) to 1-up (460), skipping the 2-up step. DESIGN.md says 3-up at 1280, 2-up at 1024, 1-up at 768.
  After Phase A.1 replaces the token foundation, repoint every `@media` to the DESIGN.md breakpoint values and add the missing 2-up wall grid step.
  Verify: `@media` queries use 1024 and 768 (not 1080 and 760), the wall has a 2-up step, and no breakpoint uses the old values.

### P2 - Minor

- [ ] **AU.5 [AGENT]** Remove hard-coded `#000` from color-mix calls.
  Anchor: `color-mix(in oklab, var(--text) 86%, #000)` at line 696, `color-mix(in oklab, var(--danger) 82%, #000)` at lines 719-720.
  These use literal `#000` instead of a token. DESIGN.md says: don't use true black `#000000` for text; use ink `#101114`. The `color-mix` calls darken `--text` and `--danger` toward black for hover/pressed states, which is fine functionally, but the `#000` should be a token (e.g., `--ink` or a dedicated `--black` token) so the color system stays tokenized.
  Verify: no literal `#000` appears in `color-mix` or any color expression; a token carries the darkest end of the ramp.

- [ ] **AU.6 [AGENT]** Tokenize or remove `--kind-chat: #6a4a8f`.
  Anchor: `--kind-chat: #6a4a8f` at line 142, used at line 884 (`--kind: var(--kind-chat)`).
  This is a hard-coded purple for the chat kind dot, not in the new DESIGN.md token system. The kind dots are an 8px-dot palette (`--green`, `--blue`, `--peach`, `--pink`, `--teal`, `--kind-chat`) that classifies artifact types. DESIGN.md does not define kind-dot tokens (the current PROGRESS.md Phase C.4 says to re-pick kind-dot values for the new canvas).
  Either fold `--kind-chat` into the kind-dot set and re-measure it on the new white canvas for 3:1 graphic contrast and deuteranopia/protanopia hue separation, or remove it if chat cards no longer need a unique kind color.
  Verify: `--kind-chat` either becomes part of the re-measured kind-dot palette or is removed; no orphan hard-coded color remains outside the token system.

- [ ] **AU.7 [AGENT]** Switch font loading from TTF to woff2.
  Anchor: `@font-face` blocks at `museum.html:36-63`, font files in `src/enqueue/static/fonts/`.
  The app loads 4 TTF files (Regular, Medium, SemiBold, Bold) at ~205 KB each, totalling ~820 KB. A `IBM-Plex-Sans-400.woff2` file (1.6 KB, likely a subset) exists in the same directory but is unused. woff2 is ~30% smaller than TTF for the same glyphs.
  The offline promise means fonts must stay bundled, but replacing TTF with full woff2 cuts the payload. If the 1.6 KB woff2 is a subset (e.g., only for the capture window), generate full woff2 files for all 4 weights and reference them in `@font-face` with TTF as a fallback.
  Verify: `@font-face` `src` references `.woff2` files; the total font payload is smaller; all weights still render correctly.

- [ ] **AU.8 [AGENT]** Scope the greeting eye pointermove listener to the home view only.
  Anchor: `mountEye()` at `museum.html:4191`, which does `document.addEventListener("pointermove", step, { passive: true })`.
  The listener is on `document`, so it fires on every mouse move across the entire app, even when the eye is not on screen (artifact view, settings, chat). The handler is lightweight (`getBoundingClientRect` + `setAttribute`), and it is cleaned up by `tearDownEye()` in `teardown()`, so it does not fire on other surfaces.
  However, `getBoundingClientRect()` forces a layout read on every pointermove, which is a layout-thrash risk on pages with frequent reflows. Scoping the listener to `window` with a guard (check `document.getElementById("greetEye")` first, return early if null) avoids the layout read when the eye is not present.
  Alternatively, attach the listener to the `#greetEye` element's parent or use a `requestAnimationFrame` throttle so the layout read happens at most once per frame.
  Verify: the pointermove handler does not call `getBoundingClientRect` when `#greetEye` is not in the DOM; no layout read happens on artifact, settings, or chat surfaces.

### P3 - Polish

- [ ] **AU.9 [AGENT]** Move raw z-index values into the token scale.
  Anchor: `z-index: 2` at line 563, `z-index: 1` at line 1016.
  These are raw integers, not using `--z-pill`, `--z-menu`, or `--z-drawer`. The impeccable skill says: build a semantic z-index scale, never use arbitrary values.
  Add tokens (e.g., `--z-base: 1`, `--z-raised: 2`) or repoint to existing tokens, and document what each level means.
  Verify: no raw z-index integer appears in the CSS; every z-index uses a token.

- [ ] **AU.10 [AGENT]** Grow `.pill button.round` to 44px for touch.
  Anchor: `.pill button.round { width: 40px; height: 40px; }` at `museum.html:1226`.
  40x40 meets the DESIGN.md minimum (40px) but falls short of the 44x44 WCAG 2.5.5 touch target standard. The pill is a desktop ribbon, but the app is responsive down to 390px (PROGRESS.md verifies at 390), so touch targets matter.
  DESIGN.md section 9 says CTAs hold at least 40px; inputs hold 44px on touch. The round buttons are icon buttons (not CTAs with text), so 40px is the floor. Bump to 44px to be safe, or add a `@media (pointer: coarse)` rule that grows them on touch devices.
  Verify: `.pill button.round` is 44px or has a `pointer: coarse` override at 44px.

## Positive findings

- The `prefers-reduced-motion` block at line 1382 kills all animations and transitions globally, and the greeting eye JS (line 4193) checks `matchMedia` and returns a static open eye. Both paths work.
- `:focus-visible` with `:focus:not(:focus-visible) { outline: none; }` (lines 638-643) is the correct modern focus-ring pattern - keyboard users get a ring, mouse users do not.
- `aria-hidden="true"` on the greeting eye, the searchbar svg, and the `kbd.hint` correctly removes decorative elements from the accessibility tree.
- Wall cards use `tabindex="0" role="button"` with `aria-label` - keyboard navigable and screen-reader labeled.
- `font-display: swap` on all `@font-face` rules prevents FOIT (flash of invisible text).
- No external CDN fetches, no `@import`, no remote `url(http...)` - the offline promise is kept.
- No layout-property transitions (width, height, margin, padding, top, left) in the CSS - transitions are on transform, opacity, color, border-color, box-shadow only.
- The `.searchbar:focus-within` pattern (border-color + box-shadow on the container, outline: none on the input) is the correct way to draw focus on a composite input.

## Recommended actions

1. **[P1] `$impeccable polish`**: Fix the focus ring (AU.1), pill input focus (AU.2), and ghost-card pattern (AU.3) after Phase A replaces the token foundation.
2. **[P1] `$impeccable adapt`**: Align breakpoints and add the 2-up wall grid step (AU.4) and touch target sizes (AU.10).
3. **[P2] `$impeccable polish`**: Tokenize `#000` and `--kind-chat` (AU.5, AU.6), switch to woff2 (AU.7), scope the pointermove listener (AU.8).
4. **[P3] `$impeccable polish`**: Clean up raw z-index values (AU.9).
5. **[final] `$impeccable audit`**: Re-run after fixes to confirm the score improves.
