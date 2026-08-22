const ICONS = {
	plus: '<path d="M12 5v14M5 12h14"/>',
	find: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
	// The eye, not a question mark. Asking here is not a support request; it is looking
	// at what you already own and seeing what is in it.
	ask: '<path d="M2.2 12S5.8 5.6 12 5.6 21.8 12 21.8 12 18.2 18.4 12 18.4 2.2 12 2.2 12z"/><circle cx="12" cy="12" r="2.8"/>',
	// Organize: four panes over the whole library, answering like search and ask do.
	// Search narrows, ask converses, organize rearranges.
	grid: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
	back: '<path d="M14.5 6.5L9 12l5.5 5.5"/>',
	chev: '<path d="M6.5 14.5L12 9l5.5 5.5"/>',
	down: '<path d="M12 4v11"/><path d="M7.5 10.5L12 15l4.5-4.5"/><path d="M5 19h14"/>',
	home: '<path d="M4 10.5L12 4l8 6.5"/><path d="M6 9.6V20h12V9.6"/>',
	star: '<path d="M12 4.2l2.3 4.9 5.2.7-3.8 3.7 1 5.3-4.7-2.6-4.7 2.6 1-5.3-3.8-3.7 5.2-.7z"/>',
	trash:
		'<path d="M4 7h16"/><path d="M9.5 7V5h5v2"/><path d="M6.5 7l1 13h9l1-13"/>',
	close: '<path d="M6 6l12 12M18 6L6 18"/>',
	// Move/redistribute: two horizontal arrows pointing outward - one left, one
	// right. Reads as "move this artifact to another place".
	move: '<path d="M3 8h13"/><path d="M12 4l4 4-4 4"/><path d="M21 16H8"/><path d="M12 12l-4 4 4 4"/>',
	note: '<path d="M4 4h11l5 5v11H4z"/><path d="M15 4v5h5"/>',
	upload:
		'<path d="M12 16V4"/><path d="M7 9l5-5 5 5"/><path d="M4 17v3h16v-3"/>',
	link: '<path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1"/>',
	image:
		'<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-7 7"/>',
	gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
	// The rename pencil (K.7/L.3b): a quiet ghost beside a saved-grouping title, not a
	// gear or a menu - renaming is an act on one grouping while you look at it.
	pencil:
		'<path d="M4 20l4.5-1 10-10-3.5-3.5-10 10z"/><path d="M14 6.5l3.5 3.5"/>',
	// The drawer toggle: a double chevron pointing at the drawer. Closed, it points
	// into the content (the drawer lives off the right edge, so it invites you to
	// pull it in); open, it points back out, inviting you to push it away. One
	// button, two directions, read at a glance.
	panelin:
		'<path d="M13.5 6.5L8 12l5.5 5.5"/><path d="M19 6.5L13.5 12l5.5 5.5"/>',
	panelout:
		'<path d="M5.5 6.5L11 12l-5.5 5.5"/><path d="M11 6.5L16.5 12 11 17.5"/>',
};
const svg = (k) => '<svg viewBox="0 0 24 24">' + ICONS[k] + "</svg>";

// ---- the living eye (O.3, EYE.1) -----------------------------------------
// The brand mark is a living raven eye: a fixed frame (the socket: outline,
// lashes, ground) and a pupil that leans toward the cursor inside it. One
// factory produces the markup and wires the follow, shared by the home
// greeting emblem and the ribbon's ask button, so every surface renders the
// same eye. The travel math self-scales from the socket's rendered size, so
// the same code works at emblem size and ribbon-button size.
// The eye PNGs load via img.src, not through home.html's versioned <link>/<script>
// tags, so the cache-buster never reaches them and a swapped asset shows stale. A
// per-page-load version query fixes that: the same value for every mount in a
// session (so the WebView caches within the session), a fresh value each app
// launch (so a relaunch always pulls a changed eye-frame/pupil/eye-only).
// On desktop, eye assets are at /static/; on mobile (tauri.localhost) they're at root /
const IS_MOBILE = location.origin.includes("tauri.localhost");
const EYE_ASSET_BASE = IS_MOBILE ? "" : "/static";
const EYE_ASSET_V = "?v=" + Date.now();

