# Phase layout findings

The home/wall view has a monotonous spatial rhythm, an over-dense 5-up square card grid, and card radii (40px) far past the 32px "insanely rounded" ban.
The spacing scale skips the 16px and 24px steps that DESIGN.md requires, so the page's most common gap (sp-4 = 20px) is an off-scale value that falls between the new md (16) and lg (24).
Section rhythm is uniform (every shelf 32px above / 8px below, every wall 20px gap) with no tight-generous alternation, and the greeting display is undersized and underweighted for a hero under the new type scale.

## Overlap with existing PROGRESS.md

These findings extend Phase A (tokens), Phase B (typography), and Phase C (components) for the home surface specifically.
A.1 covers the scale repoint; the tasks below specify which home selectors take which new values and why.
B.1 covers the type scale; the tasks below call out the greeting, shelf, and card-title sizes by name.
C.2 covers card radius and surface; the tasks below add the wall grid density and aspect-ratio restructure that C.2 does not address.

## Findings

- [ ] **L.1 [AGENT]** Cut card radius from 40px to 12px per DESIGN.md section 5.
  Anchor: `museum.html:159` `--r-lg: 40px`, used by `.card` at `museum.html:844` (`border-radius: var(--r-lg)`), and by `.cardband` at `museum.html:1100` and `.card.pictorial` at `museum.html:1142`.
  40px on a ~220px card eats the corners and is above the 32px+ "insanely rounded" impeccable ban (SKILL.md absolute bans: "border-radius: 32px+ on cards / sections / inputs").
  DESIGN.md section 5 says cards use `lg` 12px. Repoint `--r-lg` to 12px in Phase A.1, then confirm every card surface that references it (`.card`, `.cardband`, `.card.pictorial`, `.reader`) lands at 12px.
  Verify: a resting card has 12px corners; no card on the wall reads as "insanely rounded".

- [ ] **L.2 [AGENT]** Reduce the wall from 5-up square to 4-up with a relaxed aspect ratio.
  Anchor: `.wall` at `museum.html:828` (`grid-template-columns: repeat(5, minmax(0, 1fr))`, `gap: var(--sp-4)`, `aspect-ratio: 1 / 1` on `.card` at `museum.html:839`).
  Five columns of square cards at a 1200px max-width is ~220px per card with a 20px gap: too dense for a product surface where Linear uses 3-up and the impeccable layout reference says "Use cards only when content is truly distinct and actionable" and "Vary card sizes, span columns, or mix cards with non-card content."
  The `aspect-ratio: 1 / 1` forces squareness on notes that are not square: a short title leaves empty space, a long title clips at 3 lines.
  Change the grid to `repeat(4, minmax(0, 1fr))` at desktop (stepping to 3 at 1080px, 2 at 760px, 1 at 460px) and replace the fixed `1 / 1` aspect ratio with a `min-height` that lets card height follow content, so a note with a one-line title does not waste half the card.
  Tie the gap to the new scale: `gap: var(--sp-lg)` (24px) per DESIGN.md section 4, not the off-scale 20px.
  Verify: at 1440px the wall shows 4 columns with 24px gaps; card heights vary with content; no card is forced square.

- [ ] **L.3 [AGENT]** Break the monotony between the "saved" and "Everything else" walls.
  Anchor: `home()` at `museum.html:4118` (saved wall) and `museum.html:4130` (Everything else wall). Both render `<div class="wall">` with identical grid, gap, and card markup, separated only by a shelf label.
  The impeccable layout reference: "Is every section structured the same way? Monotonous repetition." Two consecutive identical grids is the tell.
  Options: (a) merge saved + Everything else into one wall with a pinned section break (a subtle divider or a shelf label inside the grid, not a separate grid), or (b) give the saved wall a different treatment (a wider 2-up grid for pinned items, or a horizontal scroll rail) so it reads as a distinct shelf, not a repeat.
  The "saved" items are pinned by the user, so they earn a distinct treatment. Recommend option (b): a 2-up or 3-up wider grid for saved, then the 4-up grid for Everything else, so the two sections read as different densities.
  Verify: the saved section and the Everything else section have visibly different grid density or layout; they do not read as the same grid twice.

