// The first-run welcome: a few short steps on a fresh library, shown once.
//
// It shows when the library is empty, the three setup steps are not all done
// (GET /setup), and the welcome was never finished or skipped (the `welcome_done`
// setting, so it survives a cleared webview). Every step can be skipped. Nothing
// here is new machinery: the assistant step writes the same settings the Assistant
// tab does, the sync step IS the Sync tab (rendered into this page through
// renderSettingsTab, so the sign-in, the recovery phrase and joining another
// computer work exactly as they do there), and the recovery kit and the phone code
// use the Library and Sync tabs' own functions.
//
// Loaded before settings.js, whose last line boots the app.

const WELCOME_STEPS = [
	{ id: "hello", label: "Overview" },
	{ id: "ai", label: "Assistant" },
	{ id: "sync", label: "Sync" },
	{ id: "kit", label: "Recovery kit" },
	{ id: "phone", label: "Phone" },
];
let welcomeAt = 0;
// Opened from the ? on the home header, on a library already in use: the same steps,
// each showing where this Mac stands, and the way out says Close, not Skip.
let welcomeOnDemand = false;

// The ? at the top right of the home header, which opens the welcome on demand.
function welcomeTriggerHtml() {
	return (
		'<button type="button" class="tour-open" onclick="openWelcome()" ' +
		'aria-label="Set up Enqueue" title="Set up Enqueue">' +
		// The tour's ? glyph (js/tour.js), drawn the same way.
		'<svg viewBox="0 0 24 24" aria-hidden="true">' +
		'<path d="M9.2 9.2a2.9 2.9 0 0 1 5.6 1c0 1.9-2.8 2.4-2.8 4.3"/>' +
		'<path d="M12 17.6v.01"/></svg></button>'
	);
}

function openWelcome() {
	if (typeof teardown === "function") teardown();
	welcomeOnDemand = true;
	welcomeAt = 0;
	renderWelcome();
}

// Whether to show the welcome instead of the empty wall, and show it if so.
async function maybeWelcome() {
	let d, setup;
	try {
		[d, setup] = await Promise.all([api("/settings"), api("/setup")]);
	} catch {
		return false;
	}
	const done = d.settings.welcome_done && d.settings.welcome_done.value;
	const steps = (setup && setup.steps) || [];
	if (done || (steps.length && steps.every((s) => s.state === "done"))) return false;
	welcomeOnDemand = false;
	welcomeAt = 0;
	await renderWelcome();
	return true;
}

function welcomeOpen() {
	return !!document.getElementById("welcome");
}

// Leave the welcome for good (finished or skipped) and land on the wall.
async function finishWelcome() {
	try {
		await api("/settings", {
			method: "PATCH",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ changes: { welcome_done: true } }),
		});
	} catch {
		// Not remembered: it comes back on the next empty wall, which is harmless.
	}
	welcomeLeaveStep();
	currentSettingsTab = "ai";
	home();
}

function welcomeGo(index) {
	welcomeLeaveStep();
	welcomeAt = Math.max(0, Math.min(WELCOME_STEPS.length - 1, index));
	renderWelcome();
}

// The sync walk and the phone code keep state outside the page; a step that is left
// must not leave a code on screen or a sign-in poll pointed at it.
function welcomeLeaveStep() {
	if (typeof hideLinkCode === "function") hideLinkCode();
	if (window.syncSetupStep === "signin") {
		window.syncSetupStep = null;
		window.accountSignInUrl = null;
	}
}

