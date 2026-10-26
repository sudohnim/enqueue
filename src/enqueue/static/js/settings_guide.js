// Settings that explain themselves (desktop). Three pieces, all fed by js/guides.js:
//
//   the mark    a ? beside a section heading, where one line cannot do the job
//   the guide   the Details plate, opened beside the setting it is about
//   the eye     in settings it answers about settings: a guide matched in the page
//               first, a model only when nothing matches well
//
// Plus where the installation stands (GET /setup): the "left to set up" cards, the
// settings that need a look, and the marks on the tabs.
//
// Loaded BEFORE settings.js, whose last line boots the app (and may open Settings at
// once): everything here is a function it calls later.
//
// Nothing in settings.js had to learn about guides: the headings are found after each
// tab renders (SHELF_GUIDES), so a new section gets its mark by adding one line here.

// Section heading -> guide, per tab. A heading with no entry gets no mark, which is
// right for anything its one-line note already explains.
const SHELF_GUIDES = {
	ai: {
		"Where answers come from": "answers",
		"Which AI does each job": "models",
		Summaries: "concepts",
	},
	features: { Capturing: "hotkey", Links: "link-previews", Search: "search-options" },
	storage: { Backup: "backups", Drafts: "drafts" },
	trash: { Trash: "trash" },
	sync: {
		"Join a library": "join-library",
		"Already using Enqueue on another computer?": "join-library",
		"Link your phone": "link-phone",
		"Add another computer": "pair-computer",
		"Start sync over": "reset-sync",
	},
	events: { Activity: "activity" },
};

// "Set up sync" is three screens under one heading; the guide follows the screen.
function syncSetupGuide() {
	const step = window.syncSetupStep || 1;
	if (step === "recovery") return "recovery-phrase";
	if (step === 3) return "sync-secret";
	return "relay";
}

const GUIDE_EYE =
	'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z"/>' +
	'<circle cx="12" cy="12" r="3"/></svg>';

let setupState = null; // the last GET /setup
let guideOpenId = null;
let guideReturn = null; // what to give the focus back to when the plate closes

function guideMarkHtml(id) {
	return Guides.mark(id, guideOpenId === id);
}

// Put the marks on a freshly rendered tab. Safe to run again on the same DOM.
function decorateSettingsGuides() {
	const pane = document.getElementById("settingsTabPane");
	if (!pane) return;
	const map = SHELF_GUIDES[currentSettingsTab] || {};
	pane.querySelectorAll(".shelf, .settings-card-label").forEach((head) => {
		if (head.querySelector(".gmark")) return;
		const name = head.textContent.trim();
		const id = name === "Use Enqueue on your phone" ? syncSetupGuide() : map[name];
		if (!id || !Guides.get(id)) return;
		head.insertAdjacentHTML("beforeend", guideMarkHtml(id));
		// The thing the guide is about: the card under the heading.
		const target = head.classList.contains("shelf")
			? head.nextElementSibling
			: head.closest(".settings-card");
		if (target) target.dataset.guideFor = id;
	});
	// The index has no heading of its own; its button is the anchor.
	const rebuild = pane.querySelector('button[onclick^="rebuildIndex"]');
	if (rebuild && !pane.querySelector('[data-guide-for="index"]')) {
		const group = rebuild.closest(".group");
		const label = rebuild.closest(".field")?.querySelector(".rowlabel");
		if (group && label) {
			group.dataset.guideFor = "index";
			label.style.display = "flex";
			label.style.alignItems = "center";
			label.style.gap = "8px";
			label.insertAdjacentHTML("beforeend", guideMarkHtml("index"));
		}
	}
	lightGuideTarget();
}

