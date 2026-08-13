# PLAN.md - desktop polish, then sync, then a mobile Enqueue

This file is a work queue for an implementing agent, in the house style of `PROGRESS.md` and `docs/e2e/E2E.md`.
Do one checkbox per commit, verify each with its "Done when" line before checking the box, and keep every step atomic and idempotent.
Every task is `[AGENT]` work - there are NO mid-run human gates, so the agent never pauses waiting on Minh. Decisions are pre-baked inline (marked "DECISION, baked"). Minh reviews once at the very end, using the "Review when it's all done" section at the bottom.
Never use the em dash; plain dash only.

Queue order is desktop-first: the desktop phases (EYE, NOTE, FIX, SET) are independent, need no sync decision, and are worked first - EYE at the top. The sync and mobile initiative (Findings, the ratified decisions, SYNC, MOBILE) sits below them; sync is the foundation and mobile needs sync first.

---

## Phase EYE - the raven eye in the bottom ribbon (desktop UI only)

The home view already renders a living eye as the greeting emblem: a PNG eye whose pupil tracks the cursor (`src/enqueue/static/js/home.js`, the split frame plus pupil layer; assets `static/eye-frame.png`, `static/eye-pupil.png`, `static/eyeball.png`; styles in `css/home.css` under the greeting emblem).
The bottom ribbon's "Chat with AI" button still uses the flat SVG eye `svg("ask")` (`src/enqueue/static/js/pill.js`, two places: the wall ribbon and the in-chat ribbon).
This phase makes the ribbon eye the same living raven eye - purple pupil, cursor-tracking - and dials the weirdness up, with the click behavior unchanged. UI only.

- [x] **EYE.1 [AGENT]** Extract the eye into a reusable piece.
  Anchor: the eye markup (`home.js` lines ~709-716: `.eye` > `.eye-blinkwrap` > `.eye-socket` > `.eye-pupil` plus `.eye-frame`) and the tracking logic (`mountEye`/`tearDownEye`, `home.js` lines ~794-888; the listeners are `pointermove` and `mouseleave` on `document`, not `mousemove`).
  Move both into one small factory, `makeEye(el)`, that injects the markup into a given element and wires its tracking. Put the factory in `js/icons.js` (it loads second, before `pill.js`, so the pill can call it). If a new `js/eye.js` is created instead, it must be added in TWO places or it silently never loads and is never checked: the `<script>` tags in `home.html` (before `pill.js`) and the hardcoded `JS_ORDER` list in `bin/verify`.
  Three constraints the factory must respect:
  - The travel math already self-scales from the socket's rendered size (`home.js` lines ~854-862), so the same code works at emblem size and ribbon-button size; keep that property.
  - Listener lifecycle: the pill re-renders its `innerHTML` on every navigation, so a naive mount adds a new `document` listener each render. Use ONE shared document-level `pointermove`/`mouseleave` pair that iterates all mounted eyes (or an equivalent idempotent mount). Never stack listeners per render.
  - `getElementById("greetEye")` is hardcoded today; the factory takes the element as an argument instead.
  Done when: the home greeting eye still tracks the cursor exactly as before (including hover-holds-centred and the dead-zone), the eye is produced by one shared function, no duplicate listeners accumulate across home renders, and `bin/verify` passes.

- [x] **EYE.2 [AGENT]** Put the eye in the ribbon "ask" button.
  Anchor: the two `svg("ask")` uses in `pill.js` (aria-label "Chat with AI" on the wall, "Continue chat"/"Ask about this" inside a chat).
  Replace the static SVG with the shared eye at the ribbon button's size (the travel math self-scales, so no size-specific tuning); keep `onclick="openField('ask')"` and `chatOrAsk()` exactly as they are. Mount via the factory right after `pill.innerHTML` is set, once per rendered button, relying on EYE.1's shared listener so re-renders never stack listeners.
  Done when: the ribbon eye tracks the cursor, clicking it opens the ask field / continues the chat exactly as before, and the button's aria-label is unchanged.

**EYE.3 - folded into EYE.5, not a checkbox.** It was a verification step with no mechanical gate (`bin/check-contrast` cannot see PNGs), so an agent could tick it without looking. Its content - the pupil asset `eye-pupil.png` is ALREADY a vivid purple by design; do NOT mute it to lavender `#5e6ad2`; confirm it still reads purple at ribbon size - is now part of the human review.

- [x] **EYE.4a [AGENT]** Dilation. The ribbon pupil dilates on hover and constricts on click.
  One reduced-motion rule covers all of EYE.4a-c, stated precisely because the doc trail conflicts: cursor tracking is ratified as functional, not decorative (L.7/M.4, comment in `mountEye`), and RUNS EVEN under `prefers-reduced-motion` - do not disable it. Gate only the new effects behind the media query.
  Done when: hover visibly dilates, click visibly constricts, tracking is unaffected, and under reduced motion neither happens; `bin/verify` passes.

- [x] **EYE.4b [AGENT]** Idle saccades. When the cursor is still for several seconds, the eye glances to a random point, then returns to tracking.
  Done when: a still cursor produces an occasional glance that does not fight live tracking (a move during a saccade wins immediately), and reduced motion suppresses it; `bin/verify` passes.

- [x] **EYE.4c [AGENT]** Blinking, built new. There is NO existing blink cadence anywhere in the codebase (`.eye-blinkwrap` is only a positioning wrapper; no blink keyframes exist) - build it, at irregular 5 to 20 second intervals, as a quick lid scale/clip on the blinkwrap.
  Done when: the eye blinks at irregular intervals in the 5 to 20 second band, never on a fixed metronome, and reduced motion suppresses it; `bin/verify` passes.

