# Phase delight findings

The capture pill, search bar, and greeting eye each have a strong identity but almost no micro-interaction feedback.
The pill's disc hovers to a quiet color swap (`.pill .keep:hover .disc` at `museum.html:1218`) with no press, lift, or transition curve; the round companion buttons have only a background swap (`.pill button.round:hover` at `:1238`).
The search bar's focus state is a border-color swap (`.searchbar:focus-within` at `:249`) with a box-shadow that does not read as a lavender focus ring per `docs/DESIGN.md` section 6 (level 4 focus: 2px lavender-focus outline at 50% opacity), and the `kbd.hint` hint vanishes with no transition.
The eye blinks and follows but the iris translate is a hard `setAttribute` with no easing (linear snap per pointermove event), the blink is a uniform 0.26s squash with no variance, and the emblem disc has a warm amber `box-shadow` glow (`0 6px 18px color-mix(in oklab, var(--accent) 38%, transparent)` at `:362`) that reads as a residual amber-era heat, not the cool quiet the new system calls for.
Per the delight reference: "delight at specific moments, not pages"; per the product register: "motion conveys state, not decoration"; per `docs/DESIGN.md` section 8: lavender is scarce and shadows are cool and low-opacity. The personality is already half-built; these tasks complete it with restrained, on-brand micro-interactions.

- [ ] **D.1 [AGENT]** Give the capture pill disc a press-down micro-interaction.
  Anchor: `.pill .keep .disc` at `museum.html:1207`, `.pill .keep:hover .disc` at `:1218`.
  The disc currently has no `:active` state and no transform on press.
  The delight reference prescribes a "satisfying button press" with `transform: translateY(2px)` on `:active` and an ease-out-quart transition.
  Add `transition: transform var(--dur-fast) cubic-bezier(0.25, 1, 0.5, 1)` to `.pill .keep .disc`, and `.pill .keep:active .disc { transform: scale(0.92); }` (scale, not translateY, because the disc is a circular fill inside a horizontal pill, so a press-squash reads better than a drop).
  The squash must be 100ms or less (delight reference: "delight moments should be quick (< 1 second)"; product register: "150-250ms on most transitions"; a press is the fastest end of that range).
  Verify: pressing the disc gives a quick scale-squash that springs back on release; no bounce or elastic (impeccable motion rule: "No bounce, no elastic").

- [ ] **D.2 [AGENT]** Add a hover-lift to the capture pill itself.
  Anchor: `.pill` at `museum.html:1165`, the `box-shadow: var(--shadow-2)` at `:1180`.
  The pill is one of "the four things in the whole system allowed a shadow" (the code comment at `:1165`), but it has no hover state on the container.
  Per the delight reference: "Smooth lift on hover" with `translateY(-2px)` and an ease-out-quart transition.
  Add `.pill:hover { transform: translateX(-50%) translateY(-2px); box-shadow: var(--shadow-lifted); }` (the `translateX(-50%)` must be preserved because it centers the pill; only `translateY` is new).
  Use `--shadow-lifted` from `docs/DESIGN.md` section 6 (the cool `rgba(16,17,20,0.08) 0 8px 28px`), not the current warm `--shadow-2`.
  This is a product-surface hover, not an orchestrated page-load sequence, so it complies with the product register's "No orchestrated page-load sequences" ban.
  Verify: hovering the pill lifts it 2px with a cool deeper shadow; it settles back on mouseleave.

- [ ] **D.3 [AGENT]** Give the round companion buttons a press feedback.
  Anchor: `.pill button.round` at `museum.html:1230`, `.pill button.round:hover` at `:1238`.
  The round buttons have a hover background swap but no `:active` state and no transition on transform.
  Add `transition: background var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);` to `.pill button.round`, and `.pill button.round:active { transform: scale(0.94); }`.
  The scale-squash matches the disc press (D.1) so the vocabulary is consistent, per the product register: "Consistent affordances across the surface."
  Verify: pressing any round button gives the same quick squash as the disc; hover stays the background swap.

- [ ] **D.4 [AGENT]** Give the search bar a lavender focus ring per the design system.
  Anchor: `.searchbar:focus-within` at `museum.html:249`.
  The current focus state swaps `border-color` to `--accent` (amber) and adds `box-shadow: var(--shadow-1)` (a drop shadow, not a focus ring).
  `docs/DESIGN.md` section 6 level 4 focus: "2px `--lavender-focus` outline at 50% opacity" on focused inputs.
  After Phase A.1 repoints `--accent` to lavender, replace the box-shadow with a focus ring: `box-shadow: 0 0 0 2px color-mix(in srgb, var(--lavender-focus) 50%, transparent);` and keep the border-color shift to `--lavender`.
  Add a `transition` on `.searchbar` that animates the box-shadow (currently only border-color and box-shadow are in the transition list at `:246`, which is correct, but the shadow value itself is wrong).
  The delight reference: "Input fields that animate on focus" as a form-interaction technique; this is a product input, so the animation is the ring's appearance, not a decorative glow.
  Verify: focusing the search input shows a 2px lavender-focus ring at 50% opacity, not a drop shadow; the ring animates in over 140ms with the ease-out curve.

- [ ] **D.5 [AGENT]** Animate the `kbd.hint` disappearance with a fade, not a hard cut.
  Anchor: `.searchbar kbd.hint` at `museum.html:305`, the `display: none` rules at `:316-318`.
  The `kbd.hint` (the `Cmd+K` discoverability keycap) vanishes instantly when the search is focused or has text.
  The delight reference: "Hover reveals with personality" and "Form interactions: input fields that animate on focus." A hard `display: none` cannot animate.
  Replace `display: none` with an opacity + width collapse: `.searchbar:focus-within kbd.hint, .searchbar:has(input:not(:placeholder-shown)) kbd.hint { opacity: 0; transform: scale(0.8); pointer-events: none; }` and add `transition: opacity var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);` to `.searchbar kbd.hint`.
  This is a discoverability reward: the keycap fades out gracefully as the user engages, instead of blinking away.
  Verify: focusing the search or typing fades the keycap out over ~140ms; it fades back in on blur/empty.

