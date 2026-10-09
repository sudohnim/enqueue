# Enqueue Design System

A flat violet ground, white-lit tiles, and one bold violet accent: the app lives inside the raven's colour instead of sitting on white paper.

This system replaced the earlier "light canvas, hairline borders, whisper shadows" look (Kraken restrained by Linear) in September 2026.
The earlier look read as boxed and amateurish: every surface was outlined in a grey 1px line, so the page looked like a set of drawn rectangles.
The replacement keeps the product's identity - the raven, the bold violet `#60079f`, IBM Plex for reading, the layout and every behaviour - and changes how depth and edges are made.

The rules in one breath:
the canvas is a flat medium lavender, surfaces climb toward white from it, edges are violet hairlines or soft violet shadows (never grey borders), headings speak in Instrument Sans with tight tracking, and violet is the one accent.

## 1. Atmosphere

- Light, but not white. The canvas is a flat lavender (`#eee8f6`), with no gradient and no wash.
- Tiles are lighter plates on that ground; anything hovered, raised, or typed into is white.
- Edges come from a 1px violet hairline drawn as an inset shadow, or from a layered violet shadow. There are no grey borders.
- The bold violet `#60079f` (the raven eye's pupil) is the only chromatic accent: primary fills, focus rings, links, the active-tab bar, the greeting's last word and period.
- The raven sits tight against its heading everywhere it appears (home greeting, settings title, capture overlay, the phone's quick-capture popup, a new note's date line), as part of the title rather than beside it.
- Display type (Instrument Sans) is tight and bold; body type (IBM Plex Sans) is calm and holds zero tracking.

## 2. Color

### The violet ground (surface ladder)

Surfaces climb toward white from the canvas, and recessed wells sink below it.

- **Canvas** `--bg` `#eee8f6`: the page, the frozen home header, the capture card, dialogs' page behind the scrim.
- **Tile** `--surface` `#f8f5fb`: wall cards, settings groups, list rows, resting chips.
- **Reading** `--surface-doc` `#fbf9fd`: menus, dialogs, drawers, toasts.
- A note (and a capture's notes) is a sheet lying on the canvas, the same raised page a PDF's leaves are: `--surface-doc` (the warm reading white, never pure white under a page of text), a 20px corner, hairline plus `--shadow-card`, 44/52px of padding (`.docpane:has(> .editor)` in `css/artifact.css`). A line fills across the sheet's top edge on a successful save (`.docpane.landed`) and "✓ Saved" whispers beside the date. A picture stays straight on the ground. The phone's writing page is still an open page, full screen, with a `--surface` tool bar on the keyboard. The caret is the accent everywhere you write.
- A note's typography reads the shape already typed, with nothing for the writer to do (scoped to `.editor`): a line that leads into a list is that list's label (500, `--text`); an item with items under it heads them; markers step down by depth (accent dot, dash, small dot) beside a hairline guide; headings are in the display face; a quotation is a soft `--bg` block, never a striped margin; a line of three or more dashes is a short centred rule (`md.js` renders it as `<hr data-dashes>` and writes the same dashes back).
- **Raised** `--surface-2` `#ffffff`: a hovered tile, search, inputs, the active settings section, secondary buttons.
- **Recessed** `--surface-3` `#e3d9ef`: an OFF toggle track, pressed wells. The darkest ground any text sits on.

### Accent

- **Violet** `--accent` / `--purple-bold` `#60079f`: primary buttons, the capture disc and Save, focus rings, links, the active tab bar, the greeting's last word and period. White ink on it (10.35:1).
- **Violet hover** `--lavender-focus` / `--purple-bold-hover` `#7a1fc0`, **pressed** `--lavender-deep` `#4a0578`.
- **Violet subtle** `--lavender-subtle` `rgba(96, 7, 159, 0.12)`: low-emphasis accent washes.
- The `--lavender*` names are aliases kept for existing consumers; they all resolve to the violet family.

### Ink (text)

Inks are pulled toward the violet so grey text never reads cold on the lavender ground.

- **Ink** `--text` `#120f19`: headings, primary text.
- **Ink dim** `--text-dim` `#433e57`: secondary text, helper text.
- **Ink mute** `--text-mute` / `--ink-faint` `#5a546e`: meta, counts, placeholders, inactive tabs. Clears 4.5:1 on every ground including `--surface-3`.

### Lines

- **Hairline** `--line` `rgba(58, 13, 99, 0.12)`: the tile edge, drawn as `--hairline` (`inset 0 0 0 1px var(--line)`), so it adds no layout.
- **Soft line** `--line-soft` `rgba(58, 13, 99, 0.07)`: dividers inside a tile, ghost-button hovers, keycap fills.
- **Strong line** `--line-strong` `#7a7291`: the only line that may be a sole boundary (3.32:1 on `--surface-3`); used for the OFF toggle ring and the rare control that has no fill to bound it.

### Semantic

Re-tuned for the lavender ground so each still clears its tier (`bin/check-contrast`).

- **Danger** `#a3291f` (text-safe on every ground), badge fill `rgba(180, 51, 43, 0.14)`, badge ink `#7a241c`.
- **Success** `#0f8453` (fill and graphic only), badge fill `rgba(20, 158, 97, 0.16)`, badge ink `#026b3f`.
- **Warning** `#a4650e` (fill and graphic only).
- **Info** `#325f9f`.

### Kind dots

Note green `#30804b`, link blue `#376899`, PDF terracotta `#ad5a31`, image plum `#8f4273`, file olive `#755c12`, chat violet `#7f6ad4`.
A kind hue only ever colours its 8px dot; kind is a fact, never an action.

## 3. Typography

### Families

- **Display**: Instrument Sans (`--display`), vendored as a variable woff2 (weights 400-700, widths 75-100%) in `static/fonts/` under the SIL OFL (`InstrumentSans-OFL.txt`).
  It carries the greeting, page and section headings, card and tile titles, dialog, settings and capture headings.
- **Body**: IBM Plex Sans (`--sans`), vendored woff2 400/500/600/700. Reading text, labels, buttons, meta.
- **Mono**: the system mono stack (`--mono`), for keycaps, hotkeys, IDs, code.
- No CDN, no webfont service: every face is a file beside the page.

### Scale

| Role | Face | Size | Weight | Tracking | Use |
| --- | --- | --- | --- | --- | --- |
| Greeting (desktop) | Instrument Sans | 54px | 600 | -0.045em | Home greeting |
| Settings title | Instrument Sans | 44px | 600 | -0.045em | "Settings." |
| Display | Instrument Sans | 34px | 600 | -0.04em | Generic `.display` |
| Greeting (phone) | Instrument Sans | 29px | 600 | -0.04em | Library greeting |
| Headline | Instrument Sans | 26px | 600 | -0.03 to -0.035em | Wall shelves, `.h1` |
| Section | Instrument Sans | 18-22px | 600 | -0.02 to -0.03em | Settings sections, phone shelves |
| Card title | Instrument Sans | 16.5-19px | 600 | -0.02 to -0.025em | Tiles |
| Capture heading | Instrument Sans | 21px | 600 | -0.03em | "Capture your thoughts." |
| Body | IBM Plex Sans | 16px | 400 | 0 | Reading, fields |
| Body SM | IBM Plex Sans | 14px | 400 | 0 | Tile excerpts, tabs |
| Caption | IBM Plex Sans | 12-13px | 400 | 0 | Meta, counts, the date line |
| Button | IBM Plex Sans | 14-15px | 500-600 | 0 | Buttons |
| Mono | system mono | 11-13px | 400-500 | 0 | Keycaps, hotkeys |

### Principles

- Display tracking is tight and scales with size: about -0.045em at 44px and above, -0.02em at card size.
- Headings are sentence case. No uppercase shelf labels, no eyebrows above headings.
- The greeting's last word and its period are in the accent: "Think about winding **down.**"
- A small date line sits above the greeting ("Sunday, September 27"), in caption mute ink.

## 4. Spacing

Base unit 4px: `4, 8, 12, 16, 24, 32, 48, 96` (`--sp-1` to `--sp-7`, `--sp-section`).
Tiles pad 14-16px; settings groups 24px; the capture card 14-16px; the phone gutter is 16px.

## 5. Radius

| Token | Value | Use |
| --- | --- | --- |
| `--r-sm` | 6px | Keycaps, small thumbnails |
| `--r-md` | 8px | Legacy small controls |
| `--r-lg` | 12px | Buttons, inputs, Save |
| `--r-xl` | 16px | Search, list rows, the capture field, event log |
| `--r-2xl` | 20px | Settings groups, dialogs |
| tiles | 18px | Wall tiles (desktop and phone) |
| sheets | 22px | The capture overlay card |
| `--r-full` | pill | The capture pill, tag chips, status badges |

## 6. Elevation

Depth is the surface ladder plus violet-tinted, layered shadows.
A shadow always has an offset and a soft fall-off; there are no grey halos and no zero-offset glows.

| Token | Value | Use |
| --- | --- | --- |
| `--hairline` | `inset 0 0 0 1px var(--line)` | A tile's resting edge |
| `--shadow-micro` | `0 1px 2px rgba(43,11,74,.06)` | Small raised controls |
| `--shadow-card` | contact + `0 12px 32px -14px rgba(43,11,74,.3)` | A hovered tile |
| `--shadow-lifted` | contact + `0 28px 64px -20px rgba(43,11,74,.4)` | Menus, dialogs, drawers, the capture card |
| `--shadow-field` | contact + `0 10px 30px -12px rgba(96,7,159,.3)` | A field floating on the ground (search, focused inputs) |

Hover on a desktop tile: it turns white, takes `--shadow-card`, and rises 2px (no scale, so neighbours never shift; no rise under reduced motion).
Focus on any field: a 2px accent ring at 45% plus `--shadow-field`.

## 7. Components

### Wall tiles

- `--surface` plate, `--hairline` edge, 18px radius, 14-16px padding.
- Kind dot + kind word, then the title in Instrument Sans, a three-line excerpt, the relative time.
- Pictorial tiles (image, PDF page, link preview picture) fill the tile; the title band fades up out of the plate instead of cutting across the picture with a hard edge.
- Desktop: a bounded grid (5-up at the widest, stepping down). Phone: each shelf is one sideways-scrolling rail of 168px square tiles that snaps to the content gutter, so Saved never scrolls away; the › expands a shelf into a grid.

### Home header

- Desktop: centred. Date line, then the raven tight against the greeting, then a 720px search, then the mode tabs.
- Phone: left-aligned. The raven (86px) spans the date line and the greeting (29px).
- The frozen desktop header sits on the flat canvas (full-bleed), and only its last 18px fade, below the tabs.

### Search

A white field floating on the ground: `--surface-2`, `--shadow-field`, 16px radius, 48px tall, a drawn magnifier, and the ⌘K keycap on desktop.

### Mode tabs (Last touch / Type / Tags / Custom)

Text tabs, not a segmented control: mute ink, the chosen one in ink at 500 with a 16x2px accent bar under it.

### Buttons

- **Primary**: violet fill, white ink, 12px radius, a soft violet drop shadow. Hover `#7a1fc0`, pressed `#4a0578`.
- **Secondary**: a white plate with `--hairline` + micro shadow.
- **Tertiary / ghost**: transparent, `--line-soft` on hover.
- **Danger**: `--danger` fill, white ink.
- **Icon**: a `--line-soft` plate that turns white on hover.

### Inputs

White (`--surface-2`), `--hairline`, 12px radius (16px for the big capture fields); focus adds the 2px accent ring and `--shadow-field`. Placeholder in `--ink-faint`.

### Settings

- Title lockup: the living raven eye tight against "Settings." (44px).
- A 196px sidebar of sections (the active one a white plate with an accent dot), beside a pane of titled tiles; below 820px the sidebar folds into a scrolling row.
- Section names are headings in the display face; the pane does not repeat the section title.
- Toggles: an OFF recessed violet track ringed in `--line-strong`, an ON violet track, a white bead.
- On the phone, settings are managed by the desktop and read-only.

### The capture pill

- One icon system: three equal 46px circles. Capture is the one solid violet disc (24px plus, 2.25px stroke); ask and settings sit on soft lavender discs of the same size (the accent at 8%), as line icons in `--text-dim` (the eye 30px, the gear 26px, about a 1.5px line), so all three carry equal weight.
- On desktop (capture, ask, settings; Home + ask inside an artifact; search lives in the header and on ⌘K) and phone (capture, ask, settings) alike, the ask eye is drawn in that same line (an almond and three lashes), with a violet iris in a clipped socket that still follows the cursor (desktop) or glances on its own (phone), constricts on tap and blinks. It is not the `eye-only.png` art, whose thick black outline outweighed everything around it.
- Glass: the canvas tinted toward white (`color-mix(--bg 62%, white 70%)`), 20px backdrop blur, a white inner rim and a violet hairline ring, so the edge holds even over white tiles; a violet drop shadow.
- Pressed: the lavender disc deepens to 14% and squashes to 0.94. No outlines anywhere.

### Quick capture (desktop overlay)

- A 640x320 transparent window holding a 22px-radius card on the canvas, so the card's `--shadow-lifted` falls inside the window instead of being clipped into a box.
- Header (the drag handle): the raven tight against "Capture your thoughts." centred.
- A white field plate (the one pure-white thing on the card); focus adds the accent ring and `--shadow-field`.
- Footer: a tonal kind chip (dot + "link · psyche.co"), the key hints (↵ save, ⇧↵ new line, esc close), and the violet Save.
- On a keep, the card leaves and the raven flies across the app you were in (CAP2.2).

### Quick capture (phone sheet)

- A bottom sheet over the blurred, dimmed library: grab handle, the raven + "Capture your thoughts.", a white field, Photo and Camera beside Save.
- It follows the visual viewport, so the keyboard never covers it.
- Opened from the pill's "Note" and from the launcher shortcut (long-press the app icon, "Quick capture"). From the shortcut, a keep or a dismiss hands the phone back to the app the person was in.

### Dialogs, menus, drawers, toasts

`--surface-doc` with `--shadow-lifted`, 16-20px radius, no border. Scrims are violet-black (`rgba(33, 10, 56, 0.34-0.4)`), never grey.

**The Details panel** (an artifact's tags, views, summary and connecting passages; `.drawer` in `css/artifact.css`) is a floating white plate, not a slab welded to the window edge: `--surface-2`, `--r-xl`, hairline plus `--shadow-lifted`, 12px in from the right and bottom, under the drag strip.
Its header ("Details" in the display face) stays put while the body scrolls.
Each section (`.dsec`) is a label row in the display face at 13/600, with a count or a control when it has one, parted from the next by a `--line-soft` hairline; no tinted boxes inside the panel.
Chips are 28px pills on `--surface` with a hairline; an "add" control is the same pill drawn with a dashed `--line-strong` edge, which turns solid accent with a ring on focus.
The summary is a list of points on the panel's white, each led by a small dot (accent on a line the person rewrote), in a box that scrolls on its own with a fade at its foot.
The open panel never covers the reading column: the column slides left by its overlap (`left`, not `transform`, because the PDF page count is `position: fixed` inside it), as far as the window allows.
The toggle that opens it is the circled i, the same mark as the phone's, and stays lit (`--lavender-subtle`, accent ink) while it is open; the panel closes on its own x.
The phone's Details panel (`.details-panel` in `mobile.html`) is the same plate at phone size: floating card, header with the raven and its line, sections parted by hairlines, pill chips with a dashed add, a dotted summary.

### Personality

- **The ask eye has moods** (`js/eyemood.js`, shared by desktop and phone). It follows you anywhere (the cursor on desktop, your finger on the phone), blinks, and drifts into a lazy eye every 9 to 16 seconds. It approves a keep with one slow blink, squints and darts while search thinks then opens wide on results, startles when something new arrives, looks away and shuts while the vault is open, dozes after a minute of nothing and wakes with a start, and winces and looks away when poked three times. The iris is one flat violet disc, big enough to stare with white left around it. Reduced motion gets a still eye.
- **The ground drifts with the day** (`js/ground.js`): night `#ddd1ec`, dawn `#f2e9f2`, day `#eee8f6`, dusk `#ebe0f0`, evening `#e4d9f0`, interpolated by the minute. Only the ground ladder moves (`--bg`, and `--surface`, `--surface-doc`, `--surface-3` derived from it); inks and the accent stay. `bin/check-contrast` re-checks every rule on the night ladder. On Android the status and navigation bar strips follow it through the `EnqueueAndroid.setGround` bridge.
- **The loading raven flies** (`css/bird.css`, `.flybird`, shared with the phone). The one loading mark is the front-on raven with its wings out, cut into a body and two wings with clip-paths: each wing beats about its own shoulder and the body rides the beat, sinking on the upstroke and lifting on the downstroke, with a slow sway. It used to be the whole picture spinning like a wheel. Markup is `<span class="flybird"><i></i><i></i><i></i></span>`, sized where it is used; reduced motion holds it still.
- **The raven that found them stands on Related** (`.related-raven`, `raven-scroll.png`): on the top edge of the first row of related artifacts, the scroll it carried at its feet, leaning in when you reach for one.
- **The raven stands in the Details panel** (`.drawer-perch`, `ravenLine` and `ravenNod` in `js/artifact.js`). The panel is the raven showing what it made of the thing, so it stands on the header's rule with its head cocked (`raven-tilt.png`), facing the page, and the header says so in its voice ("I read it. Here's what stuck.", "My reading. Correct me.", "Still reading. One moment.", "I kept my eyes off this one." for a thing held out of every model call). Every line is true of the state it is shown in, and the "read it" line an artifact gets is fixed by its id. It lands once when the panel is opened (never on a re-render), bobs for exactly as long as a summary is being rewritten while the ask eye squints, and hops, with the eye's slow approving blink, when you rewrite or add a line; that line's dot takes the accent with a small pop. Reduced motion gets a still raven.
- **The greetings have a voice**: the raven that keeps your things, cheeky and a little too observant ("Up before the worms", "I've been counting your tabs", "It's just us now"). `greeting.py` is the source; the phone mirrors the lists. The phrase's own ending ("Still up?") or a period is the accent mark.

### The tour (the ? on the home header)

- The `?` is an icon button (a `--line-soft` plate that turns white on hover), 32px on the desk and a 44px target on the phone, at the top right of the home header; an 8px accent bead marks it until the tour has been opened once.
- The tour is a stage, not a dialog card: the whole window on the flat canvas, with no scrim.
- It speaks in the greeting's voice: the headline is the display face at greeting size (40-58px on the desk, 34px on the phone), tight, with its last word and full stop in the accent.
- Two columns on the desk (words, then a demo plate on `--surface` with a 22px radius); one column on the phone, words first.
- Demos are built from miniature wall tiles (white `--surface-2` plates, kind dot and word, title in the display face) so they read as the real thing at a glance.
- Progress is a row of short bars that fill in the accent; there are no step numbers.
- Motion is one settle per card (the words slide in from the side they came from, the plate rises) plus the small answers inside the demos; reduced motion gets none of it.

## 8. Do's and Don'ts

### Do

- Build depth from the ladder (canvas → tile → white) and violet shadows.
- Draw a tile's edge with `--hairline`, a divider with `--line-soft`.
- Put the raven tight against its heading.
- Keep headings sentence case in Instrument Sans with tight tracking.
- Let violet be the single accent, and keep it for instructions, focus, links, and the brand's own marks.

### Don't

- Don't draw grey 1px borders around surfaces. A border that is a solid line is the old system.
- Don't use a gradient for the ground. The canvas is flat; the only fades are functional (the header's last 18px, a pictorial tile's title band).
- Don't use grey shadows or zero-offset glows.
- Don't uppercase headings or add eyebrows above them.
- Don't introduce a second accent colour, and don't use the loud Kraken blue-purple `#7132f5`.
- Don't use true black `#000000` for text.

## 9. Responsive

### Breakpoints

| Width | Change |
| --- | --- |
| > 1280px | Wall 5-up |
| ≤ 1280px | Wall 4-up, tiles back to 16px padding |
| ≤ 1024px | Wall 3-up |
| ≤ 820px | Settings sidebar folds into a scrolling row |
| ≤ 768px | Wall 2-up, greeting steps down |
| ≤ 480px | Wall 1-up |

### Touch

Every tap target is at least 40px (44px on the pill); inputs are 16px text so the WebView never zooms on focus.

### The Android app (`mobile.html`)

Shares `tokens.css` with the desktop, so the ground, inks, hairlines, shadows and faces are identical.
The Android status bar and navigation bar are reserved by `MainActivity` (system-bar insets); the page adds `env(safe-area-inset-*)` on top only for a display cutout.

## 10. Token summary

```
--bg:          #eee8f6    --surface:   #f8f5fb    --surface-doc: #fbf9fd
--surface-2:   #ffffff    --surface-3: #e3d9ef

--text:        #120f19    --text-dim:  #433e57    --text-mute:   #5a546e
--ink-faint:   #5a546e

--accent / --purple-bold:   #60079f
--lavender-focus / hover:   #7a1fc0
--lavender-deep:            #4a0578
--lavender-subtle:          rgba(96, 7, 159, 0.12)

--line:        rgba(58, 13, 99, 0.12)
--line-soft:   rgba(58, 13, 99, 0.07)
--line-strong: #7a7291

--danger: #a3291f   --success: #0f8453   --warning: #a4650e   --info: #325f9f

--hairline:      inset 0 0 0 1px var(--line)
--shadow-micro:  0 1px 2px rgba(43, 11, 74, 0.06)
--shadow-card:   0 1px 2px rgba(43, 11, 74, 0.06), 0 12px 32px -14px rgba(43, 11, 74, 0.3)
--shadow-lifted: 0 2px 6px rgba(43, 11, 74, 0.06), 0 28px 64px -20px rgba(43, 11, 74, 0.4)
--shadow-field:  0 1px 2px rgba(43, 11, 74, 0.06), 0 10px 30px -12px rgba(96, 7, 159, 0.3)

--r-sm 6  --r-md 8  --r-lg 12  --r-xl 16  --r-2xl 20  --r-full 9999

--display: "Instrument Sans", "IBM Plex Sans", system-ui, -apple-system, sans-serif
--sans:    "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif
--mono:    ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace
```

`static/css/tokens.css` is the source of truth; `capture.html` copies the subset it uses, and `bin/check-contrast` fails on any drift between the two and on any ink or boundary below its WCAG tier (washes are composited over the lavender canvas, not white).

## 11. Provenance

| Earlier system | Decision | Now |
| --- | --- | --- |
| White canvas `#ffffff` | Replaced | Flat lavender ground `#eee8f6` |
| Grey 1px borders on every surface | Removed | Violet inset hairline, violet layered shadows |
| Home header purple gradient wash | Removed | Flat full-bleed ground, a short functional fade |
| Uppercase shelf labels | Removed | Sentence-case display headings |
| Segmented pill mode switcher | Replaced | Text tabs with an accent bar |
| IBM Plex for everything | Split | Instrument Sans display, Plex body |
| Bordered capture card with a tiny disc | Replaced | Raven + "Capture your thoughts." header, white field, key hints |
| Full-screen phone capture page | Replaced | Bottom sheet, plus the launcher long-press shortcut |
| Bold violet `#60079f` accent | Kept | Still the single accent |
| The raven, the living eye, IBM Plex body, the layout | Kept | Unchanged in behaviour |
