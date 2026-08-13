# Enqueue Design System

A light, trustworthy surface with a quiet lavender accent.

The system takes Kraken's clean, professional, white-canvas calm and restrains it with Linear's muted-lavender discipline.
Kraken's purple scale (`#7132f5`, `#5741d8`, `#5b1ecf`) is too loud for a tool meant to age well, so the brand accent is Linear's muted lavender (`#5e6ad2`) instead.
The result is distinct from either source: a light canvas (Kraken) carrying a quiet lavender (Linear), rather than Kraken's shouty purple-on-white or Linear's lavender-on-near-black.

Lavender is scarce here, the way it is in Linear.
It is a fill and a focus ring and a link, never a section background or a card wash.
Depth comes from a cool light surface ladder plus hairline borders plus whisper shadows, the way Kraken earns trust without drama.
One lavender UI accent, plus one scoped brand-mark purple `#60079f` for the raven's own moments. No atmospheric gradients except the single brand-mark header wash. No spotlight cards.

## 1. Atmosphere

- Light only. The canvas is white with the faintest cool tint.
- A muted lavender (`#5e6ad2`) is the interface accent, used scarcely; the bolder brand-mark violet (`#60079f`) is the raven mark's own color, scoped to a few brand moments.
- Near-black text (`#101114`) on a cool-gray neutral scale.
- Depth from a three-step light surface ladder, hairline borders, and whisper shadows.
- Display type uses aggressive negative tracking. Body holds near zero.
- One type family across display and body, so the voice is continuous.

## 2. Color

### Brand accent (lavender)

- **Lavender** `#5e6ad2`: primary CTA, brand mark, focus ring, link emphasis. Never a section fill.
- **Lavender Hover** `#828fff`: hovered primary CTA.
- **Lavender Focus** `#5e69d1`: focus-ring tint, pressed primary.
- **Lavender Deep** `#4a51a8`: deepest lavender, for pressed/active fills.
- **Lavender Subtle** `rgba(94, 106, 210, 0.12)`: subtle lavender fills (low-emphasis buttons, selected chips).
- **On Lavender** `#ffffff`: text on a lavender fill.

### Brand-mark purple

The raven's eye is a vivid purple `#60079f` - bolder and more saturated than the lavender UI accent. It is the ONE brand-saturation the system allows, and it is the mark's own color, not a second interface accent. It is scarce and scoped: it appears only where the mark belongs, never as an ordinary control color.

- **Purple Bold** `#60079f`: the raven eye's pupil, the home header wash (a low-opacity gradient), the capture overlay's disc and Keep button, and the greeting's trailing period. Dark, so it wears white ink (dark ink fails on it).
- **Purple Bold Hover** `#7a1fc0`: the lighter lift for the capture Keep button on hover.
- **Purple Bold Wash** `rgba(96, 7, 159, 0.1)`: the home header's fading purple wash, and the capture focus glow.

Lavender stays the interface accent (CTA, focus ring, links, chips). The bold purple is the mark's saturation only - do not reach for it for ordinary buttons, focus rings, or links.

### Surface (light ladder)

- **Canvas** `#ffffff`: page background, faint cool tint acceptable (`#fbfbfd`).
- **Surface 1** `#f6f7f9`: one step up. Cards, panels, inputs.
- **Surface 2** `#eef0f3`: two steps up. Hovered cards, featured tiles, selected chips.
- **Surface 3** `#e4e6eb`: three steps up. Pressed fills, recessed wells.

### Ink (text)

- **Ink** `#101114`: headlines, emphasized body, primary text.
- **Ink Muted** `#4d5061`: secondary text, meta on hero panels.
- **Ink Subtle** `#686b82`: tertiary text, muted labels.
- **Ink Faint** `#9497a9`: disabled, footnotes, placeholders.

### Lines

- **Line** `#dedee5`: 1px borders on cards, dividers.
- **Line Strong** `#c4c6d0`: stronger borders, input borders.
- **Line Soft** `#eceef2`: soft dividers inside panels.

### Semantic