const EYE_MARKUP = (() => {
	const wrap = document.createElement("div");
	wrap.className = "eye-blinkwrap";
	const socket = document.createElement("div");
	socket.className = "eye-socket";
	const pupil = document.createElement("img");
	pupil.className = "eye-pupil";
	pupil.src = EYE_ASSET_BASE + "/eye-pupil.png" + EYE_ASSET_V;
	pupil.alt = "";
	pupil.draggable = false;
	socket.appendChild(pupil);
	const frame = document.createElement("img");
	frame.className = "eye-frame";
	frame.src = EYE_ASSET_BASE + "/eye-frame.png" + EYE_ASSET_V;
	frame.alt = "";
	frame.draggable = false;
	wrap.appendChild(socket);
	wrap.appendChild(frame);
	return wrap;
})();

// Every mounted eye registers here. One document-level pointermove/mouseleave
// pair iterates the set, so re-renders never stack listeners (the pill
// rewrites its innerHTML on every navigation; a naive mount would add a
// listener per render). The pair is attached on the first mount and stopped
// by tearDownEye, never one per eye.
const mountedEyes = new Set();
// Per-eye rAF state: the pending frame id and when it was queued, so a queued
// frame that never fires (window hidden, rAF throttled) can be reclaimed.
const eyeState = new WeakMap();
let eyeMove = null;
let eyeLeave = null;

// EYE.4a-c: the autonomous eye. Dilation (hover), constriction (press), the
// idle saccade and the blink are all motion, and motion is gated behind one
// check that is re-read at every event, so reduced-motion users get a still
// eye, not a trackless one - the pointer follow is functional and runs on.
const EYE_MOTION = {
	idleMin: 3500,
	idleMax: 6500,
	glanceMs: 300,
	glanceReturnMs: 320,
	blinkMin: 5000,
	blinkMax: 20000,
	blinkCloseMs: 95,
	blinkOpenMs: 120,
	constrictMs: 180,
};

