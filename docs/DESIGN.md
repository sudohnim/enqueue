# Design System - Enqueue

## Overview

Enqueue is a place to put things you are not ready to decide about.
The interface should feel like a quiet, warm, well-lit room where nothing is urgent and nothing is lost.
It is a local-only desktop application built on a Tauri shell wrapping a Python FastAPI backend that serves two self-contained HTML surfaces: a museum (the main browsing and reading interface) and a capture overlay (a floating quick-entry window).

The visual system combines two source languages.
Colour comes from PostHog: a warm cream canvas (`#eeefe9`), an olive-charcoal ink ladder, a four-step surface ladder, a pastel callout family, and a single saturated yellow-orange (`#f7a501`) carrying every primary action.
Form and typography come from Mastercard: a pill-and-stadium radius vocabulary that skips the 8-16px middle ground, one geometric sans (IBM Plex Sans) at weight 450 body with -2% headline tracking, a dotted eyebrow label, generous structural whitespace, and wide low-opacity shadows used only for floating chrome.

The app's signature object is the floating capture pill, present on every page.
It is a 56px-tall full-pill at the bottom-centre of the viewport, carrying a 32px yellow-orange disc with a plus glyph, flanked by icon-only companion buttons for search, ask, and settings.
Everything else on screen is olive ink on warm cream, organised into square artifact cards on a responsive grid, with kind identity carried by an 8px dot beside a plain text label rather than by colour alone.

The app makes no network requests for fonts, stylesheets, or analytics.
All fonts are vendored as static TTF files in `src/enqueue/static/fonts/`.
The HTML is served from `127.0.0.1` and the only external request the app ever makes is a single opt-in fetch per saved link, for preview generation.

### Key Characteristics

- Warm cream canvas (`#eeefe9`) edge to edge, never pure white, never dark.
- Single yellow-orange CTA (`#f7a501`) with a mandatory 1.5px ink border, because the yellow measures 1.63:1 on the darkest ground and cannot bound a control on its own.
- IBM Plex Sans across every text role, vendored as static TTF cuts at weights 400, 500, 600, 700. Weight 450 is declared but rounds to 400 because the variable woff2 cut is not vendored; body letter-spacing is tightened by -0.08px to compensate.
- Radius scale skips 8-16px entirely: 6px for micro-decoration, 20px for controls, 40px for containers, 999px for pills and circles.
- Kind identity is always an 8px dot plus a plain ink text label, never colour alone.
- About 95% of surfaces sit flat on cream with a 1px hairline border; shadows appear only on genuinely floating chrome (the capture pill, the capture menu, the modal, hovered cards).
- No dark mode. `color-scheme: light` on `:root` ensures native scrollbars and carets stay light.

---

## Colours

All hex values below are extracted from the `:root` block in `src/enqueue/static/museum.html`.
The capture overlay (`capture.html`) copies a subset of these tokens rather than sharing the stylesheet, because it is a different surface with a different lifetime.

### Surface Ladder

| Token | Hex | Role |
| --- | --- | --- |
| `--bg` | `#eeefe9` | Warm cream canvas. The page body, the top bar, every page background. Runs edge to edge. Never substitute white. |
| `--surface` | `#ffffff` | Raised card. Artifact cards, the answer bubble, settings group cards, the modal dialog, the capture menu, the search bar. The dominant card surface. |
| `--surface-doc` | `#fcfcfa` | Warm reading white. Long-form surfaces: the artifact detail body pane (`.docpane`), note text, extracted PDF text. Softer than `--surface` so a full page of it does not glare against the cream. |
| `--surface-2` | `#e5e7e0` | Recessed soft fill. Secondary fills, inline code chips, the search field at rest, hovered rail rows, disabled control fill, the user's chat bubble. |

Surface rule: the ladder runs canvas to raised (`--surface`) to reading (`--surface-doc`), with `--surface-2` sideways off the canvas as a recession, not an elevation.
The code never nests a `--surface-2` block inside a `--surface` card.

### Ink (Text)

| Token | Hex | Role | Worst contrast (vs `--surface-2`) |
| --- | --- | --- | --- |
| `--text` | `#23251d` | Headlines, artifact titles, button labels on light, question text, active nav, focus ring. Olive-charcoal that reads near-black on cream. | 12.44:1 |
| `--text-dim` | `#4d4f46` | Default body copy. Answer text, note bodies, settings descriptions, card previews, excerpts. The most-used text colour. | 6.68:1 |
| `--text-mute` | `#63655b` | Metadata only: timestamps, kind labels, counts, capture source, meta rows. | 4.75:1 |

All three pass 4.5:1 on all three grounds checked by `bin/check-contrast` (`--bg`, `--surface`, `--surface-2`).
`--text-mute` is the tightest at 4.75:1 on `--surface-2` and has almost no headroom left.

PostHog's `mute` value `#6c6e63` measures 4.16:1 on `--surface-2` and fails 4.5:1.
It was darkened to `#63655b` (4.75:1). This is the only PostHog ink value altered from the source.

PostHog's `ash` `#9b9c92` (2.40:1 on canvas) and `stone` `#b6b7af` (1.58:1) are deliberately absent.
Disabled text uses `--text-mute` at 55% opacity plus `cursor: not-allowed` plus `aria-disabled`, because disabled state must be signalled by more than colour.

### The Accent

| Token | Hex | Role |
| --- | --- | --- |
| `--accent` | `#f7a501` | The one loud colour. Fill of the primary action only: the capture pill's disc, the primary button, the toggle on-state, the unread marker dot, the streaming bar, the eyebrow dot. |
| `--accent-quiet` | `#dd9001` | Pressed / hover state of the primary action. |
| `--accent-ink` | `#23251d` | Text and icons on `--accent`. Measures 7.64:1 on `#f7a501`. |
| `--accent-strong` | `#b17816` | Used only in `capture.html` for the drag-over border. Not present in `museum.html`. |

`--accent` is never used as text.
It measures 1.63:1 on `--surface-2` (the darkest ground) and 1.76:1 on `--bg`.
There is no ground in this app where yellow-orange text is legible.