- **Success** `#149e61`: positive states. Badge fill `rgba(20, 158, 97, 0.16)`, badge text `#026b3f`.
- **Danger** `#b4332b`: destructive actions. Badge fill `rgba(180, 51, 43, 0.14)`, badge text `#7a241c`.
- **Warning** `#c47d1f`: caution. Badge fill `rgba(196, 125, 31, 0.16)`, badge text `#8a5512`.
- **Info** `#3b6bb5`: neutral informational. Badge fill `rgba(59, 107, 181, 0.14)`, badge text `#274a82`.

### Code

- **Code Ink** `#0a5270`: inline code text on light surfaces.
- **Code Surface** `#eef0f3`: code block ground (surface 2).

## 3. Typography

### Families

- **Display and Body**: `IBM Plex Sans`, fallbacks `system-ui, -apple-system, Segoe UI, Roboto`.
  One family across display and body, so the voice stays continuous.
  Vendored as woff2 in `static/fonts/` (weights 400/500/600/700); no CDN, no webfont substitute.
- **Mono**: the system mono stack (`ui-monospace, SF Mono, Menlo, Consolas`), matching `--mono` in `css/tokens.css`.
  Reserved for code and for status or ID tokens.

### Scale

| Role | Family | Size | Weight | Line height | Tracking | Use |
| --- | --- | --- | --- | --- | --- | --- |
| Display XL | IBM Plex Sans | 56px | 600 | 1.08 | -2.0px | Largest hero headline |
| Display LG | IBM Plex Sans | 40px | 600 | 1.12 | -1.4px | Section opener headlines |
| Display MD | IBM Plex Sans | 30px | 600 | 1.18 | -1.0px | Sub-section headlines |
| Headline | IBM Plex Sans | 24px | 600 | 1.22 | -0.5px | Panel titles, CTA headings |
| Title | IBM Plex Sans | 20px | 500 | 1.26 | -0.3px | Card titles |
| Subhead | IBM Plex Sans | 18px | 400 | 1.40 | -0.2px | Lead paragraphs |
| Body LG | IBM Plex Sans | 18px | 400 | 1.50 | -0.1px | Hero subhead |
| Body | IBM Plex Sans | 16px | 400 | 1.50 | 0 | Default body |
| Body SM | IBM Plex Sans | 14px | 400 | 1.50 | 0 | Card body, secondary |
| Caption | IBM Plex Sans | 12px | 400 | 1.40 | 0 | Meta, captions |
| Button | IBM Plex Sans | 14px | 500 | 1.20 | 0 | All button labels |
| Eyebrow | IBM Plex Sans | 12px | 600 | 1.30 | +0.6px | Section eyebrow, uppercase |
| Mono | system mono | 13px | 400 | 1.50 | 0 | Code, IDs |

### Principles

- Aggressive negative tracking on display, scaling with size. Body holds at zero.
- Display at weight 600. Body at 400. Buttons at 500. Never 700 on display.
- Eyebrow uses positive tracking and uppercase, to mark it as taxonomy against the negative-tracked display.
- Mono only in code and ID contexts, never in marketing chrome.

## 4. Spacing

Base unit 4px.

- `xxs` 4px
- `xs` 8px
- `sm` 12px
- `md` 16px
- `lg` 24px
- `xl` 32px
- `xxl` 48px
- `section` 96px

Card interior padding is `lg` 24px on feature cards, `xl` 32px on testimonial or hero cards.
Button padding is 8px vertical, 14px horizontal.
Input padding is 8px vertical, 12px horizontal.

## 5. Radius

| Token | Value | Use |
| --- | --- | --- |
| `xs` | 4px | Small chips, status dots |
| `sm` | 6px | Inline tags |
| `md` | 8px | Buttons, form inputs |
| `lg` | 12px | Cards, panels |
| `xl` | 16px | Large product panels, modals |
| `pill` | 9999px | Status pills, tab toggles only |

Buttons use 8px corners.
Never pill-round a button.
Cards use 12px.
Status badges use pill.

## 6. Elevation

Depth comes from the surface ladder plus hairline borders plus whisper shadows.
Shadows are cool and low-opacity, never dramatic.

