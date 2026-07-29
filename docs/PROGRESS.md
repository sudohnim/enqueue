# Enqueue - the editorial redesign

Status: **in progress (P0)**
The current files (`museum.html`, `capture.html`) still carry the work from the charcoal redesign.
This document replaces that direction entirely.

## Decisions

- **Font delivery**: IBM Plex Sans Variable woff2 files will be downloaded into `src/enqueue/static/fonts/` and served locally via `@font-face`. No CDN.
- **Canvas colour**: Start with `#F0EDE6`. If it feels too generic-warm after P1 is live, bump to `#EBE4D8` or similar. 30-second feedback loop via `bin/relaunch`.

---

## 1. Orientation

Enqueue is a local-first place to put digital things without deciding what they are.
An AI reads them on your behalf and nothing leaves the machine.
The whole product runs on `127.0.0.1` only.

### What you will touch

| Path | What it is |
| --- | --- |
| `src/enqueue/static/museum.html` | The entire interface. One file: inline `<style>`, inline `<script>`, ~4500 lines. |
| `src/enqueue/static/capture.html` | The global-hotkey capture overlay. A separate page with its own copy of the tokens. |
| `docs/design-before.html` | Byte-identical snapshot of the museum before any changes. |
| `bin/relaunch` | Rebuilds and launches. Refuses to start if either page fails to parse. |
| `bin/verify` | Runs JS parse check on both pages, pytest, and contrast check. |

### Running it

```bash
bin/relaunch          # rebuild + launch; prints "up: {...}" on success
uv run pytest -q      # 85 passing at the time of writing
```

### House rules

- **Never commit.** The human commits.
- **No em dashes** anywhere. Use a plain dash.
- Everything binds to `127.0.0.1` only. No CDN fonts, no external stylesheets.

---

## 2. The design direction

Combined from PostHog's warm cream canvas and Mastercard's editorial pill language.

**Warm cream ground.** The canvas is a warm, putty-cream tone (`#F0EDE6`) — inspired by PostHog's `#eeefe9` and Mastercard's `#F3F0EE`. Not white, not grey. Content sits on paper, not on a screen.

**One sans family, one voice.** IBM Plex Sans Variable (open-source, Google Fonts hosted) across every role. Weights 400/500/600/700. No serif, no mono, no second personality. Fallback: system-ui, -apple-system, sans-serif.

**One accent.** A warm amber-orange (`#D48B2B`) carries every action and current-selection state. Nothing else may use it. Kind colours are facts about a thing, never actions, so they stay muted.

**Editorial but precise.** Cards use 6px radius (PostHog). The capture pill uses 999px (Mastercard). A single hero-style element (the rail header) may use 20px radius. No other radii exist.

**Ink on cream.** Text is a warm olive-charcoal (`#2C2D26`) — near-black with a hint of warmth so it never feels cold on the cream canvas.

**No drop shadows on cards.** Cards sit flat on cream with thin olive borders. The only shadow is a soft one on the floating capture pill.

---

## 3. The palette

### Colors

| Token | Hex | Role |
| --- | --- | --- |
| `--bg` | `#F0EDE6` | warm cream canvas - the page ground |
| `--surface` | `#F7F5F0` | inset panels, card frames, input fills - lifted cream |
| `--surface-2` | `#EAE7DF` | hover state on surface, selected row, pressed |
| `--surface-card` | `#FFFFFF` | true white card on cream (design target only, not used yet) |
| `--line` | `#D6D3CB` | hairline dividers, decorative only |
| `--line-strong` | `#A5A298` | the sole boundary of a control |
| `--text` | `#2C2D26` | warm olive-charcoal - primary text |
| `--text-dim` | `#5C5D55` | secondary text |
| `--text-mute` | `#8B8C83` | metadata, timestamps, captions |
| `--accent` | `#D48B2B` | warm amber-orange; actions and current selection |
| `--accent-quiet` | `#C07D20` | accent text on a busy ground |
| `--accent-ink` | `#F7F5F0` | text on top of a filled accent |
| `--green` | `#5E8A6D` | kind: note - muted sage |
| `--blue` | `#5B7FA5` | kind: link - muted slate |
| `--peach` | `#C27A5D` | kind: pdf - muted terra cotta |
| `--pink` | `#B57D95` | kind: image - muted rose |
| `--teal` | `#5C8A84` | kind: file - muted teal |

### Typography

| Role | Size | Weight | Line Height | Letter Spacing |
| --- | --- | --- | --- | --- |
| Display | 28px | 600 | 1.2 | -0.5px |
| Heading | 20px | 600 | 1.3 | -0.3px |
| Subheading | 16px | 600 | 1.4 | 0 |
| Body | 15px | 400 | 1.6 | 0 |
| Body Small | 14px | 400 | 1.55 | 0 |
| Caption | 12.5px | 500 | 1.4 | 0 |
| Label | 11px | 600 | 1.3 | +0.5px, uppercase |
| Code | 13px | 400 | 1.4 | 0 (mono) |

**Font family:** `"IBM Plex Sans Variable", "IBM Plex Sans", system-ui, -apple-system, sans-serif`
**Monospace:** `"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace`

### Spacing

