# Enqueue Design System

This document is the single source of truth for how the Enqueue interface looks.
An agent with no other context should be able to build the whole app from this file alone.
Values here are normative. If the code disagrees with this document, the code is wrong.

---

## 1. Philosophy

Enqueue is a place to put things you are not ready to decide about.
The interface should feel like a quiet, warm, well-lit room where nothing is urgent and nothing is lost.

Three sentences that govern every decision:

1. **The canvas is warm, never white, never dark.** Cream paper, olive ink. The app is a reading room, not a terminal.
2. **Everything is soft-cornered and generously spaced.** Pills, stadiums, and circles. Whitespace is structure, not leftover.
3. **There is exactly one loud colour, and it only ever means "do this now."** Yellow-orange is the primary action and nothing else. Anything a colour tells you that is not an action lives on a small dot, never on text.

The two systems this document combines:

- **Colour comes from PostHog.** The cream canvas, the olive ink ladder, the surface ladder, the pastel callout family, and the single saturated yellow-orange.
- **Form and typography come from Mastercard.** The pill and stadium radius language, one geometric sans at weight 450 body and -2% headline tracking, the dotted eyebrow label, generous structural whitespace, and wide low-opacity shadows instead of hard drops.

Nothing else gets to be a source.
If a value cannot be traced to one of those two systems or to a contrast requirement in section 3, it does not belong here.

---

## 2. Hard constraints

These are not preferences. Violating any of them is a bug.

- **Dark mode does not exist.** There is one theme: light and warm. Do not write a `prefers-color-scheme: dark` block. Do not add a theme toggle. Do keep `color-scheme: light` on `:root` so the browser paints native scrollbars, carets, and select menus light even when macOS is set to dark.
- **No network, ever.** No CDN fonts, no external stylesheets, no remote images, no analytics, no request to anything but `127.0.0.1`. The app is offline and local-only, and a single external request would be a privacy regression, not a styling detail.
- **Fonts must be vendored or system.** See section 5.1.
- **Contrast is verified, not assumed.** Every text colour reaches 4.5:1 against every ground it can sit on. Every colour that is the sole boundary of a control reaches 3:1. Measured numbers are in section 3.
- **Plain dashes only.** Never an em dash, in the UI or in this document.

---

## 3. Colour tokens

All ratios below were computed with the WCAG 2.1 relative-luminance formula.
The four grounds a foreground colour can sit on are `--bg`, `--surface`, `--surface-doc`, and `--surface-2`.
The darkest of those is `--surface-2` (`#e5e7e0`), so it is the binding case for every text colour.
All four are listed anyway so nothing has to be re-derived later.

### 3.1 Surfaces (the PostHog ladder)

| Token | Hex | Role |
|---|---|---|
| `--bg` | `#eeefe9` | Warm cream canvas. The page body, the left rail, the trash page, the settings page. Runs edge to edge. Never substitute white. |
| `--surface` | `#ffffff` | Raised card. Artifact cards, the answer bubble, settings group cards, the modal dialog, the capture menu. The dominant card surface. |
| `--surface-doc` | `#fcfcfa` | Warm reading white. Long-form surfaces: the artifact detail body, note text, extracted PDF text. Softer than `--surface` so a full page of it does not glare against the cream. |
| `--surface-2` | `#e5e7e0` | Recessed soft fill. Secondary fills, inline code chips, the search field at rest, a hovered rail row, disabled control fill. |

Surface rule: the ladder is **canvas -> raised (`--surface`) -> reading (`--surface-doc`)**, with `--surface-2` sideways off the canvas as a *recession*, not an elevation.
Never nest a `--surface-2` block inside a `--surface` card; use a hairline there instead.

### 3.2 Ink (text)

| Token | Hex | Role | vs `--bg` | vs `--surface` | vs `--surface-doc` | vs `--surface-2` |
|---|---|---|---|---|---|---|
| `--text` | `#23251d` | Headlines, artifact titles, button labels on light, question text, active nav. Olive-charcoal that reads near-black on cream. | 13.41 | 15.51 | 15.10 | 12.44 |
| `--text-dim` | `#4d4f46` | Default body copy. Answer text, note bodies, settings descriptions, card previews. The most-used text colour in the app. | 7.20 | 8.33 | 8.10 | 6.68 |
| `--text-mute` | `#63655b` | Metadata only: timestamps, kind labels, counts, capture source. | 5.13 | 5.93 | 5.77 | **4.75** |

All three pass 4.5:1 on all four grounds.
`--text-mute` is the tightest at 4.75 on `--surface-2` and has almost no headroom left. Do not lighten it.

> **Changed from source:** PostHog's `mute` is `#6c6e63`, which measures **4.16** on `--surface-2` and fails 4.5:1.
> It was darkened to `#63655b` (4.75 worst case). This is the only PostHog ink value altered.

Two PostHog ink values are deliberately **not** tokens here.
`ash` `#9b9c92` (2.40 on canvas) and `stone` `#b6b7af` (1.58) fail badly and have no legitimate use in this app.
Disabled text is `--text-mute` at 55% opacity plus `cursor: not-allowed` plus `aria-disabled`, because disabled state must be signalled by more than colour regardless.

### 3.3 The accent

| Token | Hex | Role |
|---|---|---|
| `--accent` | `#f7a501` | The one loud colour. Fill of the primary action only. |
| `--accent-quiet` | `#dd9001` | Pressed state of the primary action. |
| `--accent-ink` | `#23251d` | Text and icons on `--accent`. Measured **7.64:1** on `#f7a501`. |