// A tab re-renders parts of itself (the sync walk, the backup section, a save), so
// the marks are put back whenever the pane changes rather than at one call site.
let guideWatch = null;
function watchSettingsPane() {
	const pane = document.getElementById("settingsTabPane");
	if (guideWatch) guideWatch.disconnect();
	if (!pane) return;
	let queued = false;
	guideWatch = new MutationObserver(() => {
		if (queued) return;
		queued = true;
		requestAnimationFrame(() => {
			queued = false;
			if (!document.getElementById("settingsTabPane")) return;
			// The sync walk moved on: the open guide follows it.
			if (guideOpenId && ["relay", "recovery-phrase", "sync-secret"].includes(guideOpenId)) {
				const now = syncSetupGuide();
				const heads = [...pane.querySelectorAll(".shelf")].map((h) => h.textContent.trim());
				if (heads.some((h) => h.startsWith("Set up sync")) && now !== guideOpenId) openGuide(now, { keepFocus: true });
			}
			decorateSettingsGuides();
		});
	});
	guideWatch.observe(pane, { childList: true, subtree: true });
}

// ---- where the installation stands ------------------------------------------
async function refreshSetup() {
	try {
		setupState = await api("/setup");
	} catch (err) {
		setupState = null;
	}
	renderSetup();
	// An open guide's "where you stand" line follows a change (a key saved, a folder chosen).
	if (guideOpenId) renderGuideBody(guideOpenId);
}

function renderSetup() {
	const strip = document.getElementById("settingsSetup");
	if (!strip) return;
	const steps = (setupState && setupState.steps) || [];
	const alerts = (setupState && setupState.alerts) || [];
	// Where things stand, as one quiet line under the title: a dot per step, and a
	// way in on the ones not done.
	strip.innerHTML = steps.length
		? '<ul class="setup-line" aria-label="Where things stand">' +
			steps
				.map(
					(s) =>
						'<li data-state="' +
						esc(s.state) +
						'"><span class="setup-dot" aria-hidden="true"></span>' +
						esc(s.title) +
						(s.state === "done"
							? ""
							: ' <button type="button" class="setup-go" data-guide="' +
								esc(s.guide) +
								'">' +
								esc(s.state === "warn" ? "Fix" : "Set up") +
								"</button>") +
						"</li>",
				)
				.join("") +
			"</ul>"
		: "";
	// A setting that needs a look is said on its own tab, above its settings.
	const notes = document.getElementById("settingsNotes");
	const here = alerts.filter((a) => !a.tab || a.tab === currentSettingsTab);
	if (notes)
		notes.innerHTML = here.length
			? '<ul class="setup-alerts" aria-label="Needs a look">' +
				here
					.map(
						(a) =>
							'<li data-level="' +
							esc(a.level) +
							'"><span>' +
							esc(a.text) +
							'</span><button type="button" class="setup-go" data-guide="' +
							esc(a.guide) +
							'">Show me</button></li>',
					)
					.join("") +
				"</ul>"
			: "";
	// The tabs say where something is left.
	const todo = new Set(
		steps
			.filter((s) => s.state !== "done")
			.map((s) => s.tab)
			.concat(alerts.filter((a) => a.level === "warn").map((a) => a.tab)),
	);
	for (const t of SETTINGS_TABS) {
		const b = document.getElementById("tab-" + t.id);
		if (!b) continue;
		const had = b.querySelector(".tab-todo");
		if (todo.has(t.id) && !had) b.insertAdjacentHTML("beforeend", '<span class="tab-todo" aria-label="to do"></span>');
		else if (!todo.has(t.id) && had) had.remove();
	}
}

// ---- the guide ----------------------------------------------------------------
function guideBodyHtml(g) {
	return Guides.html(g, Guides.stand(g.id, setupState));
}

function renderGuideBody(id) {
	const g = Guides.get(id);
	const panel = document.getElementById("guide");
	if (!g || !panel) return;
	panel.querySelector(".dpanel-title").textContent = g.title;
	panel.querySelector(".dpanel-voice").textContent = g.voice;
	const body = panel.querySelector(".dpanel-body");
	body.innerHTML = guideBodyHtml(g);
	panel.querySelector(".gask-words").textContent = "Ask about " + g.title.replace(/^The /, "the ");
}

