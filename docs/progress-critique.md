# Phase critique findings

Method: degraded, single-context (no sub-agent tool exposed in this worker; no browser automation available per task constraints). Assessment A (source review) ran inline. Assessment B (detector) ran via CLI: `detect.mjs` on `museum.html` and `capture.html` returned `[]` — zero findings, clean. No browser visualization (browser tools prohibited). No snapshot persisted (slug skipped, no PRODUCT.md).

The app is a hand-crafted, single-file desktop tool with a coherent voice, strong WCAG commentary baked into the `:root`, and a deliberately opinionated set of constraints (no external assets, no model calls for rendering, warm cream museum aesthetic). The design is NOT AI slop — it reads as a designed product, not a generated one. But the current palette (warm cream `#eeefe9` + amber `#f7a501`) is pre-overhaul; `docs/DESIGN.md` mandates a cool white canvas `#ffffff` + muted lavender `#5e6ad2`. Every finding below is framed against that target system, not the current one, because the overhaul plan in `docs/PROGRESS.md` will execute the migration.

## Heuristic scores

| # | Heuristic | Score | Key issue |
| --- | ----------- | ------- | ----------- |
| 1 | Visibility of System Status | 3 | Async answer path shows "thinking" then can fail silently with generic "That answer could not be completed." — no cause, no recovery. Settings has a staging/dirty bar but it is not always visible above the fold. |
| 2 | Match System / Real World | 3 | Language is plain and honest ("Nothing here expires", "Still searchable"). Minor: `whyNoFacets` translates internal enums to human sentences — good. "Concept layer" / "facets" is jargon the app explains only once in a tooltip. |
| 3 | User Control and Freedom | 3 | Escape closes the drawer (Phase J4). Back button returns from settings sub-pages to the nav. No undo for tag add/remove (it re-renders immediately). Pin/unpin is instant. |
| 4 | Consistency and Standards | 2 | Radius scale is `6px / 20px / 40px` — cards at 40px, searchbar at 999px (pill), items at 20px. DESIGN.md mandates `8/12/16px` + pill for pills only. The searchbar pill violates the "never pill-round a button" spirit even though it is an input. Settings rows use `--r-lg` (40px) on a full-width list row — far too round. |
| 5 | Error Prevention | 3 | Destructive actions (trash, rebuild facets) use a confirm dialog (`ask()`). Settings stage changes and require Save/Discard. The API key field is type=password with a "Forget" button. No autosave on the note editor — changes can be lost if the user navigates away mid-edit without the editor's save cycle firing. |
| 6 | Recognition Rather Than Recall | 3 | The kbd hint `⌘K` in the searchbar teaches the shortcut and disappears on focus — good discoverability. Settings nav rows carry icon + label + description — excellent. The artifact header has 4 icon-only buttons (download, pin, drawer, trash) with `aria-label` and `title` but no visible text — a first-timer must hover to learn. |
| 7 | Flexibility and Efficiency | 3 | `⌘K` for search, Escape to close drawer/back, `rowKey` for exhibit navigation. No keyboard shortcut to open the artifact drawer toggle (`#drawerToggle` is click-only). No bulk actions on the wall. |
| 8 | Aesthetic and Minimalist Design | 3 | The wall is clean: centered greeting, search, shelves, square cards. The pill is a single floating action. But the 40px card radius and pill-shaped searchbar read as over-rounded, not minimal. The amber accent is a loud fill that the app itself documents as "1.76:1, cannot be text or a lone border" — that constraint drove a 1.5px edge on every accent fill, adding visual weight where lavender would need none. |
| 9 | Error Recovery | 2 | "That answer could not be completed." is the worst case: no cause, no fix, no link to settings. The `ProviderError` message ("the endpoint rejected the API key") is slightly better but still not actionable from the chat view. The user must navigate to Settings to learn the key is the problem. |
| 10 | Help and Documentation | 2 | No help system. The app is self-documenting via its empty states, aside notes, and tooltip copy, but there is no searchable help, no shortcut reference, and no guided tour. The `⌘K` hint is the only inline teaching. |

**Total: 26/40 — Acceptable.** Significant improvements needed before the lavender overhaul lands. The score is honest: the app is well-built but the amber system and its workarounds (1.5px edges, pill searchbar, 40px radii) add friction the new system can eliminate.

## Anti-patterns verdict

**LLM assessment**: This is not AI slop. The code is hand-crafted with deliberate, documented constraints. But several patterns the impeccable skill flags as defects are present:

1. **Ghost-card on the pill** (`museum.html:1175-1181`): `.pill` has `border: 1px solid var(--line)` AND `box-shadow: var(--shadow-2)` where `--shadow-2` is `0 24px 48px rgba(35,37,29,0.08)` — 24px blur ≥ 16px. The skill bans "border: 1px solid X + box-shadow with M≥16px on the same element." The pill is one of four elements allowed a shadow, but the border+shadow pairing is the tell.
2. **Over-rounded cards** (`museum.html:836`): `.card { border-radius: var(--r-lg) }` where `--r-lg: 40px`. The skill bans "border-radius: 32px+ on cards/sections/inputs." 40px on a square card is the codex tell. DESIGN.md mandates 12px.
3. **Over-rounded settings rows** (`museum.html:1099`): `.settings-nav-row:first-of-type { border-radius: var(--r-lg) }` = 40px on a full-width list row. DESIGN.md says cards 12px; list rows should be flatter or borderless.
4. **Pill searchbar** (`museum.html:244`): `.searchbar { border-radius: var(--r-full) }` = 999px. DESIGN.md section 5: pill is for "Status pills, tab toggles only." A search input should be 8px.
5. **Accent edge workaround**: Every accent fill carries a `1.5px solid var(--text)` border (`museum.html:1206` `.pill .keep .disc`, `museum.html:363` `.greet-emblem`). This exists because amber `#f7a501` is 1.76:1 on cream and cannot stand alone as a boundary. Lavender `#5e6ad2` at ~4.67:1 on white clears 3:1 and needs no edge — the workaround can be dropped, simplifying every accent component.