function eyeMotionOK() {
	return !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function rand(a, b) {
	return a + Math.random() * (b - a);
}

function eyeClearTimers(el) {
	const st = eyeState.get(el);
	if (!st) return;
	clearTimeout(st.idle);
	clearTimeout(st.glance);
	clearTimeout(st.glanceBack);
	clearTimeout(st.blink);
	clearTimeout(st.constrict);
	st.idle = st.glance = st.glanceBack = st.blink = st.constrict = 0;
}

function eyeArmIdle(el) {
	const st = eyeState.get(el);
	if (!st) return;
	clearTimeout(st.idle);
	if (!eyeMotionOK()) return;
	// A still cursor earns a glance: any pointer event below re-arms this, so
	// a saccade only ever fires after the cursor has been parked a few seconds.
	st.idle = setTimeout(
		() => eyeSaccade(el),
		rand(EYE_MOTION.idleMin, EYE_MOTION.idleMax),
	);
}

function eyeArmBlink(el) {
	const st = eyeState.get(el);
	if (!st) return;
	clearTimeout(st.blink);
	if (!eyeMotionOK()) return;
	// A fresh random delay each cycle, so the cadence is never a metronome.
	st.blink = setTimeout(
		() => eyeBlink(el),
		rand(EYE_MOTION.blinkMin, EYE_MOTION.blinkMax),
	);
}

function eyeConstrict(el) {
	const st = eyeState.get(el);
	if (!st || !eyeMotionOK()) return;
	el.classList.add("eye-constrict");
	clearTimeout(st.constrict);
	st.constrict = setTimeout(
		() => el.classList.remove("eye-constrict"),
		EYE_MOTION.constrictMs,
	);
}

function eyePress(e) {
	// The listener lives on the eye element itself (it dies with the view's
	// render), so any press inside the eye - on the pupil, the frame, or the
	// ribbon button that wraps it - constricts the iris it was aimed at.
	eyeConstrict(this || e.currentTarget);
}

function eyeSaccade(el) {
	const st = eyeState.get(el);
	if (!st) return;
	if (!el.isConnected) {
		mountedEyes.delete(el);
		eyeClearTimers(el);
		return;
	}
	if (!eyeMotionOK() || el.matches(":hover")) {
		// Motion turned off since scheduling, or the cursor is resting on the
		// eye itself, where a glance would fight the hover: re-arm and wait.
		eyeArmIdle(el);
		return;
	}
	const socket = el.querySelector(".eye-socket");
	const sock = socket.getBoundingClientRect();
	// The follow's reach keeps tracking subtle, but the idle glance is a deliberate
	// "look away" and should read. The emblem's pupil is small inside a large lid,
	// so it has far more travel room than the follow baseline assumes; give it a
	// bigger swing than the ribbon eye (whose pupil already fills its socket).
	const glanceScale = el.classList.contains("pill-eye") ? 25 : 55;
	const reach = glanceScale * (sock.width / 184);
	const ang = Math.random() * Math.PI * 2;
	const len = reach * rand(0.65, 0.95);
	st.gx = (Math.cos(ang) * len).toFixed(2);
	st.gy = (Math.sin(ang) * len).toFixed(2);
	el.classList.add("eye-saccade");
	st.layer.style.transform =
		"translate(calc(-50% + " + st.gx + "px), calc(-50% + " + st.gy + "px))";
	st.glance = setTimeout(() => {
		// Return to the exact tracking pose the glance interrupted, not to a
		// dead centre - the follow resumes from where it left off.
		st.layer.style.transform = st.track || "";
		st.glanceBack = setTimeout(() => {
			el.classList.remove("eye-saccade");
			eyeArmIdle(el);
		}, EYE_MOTION.glanceReturnMs);
	}, EYE_MOTION.glanceMs);
}

function eyeBlink(el) {
	const st = eyeState.get(el);
	if (!st) return;
	if (!el.isConnected) {
		mountedEyes.delete(el);
		eyeClearTimers(el);
		return;
	}
	if (!eyeMotionOK()) {
		eyeArmBlink(el);
		return;
	}
	el.classList.add("eye-blinking");
	st.blink = setTimeout(
		() => {
			el.classList.remove("eye-blinking");
			eyeArmBlink(el);
		},
		rand(
			EYE_MOTION.blinkCloseMs,
			EYE_MOTION.blinkCloseMs + EYE_MOTION.blinkOpenMs,
		),
	);
}

function eyeRest(el) {
	const st = eyeState.get(el);
	if (!st) return;
	if (st.raf) {
		cancelAnimationFrame(st.raf);
		st.raf = 0;
	}
	clearTimeout(st.glance);
	clearTimeout(st.glanceBack);
	st.glance = st.glanceBack = 0;
	el.classList.remove("eye-saccade");
	st.layer.style.transform = "";
	st.track = "";
}

function eyeStep(el, e) {
	const st = eyeState.get(el);
	if (!st) return;
	const layer = st.layer;
	if (st.track === undefined) st.track = "";
	// A real move wins over a saccade immediately: drop the glance's easing
	// class and pending timers so the next tracking frame is applied crisply,
	// never through the glance transition.
	if (el.classList.contains("eye-saccade")) {
		el.classList.remove("eye-saccade");
		clearTimeout(st.glance);
		clearTimeout(st.glanceBack);
		st.glance = st.glanceBack = 0;
	}
	if (el.matches(":hover")) {
		// Hovering holds the iris centred (no follow drift while the mouse
		// rests on the emblem), so the two never fight over it.
		if (layer.style.transform) layer.style.transform = "";
		st.track = "";
		return;
	}
	if (st.raf) {
		// The newest event wins when the queued frame runs; reclaim a slot
		// that never fired (window hidden, rAF throttled) after a beat.
		if (performance.now() - st.rafQueued > 500) {
			cancelAnimationFrame(st.raf);
			st.raf = 0;
		} else {
			return;
		}
	}
	st.rafQueued = performance.now();
	st.raf = requestAnimationFrame(() => {
		st.raf = 0;
		// An eye whose view died while the frame was queued is not worth
		// tracking: the view swap already discarded it.
		if (!el.isConnected) return;
		// Re-check the hover inside the frame: a move queued before the hover
		// began would otherwise re-apply its offset for one frame after the
		// CSS hover-wake has centred the layer.
		if (el.matches(":hover")) {
			layer.style.transform = "";
			st.track = "";
			return;
		}
		const r = el.getBoundingClientRect();
		const dx = e.clientX - (r.left + r.width / 2);
		const dy = e.clientY - (r.top + r.height / 2);
		const d = Math.hypot(dx, dy) || 1;
		// Dead-zone falloff: full reach past 90px, easing off inside it so a
		// cursor resting near the eye does not make it tremble.
		const pull = Math.min(1, d / 90);
		if (pull === 0) {
			layer.style.transform = "";
			st.track = "";
			return;
		}
		const socket = el.querySelector(".eye-socket");
		const sock = socket.getBoundingClientRect();
		// Cap at 25 source px of travel, scaled by the rendered socket's
		// width vs the 184 px source width. (140 px tall source pupil has
		// 35 px of vertical headroom - 25 px keeps the pupil well inside
		// the lid even when the lean runs along the diagonal.) At the
		// 104 px display size that is ~2.5 CSS px of lean. The clip box
		// guarantees containment even if the math drifts.
		const reach = 25 * (sock.width / 184);
		// The -50% centring stays, the offset slides the iris (M.4: translate()
		// needs comma-separated lengths, not a bare pair).
		layer.style.transform =
			"translate(calc(-50% + " +
			((dx / d) * reach * pull).toFixed(2) +
			"px), calc(-50% + " +
			((dy / d) * reach * pull).toFixed(2) +
			"px))";
		st.track = layer.style.transform;
	});
}

function eyePointer(e) {
	for (const el of mountedEyes) {
		// A view swap detaches its eye without ceremony; drop it so the
		// registry never outlives its elements or its timers.
		if (!el.isConnected) {
			mountedEyes.delete(el);
			eyeClearTimers(el);
			continue;
		}
		eyeArmIdle(el);
		eyeStep(el, e);
	}
}

function eyeLeaveDoc() {
	for (const el of mountedEyes) {
		if (!el.isConnected) {
			mountedEyes.delete(el);
			eyeClearTimers(el);
			continue;
		}
		eyeRest(el);
	}
}

// The living eye factory: injects the eye markup into a given element and
// wires the cursor-follow by registering the element with the one shared
// document listener pair. The element itself is the caller's - its classes,
// id, and a11y attributes stay in the calling view's markup.
function makeEye(el) {
	if (!el) return;
	el.replaceChildren(EYE_MARKUP.cloneNode(true));
	// The ribbon button (EYE.6) wears the eye alone, not the whole raven: the
	// home emblem's frame is the full bird, so a small button reusing it reads
	// as the bird. `eye-only.png` is that same eye cropped out onto transparency;
	// its socket geometry is overridden in pill.css. The emblem keeps the raven.
	if (el.classList.contains("pill-eye")) {
		const f = el.querySelector(".eye-frame");
		if (f) f.src = "/static/eye-only.png" + EYE_ASSET_V;
	}
	eyeState.set(el, {
		raf: 0,
		rafQueued: 0,
		layer: el.querySelector(".eye-pupil"),
		track: "",
		idle: 0,
		glance: 0,
		glanceBack: 0,
		blink: 0,
		constrict: 0,
	});
	mountedEyes.add(el);
	if (!eyeMove) {
		eyeMove = eyePointer;
		eyeLeave = eyeLeaveDoc;
		document.addEventListener("pointermove", eyeMove, { passive: true });
		document.addEventListener("mouseleave", eyeLeave);
	}
	el.addEventListener("pointerdown", eyePress, { passive: true });
	eyeArmIdle(el);
	// The home greeting raven no longer blinks (Minh); only the ribbon eye does.
	if (el.classList.contains("pill-eye")) eyeArmBlink(el);
}

// The eye dies with the view (the view teardown calls this): drop every
// mounted eye, its timers and transient classes, and stop the shared pair,
// so no other surface inherits a stray handler. A later makeEye re-attaches
// the pair.
function tearDownEye() {
	for (const el of mountedEyes) {
		eyeClearTimers(el);
		el.classList.remove("eye-saccade", "eye-blinking", "eye-constrict");
	}
	mountedEyes.clear();
	if (eyeMove) {
		document.removeEventListener("pointermove", eyeMove);
		eyeMove = null;
	}
	if (eyeLeave) {
		document.removeEventListener("mouseleave", eyeLeave);
		eyeLeave = null;
	}
}