function lightGuideTarget() {
	document.querySelectorAll(".guide-lit").forEach((el) => el.classList.remove("guide-lit"));
	document.querySelectorAll(".gmark").forEach((m) => {
		m.setAttribute("aria-expanded", String(m.dataset.guide === guideOpenId));
	});
	if (!guideOpenId) return null;
	const target = document.querySelector('[data-guide-for="' + guideOpenId + '"]');
	if (target) target.classList.add("guide-lit");
	return target;
}

// Open a guide beside its setting. Goes to the guide's tab first when it is on
// another one, so the setting it talks about is always the one on screen.
async function openGuide(id, opts) {
	const g = Guides.get(id);
	if (!g || !document.getElementById("settingsTabPane")) return;
	const o = opts || {};
	closeSettingsAsk(true);
	if (!o.keepFocus && !guideOpenId) guideReturn = document.activeElement;
	if (g.tab !== currentSettingsTab) await renderSettingsTab(g.tab);

	let panel = document.getElementById("guide");
	const arriving = !panel;
	if (!panel) {
		panel = document.createElement("aside");
		panel.id = "guide";
		panel.className = "drawer dpanel guide";
		panel.setAttribute("aria-label", "Guide");
		panel.innerHTML =
			'<div class="dpanel-top">' +
			'<img class="dpanel-perch" src="/static/raven-tilt.png" alt="" aria-hidden="true">' +
			'<div class="dpanel-heading"><span class="dpanel-title"></span>' +
			'<span class="dpanel-voice"></span></div>' +
			'<button type="button" class="dpanel-close" aria-label="Close guide" title="Close guide">' +
			svg("close") +
			"</button></div>" +
			'<div class="dpanel-body" tabindex="-1"></div>' +
			'<button type="button" class="gask"><span class="gask-eye">' +
			GUIDE_EYE +
			'</span><span class="gask-words"></span></button>';
		view.appendChild(panel);
		panel.querySelector(".dpanel-close").addEventListener("click", () => closeGuide());
		panel.querySelector(".gask").addEventListener("click", () => {
			const about = Guides.get(guideOpenId);
			openSettingsAsk(about ? about.title.replace(/^The /, "") + ": " : "");
		});
	}
	guideOpenId = id;
	renderGuideBody(id);
	panel.querySelector(".dpanel-body").scrollTop = 0;
	// Next frame, so the plate slides in from its closed position.
	requestAnimationFrame(() => {
		panel.classList.add("open");
		if (arriving) Details.arrive(panel);
	});
	decorateSettingsGuides();
	const target = lightGuideTarget();
	if (target) target.scrollIntoView({ block: "nearest", behavior: "smooth" });
	if (!o.keepFocus) panel.querySelector(".dpanel-close").focus({ preventScroll: true });
}

function closeGuide() {
	const panel = document.getElementById("guide");
	guideOpenId = null;
	lightGuideTarget();
	if (!panel) return;
	panel.classList.remove("open");
	// After the slide out (matches .drawer's closing transition).
	setTimeout(() => {
		if (!guideOpenId) panel.remove();
	}, 320);
	if (guideReturn && document.contains(guideReturn)) guideReturn.focus({ preventScroll: true });
	guideReturn = null;
}

// One delegated listener for every mark, chip and "Show me".
document.addEventListener("click", (e) => {
	const el = e.target.closest && e.target.closest("[data-guide]");
	if (!el || !document.getElementById("settingsTabPane")) return;
	if (el.closest("#settingsAsk")) return; // the eye's panel handles its own rows
	e.preventDefault();
	const id = el.dataset.guide;
	if (el.classList.contains("gmark") && guideOpenId === id) return closeGuide();
	openGuide(id, { keepFocus: el.classList.contains("gchip") });
});
document.addEventListener(
	"keydown",
	(e) => {
		if (e.key !== "Escape") return;
		if (document.getElementById("settingsAsk")) {
			e.stopPropagation();
			closeSettingsAsk(true);
		} else if (guideOpenId && !e.target.closest("input, textarea, select")) {
			e.stopPropagation();
			closeGuide();
		}
	},
	true,
);

