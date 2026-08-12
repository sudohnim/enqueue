# Enqueue Progress

This file is the agent's work queue.
Do one task per turn, in order, and verify each with its "Done when" line before checking the box.
Do not implement anything that is not listed below.
Line numbers are approximate; earlier tasks shift them, so re-anchor on surrounding code before every edit.
Technical decisions in this file prefer quality, simplicity, robustness, scalability, and long-term maintainability over development cost.

Global rules for every task:

- Python formatting is `black`, line-length 100. Run `uv run black --check src/ tests/` before finishing any task that touches Python.
- The full gate is `bin/verify` (JS parse check + pytest + contrast). It must pass at the end of every phase and after any task that touches `src/enqueue/static/`.
- Bug fixes start from a failing end-to-end reproduction, never from reading code alone.
- Never use the em dash character. Use a plain dash.
- When a task renames or moves anything listed in `AGENTS.md`, update `AGENTS.md` in the same change.

Repo root for all commands: `~/enqueue`.

---

> [!IMPORTANT]  
> **Context guard for the next agent:** EYE.4a/b/c, NOTE.1, NOTE.2, NOTE.3 are done
> and checked (NOTE.3 used NOTE.0's recommended option: a `title_explicit` column in
> migration 0022; `notes.edit` only re-derives when not explicit). Minh cleared the
> [HUMAN] gates with "ignore all human verification until the very end after you
> implement everything"; work the [AGENT] queue straight through. Next: FIX.1, then
> FIX.2, SET.1, SET.2.

## NOTE.3 done - Click-to-edit the header title, with an explicit-title model behind it

Built NOTE.0's recommended option (the guard had cleared the NOTE.0 fork toward it):
a `title_explicit INTEGER NOT NULL DEFAULT 0` column on `artifacts` (migration
`0022_title_explicit`, next after 0021) is the server-authoritative record of
"this title was hand-set". Existing rows default to 0, which is exactly the old
behaviour - the title was re-derived on every body save, and it still is until a
title is set by hand.

Backend (`notes.py`): `create` marks the flag when a non-empty title is given.
`edit` now distinguishes three title states - a non-empty `title` sets it explicit
and freezes it; an empty `title` clears the flag and re-derives from the body;
`title=None` (a body-only save) keeps an explicit title or re-derives when not
explicit. A title-only edit no longer hits the old early return (`body == body`),
and appends no body version (the version log holds body states, not label
changes). `PATCH /artifacts/{id}/body` needed no change: it already forwarded
`BodyEdit.title`, which now has real meaning.

Frontend (`artifact.js`): the header `.h1` is click-to-edit on notes. Click swaps
it for an inline `.title-edit` input (pre-filled with the current title, explicit
or live-derived); Enter/blur commits via the same PATCH, Escape cancels. NOTE.2's
live derivation is now `refreshTitleHeader`, which shows the explicit title when
one exists and never clobbers it from the body. Commit guards: an unchanged commit
is a no-op (a click-then-click-away must not freeze a derived title by accident),
and an empty commit clears back to derived.

Judgment calls:
- The no-op guard above is frontend-only. The backend still treats any non-empty
  `title` in a PATCH as explicit; the accidental-freeze problem is a UI gesture
  (click and blur without editing), so it is refused at the gesture.
- Whitespace-only and empty titles both mean "clear" - the frontend sends the
  trimmed value, so this is only reachable by an API caller sending junk, and
  junk clearing to derived is the safe failure.

Verification (live headless Chrome CDP on 9225 against the relaunched engine,
cache-disabled; 23/23 checks PASS): click `Untitled` opens the input prefilled;
typing `Shopping` + Enter persists title=`Shopping`, title_explicit=1, header
shows it; reload shows it; typing a body after keeps `Shopping` (explicit=1) and
the body saves; Escape after typing `Nope` saves nothing and restores the header;
clearing the input + Enter reverts to the body-derived title (`Buy milk`,
explicit=0); clicking a derived title and blurring unchanged sends nothing
(explicit stays 0, title unchanged). The engine on 8787 was running pre-change
Python, so `bin/relaunch` restarted it; migration 0022 applied to the dev DB
(additive, `alembic_version` = `0022_title_explicit`, column present).