async function renderWelcome() {
	const step = WELCOME_STEPS[welcomeAt];
	const last = welcomeAt === WELCOME_STEPS.length - 1;
	const body = await WELCOME_RENDER[step.id]();
	view.innerHTML =
		'<div class="pagecol settings-page welcome" id="welcome">' +
		'<div class="settings-head">' +
		'<div class="settings-title">' +
		'<div class="settings-eye eye" id="welcomeEye" aria-hidden="true"></div>' +
		'<h1 class="display">Welcome to Enqueue<span class="greet-mark">.</span></h1>' +
		"</div>" +
		'<ol class="welcome-steps" aria-label="Steps">' +
		WELCOME_STEPS.map(
			(s, i) =>
				'<li data-state="' +
				(i < welcomeAt ? "past" : i === welcomeAt ? "now" : "next") +
				'"' +
				(i === welcomeAt ? ' aria-current="step"' : "") +
				'><button type="button" onclick="welcomeGo(' +
				i +
				')"><span class="welcome-dot" aria-hidden="true"></span>' +
				esc(s.label) +
				"</button></li>",
		).join("") +
		"</ol>" +
		"</div>" +
		'<div class="welcome-body">' +
		body +
		"</div>" +
		'<div class="welcome-nav">' +
		(welcomeAt > 0
			? '<button class="btn ghost" onclick="welcomeGo(' + (welcomeAt - 1) + ')">Back</button>'
			: '<button class="btn ghost" onclick="finishWelcome()">' +
				(welcomeOnDemand ? "Close" : "Skip all of this") +
				"</button>") +
		'<span class="welcome-nav-gap"></span>' +
		(last
			? '<button class="btn primary" onclick="finishWelcome()">' +
				(welcomeOnDemand ? "Done" : "Start using Enqueue") +
				"</button>"
			: (welcomeAt > 0
					? '<button class="btn ghost" onclick="welcomeGo(' + (welcomeAt + 1) + ')">Skip this step</button>'
					: "") +
				'<button class="btn primary" onclick="welcomeGo(' +
				(welcomeAt + 1) +
				')">' +
				(welcomeAt === 0 ? "Set it up" : "Next") +
				"</button>") +
		"</div>" +
		"</div>";
	makeEye(document.getElementById("welcomeEye"));
	window.scrollTo(0, 0);
	if (step.id === "sync") {
		currentSettingsTab = "sync";
		await renderSettingsTab("sync");
	}
}