// ---- the eye, in settings -------------------------------------------------------
// Typing ranks the guides in the page (Guides.match): no request, no model. Enter on
// a sure match opens that guide. Only a question no guide clearly answers goes to the
// model, with the few closest guides and where the installation stands.
let saskLit = -1;
let saskRows = [];
let saskAsking = 0;

function closeSettingsAsk(restore) {
	const panel = document.getElementById("settingsAsk");
	if (panel) panel.remove();
	saskAsking++;
	if (window.eyeMood) eyeMood.drop("search");
	if (restore && pill.classList.contains("wide")) restorePill();
}

function openSettingsAsk(prefill) {
	closeMenu();
	pill.classList.add("wide");
	pill.innerHTML =
		'<span class="scope">settings</span>' +
		'<input id="field" placeholder="ask about settings" aria-label="Ask about settings" ' +
		'autocomplete="off" role="combobox" aria-autocomplete="list" aria-expanded="true" ' +
		'aria-controls="settingsAskList">' +
		'<button class="round" aria-label="Close" onclick="closeSettingsAsk(true)">' +
		svg("close") +
		"</button>";
	let panel = document.getElementById("settingsAsk");
	if (!panel) {
		panel = document.createElement("div");
		panel.id = "settingsAsk";
		panel.className = "sask";
		document.body.appendChild(panel);
		panel.addEventListener("mousedown", (e) => {
			// A press in the panel must not take the caret out of the field.
			if (!e.target.closest("a")) e.preventDefault();
		});
		panel.addEventListener("click", (e) => {
			const row = e.target.closest(".sask-row, .sask-go, .gchip");
			if (!row) return;
			if (row.dataset.ask !== undefined) return askSettingsModel(document.getElementById("field").value);
			if (row.dataset.guide) openGuide(row.dataset.guide);
		});
	}
	const field = document.getElementById("field");
	field.value = prefill || "";
	field.focus();
	field.addEventListener("input", () => renderSettingsMatches(field.value));
	field.addEventListener("keydown", (e) => {
		if (e.key === "ArrowDown" || e.key === "ArrowUp") {
			if (!saskRows.length) return;
			e.preventDefault();
			saskLit = (saskLit + (e.key === "ArrowDown" ? 1 : -1) + saskRows.length) % saskRows.length;
			paintSettingsRows();
		} else if (e.key === "Enter") {
			e.preventDefault();
			const row = saskRows[saskLit];
			if (!row) return;
			if (row.ask) askSettingsModel(field.value);
			else openGuide(row.guide);
		}
	});
	renderSettingsMatches(field.value);
}

function paintSettingsRows() {
	document.querySelectorAll("#settingsAsk .sask-row").forEach((el, i) => {
		el.setAttribute("aria-selected", String(i === saskLit));
		if (i === saskLit) el.scrollIntoView({ block: "nearest" });
	});
}

function modelConnected() {
	const step = setupState && setupState.steps && setupState.steps.find((s) => s.id === "model");
	return !!step && step.state === "done";
}

function settingsRowHtml(g, i) {
	return (
		'<li role="none"><button type="button" role="option" id="sask' +
		i +
		'" class="sask-row" aria-selected="false" data-guide="' +
		esc(g.id) +
		'"><b>' +
		esc(g.title) +
		"</b><small>" +
		esc(g.voice) +
		"</small></button></li>"
	);
}