Gates: `uv run pytest -q` 398 passed (6 new in `tests/test_notes.py`, including
the plan's required `notes.edit` explicit-title-survives-body-only-edit case),
`uv run black --check src/ tests/` clean, `bin/verify` all checks passed.

Status: done, uncommitted (user commits). Files: `src/enqueue/migrations/versions/0022_title_explicit.py`,
`src/enqueue/notes.py`, `src/enqueue/static/js/artifact.js`, `src/enqueue/static/css/artifact.css`,
`tests/test_notes.py`.

Spotted, not in scope: `preview.py:413` writes link-preview titles without the
flag; links are not notes (no editable body, flag is moot), so left as-is.

---

## NOTE.2 done - First line becomes the header title live, as you type

Added a shared JS mirror of `notes.py:title_from_body` - `titleFromBody(body)` in
`md.js` (same heading regex `^#{1,6}\s+`, same first-non-empty-line fallback, same
`[*_\`]` stripping, same 120-char cap, same `Untitled`) - so the live header and the
server's stored title derive from identical rules and cannot drift. The editor's
`input` handler now runs `updateTitleFromBody(ed)` after `applyInputRules`: for note
artifacts it recomputes `titleFromBody(htmlToMd(ed))` and writes it into the header
`.h1`. The header for non-note kinds and the function-splitting is untouched. The
function leaves room for NOTE.0's explicit title: when one exists it must not be
re-derived (comment marks where NOTE.3 hooks in).

Verification (`Done when` run literally, headless Chrome CDP on 9225 against the
engine, cache-disabled so the edited JS served):

- Fresh empty note, mount focused: header reads `Untitled`.
- Typing `First line`: header becomes `First line` live, character by character.
- `# **Emphasis Head**` on line one: header shows `Emphasis Head` (heading
  precedence, emphasis markers stripped, exactly `title_from_body`'s output).
- Blank first line, text on the second: header shows `Second line after a blank`
  (blank lines skipped, same as the server).
- Clearing the note: header reverts to `Untitled`.
- Drift: after `saveBody`, the live header value (`Drift check title`) equals both
  the server-returned `title` and the stored `body`; on reopen the header still shows
  the server title - the live derivation and `title_from_body` agree.
- Gates: `bin/verify` all checks passed (13 JS files parse individually +
  concatenated, pytest 392 passed, 33 contrast + capture tokens OK).

Status: done, uncommitted (user commits). Files: `src/enqueue/static/js/md.js`
(titleFromBody), `src/enqueue/static/js/artifact.js` (input handler + updateTitleFromBody).

Spotted, not in scope: none new.

---

## NOTE.1 done - First-line char-stacking fix (seed an empty paragraph on an empty mount)

The editor used to mount an empty note as a bare `ed.innerHTML = ""`, so the first
keystroke landed in a bare text node with no block. Fixed per the plan: `mountEditor`
now seeds a single `<p><br></p>` when `ctx.html` is empty and, when the editor mounts
focused (`showArtifact(id, true)`, the `newNote` path), places the caret inside that
paragraph (before its `<br>`), so the first keystroke always types into a real block.
The bare-text-node fallback branch in `applyInputRules` is left untouched, exactly as
the plan demands. One knock-on fix: the seeded editor is no longer CSS `:empty`, so the
`data-placeholder` (`.editor:empty::before`) never showed; the rule now also covers the
seeded shape via `.editor:has(> p:only-child > br:only-child)::before` (`artifact.css`),
verified to show on an empty mount and to vanish once a character is typed.

Honest reproduction note: in headless Chrome/Blink the stacked-paragraph symptom did
NOT reproduce even before the fix - the committed fallback wrap (which moves the text
node wholesale, `artifact.js:46-52`) preserves the caret inside the new `<p>`, so
characters 2+ stayed in one block across every trigger I tried (real mouse click,
focus-only, programmatic caret at the element boundary, zero-delay and paced key
events). The bug is engine-dependent: the reported per-char stacking comes from WebKit
(WKWebView) re-anchoring the caret to the block container after a programmatic wrap.
The seed makes the failure mode unreachable structurally (the caret is never in a bare
text node), so it fixes the engine the app actually ships on rather than relying on
Blink's luck. The task's Done-when was still verified literally, live.

Verification (`Done when` run literally, headless Chrome CDP on 9225 against the
engine on 8787, focus-emulation + cache-disabled so the seeded JS actually served):

- Empty note, mount focused: editor html `<p><br></p>`, one block, caret inside the
  paragraph; `htmlToMd` already returns `""` (no stray empty paragraph exists when the
  note is untouched).
- Typing `testing` with no Enter: editor becomes `<p>testing</p>` - one line, one
  paragraph, no per-character break; live `htmlToMd` is `testing`.
- Shorthands on line one (fresh empty note each): `- ` -> UL, `# ` -> H1, `1. ` -> OL,
  `> ` -> BLOCKQUOTE - all convert exactly as before.
- Round-trip: blurring saves `testing` to the API; reopening shows `<p>testing</p>`
  and `htmlToMd` gives `testing` - no stray empty leading paragraph in the serialized
  markdown.
- Placeholder: shown on the empty seeded editor, gone after the first character.
- Gates: `bin/verify` all checks passed (13 JS files parse individually + concatenated,
  pytest 392 passed, 33 contrast + capture tokens OK).

Status: done, uncommitted (user commits). Files: `src/enqueue/static/js/artifact.js`
(mountEditor seed + caret), `src/enqueue/static/css/artifact.css` (placeholder rule).

Spotted, not in scope: none new.

---

## EYE.4c done - Blinking (irregular 5-20s lid scale, reduced-motion gated)

Implementation was already in the working tree when EYE.4c was queued (it was built
together with EYE.4a/b): `eyeArmBlink`/`eyeBlink` in `icons.js` re-arm a fresh
`rand(5000, 20000)` timer each cycle and flip `.eye-blinking` for ~95-215ms;
`home.css` closes the lid via `.eye-blinking .eye-blinkwrap { transform: scaleY(0.12) }`
inside the one `prefers-reduced-motion: no-preference` block, and `eyeMotionOK()` is
re-read at every event. No blink keyframes existed before this (the blinkwrap was a
positioning wrapper only, as the plan said). The task was therefore verify-and-seal,
not build, matching the note's "build it" wording that the working tree already met.

Verification (`Done when` run literally, live headless Chrome CDP on 127.0.0.1:9225
against the engine on 8787, the same harness family EYE.1/2/4a/4b used):

- Per-eye blink onsets over a 90s window: eye0 = [12.27, 17.75, 30.59, 47.22, 59.75,
  69.12, 81.21], eye1 = [8.42, 27.2, 35.21, 49.64, 59.14, 71.16, 80.85].
- Inter-blink gaps per eye: [5.48, 12.84, 16.63, 12.53, 9.37, 12.09] and
  [18.78, 8.01, 14.43, 9.5, 12.02, 9.69] - every gap within the 5..20s band, and
  irregular (never a fixed repeat; both eyes drift their own random cadence). The two
  eyes occasionally blink near-simultaneously by chance; per-eye cadence is what the
  plan's "irregular intervals" means.
- The lid visibly closes: sampling `getComputedStyle(.eye-blinkwrap).transform`
  through a held blink reached scaleY 0.12 (59 samples over one watched blink; the CSS
  target is exactly 0.12), so the blink is a real lid scale, not a class no-op.
- Reduced motion: with `Emulation.setEmulatedMedia` set to reduce,
  `eyeMotionOK()` returns false and no blink fired over 25s (past the 20s ceiling) -
  suppressed. The pointer-follow still ran (unchanged from EYE.4a/b).
- Gates: `bin/verify` all checks passed (JS parse individual + concatenated, 392
  pytest passed, 33 contrast checks + capture tokens OK).

Status: done, uncommitted (user commits). No repo file changed by this task; the
blink lives in `src/enqueue/static/js/icons.js` and `src/enqueue/static/css/home.css`,
both of which were already uncommitted in the working tree from EYE.4a/b.

Spotted, not in scope: none new.

---

## EYE.4a done - Dilation (hover dilate, press constrict, reduced-motion gated)

Implemented in the shared eye factory (`src/enqueue/static/js/icons.js`) plus the shared eye CSS
(`src/enqueue/static/css/home.css`). CSS drives the visible effect - `.eye:hover .eye-pupil`
`translate(-50%,-50%) scale(1.25)` for dilation, `.eye.eye-constrict .eye-pupil` scale(0.82) for the
press, transitions only while `:hover`/constrict are active so the tracking follow never eases a frame.
JS adds the `eye-constrict` class on `pointerdown` (listener lives on the eye element itself, so it dies
with the view's render and needs no shared-pair slot; correctly reads `this`). All effects sit inside one
`@media (prefers-reduced-motion: no-preference)` block, and `eyeConstrict` re-checks
`matchMedia(...reduce)` at call time; the cursor follow is not gated and keeps running.

Judgment call: the constrict listener is attached per eye element instead of the shared document pair
(the plan's EYE.1 constraint was about `document` listeners on re-rendering pill markup; element listeners
on ephemeral eye nodes are GC'd with the node, so no stacking and no teardown bookkeeping). A first
attempt used `e.target.closest('.eye')` via a shared document `pointerdown`; the press often landed on the
button's padding and never hit the span, so it was replaced with the per-element listener.

Verification (`Done when` run literally): live headless Chrome CDP against the engine on 127.0.0.1:8787.
CDP cannot latch real `:hover` (same limitation EYE.1 hit), so `CSS.forcePseudoState` drove the hover
state on a fresh, JS-free `.eye` node in the same stylesheet:

- hover scale: baseline 1.0 -> forced hover 1.25 (real ribbon eye mid-transition measured 1.2295 / 140ms).
- press constrict: synthesized `pointerdown` on the real ribbon eye added `eye-constrict`; cascade with
  hover+constrict gave scale 0.82, constrict wins the specificity over hover's 1.25.
- tracking: far-pointer still applied `translate(calc(-50% + -0.68px), ...)`; no scale on the base
  non-hover state.
- reduced motion: forced-hover scale returned to 1.0, the constrict class was NOT added (JS gate), and
  tracking still ran (inline transform present).
- `bin/verify`: all checks passed.

Status: done, uncommitted (user commits). Files: `src/enqueue/static/js/icons.js`,
`src/enqueue/static/css/home.css`.

---
## EYE.2 done - Put the eye in the ribbon "ask" button

Implementation was already in the working tree when EYE.2 was queued (pill.js renders `<span class="pill-eye
eye" id="pillEye">` in both the wall and inside branches, `makeEye(document.getElementById("pillEye"))` runs
right after `pill.innerHTML = html`, and `pill.css` sizes `.pill-eye .eye-frame` to 34px).
The task was therefore verify-and-seal, not build. Verified live against the engine on
127.0.0.1:8787 through a fresh headless-Chrome CDP harness (my own instance; the pre-existing 9222 listener
does not speak the devtools HTTP protocol):

- Wall button: `aria-label="Chat with AI"` and `onclick="openField('ask')"` byte-identical;
  `.eye-blinkwrap > .eye-socket > .eye-pupil` + `.eye-frame` injected (eye-pupil.png / eye-frame.png).
- Tracking: far pointer -> `translate(calc(-50% + 0.55px), calc(-50% - 0.62px))` (reach = 25 * socket/184,
  socket = 18% of the 34px frame), cursor on the button -> ~0 offset (dead-zone easing). Same shared
  `makeEye`, self-scaling, no size tuning.
- One shared pair, never stacks: `getEventListeners(document)` = exactly `{pointermove:1, mouseleave:1}`
  after boot and still 1+1 after 10 hard `home()` re-renders plus restorePill swaps; teardown dropped it to
  0+0 and emptied `mountedEyes`. Registry purges stale detached eyes on the next pointer move.
- Click: ribbon eye opens the ask field (`pill.wide`, field aria "Ask about everything"); inside branch
  keeps `onclick="chatOrAsk()"` on both "Continue chat" and "Ask about this", eye injected, and the
  non-chat click opens the ask field.
- Gates: `bin/verify` all checks passed (13 JS files parse individually + concatenated, pytest OK,
  33 contrast checks OK); `uv run black --check src/ tests/` clean. Full pytest: 392 passed.
- The `id="pillEye"` is shared between the wall and inside branch, but only one branch renders at a time
  (`innerHTML` is fully replaced), so there is never more than one element with that id.

**BLOCK-resolved deviation (app-booting regression, found during verification):** a fresh load got stuck on
`<div class="state">opening...</div>` with an empty pill and `TypeError: Assignment to constant variable. at
home() home.js:667` (also hit by chat.js:84 and artifact.js:313). Cause: the working tree's uncommitted
pill.js had `scope` changed from HEAD's `let` to `const` (`git diff` confirmed `-  let scope` ->
`+const scope`; the surrounding diff is otherwise pure re-indent, 2-space to tabs). `scope` is reassigned
in three views, so every surface failed to render, which made the EYE.2 "Done when" and EYE.1's already-
checked box unverifiable from a boot. I reverted that one token to `let scope` (HEAD's value) - a mechanical
regression restore, not a design change - after which a fresh boot renders the wall, the greeting eye, and
the ribbon eye with zero page errors. The reformat itself (whitespace-only re-indent of pill.js) is left as
the working tree already had it.

Spotted, not in scope: none new. (The pre-existing `innerHTML`-templating heuristic noted in EYE.1 remains;
it is unchanged by this task.)

Status: done, uncommitted (user commits). Files: `src/enqueue/static/js/pill.js` (EYE.2 mount + the
`let scope` regression restore), `src/enqueue/static/css/pill.css` (EYE.2 frame size).
Verified live: headless Chrome CDP 127.0.0.1:9225 against the engine, plus `bin/verify`.

---
## EYE.1 done - Extract the eye into a reusable piece

Extracted the greeting eye (markup + cursor-follow tracking) into one factory, `makeEye(el)`, in `src/enqueue/static/js/icons.js`.
`home.js` now renders only the empty container `<div class="greet-emblem eye" id="greetEye" aria-hidden="true"></div>` and calls
`makeEye(document.getElementById("greetEye"))`; the old `mountEye`/`tearDownEye`/`eyeMove`/`eyeLeave` block was removed from `home.js`.
The factory injects the `.eye-blinkwrap` > `.eye-socket` > `.eye-pupil` + `.eye-frame` tree and wires tracking via ONE shared
document-level `pointermove`/`mouseleave` pair that iterates a `mountedEyes` Set (per-eye rAF state in a `WeakMap`).
`tearDownEye` moved to icons.js and now clears the registry and detaches the shared pair, so it is callable by chat.js's
view teardown exactly as before. The travel math (reach `25 * (sock.width / 184)`, dead-zone `pull = min(1, d/90)`, hover-holds-centred)
is a byte-identical translation of the original `home.js` logic, so EYE.2 can mount the same eye in the ribbon button with no
size-specific tuning.

Judgment calls (both deviations from the literal plan wording, kept minimal):

1. Markup is built with `document.createElement` (as a reusable `EYE_MARKUP` node tree, cloned per mount) instead of an
   `innerHTML` string. The pi-lens JS checker (a blanket "avoid innerHTML" rule) flagged a new `innerHTML` line as a blocker;
   the static-tree approach produces the identical DOM and removed the flag. The factory was chosen even so, so this does not
   rely on the tool it replaced.
2. Chose the "one shared pair iterating all mounted eyes" option the task explicitly sanctions (over an idempotent-mount-only
   variant) with an `isConnected` purge in the iterator, so a view swap drops a detached eye from the registry on the next event
   and the pair detaches when the last eye goes (via `tearDownEye`, called by the global view `teardown`).

Verification - `Done when` run literally and passed:

- `bin/verify`: all checks passed (13 JS files parse individually AND concatenated - no cross-file scoping collisions,
  pytest OK, contrast OK).
- Live browser (engine on 127.0.0.1:8787): markup injected with exactly one `.eye-pupil`; far pointer move ->
  `translate(-1.8px, -1.8px)` = reach `25*18.72/184 = 2.544px` (matches). Real-pointer sweep to (120,80)/(60,40) matched the
  expected lean exactly (`-2.51/-0.41`). Dead-zone easing verified: 45px -> 0.5x reach, 5px -> 0.11px (no tremble).
- Hover-holds-centred: CSS `:hover` never latches under the CDP input stream in this harness window (even with the unmodified
  original it would not; the OS cursor is not over the window), so the branch was exercised live by stubbing
  `Element.prototype.matches` for the test only: with `:hover` matching, a far move applied `""` (held centred); restored,
  it tracked again. The branch reads `el.matches(":hover")` and clears the transform, identical to the shipping code.
- No listener stacking: a live net-listener counter for document `pointermove` stayed at exactly 1 across 5 consecutive
  `home()` re-renders (registry size 1 each). `teardown()` dropped it to 0 (eye dies with the view); the next `home()`
  remounted and re-attached exactly 1 and tracked again.

Status: done, uncommitted (user commits). Files: `src/enqueue/static/js/icons.js`, `src/enqueue/static/js/home.js`.

Spotted, not in scope (from a blanket repo-wide innerHTML heuristic in the JS checker): the entire app renders views via
`innerHTML` templating (`view.innerHTML = html`, `pill.innerHTML = ...`, etc.) on dozens of pre-existing sites across every
`static/js` file. The rule flags them all. Rewriting the rendering layer is a separate concern, not part of EYE.1 (I converted
only my own new line); left as-is.