- [ ] **L.4 [AGENT]** Establish tight-generous rhythm between sections.
  Anchor: `.shelf` at `museum.html:467` (`margin: var(--sp-5) 0 var(--sp-2)` = 32px above, 8px below), `.wall` at `museum.html:833` (`margin-top: var(--sp-4)` = 20px), `.homehead` at `museum.html:280` (`margin-bottom: var(--sp-6)` = 48px).
  Every shelf has the same 32px/8px margin. Every wall has the same 20px top margin. The rhythm is uniform, not alternating.
  The impeccable layout reference: "Does the layout have visual rhythm? Alternating tight/generous spacing" and "Varied spacing within sections (not every row needs the same gap)."
  Under the DESIGN.md scale: the shelf-to-content gap should be `--sp-sm` (12px) or `--sp-md` (16px), not 8px (`--sp-2`) which is too tight for a label-to-content separation. The section-to-section gap (shelf to shelf) should be `--sp-xl` (32px) or `--sp-xxl` (48px), with the first shelf after the homehead getting `--sp-xxl` (48px) and subsequent shelves getting `--sp-xl` (32px) so the step down from the header is the largest, then the rhythm tightens.
  Verify: the gap from homehead to first shelf is larger than the gap between subsequent shelves; the shelf label has at least 12px to its content below.

- [ ] **L.5 [AGENT]** Fix the spacing scale so 16px and 24px exist, and repoint sp-4 uses on the home surface.
  Anchor: `--sp-4: 20px` at `museum.html:147`, used by `.wall` gap and margin-top (`museum.html:833-834`), `.searchbar` padding (`museum.html:241`), `.item` padding (`museum.html:803`), `.homehead .searchbar` margin-top (`museum.html:286`), `#wallEnd` padding (`museum.html:1057`).
  The current scale (4, 8, 12, 20, 32, 48) skips 16 and 24, which DESIGN.md section 4 requires. The 20px value is off the new scale.
  This is a Phase A.1 task (repoint the tokens), but the layout diagnosis specifies which home-surface uses take which new value: wall gap and margin-top become 24px (lg); searchbar padding becomes 12px (sm) horizontal and 8px (xs) vertical per DESIGN.md section 7 input spec; item padding becomes 12px (sm) vertical and 16px (md) horizontal; homehead search margin-top becomes 16px (md).
  Verify: no home-surface rule uses a 20px value after the repoint; every spacing comes from the new scale.

- [ ] **L.6 [AGENT]** Move the greeting to Display LG 40px / weight 600 per DESIGN.md section 3.
  Anchor: `.display` at `museum.html:428` (`font-size: 32px; line-height: 36px; letter-spacing: -0.64px; font-weight: 500` via `.h1, .display` at `museum.html:423`), and `.homehead .display` at `museum.html:284` (`font-weight: 500`).
  The greeting is the page hero but 32px/500 is only 1.6x the card title (17px/500) and 2.3x the shelf label (14px/700). The squint test barely separates it.
  DESIGN.md section 3: Display LG is 40px / 600 / 1.12 / -1.4px. The greeting should move to this scale, and the weight to 600 (DESIGN.md: "Display at weight 600. Never 700 on display.").
  The `.greetline` gap (`museum.html:356`, `var(--sp-3)` = 12px) between the 44px emblem and the 40px greeting is fine.
  Verify: the greeting is visibly larger than every other text on the home page, at weight 600, with -1.4px tracking.

- [ ] **L.7 [AGENT]** Convert the shelf label to the DESIGN.md eyebrow role.
  Anchor: `.shelf` at `museum.html:467` (`font-size: 14px; font-weight: 700; letter-spacing: 0.56px; text-transform: uppercase`).
  DESIGN.md section 3 eyebrow: 12px / 600 / +0.6px / uppercase. The current shelf is 14px/700/0.56px: larger, bolder, and less tracked than the eyebrow spec.
  The impeccable product register: "One family is often right" and the SKILL.md ban on "Tiny uppercase tracked eyebrow above every section" is about overuse, not the role itself. The home view has 3 shelves (Collections, saved, Everything else) which is within voice, not reflex scaffolding.
  Move to 12px/600/+0.6px to match DESIGN.md. Keep the leading 8px accent dot (`.shelf::before` at `museum.html:476`) as the brand mark signal, but note it uses `--accent` which becomes lavender in Phase D.
  Verify: shelf labels are 12px/600/uppercase/+0.6px; the dot is lavender; the label reads as taxonomy, not a heading.