**Deterministic scan**: `detect.mjs` on `museum.html` and `capture.html` returned `[]` — zero findings. The detector does not catch the ghost-card or over-radius patterns (those are in the skill's manual review checklist, not the automated rules). No false positives to report.

## What's working

1. **The empty state** (`museum.html:4024`): "Nothing here yet. Anything you drop on the pill below is kept exactly as it arrived and read on this machine, in the order you found it. No folder, no tag, no reason required. Nothing here expires." This is perfect product copy — warm, clear, honest, teaches the interface. The design system should preserve this voice.
2. **The settings nav** (`museum.html:6761-6796`): Four rows with icon + label + description. The IA is right: AI, Features, Storage, Trash. Within working memory (4 items). Each row teaches what it contains. The shape is wrong (40px radius, warm palette) but the structure is excellent.
3. **The WCAG commentary** (`museum.html:69-120`): Every token in `:root` has a comment recording its contrast ratio, the rule it satisfies, and the constraint it creates. This is rare and valuable. The lavender overhaul must re-establish this rigor for the new tokens (PROGRESS.md Phase A.3 already requires it).

## Priority issues

### [P1] The entire palette is pre-overhaul — amber on cream, not lavender on white

**Why it matters**: Every visual element — surfaces, text, accent fills, borders, shadows, tints — uses warm tokens that `docs/DESIGN.md` replaces. The app looks like a different product from the one the design system describes. The 1.5px accent-edge workaround exists only because amber cannot clear 3:1; lavender can, so every accent component carries unnecessary visual weight.

**Fix**: Execute PROGRESS.md Phase A (token foundation) and Phase D (accent migration). Repoint every `:root` token to the DESIGN.md values, drop the 1.5px accent edges where lavender clears 3:1, and re-prove contrast per A.3.

**Suggested command**: `$impeccable layout` (the layout agent already found the radius and spacing mismatches; Phase A is the token swap).

### [P1] 40px card radius is a codex tell — DESIGN.md mandates 12px

**Why it matters**: `--r-lg: 40px` on `.card` (`museum.html:836`) and `.settings-nav-row` (`museum.html:1099`) reads as over-rounded. The impeccable skill bans 32px+ on cards. DESIGN.md section 5: cards use 12px (`--r-lg`), inputs use 8px (`--r-md`).

**Fix**: PROGRESS.md Phase A.1 replaces `--r-lg` with 12px. But the settings rows should not use `--r-lg` at all — a full-width list row with 12px corners on a container that already has a 1px border is fine, but the individual row corners should inherit the container's radius, not declare their own 40px.

**Suggested command**: `$impeccable layout`.

### [P1] Searchbar is pill-shaped — DESIGN.md reserves pill for status pills and tab toggles

**Why it matters**: `.searchbar { border-radius: var(--r-full) }` (`museum.html:244`) = 999px. DESIGN.md section 5: "Buttons use 8px corners. Never pill-round a button. Cards use 12px. Status badges use pill." The searchbar is an input, not a button, but the pill shape breaks the radius vocabulary. Under the new system, the searchbar should use `--r-md` (8px) to match inputs.

**Fix**: Change `.searchbar` radius from `var(--r-full)` to `var(--r-md)` (8px) in Phase C.3. The kbd hint's `var(--r-sm)` (6px) is fine.

**Suggested command**: `$impeccable layout`.

### [P2] "That answer could not be completed." is not recoverable from the chat view

**Why it matters**: When the answer worker fails (`chats_worker.py:75` except block writes `FAILED_TEXT`), the user sees "That answer could not be completed." — no cause, no fix, no link to Settings. The `ProviderError` message ("the endpoint rejected the API key") is more specific but still not actionable from the chat surface. Heuristic 9 (error recovery) scores 2 for this.

**Fix**: The failed-turn UI should carry a one-line cause and a link to the relevant settings section (e.g., "The API key was rejected. Check Settings → AI." with a clickable link to `showSettingsAI()`). This is a UX copy + interaction change, not a design system change.

**Suggested command**: `$impeccable clarify`.

### [P2] Settings AI sub-page presents 7+ fields simultaneously — over working memory

**Why it matters**: `showSettingsAI()` (`museum.html:6801`) renders: backend select, model, URL, retries, API key, headers, concept-layer rebuild — all at once, in one scroll. The cognitive load checklist's working memory rule says ≤4 items at a decision point; 7+ is overloaded. The "Save/Discard" bar at the bottom adds a deferred-decision concept the user must hold in mind while scrolling up to review.

**Fix**: Group the AI settings into two visual sections with a clear break: "Connection" (backend, model, URL, key) and "Behavior" (retries, headers, concept rebuild). This is the `distill` agent's task — the settings are already well-structured, they just need progressive disclosure or visual grouping to reduce simultaneous cognitive load.

**Suggested command**: `$impeccable distill`.

## Persona red flags

**Alex (Power User)**:

- No keyboard shortcut to open the artifact drawer toggle. `#drawerToggle` is click-only (`museum.html:4596`). Alex expects `⌘.` or a tab+Enter path to reach tags/summary without leaving the keyboard.
- No bulk actions on the wall. Alex cannot multi-select cards to pin, tag, or trash. Every action is one-at-a-time through the artifact view.
- The wall uses `content-visibility: auto` with `contain-intrinsic-size: auto 280px` (`museum.html:850`) — efficient, but Alex cannot `⌘F` search within off-screen cards because they are not rendered. The searchbar is the only find path.

**Jordan (First-Timer)**:

- The artifact header has 4 icon-only buttons (download, pin, drawer toggle, trash) at `museum.html:4582-4602`. Each has `aria-label` and `title`, but Jordan must hover to learn what each does. A first-timer on a touch device (no hover) sees four mystery icons.
- "Concepts (facets)" and "The concept layer" in Settings AI (`museum.html:6940`) is jargon. The aside explains it ("Re-analyze every item with the current model to rebuild the concept layer search uses"), but the term "concept layer" is never defined for the user. Jordan does not know what a facet is.
- The capture pill's `.keep` button says "Keep" with a disc icon. Jordan does not know what "Keep" means in this context — keep what? The pill is the primary action but its label does not say what it captures.

**Sam (Accessibility-Dependent)**:

- The greeting eye is `aria-hidden="true"` (`museum.html:4057`) — correct, it is decorative. But the pupil-following and blink are `pointermove`/`setTimeout` driven with no reduced-motion alternative beyond `mountEye()` returning early (`motionOk` check). The CSS `@keyframes eye-blink` has no `@media (prefers-reduced-motion: reduce)` override — the animation is JS-gated, so this is technically fine, but a CSS-level guard would be belt-and-suspenders.
- The pill's icon-only `.round` buttons (`museum.html:1227`) have `aria-label` attributes but no visible text. Tabbing to them shows a focus ring but no label for a sighted keyboard user who is not using a screen reader.
- The searchbar input has no `<label>` element — only `placeholder="Search everything"`. Placeholders disappear on focus and are not a label substitute.

## Minor observations

- `--sp-section` is declared twice in `:root` (`museum.html:178` at 48px, and a second declaration overrides to 24px). The layout agent already caught this (L.9).
- `--sp-4: 20px` is an odd value in a 4px-base scale — it is 5×4px, but the DESIGN.md scale has no 20px token (it goes 4, 8, 12, 16, 24). The overhaul should collapse 20px to either 16px or 24px.
- The `.pill .keep .disc` has `border: 1.5px solid var(--text)` (`museum.html:1206`) — the accent-edge workaround. Under lavender this border can be dropped, simplifying the disc to a plain fill.
- The `.greet-emblem` has `box-shadow: 0 6px 18px color-mix(in oklab, var(--accent) 38%, transparent)` (`museum.html:363`) — a colored glow. Under DESIGN.md's elevation system, the disc should use `--shadow-card` or `--shadow-micro`, not a custom colored shadow.
- `capture.html` duplicates the `:root` tokens (`capture.html:46-68`) with a note saying they are "copied rather than shared." Under the overhaul, both files must update in sync (PROGRESS.md Phase A.2 and Phase E.1).
- The `.card` uses `aspect-ratio: 1 / 1` (`museum.html:839`) — a square grid. This is a strong design choice (the wall reads as a grid of tiles), but square cards with 40px corners lose 40px of each corner to the curve. Under 12px radius this resolves itself.

## Questions to consider

- The pill says "Keep" — keep what? Would "Capture" or "Drop" or "Save" be clearer for a first-timer who does not yet know the product's verb?
- The artifact header has 4 icon buttons in a row with no visual grouping. Would grouping them (pin + drawer toggle together, download + trash apart) reduce the "four mystery icons" problem?
- The wall is a square grid of identical cards. The impeccable skill bans "identical card grids." The kind-dot system gives each card a hue, but the cards are still same-sized squares. Would varying card heights (content-based, not aspect-ratio-locked) break the monotony without losing the grid rhythm?
- "That answer could not be completed." — what if the failed turn showed the user's question back with a "retry" button and a one-line cause? Would that change the emotional valley from frustration to recovery?