| Token | Value |
| --- | --- |
| `--sp-1` | 4px |
| `--sp-2` | 8px |
| `--sp-3` | 12px |
| `--sp-4` | 20px |
| `--sp-5` | 32px |
| `--sp-6` | 44px |
| `--sp-7` | 64px |
| `--sp-8` | 96px |
| `--sp-9` | 128px |

### Radii

| Token | Value | Use |
| --- | --- | --- |
| `--r-sm` | 6px | Cards, inputs, menus, most elements |
| `--r` | 10px | Occasional medium container |
| `--r-lg` | 20px | Rail "Everything" header, hero-like elements |
| `--r-full` | 999px | Capture pill, search input |

### Shadows

| Token | Value |
|---|---|
| `--shadow-1` | `0 2px 8px rgb(0 0 0 / 0.06)` (capture pill) |

---

## 4. Traps

**T1. No `data-theme` survives.** There is one theme now - warm cream. No light/dark toggle.

**T2. `capture.html` has its own token copy.** It defines its own `:root`. Renaming museum.html does nothing to it.

**T3. The file contains NUL bytes.** Always use `rg -a` on `museum.html`.

---

## 5. Invariants

1. `node --check` passes on every inline `<script>` in both pages.
2. `uv run pytest -q` is green (85 passing baseline).
3. `bin/verify` passes.
4. `bin/relaunch` reports `up:` with a health payload.

---

## 6. How to work these steps

Every step states a **target state**, not an edit.
Run its check first; if the check already passes, the step is done and you skip it.

Work in order.
Do not start a phase until the previous phase's checks pass.

---

## P0 - baseline

**P0.1 Verify current state.**
`bin/verify` passes, `bin/relaunch` works.

**P0.2 Confirm design-before.html exists.**
`cmp -s docs/design-before.html src/enqueue/static/museum.html && echo same`

---

## P1 - warm cream palette

**P1.1 Replace :root block.**
Replace the current charcoal `:root` (dark-only) with the warm cream palette from section 3.
Remove `color-scheme: dark`.
Add IBM Plex Sans Variable as `--sans` family.

**P1.2 Update capture.html :root.**
Replace capture.html's `:root` with the same warm cream palette subset.

---

## P2 - rename & clean dead tokens

**P2.1 Remove all `data-theme` references.**
Remove `[data-theme="dark"]`, `[data-theme="light"]`, `prefers-color-scheme` from both files.

**P2.2 Remove all Atrium comments.**
Any CSS or JS comment mentioning `plaster`, `bronze`, `iron`, `canvas` (as old token), `verdigris`, `ochre`, `oxide`, `slate`, `vellum` → remove or rewrite.

---

## P3 - typography

**P3.1 Set `--sans` to IBM Plex Sans Variable.**
In both files.

**P3.2 Remove `--serif` references.**
Replace any `var(--serif)` with `var(--sans)`.

**P3.3 Restrict `--mono` to code only.**
Only `.editor code` uses `var(--mono)`. All other `var(--mono)` become `var(--sans)`.

**P3.4 Set type scale.**
Replace all `font-size` values with the ramp from section 3 (28, 20, 16, 15, 14, 12.5, 11, 13px).

---

## P4 - radii & shapes

**P4.1 Replace all `border-radius: 0` with `var(--r-sm)`.**
Every square corner becomes 6px radius.

**P4.2 Make the capture pill `--r-full`.**
The `.pill` gets `border-radius: var(--r-full)` and `box-shadow: var(--shadow-1)`.

**P4.3 Make the rail header `--r-lg`.**
The `.gohome` (Everything button) gets `border-radius: var(--r-lg)`.

**P4.4 Set one shadow.**
Only the capture pill floats. Remove any other `box-shadow`.

---

## P5 - components

**P5.1 Update the rail.**

- `.gohome` fills accent (`--accent`) with `--accent-ink` text
- Hover: mix accent toward text
- `.threadrow.on` uses `--surface-2`
- `.gear` uses `--text-mute` default, `--text` on hover

**P5.2 Update the wall.**

- Card frame on `--surface` with 1px `--line` border
- Kind colour only on `.kindmark` dot and hover border
- Title in `--text`, meta in `--text-mute`

**P5.3 Update chat bubbles.**

- User question bubble: `--surface` background, `--text-dim` text, `--line` border
- Curator answer: no frame, max-width 68ch, `--text` body, `--text-dim` lede
- Citations in `--text-mute`

**P5.4 Update settings.**

- Field labels in `--text-dim`, body in `--text`
- Focus ring on `--accent`
- Segmented control uses `--line` border, active = `--surface-2`

**P5.5 Update the capture overlay.**

- Background `--bg`, text `--text`
- Bar on `--surface` with `--line` bottom border
- Kind label in `--accent`
- Input field: transparent bg, `--text` placeholder

---

## P6 - polish

**P6.1 Remove the sole serif type style.**
Check no `--serif` references remain.

**P6.2 Verify full rebuild.**
`bin/verify && bin/relaunch`

---

## P7 - copy refresh

**P7.1 Inventory museum vocabulary.**
List every visible copy word from the old museum system (curator, Kept, shelf, exhibit, plaque).

**P7.2 Decide replacements.**
curator→?, Kept→saved, shelf→section, exhibit→collection.

**P7.3 Apply copy changes.**
Replace visible copy only.

---

## Rollback

`docs/design-before.html` restores the interface exactly.
Nothing here touches the database, the ingest pipeline, or any stored artifact.