**`--accent` is never text.**
It measures 1.76:1 on the cream canvas and 2.03:1 on white.
There is no ground in this app where yellow-orange text is legible.
If you want an emphasised word, set it in `--text` and put a yellow-orange element beside it.

**`--accent` is never a lone border.**
1.76:1 fails the 3:1 non-text requirement outright.

**The primary button is therefore always `--accent` fill plus a 1.5px `--text` border.**
The border, not the fill, satisfies the 3:1 boundary requirement, and it measures 13.41:1 against the canvas.
This is not an accessibility patch bolted on afterwards: Mastercard's primary pill specifies a 1.5px border in the same colour as its fill for exactly this crisp-edge reason, so the mechanism is native to the source system.

### 3.4 Lines

| Token | Hex | Role | Contrast |
|---|---|---|---|
| `--line` | `#bfc1b7` | Decorative hairline. Card borders, table rules, the rail divider, section rules. | 1.58 vs `--bg`, 1.82 vs `--surface`. **Decorative only.** |
| `--line-soft` | `#dcdfd2` | In-card divider between adjacent rows. | 1.17 vs `--bg`, 1.35 vs `--surface`. **Decorative only.** |
| `--line-strong` | `#7d7b73` | The sole boundary of a control: outlined button, text input, checkbox, select, toggle track. | **3.67** vs `--bg`, 4.24 vs `--surface`, 4.13 vs `--surface-doc`, **3.40** vs `--surface-2`. Clears 3:1 everywhere. |

Rule: if a line is the *only* thing telling the user where a clickable or typable region starts and ends, it must be `--line-strong`.
If the element also has a fill change or a visible label boundary, `--line` is fine.

### 3.5 Semantic colours

| Token | Hex | Role | Worst ground (`--surface-2`) |
|---|---|---|---|
| `--link` | `#0c6083` | Inline anchor in prose, source URL on a link artifact. | 5.58 |
| `--danger` | `#9e2a20` | Destructive text, and the fill of the destructive button. | 6.00 as text on `--surface-2`; `#ffffff` on `#9e2a20` measures 7.48. |

> **Changed from source:** PostHog's `link-teal` `#1078a3` measures **3.97** on `--surface-2` and fails; darkened to `#0c6083` (5.58).
> PostHog's `accent-red` `#cd4239` measures **3.80** and fails; darkened to `#9e2a20` (6.00).
> PostHog's `link-blue` `#1d4ed8` passes at 5.37 but is dropped anyway, because two link colours in a single-purpose app is one too many.

### 3.6 Pastel callout family (from PostHog)

Soft tinted panels carrying `--text`, used for inline notices only.

| Token | Hex | Meaning | `--text` on it | `--text-dim` on it |
|---|---|---|---|---|
| `--tint-info` | `#dceaf6` | Neutral information. "This has not been read yet." | 12.66 | 6.80 |
| `--tint-ok` | `#d9eddf` | Confirmation. "Restored to the wall." | 12.65 | 6.79 |
| `--tint-warn` | `#f7d6d3` | Caution and destructive framing. "Emptying trash is permanent." | 11.46 | 6.15 |
| `--tint-note` | `#e7d8ee` | Model and provenance annotation. "Read locally by Lumo." | 11.42 | 6.13 |

`--text-mute` is **not** permitted on any tint.
Callouts render at `--r` (20px), `--sp-4` inset, no border, no shadow.

### 3.7 Kind colours

Five hues identify what an artifact *is*.
Section 6.5 gives the rendering rule; this section gives the values and the evidence.

| Token | Alias | Hex | vs `--bg` | vs `--surface` | vs `--surface-doc` | vs `--surface-2` |
|---|---|---|---|---|---|---|
| `--green` | `--kind-note` | `#30804b` | 4.21 | 4.87 | 4.74 | **3.90** |
| `--blue` | `--kind-link` | `#376899` | 5.04 | 5.83 | 5.67 | 4.67 |
| `--peach` | `--kind-pdf` | `#ad5a31` | 4.24 | 4.90 | 4.77 | **3.93** |
| `--pink` | `--kind-image` | `#8f4273` | 5.68 | 6.57 | 6.40 | 5.27 |
| `--teal` | `--kind-file` | `#755c12` | 5.51 | 6.37 | 6.20 | 5.11 |

All five clear **3:1** on every ground. The worst is `--green` at 3.90.

Two of them (`--green`, `--peach`) do **not** clear 4.5:1 on `--surface-2`, and that is correct, because of the rule in 6.5: kind is an 8px dot beside a plain ink label.
The dot is a graphic and answers to 3:1. The label carries the meaning and answers to 4.5:1 in `--text-dim`.

This is a deliberate move, not a concession.
Forcing five hues to clear 4.5:1 on a light canvas confines all of them below 0.132 relative luminance, at which point they separate by roughly 2.5% and green and teal are indistinguishable to normal vision before colour vision deficiency is even considered.
Freeing them to be graphics widens the usable band to 0.223 and lets them separate by hue instead of by lightness.

Measured separation between the five, worst pair, CIE ΔE76, with Viénot colour vision simulation:

| Vision | Worst pair | ΔE76 |
|---|---|---|
| Normal | pdf / file | 29.2 |
| Deuteranopia | pdf / file | 10.9 |
| Protanopia | note / pdf | 8.3 |

Two naming legacies are kept so the token names map cleanly onto the existing implementation:

- `--teal` holds an olive-gold `#755c12`, not a teal. An actual teal collapses into `--green` under deuteranopia; this gold does not. The name is wrong and the value is right. Do not "fix" the value to match the name.
- `--peach` holds a burnt terracotta, not a peach.