const WELCOME_RENDER = {
	// The hub: the tour (what Enqueue does, with live demos) and the setup list (where
	// this Mac stands), on one page. A first run walks from one into the other; the ?
	// on a library in use lands here to replay the tour or finish what is left.
	hello: async () => {
		const rows = await welcomeChecklist();
		return (
			'<div class="welcome-hub">' +
			'<p class="welcome-lead">Save anything. Find it again.</p>' +
			'<p class="welcome-sub">Notes, links, PDFs, pictures and files go in as they are, ' +
			"with nothing to file. Find them by searching, or by asking in your own words.</p>" +
			'<button type="button" class="welcome-tourcard" onclick="welcomePlayTour()">' +
			'<span class="welcome-deck" aria-hidden="true">' +
			"<span></span><span></span>" +
			'<span><img class="welcome-deck-mark" src="/static/raven-mark.png" alt=""></span>' +
			"</span>" +
			'<span class="welcome-tourcard-words">' +
			'<span class="welcome-tourcard-title">See how it works</span>' +
			'<span class="welcome-tourcard-copy">Seven short cards you can try: capture, ' +
			"search, ask, summaries, views and privacy. About a minute.</span>" +
			"</span>" +
			'<span class="welcome-tourcard-go" aria-hidden="true">' +
			'<svg viewBox="0 0 24 24"><path d="M8 5.5v13l10.5-6.5z"/></svg>' +
			"</span>" +
			"</button>" +
			"</div>" +
			'<div class="shelf">Set it up</div>' +
			'<div class="group welcome-checklist">' +
			rows +
			"</div>"
		);
	},

	ai: async () => {
		const [d, setup] = await Promise.all([api("/settings"), api("/setup").catch(() => null)]);
		const stand = ((setup && setup.steps) || []).find((x) => x.id === "model");
		const chosen = d.settings.llm_backend.value;
		const online = d.backends.filter((b) => !b.local);
		const pick = online.find((b) => b.name === chosen) || online[0];
		const local = (d.backends.find((b) => b.local) || {}).name || "ollama";
		const isLocal = !online.some((b) => b.name === chosen);
		return (
			'<div class="shelf">Choose your assistant</div>' +
			'<div class="group">' +
			'<div class="aside">The assistant reads what you save, so you can find things by ' +
			"what they're about and ask questions. Pick where it runs.</div>" +
			'<div class="field"><span class="rowlabel">On this Mac</span>' +
			'<div class="aside">Private: nothing leaves your computer. Needs the free ' +
			"<b>Ollama</b> app, from ollama.com.</div>" +
			(isLocal
				? '<span class="welcome-chosen">Chosen</span>'
				: '<button class="btn tertiary" onclick="welcomeUseLocal(' +
					esc(JSON.stringify(local)) +
					')">Use this Mac</button>') +
			"</div>" +
			'<div class="field"><span class="rowlabel">An online service, with your own key</span>' +
			'<div class="aside">Faster and smarter on most Macs. When you ask something, the ' +
			"notes it needs are sent to the service you pick.</div>" +
			(isLocal ? "" : '<span class="welcome-chosen">Chosen</span>') +
			"</div>" +
			'<div class="field welcome-online"><label for="w_backend">Service</label>' +
			'<select id="w_backend">' +
			online
				.map(
					(b) =>
						'<option value="' +
						esc(b.name) +
						'"' +
						(b.name === pick.name ? " selected" : "") +
						">" +
						esc(b.label) +
						"</option>",
				)
				.join("") +
			"</select></div>" +
			'<div class="field welcome-online"><label for="w_key">Your key</label>' +
			'<div class="aside">The service gives you one when you sign up. Kept safely in ' +
			"this Mac's Keychain." +
			(!isLocal && d.storage.api_key_present ? " A key is saved already." : "") +
			"</div>" +
			'<div class="keyrow"><input id="w_key" type="password" autocomplete="off" ' +
			'spellcheck="false" placeholder="Paste your key">' +
			'<button class="btn primary sm" onclick="welcomeUseOnline()">Use it</button></div>' +
			'<div id="w_state" class="aside caution">' +
			(stand && stand.state !== "done"
				? esc(stand.detail) + ". Finish in Settings, Assistant."
				: "") +
			"</div>" +
			"</div>" +
			"</div>" +
			'<p class="welcome-note">An assistant included with Enqueue is coming, so you ' +
			"won't need a key of your own. Until then, pick one of these. You can switch any " +
			"time in Settings, Assistant.</p>"
		);
	},

	sync: async () => '<div class="settings-layout"><div id="settingsTabPane"></div></div>',

	kit: async () => {
		let b = {};
		try {
			b = await api("/backup");
		} catch {
			// Shown as not saved; the kit itself comes from its own request.
		}
		return (
			'<div class="shelf">Save your recovery kit</div>' +
			'<div class="group">' +
			'<div class="aside">If this Mac is lost along with every other device, this ' +
			"code is the way back to your library. It's separate from the sync recovery " +
			"phrase, if you wrote one down.</div>" +
			backupKitHtml(!!b.kit_saved, !!b.library_encrypted) +
			"</div>"
		);
	},

	phone: async () => {
		const d = await api("/settings");
		const sync = d.sync || {};
		if (!sync.relay_configured)
			return (
				'<div class="shelf">Link your phone</div>' +
				'<div class="group">' +
				'<div class="field"><span class="rowlabel">Turn on sync first</span>' +
				'<div class="aside">Your phone gets your library through sync. You can turn it ' +
				"on now, or later in Settings, Sync.</div>" +
				'<button class="btn tertiary" onclick="welcomeGo(2)">Turn on sync</button>' +
				"</div></div>"
			);
		return (
			'<div class="shelf">Link your phone</div>' +
			'<div class="group">' +
			'<div class="aside">Install Enqueue on your Android phone and open it. ' +
			"It asks you to scan a code: show it here and point the phone at it.</div>" +
			'<div class="field"><span class="rowlabel">Your code</span>' +
			'<div class="aside">Opens your library, so keep it to yourself: no screenshots.</div>' +
			'<button class="btn primary" id="linkShowBtn" aria-expanded="false" ' +
			'aria-controls="linkQRArea" onclick="toggleLinkCode()">Show the code</button>' +
			"</div>" +
			'<div class="link-qr" id="linkQRArea" hidden>' +
			'<div class="link-qr-code" id="linkQR"></div>' +
			'<p class="link-qr-note">It disappears when you move on.</p>' +
			"</div>" +
			"</div>"
		);
	},
};