- [ ] **L.8 [AGENT]** Move the searchbar from pill to 8px radius per DESIGN.md section 7.
  Anchor: `.searchbar` at `museum.html:244` (`border-radius: var(--r-full)` = 999px).
  DESIGN.md section 7 inputs: "radius 8px." DESIGN.md section 5: "Buttons use 8px corners. Never pill-round a button." The searchbar is an input container, not a button, but the input spec is 8px.
  The current pill shape is a style choice that will clash with 12px cards and 8px buttons under the new system: three different radii on one surface reads as inconsistent vocabulary.
  Change to `var(--r-md)` (8px) after Phase A.1 adds the token. Keep the focus ring as the 2px lavender-focus outline per DESIGN.md section 6.
  Verify: the searchbar has 8px corners; its focus ring is the lavender outline; it reads as the same vocabulary as the cards and buttons.

- [ ] **L.9 [AGENT]** Fix the duplicate `--sp-section` declaration.
  Anchor: `museum.html:148` (`--sp-section: 48px`) and a later override (grep shows `--sp-section: 24px` at a second `:root` block around `museum.html:190`).
  The first declaration is 48px, the second overrides to 24px. The cascade makes 24px win, but 24px is far too small for section separation. DESIGN.md section 4: `section` is 96px.
  Delete the duplicate, set `--sp-section` once to 96px, and audit any rule that references it (the homehead margin-bottom uses `--sp-6` not `--sp-section`, so the section token may be unused on the home surface, but other surfaces may depend on it).
  Verify: `--sp-section` is declared once at 96px; no rule accidentally inherits 24px.

- [ ] **L.10 [AGENT]** Move the Collections `.item` radius from 20px to 12px.
  Anchor: `.item` at `museum.html:806` (`border-radius: var(--r)` = 20px).
  The `.item` is a full-width horizontal row, not a card, but 20px is still very round for a row that spans the full content width. DESIGN.md section 5: cards and panels use 12px.
  The `.item` sits in the Collections section between the homehead and the walls. At 20px it reads as a different shape vocabulary from the 12px cards below it.
  Change to `var(--r-lg)` (12px) after Phase A.1. Also check `.item` padding (`museum.html:803`, `var(--sp-3) var(--sp-4)` = 12px 20px) and repoint to 12px 16px per the new scale.
  Verify: the Collections rows have 12px corners matching the wall cards; the shape vocabulary is consistent across the page.

- [ ] **L.11 [AGENT]** Replace inline `style="margin-bottom:var(--sp-5)"` on the saved wall with a CSS class.
  Anchor: `museum.html:4122` in `home()` JS: `'<div class="wall" style="margin-bottom:var(--sp-5)">'`.
  Inline styles in the JS markup are hard to maintain and bypass the stylesheet. The impeccable layout reference: "Use a consistent spacing scale" and the product register: "Consistent affordances across the surface."
  Add a `.wall--saved` or `.wall + .shelf` margin rule in the CSS instead of the inline style, so the gap between the saved wall and the next shelf is controlled by the stylesheet, not the JS.
  Verify: grep for `style="margin` in the home() function returns nothing; the gap is controlled by CSS.

- [ ] **L.12 [HUMAN]** Desktop review of the reshaped home view at 1440, 768, and 390px.
  The rhythm alternates (homehead-to-first-shelf is the largest gap, subsequent shelves tighten), the wall is 4-up with content-height cards at 24px gaps, the greeting reads as the hero at 40px/600, the shelf labels are quiet eyebrows, and the card and row radii are consistent at 12px.
  Verify: the squint test identifies the greeting as primary, the search bar as secondary, the shelves as groupings; the wall does not read as a dense grid of identical squares; the radii are consistent.