`--teal` `#755c12` and `--accent` `#f7a501` are both in the yellow family and measure 3.14:1 against each other.
They never occupy the same role: `--accent` is only ever a filled action, `--teal` is only ever an 8px dot beside a text label.
Do not place them adjacent.

### 3.8 Focus

| Token | Value | Role |
|---|---|---|
| `--focus` | `#23251d` | Focus ring colour. |

Focus ring: `outline: 2px solid var(--focus); outline-offset: 2px;` on every focusable element, via `:focus-visible`.
Measures 13.41:1 on the canvas and 12.44 on the softest surface.
Do not use a translucent blue browser-default ring. Do not remove outlines.

### 3.9 Scrim

| Token | Value | Role |
|---|---|---|
| `--scrim` | `rgba(35, 37, 29, 0.32)` | Behind the modal dialog. Tinted with `--text` rather than black, so it warms the cream rather than greying it. |

---

## 4. Spacing, radii, shadows

### 4.1 Spacing

Base unit 4px, structural rhythm on 8.
Mastercard's generosity applies to the *structure*; the artifact wall itself stays dense, because it is a working surface.

| Token | Value | Use |
|---|---|---|
| `--sp-1` | `4px` | Icon-to-label gap, dot-to-label gap. |
| `--sp-2` | `8px` | Chip inset, tight list gaps. |
| `--sp-3` | `12px` | Control inner padding, rail row vertical padding. |
| `--sp-4` | `20px` | Card inner padding, standard block gap. |
| `--sp-5` | `32px` | Card grid gutters, page gutters, gaps between groups. |
| `--sp-6` | `48px` | Gap between major regions inside a page. |
| `--sp-section` | `96px` | Top padding of a page region, and the gap between top-level sections on the settings page. Compresses to `48px` below 900px viewport width. |

Never invent a spacing value.
If nothing on the scale fits, the layout is wrong.

### 4.2 Radii

This is Mastercard's scale and it is the most load-bearing gesture in the system.
It deliberately **skips the 8px to 16px middle ground**, which is what makes the UI read as either precise-and-small or soft-and-editorial, with nothing generic in between.

| Token | Value | Use |
|---|---|---|
| `--r-sm` | `6px` | Tiny decorative elements only: inline code chips, keyboard-shortcut glyphs, the square kind-marker variant. Nothing interactive, nothing larger than about 28px. |
| `--r` | `20px` | The signature control radius. Buttons, text inputs, select, callout panels, chat bubbles, rail rows, menu items. |
| `--r-lg` | `40px` | Large containers. Artifact cards, the artifact detail pane, the modal dialog, the settings group card, the capture menu, the composer field. |
| `--r-full` | `999px` | Full pill and circle. The floating capture pill, filter chips, kind dots, the search field, icon-only buttons, the "Empty trash" pill. |

**There is no 8px, 10px, 12px, or 16px radius anywhere in this app.**
If you find one, it is drift and it should be removed.

### 4.3 Shadows

Mastercard's atmospheric cushioning: wide spread, very low opacity, no directional light.
Tinted with `--text` rather than pure black so the halo stays warm on cream.

| Token | Value | Use |
|---|---|---|
| `--shadow-1` | `0 4px 24px rgba(35, 37, 29, 0.05)` | Barely-there lift. Sticky headers, the search field on focus. |
| `--shadow-2` | `0 24px 48px rgba(35, 37, 29, 0.08)` | The floating capture pill at rest, the capture menu, a hovered artifact card. |
| `--shadow-3` | `0 40px 96px rgba(35, 37, 29, 0.10)` | The modal dialog only. |

Rules: minimum 24px blur, maximum 10% opacity, no `inset` shadows, no stacked second shadow, no shadow on anything that already has a `--line` border unless it genuinely floats over other content.
**About 95% of surfaces have no shadow at all** and sit flat on the cream with a hairline.
Reach for a border before a shadow.

---

## 5. Typography

One geometric sans across the entire app.
No serif accent, no display face, no second family.

### 5.1 Font, and how to ship it offline

**Recommendation: self-host IBM Plex Sans from `src/enqueue/static/fonts/`.**
It is the PostHog face, it is open-source under the SIL Open Font License, and its variable cut supports the weight 450 that Mastercard's type system depends on.

Choosing this means **the woff2 files must be vendored into the repository** at `src/enqueue/static/fonts/`.
Do not link Google Fonts. Do not link any CDN. Do not use `@import url(...)`.
Vendor one file, or two if italics are actually used, and declare them locally:

```css
@font-face {
  font-family: "IBM Plex Sans Var";
  src: url("fonts/IBMPlexSansVar-Roman.woff2") format("woff2-variations");
  font-weight: 100 700;
  font-style: normal;
  font-display: swap;
}
```

Stacks:

```css
--sans: "IBM Plex Sans Var", "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
--mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
```

If the woff2 files are not vendored, **do not fall back to a webfont link**.
Ship the same stack, let it resolve to `system-ui`, and accept that weight 450 rounds to 400 (see 5.2 for the compensation).

`--mono` is deliberately system-only.
Monospace here is information (hashes, paths, byte sizes), never decoration, and it is not worth a second font file.
Do not name JetBrains Mono or Source Code Pro in the stack unless those files are also vendored.

**MarkForMC is proprietary and must never appear in a font stack**, not even as an unreachable first entry.

### 5.2 The two properties that are the identity