- [ ] **D.6 [AGENT]** Ease the eye's pupil tracking.
  Anchor: `mountEye()` at `museum.html:4195`, the `step` function's `iris.setAttribute("transform", ...)` at `:4207`.
  The pupil currently snaps to the cursor position on every `pointermove` event with no easing.
  The delight reference: "Satisfying interactions" and "Smooth slide" with spring or ease physics. The impeccable motion rule: "Ease out with exponential curves (ease-out-quart / quint / expo)."
  Replace the hard `setAttribute` with a CSS transition on `.eye-iris`: `transition: transform 120ms cubic-bezier(0.16, 1, 0.3, 1);` (the existing `--ease` token, an ease-out-quart), and set the transform via `iris.style.transform` instead of `setAttribute` so CSS transitions apply (SVG `transform` attribute does not transition; CSS `transform` property does).
  This gives the pupil a subtle lag as it follows the cursor, making it feel alive rather than mechanically pinned.
  Verify: moving the cursor shows the pupil easing toward the new position over ~120ms, not snapping; it still clamps within the sclera (the reach limit is unchanged).

- [ ] **D.7 [AGENT]** Vary the blink cadence and add an occasional double-blink.
  Anchor: `mountEye()` at `museum.html:4219`, the `blink` closure's `setTimeout(blink, 5000 + Math.random() * 15000)`.
  The blink currently fires at a uniform 5-20s interval with the same 0.26s duration every time.
  The delight reference: "Vary responses (not same animation every time)" and "Compound over time: delight should remain fresh with repeated use."
  Add a 15% chance of a double-blink: after the first blink's 320ms class-removal, if `Math.random() < 0.15`, schedule a second `.blinking` add after ~120ms instead of the next full interval.
  Keep the 5-20s random interval for the base cadence (already correct).
  This is a product-surface delight moment (the greeting), not an orchestrated page-load, so it complies with the product register's motion ban.
  Verify: over ~60s of observation, the eye occasionally double-blinks; the cadence never feels metronomic.

- [ ] **D.8 [AGENT]** Replace the emblem's warm amber glow with a cool lavender shadow.
  Anchor: `.greet-emblem` at `museum.html:358`, the `box-shadow: 0 6px 18px color-mix(in oklab, var(--accent) 38%, transparent)` at `:362`.
  The emblem disc has a warm amber glow from the current `--accent` (amber `#f7a501`). After Phase A.1 repoints `--accent` to lavender `#5e6ad2`, this shadow becomes a lavender glow, but at 38% opacity and 18px blur it is too strong for the "whisper shadow" discipline in `docs/DESIGN.md` section 6 ("Shadows are cool and low-opacity, never dramatic").
  Replace with `box-shadow: var(--shadow-card)` (the cool `rgba(16,17,20,0.06) 0 4px 16px`), or a custom `0 4px 16px color-mix(in oklab, var(--lavender) 20%, transparent)` if a faint brand-tinted glow is wanted (20%, not 38%).
  The ring (`.greet-emblem::before` at `:365`) already uses `color-mix(in oklab, var(--accent) 34%, transparent)` which becomes a lavender ring post-A.1; that is on-brand and can stay, but should be re-measured at 20-25% to stay quiet.
  Verify: the emblem's shadow is cool and subtle, not a warm glow; the ring echoes the lavender quietly.

- [ ] **D.9 [AGENT]** Add a discoverable hover-wake to the eye.
  Anchor: `.greet-emblem.eye` at `museum.html:358` (the base class), `mountEye()` at `:4195`.
  The eye blinks on a random timer but has no reaction to direct attention.
  The delight reference: "Hover surprises: icons that animate on hover" and "Easter eggs: hover reveals on logos."
  Add a CSS-triggered hover that does not require JS: when the cursor enters the emblem's bounds (`.greet-emblem.eye:hover`), the iris centers (`transform: translate(0, 0)`) and a single blink fires via a CSS animation (reuse `eye-blink` with `animation: eye-blink 0.26s var(--ease);` on hover). This makes the eye "look at you" when you approach it, then blink, a small discovery reward.
  This is CSS-only, so it does not conflict with the JS pointermove listener (which tracks document-wide cursor position). The `:hover` scoped blink is additive.
  Respect reduced-motion: the global `@media (prefers-reduced-motion: reduce)` block at `museum.html:1382` already crushes animation-duration to 1ms, so the hover-blink is instant under reduced motion. Confirm the hover-blink is covered by that block (it is, because it is a CSS animation, not a JS setTimeout).
  Verify: hovering the emblem centers the pupil and triggers one blink; under reduced-motion, the blink is instant and the pupil stays where the JS last set it.

- [ ] **D.10 [HUMAN]** Desktop review: the pill feels like a physical object (lifts on hover, squashes on press), the search bar's lavender ring reads as focus, the keycap fades gracefully, and the eye feels alive (eased tracking, occasional double-blinks, a hover-wake) without being distracting.
  All delight is under 250ms, uses ease-out-quart, and respects the reduced-motion block at `museum.html:1382`.
  Verify: the squint test shows the pill as a tactile floating object, the search bar's focus as a quiet lavender ring, and the eye as a living mark, not a decoration; none of the delight delays or blocks the core action.
