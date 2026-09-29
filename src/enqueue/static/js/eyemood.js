// ---- the pill eye's moods ------------------------------------------------------
// The ask eye in the pill is a character, not an icon. It already follows the
// pointer (desktop) or glances on its own (phone), and blinks. This module adds the
// rest of its personality, shared by both shells:
//
//   - a lazy eye: every so often it stops following, drifts slowly down and out,
//     holds a beat too long, and snaps back;
//   - moods the app triggers at moments that matter: approving a keep, squinting
//     while search thinks, startling when something new arrives, averting its gaze
//     from the vault;
//   - dozing when nothing has happened for a minute, and waking with a start;
//   - annoyance when it is poked three times in a row.
//
// It works on any element carrying `.pill-eye` with an `.eye-blinkwrap` lid and an
// `.eye-pupil` iris inside an `.eye-socket` clip - the markup both shells render.
// While a mood plays, `data-mood` is set on the eye and the shells' own follow and
// glance code stands aside (they check it), so the two never fight over the iris.
// Everything is gated on reduced motion: a person who asked for less motion gets a
// still eye that only shuts for the vault.
(function () {
	const MOOD_CSS = `
.pill-eye .eye-pupil { transition: transform 120ms cubic-bezier(.2,.8,.2,1), scale 220ms cubic-bezier(.2,.8,.2,1); }
.pill-eye.eye-m-slow .eye-pupil { transition: transform 900ms cubic-bezier(.3,0,.2,1), scale 220ms; }
.pill-eye.eye-m-dart .eye-pupil { transition: transform 200ms cubic-bezier(.4,0,.2,1); }
.pill-eye .eye-blinkwrap { transition: transform 110ms cubic-bezier(.4,0,.2,1); }
.pill-eye.eye-m-shut .eye-blinkwrap { transform: scaleY(.08); }
.pill-eye.eye-m-squint .eye-blinkwrap { transform: scaleY(.46); transition-duration: 260ms; }
.pill-eye.eye-m-sleepy .eye-blinkwrap { transform: scaleY(.5); transition: transform 1600ms cubic-bezier(.4,0,.2,1); }
.pill-eye.eye-m-wide .eye-blinkwrap { transform: scale(1.1, 1.34); transition: transform 160ms cubic-bezier(.16,1,.3,1); }
.pill-eye.eye-m-wince .eye-blinkwrap { transform: scaleY(.22) rotate(-4deg); }
.pill-eye.eye-m-shrink .eye-pupil { scale: .62; }
.pill-eye.eye-m-dilate .eye-pupil { scale: 1.22; }
`;
	const style = document.createElement("style");
	style.textContent = MOOD_CSS;
	document.head.appendChild(style);

	const MOOD_CLASSES = [
		"eye-m-slow",
		"eye-m-dart",
		"eye-m-shut",
		"eye-m-squint",
		"eye-m-sleepy",
		"eye-m-wide",
		"eye-m-wince",
		"eye-m-shrink",
		"eye-m-dilate",
	];
	const motionOK = () => !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
	const wait = (ms) => new Promise((r) => setTimeout(r, ms));
	const rand = (a, b) => a + Math.random() * (b - a);

	const eyes = () => [...document.querySelectorAll(".pill-eye")];

	// Put every pill eye into a pose: lid classes, and the iris offset as a fraction
	// of the socket's width/height (0,0 is centred). `slow` eases the move.
	function pose(classes, fx, fy, opts = {}) {
		for (const el of eyes()) {
			el.classList.remove(...MOOD_CLASSES);
			if (classes) el.classList.add(...classes.split(" ").filter(Boolean));
			if (opts.slow) el.classList.add("eye-m-slow");
			if (opts.dart) el.classList.add("eye-m-dart");
			const pupil = el.querySelector(".eye-pupil");
			const sock = el.querySelector(".eye-socket");
			if (!pupil || !sock || fx === undefined) continue;
			const r = sock.getBoundingClientRect();
			pupil.style.transform =
				"translate(calc(-50% + " +
				(fx * r.width).toFixed(2) +
				"px), calc(-50% + " +
				(fy * r.height).toFixed(2) +
				"px))";
		}
	}
	function setMood(name) {
		for (const el of eyes()) {
			if (name) el.dataset.mood = name;
			else delete el.dataset.mood;
		}
	}
	// Hand the eye back to the shell's own follow/glance code.
	function release() {
		pose("", 0, 0);
		setMood(null);
		for (const el of eyes()) {
			const p = el.querySelector(".eye-pupil");
			if (p) p.style.transform = "";
		}
	}

	let busy = null; // the one-shot mood playing now, if any
	let held = null; // a persistent mood (search, vault) that outlives one-shots
	const ONE_SHOTS = {
		// A keep: one slow, satisfied blink.
		approve: async () => {
			pose("eye-m-sleepy", 0, 0.05);
			await wait(900);
			pose("eye-m-shut", 0, 0.05);
			await wait(260);
			pose("", 0, 0);
			await wait(250);
		},
		// Search came back: eyes wide, pupil blown.
		found: async () => {
			pose("eye-m-wide eye-m-dilate", 0, 0);
			await wait(700);
		},
		// Something new arrived: pop wide open with a pinprick pupil.
		startle: async () => {
			pose("eye-m-wide eye-m-shrink", 0, -0.05);
			await wait(900);
		},
		// Poked three times: wince, twitch, pointedly look away.
		annoyed: async () => {
			for (let i = 0; i < 4; i++) {
				pose("eye-m-wince", i % 2 ? 0.1 : -0.1, -0.06);
				await wait(70);
			}
			pose("", -0.26, 0.12, { slow: true });
			await wait(1300);
		},
		// The lazy eye: drifts down and out, holds too long, snaps back.
		lazy: async () => {
			const side = Math.random() < 0.5 ? -1 : 1;
			pose("", side * rand(0.2, 0.26), rand(0.08, 0.16), { slow: true });
			await wait(rand(1900, 3200));
		},
		// Woken from a doze: a startled blink awake.
		wake: async () => {
			pose("eye-m-wide", 0, 0);
			await wait(380);
		},
	};

	async function play(name) {
		const run = ONE_SHOTS[name];
		if (!run || busy || held || !motionOK() || !eyes().length) return;
		busy = name;
		setMood(name);
		try {
			await run();
		} finally {
			busy = null;
			if (held) applyHeld();
			else release();
		}
	}

	// Persistent moods, held until released: squinting through a search (darting
	// side to side), and averting its gaze - shut - while the vault is open.
	let dartTimer = 0;
	function applyHeld() {
		clearInterval(dartTimer);
		setMood(held);
		if (held === "avert") {
			pose("eye-m-shut", 0.26, 0.1);
		} else if (held === "search") {
			let side = 1;
			pose("eye-m-squint", 0.2, 0, { dart: true });
			if (motionOK())
				dartTimer = setInterval(() => {
					side = -side;
					pose("eye-m-squint", side * 0.2, 0, { dart: true });
				}, 260);
		}
	}
	function hold(name) {
		held = name;
		applyHeld();
	}
	function drop(name, then) {
		if (held !== name) return;
		held = null;
		clearInterval(dartTimer);
		release();
		if (then) play(then);
	}

	// The lazy eye comes and goes on its own, and never interrupts a mood.
	(function lazyLoop() {
		setTimeout(
			() => {
				if (!busy && !held && !dozing && !document.hidden) play("lazy");
				lazyLoop();
			},
			rand(9000, 16000),
		);
	})();

	// Dozing: a minute with no input and the lid droops; any input wakes it.
	let dozing = false;
	let idleTimer = 0;
	function armIdle() {
		clearTimeout(idleTimer);
		idleTimer = setTimeout(() => {
			if (busy || held || !motionOK() || !eyes().length) return armIdle();
			dozing = true;
			setMood("doze");
			pose("eye-m-sleepy", 0, 0.14, { slow: true });
		}, 60000);
	}
	function activity() {
		if (dozing) {
			dozing = false;
			release();
			play("wake");
		}
		armIdle();
	}
	for (const ev of ["pointermove", "pointerdown", "keydown", "wheel", "touchstart", "scroll"])
		addEventListener(ev, activity, { passive: true, capture: true });
	armIdle();

	// Three pokes in quick succession annoy it.
	let pokes = [];
	addEventListener(
		"pointerdown",
		(e) => {
			if (!e.target.closest || !e.target.closest(".pill-eye, .pill .round:has(.pill-eye)"))
				return;
			const t = Date.now();
			pokes = pokes.filter((x) => t - x < 900);
			pokes.push(t);
			if (pokes.length >= 3) {
				pokes = [];
				play("annoyed");
			}
		},
		{ passive: true, capture: true },
	);

	// A freshly rendered pill eye picks up a held mood (the pill re-renders on
	// navigation, which would otherwise drop the vault's averted gaze).
	function refresh() {
		if (held) applyHeld();
	}

	window.eyeMood = { play, hold, drop, refresh };
})();