- **Body copy is weight 450.** Not 400. It reads softer than regular without going thin, and it is the single most identifying property of the type system. With the variable font this works directly. With the `system-ui` fallback it rounds to 400; in that case tighten body letter-spacing by `-0.08px` to compensate for the extra apparent looseness.
- **Headlines carry -2% letter-spacing.** Every role at 20px and above. In px that is `size * -0.02`. The words lock together rather than breathe, which is what gives display type its editorial density.
- **Line-height ratio drops as size rises.** Display near 1.05, headings 1.2 to 1.3, body 1.4 to 1.5. Tight display, comfortable reading.

### 5.3 Scale

| Role | Size | Weight | Line height | Letter spacing | Transform | Use |
|---|---|---|---|---|---|---|
| `display` | 40px | 500 | 42px (1.05) | -0.80px (-2%) | none | The line on an empty wall, first-run copy. At most one per view. |
| `h1` | 32px | 500 | 38px (1.19) | -0.64px (-2%) | none | Artifact detail title, settings page title. |
| `h2` | 24px | 500 | 29px (1.20) | -0.48px (-2%) | none | Trash page title, settings section title, modal title, conversation title. |
| `h3` | 20px | 500 | 26px (1.30) | -0.40px (-2%) | none | Artifact card title, settings group title. |
| `eyebrow` | 14px | 700 | 14px (1.0) | +0.56px (+4%) | uppercase | Section category label. **Always preceded by a leading accent dot** (6.5 and 8). |
| `body` | 16px | 450 | 22.4px (1.40) | 0 | none | Default paragraph. Answer text, note bodies, settings descriptions. |
| `body-strong` | 16px | 600 | 22.4px (1.40) | 0 | none | Inline emphasis, selected rail row, question text. |
| `body-sm` | 15px | 450 | 22px (1.47) | 0 | none | Card preview, secondary prose, list second line. |
| `label` | 14px | 500 | 20px (1.43) | 0 | none | Form field label, kind label beside a dot, rail row label. |
| `button` | 16px | 500 | 16px (1.0) | -0.48px (-3%) | none | Every button label and nav link. Tight and compact, never uppercase. |
| `button-sm` | 14px | 500 | 14px (1.0) | -0.42px (-3%) | none | Chip and compact CTA label. |
| `meta` | 13px | 500 | 18px (1.38) | 0 | none | Timestamp, count, byte size, capture source. Always `--text-mute`. |
| `code` | 14px | 400 | 20px (1.43) | 0 | none | `--mono`. Inline chips and code blocks. |

**Uppercase appears in exactly one role: `eyebrow`.**
Nowhere else, at no size, for no reason.
No shouty section titles, no uppercase buttons, no uppercase nav.

---

## 6. Where the two systems conflict, and how it is resolved

The sources disagree in four places, plus one rule that keeps the first resolution honest.
Each is settled here with a reason. Do not relitigate them in code.

### 6.1 The primary CTA colour. RESOLVED: PostHog yellow, in Mastercard geometry.

**The conflict.**
PostHog's primary CTA is a saturated yellow-orange `#f7a501` pill, and that yellow is the entire brand.
Mastercard's primary CTA is an Ink Black `#141413` pill at 20px radius, and its Signal Orange `#CF4500` is reserved strictly for consent, legal, and compliance actions, on the explicit grounds that using it for marketing would dilute a legal signal.
These are directly incompatible: one system's primary colour is the other system's forbidden colour.

**The decision.**
**PostHog's yellow-orange `--accent` carries the primary action, rendered in Mastercard's pill geometry and type.**
Concretely: `#f7a501` fill, `--accent-ink` label, `--r` (20px) radius, 1.5px `--text` border, `6px 24px` padding, label at `button` type (16px / weight 500 / -0.48px).

**Why.**

1. The brief takes colour from PostHog and form from Mastercard. This button is the single most visible place those two axes intersect. Resolving it any other way makes the whole combination incoherent, because the accent would then come from neither system.
2. Mastercard's reason for quarantining its orange does not transfer. That reservation exists because Mastercard runs cookie-consent and privacy flows where a legal signal must stay unambiguous. Enqueue has no consent flow, no legal action, and no third-party surface. It is local-only software with nothing to consent to. The constraint has no referent here.
3. An ink-black pill on cream would make the app's most important control indistinguishable from the app's text colour. The wall of artifacts is already almost entirely olive-on-cream. A black pill would disappear into it. The yellow is the only thing in the system that says "act."

**The cost, accepted.**
The yellow pill on cream is 1.76:1 as a shape, so the 1.5px `--text` border in 3.3 is mandatory rather than decorative.
That border is Mastercard's own primary-pill spec, so no new mechanism is invented to pay this cost.

**Consequence.**
Mastercard's ink-black pill survives, demoted to the *secondary* action, and its outlined white variant becomes the tertiary. See 7.2.

### 6.2 Border radius. RESOLVED: Mastercard, entirely.

**The conflict.**
PostHog clusters at 4px and 6px, with 8px for rare large containers, and calls the 4-6px band its card vocabulary.
Mastercard uses 20 / 40 / 999 and deliberately avoids everything between 8 and 16.

**The decision.**
Mastercard's scale wins outright, per the brief's split.
PostHog's 4-6px band survives only as `--r-sm` (6px) for inline code chips and similar sub-28px decoration.
PostHog cards at 6px radius do not exist in this app. Artifact cards are 40px.

**Why.**
Radius is the most immediately legible property of a form language, and the brief assigns form to Mastercard.
A 40px artifact card is a fundamentally different object from a 6px one, and that difference is the entire point of the combination.

