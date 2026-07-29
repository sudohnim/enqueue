# Atrium Design System

A second brain built as a museum catalogue.
Plaster walls, iron mounts, bronze plaques.
The interface is architecture; your notes are the collection.

---

## Design Philosophy

**Core statement:** the interface is a room, not a product surface.
It holds one artifact at a time, labels it precisely, and otherwise gets out of the way.

**Material honesty.** Three materials, three jobs, no overlap.
Iron is structure.
Bronze is designation.
Grey is time.
Anything that cannot be assigned a material does not get a color.

**Cool canvas, warm metal.** Plaster is deliberately cool and slightly green.
Bronze is warm.
That tension is what makes bronze read as an alloy rather than a brand accent.
Bronze on a warm cream canvas collapses into ordinary editorial coral - the cool wall is load-bearing.

**Designation, not decoration.** Every bronze mark answers "what is this object called."
It never says "click me" and never says "we are a company with a color."

**The label is an object.** Metadata is not a caption floating above a title.
It is a framed plaque bolted to the wall in the right margin, with its own iron border.

**Depth from material, never from light.** No drop shadows, no gradients, no blur, no glow.
Hierarchy comes from surface tone, hairline weight, and empty space.

**Square is the shape.** Zero radius everywhere.
Frames and mounts have corners.
Pills belong to software; this is a wall.

---

## Color Palette

### Light - plaster

| Token | Hex | Use |
|---|---|---|
| `canvas` | `#EAE9E4` | page background, the wall |
| `surface-lifted` | `#F4F3EF` | plaque interior, input fields |
| `iron-structural` | `#55585B` | mount rules, plaque frames, nav baseline |
| `iron-hairline` | `#C3C2BC` | list dividers, column separators |
| `ink` | `#191B1A` | headings, primary values |
| `body` | `#434644` | running prose |
| `grey` | `#7A7C78` | dates, counts, field labels, disabled |
| `bronze` | `#6B5230` | object numbers, section designations |

### Dark - iron vitrine

| Token | Hex | Use |
|---|---|---|
| `canvas` | `#16171A` | page background |
| `surface-lifted` | `#202226` | plaque interior, input fields |
| `iron-structural` | `#4A4E52` | mount rules, plaque frames, nav baseline |
| `iron-hairline` | `#303338` | list dividers, column separators |
| `ink` | `#EDEDE9` | headings, primary values |
| `body` | `#BCBEBA` | running prose |
| `grey` | `#83868B` | dates, counts, field labels, disabled |
| `bronze` | `#AF9057` | object numbers, section designations |

### Semantic - archival key

| Token | Light | Dark | Use |
|---|---|---|---|
| `verdigris` | `#5A6B5F` | `#7FA08C` | verified, archived, resolved |
| `ochre` | `#8A6A2A` | `#C4A05A` | warning - always paired with an icon |
| `oxide` | `#9B4A3C` | `#C4705E` | destructive and error only |

**Dark mode is not an inversion.**
Bronze lightens from `#6B5230` to `#AF9057` because deep bronze fails contrast on iron-black.
Iron lightens; hairlines darken.
Every pair was re-picked, not flipped.

### Contrast floor

- Bronze on plaster: 6.0:1
- Bronze on iron-black: 5.9:1
- Both clear AA for body text and fail AAA. Do not set paragraphs in bronze; labels and short values only.
- Grey on canvas clears AA at 14px and above. Below 14px, grey must go up to `body`.

### Separation from adjacent systems

Bronze must stay at hue 39 degrees, saturation 35%, lightness 51%.
Drifting below 30 degrees hue or above 45% saturation lands in coral territory and the system stops reading as metal.

---

## Typography

**Split inverted from convention.**
Sans carries display, serif carries body.
Brand sites do the opposite.
A catalogue raisonné does this.

| Role | Family | Notes |
|---|---|---|
| Display and UI | ABC Diatype, Söhne, Inter, system-ui, sans-serif | tight tracking, weight 500 max |
| Body and prose | Lyon Text, Freight Text Pro, Source Serif 4, Georgia, serif | weight 400 only |
| Designation | same sans, uppercase, tracked | 10-11px only |
| Code | JetBrains Mono, ui-monospace, monospace | 13px |

### Scale

| Role | Size | Weight | Line height | Tracking | Family |
|---|---|---|---|---|---|
| Display | 34px | 500 | 1.15 | -0.8px | sans |
| Title LG | 25px | 500 | 1.20 | -0.55px | sans |
| Title MD | 19px | 500 | 1.30 | -0.3px | sans |
| Body | 15px | 400 | 1.70 | 0 | serif |
| Body SM | 14px | 400 | 1.65 | 0 | serif |
| Value | 12px | 400 | 1.45 | 0 | sans |
| Field label | 11px | 400 | 1.40 | +1.2px, uppercase | sans |
| Designation | 10px | 400 | 1.40 | +1.4px, uppercase | sans |

**Two weights only: 400 and 500.**
Nothing bolder.
A wall label is never bold.

**Serif is reserved for your words.**
Any serif on screen is content you wrote or captured.
Any sans is the building.
The reader learns this split in one glance and never has to be told.

**Tracking rule.**
Negative tracking on sans display sizes only.
Positive tracking on uppercase micro-labels only.
Body serif stays at zero, always.

---

## Spacing and Layout

**Base unit:** 4px

