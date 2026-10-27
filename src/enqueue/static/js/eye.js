// The living eye, shared by the desktop and the phone (the phone has no cursor, so
// there it follows a finger). Every mounted eye registers in one set served by one
// set of document listeners, attached on the first mount and removed by tearDownEye.

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
// On desktop the eye pictures are under /static/; in the phone app (http://tauri.localhost
// on Android, tauri://localhost on iOS) they are at the root.
const IS_MOBILE = location.hostname === "tauri.localhost" || location.protocol === "tauri:";
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
	clearTimeout(st.settle);
	st.idle = st.glance = st.glanceBack = st.blink = st.constrict = st.settle = 0;
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
	st.constrict = setTimeout(() => el.classList.remove("eye-constrict"), EYE_MOTION.constrictMs);
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
	// A mood (eyemood.js) owns the iris while it plays; wait it out.
	if (!eyeMotionOK() || el.matches(":hover") || el.dataset.mood || st.following) {
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
	st.blink = setTimeout(() => {
		el.classList.remove("eye-blinking");
		eyeArmBlink(el);
	}, rand(EYE_MOTION.blinkCloseMs, EYE_MOTION.blinkCloseMs + EYE_MOTION.blinkOpenMs));
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
	// A mood (eyemood.js) owns the iris while it plays; the follow resumes after.
	if (el.dataset.mood) return;
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
		if (e.pointerType === "mouse") eyeStep(el, e);
		else eyeFinger(el, e);
	}
}

// A finger has no hover: the iris leans toward it while it touches, drags or
// scrolls anywhere, and lets go a beat after it lifts. The lean saturates with
// distance, so a far touch still reads as "over there" without pinning the iris.
function eyeFinger(el, e) {
	const st = eyeState.get(el);
	if (!eyeMotionOK() || el.dataset.mood) return;
	st.following = true;
	clearTimeout(st.settle);
	const r = el.getBoundingClientRect();
	const sock = el.querySelector(".eye-socket").getBoundingClientRect();
	const dx = e.clientX - (r.left + r.width / 2);
	const dy = e.clientY - (r.top + r.height * 0.53);
	const d = Math.hypot(dx, dy) || 1;
	const k = Math.min(1, d / 220);
	st.track = st.layer.style.transform =
		"translate(calc(-50% + " +
		((dx / d) * k * sock.width * 0.22).toFixed(2) +
		"px), calc(-50% + " +
		((dy / d) * k * sock.height * 0.2).toFixed(2) +
		"px))";
}

function eyeLift(e) {
	if (e.pointerType === "mouse") return;
	for (const el of mountedEyes) {
		const st = eyeState.get(el);
		clearTimeout(st.settle);
		st.settle = setTimeout(() => {
			st.following = false;
			if (!el.dataset.mood) st.layer.style.transform = st.track = "";
		}, 700);
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
// The pill's ask eye is DRAWN, in the same thin line as the pill's other icons:
// an almond and three lashes in currentColor over a clipped socket, with a violet
// iris (a styled div, not the pupil PNG) that the shared follow code leans toward
// the cursor. The old pill eye was the eye-only.png art, a thick black outline
// that outweighed every other control in the pill. The emblem keeps the raven.
const PILL_EYE_MARKUP = (() => {
	const wrap = document.createElement("div");
	wrap.className = "eye-blinkwrap";
	const socket = document.createElement("div");
	socket.className = "eye-socket";
	const pupil = document.createElement("div");
	pupil.className = "eye-pupil";
	socket.appendChild(pupil);
	wrap.appendChild(socket);
	wrap.insertAdjacentHTML(
		"beforeend",
		'<svg class="eye-line" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
			'<path d="M2.6 12.8C5.2 8.6 8.4 6.6 12 6.6s6.8 2 9.4 6.2c-2.6 4.2-5.8 6.2-9.4 6.2s-6.8-2-9.4-6.2z"/>' +
			'<path d="M8 7.3 7 5.2M12 6.6V4.3M16 7.3l1-2.1"/></svg>',
	);
	return wrap;
})();

function makeEye(el) {
	if (!el) return;
	el.replaceChildren(
		(el.classList.contains("pill-eye") ? PILL_EYE_MARKUP : EYE_MARKUP).cloneNode(true),
	);
	// The pill re-renders on every navigation; a held mood (the vault's averted gaze,
	// a search in progress) carries over to the fresh eye.
	if (el.classList.contains("pill-eye") && window.eyeMood) queueMicrotask(eyeMood.refresh);
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
		settle: 0,
		following: false,
	});
	mountedEyes.add(el);
	if (!eyeMove) {
		eyeMove = eyePointer;
		eyeLeave = eyeLeaveDoc;
		for (const type of ["pointermove", "pointerdown"])
			document.addEventListener(type, eyeMove, { passive: true });
		for (const type of ["pointerup", "pointercancel"])
			document.addEventListener(type, eyeLift, { passive: true });
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
		for (const type of ["pointermove", "pointerdown"])
			document.removeEventListener(type, eyeMove);
		for (const type of ["pointerup", "pointercancel"])
			document.removeEventListener(type, eyeLift);
		eyeMove = null;
	}
	if (eyeLeave) {
		document.removeEventListener("mouseleave", eyeLeave);
		eyeLeave = null;
	}
}

// After a capture the raven flies off with it (css/bird.css), and the eye approves
// with one slow blink. Resolves when the bird has gone.
function captureFlight() {
	if (window.eyeMood) eyeMood.play("approve");
	document.getElementById("captureFlight")?.remove();
	const img = document.createElement("img");
	img.id = "captureFlight";
	img.className = "capture-flight";
	img.src = EYE_ASSET_BASE + "/capture-bird.png" + EYE_ASSET_V;
	img.alt = "";
	img.setAttribute("aria-hidden", "true");
	const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
	if (reduced) img.classList.add("reduced");
	document.body.appendChild(img);
	return new Promise((resolve) =>
		setTimeout(() => {
			img.remove(); // a no-op when a second capture already replaced this bird
			resolve();
		}, 1900),
	);
}