### 6.3 Elevation. RESOLVED: split by function, not by source.

**The conflict.**
PostHog has essentially no shadows; cards sit flat on cream with thin olive borders, and its documentation says so explicitly.
Mastercard uses soft wide halos as atmospheric cushioning.

**The decision.**
**Flat, with a 1px `--line` hairline, is the default for anything in the document flow.**
Mastercard's wide low-opacity shadow is used only for things that genuinely float above other content: the capture pill, the capture menu, the modal, and the hover state of an artifact card.

**Why.**
These two are not really answering the same question.
PostHog is describing static page content, which this app has a great deal of.
Mastercard is describing floating chrome, which this app also has.
Shadows everywhere would make the wall look like a pile of receipts.
Shadows nowhere would leave the floating capture pill with no way to say it is floating.

### 6.4 Canvas tint and body weight. RESOLVED: PostHog canvas, Mastercard weight.

**The conflict.**
PostHog's canvas is `#eeefe9`, a greenish cream, with body at weight 400.
Mastercard's is `#F3F0EE`, a pinkish putty, with body at weight 450.

**The decision.**
Canvas is PostHog's `#eeefe9`. Body weight is Mastercard's 450.

**Why.**
A straight application of the brief's split: colour is PostHog's axis, type is Mastercard's.
The olive cast of `#eeefe9` is also what makes the olive ink ladder read as intentional rather than as grey text on beige, and the ink ladder is the part of PostHog's colour system doing the most work here.

### 6.5 Kind colours are facts, never actions.

Not a conflict between sources, but the rule that keeps 6.1 honest, stated here so it cannot be missed.

**None of the five kind colours may ever be `--accent`, and `--accent` may never identify a kind.**
Kind is a fact about a thing. The accent is an instruction.
If the two ever share a colour, the user cannot tell a category from a command.

**Rendering rule.**
Kind is always an **8px circle at `--r-full` filled with the kind colour, then `--sp-1`, then the kind name as plain text in `label` type at `--text-dim`.**

- The dot is a graphic. It answers to 3:1 and all five clear it (3.7).
- The label carries the meaning. It answers to 4.5:1 and it is ink, so it does.
- Colour is therefore never the sole carrier of information, which satisfies WCAG 1.4.1 structurally rather than by a note in a doc.

Prohibited: kind colour as a card background, as a card border, as a title colour, as a filled badge, as a full-bleed strip.
A tinted background derived from a kind colour is prohibited even at low opacity.

---

## 7. Component specifications

### 7.1 App shell

Two columns, full viewport height, no page scroll on the shell itself.

- Body background `--bg`, `color-scheme: light`.
- Left rail: fixed `280px` wide, background `--bg`, right border 1px `--line`, its own scroll region. Below 900px viewport width it collapses behind a `--r-full` icon button in the content header and slides in as an overlay over `--scrim`.
- Content column: fills the rest, its own scroll region, horizontal padding `--sp-5`, top padding `--sp-section`.
- Max content width `1200px`, centred; gutters grow symmetrically past that.

### 7.2 Buttons

All buttons: `--r` (20px) radius, `button` type, `6px 24px` padding, minimum height `40px`, minimum tap target `44px` reached with transparent inline padding where the visible height is smaller.

| Variant | Fill | Label | Border | Use |
|---|---|---|---|---|
| Primary | `--accent` | `--accent-ink` (7.64) | 1.5px `--text` (13.41 vs canvas) | The one urgent action in a view. Pressed: fill `--accent-quiet`, no size change, no shadow. |
| Secondary | `--text` | `--bg` (13.41, not pure white) | 1.5px `--text` | Mastercard's ink pill, demoted. "Cancel" beside a destructive primary, "Open original", "Save". |
| Tertiary | `--surface` | `--text` | 1.5px `--line-strong` (3.67) | Low-emphasis but still bounded. The border is the sole boundary, hence `--line-strong`. |
| Ghost | none | `--text` | none, padding `6px 12px` | Lowest emphasis. "Show more", "Restore", non-destructive "Cancel". |
| Destructive | `--danger` | `#ffffff` (7.48) | 1.5px `--danger` | Only in a confirmation modal or on the trash page. Never on the wall. |
| Icon-only | `--surface-2` | icon in `--text` | none, `--r-full`, 40px diameter | The fill change is the boundary, so `--line-strong` is not required. |
| Disabled | `--surface-2` | `--text-mute` at 55% | none | Plus `cursor: not-allowed` and `aria-disabled="true"`. Never colour alone. |

One primary per view.
If a view seems to need two, one of them is a secondary.

### 7.3 Left rail with conversation list

- Header: the wordmark in `h3` at `--text`, then `--sp-4`.
- A "New conversation" **primary** button at full rail width minus `--sp-4` gutters. This is the rail's only accent.
- Search field: `--r-full`, fill `--surface-2`, 1.5px `--line-strong`, `12px 16px` padding, magnifier glyph at the left in `--text-mute`, placeholder in `--text-mute`. On focus: fill `--surface`, `--shadow-1`, focus ring per 3.8.
- An `eyebrow` reading "• CONVERSATIONS": dot filled `--accent`, text `--text-mute`. `--sp-5` above, `--sp-2` below.
- Rows: `--r` (20px), `12px 16px` padding, `2px` vertical gap.
  - Rest: transparent fill, title in `body-sm` at `--text-dim`, second line in `meta` at `--text-mute` giving relative time and artifact count.
  - Hover: fill `--surface-2`.
  - Selected: fill `--surface`, 1px `--line`, title becomes `body-strong` at `--text`. The row lifts off the cream, which is PostHog's tab-selection gesture.
  - **Never mark selection with `--accent`.** Selection is a state, not an action.