| Token | Value |
|---|---|
| `xxs` | 4px |
| `xs` | 8px |
| `sm` | 12px |
| `md` | 20px |
| `lg` | 32px |
| `xl` | 44px |
| `xxl` | 64px |
| `gallery` | 96px |
| `hall` | 128px |

### Structure

- **Floor plan bar** across the top, 48px tall, sits on a 1px `iron-structural` baseline. Rooms are uppercase tracked labels, not a sidebar.
- **Object column** on the left, fluid, max 680px measure.
- **Label column** on the right, fixed 156px, separated by 1px `iron-hairline`.
- **Mount rule**: a 2px `iron-structural` vertical line hanging the object text, with 20px offset. This is the visual equivalent of the hanging hardware. Present on every artifact view.
- Top margin above a title is `xl` at minimum. Artifacts need air above them more than below.

### Measure

Serif body caps at 68 characters.
Past that the room stops feeling curated and starts feeling like documentation.

---

## Shapes and Elevation

**Border radius: 0px.** Every element.
The only exception is `9999px` for author avatars, because faces are not rectangles.

**No shadows. No gradients. No blur.**

| Level | Treatment |
|---|---|
| Wall | `canvas`, flat |
| Mounted | `surface-lifted` + 1px `iron-structural` frame |
| Divided | 1px `iron-hairline`, no fill change |
| Hung | 2px `iron-structural` left rule, no fill change |

Elevation is a border decision, never a light decision.

---

## Components

### Floor plan bar

Wordmark in uppercase tracked sans at `ink`.
Rooms in `grey`, uppercase, 11px, +1.1px.
Active room gets a 2px `iron-structural` bottom bar and shifts to `ink`.
Search is an icon at `iron-structural`, no input field until invoked.

### Plaque

Bordered box, 1px `iron-structural`, `surface-lifted` fill, 12px padding, square corners.
Interior: object designation in bronze uppercase, then alternating grey field labels with `ink` values.
Only one plaque per view.
Two plaques means two objects, which means the room is overhung.

### Mount

2px `iron-structural` left rule, 20px padding.
Wraps the title and body as a single hung unit.

### Provenance list

Section designation in bronze uppercase.
Entries in `ink` with a 1px `iron-hairline` bottom rule, last entry unruled.
Hover adds a 1px `iron-structural` underline.
Links are iron, not bronze.

### Buttons

No fills except for the primary.

| Variant | Light | Dark |
|---|---|---|
| Primary | `ink` fill, `canvas` text | `ink` fill, `canvas` text |
| Secondary | transparent, 1px `iron-structural` border, `ink` text | same |
| Tertiary | text only, `iron-structural` underline on hover | same |
| Destructive | transparent, 1px `oxide` border, `oxide` text | same |

44px height, 0px radius, 14px sans at weight 500, sentence case.
Never uppercase - uppercase belongs to labels.

### Inputs

`surface-lifted` fill, 1px `iron-hairline` border, 44px height, 0px radius.
Focus swaps the border to 1px `iron-structural` plus a 2px offset `iron-structural` ring.
No glow.

### Empty state

An empty room, not an illustration.
Centered `grey` sans at 14px, one line, one tertiary action.
No graphics.

---

## Motion

| Property | Value |
|---|---|
| Duration | 140ms standard, 200ms for view transitions |
| Easing | `cubic-bezier(0.2, 0, 0.2, 1)` |
| Permitted | opacity, 2px vertical translate, border-color |
| Forbidden | scale, bounce, spring, parallax, skeleton shimmer |

Rooms cross-fade.
Objects do not slide in.
Nothing in a museum moves when you look at it.

Respect `prefers-reduced-motion` by dropping to opacity only at 100ms.

---

## Responsive

| Breakpoint | Width | Behavior |
|---|---|---|
| Mobile | <=640px | Label column collapses to a plaque above the mount. Floor plan becomes a single active-room label plus menu icon. Display drops to 26px |
| Tablet | 641-1024px | Label column returns at 140px. Floor plan shows all rooms |
| Desktop | 1025-1440px | Full three-part layout. Label column 156px |
| Wide | >1440px | Content caps at 1100px. Extra width becomes wall, not content |

Touch targets 44px minimum.

---

## Do

- Keep bronze under five appearances per screen
- Give every object a designation number
- Leave more space above a title than below it
- Use serif for anything the user authored
- Let the label column stay half empty
- Re-pick colors for dark mode rather than inverting

## Don't

- Round a corner
- Add a shadow
- Set body copy in bronze
- Use bronze for links, buttons, or active states
- Introduce a fifth material
- Uppercase a button
- Put two plaques in one view
- Warm the canvas - the cool wall is what keeps bronze from reading as coral

---

## Known weak points

**Ochre sits close to bronze.**
A warning state and an object designation can be confused at a glance.
Ochre must always carry an icon; bronze never does.
If this proves fragile in use, drop ochre and render warnings as `oxide` with a different icon.

**Oxide is coral-adjacent** at hue 12 degrees.
Acceptable because destructive states are rare and are supposed to feel foreign to the system.
If oxide starts appearing on more than one screen in a session, the system has a bigger problem than color.

**Zero accent means no visual CTA.**
Primary actions rely on an `ink` fill and position alone.
Good for a reading tool.
If onboarding, upsell, or a marketing surface gets added, that surface needs its own rules - do not solve it by promoting bronze.

---

**Diverges from the mockup in one place:** bronze there also carried the active room and provenance links.
Spec pulls both to iron so bronze stays designation-only.
To revert, set active room and provenance links to bronze and accept roughly nine bronze marks per screen instead of four.