`--accent` is never a lone border.
1.63:1 fails the 3:1 non-text boundary requirement.

Every filled `--accent` control carries a 1.5px `--text` border.
The border, not the fill, satisfies the 3:1 boundary requirement.
This mechanism is native to Mastercard's primary-pill spec, which uses a 1.5px border in the same colour as its fill for a crisp edge.

### Lines

| Token | Hex | Role | Worst contrast (vs `--bg`) |
| --- | --- | --- | --- |
| `--line` | `#bfc1b7` | Decorative hairline. Card borders, table rules, the rail divider, section rules, the top bar's bottom border. | 1.58:1. Decorative only. |
| `--line-soft` | `#dcdfd2` | In-card divider between adjacent rows (`.bar` top border, `.kept` bottom border). | 1.17:1. Decorative only. |
| `--line-strong` | `#7d7b73` | The sole boundary of a control: outlined button (tertiary), text input, select, textarea, toggle track, search bar, meta separator dot. | 3.40:1 (vs `--surface-2`). Clears 3:1 everywhere. |

Rule: if a line is the only thing telling the user where a clickable or typable region starts and ends, it must be `--line-strong`.
If the element also has a fill change or a visible label boundary, `--line` is fine.

### Semantic Colours

| Token | Hex | Role | Worst contrast (vs `--surface-2`) |
| --- | --- | --- | --- |
| `--link` | `#0c6083` | Inline anchor in prose, source URL on a link artifact. | 5.58:1 |
| `--danger` | `#9e2a20` | Destructive text and the fill of the destructive button. White on `#9e2a20` measures 7.48:1. | 6.00:1 as text |

PostHog's `link-teal` `#1078a3` measures 3.97:1 on `--surface-2` and fails; darkened to `#0c6083` (5.58:1).
PostHog's `accent-red` `#cd4239` measures 3.80:1 and fails; darkened to `#9e2a20` (6.00:1).

### Pastel Callout Family

Soft tinted panels carrying `--text` or `--text-dim`, used for inline notices only.
Rendered at `--r` (20px) radius, `--sp-4` (20px) inset, no border, no shadow.

| Token | Hex | Meaning |
| --- | --- | --- |
| `--tint-info` | `#dceaf6` | Neutral information. PDF page count callout, find highlights in the reader. |
| `--tint-ok` | `#d9eddf` | Confirmation. Active drop state on the capture pill. |
| `--tint-warn` | `#f7d6d3` | Caution and destructive framing. Trash warning callout, error toasts, current find highlight. |
| `--tint-note` | `#e7d8ee` | Model and provenance annotation. "Read locally" callout, credential warning. |

`--text-mute` is not permitted on any tint.
On `--tint-note` it measures 4.36:1 and fails 4.5:1.
The eyebrow on a callout steps up to `--text-dim` (6.13:1) rather than keeping its usual grey.

### Kind Colours

Five hues identify what an artifact is.
They appear only as an 8px dot at `--r-full` filled with the kind colour, then `--sp-1` (4px), then the kind name as plain text.
The dot is a graphic and answers to 3:1. The label carries the meaning and answers to 4.5:1 in `--text-dim`.

| Token | Alias | Hex | Worst contrast (vs `--surface-2`) |
| --- | --- | --- | --- |
| `--green` | `--kind-note` | `#30804b` | 3.90:1 |
| `--blue` | `--kind-link` | `#376899` | 4.67:1 |
| `--peach` | `--kind-pdf` | `#ad5a31` | 3.93:1 |
| `--pink` | `--kind-image` | `#8f4273` | 5.27:1 |
| `--teal` | `--kind-file` | `#755c12` | 5.11:1 |

All five clear 3:1 on every ground. The worst is `--green` at 3.90:1.
`--green` and `--peach` do not clear 4.5:1 on `--surface-2`, which is correct because they are graphics, not text.

Two naming legacies are kept so token names map onto the existing implementation:
`--teal` holds an olive-gold `#755c12`, not a teal. An actual teal collapses into `--green` under deuteranopia simulation; this gold does not.
`--peach` holds a burnt terracotta `#ad5a31`, not a peach.
The names are wrong and the values are right. Do not "fix" the value to match the name.

`--teal` `#755c12` and `--accent` `#f7a501` are both in the yellow family and measure 3.14:1 against each other.
They never occupy the same role: `--accent` is only ever a filled action, `--teal` is only ever an 8px dot beside a text label.
Do not place them adjacent.

### Focus and Scrim

| Token | Value | Role |
| --- | --- | --- |
| `--focus` | `#23251d` | Focus ring colour. Applied via `:focus-visible` as `outline: 2px solid var(--focus); outline-offset: 2px;` on every focusable element. Measures 12.44:1 on `--surface-2`. |
| `--scrim` | `rgba(35, 37, 29, 0.32)` | Behind the modal dialog. Tinted with `--text` rather than black, so it warms the cream rather than greying it. |

---

## Typography

### Font Family

IBM Plex Sans is the system's only typeface, vendored as static TTF cuts in `src/enqueue/static/fonts/`.
The available weights are: Regular (400), Medium (500), SemiBold (600), Bold (700).
A variable woff2 file (`IBM-Plex-Sans-400.woff2`) exists in the fonts directory but is not loaded by the HTML; the code loads only the static TTF cuts.