| Level | Treatment | Use |
| --- | --- | --- |
| 0 flat | No shadow, no border | Body text, hero text |
| 1 lift | Surface 1 on canvas, 1px line border | Default cards, panels, inputs |
| 2 lift | Surface 2 on canvas, 1px line-strong border | Hovered cards, featured tiles |
| 3 lift | Surface 3 on canvas, 1px line border | Pressed wells, recessed areas |
| 4 focus | 2px lavender-focus outline at 50% opacity | Focused input, focused button |

### Shadows

- **Micro**: `rgba(16, 17, 20, 0.04) 0 1px 3px`.
- **Card**: `rgba(16, 17, 20, 0.06) 0 4px 16px`.
- **Lifted**: `rgba(16, 17, 20, 0.08) 0 8px 28px`.

Use shadows sparingly.
The surface ladder and hairlines carry most of the hierarchy.
A lifted modal or a floating menu earns a `Lifted` shadow.
A resting card earns at most a hairline, or a `Card` shadow if it must separate from a busy ground.

## 7. Components

### Buttons

**Primary (Lavender)**

- Background `#5e6ad2`, text `#ffffff`.
- Hover background `#828fff`. Pressed background `#5e69d1`.
- Padding 8px 14px. Radius 8px. Weight 500.

**Secondary (Surface)**

- Background surface 1 `#f6f7f9`, text ink `#101114`. 1px line border.
- Hover background surface 2.

**Tertiary (Ghost)**

- Background transparent, text ink.
- Hover background surface 1.

**Subtle (Lavender wash)**

- Background lavender subtle `rgba(94, 106, 210, 0.12)`, text lavender `#5e6ad2`.
- Hover deepens the wash.

**Inverse (White)**

- Background `#ffffff`, text ink, 1px line border.
- For a white CTA on a lavender or surface-2 banner.

**Danger**

- Background `#b4332b`, text `#ffffff`.
- Hover a shade darker.

### Badges

- **Success**: fill `rgba(20, 158, 97, 0.16)`, text `#026b3f`, radius pill, padding 2px 8px.
- **Neutral**: fill `rgba(104, 107, 130, 0.12)`, text `#4d5061`, radius 8px.
- **Lavender**: fill lavender subtle, text `#5e6ad2`, radius pill. For brand or status emphasis.
- **Danger**: fill `rgba(180, 51, 43, 0.14)`, text `#7a241c`, radius pill.

### Cards

- Background surface 1, text ink, radius 12px, padding 24px, 1px line border.
- Featured or hovered card lifts to surface 2 with a line-strong border.
- Large product or screenshot panel uses radius 16px.

### Inputs

- Background surface 1, text ink, radius 8px, padding 8px 12px, 1px line-strong border.
- Focused state keeps the surface. The focus ring is a 2px lavender-focus outline at 50% opacity.
- Placeholder text uses ink faint.

### Status pills

- Background surface 2, text ink muted, radius pill, padding 2px 8px, caption type.

### Navigation

- Top nav: canvas background, ink text, body-sm type, 56px height.
- Footer: canvas background, ink subtle text, caption type, 64px 32px padding.

## 8. Do's and Don'ts

### Do

- Reserve lavender for the primary CTA, focus ring, link emphasis, and chips.
- Reserve the bold brand-mark purple `#60079f` for the mark's own moments only (the raven eye, the home header wash, the capture disc and Keep button, the greeting period).
- Use the surface ladder for hierarchy. Avoid skipping levels.
- Apply negative letter-spacing aggressively on display.
- Pair display weight 600 with body weight 400.
- Compose buttons at 8px corners and cards at 12px.
- Let hairline borders and the surface ladder carry depth before reaching for a shadow.

### Don't