// The tour, then on into the first setup step (the deck's last button says so).
function welcomePlayTour() {
	if (typeof Tour === "undefined") return;
	Tour.open({ label: "Set it up", then: () => welcomeGo(1) });
}

// One row per setup step, with where this Mac stands. Read from the same places the
// steps themselves read; a failed read shows the step as not done, never an error.
async function welcomeChecklist() {
	const [d, setup, b] = await Promise.all([
		api("/settings").catch(() => null),
		api("/setup").catch(() => null),
		api("/backup").catch(() => null),
	]);
	const step = (id) => ((setup && setup.steps) || []).find((x) => x.id === id) || {};
	const model = step("model");
	const phone = step("phone");
	const sync = (d && d.sync) || {};
	const acct = sync.account || {};
	const state = {
		ai: model.state === "done" ? ["done", model.detail || "Connected"] : ["todo", model.detail || "Not chosen yet"],
		sync: sync.relay_configured
			? ["done", acct.email ? "Signed in as " + acct.email : "On"]
			: ["todo", "Off: your library stays on this Mac"],
		kit: b && b.kit_saved ? ["done", "Saved"] : ["todo", "Not saved yet"],
		phone:
			phone.state === "done"
				? ["done", "Show the code any time to link another"]
				: ["todo", "Not linked"],
	};
	return WELCOME_STEPS.slice(1)
		.map((s, i) => {
			const [st, detail] = state[s.id] || ["todo", ""];
			return (
				'<button type="button" class="welcome-row" data-state="' +
				st +
				'" onclick="welcomeGo(' +
				(i + 1) +
				')">' +
				'<span class="welcome-row-mark" aria-hidden="true">' +
				(st === "done" ? '<svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>' : "") +
				"</span>" +
				'<span class="welcome-row-words"><span class="welcome-row-title">' +
				esc(s.label) +
				'</span><span class="welcome-row-detail">' +
				esc(detail) +
				"</span></span>" +
				'<span class="welcome-row-go">' +
				(st === "done" ? "Change" : "Set up") +
				"</span></button>"
			);
		})
		.join("");
}

async function welcomeSettings(changes) {
	await api("/settings", {
		method: "PATCH",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ changes }),
	});
}

async function welcomeUseLocal(name) {
	try {
		await welcomeSettings({ llm_backend: name, llm_model: BACKEND_MODELS[name] || null });
	} catch (err) {
		return toast(String(err.message || err), true);
	}
	toast("The assistant runs on this Mac.");
	renderWelcome();
}

async function welcomeUseOnline() {
	const name = document.getElementById("w_backend").value;
	const field = document.getElementById("w_key");
	const state = document.getElementById("w_state");
	const key = field.value.trim();
	try {
		await welcomeSettings({ llm_backend: name, llm_model: BACKEND_MODELS[name] || null });
		if (key)
			await api("/settings/api-key", {
				method: "PUT",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ key }),
			});
	} catch (err) {
		state.textContent = String(err.message || err);
		return;
	}
	field.value = "";
	const label = document.getElementById("w_backend").selectedOptions[0].textContent;
	toast(key ? "Saved. The assistant uses " + label + "." : "Chosen. Add your key to use it.");
	welcomeGo(welcomeAt + 1);
}