function renderSettingsMatches(typed) {
	const panel = document.getElementById("settingsAsk");
	if (!panel) return;
	saskAsking++;
	if (window.eyeMood) eyeMood.drop("search");
	const text = (typed || "").trim();
	const matches = Guides.match(text, { platform: "desktop", tab: currentSettingsTab });
	let guides;
	let head;
	if (!text || !matches.length) {
		// Nothing typed, or nothing found: what is left to set up, then this tab's guides.
		const first = ((setupState && setupState.steps) || [])
			.filter((s) => s.state !== "done")
			.map((s) => Guides.get(s.guide));
		const here = Guides.all("desktop").filter((g) => g.tab === currentSettingsTab);
		guides = [...new Set(first.concat(here).filter(Boolean))].slice(0, 5);
		head = text ? "No guide by that name. These are on this page" : "On this page";
	} else {
		// The clear ones only: a guide that shares one stray word is noise.
		const floor = matches[0].score * 0.45;
		guides = matches
			.filter((m) => m.score >= floor)
			.slice(0, 4)
			.map((m) => m.guide);
		head = "Guides";
	}
	saskRows = guides.map((g) => ({ guide: g.id }));
	// A typed question can always be put to the model, when one is connected.
	const canAsk = text.length > 2 && modelConnected();
	if (canAsk) saskRows.push({ ask: true });
	// Enter opens the closest guide: a guide costs nothing, and it says where this
	// installation stands. The model is asked only on purpose (its row), or when no
	// guide matched at all.
	saskLit = !text ? -1 : matches.length || !canAsk ? 0 : saskRows.length - 1;
	panel.innerHTML =
		'<p class="sask-head">' +
		esc(head) +
		'</p><ul class="sask-list" id="settingsAskList" role="listbox" aria-label="Guides">' +
		guides.map(settingsRowHtml).join("") +
		(canAsk
			? '<li role="none"><button type="button" role="option" class="sask-row ask" aria-selected="false" data-ask>' +
				"<b>Ask: " +
				esc(text) +
				"</b><small>Reads these guides and where your setup stands. Not your notes.</small></button></li>"
			: "") +
		"</ul>";
	paintSettingsRows();
}

// The one model call: a question none of the guides clearly answers by name.
async function askSettingsModel(question) {
	const q = (question || "").trim();
	const panel = document.getElementById("settingsAsk");
	if (!q || !panel) return;
	const mine = ++saskAsking;
	const matches = Guides.match(q, { platform: "desktop", tab: currentSettingsTab });
	const offered = (matches.length ? matches.map((m) => m.guide) : Guides.all("desktop")).slice(0, 5);
	saskRows = [];
	saskLit = -1;
	panel.innerHTML =
		'<div class="sask-answer"><p class="sask-q">' +
		esc(q) +
		'</p><div class="sask-wait">' +
		spinner("sm", "Reading the guides…") +
		"</div></div>";
	if (window.eyeMood) eyeMood.hold("search");
	let out = null;
	let failed = "";
	try {
		out = await api("/setup/ask", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				question: q,
				guides: offered.map((g) => ({ id: g.id, title: g.title, text: Guides.text(g) })),
			}),
		});
	} catch (err) {
		failed = String((err && err.message) || err);
	}
	if (mine !== saskAsking || !document.getElementById("settingsAsk")) return;
	if (window.eyeMood) eyeMood.drop("search");
	if (!out) {
		// No answer: the closest guides are still worth more than an error.
		saskRows = offered.slice(0, 4).map((g) => ({ guide: g.id }));
		saskLit = 0;
		panel.innerHTML =
			'<p class="sask-head">No answer from the model' +
			(failed ? " (" + esc(failed.slice(0, 120)) + ")" : "") +
			'. The closest guides</p><ul class="sask-list" id="settingsAskList" role="listbox">' +
			offered.slice(0, 4).map(settingsRowHtml).join("") +
			"</ul>";
		paintSettingsRows();
		return;
	}
	const go = out.guide ? Guides.get(out.guide) : null;
	panel.innerHTML =
		'<div class="sask-answer" role="status"><p class="sask-q">' +
		esc(q) +
		'</p><p class="sask-a">' +
		esc(out.answer) +
		'</p><div class="sask-from"><span>From</span>' +
		offered
			.slice(0, 3)
			.map(
				(g) =>
					'<button type="button" class="gchip" data-guide="' + esc(g.id) + '">' + esc(g.title) + "</button>",
			)
			.join("") +
		(go
			? '<button type="button" class="sask-go" data-guide="' +
				esc(go.id) +
				'">Take me to ' +
				esc(go.title.replace(/^The /, "the ")) +
				"</button>"
			: "") +
		"</div></div>";
}