- Rail footer, pinned to the bottom above a 1px `--line` rule: two ghost rows, "Trash" and "Settings", in `label` at `--text-dim`.

### 7.4 The wall (square artifact cards)

The default view. A wall of square cards on cream.

- Grid: `repeat(auto-fill, minmax(240px, 1fr))`, gutter `--sp-5` (32px), `aspect-ratio: 1 / 1` on every card.
- Column count follows from `auto-fill`: roughly 4-up at 1200px, 3-up at 1024px, 2-up at 768px, 1-up at 480px. Gutter drops to `--sp-4` below 768px.

**Card.**

- Container: fill `--surface`, 1px `--line`, `--r-lg` (40px), `--sp-4` inset, no shadow at rest.
- Because the radius is 40px on a roughly 240px square, keep all content inside a 24px inset from the card edge or it will visually collide with the corner curve.
- Top row: kind dot and label per 6.5, left aligned.
- Title: `h3` at `--text`, clamped to 3 lines.
- Preview: `body-sm` at `--text-dim`, clamped to 3 lines, filling the middle.
- Bottom row, pinned: `meta` at `--text-mute` with relative capture time on the left, and an unread marker on the right when the AI has not read the artifact yet. The unread marker is a 6px `--accent` dot with an `aria-label`, and it is the only `--accent` on the wall.
- Hover: `--shadow-2`, border unchanged, **no transform and no scale**. Transition `box-shadow 160ms ease`.
- Focus: ring per 3.8.
- Image artifacts: thumbnail fills the card with `object-fit: cover` and `overflow: hidden` so it inherits `--r-lg`, with a bottom band carrying the title. The band is `--surface` at 92% opacity with `backdrop-filter: blur(8px)`, never a gradient.

**Empty wall.**
Centred, `--sp-section` from the top: a `display` line ("Nothing here yet"), then `body` at `--text-dim` explaining that anything dropped on the capture pill is kept and read locally.
No illustration, no accent button. The capture pill is already on screen and is the call to action.

### 7.5 Artifact detail page

Single column, replaces the wall in the content column.

- Back control: ghost button with a left-arrow glyph, top left.
- Header block, `--sp-6` bottom margin:
  - Kind dot and label per 6.5.
  - Title in `h1`.
  - `meta` row at `--text-mute`: captured time, byte size, source, separated by a `•` in `--line-strong`.
- Actions row: **secondary** "Open original", tertiary "Copy", ghost "Move to trash". No primary action on this page. Nothing you can do to an artifact is urgent.
- Body pane: fill `--surface-doc`, 1px `--line`, `--r-lg` (40px), padding `--sp-6`, `max-width: 720px`.
  - Text artifacts: `body` at `--text-dim` with `--sp-4` paragraph gaps.
  - Images: `max-width: 100%`, `--r` radius, centred on `--surface-doc`.
  - PDFs: extracted text in the same body treatment, preceded by a `--tint-info` callout naming the page count.
  - Paths, hashes, sizes: `--mono` at `code`, chips filled `--surface-2` at `--r-sm`.
- "What the AI made of this" block, `--sp-6` below the body pane: a `--tint-note` callout at `--r` with `--sp-4` inset, containing an `eyebrow` reading "• READ LOCALLY" with an `--accent` dot, then the model's summary in `body` at `--text-dim`.
  This block is how the app keeps its central promise visible. Do not hide it behind a disclosure.

### 7.6 Chat transcript

Question right, answer left. Transcript `max-width: 760px`, centred.

**Question (user, right).**

- Right aligned, `max-width: 78%`.
- Fill `--surface-2`, no border, `--r` (20px) with the bottom-right corner at `--r-sm` (6px) to point at the sender.
- Text: `body-strong` at `--text` (12.44 on `--surface-2`).
- Padding `--sp-3 --sp-4`.

**Answer (assistant, left).**

- Left aligned, `max-width: 88%`.
- Fill `--surface`, 1px `--line`, `--r` (20px) with the bottom-left corner at `--r-sm`.
- Text: `body` at `--text-dim`.
- Padding `--sp-4`.
- Cited artifacts appear at the bottom of the bubble as a chip row: `--r-full`, fill `--surface-2`, 1px `--line`, `--sp-2` inset, kind dot plus `button-sm` label at `--text`. Selecting one opens the artifact detail page.

**Rhythm.**
`--sp-5` between turns, `--sp-3` between consecutive bubbles on the same side.
No avatars, no name labels, no in-flow timestamps. Side and corner shape carry the speaker.

**Composer.**
Pinned to the bottom of the content column, background `--bg`, 1px `--line` top rule, `--sp-4` padding.
Field: `--r-lg` (40px), fill `--surface`, 1.5px `--line-strong`, `--sp-3 --sp-4` padding, `body` at `--text`, auto-growing to 6 lines then scrolling.
Send: primary icon-only button at `--r-full`, 40px, inside the field's right edge with `--sp-2` clearance.

**Streaming.**
A 3px `--accent` bar animating left to right across the top edge of the answer bubble.
No spinner, no bouncing dots.

### 7.7 Trash page