- Don't use lavender as a section background or a card fill.
- Don't introduce a chromatic accent beyond the two sanctioned here: the lavender UI accent and the one scoped brand-mark purple `#60079f`. No third.
- Don't spread the bold purple `#60079f` into ordinary controls (buttons, focus rings, links) - it is the mark's saturation, not a UI accent.
- Don't pill-round buttons.
- Don't use true black `#000000` for text. Use ink `#101114`.
- Don't add atmospheric gradients or spotlight cards - with one sanctioned exception: the home header's single low-opacity brand-mark purple wash fading to the canvas. No other gradients.
- Don't use the loud Kraken blue-purple `#7132f5` (distinct from the sanctioned brand-mark violet `#60079f`). The interface accent is the muted lavender.
- Don't combine multiple bright accents in one view.

## 9. Responsive

### Breakpoints

| Name | Width | Key changes |
| --- | --- | --- |
| Desktop XL | 1440px | Default layout |
| Desktop | 1280px | Card grid 3-up |
| Tablet | 1024px | Card grid 3-up to 2-up |
| Mobile LG | 768px | Nav collapses, grids 1-up |
| Mobile | 480px | Single column, display scales down |

### Touch

- CTAs hold at least 40px tap height.
- Inputs hold at least 44px tap target on touch.
- Pills hold at least 36px tap height, grown to 44px on touch.

### Collapse

- Top nav links collapse to a menu below 768px.
- Card grids go 3-up at 1024px, 2-up below that, 1-up below 768px.
- Display XL 56px scales toward Display MD 30px on mobile.

## 10. Token summary

```
--canvas:        #ffffff
--surface-1:     #f6f7f9
--surface-2:     #eef0f3
--surface-3:     #e4e6eb

--lavender:      #5e6ad2
--lavender-hover:#828fff
--lavender-focus:#5e69d1
--lavender-deep: #4a51a8
--lavender-subtle: rgba(94, 106, 210, 0.12)
--on-lavender:   #ffffff

--purple-bold:       #60079f
--purple-bold-hover: #7a1fc0
--purple-bold-wash:  rgba(96, 7, 159, 0.1)
--on-purple-bold:    #ffffff

--ink:           #101114
--ink-muted:     #4d5061
--ink-subtle:    #686b82
--ink-faint:     #9497a9

--line:          #dedee5
--line-strong:   #c4c6d0
--line-soft:     #eceef2

--success:       #149e61
--danger:        #b4332b
--warning:       #c47d1f
--info:          #3b6bb5
--code-ink:      #0a5270

--r-xs:  4px
--r-sm:  6px
--r-md:  8px
--r-lg:  12px
--r-xl:  16px
--r-pill: 9999px

--sp-xxs: 4px
--sp-xs:  8px
--sp-sm:  12px
--sp-md:  16px
--sp-lg:  24px
--sp-xl:  32px
--sp-xxl: 48px
--sp-section: 96px

--shadow-micro:  0 1px 3px rgba(16, 17, 20, 0.04)
--shadow-card:   0 4px 16px rgba(16, 17, 20, 0.06)
--shadow-lifted: 0 8px 28px rgba(16, 17, 20, 0.08)

--font-sans: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif
--font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace
```

## 11. Provenance

This system descends from Kraken's marketing surface, restrained.
The following table records what was carried over and what was deliberately toned down, so the lineage stays legible.

| From Kraken | Decision | Result here |
| --- | --- | --- |
| Purple scale `#7132f5` / `#5741d8` / `#5b1ecf` | Restrained | Muted lavender `#5e6ad2`, used scarcely |
| White canvas, professional calm | Kept | Light-only canvas, cool tint |
| Near-black text `#101114` | Kept | Ink `#101114`, never true black |
| Green success `#149e61`, badge text `#026b3f` | Kept | Success token and badge treatment |
| Whisper shadows (`rgba(0,0,0,0.03) 0 4px 24px`) | Kept, cooled | Cool low-opacity Micro/Card/Lifted shadows |
| 12px-max button radius, no pill | Kept as discipline | Buttons at 8px, never pilled |
| Kraken-Brand / Kraken-Product dual font | Restrained | One family (IBM Plex Sans) across display and body |
| Bold 700 display, negative tracking | Softened | Display at 600, aggressive negative tracking |
| Ad-hoc spacing (13px, 15px, 25px) | Replaced | Clean 4px-base scale |