- [x] **EYE.6 [AGENT]** The ribbon eye must show ONLY the eye, not the whole raven.
  DONE (verified in-app): added `static/eye-only.png` (the eye cropped out of `eye-frame.png` onto transparency - flood-filled the bird away, kept the almond + lashes, cleared the opening for the moving pupil); `makeEye` swaps the frame to it for `.pill-eye` (`js/icons.js`); `pill.css` overrides the ribbon socket to `52.6%/51.5%/80%/69.3%` to re-centre on the cropped eye, and bumps the ribbon pupil to `120%/156%` so the purple reads boldly at 34px (the shared `72.7%` is tuned to the emblem's larger iris and rendered as a faint dot at ribbon size). Confirmed live in the browser: `#pillEye` frame src is `/static/eye-only.png`, socket and pupil resolve to the new geometry, the pupil (`eye-pupil.png`) shows a bold purple and still tracks, the home emblem is still the full raven, and `bin/verify` passes.
  Current state: `makeEye` builds the frame from `/static/eye-frame.png` (`js/icons.js:62-63`), and both `eye-frame.png` and `eyeball.png` are the FULL raven (bird body plus a white panel holding an almond eye). At emblem size on the home greeting that full raven is the intended brand mark, but the ribbon "ask" button (`pill.js:73`, `makeEye(pillEye)`) reuses the same full-raven frame, so the small button renders the entire bird instead of the eye alone. Reference of what is wanted: an almond eye outline, three short lashes, and a filled vivid-purple pupil - the eye by itself, no bird.
  Anchor: `makeEye` and the frame/pupil construction in `js/icons.js:44-63` and `:336`, the ribbon mount `pill.js:73`, and the emblem mounts `home.js:709,741`. Change ONLY the ribbon (`pillEye`); leave the home greeting emblem as the full raven.
  Recommended: add an eye-only frame asset - crop the almond-eye region of the raven to a transparent PNG (for example `static/eye-only.png`) - and have `makeEye` use it for a ribbon-context eye (a variant flag or a second factory arg for the frame src), keeping `eye-pupil.png` as the tracking layer on top so the purple pupil still follows the cursor. Alternative with no new asset: CSS-crop the existing raven PNG to the eye's bounding box (a container with `overflow:hidden`, the image scaled/positioned to show only the eye), but then the tracking-pupil offset math - which keys off the socket's rendered size (`home.js` ~854-862) - must be re-aligned to the cropped box, so verify the pupil still lands on the cursor.
  Done when: the ribbon ask button shows only the eye (almond + lashes + purple pupil), matching the reference, with no bird visible; the pupil still tracks the cursor and the click behavior is unchanged; the home greeting emblem is still the full raven; and `bin/verify` passes.

Verify (EYE.1 to EYE.4c): `bin/verify` (JS parse plus contrast) passes and the ribbon's ask/chat actions still work end to end.

---

## Phase NOTE - the note title flow and first-line typing (desktop UI, shared with mobile Reader)

The note editor has three problems the person hit directly.

Findings (verified in the code, not guessed):

- **Char-stacking on the first line.** Typing into an empty note breaks each character onto its own line until Enter is pressed. Cause: an empty note mounts with `ctx.html = ""` (`src/enqueue/static/js/artifact.js:1024`), so the first keystroke lands in a bare text node with no block element. The `input` handler runs `applyInputRules` on every keystroke (`artifact.js:1035`), and the bare-text-node branch (`artifact.js:46-52`) wraps the current block in a fresh `<p>` each time, so every character spawns its own paragraph. Enter creates a real block boundary, which is why it "works" only after Enter.
- **The title is not editable.** The header title is a static `<div class="h1">` rendering `a.title || "Untitled"` (`artifact.js:334`); there is no way to click it and set a title.
- **The title is derived, but never live.** The backend already sets a note's title from its body: `notes.edit()` calls `title_from_body(body)` - first markdown heading, else first non-empty line, else `Untitled` (`src/enqueue/notes.py:24-39`, `notes.py:120`). But the desktop only shows the new title after a save and reload, so the person cannot see the first line becoming the title as they type.

Backend note: `PATCH /artifacts/{id}/body` already accepts an optional `title` (`src/enqueue/api/artifacts.py:378-393`, `BodyEdit{body, title}`), and `notes.edit(artifact_id, body, title=)` already honors it. When `title` is `None`, `notes.edit` re-derives from the body via `title_from_body`, so an explicit title is silently overwritten on the next body edit unless the explicit intent is persisted. That persistence is the one real decision (NOTE.0). `saveBody` (`artifact.js`) currently PATCHes `{body}` only, never a title.

- **NOTE.0 (DECISION, baked - no gate).** Title model: by default the title is the note's first line, derived live; an explicitly edited title overrides and must survive later body edits. Persistence is the robust option, no pause: add a `title_explicit` boolean column to `artifacts` in a new migration (next after `0021`), and have `notes.edit` re-derive from the body ONLY when `title_explicit` is false. Server-authoritative, survives sync (the E2E snapshot carries the field) and the mobile Reader. The client heuristic (infer explicit-ness by comparing stored title to `title_from_body`) was rejected as fragile across sync. If NOTE.3 already shipped a different persistence approach, the end-review flags it; otherwise build to this.

- [x] **NOTE.1 [AGENT]** Fix the first-line char-stacking so typing on line one behaves without pressing Enter.
  Anchor: `mountEditor` (`src/enqueue/static/js/artifact.js:1021-1035`) and the bare-text-node branch of `applyInputRules` (`artifact.js:43-52`). The fix is to guarantee the caret always sits inside a real block: when the editor mounts empty (`ctx.html` is empty), seed it with a single empty paragraph (`<p><br></p>`) and place the caret inside it, so the first keystroke never lands in a bare text node. Do not remove the bare-text-node guard in `applyInputRules` - it is the fallback; the seed is the fix.
  The markdown-shorthand rules must still fire on the first line: after the fix, typing `-`, `#`, `1.`, and `>` at the start of line one must still convert to a list / heading / quote exactly as before (that path runs through the same `RULES` in `applyInputRules`).
  Done when: opening a brand-new empty note and typing `testing` on the first line renders `testing` on one line (no per-character break) with no Enter pressed; the markdown shorthands above still convert on line one; a saved-and-reloaded note round-trips its body unchanged (no stray empty leading paragraph in the serialized markdown - check `htmlToMd`); and `bin/verify` passes.

- [x] **NOTE.2 [AGENT]** Render the first line as the title live, in the header, as the person types.
  Anchor: the header title `<div class="h1">` (`artifact.js:334`) and the editor `input` handler (`artifact.js:1035`). On each input, recompute the title from the current body the same way the server does and write it into the header `.h1`. Mirror `notes.py:title_from_body` exactly (first `#{1,6}` heading text, else first non-empty line, stripped of `*_\``, capped, else`Untitled`) so the live header matches what the server will store on save; if a shared JS helper does not exist, add one small function and reuse it, do not scatter the logic. When an explicit title is set (per NOTE.0), do not override it from the body.
  Done when: typing the first line of a note updates the header title in real time; clearing the first line reverts the header to`Untitled`; after`saveBody`, the header equals the server-returned`title` for the same body (no drift between the live derivation and `title_from_body`); and`bin/verify` passes.

- [x] **NOTE.3 [AGENT]** Make the header title click-to-edit, and persist an explicit title per NOTE.0.
  Anchor: the header title `<div class="h1">` (`artifact.js:334`), `saveBody` (`artifact.js`, the note branch that PATCHes `/artifacts/{id}/body`), and the existing route `PATCH /artifacts/{id}/body` with `BodyEdit{body, title}` (`src/enqueue/api/artifacts.py:378-393`) plus `notes.edit(..., title=)` (`src/enqueue/notes.py:97-128`). Clicking the title makes it editable (an inline input or a `contenteditable` header); committing (blur or Enter) sends the explicit title to the backend, and the persistence chosen in NOTE.0 keeps it from being re-derived on the next body edit. Provide a way to clear an explicit title back to first-line-derived (for example, committing an empty title reverts to derived). Escape cancels without saving.
  Done when: clicking `Untitled`, typing a title, and blurring persists it; reloading the note shows the explicit title; editing the body afterward keeps the explicit title (it is not clobbered by `title_from_body`); clearing the title reverts to the live first-line derivation from NOTE.2; and `uv run pytest -q` covers `notes.edit` preserving an explicit title across a subsequent body-only edit.

Verify (NOTE.1 to NOTE.3): `bin/verify` passes, `uv run pytest -q` is green, and a manual pass in the desktop app shows first-line typing, live title, and click-to-rename all working.

---

## Phase FIX - two live bugs carried over from the old search plan

Carried from the retired search-floor PLAN.md because they are still real in the code, both user-visible. The rest of that plan was HUMAN review gates and eval calibration and was intentionally dropped.

- [x] **FIX.1 [AGENT]** Stop discarding a good grounded answer that has no citations (the "That answer could not be completed" failure).
  Repro: a chat question whose model returns a correct grounded answer with `cited: []` is rejected and the whole turn fails. The `Answer` validator still raises "grounded is true but nothing is cited" at `src/enqueue/schemas.py:291`.
  Anchor: the validator in `src/enqueue/schemas.py:291` and `chats._ask_model` / `run_answer` in `src/enqueue/chats.py`. Salvage the answer instead of throwing: prefer a best-effort backfill of citation ids from the passages actually fed to the model; if none can be matched, downgrade `grounded` to `false` and keep the answer rather than failing the turn. Do not weaken the schema into meaninglessness - a grounded claim should still try to cite - but a missing citation must never nuke a correct answer.
  Done when: the repro question returns the model's answer (not the failure string); an answer that genuinely cites still carries its citations; and `uv run pytest -q` covers the grounded-but-uncited case surviving.

- [x] **FIX.2 [AGENT]** Close the chat-side floor leak in `chats.passages()` (the old Q.10). The chunk branch already faces the two-tier floor (`src/enqueue/chats.py:244-289`), but the facet branch (`chats.py:344-357`) and entity branch (`chats.py:360-372`) still add hits with no floor check, so an answer can ground on a weak facet/entity vector match the same way `/search` used to.
  Anchor: the facet and entity branches of `chats.passages()` in `src/enqueue/chats.py`. Apply the same rule Q.7 applied to `/search`: a dense-only facet/entity hit faces the two-tier gate (keep >= `KEEP_ABOVE`, drop < `DROP_BELOW`, gray zone -> `judge_gray_zone`); only a real lexical leg bypasses. Reuse the shared floor helpers (`_floor_verdict`, `judge_gray_zone` from `retrieve.candidates`) already imported at `chats.py:244`, do not copy the logic.
  Done when: a chat question whose only matches are weak facet/entity vectors feeds the answer model nothing (so it refuses honestly), a real question still retrieves its passages, and `uv run pytest tests/test_chats.py -q` is green.

## Phase SET - simplify the model settings (desktop)

The desktop Settings screen mishandles the model config. Findings (verified in the code):

- The Settings screen exposes an editable **Endpoint** field (`llm_url`) that is redundant and actively breaks hosted backends. The provider reads the `llm_url` setting and only falls back to the backend's real URL when it is empty (`src/enqueue/providers/base.py:143-146` and `:164`: `base_url = url or backend["url"]`). `llm_url` defaults to `config.OLLAMA_URL` = localhost (`src/enqueue/settings.py:46`, keyed to `ENQ_OLLAMA_URL`), no matter which backend is picked. So choosing `opencode-go` while `llm_url` is still localhost points the hosted backend at localhost and fails; deleting the field "works" only because an empty value falls through to `backend["url"]`.
- For every named backend the correct URL already lives in `config.BACKENDS[name]["url"]` (`config.py:29-69`). Only the `custom` backend needs a user-typed URL.
- The "defaults to kimi" model is not a code default (the code default is `llama3.1:8b`, `config.py:82`); it is a stale value stored in the settings JSON. Once the endpoint stops overriding the backend, a stale model is just a value the person retypes.
- OpenCode Zen (`opencode`) and OpenCode Go (`opencode-go`) are two real products with separate billing/entitlement - a Go key has no Zen access, per the `config.py` comments. Keep both; only the labels need to be clearer.

The simplification: for a named backend the endpoint is implied by the backend, so Settings becomes just backend + model + API key. Only `custom` keeps an endpoint field.

- [x] **SET.1 [AGENT]** Make the endpoint derive from the chosen backend, and stop exposing it for named backends.
  Anchor: `src/enqueue/providers/base.py:140-146` and `:161-164` (both the vision and text provider builders), `src/enqueue/settings.py:46` (the `llm_url` field), and the Settings UI `src/enqueue/static/js/settings.js` (the field loop at `:279` renders `llm_model` + `llm_url`; the backend-switch at `:439-446` stages `llm_url = spec.url`).
  Backend: for a named backend use `config.BACKENDS[name]["url"]` directly; read the stored `llm_url` only when the backend is `custom`. Local-only artifacts keep routing to the Ollama URL exactly as now. A stale stored `llm_url` (localhost from before) must never override a named backend's URL.
  Frontend: render the Endpoint (`llm_url`) field ONLY when the chosen backend is `custom`; drop the `llm_url` staging on backend switch for named backends.
  Done when: picking `opencode-go` with a valid key works with NO endpoint field shown and no localhost anywhere in the path; picking `custom` shows the endpoint field and uses it; switching backends never leaves a stale URL that overrides the choice; and `bin/verify` passes.

- [x] **SET.2 [AGENT]** Clarify the two OpenCode backends so the split is not confusing.
  Anchor: the `label` fields for `opencode` and `opencode-go` in `config.py:43,54`, rendered by the backend `<select>` in `settings.js:246-265`.
  Make the labels state the billing split plainly (for example "OpenCode Zen (Zen key)" and "OpenCode Go (Go subscription key)") so it is obvious the two use different keys. Labels only, no behavior change.
  Done when: the backend picker names make the Zen-vs-Go key distinction obvious and nothing else changes.

Verify (SET.1 to SET.2): `bin/verify` passes, `uv run pytest -q` is green, and Settings shows no endpoint field for any named backend.

---

## Phase ANIM - the raven-in-motion loading and capture-success animations (desktop UI)

Two brand-motion moments, both driven by new assets **already added** to `src/enqueue/static/`: `capture-bird.png` (the raven flying left with speed lines, source `~/Downloads/capture.png`) and `loading.png` (the wings-up raven, source `~/Downloads/loading.png`). The point is one consistent, slightly-unhinged raven doing every "wait" and every "captured" beat in the app - branding through motion.

Motion thesis (from the animate lens):

- Focal moment: the capture-success flight - a rehearsed one-off the app has earned; it fires only on a successful quick capture.
- Feedback everywhere else: a single spinning-raven loader replaces every ad-hoc text-only "...ing" state, so "the app is working" always looks the same.
- Rules that hold for both: animate `transform`/`opacity` only; arrivals decelerate on `cubic-bezier(0.16, 1, 0.3, 1)` and exits are faster than entrances; `will-change` only while animating; the loader stops when its element is removed or hidden; and every effect has a `@media (prefers-reduced-motion: reduce)` alternative (the spin becomes a static raven, the flight becomes a plain fade).

- [x] **ANIM.1 [AGENT]** Build one reusable spinning-raven loader that everything below uses.
  Asset already in place: `src/enqueue/static/loading.png`. Add a component (a markup helper plus CSS) that shows `loading.png` rotating COUNTER-clockwise: `@keyframes spin-ccw { to { transform: rotate(-360deg); } }`, about 1.1s linear infinite, GPU transform only. Two sizes via a modifier class: large (~64px, for full-view waits) and small (~24px, for inline/conversation waits). The large variant stacks an optional caption BELOW the bird, centred; the small variant is bird-only or bird plus inline text. Put the CSS in a shared stylesheet (`css/base.css`, or a new `css/loader.css` added BOTH to `home.html`'s `<link>` list and `bin/verify`'s `JS_ORDER`/stylesheet order if a new file), and a JS helper (for example `spinner(size, caption)` in `js/util.js` or `js/icons.js`) that returns the markup so no caller hand-rolls it.
  Reduced motion: under `prefers-reduced-motion: reduce` the bird does not spin - it sits static and the caption still communicates the wait. Never a blank, never a spinner that vanishes.
  Done when: `spinner("lg","searching...")` and `spinner("sm")` render the rotating raven at both sizes, rotation is visibly counter-clockwise, reduced motion shows a still raven, and `bin/verify` passes.

- [x] **ANIM.2 [AGENT]** Search shows the big centred raven instead of the top-left text. Today `search.js:24` sets `<div class="state thinking">searching...</div>`.
  Anchor: `src/enqueue/static/js/search.js:24` and the sibling message branch at `:34`. Replace the text-only state with the large `spinner("lg","searching...")` - the spinning raven centred in the results view with "searching..." below it, not a top-left label. Keep the existing timing and clearing logic; only the rendered markup changes.
  Done when: starting a search shows the counter-clockwise raven centred with "searching..." beneath it, results replace it when they arrive, reduced motion shows the still raven, and `bin/verify` passes.

- [x] **ANIM.3 [AGENT]** Conversations use the small spinning raven. Today the pending/"thinking" turns render text bubbles (`chat.js:40` "reading what you saved...", `:159` "Reading what you saved...", `:209`/`:454` "Building the view...", `:340` "moving it...").
  Anchor: the thinking/pending states in `src/enqueue/static/js/chat.js`. Put the small `spinner("sm", ...)` in the pending assistant bubble and the other in-chat waits, keeping the existing wording as the caption beside or below the small bird. The poller/refresh logic is unchanged; only the waiting markup changes.
  Done when: a pending chat turn shows the small counter-clockwise raven with its wording, it clears when the turn resolves, reduced motion shows it still, and `uv run pytest -q` plus `bin/verify` pass.

- [x] **ANIM.4 [AGENT]** The capture-success flight. On a successful quick capture, `capture-bird.png` flies in from the left edge to screen centre, holds ~1s, then fades away.
  Anchor: the quick-capture success paths - `keep()` / `keepFiles()` in `src/enqueue/static/capture.html` (the overlay window) and the `toast("Saved.")` site in `src/enqueue/static/js/pill.js:220` (`toast` is defined in `js/util.js:43`). On success, mount a `position: fixed`, `pointer-events: none`, high-z `<img src="/static/capture-bird.png">` and run: enter left→centre via `transform: translateX(...)` over ~600ms on `cubic-bezier(0.16, 1, 0.3, 1)` (the asset's speed lines already read as flight), hold 1000ms, then fade `opacity` to 0 over ~300ms and remove the element. `will-change: transform, opacity` only during the run. It must not block interaction or steal focus.
  Reduced motion: no fly-in - a plain fade in, hold ~1s, fade out, same asset.
  Small choice the agent may make: whether the flight replaces the "Saved." toast or plays alongside it; default alongside, since the toast also serves screen readers.
  Done when: completing a quick capture flies the raven from left to centre, it holds ~1s and fades, it never blocks clicks or the next capture, reduced motion fades instead of flies, and rapid repeated captures do not stack birds (a second capture restarts/replaces the first).

- [x] **ANIM.5 [AGENT]** Brand sweep: every remaining loading state uses the spinning raven, so nothing waits with bare text.
  Anchors (from the audit): `home.js:300` and `:671` "opening...", `home.js:952` "loading more...", `artifact.js:432` "reading...", `trash.js:36` "...", `pivot.js:276/311/332/355/495` ("removing it..."/"restoring it..."/"adding it..."/"moving it..."), `pivot.js:411` "Loading your library...", and any other `class="state"` / `class="state thinking"` site. Full-view waits get `lg`; inline/row waits get `sm`. Keep each existing wording as the caption. Finish with a grep for `state thinking` and for bare `>...ing<` loaders to confirm none were missed.
  Done when: a grep shows no bare-text loading state left (each routes through `spinner(...)`), the raven is the single loading mark across search, chat, pivots, wall paging, artifact read, trash, and settings, and `bin/verify` passes.

Verify (ANIM.1 to ANIM.5): `bin/verify` and `uv run pytest -q` are green, and a manual pass shows the raven as the single loading/capture motion across the app.

---

## Phase CAP - refactor the quick-capture overlay to the dequeue format (desktop)

The quick-capture overlay was clunky. It is being reshaped to the dequeue capture format (a contained card: a prominent input box with a Keep button under it), in the app's bold purple.

Current state - ALREADY in the working tree, uncommitted, do NOT redo:

- `capture.html` reshaped: a card that fills the transparent window, a prominent tinted input box (`#fieldbox`) with a purple focus ring, a caption row (kind dot + label + status), and a bold-purple `Keep` button bottom-right.
- The overlay wears the eye's bold purple (`--purple-bold` `#60079f`) on the disc, focus edge, and Keep button (capture-local tokens, kept in sync with `tokens.css` so `bin/check-contrast` passes).
- Fixed: the `disc` crash (keptBeat referenced an undeclared handle, so every keep reported "Not kept: Can't find variable: disc"); the flying-bird asset (`capture-bird.png` had the transparency checkerboard baked in as RGB - now a clean transparent bird); and cache-busting on the bird + eye PNGs, which load via `img.src` and so skipped the versioned `<link>`/`<script>` cache-buster.
- Flow reordered in `keep()`: on success the card fades (`#card.kept`), the raven flies, then the window dismisses.
- `desktop/src/main.rs:457` capture window resized from `580x132` to `600x264` to hold the box + button (Rust - needs a rebuild to take effect).

- [x] **CAP.1 [AGENT]** Rebuild the shell and verify the new card fits.
  The window resize is Rust, so a plain `bin/relaunch` does NOT apply it (the binary was older than `main.rs`, which is why the card was crammed into 132px and the input text clipped). Rebuild with `bin/relaunch --build` (it runs `cargo build`), then verify.
  Anchor: `src/enqueue/static/capture.html` (`#card` / `#fieldbox` / `#field` / `#foot` CSS), `desktop/src/main.rs:457`.
  Done when: after `bin/relaunch --build`, the overlay shows the whole card - input box with text sitting top-left (not clipped), the caption row, and the fully-visible `Keep` button - the drag strip drags the window, and `bin/verify` passes.

- [x] **CAP.2 [AGENT]** Markdown-as-you-type in the capture box. Today `#field` is a plain `<textarea>`; it should render markdown live like the note editor (`-` becomes a bullet, `#` a heading) and serialize back to markdown on keep.
  Anchor: the `<textarea id="field">` in `capture.html` and the note editor's live-markdown logic in `src/enqueue/static/js/artifact.js` (`applyInputRules`, the `RULES` table, `htmlToMd`) plus `md()` in `js/md.js`. Replace the textarea with a `contenteditable` div, wire the same input-rule conversions (bullets, numbered lists, headings, quote), keep the placeholder via `:empty::before`, and on keep read the serialized markdown (`htmlToMd`) instead of `field.value`. `paint()` / kind detection and the paste + drop handlers must read the editor's text content, not `.value`.
  Reuse, do not fork: load `md.js` / the serializer into `capture.html` (add the `<script>`) rather than copying it.
  Done when: typing `- a` Enter `- b` shows a real bullet list, a `#` line shows a heading, keeping stores the correct markdown body (verify the saved note round-trips), link/note/image kind-detection still works, and `bin/verify` passes.

- [x] **CAP.3 [AGENT]** Make the capture-success raven visible. In the 600x264 overlay the bird is a tiny quick sweep - "barely see it." Do (a): fire the existing full-screen main-window flight (`util.js captureFlight`, `css/base.css .capture-flight`) when a capture completes, so the raven flies across the whole screen. Fall back to (b) - enlarge and slow the in-overlay flight so it reads - ONLY if (a) proves impossible after one real attempt at the cross-window signaling, and record why in the checkbox note. Either way, ensure no bird persists after (the flight img must be removed; a stale bird was seen top-left).
  Anchor: `captureFlight()` in `capture.html` and `src/enqueue/static/js/util.js`, the `.capture-flight` keyframes in `capture.html` and `css/base.css`, and the `keep()` flow.
  Done when: completing a capture shows a clearly visible raven flight, a DOM check confirms the flight `<img>` is removed after each run (no bird remains), and the overlay dismisses cleanly.

- [x] **CAP.4 [AGENT]** Verify the whole capture flow end to end from the reshaped overlay: a bare URL becomes a link, a URL plus words becomes link + note, plain text becomes a note, and a pasted or dropped image becomes an image artifact. Image paste was previously blocked by the `disc` crash.
  Anchor: `keep()`, `keepFiles()`, the `paste` and `drop` handlers in `capture.html`.
  Done when: each of the four kinds creates the right artifact from the overlay, image paste works, the overlay dismisses and resets on the next summon, and `uv run pytest -q` plus `bin/verify` are green.

Verify (CAP.1 to CAP.4): after `bin/relaunch --build` the overlay shows the reshaped card, markdown renders as you type, the raven flight is visible, all four capture kinds work, and `bin/verify` passes.

---

## Findings - how the three reference systems actually sync

Researched before scoping so the plan does not cargo-cult the wrong model.

### dequeue (the user's todo app) - cloud-authoritative, SSE push

- A cloud backend holds the canonical data; clients are thin. Not local-first.
- Live updates ride Server-Sent Events: `GET /events?token=<jwt>`, named events (`task`, `template`, `phrase_override`, `settings`), the server pushes "this changed" and the client re-fetches. `frontend/src/api/sync.ts`.
- The token is a query parameter because `EventSource` cannot send headers; validated on connect.
- Auto-reconnect on transient drops (the library's own `pollingInterval`; do not add a second reconnect loop on top); `403` is treated as terminal, `401` means refresh-and-retry once.
- Takeaway for Enqueue: borrow the SSE transport shape (query-token auth, named events, reconnect discipline), NOT the cloud-authoritative model. Enqueue is local-first and has no accounts.

### Obsidian Sync - local-first, E2E relay, per-file versions

- An off-site remote vault (a relay) holds encrypted copies; a full local copy is always on every device (works offline). Confirmed from the help page; the rest is the widely-known architecture.
- End-to-end encrypted: the client encrypts, the relay is a byte store that cannot read content.
- Live propagation over a persistent connection; per-file version history kept (encrypted) on the relay; selective sync by folder and size limits per file.
- Takeaway for Enqueue: this is the right spirit - local-first plus a dumb encrypted relay. It is what `E2E.md` already designed, minus a live-push relay.

### Enqueue today - local-first, no cloud, and a sync plan already written

- Local Python engine on `127.0.0.1:8787`, one SQLite library file, a Tauri v2 desktop shell (`desktop/`, `tauri = "2"`), static UI split into `src/enqueue/static/js/*` and `css/*`.
- `docs/e2e/E2E.md` already specifies sync: one encrypted canonical snapshot per artifact, last-writer-wins per artifact, no event log, provider-agnostic (any synced folder is a dumb byte replicator), PyNaCl / XChaCha20, phases E1 to E8.
- None of E1 to E8 is built. There is zero sync code in the repo today; every SYNC step below that names an E2E.md piece must build it first.
- E2E.md is stale in two places: it syncs `exhibits`/`exhibit_members` (dropped in migration 0019; `saved_pivots` carry that concept now) and it deletes `lens_judgments` rows on purge (the lens was removed in Phase M). Read E2E.md for the snapshot/LWW/crypto design only; substitute `saved_pivots` for exhibits wherever it says exhibits, and ignore the lens references.
- That design is Obsidian's model with a synced folder instead of a relay. A folder works desktop-to-desktop; it is awkward on iOS where app access to iCloud Drive or Dropbox folders is restricted.

### The synthesis this plan adopts

- Keep `E2E.md`'s per-artifact encrypted-snapshot LWW as the sync core. Do not re-design it.
- Add a dumb, end-to-end-encrypted relay as the transport (Obsidian's relay), because mobile cannot reliably use a shared folder. The relay stores `.enc` snapshots and content-addressed blobs and can read none of it.
- Give the relay an SSE stream for "something changed, pull" (dequeue's transport), so edits appear live instead of on a timer.
- Mobile runs no Python engine and no model. It captures (writes snapshots into sync) and reads (browses and reads the synced library plus keyword search). All AI enrichment - facets, entities, embeddings, chat - stays on the desktop and syncs down as derived data. This matches the user's ask: "very simple - capture links, pictures, notes, and read all the artifacts."

---

## The decisions behind sync and mobile (all baked - no gate)

These are genuine forks; scoping both is cheap, guessing is not.

- [x] **D.1 [HUMAN]** Relay vs synced-folder for the sync transport.
  DECISION (Minh): relay-first. A dumb E2E relay (Obsidian model) - the only transport that serves mobile cleanly and gives live push. The synced-folder path from `E2E.md` stays valid for desktop-to-desktop and can coexist.

- [x] **D.2 [HUMAN]** Where the relay runs.
  DECISION (Minh): self-hosted on Railway. Deploy the relay (the SYNC.2 FastAPI service) as a Railway service with a persistent volume (SQLite + blob files on the volume; Railway Postgres is an alternative for the index). It stores only encrypted blobs and metadata (device namespace, cursor, timestamps) and never sees plaintext (DEC-B, DEC-C in `E2E.md`). Every device points at the Railway URL as its `SYNC_RELAY_URL`.

- [x] **D.3 [HUMAN]** Mobile platform.
  DECISION (Minh): Tauri v2 mobile, **Android first**, reusing the DESIGN.md system and a new simple mobile UI. One shell language (Rust) with the existing desktop, native capture plugins (share sheet, photo picker), a local SQLite read copy. iOS is the follow-on. (PWA and native were the rejected alternatives - PWA has the weakest native capture, native is the most work.)

- [x] **D.4 [HUMAN]** Ratify that mobile is capture-and-read only, with no model on device and no semantic search on device (keyword/FTS only), and that AI enrichment syncs down from the desktop. If mobile must do AI, that is a much larger plan and this one does not cover it.
  DECISION (Minh): ratified. Capture + read only, no on-device model, keyword/FTS search only, AI enrichment syncs down from the desktop.

---

## Phase SYNC - the relay and live transport (the foundation)

Gated on D.1, D.2. Build on `E2E.md` (read it first).

**This phase is built in two stages, plaintext first.** Encryption is a thin, separable layer: the snapshot format, the relay protocol, push, pull, SSE, and the LWW merge all move opaque bytes and do not care whether those bytes are encrypted. So the sync mechanics are proven with plaintext snapshots on a localhost/LAN relay (SYNC.1 to SYNC.7), and encryption is folded in afterward by wrapping the bytes at the relay boundary only (SYNC.8 to SYNC.9). Building this order de-risks the uncertain part (does sync actually converge across two devices?) without paying the crypto cost up front, and adds almost no rework because the two stages share the code.

What is deferred and what is not:

- **Deferred to stage two:** `E2E.md`'s E1 and E2 (crypto and keyring). The prototype does not encrypt.
- **NOT deferred, required in stage one:** `E2E.md`'s snapshot model and last-writer-wins merge (Phase E3: `sync/snapshot.py` plus its convergence property tests; sections 0 and 1 are the prose and glossary that define them). Encryption protects confidentiality; the LWW merge protects the data itself from silent loss. Dropping crypto for a test is fine. Dropping convergence correctness is not - that is the part that eats edits without telling you, and it is required from the first plaintext commit.

The relay stays a dumb byte store throughout: it holds per-device snapshot objects and content-addressed blobs, serves them back, and streams a "something changed" signal. It parses nothing. In stage one those bytes are plaintext canonical-JSON snapshots; in stage two they are the same bytes encrypted, and the relay code does not change.

- **SYNC.0 (DECISION, baked - no gate).** Two-stage order ratified: build the plaintext prototype first (SYNC.1-SYNC.7), then fold in encryption (SYNC.8-SYNC.10). The prototype is localhost/LAN only, throwaway data, never a hosted relay, never real notes, never shipped - it exists only to prove convergence and the live transport. Encryption (stage two) is mandatory before any real data or any non-localhost relay; the `SYNC_PLAINTEXT_PROTOTYPE` guard (SYNC.3b) enforces this in code, so no human gate is needed to hold the line. Prerequisite the agent must honor: E2E.md's Phase E3 (snapshot model + LWW merge + convergence property tests) is the bulk of stage one and must be built ahead of SYNC.4; only E1/E2 (crypto) are deferred to stage two.

- [x] **SYNC.1 [AGENT]** Specify the relay protocol as a short document `docs/sync-relay.md` before writing a server.
  It must define, concretely: the auth model (a per-library shared secret or device token, since there are no user accounts), the object namespace (`dev/<device_id>/artifacts/<id>.enc`, `blobs/<blob_name>`, mirroring `E2E.md`'s glossary except its `exhibits/` path - exhibits were dropped; saved-pivot sync is out of scope for this plan), and the four operations: list-changed-since, get-object, put-object (write-by-unique-name, never overwrite in place), and subscribe (SSE).
  Done when: `docs/sync-relay.md` names every endpoint, its request and response shape, and states plainly that the relay stores opaque bytes and can decrypt nothing.

- [x] **SYNC.2 [AGENT]** Implement the relay as a standalone service (its own small FastAPI app, not inside the local engine).
  Endpoints from SYNC.1: `GET /sync/objects?since=<cursor>` (list changed object names plus a new cursor), `GET /sync/object/<name>` (bytes), `PUT /sync/object/<name>` (store bytes, reject overwrite of an existing name), `GET /sync/events?token=<secret>` (SSE stream emitting an event whenever any object changes).
  The relay stores objects on disk or object storage keyed by name; it parses none of them.
  Done when: a test can `PUT` an opaque blob, `GET` it back byte-identical, `list` shows it after a cursor, and an SSE client receives an event on the `PUT`.

- [x] **SYNC.3 [AGENT]** Add a `SYNC_RELAY_URL` and a per-library sync secret to the engine's settings (alongside the existing settings, encrypted secret in the Keychain like the API key), plus a device token derived per `E2E.md`.
  Done when: `GET /settings` reports whether a relay is configured, and the secret is stored in the Keychain, never in a file.

- [x] **SYNC.3b [AGENT]** The plaintext-prototype safety guard. Add a single module-level flag (for example `SYNC_PLAINTEXT_PROTOTYPE = True`) and a hard check on the push/pull path: when the flag is set, the sync client refuses to run against any `SYNC_RELAY_URL` whose host is not `127.0.0.1`, `localhost`, or a private-LAN address, raising a clear error rather than uploading.
  This makes it impossible for the unencrypted prototype to quietly graduate to a real or hosted relay. The flag flips to `False` only in SYNC.9, after encryption is in.
  Done when: pointing the sync client at a non-local URL while the flag is set raises and uploads nothing; pointing it at localhost works.

- [x] **SYNC.4 [AGENT]** Push: when a local artifact snapshot is written, also `PUT` its snapshot object and any new blobs to the relay under this device's namespace. The snapshot producer does not exist yet - E2E.md Phase E3 (`src/enqueue/sync/snapshot.py`: `read_artifact_snapshot`, `serialize`, `winner`, `apply_snapshot`) must be implemented first, per SYNC.0. In the prototype the object is the plaintext canonical-JSON snapshot (`E2E.md` section 1); after SYNC.8 it is the same snapshot encrypted (`.enc`), and this push code is unchanged except for the one wrap call.
  Idempotent: re-pushing an unchanged snapshot is a no-op (same name, already present).
  Done when: editing an artifact on the desktop results in its snapshot object appearing on the relay, and re-running the push uploads nothing new.

- [x] **SYNC.5 [AGENT]** Pull: a background sync worker (reuse the shared `Worker` class in `src/enqueue/worker.py`) that, on an SSE event or on a timer fallback, lists changed objects since its cursor, downloads them, and feeds them to the LWW merge from E2E.md Phase E3 (built in SYNC.4's prerequisite) to update local state.
  The SSE client mirrors dequeue's discipline: query-token auth, auto-reconnect on transient drop, a terminal state on auth rejection, a heartbeat.
  Done when: an artifact edited on device A appears on device B within seconds of the edit, with byte-identical local state (the E2E.md convergence invariant), and no polling storm when idle.

- [x] **SYNC.6 [AGENT]** Conflict surface: when LWW discards a losing edit (DEC-A), keep the losing snapshot as a local version row (E2E.md already requires this) and surface it in the UI as a recoverable prior version, so a lost edit is never silently gone.
  Done when: two offline edits to one artifact resolve to the newer, and the older is visible and recoverable in that artifact's version history.

### Stage two - fold in encryption (mandatory before any real data or non-localhost relay)

Only after SYNC.7 passes. This wraps the bytes at the relay boundary and touches nothing else - the snapshot model, LWW merge, relay, push, pull, and SSE are all unchanged.

- [x] **SYNC.8 [AGENT]** Implement `E2E.md`'s E1 and E2 (crypto and keyring) if not already done, then wrap the boundary: `encrypt(snapshot_bytes, dek)` immediately before every `PUT`, `decrypt(bytes, dek)` immediately after every `GET`, and content-address blobs by `blob_name(content_hash, dek)` (all per `E2E.md`). The relay still stores and streams opaque bytes and its code does not change.
  Done when: relay objects are now ciphertext (a raw `GET` from the relay yields no readable JSON), and the two-device convergence test from SYNC.5/SYNC.7 still passes byte-identically through the encrypted path.

- [x] **SYNC.9 [AGENT]** Flip `SYNC_PLAINTEXT_PROTOTYPE` to `False` (SYNC.3b) so a non-local relay is now allowed, since the bytes are encrypted. Re-run the E2E.md convergence property tests (E3) over the encrypted path.
  Done when: the flag is `False`, a non-local relay URL is accepted, a raw fetch from it is unreadable ciphertext, and E3 convergence still holds.

Verify (SYNC.2 to SYNC.6, plaintext stage): the relay's own test suite is green, `uv run pytest -q` is green, and a scripted two-engine LAN test shows convergence.
Verify (SYNC.8 to SYNC.9, encrypted stage): the same convergence test passes through ciphertext, a raw relay object is unreadable, and E2E.md's E3 property tests pass.

---

## Phase MOBILE - a simple capture-and-read Enqueue

Gates cleared: D.3 (Android-first) and D.4 (capture+read only) are baked, Phase SYNC is done (relay + push/pull + LWW + encryption, all green), and the Android toolchain is provisioned (see MOB.2 - it already builds and launches on a Pixel). So this phase is ready to work top to bottom. Mobile is a thin client: it syncs the encrypted library from the relay into a local read copy, lets the person capture and read, and runs no model.

Scope, fixed: capture a link, capture a picture from storage or the camera, write a note; browse and read every artifact; keyword search over the synced text. Nothing else. No facets, no entities, no chat, no semantic search, no organize - those are desktop-only, and per MOB.0 they are desktop-DISPLAYED too (the snapshot carries no derived AI data); the mobile reader displays content plus annotations only.

### Design (shape plus layout brief, no code)

Mode: Operate. The person reaches for mobile in two moments - to toss something in quickly (capture), and to look something up or read (browse/read). Both must be one thumb, two taps.

Visual world: inherit DESIGN.md exactly (light canvas, scarce muted lavender `#5e6ad2`, hairlines, whisper shadows, IBM Plex Sans). No new brand. The raven eye may appear as the app mark.
Type is IBM Plex Sans (vendored woff2 in `static/fonts/`, weights 400/500/600/700), never Inter - if any doc disagrees, `--sans` in `css/tokens.css` is the truth.
Mono is the system mono stack (`--mono` in `tokens.css`), not a webfont.
The mobile page imports `css/tokens.css` VERBATIM via a RELATIVE path and adds zero new tokens.

Structure (three surfaces, navigation pre-baked - do not re-litigate):

- Library is the home surface: a single scroll, newest first, with the SAVED / EVERYTHING ELSE shelf headers the desktop wall uses.
- The capture control is the one fixed element: a bottom-anchored bar (safe-area padded) holding the capture button; everything else scrolls. There is NO bottom tab bar (two destinations do not earn one) and no hamburger menu.
- Search lives as a field in the top app bar of the Library surface, not as a tab.
- Reader is pushed over Library. The Android system Back gesture/button MUST pop Reader back to Library and must never be trapped or hijacked - wire the webview history so Back works (the Android slop test).
- Capture is a sheet over the home surface: one field, auto-focused, with the IME inset handled so the field never hides behind the keyboard.

Surface specs (build to these, do not improvise):

- Capture: the primary action, always one tap away (the fixed bottom control, plus the share-sheet target so other apps push into Enqueue). One field, same four-outcomes logic as the desktop overlay (a URL becomes a link, text a note, an image an image) so behavior is identical across surfaces. The capture button wears the eye's vivid purple `--purple-bold` `#60079f`, matching the desktop capture overlay - capture is the brand moment, not the lavender accent. Plain text field on mobile: the desktop overlay's live-markdown (CAP.2) is desktop-only, do not port it.
- Library: rows, not the desktop's square cards. Row anatomy: a kind dot in the desktop's kind colors, the title (IBM Plex Sans 500, two-line clamp), a two-line muted snippet, a relative timestamp, and a thumbnail for image artifacts and link-preview pictures. States that must exist as DESIGNED states, not bare text: first-sync loading (the ANIM.1 raven spinner asset, bundled), the empty library before any sync, captures with no snippet, over-long titles, and rows captured on the phone that the desktop has not enriched yet.
- Reader: the full artifact, read-only, per MOB.0's display scope. Per kind: a note renders its markdown (reuse `js/md.js`, loaded by relative path); an image gets a full viewer with pinch zoom; a link renders its stored preview card (image, title, description, site name) and tapping it opens the URL in the system browser; a PDF renders through a VENDORED pdf.js build over the synced blob (there is no Python on the device - do not port pymupdf, do not fetch a CDN pdf.js). Annotations show below the content. There is NO "summary" field - none exists in the data model - so never render a summary placeholder.

Layout theses (from the layout lens): reading order is capture-first on the home surface, then the library; grouping by the SAVED / EVERYTHING ELSE shelves the desktop already uses; touch targets at least 48dp with 8dp separation (Android's rule - it overrides DESIGN.md's desktop 40px figures); `env(safe-area-inset-*)` respected edge to edge (status bar, nav bar, display cutout, IME); the capture control is the one fixed element, everything else scrolls.
Light theme only: DESIGN.md is light-only, so do not add a dark scheme.
Respect the system font-scale setting (test at 130%).
Every wait shows the raven spinner; under `prefers-reduced-motion` or the system's animator-off setting the raven sits static, never vanishes.

Visual verification, mandatory: every mobile surface's done-when includes an `adb exec-out screencap -p` screenshot that the agent must actually READ against this brief before checking the box. An unread screenshot is not a pass. This is how "as polished as the desktop" is enforced.

- **MOB.0 (DECISION, baked - no gate).** What mobile may display: the snapshot carries the artifact row, annotations, page_text, and versions (E2E.md Section 1) - NOT facets, entities, or embeddings, and there is no "summary" field anywhere in the data model. This NARROWS the "AI enrichment syncs down as derived data" wording in the Findings synthesis and D.4: AI enrichment is desktop-computed AND desktop-displayed. Adding any display bundle to the snapshot is a follow-on decision, not this plan. The Reader shows content plus annotations. Tags appear only if `src/enqueue/sync/snapshot.py` already carries them; if it does not, leave tags out of this phase rather than extending the snapshot mid-flight.

- **MOB.1 (DECISION, baked - no gate).** The shape brief above (three surfaces, capture-first, inherit DESIGN.md exactly, AI data shown read-only) is ratified. Build to it; the end-review is where Minh reacts to the running app, not a pre-build gate.

- [ ] **MOB.2 [AGENT]** Stand up the mobile shell (Tauri v2, Android) so it builds and launches on a device showing the DESIGN.md light canvas + fonts.

  DONE so far (2026-08-12, in the working tree, uncommitted - do NOT redo):
  - The crate now builds as a mobile library. `desktop/Cargo.toml` gained a `[lib]` target (`crate-type = ["staticlib", "cdylib", "rlib"]`); all shell logic moved from `main.rs` into `desktop/src/lib.rs`, with the desktop code (engine spawn, AppKit, global-shortcut, the two windows) behind `#[cfg(desktop)]` and a thin `#[cfg(mobile)] mod mobile` path; `main.rs` is now just `enqueue_lib::run()`. `tauri-plugin-global-shortcut` is a `cfg(not(android/ios))` dependency. Verified: desktop `cargo check` is clean and `cargo check --lib --target aarch64-linux-android` compiles.
  - `cargo tauri android init` scaffolded `desktop/gen/android`; the Rust android targets are installed; it builds, installs, and launches on a physical Pixel 10 Pro (`com.sudohnim.enqueue`), loading the bundled `home.html`.
  - Toolchain present (from `~/dequeue`/`~/stance-lab`): Android SDK `~/Library/Android/sdk`, NDK 26.1 + 27.1, platform-tools, JDK 21, mobile-capable `cargo-tauri`. There is no AVD/cmdline-tools, but a physical device works, so an emulator is optional.

  How to run it (device plugged in, USB debugging on):
  `cd ~/enqueue/desktop && export ANDROID_HOME=$HOME/Library/Android/sdk && export NDK_HOME=$HOME/Library/Android/sdk/ndk/27.1.12297006 && cargo tauri android dev`
  (`dev` is a live-reload server; it does not exit - Ctrl+C stops it, the app stays installed.)

  REMAINING to meet the done-when: the page launches but is UNSTYLED (no light canvas). Cause: the mobile path loads the desktop `home.html`, whose stylesheet/script links are absolute `/static/css/...` and `/static/js/...`; on device the bundle root already IS `static/` (`tauri.conf.json` `frontendDist = "../src/enqueue/static"`), so those become `tauri.localhost/static/...` -> 404 (fonts loaded only because `home.html` references them as `/fonts/...`, which does resolve). `home.html` also boots by calling `127.0.0.1:8787`, which has no engine on device.
  Fix: do NOT reuse the engine-backed desktop `home.html`. Point the mobile window (`desktop/src/lib.rs` `mod mobile`) at a minimal mobile page that loads the DESIGN.md tokens with RELATIVE asset paths (or a base that resolves under `tauri.localhost`), showing just the light canvas and IBM Plex Sans. This page is the shell the real surfaces (MOB.4/MOB.5) build into. The absolute-`/static/`-path lesson applies to ALL mobile UI, not just this page.
  Anchor: `desktop/src/lib.rs` (`mod mobile`, the `WebviewUrl::App("home.html")` placeholder), `desktop/tauri.conf.json` `frontendDist`, and the absolute `/static/...` links in `src/enqueue/static/home.html`.
  Done when: the app builds and launches on the Pixel showing the DESIGN.md light canvas and the correct fonts (styled, not a bare page), verified by an `adb exec-out screencap -p` screenshot the agent reads; the mobile page (and any JS it loads) is added to `bin/verify` (a mobile entry in `FILES` plus its own JS list, mirroring the home-page treatment) so the parse gate covers it; and `bin/verify` passes.

- [ ] **MOB.3 [AGENT]** Local library store on device: a local SQLite read copy plus the relay pull client (reuse the Phase SYNC pull path, no push-of-derived-data), so the phone holds the synced artifacts offline.
  Done when: after configuring the relay secret, the phone downloads and decrypts the library and can list artifact ids offline.

- [ ] **MOB.3b [AGENT]** The setup/pairing surface - the one place the person enters the relay URL and sync secret, and the one place sync status lives: configured-or-not, last-synced time, pending-outbox count, last error in human-readable form. Entry from a small control in the Library top bar. Store the secret via Android Keystore-backed secure storage, never in a file or localStorage. A fresh install shows an unconfigured empty state that leads here.
  Done when: entering the relay URL + secret on a fresh install triggers the first sync and the status reads correctly afterward; a wrong secret shows a human-readable error (no crash, no silent hang); and a screencap of the screen is read against the design brief.

- [ ] **MOB.4 [AGENT]** The Library surface, per the design brief: a single-column list of artifact rows, newest first, under the SAVED / EVERYTHING ELSE shelf headers, each row tappable to the Reader.
  Done when: every synced artifact appears and opens; the row anatomy (kind dot, two-line-clamped title, two-line muted snippet, relative timestamp, thumbnail for images and link previews) matches the brief; the first-sync loading (raven spinner), empty-library, no-snippet, and over-long-title states are designed states, not bare text; and an `adb exec-out screencap -p` screenshot of each state is read against the brief before the box is checked.

- [ ] **MOB.5 [AGENT]** The Reader surface, per the design brief and MOB.0's display scope: a note's markdown (via `js/md.js`, relative path), an image (full viewer, pinch zoom), a link preview (the stored preview card; tapping opens the URL in the system browser), and a PDF (vendored pdf.js over the synced blob), all read-only, with the artifact's annotations below the content - and tags only if the snapshot carries them (MOB.0). The Android system Back gesture pops back to the Library. AI-derived data is absent quietly (MOB.0) - never a placeholder, never a fabricated "summary".
  Done when: each artifact kind reads correctly on the phone (verified by screencaps the agent reads), Back returns to the Library, annotations show, and no summary placeholder or fabricated field appears.

- [ ] **MOB.6 [AGENT]** Keyword search over the synced text (FTS over titles, bodies, annotations - no embeddings, no model).
  Done when: searching a word that appears in a synced note returns it; searching gibberish returns nothing (the same honesty as PLAN.md Phase Q, achieved trivially here because there is no dense leg).

- [ ] **MOB.7 [AGENT]** Capture on device: one field with the desktop overlay's four-outcomes logic (link, note, image), writing a new encrypted snapshot into sync (the push path) so it appears on every device. Plain text field - the desktop overlay's live-markdown (CAP.2) is desktop-only, do not port it. The capture button wears `--purple-bold` `#60079f` per the brief. Capture works OFFLINE: the snapshot is written locally and queued in an outbox that pushes when the relay is reachable; a pending artifact shows a subtle unsynced state on its Library row, never an error. On success the raven moment plays (the ANIM.4 flight asset, bundled): a quick left-to-centre flight, or a fade under reduced motion.
  Wire the OS share sheet and the photo picker as capture entry points.
  Done when: capturing a link, a photo from the library, and a note on the phone each create an artifact that syncs to the desktop within seconds; a capture taken with the relay unreachable queues quietly and syncs when the relay returns; the success raven shows (and is removed afterward); and the desktop then enriches the artifact per MOB.0 (enrichment stays desktop-displayed until a snapshot display bundle is decided).

Verify (MOB.2 to MOB.7): the app builds and launches on the Pixel device, capture round-trips to the desktop through the relay, the library reads offline, and every surface's screencap was read against the design brief.

---

## Out of scope

- Any model, embedding, facet, entity, or chat computation on the phone. Mobile displays desktop-computed AI data; it never generates it.
- Multi-user or shared libraries. Sync is one person's devices, one library (the `E2E.md` assumption).
- The full event-sourced CRDT sync `E2E.md` explicitly rejected. LWW per artifact is the chosen model.
- iOS, since D.3 picked Android-first; it is a follow-on, not this plan.
- Changing the desktop's local-first engine. The relay is additive; with sync off, nothing about the desktop changes.
- Syncing `saved_pivots` (saved views) and chats. E2E.md synced exhibits, but exhibits were dropped; whether views sync is a follow-on decision. Mobile reads artifacts only.

Desktop first (independent, no sync decision needed, worked in this order):

1. Phase EYE - desktop UI, ship anytime.
2. Phase NOTE - desktop editor; NOTE.0 persistence is pre-baked, so nothing gates the build.
3. Phase FIX - desktop engine bugs (answer salvage, chat floor leak), ship anytime.
4. Phase SET - desktop settings simplification, ship anytime.
5. Phase ANIM - desktop raven-motion (loading spinner + capture-success flight); assets already added, ship anytime.

Then the sync/mobile initiative (D.1 to D.4 already ratified):

1. Phase SYNC - needs E2E.md Phase E3 (snapshot core, unbuilt) before SYNC.4, and E1/E2 (crypto, unbuilt) before SYNC.8. Nothing else from E2E.md is a prerequisite.
2. Phase MOBILE - needs Phase SYNC working.

---

## Review when it's all done (Minh, /bro)

No gates while the agent works - it runs the whole desktop block start to finish without stopping. When it's done, you do this. Relaunch the app first (`bin/relaunch`), then walk these.

**The eye (EYE).** Look at the little eye button in the bottom pill. Should be just the eye - almond outline, lashes, bold purple pupil that follows your cursor. No whole bird. The big bird up top by the greeting stays a bird, that's on purpose. Move your mouse around, pupil should track.

**Notes (NOTE).** Make a new note, start typing on the first line. It should read as one normal line, not one letter per line, and you shouldn't have to hit Enter. As you type the first line, watch the title up top change live to match. Now click the title and rename it by hand - that name should stick even after you edit the body more and reload. Blank note still says "Untitled".

**Settings (SET).** Open Settings. It should be just three things now: which backend, the model name, the API key. No "Endpoint" box anymore (unless you pick "custom"). Switch to OpenCode Go, put a key in, ask something - should work, no localhost weirdness. The two OpenCode options should clearly say which is Zen vs Go.

**The bird animations (ANIM).** Do a quick capture - a raven should fly in from the left, sit for a second, fade out. Shouldn't block you clicking. Run a search - big raven spinning counter-clockwise in the middle, "searching..." under it, not tucked in the corner. Open a chat while it thinks - same raven, smaller. The spin should look the same everywhere. If you turn on Reduce Motion in macOS, the bird should sit still instead of spinning, never just vanish.

**The bugs (FIX).** Ask the chat a question you know it has notes for - it should answer, not say "That answer could not be completed." And ask something you have nothing on - it should honestly come up empty, not ground on junk.

**The capture overlay (CAP).** Summon the quick capture. The whole card should fit - input box with text sitting top-left (not clipped), the caption row, and the full Keep button. Type `- a`, Enter, `- b` and you should see real bullets; `#` should make a heading. Keep one of each: a bare URL, a URL plus words, plain text, and a pasted image - each should land as the right kind of artifact. When a keep succeeds, the raven flight should be clearly visible and gone afterward - no bird left sitting on screen.

**The phone app (MOBILE).** On the Pixel: it should look like Enqueue, not a bare web page - light canvas, IBM Plex Sans, hairlines. The library shows rows with kind, title, snippet, and time under the same shelves as the desktop, and the capture button is the bold purple, fixed at the bottom. First-run should walk you into entering the relay URL and secret; a wrong secret should say so in words. Open a note, an image (pinch zoom), a link (preview card, tap opens the browser), and a PDF (pages turn). Try the Back gesture from the reader - it should go back, never trap you. Capture a note with the relay unreachable - it should queue quietly and land on the desktop once the relay comes back. Nothing AI-derived should pretend to be there.

**Later, only when sync/mobile actually gets built (not now):** two things you have to check yourself before trusting it with real notes, because a bad merge silently eats edits. (1) Two machines, plaintext prototype: edit on one, watch it land on the other; go offline, edit both, reconnect - the newer wins and the older is still recoverable. (2) Once encryption's on and it's pointed at the real Railway relay: fetch a raw object straight from the relay and confirm it's unreadable ciphertext, not your notes. Don't put real notes through sync until both pass.