- Header: `h2` "Trash", then `body` at `--text-dim` stating the retention rule in plain words.
- Directly beneath: a `--tint-warn` callout at `--r` with `--sp-4` inset, text `--text`: "Emptying the trash deletes these files from this machine. It cannot be undone."
- Items render as a **list, not the wall grid**, because a wall implies keeping and this page is about not keeping.
  Rows: `--r` radius, fill `--surface`, 1px `--line`, `--sp-3 --sp-4` padding, `--sp-2` gap. Each row: kind dot and label, title in `body-strong` at `--text`, `meta` deletion date right aligned, ghost "Restore".
- Page actions, top right of the header: ghost "Restore all", and a **destructive pill** "Empty trash" at `--r-full`.
  Full-pill radius is the only place trash departs from the app's 20px button radius, and it is intentional: the shape itself flags the action as terminal. It opens the modal in 7.10.
- Empty state: `body` at `--text-mute`, "Nothing in the trash." No illustration.

### 7.8 Settings page

- Page title in `h1`, `--sp-section` top padding.
- Sections separated by `--sp-section`, each opened by an `eyebrow` with an `--accent` dot, for example "• PRIVACY".
- Group card: fill `--surface`, 1px `--line`, `--r-lg` (40px), `--sp-6` inset. Rows inside are separated by 1px `--line-soft` full-bleed rules with `--sp-4` above and below.
- Row layout: label in `body-strong` at `--text`, description beneath in `body-sm` at `--text-dim`, control right aligned and vertically centred.
- **Toggle:** track 44x26px at `--r-full`. Off: fill `--surface-2`, 1.5px `--line-strong`, knob `--surface` with a 1px `--line` ring. On: fill `--accent`, 1.5px `--text`, knob `--surface`.
  The toggle is the one non-button control permitted to use `--accent`, because its on-state is a live instruction to the software rather than a category.
- **Select:** `--r`, fill `--surface`, 1.5px `--line-strong`, `body` at `--text`, chevron in `--text-mute`.
- **Text input:** `--r`, fill `--surface`, 1.5px `--line-strong`, `--sp-3 --sp-4` padding, `body` at `--text`, placeholder `--text-mute`.
- A "Local only" section is mandatory and comes first: a `--tint-note` callout at `--r` stating in `body` that no data leaves the machine and that the app binds to `127.0.0.1`, followed by rows showing the model in use and the storage path in `--mono` at `code`.
- Destructive settings ("Delete all artifacts") live in a final section under a `--tint-warn` callout with a destructive button, and always open the modal in 7.10.

### 7.9 Floating capture pill and its menu

The app's signature object. Present on every page.

**Pill.**

- `position: fixed`, horizontally centred, `--sp-5` from the viewport bottom, above content and below the modal.
- Shape `--r-full`, height `56px`, padding `0 --sp-4`, fill `--surface`, 1px `--line`, `--shadow-2`.
- Content: a plus glyph inside a 32px `--accent` circle at the left with `--accent-ink` stroke, then "Keep something" in `button` at `--text`, then a chevron in `--text-mute`.
- Drag-over state: pill widens to `min(560px, 90vw)`, border becomes 1.5px `--accent`, label changes to "Drop to keep". Transition `200ms ease` on width and border-color.
  Because 1.5px `--accent` at 1.76:1 cannot be a sole indicator, the label text changes at the same moment. The colour is reinforcement, never the signal.
- Active drop: fill `--tint-ok`, label `--text`.

**Menu.** Opens upward on click.

- Fill `--surface`, 1px `--line`, `--r-lg` (40px), `--shadow-2`, `--sp-2` inset, width `280px`, anchored `--sp-2` above the pill and centred on it.
- Items: `--r` (20px) rows, `--sp-3` padding, 20px glyph in `--text-mute`, then `body` label at `--text`, then a `meta` keyboard hint at `--text-mute`, right aligned.
- Items are: "Paste from clipboard", "Choose a file", "Write a note", "Save a link".
- Hover and keyboard focus: fill `--surface-2`. **Never `--accent`.** These are four equal-weight choices and none of them is the primary.
- Opens with a `140ms` fade plus 4px upward translate. Closes on Escape, outside click, or selection. Focus returns to the pill.

### 7.10 Modal confirmation dialog

Used for anything irreversible, and only for that.

- Scrim: full viewport, `--scrim`, fading in over `160ms`.
- Dialog: fill `--surface`, `--r-lg` (40px), `--shadow-3`, no border, `--sp-6` inset, `max-width: 480px`, centred, entering with a `160ms` fade plus 8px upward translate.
- Content order: `h2` title stating the action in plain words ("Empty the trash?"), `--sp-3`, `body` at `--text-dim` stating exactly what happens and that it cannot be undone, `--sp-6`, action row.
- Action row: right aligned, `--sp-3` gap. The **destructive button sits on the right**, with a **secondary "Cancel"** to its left.
- The destructive button repeats the verb ("Empty trash"). Never "OK", never "Yes".
- Focus is trapped inside the dialog. Initial focus lands on **Cancel**, never on the destructive action. Escape cancels.
- `role="dialog"`, `aria-modal="true"`, `aria-labelledby` pointing at the title.
- Never open a modal for a reversible action. Confirmation friction with no payoff is just friction.

---

## 8. Do and Don't

### Do