The type system calls for body weight 450 (Mastercard's signature half-step), but without the variable woff2 cut loaded, 450 rounds to 400.
Body letter-spacing is tightened by -0.08px to compensate for the extra apparent looseness of 400 vs 450.

Stacks declared in the code:

```css
--sans: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
--mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
```

`--mono` is deliberately system-only.
Monospace in this app carries information (hashes, paths, byte sizes), never decoration, and is not worth a second font file.

MarkForMC is proprietary and must never appear in a font stack, not even as an unreachable first entry.

### Hierarchy

Values below are extracted from the computed CSS in `museum.html`.
The chrome type roles (display, h1, h2, h3, eyebrow) are used for the app's own interface.
The markdown/editor roles (md h1, md h2, md h3) apply inside rendered markdown content and the contenteditable note editor.

| Role | Selector | Size | Weight | Line height | Letter spacing | Transform | Use |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Display | `.display` | 32px | 500 | 36px (1.125) | -0.64px (-2%) | none | Empty wall first-run copy. At most one per view. |
| H1 | `.h1` | 26px | 500 | 31px (1.19) | -0.52px (-2%) | none | Artifact detail title. |
| H2 | `.h2` | 20px | 500 | 25px (1.25) | -0.4px (-2%) | none | Modal title, settings section heading. |
| H3 | `.h3` | 17px | 500 | 22px (1.29) | -0.34px (-2%) | Not used in current chrome; card title overrides this. |
| Card title | `.card .title` | 20px | 500 | 26px (1.30) | -0.4px (-2%) | none | Artifact card title on the wall. Clamped to 3 lines (2 for pictorial). |
| Eyebrow | `.shelf` | 14px | 700 | 1 (1.0) | 0.56px (+4%) | uppercase | Section category label. Always preceded by a leading 8px accent dot drawn via `::before`. |
| Body | `body` | 14px | 450 (rounds to 400) | 1.4 | -0.08px | none | Default paragraph, base text. |
| Title (inline) | `.title` | 16px | 600 | 22.4px (1.40) | 0 | none | Inline emphasis, settings nav row label. |
| Excerpt | `.excerpt` | 15px | inherited (450) | 22px (1.47) | 0 | none | Card preview, secondary prose. Clamped to 3 lines. |
| Label | `.kindword` | 14px | 500 | 20px (1.43) | 0 | none | Kind label beside a dot. |
| Button | `.btn` | 16px | 500 | 16px (1.0) | -0.48px (-3%) | none | Every button label and nav link. |
| Button sm | `.btn.sm` | 14px | 500 | 14px (1.0) | -0.42px (-3%) | none | Chip and compact CTA label. |
| Meta | `.meta` | 13px | 500 | 18px (1.38) | 0 | none | Timestamp, count, byte size, capture source. Always `--text-mute`. |
| Thread | `.thread` | 15px | 450 (rounds to 400) | 22px (1.47) | -0.08px | none | Rail conversation row label. Selected row: 16px / 600. |
| Code | `.md code`, `.editor code` | 14px | 400 | 20px (1.43) | 0 | none | `--mono`. Inline chips and code blocks. |
| MD H1 | `.md h1`, `.editor h1` | 32px | 500 | 38px (1.19) | -0.64px (-2%) | none | Rendered markdown heading. |
| MD H2 | `.md h2`, `.editor h2` | 24px | 500 | 29px (1.21) | -0.48px (-2%) | none | Rendered markdown heading. |
| MD H3 | `.md h3`, `.editor h3` | 20px | 500 | 26px (1.30) | -0.4px (-2%) | none | Rendered markdown heading. |

### Principles

- Headlines carry -2% letter-spacing. In px that is `size * -0.02`. The words lock together rather than breathe, giving display type its editorial density.
- Line-height ratio drops as size rises. Display is 1.125, h1 is 1.19, body is 1.4. Tight display, comfortable reading.
- Uppercase appears in exactly one role: the 14px eyebrow (`.shelf`). Nowhere else, at no size, for no reason.
- One-font system. No serif accent, no display face, no second family. Contrast comes from scale, weight, and letter-spacing.
- Weight 450 is the intended body identity but is unreachable without the variable font. The -0.08px tracking compensation is the fallback.

### Font Substitutes

IBM Plex Sans is open-source under the SIL Open Font License.
The static TTF cuts are already vendored in `src/enqueue/static/fonts/`.
If the variable woff2 cut were also vendored, weight 450 would work directly and the -0.08px compensation could be removed.
Inter is the closest open-source substitute at all weights if IBM Plex Sans is unavailable.

---

## Layout

### Spacing System

Base unit 4px, structural rhythm on 8.

| Token | Value | Use |
| --- | --- | --- |
| `--sp-1` | `4px` | Icon-to-label gap, dot-to-label gap. |
| `--sp-2` | `8px` | Chip inset, tight list gaps, menu item gap. |
| `--sp-3` | `12px` | Control inner padding, rail row vertical padding, meta gap. |
| `--sp-4` | `20px` | Card inner padding, standard block gap, search bar horizontal padding. |
| `--sp-5` | `32px` | Card grid gutters, page gutters, pill bottom offset, rail width padding. |
| `--sp-6` | `48px` | Gap between major regions, modal/settings group card inset. |
| `--sp-section` | `48px` | Top padding of a page region. Compresses to `24px` below 900px viewport width. |

Never invent a spacing value.
If nothing on the scale fits, the layout is wrong.

### Grid and Container

- **Max content width:** `1200px`, centred with `margin: 0 auto`.
- **Content padding:** `calc(68px + var(--sp-4))` top (clearing the fixed top bar), `var(--sp-5)` horizontal, `160px` bottom (clearing the floating pill).
- **Wall grid:** `repeat(5, minmax(0, 1fr))` at desktop, with `aspect-ratio: 1 / 1` on every card and `gap: var(--sp-4)` (20px).
  - At 1080px viewport: 4 columns.
  - At 760px viewport: 3 columns, gap drops to `var(--sp-3)` (12px).
  - At 460px viewport: 1 column.
- **Kept rail (horizontal):** `grid-auto-flow: column`, `grid-auto-columns: 200px`, `gap: var(--sp-5)`, with scroll-snap.
- **Top bar:** Fixed, full width, 68px height, centred search bar at 75% width (max 900px).
- **Left rail:** Declared at 280px width but `display: none` in the current code. See Notes on the current build.

### Whitespace Philosophy

Structural whitespace is generous at the page level but the artifact wall stays dense, because it is a working surface.
The empty wall state centres a display headline with `--sp-section` of air above it and no illustration and no accent button, because the capture pill is already on screen and is the call to action.
The artifact detail page uses `--sp-6` (48px) margins between the header, the body pane, and the AI annotation block.

---

## Shapes

### Border Radius Scale

This is Mastercard's scale and it is the most load-bearing gesture in the system.
It deliberately skips the 8px to 16px middle ground, which is what makes the UI read as either precise-and-small or soft-and-editorial, with nothing generic in between.

| Token | Value | Use |
| --- | --- | --- |
| `--r-sm` | `6px` | Inline code chips, keyboard-shortcut glyphs, the capture overlay card, title-action buttons, find boxes. Nothing interactive larger than about 28px. |
| `--r` | `20px` | The signature control radius. Buttons, text inputs, select, callout panels, chat bubbles, rail rows, menu items, item rows, the bar under the editor, the folio counter. |
| `--r-lg` | `40px` | Large containers. Artifact cards, the artifact detail pane (`.docpane`), the modal dialog, the settings group card, the capture menu, the settings nav wrap, the reader leaf. |
| `--r-full` | `999px` | Full pill and circle. The floating capture pill, filter chips, kind dots, the search field, icon-only buttons, the "Empty trash" pill, the toggle track, source chips, the unread marker. |

There is no 8px, 10px, 12px, or 16px radius anywhere in this app.
If you find one, it is drift and it should be removed.

---

## Depth and Elevation

Mastercard's atmospheric cushioning: wide spread, very low opacity, no directional light.
Tinted with `--text` (`#23251d`) rather than pure black so the halo stays warm on cream.

| Level | Token | Value | Use |
| --- | --- | --- | --- |
| 0 | (none) | No border, no shadow | Default for canvas-on-canvas blocks, body sections. About 95% of surfaces. |
| Flat | `--line` | 1px solid `--line` border | Cards, item rows, rail divider, callouts have no border. |
| 1 | `--shadow-1` | `0 4px 24px rgba(35, 37, 29, 0.05)` | Barely-there lift. The search bar on focus. |
| 2 | `--shadow-2` | `0 24px 48px rgba(35, 37, 29, 0.08)` | The floating capture pill at rest, the capture menu, a hovered artifact card, the toast, the folio counter, the rail on mobile. |
| 3 | `--shadow-3` | `0 40px 96px rgba(35, 37, 29, 0.1)` | The modal dialog only. |

Rules: minimum 24px blur, maximum 10% opacity, no `inset` shadows, no stacked second shadow.
No shadow on anything that already has a `--line` border unless it genuinely floats over other content.
Reach for a border before a shadow.

---

## Components

### App Shell

The current museum.html implements a single-column layout with a fixed top bar.
A left rail is declared in CSS but set to `display: none` (see Notes on the current build).

- Body background `--bg`, `color-scheme: light`.
- Top bar: fixed, full width, 68px height, `--bg` background, centred search bar.
- Content column: `max-width: 1200px`, centred, own scroll region, padding `calc(68px + 20px) 32px 160px`.
- Capture pill: fixed, bottom-centre, above content, below the modal.

### Top Bar and Search

- Container: fixed, `--bg` background, 68px height, `z-index: calc(var(--z-pill) - 1)`.
- Search bar: `--r-full`, fill `--surface`, 1.5px `--line-strong` border, 40px height, `0 20px` padding, `max-width: 900px`, width 75%.
- On focus: border becomes `--accent`, `--shadow-1` appears.
- Magnifier glyph: 16px, `--text-mute` stroke.
- Input: `14px`, `--text` colour, placeholder `--text-mute`.
- The entire top bar is a window drag handle (via Rust `window_drag` invoke), except the search field itself.

### Buttons

All buttons share: `--r` (20px) radius, `button` type (16px / 500 / -0.48px), `6px 24px` padding, minimum height `40px`.
The `.btn` class also has a `.sm` variant at 14px / 500 / -0.42px.

| Variant | Class | Fill | Label | Border | Use |
| --- | --- | --- | --- | --- | --- |
| Primary | `.btn.primary` | `--accent` | `--accent-ink` | 1.5px `--text` | The one urgent action in a view. Hover/active: `--accent-quiet`. |
| Secondary | `.btn.secondary` | `--text` | `--bg` | 1.5px `--text` | Mastercard's ink pill, demoted. "Cancel" beside a destructive primary, "Open original", "Download a copy". Hover: `#14150f`. |
| Tertiary | `.btn.tertiary` | `--surface` | `--text` | 1.5px `--line-strong` | Low-emphasis but bounded. Hover: `--surface-2`. |
| Ghost | `.btn.ghost` | transparent | `--text` | none, `6px 12px` padding | Lowest emphasis. "Show more", "Restore", back button. Hover: `--surface-2`. |
| Destructive | `.btn.danger` | `--danger` | `#ffffff` | 1.5px `--danger` | Only in a confirmation modal or on the trash page. Hover: `#82221a`. |
| Terminal | `.btn.terminal` | (inherits variant) | (inherits) | (inherits) | `--r-full` radius override. Only "Empty trash". |
| Icon-only | `.btn.icon` | `--surface-2` | icon in `--text` | none, `--r-full`, 40x40 | Hover: `--line-soft`. |
| Disabled | `.btn[disabled]` | `--surface-2` | `--text-mute` at 55% | transparent | Plus `cursor: not-allowed` and `aria-disabled="true"`. |

One primary per view.

### The Wall (Artifact Cards)

The default view. A grid of square cards on cream.

- Grid: `repeat(5, minmax(0, 1fr))`, gap `--sp-4` (20px), `aspect-ratio: 1 / 1` on every card.
- Cards use `content-visibility: auto` with `contain-intrinsic-size: auto 280px` for scroll performance on large collections.
- First 18 cards animate in with a staggered `hang` animation (22ms delay per card).

**Card (text-based).**

- Container: fill `--surface`, 1px `--line`, `--r-lg` (40px), 24px inset, no shadow at rest.
- Top row: kind dot (8px `--r-full` filled with kind colour) and kind label (`.kindword`, 14px / 500, `--text-dim`), left aligned. Optional pinned star flag on the right.
- Title: 20px / 500 / -0.4px, `--text`, clamped to 3 lines.
- Preview: 15px / `--text-dim`, clamped to 3 lines, filling the middle.
- Bottom row: `.meta` at `--text-mute` with relative capture time on the left, and an unread marker (6px `--accent` dot) on the right when the artifact has not been read by the AI yet.
- Hover: `--shadow-2`, border unchanged, no transform, no scale. Transition `box-shadow 160ms ease`.
- Focus: ring per Focus spec.

**Card (pictorial).**

- `.card.pictorial`: padding 0, image fills card with `object-fit: cover` and `overflow: hidden`.
- Bottom band: `--surface` at 92% opacity with `backdrop-filter: blur(8px)`, carrying kind row and title (clamped to 2 lines).
- Pinned flag positioned absolute top-right.

**Empty wall.**

Centred, `--sp-section` from the top: a `.display` line ("Nothing here yet"), then `.state` body explaining the capture pill.
No illustration, no accent button.

### Artifact Detail Page

Single column, replaces the wall in the content column.

- Back control: ghost button with a left-arrow glyph.
- Kind dot and label.
- Title in `.h1` (26px).
- `.meta` row: captured time, byte size, source, separated by `•` in `--line-strong`.
- Title-action row: pin (star) button and trash button, 40x40, `--r-sm`, positioned to the right of the title.
  - Pin lit state: `--accent` colour, filled star icon, with a `kept` keyframe animation (260ms scale-up).
  - Trash: `.title-action.danger` hover, `--danger` colour.
- Actions row: secondary "Open original" (if link), tertiary "Download a copy" (if pdf/image/file). No primary action on this page.
- Body pane (`.docpane`): fill `--surface-doc`, 1px `--line`, `--r-lg` (40px), `--sp-6` (48px) padding, `max-width: 720px`.
  - Notes: contenteditable `.editor.md` with markdown rendering, auto-saving, version count shown in `.bar` below.
  - Images: `max-width: 100%`, `--r` (20px) radius, centred.
  - PDFs: reader with `.leaf` pages at `aspect-ratio: 1 / 1.414`, `content-visibility: auto`, find highlighting via `.findbox` overlays.
  - Links: preview image (`.shot`), description (`.lede`), URL (`.url` in `--link`).
- "Read locally" block: `--tint-note` callout at `--r` with `--sp-4` inset, containing a `.shelf` eyebrow with `--accent` dot, then the model's summary.
- Credential warning: `--tint-warn` callout if the artifact holds a detected secret.

### Chat Transcript

Question right, answer left. Transcript `max-width: 760px`, centred.

**Question (user, right).**

- Right aligned, `max-width: 78%`.
- Fill `--surface-2`, no border, `--r` (20px) with bottom-right corner at `--r-sm` (6px).
- Text: `.title` type (16px / 600) at `--text`.
- Padding `--sp-3 --sp-4` (12px 20px).

**Answer (assistant, left).**

- Left aligned, `max-width: 88%`.
- Fill `--surface`, 1px `--line`, `--r` (20px) with bottom-left corner at `--r-sm`.
- Text: `body` at `--text-dim`.
- Padding `--sp-4` (20px).
- Cited artifacts: `.src` chips at `--r-full`, fill `--surface-2`, 1px `--line`, `--sp-2 --sp-3` padding, kind dot plus `button-sm` label.
- Unsourced caveat: 16px / 600 at `--text`, with a 1px `--line-soft` top border.

**Streaming indicator.**

A 3px `--accent` bar animating left to right across the top edge of the answer bubble (`sweep` keyframe, 1.4s ease-in-out infinite).
No spinner, no bouncing dots.

**Rhythm.**

`--sp-5` (32px) between turns, `--sp-3` (12px) between consecutive bubbles on the same side.
No avatars, no name labels, no in-flow timestamps. Side and corner shape carry the speaker.

### Trash Page

- Header: `.h2` "Trash", then `.state` body stating the retention rule.
- `--tint-warn` callout at `--r` with `--sp-4` inset: "Emptying the trash deletes these files from this machine."
- Items as list rows (`.item`), not the wall grid.
  - Rows: `--r` radius, fill `--surface`, 1px `--line`, `--sp-3 --sp-4` padding, `--sp-2` gap.
  - Each row: kind dot and label, title in `.title` (16px / 600) at `--text`, `.meta` deletion date, ghost "Restore".
- Page actions: ghost "Restore all", and a `.btn.terminal` (full-pill) "Empty trash" at `--r-full`.
- Empty state: `.state` at `--text-mute`, "Nothing in the trash."

### Settings Page

- Page title in `.h1`.
- Settings nav wrap: `--surface` fill, 1px `--line`, `--r-lg` (40px), with nav rows divided by 1px `--line` bottom borders.
  - Nav rows: 14px 16px padding, 14px / 500 label, 12px / `--text-mute` description, 20px row icon, 16px chevron at 50% opacity.
- Group card (`.group`): fill `--surface`, 1px `--line`, `--r-lg` (40px), `--sp-6` (48px) inset.
  - Rows separated by 1px `--line-soft` full-bleed rules with `--sp-4` above and below.
  - Row layout: label in 16px / 600 at `--text`, description in 15px / `--text-dim`, control right aligned.
- **Toggle:** track 44x26px at `--r-full`. Off: fill `--surface-2`, 1.5px `--line-strong`, knob `--surface` with 1px `--line`. On: fill `--accent`, 1.5px `--text`, knob `--surface`. Knob translates 18px on activation.
- **Text input:** `--r`, fill `--surface`, 1.5px `--line-strong`, `--sp-3 --sp-4` padding, 16px / 450 (rounds to 400), `--text`, placeholder `--text-mute`.
- **Select:** same as text input with chevron.
- **Recorder button:** `--r`, fill `--surface`, 1.5px `--line-strong`, 16px / 500, `--text`. Listening state: fill `--surface-2`, `breathe` animation on label.

### Floating Capture Pill

The app's signature object. Present on every page.

- `position: fixed`, horizontally centred (`left: 50%; transform: translateX(-50%)`), `bottom: var(--sp-5)` (32px), `z-index: var(--z-pill)` (40).
- Shape `--r-full`, height `56px`, padding `0 var(--sp-4)`, fill `--surface`, 1px `--line`, `--shadow-2`.
- Content varies by context:
  - **On the wall:** Plus disc (32px `--accent` circle with 1.5px `--text` border, `--accent-ink` stroke) + "Keep something" label (16px / 500 / -0.48px, `--text`) + chevron (`--text-mute`) + Search icon button + Ask icon button + Settings icon button.
  - **Inside an artifact:** Back icon button + Ask icon button.
  - **Wide (typing mode):** `width: min(560px, calc(100vw - 40px))`, input field (16px / 450 / -0.08px, `--text`, placeholder `--text-mute`) + Close icon button. Optional scope label (13px / 500, `--text-mute`) prepended for "ask" mode.
- Icon-only companion buttons: 40x40, `--r-full`, `--surface-2` fill, `--text` icon. Hover: `--line-soft`.
- Disc hover: `--accent-quiet`.
- Z-index: `--z-pill` (40) for the pill, `--z-menu` (50) for the menu.

### Capture Menu

Opens upward on click of the plus disc.

- Fill `--surface`, 1px `--line`, `--r-lg` (40px), `--shadow-2`, `--sp-2` (8px) inset, width `280px`.
- Anchored `bottom: 96px`, centred on the pill.
- Items: `--r` (20px) rows, `--sp-3` (12px) padding, 20px glyph in `--text-mute`, then 16px / 450 / -0.08px label at `--text`.
- Items: "Note", "Upload", "Link", "Image".
- Hover and keyboard focus: fill `--surface-2`. Never `--accent`.
- Opens with a `rise` keyframe: 140ms fade plus 4px upward translate.
- Arrow-key navigation, Home/End support. Focus returns to the pill on close.
- `role="menu"`, `role="menuitem"` on items.

### Modal Confirmation Dialog

Used for anything irreversible, and only for that.
Implemented as a native `<dialog>` element for focus trapping, Esc handling, and top-layer rendering.

- Scrim: full viewport, `--scrim`, fading in over 160ms.
- Dialog: fill `--surface`, `--r-lg` (40px), `--shadow-3`, no border, `--sp-6` (48px) inset, `max-width: min(480px, calc(100vw - 40px))`, centred.
- Enters with `lift` keyframe: 160ms fade plus 8px upward translate.
- Content: `.h2` (20px / 500) title, then `body` at `--text-dim`, then action row.
- Action row: right aligned, `--sp-3` gap. Destructive button on the right, secondary "Cancel" to its left.
- Destructive button repeats the verb ("Empty trash"). Never "OK", never "Yes".
- Initial focus lands on Cancel. Escape cancels.
- `role="dialog"`, `aria-modal="true"`, `aria-labelledby` pointing at the title.

### Toast

- Fixed, centred, `bottom: 108px`, `z-index: var(--z-menu)` (50).
- Fill `--surface`, 1px `--line`, `--r` (20px), `--shadow-2`, `--sp-3 --sp-4` padding.
- Error variant (`.toast.bad`): fill `--tint-warn`, no border.
- `role="status"`. Auto-dismisses after 2.6s (8s for errors).
- Enters with `rise` keyframe: 160ms fade plus 4px upward translate.

### Capture Overlay

A separate Tauri window, served from `capture.html`.
Self-contained: copies a subset of museum tokens rather than sharing the stylesheet.

- Window is transparent; the card carries its own edge and shadow.
- Card: `--bg` fill, 1px `--line-strong` border, `--r-sm` (6px) radius, `--shadow-1`.
- Title bar: `--surface` fill, 30px height, 1px `--line` bottom border, draggable.
- Labels: 10px, uppercase, 1.2px letter-spacing, `--text-mute`. Problem state: `--pink` (`#8f4273`).
- Textarea: 15px, 1.45 line-height, `--text`, placeholder `--text-mute`.
- Drag-over state: border becomes `--accent-strong` (`#b17816`), with a 160ms ease transition.
- Busy state: 55% opacity, read-only field.

---

## Motion and Interaction

### Timing Tokens

| Token | Value | Use |
| --- | --- | --- |
| `--ease` | `cubic-bezier(0.16, 1, 0.3, 1)` | The app's default easing. A smooth ease-out. |
| `--dur-fast` | `140ms` | Menu open, button state transitions, border/colour changes. |
| `--dur` | `160ms` | Card hover shadow, rail transform, modal enter. |
| `--dur-slow` | `200ms` | Pill width morph, hang animation for card entrance. |

### Keyframe Animations

| Name | Duration | Easing | Use |
| --- | --- | --- | --- |
| `rise` | `--dur-fast` (140ms) | ease | Menu and toast entrance: opacity 0 to 1, translateY 4px to 0. |
| `hang` | `--dur-slow` (200ms) | `--ease` | Card entrance on wall load: opacity 0 to 1, translateY 6px to 0. Staggered 22ms per card, first 18 only. Uses `backwards` fill mode. |
| `lift` | `--dur` (160ms) | ease | Modal entrance: opacity 0 to 1, translateY 8px to 0. |
| `kept` | 260ms | `cubic-bezier(0.22, 1, 0.36, 1)` | Pin/star activation: scale 0.7 to 1, opacity 0.4 to 1. |
| `sweep` | 1.4s | ease-in-out, infinite | Streaming indicator: 3px `--accent` bar translating -100% to 350% across the answer bubble top. |
| `breathe` | 1.4s-1.8s | `--ease`, infinite | Thinking state and recorder listening: opacity 0.35 to 1 pulse. |
| `fill` | 620ms | `cubic-bezier(0.16, 1, 0.3, 1)` | Editor save bar: 1px line scaleX 0 to 1, then fade. |

### View Transitions

The app uses the View Transitions API to morph between the wall card and the artifact detail page.
The card's image (or title) claims a `view-transition-name` before the transition, held across the swap, and released after.

- `artifact-face` and `artifact-title` named transitions have their default crossfade disabled (`animation: none`), with only the group transition animated at 340ms using `cubic-bezier(0.2, 0.9, 0.24, 1)`.
- Root transition: old view fades out at 120ms, new view fades in at 220ms (60ms delay).
- Falls through to instant swap where the API is missing or `prefers-reduced-motion: reduce` is set.

### Reduced Motion

A blanket `@media (prefers-reduced-motion: reduce)` rule crushes all animation and transition durations to 1ms, sets iteration-count to 1, and explicitly disables `breathe` and `sweep` animations.
This is applied globally to `*`, `*::before`, and `*::after`.

### Interaction Patterns

- **Card hover:** Elevation only (`--shadow-2`). No transform, no scale. The eye was using the grid to compare objects; moving one breaks the comparison.
- **Pin activation:** Scale-down on active (0.92), then `kept` keyframe on the SVG.
- **Title-action active:** Scale 0.92.
- **Menu open/close:** 140ms fade plus 4px translate. Focus trapped inside. Escape, outside click, or selection closes.
- **Pill wide mode:** 200ms ease transition on width and border-color.
- **Search focus:** Border colour transitions to `--accent` at 140ms, `--shadow-1` appears.
- **Editor save:** A 1px `--line-strong` rule fills left-to-right under the editor (620ms), then fades. The page acknowledging the words rather than a notification about them.

---

## Accessibility and Contrast

### Contrast Verification

The repo includes `bin/check-contrast`, a Python script that reads the `:root` palette from `museum.html` and verifies WCAG 2.1 contrast ratios.
It checks text-bearing tokens against three grounds (`--bg`, `--surface`, `--surface-2`) at 4.5:1, and `--line-strong` at 3:1.

Current results:

| Token | Hex | Worst ratio | Status |
| --- | --- | --- | --- |
| `--text` | `#23251d` | 12.44:1 | Pass |
| `--text-dim` | `#4d4f46` | 6.68:1 | Pass |
| `--text-mute` | `#63655b` | 4.75:1 | Pass |
| `--line-strong` | `#7d7b73` | 3.40:1 | Pass (3:1) |
| `--accent-ink` on `--accent` | `#23251d` on `#f7a501` | 7.64:1 | Pass |
| `--accent` | `#f7a501` | 1.63:1 | Fails 4.5:1 as text. Intentional: used as fill only, with 1.5px `--text` border for boundary. |
| `--accent-quiet` | `#dd9001` | 2.09:1 | Fails 4.5:1 as text. Intentional: pressed fill only. |
| `--green` | `#30804b` | 3.90:1 | Fails 4.5:1 as text. Intentional: 8px dot graphic, needs only 3:1. |
| `--peach` | `#ad5a31` | 3.93:1 | Fails 4.5:1 as text. Intentional: 8px dot graphic, needs only 3:1. |
| `--blue` | `#376899` | 4.67:1 | Pass |
| `--pink` | `#8f4273` | 5.27:1 | Pass |
| `--teal` | `#755c12` | 5.11:1 | Pass |

The script does not check `--surface-doc` (`#fcfcfa`) as a ground, though it is used for long-form reading surfaces.
This is an open question (see below).

### Structural Accessibility

- **Colour is never the sole carrier of information.** Kind is always a dot plus a text label. Disabled state is fill, opacity, cursor, and `aria-disabled` together. Drag-over state changes border colour and label text simultaneously.
- **Focus is visible everywhere.** `:focus-visible` applies `outline: 2px solid var(--focus); outline-offset: 2px;` on every focusable element. `:focus:not(:focus-visible)` removes the outline for mouse users.
- **Keyboard navigation.** Cards are `tabindex="0"` with `role="button"` and Enter/Space activation. Menu items support arrow keys, Home, End. Modal traps focus and returns it on close.
- **ARIA roles.** `role="dialog"`, `aria-modal="true"`, `aria-labelledby` on modals. `role="menu"`, `role="menuitem"` on the capture menu. `role="status"` on toasts. `role="button"` on cards. `role="textbox"` with `aria-multiline="true"` on the editor.
- **`color-scheme: light`** on `:root` ensures native scrollbars, carets, and select menus paint light even when macOS is set to dark.

---

## Do's and Don'ts

### Do

- Use `--bg` `#eeefe9` as the page canvas everywhere, including the top bar, the trash page, and the settings page.
- Set body copy at weight 450 (compensated with -0.08px tracking when the variable font is absent), and headlines at weight 500 with -2% letter-spacing.
- Reach for one of three radii by default: `--r` 20px for controls, `--r-lg` 40px for containers, `--r-full` for pills and circles.
- Put a leading accent dot before every eyebrow label (`.shelf::before`). It is the identity of the label, not a flourish.
- Keep to one primary action per view, and let it be the only saturated yellow-orange on screen.
- Give every filled `--accent` control a 1.5px `--text` border so its boundary clears 3:1.
- Express kind as an 8px dot plus a plain ink text label, always both together.
- Prefer a 1px `--line` border over a shadow. Reserve shadows for things that genuinely float.
- Use `--surface-doc` for anything read at length, and `--surface` for anything scanned.
- Keep the pastel tints to inline callouts only.
- Signal disabled state with fill, opacity, cursor, and `aria-disabled` together.
- State the destructive verb on the destructive button, and land initial focus on Cancel.
- Keep `color-scheme: light` on `:root`.
- Run `bin/check-contrast` after any palette change.

### Don't

- Don't write a dark theme, a `prefers-color-scheme: dark` block, or a theme toggle. There is one theme.
- Don't request a single byte over the network for fonts, stylesheets, or images. The app is local-only.
- Don't name MarkForMC in a font stack. It is proprietary.
- Don't set `--accent` as a text colour or as a lone border. It measures 1.63:1 on the darkest ground and fails both thresholds.
- Don't use `--line` `#bfc1b7` as the sole boundary of a control. It measures 1.58:1. Use `--line-strong`.
- Don't use `--text-mute` on a pastel tint, and don't lighten it past `#63655b`. It has 0.25 of headroom on `--surface-2`.
- Don't use any radius between 8px and 16px. That middle ground is what makes an interface look generic and it is deliberately absent from this system.
- Don't use hard drop shadows. Minimum 24px blur, maximum 10% opacity, no inset, no stacked layers.
- Don't let a kind colour become a card background, a card border, a title colour, or a filled badge. Kind is a fact, not an action.
- Don't let any colour be the only carrier of a piece of information.
- Don't mark selection with `--accent`. Selection lifts a row onto `--surface`; it does not shout.
- Don't add a second saturated colour. If something needs more emphasis, the answer is scale, weight, or whitespace.
- Don't use uppercase anywhere except the 14px eyebrow.
- Don't put a primary button on the artifact detail page or on the wall. Nothing in this app is urgent except capture.
- Don't scale or transform a card on hover. Elevation only.
- Don't add a second typeface, a serif accent, or a display face.
- Don't open a modal for a reversible action.

---

## Responsive Behavior

### Breakpoints

| Name | Width | Key Changes |
| --- | --- | --- |
| Wide | 1081px+ | Wall grid: 5 columns. Rail: `display: none`. |
| Desktop | 760-1080px | Wall grid: 4 columns. |
| Tablet | 460-760px | Wall grid: 3 columns, gap drops to `--sp-3` (12px). Horizontal rail gap drops to `--sp-3`. |
| Mobile | 460px | Wall grid: 1 column. `--sp-section` compresses to 24px. Docpane and group card padding compress to `--sp-4` (20px). |

### Touch Targets

All interactive elements meet or approach 44x44px.
Buttons are 40px minimum height with 24px horizontal padding, reaching 44px tappable via inline padding.
Icon-only buttons are 40x40.
The capture pill is 56px tall.
Menu items have 12px padding at 16px font size.

### Collapsing Strategy

- **Wall grid:** 5 to 4 to 3 to 1 columns at 1080px, 760px, and 460px breakpoints.
- **Section padding:** `--sp-section` compresses from 48px to 24px below 900px.
- **Docpane and settings group:** padding compresses from `--sp-6` (48px) to `--sp-4` (20px) below 900px.
- **Content padding:** horizontal padding compresses to `--sp-4` (20px) below 900px.

---

## Design Genealogy

This system combines two source languages.
Understanding where each value comes from prevents relitigating settled decisions.

### Colour comes from PostHog

The cream canvas (`#eeefe9`), the olive ink ladder (`#23251d` / `#4d4f46` / `#63655b`), the four-step surface ladder, the pastel callout family, and the single saturated yellow-orange (`#f7a501`) all come from PostHog's design system.
PostHog's `mute` value `#6c6e63` was darkened to `#63655b` because it fails 4.5:1 on `--surface-2`.
PostHog's `link-teal` and `accent-red` were darkened for the same reason.
PostHog's `ash` and `stone` values were dropped entirely because they fail badly.

### Form and typography come from Mastercard

The pill-and-stadium radius vocabulary (20px / 40px / 999px, skipping 8-16px), the weight 450 body, the -2% headline tracking, the dotted eyebrow label, the generous structural whitespace, and the wide low-opacity shadow philosophy all come from Mastercard's design system.
Mastercard's ink-black pill (`#141413`) survives as the secondary button.
Mastercard's Signal Orange is absent because Enqueue has no consent or legal flow to quarantine it for.

### Where they conflict

Four conflicts were resolved:

1. **Primary CTA colour.** PostHog's yellow vs Mastercard's ink-black. Resolved: PostHog yellow in Mastercard geometry. The brief takes colour from PostHog and form from Mastercard, and this button is where those two axes intersect.
2. **Border radius.** PostHog clusters at 4-6px; Mastercard uses 20/40/999. Resolved: Mastercard wins outright. PostHog's 6px survives only as `--r-sm` for sub-28px decoration.
3. **Elevation.** PostHog has no shadows; Mastercard uses soft halos. Resolved: flat with a hairline is the default; shadows only for floating chrome.
4. **Canvas tint and body weight.** PostHog's `#eeefe9` canvas with weight 400 vs Mastercard's `#F3F0EE` with weight 450. Resolved: PostHog canvas, Mastercard weight.

### Kind colours are facts, never actions

None of the five kind colours may ever be `--accent`, and `--accent` may never identify a kind.
Kind is a fact about a thing. The accent is an instruction.
If the two ever share a colour, the user cannot tell a category from a command.

### Previous design systems

The repo contains two earlier design references:

- `docs/design-before.html`: the "Atrium" museum-catalogue system (plaster, iron, bronze) with a dark mode and serif type. Superseded.
- `docs/design-target.html`: a dark charcoal theme with a lilac accent (`#c3b8ee`). Superseded.
- `src/enqueue/static/museum-plain.html` and `capture-plain.html`: stripped-down variants with no colour tokens, used as structural references. Not the shipping design.

---

## Notes on the current build

These are facts about the current code, recorded so a future change does not silently regress them.
The code is the source of truth; where an older spec disagreed, the code wins.

1. **`--sp-section` is 48px** in the code, compressing to 24px below 900px.
2. **The left rail is `display: none`** in the current build.
The CSS declares a 280px `.rail` (conversation list, search, new-chat button, Trash/Settings footer) but no rule shows it at any breakpoint.
The app shell currently has no left rail.
3. **Typography sizes are the code's values:** 32px display, 26px h1, 20px h2, 17px h3, 14px body.
The compact sizes reflect the desktop window size.
4. **The wall grid is fixed at 5 columns:** `repeat(5, minmax(0, 1fr))`, not auto-fill.
Column width varies with viewport; card count does not adapt.
5. **`--surface-doc` (`#fcfcfa`) is not checked by `bin/check-contrast`.**
The script checks three grounds (`--bg`, `--surface`, `--surface-2`) only.
If long-form reading text on `--surface-doc` matters, add it to the script.
6. **The variable woff2 is not loaded.**
`IBM-Plex-Sans-400.woff2` exists in the fonts directory but the HTML loads only static TTF cuts, so weight 450 rounds to 400.
The `-0.08px` letter-spacing compensation covers the gap.
7. **`--accent-strong: #b17816` is defined only in `capture.html`** for the drag-over border, not in `museum.html` or the shared token list.
The overlay owns this token locally.
8. **The capture overlay uses `--r-sm` (6px) for its card** while the main app uses `--r-lg` (40px).
The tight radius is because the overlay is a small floating window, not a page card.
9. **Settings nav rows use `border-bottom: 1px solid var(--line)`** with an explicit `border: none` reset, a slightly different pattern from the `.group` card's `--line-soft` internal dividers.
10. **The `.h3` role (17px / 500) appears unused** in the rendered HTML.
The card title overrides `.title` to 20px and the modal uses `.h2`.