- Use `--bg` `#eeefe9` as the page canvas everywhere, including the rail, the trash page, and the settings page.
- Set body copy at weight **450**, and headlines at weight 500 with **-2%** letter-spacing.
- Reach for one of three radii by default: `--r` 20px for controls, `--r-lg` 40px for containers, `--r-full` for pills and circles.
- Put a leading accent dot before every eyebrow label. It is the identity of the label, not a flourish.
- Keep to **one primary action per view**, and let it be the only saturated yellow-orange on screen.
- Give every filled `--accent` control a 1.5px `--text` border so its boundary clears 3:1.
- Express kind as an 8px dot plus a plain ink text label, always both together.
- Prefer a 1px `--line` border over a shadow. Reserve shadows for things that genuinely float.
- Use `--surface-doc` for anything read at length, and `--surface` for anything scanned.
- Keep the pastel tints to inline callouts: `--tint-info` for information, `--tint-ok` for confirmation, `--tint-warn` for caution, `--tint-note` for model provenance.
- Signal disabled state with fill, opacity, cursor, and `aria-disabled` together.
- State the destructive verb on the destructive button, and land initial focus on Cancel.
- Keep `color-scheme: light` on `:root`.

### Don't

- Don't write a dark theme, a `prefers-color-scheme: dark` block, or a theme toggle. There is one theme.
- Don't request a single byte over the network. No CDN fonts, no external stylesheets, no remote images.
- Don't name MarkForMC in a font stack. It is proprietary.
- Don't set `--accent` as a text colour or as a lone border. It measures 1.76:1 on the canvas and fails both thresholds.
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

## 9. What changed and why

This replaces the previous `docs/DESIGN.md` (the "Atrium" museum-catalogue system: plaster, iron, and bronze) and corrects the drift that accumulated in `src/enqueue/static/museum.html`.
The museum metaphor produced a palette belonging to neither source system and a radius scale that landed squarely in the generic band.

| Was | Now | Why |
|---|---|---|
| `--accent: #8c5b16` | `--accent: #f7a501`, `--accent-quiet: #dd9001`, `--accent-ink: #23251d` | The old value is a muddy brown belonging to neither source system. It got there by being darkened until it passed 4.5:1 as *text*, which solves the wrong problem: the accent is a fill, not a text colour, and darkening it to text legibility destroyed the one thing it existed for. The correct fix is PostHog's actual yellow plus a 1.5px ink border that carries the 3:1 boundary requirement, which is Mastercard's own primary-pill construction. |
| `--bg: #f5f4ee`, `--surface: #efede6`, `--surface-2: #e6e3da` | `--bg: #eeefe9`, `--surface: #ffffff`, `--surface-2: #e5e7e0`, plus new `--surface-doc: #fcfcfa` | The old ladder was three shades of one beige with no raised surface at all, so cards never separated from the canvas. PostHog's four-step ladder gives a true canvas, a true raised white, a warm reading white, and a recessed soft fill. |
| `--text: #1c1d18`, `--text-dim: #4a4b44`, `--text-mute: #5e5f57` | `#23251d`, `#4d4f46`, `#63655b` | Adopts PostHog's olive-charcoal ink ladder directly, with `mute` darkened from PostHog's own `#6c6e63` because that value measures 4.16 on `--surface-2` and fails 4.5:1. |
| `--line-strong: #7d7b73` used loosely | Same value, now specified as the only legal sole-boundary colour, with `--line-soft: #dcdfd2` added | `--line-strong` measures 3.40 at worst and is the only line token clearing 3:1. `--line` at 1.58 was being used on inputs, which failed. |
| `--r-sm: 6px`, `--r: 10px`, `--r-lg: 20px` | `--r-sm: 6px`, `--r: 20px`, `--r-lg: 40px`, `--r-full` unchanged | The 10px radius sat inside the 8-16px band Mastercard deliberately skips, which is exactly why the old UI read as generic. Every control moves to 20px, every container to 40px. |
| `--sp-6: 44px`, no section token | `--sp-6: 48px`, new `--sp-section: 96px` | 48 is on the 8-grid; 44 was not. The section token supplies the structural whitespace Mastercard's layout depends on, which the old scale had no way to express. |
| `--shadow-1` alone, tight | Three-step wide-halo ladder tinted with `--text`: `--shadow-1/2/3` | Mastercard's atmospheric cushioning: 24px+ blur at 8% opacity or less. Tight shadows were making floating chrome look pasted on. |
| System sans, body weight 400 | IBM Plex Sans, self-hosted from vendored woff2 in `src/enqueue/static/fonts/`, body weight **450**, -2% headline tracking | Weight 450 is the load-bearing identity of Mastercard's type system and is unreachable without a variable font. Vendoring is mandatory because the app makes no network requests. If the files are not vendored, the stack resolves to `system-ui` and 450 rounds to 400, compensated with -0.08px body tracking. |
| No eyebrow role, no accent dot | `eyebrow` at 14px / 700 / +4% uppercase with a mandatory leading accent dot | The dotted eyebrow is Mastercard's section-category signal and the previous system had no equivalent, which is why sections had no consistent opening gesture. |
| Kind colours present but the rule only lived in a code comment | Same five values, rule promoted to normative spec (6.5) | `--green` `#30804b`, `--blue` `#376899`, `--peach` `#ad5a31`, `--pink` `#8f4273`, `--teal` `#755c12` were already tuned for hue separation under colour vision deficiency and all five clear 3:1 on all four grounds. Values kept; the dot-plus-ink-label rendering that justifies the 3:1 threshold is now written down, along with the measured ΔE76 separation figures. |
| No link or danger colour | `--link: #0c6083`, `--danger: #9e2a20` | PostHog's `#1078a3` (3.97) and `#cd4239` (3.80) both fail 4.5:1 on `--surface-2` and were darkened until they passed. |
| No pastel family | `--tint-info`, `--tint-ok`, `--tint-warn`, `--tint-note` | PostHog's callout family, brought across for inline notices, which the app previously had no vocabulary for and was faking with bare text. |
