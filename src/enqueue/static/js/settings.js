// ---- settings ------------------------------------------------------------
// Not a destination. This is where you go when something is wrong, so it says where
// every value came from: a field you edit that is silently overridden by an
// environment variable is worse than no field.
// What each setting is called on screen: the words a person uses, not the engine's.
const SETTING_LABELS = {
	llm_model: "For answering questions",
	summarize_model: "For summaries",
	search_model: "For search",
	llm_url: "Address",
	vision_model: "For pictures",
	model_retries: "Times to retry",
	user_agent: "How Enqueue introduces itself to websites",
	hotkey: "Shortcut to capture",
	llm_headers: "Extra headers",
	auto_preview: "Show a preview when you save a link",
	preview_browser: "Try harder on sites that block previews",
	search_lift: "Search by idea, not just words",
	search_model_rank: "Let the assistant rank results",
	trash_days: "Keep deleted things for",
};

// "More options" at the foot of a tab: what most people never need, closed until asked.
function moreOptions(inner) {
	return inner ? '<details class="more"><summary>More options</summary>' + inner + "</details>" : "";
}

// Two spellings of the same binding, kept apart on purpose.
//
// `Alt` is what the shortcut plugin registers; `Option` is what is printed on the
// key. Showing the accelerator to a Mac user asks them to find a key their keyboard
// does not have. Store one, display the other.
const KEY_NAMES = [
	["CommandOrControl", "⌘"],
	["Command", "⌘"],
	["Cmd", "⌘"],
	["Control", "⌃"],
	["Ctrl", "⌃"],
	["Alt", "⌥"],
	["Option", "⌥"],
	["Shift", "⇧"],
];

function keyLabel(accelerator) {
	return String(accelerator || "")
		.split("+")
		.map((part) => {
			const hit = KEY_NAMES.find(
				([name]) => name.toLowerCase() === part.trim().toLowerCase(),
			);
			return hit ? hit[1] : part.trim().toUpperCase();
		})
		.join("");
}

// Recorded, not typed. Nobody knows the accelerator spelling of the key they want,
// and everybody can press it.
let recording = null;

function recordHotkey(button) {
	if (recording) return;
	const label = document.getElementById("hotkeyLabel");
	const previous = label.textContent;
	button.classList.add("listening");
	label.textContent = "press a combination";

	const stop = () => {
		window.removeEventListener("keydown", onKey, true);
		button.classList.remove("listening");
		recording = null;
	};

	const onKey = (e) => {
		e.preventDefault();
		e.stopPropagation();

		if (e.key === "Escape") {
			label.textContent = previous;
			return stop();
		}

		// A bare letter is not a system-wide shortcut, it is the letter T. Wait until at
		// least one modifier is held before accepting anything.
		const held = [];
		if (e.ctrlKey) held.push("Control");
		if (e.altKey) held.push("Alt");
		if (e.shiftKey) held.push("Shift");
		if (e.metaKey) held.push("CommandOrControl");
		if (["Control", "Alt", "Shift", "Meta"].includes(e.key)) return;
		if (!held.length) {
			label.textContent = "hold a modifier too";
			return;
		}

		const key = e.code.startsWith("Key")
			? e.code.slice(3)
			: e.code.startsWith("Digit")
				? e.code.slice(5)
				: e.key.length === 1
					? e.key.toUpperCase()
					: e.key;
		const accelerator = [...held, key].join("+");
		label.textContent = keyLabel(accelerator);
		stop();
		// The shell re-binds the system shortcut live so the change takes effect
		// without a relaunch. Only stage the new value once the rebind succeeded;
		// on a failure the old binding is still active, so the label falls back to
		// it and the error is said out loud (a silent failure here is exactly what
		// hid the missing ACL grant before). A plain browser has no global hotkey
		// and just stages.
		if (bridge) {
			bridge("hotkey_changed", { accelerator })
				.then(() => stageSetting("hotkey", accelerator))
				.catch((err) => {
					label.textContent = previous;
					toast(
						"Could not change the hotkey: " +
							String(err && err.message ? err.message : err),
						true,
					);
				});
		} else {
			stageSetting("hotkey", accelerator);
		}
	};

	recording = onKey;
	window.addEventListener("keydown", onKey, true);
}

// The ids are the old ones (guides, routes and the setup checks name them); the labels
// are what a person calls them.
const SETTINGS_TABS = [
	{ id: "ai", label: "Assistant", render: renderSettingsAI },
	{ id: "features", label: "Capture", render: renderSettingsFeatures },
	{ id: "storage", label: "Library", render: renderSettingsStorage },
	{ id: "sync", label: "Sync", render: renderSettingsSync },
	{ id: "trash", label: "Trash", render: renderSettingsTrash },
	{ id: "events", label: "Activity", render: renderSettingsEvents },
];

// The tab on screen, so Save, Discard, and the key actions can re-render it
// against fresh config without leaving the tabbed surface.
let currentSettingsTab = "ai";

function settingsTabBar() {
	return (
		'<div class="settings-tabs" role="tablist" aria-label="Settings sections">' +
		SETTINGS_TABS.map(
			(t) =>
				'<button role="tab" id="tab-' +
				t.id +
				'" aria-selected="' +
				String(t.id === currentSettingsTab) +
				'" onclick="switchSettingsTab(&#39;' +
				t.id +
				'&#39;)">' +
				esc(t.label) +
				"</button>",
		).join("") +
		"</div>"
	);
}

function markActiveSettingsTab() {
	for (const t of SETTINGS_TABS) {
		const b = document.getElementById("tab-" + t.id);
		if (!b) continue;
		b.classList.toggle("active", t.id === currentSettingsTab);
		b.setAttribute("aria-selected", String(t.id === currentSettingsTab));
	}
}

// Render one tab's form into the shared pane. The previous tab's content stays
// on screen until the new one is ready, so a switch never flashes a loading
// state (DI.1); the stale-render guard drops the result if the user clicked
// away while the fetch was in flight.
async function renderSettingsTab(name) {
	const spec = SETTINGS_TABS.find((t) => t.id === name);
	const pane = document.getElementById("settingsTabPane");
	if (!spec || !pane) return;
	currentSettingsTab = name;
	markActiveSettingsTab();
	const html = await spec.render();
	if (
		currentSettingsTab !== name ||
		!document.getElementById("settingsTabPane")
	)
		return;
	pane.innerHTML = html;
	refreshDirtyBar();
	window.scrollTo(0, 0);
	// The ? marks, and where the installation stands (js/settings_guide.js).
	decorateSettingsGuides();
	refreshSetup();
}

// The tab bar's onclick target: swap only the pane below it.
function switchSettingsTab(name) {
	renderSettingsTab(name);
}

async function showSettings() {
	// Entering settings from the vault locks it, so Diagnostics always re-prompts.
	maybeLockVault();
	teardown();
	// The eye answers about settings here, not about the library (js/settings_guide.js).
	restorePill("settings");
	// Route to settings so a reload/reconnect restores THIS view - without it the hash
	// stayed on whatever was open before (e.g. a saved view `g/<id>`), and every reinit
	// re-ran that route, popping the custom view back over settings.
	setRoute("settings");
	// The same shape as the home page: one centred column, the raven against the title,
	// where things stand in one quiet line under it, and the home page's pill tabs.
	view.innerHTML =
		'<div class="pagecol settings-page">' +
		'<div class="settings-head">' +
		'<div class="settings-title">' +
		'<div class="settings-eye eye" id="settingsEye" aria-hidden="true"></div>' +
		'<h1 class="display">Settings<span class="greet-mark">.</span></h1>' +
		"</div>" +
		'<div id="settingsSetup"></div>' +
		"</div>" +
		'<div class="settings-layout">' +
		settingsTabBar() +
		'<div class="settings-main"><div id="settingsNotes"></div>' +
		'<div id="settingsTabPane"></div></div>' +
		"</div>" +
		"</div>";
	makeEye(document.getElementById("settingsEye"));
	window.scrollTo(0, 0);
	guideOpenId = null;
	watchSettingsPane();
	await renderSettingsTab(currentSettingsTab);
}

// ---- AI tab -------------------------------------------------------------
// One settings field: label + input + helper line. The text-ish settings
// (model, url, retries, vision model, user agent, trash days) render the
// same row shape; only the input attrs and the helper line differ.
function fieldRow(name, label, opts) {
	const f = opts;
	return (
		'<div class="field"><label for="s_' +
		name +
		'">' +
		label +
		"</label>" +
		'<input id="s_' +
		name +
		'"' +
		(f.type ? ' type="' + f.type + '"' : "") +
		(f.min !== undefined ? ' min="' + f.min + '"' : "") +
		(f.max !== undefined ? ' max="' + f.max + '"' : "") +
		(f.placeholder ? ' placeholder="' + esc(f.placeholder) + '"' : "") +
		(f.list ? ' list="' + f.list + '"' : "") +
		' value="' +
		esc(String(f.value ?? "")) +
		'"' +
		(f.locked ? " disabled" : "") +
		" onchange=\"stageSetting('" +
		name +
		"', this.value)\">" +
		(f.locked && f.pinned
			? '<div class="pinned">' + f.pinned + "</div>"
			: f.aside
				? '<div class="aside">' + f.aside + "</div>"
				: "") +
		"</div>"
	);
}

async function renderSettingsAI() {
	const d = await api("/settings");
	let html = '<div class="h2">Assistant</div>';
	const chosen = d.settings.llm_backend;
	const picked = d.backends.find((b) => b.name === chosen.value);

	html +=
		'<div class="shelf">Where answers come from</div><div class="group">' +
		'<div class="aside">Enqueue\'s assistant reads what you save, so you can search by meaning and ask questions.</div>' +
		'<div class="field"><label for="s_backend">Assistant</label>' +
		'<select id="s_backend"' +
		(chosen.locked ? " disabled" : "") +
		' onchange="stageBackend(this.value)">' +
		d.backends
			.map(
				(b) =>
					'<option value="' +
					esc(b.name) +
					'"' +
					(b.name === chosen.value ? " selected" : "") +
					">" +
					esc(b.label) +
					"</option>",
			)
			.join("") +
		"</select>" +
		(picked && !picked.local
			? '<div class="aside caution">Online: when you ask something, the notes it needs are sent to ' +
				esc(picked.label) +
				". Anything you marked as only on this Mac stays here." +
				(picked.needs_key && !picked.key_present ? " <b>Add your account key below.</b>" : "") +
				"</div>"
			: '<div class="aside">On this Mac. Private: nothing leaves your computer.</div>') +
		"</div>";
	if (chosen.value === "custom") {
		const f = d.settings.llm_url;
		html += fieldRow("llm_url", esc(SETTING_LABELS.llm_url), {
			value: f.value,
			locked: f.locked,
			pinned: "set outside Enqueue (" + esc(f.env_var) + ")",
		});
	}
	const keyed = d.storage.api_key_present;
	html +=
		'<div class="field"><label for="s_key">Your key for the online assistant</label>' +
		(d.storage.api_key_editable
			? '<div class="keyrow">' +
				'<input id="s_key" type="password" autocomplete="off" spellcheck="false" ' +
				'placeholder="' +
				(keyed ? "Saved (" + esc(d.storage.api_key_hint || "") + ")" : "Paste your key") +
				'">' +
				'<button class="btn tertiary sm" onclick="saveKey()">Save</button>' +
				(keyed ? '<button class="btn ghost harm sm" onclick="forgetKey()">Remove</button>' : "") +
				"</div>" +
				'<div class="aside">The service gives you one when you sign up. Kept safely on this Mac, never in a file.</div>'
			: '<div class="aside caution">' +
				(d.storage.api_key_where === "environment"
					? "Set outside Enqueue (ENQ_LLM_API_KEY)."
					: "This computer has no Keychain to keep a key in.") +
				"</div>") +
		'<div id="keyState" class="aside caution"></div></div>' +
		"</div>";

	html +=
		'<div class="shelf">Summaries</div><div class="group">' +
		'<div class="aside">A few lines about each thing you save, so search finds it by what it\'s about, not just its words.</div>' +
		'<div class="field"><span class="rowlabel">Summarize everything again</span>' +
		'<button class="btn tertiary" id="rebuildFacetsBtn" onclick="rebuildFacets()">Summarize again</button>' +
		'<div class="aside">Useful after you switch to a better assistant. Runs in the background and can take a while.</div>' +
		'<div id="facetRebuildState" class="aside"></div></div>' +
		"</div>";

	const retries = d.settings.model_retries;
	html += moreOptions(
		modelsGroup(d, picked) +
			'<div class="group">' +
			fieldRow("model_retries", esc(SETTING_LABELS.model_retries), {
				type: "number",
				min: 1,
				max: 10,
				value: retries.value,
				locked: retries.locked,
				pinned: "set outside Enqueue (" + esc(retries.env_var) + ")",
				aside: "How many times to ask again when an answer comes back garbled.",
			}) +
			"</div>",
	);

	html += settingsActionsBar();
	return html;
}

// Rebuild the whole concept layer with the current model (POST /facets redo). The
// engine queues every item on the ingest worker and answers at once; each item is
// re-analyzed, indexed and synced in the background, a rate limit is retried, and a
// restart resumes the rest. Progress shows in the Activity tab as it goes.
async function rebuildFacets() {
	const yes = await ask(
		"Summarize everything again?",
		"The assistant reads everything you saved again. It runs in the background and can take a while.",
		"Summarize again",
	);
	if (!yes) return;
	const btn = document.getElementById("rebuildFacetsBtn");
	const el = document.getElementById("facetRebuildState");
	if (btn) btn.disabled = true;
	if (btn) btn.textContent = "Working...";
	if (el) el.textContent = "Summarizing in the background...";
	api("/facets", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ redo: true }),
	})
		.then((r) => {
			const n = r.queued || 0;
			toast("Summarizing " + n + " item" + (n === 1 ? "" : "s") + " in the background.");
			if (el)
				el.textContent =
					n + " item" + (n === 1 ? " is" : "s are") + " being summarized. Follow along in Activity.";
			if (btn) {
				btn.disabled = false;
				btn.textContent = "Summarize again";
			}
		})
		.catch((err) => {
			if (el) el.textContent = "Did not start: " + String((err && err.message) || err);
			if (btn) {
				btn.disabled = false;
				btn.textContent = "Summarize again";
			}
		});
}

// Settings changed in any settings form but not saved yet. One staging area for
// the whole settings section, because Save commits the form in one PATCH. null
// when nothing is pending. Cleared by Save or Discard, or by navigating away
// from the form (deliberate: uncommitted means uncommitted).
let pendingSettings = null;

function isDirty() {
	return !!pendingSettings && Object.keys(pendingSettings).length > 0;
}

// Staging never re-renders the form: re-rendering would reset a text field and
// lose the very edit that staged it. The control itself already shows the edit in
// place; all that reacts here is the dirty bar.
function refreshDirtyBar() {
	const bar = document.getElementById("settingsActions");
	if (bar) bar.hidden = !isDirty();
}

function stageSetting(name, value) {
	if (!pendingSettings) pendingSettings = {};
	pendingSettings[name] = value;
	refreshDirtyBar();
}

// The preview toggle's look is driven by aria-checked, which a plain click does
// not change, so the click flips it by hand and then stages like any other
// control. The aside beneath it catches up on Save or Discard, when the form
// re-renders against the config.
function stagePreviewToggle(button) {
	const on = button.getAttribute("aria-checked") !== "true";
	button.setAttribute("aria-checked", String(on));
	stageSetting("auto_preview", on ? "on" : "off");
}

function stageSwitch(button, name) {
	const on = button.getAttribute("aria-checked") !== "true";
	button.setAttribute("aria-checked", String(on));
	stageSetting(name, on ? "on" : "off");
}

// One on/off setting row under Features > Search: label, what the current state
// means (or which env var pins it), and the switch.
function searchSwitchRow(s, name, onText, offText) {
	const on = ["on", "true", "1"].includes(String(s.value).toLowerCase());
	return (
		'<div class="field"><div class="togglerow"><div>' +
		'<span class="rowlabel">' +
		esc(SETTING_LABELS[name]) +
		"</span>" +
		(s.locked
			? '<div class="pinned">set outside Enqueue (' + esc(s.env_var) + ")</div>"
			: '<div class="aside">' + (on ? onText : offText) + "</div>") +
		"</div>" +
		'<button class="toggle" role="switch" aria-checked="' +
		String(on) +
		'" aria-label="' +
		esc(SETTING_LABELS[name]) +
		'"' +
		(s.locked ? ' disabled aria-disabled="true"' : "") +
		" onclick=\"stageSwitch(this, '" +
		name +
		"')\"><span class=\"knob\"></span></button>" +
		"</div></div>"
	);
}

// Switching backend moves the model name with it when one is known. The
// endpoint is implied by the backend itself (SET.1), so nothing stages a URL
// here - only `custom` has a user-typed endpoint, edited in its own field.
// One model per job, all on the backend above. Ingestion writes the concepts and
// entities search reads, so a stronger model there pays off in every later search;
// search and chat run per request, so faster is better. Blank ingestion/search
// fall back to the chat model.
const MODEL_ROLES = [
	["llm_model", "Answers your questions and names your chats"],
	[
		"summarize_model",
		"Writes the summaries. A stronger one makes search better; after changing it, " +
			"summarize everything again",
	],
	["search_model", "Decides close calls in search. Fast beats clever here"],
	["vision_model", "Describes photos so search can find them. It has to be one that can look at pictures"],
];

function modelsGroup(d, picked) {
	const known = (picked && picked.chat_models && picked.chat_models.chat_completions) || [];
	const unsupported = (picked && picked.chat_models && picked.chat_models.unsupported_shape) || [];
	const chatModel = (d.settings.llm_model && d.settings.llm_model.value) || "";
	let html = '<div class="shelf">Which AI does each job</div><div class="group">';
	if (known.length)
		html +=
			'<datalist id="modelOptions">' +
			known.map((m) => '<option value="' + esc(m) + '"></option>').join("") +
			"</datalist>";
	for (const [name, job] of MODEL_ROLES) {
		const f = d.settings[name];
		if (!f) continue;
		html += fieldRow(name, esc(SETTING_LABELS[name]), {
			value: f.value,
			locked: f.locked,
			pinned: "set outside Enqueue (" + esc(f.env_var) + ")",
			list: known.length ? "modelOptions" : "",
			placeholder:
				name === "summarize_model" || name === "search_model"
					? "same as chatting" + (chatModel ? " (" + chatModel + ")" : "")
					: "",
			aside: esc(job) + ".",
		});
		// SET2.2b/FIX.3: an OpenCode Go model behind /responses or /messages cannot be
		// reached by the /chat/completions adapter. Warn before a call fails.
		if (unsupported.includes(f.value))
			html +=
				'<div class="aside caution"><b>' +
				esc(f.value) +
				"</b> doesn't work with Enqueue yet. Pick one of: " +
				esc(picked.chat_models.examples) +
				".</div>";
	}
	return html + "</div>";
}

async function stageBackend(name) {
	stageSetting("llm_backend", name);
	if (BACKEND_MODELS[name]) stageSetting("llm_model", BACKEND_MODELS[name]);
}

async function saveSettings() {
	if (!isDirty()) return;
	try {
		await api("/settings", {
			method: "PATCH",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ changes: pendingSettings }),
		});
		pendingSettings = null;
		toast("Settings saved.");
		await renderSettingsTab(currentSettingsTab);
	} catch (err) {
		toast(String(err.message || err), true);
	}
}

function discardSettings() {
	pendingSettings = null;
	renderSettingsTab(currentSettingsTab);
}

// The one Save/Discard bar every editable settings form ends with. Hidden until
// something is staged; refreshDirtyBar shows it.
function settingsActionsBar() {
	return (
		'<div id="settingsActions" class="actions" hidden>' +
		// Q.6: "Changes ready" is an invitation - the work is staged, go
		// ahead and save - not a status report.
		'<span class="aside dirty">You have unsaved changes</span>' +
		'<button class="btn primary" onclick="saveSettings()">Save</button>' +
		'<button class="btn ghost" onclick="discardSettings()">Discard</button>' +
		"</div>"
	);
}

// ---- Features sub-page ---------------------------------------------------
// ---- Features tab --------------------------------------------------------
async function renderSettingsFeatures() {
	const d = await api("/settings");
	let html = '<div class="h2">Capture</div>';

	const hk = d.settings.hotkey;
	html +=
		'<div class="shelf">Capturing</div><div class="group">' +
		'<div class="field"><label for="s_hotkey">' +
		esc(SETTING_LABELS.hotkey) +
		"</label>" +
		'<button class="recorder" id="s_hotkey"' +
		(hk.locked ? " disabled" : "") +
		' onclick="recordHotkey(this)"><span id="hotkeyLabel">' +
		esc(keyLabel(hk.value)) +
		"</span></button>" +
		(hk.locked
			? '<div class="pinned">set outside Enqueue (' + esc(hk.env_var) + ")</div>"
			: '<div class="aside">Opens the capture box from any app. Click, then press the keys you want.</div>') +
		"</div></div>";

	const ap = d.settings.auto_preview;
	const apOn = String(ap.value).toLowerCase() !== "off";
	html +=
		'<div class="shelf">Links</div><div class="group">' +
		'<div class="field"><div class="togglerow"><div>' +
		'<span class="rowlabel">' +
		esc(SETTING_LABELS.auto_preview) +
		"</span>" +
		(ap.locked
			? '<div class="pinned">set outside Enqueue (' + esc(ap.env_var) + ")</div>"
			: '<div class="aside">' +
				(apOn
					? "Enqueue fetches the page's title and picture once, as you save it."
					: "Links stay plain addresses until you open them.") +
				"</div>") +
		"</div>" +
		'<button class="toggle" role="switch" aria-checked="' +
		String(apOn) +
		'" aria-label="' +
		esc(SETTING_LABELS.auto_preview) +
		'"' +
		(ap.locked ? ' disabled aria-disabled="true"' : "") +
		' onclick="stagePreviewToggle(this)"><span class="knob"></span></button>' +
		"</div></div>" +
		// The Mac app ships without the preview browser (pyproject.toml, the `browser`
		// extra), so the switch is offered only where it can work.
		(d.features?.preview_browser === false
			? ""
			: searchSwitchRow(
					d.settings.preview_browser,
					"preview_browser",
					"When a site blocks the preview, Enqueue opens the page once in a hidden browser, the way you would. Slower.",
					"Some sites block previews; those links stay without one.",
				)) +
		"</div>";

	html +=
		'<div class="shelf">Search</div><div class="group">' +
		searchSwitchRow(
			d.settings.search_lift,
			"search_lift",
			"The assistant turns each new search into ideas, so related notes on other topics can match. A moment slower the first time.",
			"Search matches your words and what they mean. Asking the assistant always searches by idea.",
		) +
		searchSwitchRow(
			d.settings.search_model_rank,
			"search_model_rank",
			"The assistant reads the top results and puts the best one first. A moment slower the first time.",
			"Results are ranked by how closely they match.",
		) +
		"</div>";

	const ua = d.settings.user_agent;
	html += moreOptions(
		'<div class="group">' +
			fieldRow("user_agent", esc(SETTING_LABELS.user_agent), {
				value: ua.value,
				locked: ua.locked,
				placeholder: "Enqueue/0.2 (+https://...)",
				aside: "How Enqueue introduces itself when it fetches a preview. Some sites turn away visitors that don't say.",
			}) +
			"</div>",
	);

	html += settingsActionsBar();
	return html;
}

// ---- Storage sub-page ----------------------------------------------------
// ---- Storage tab ----------------------------------------------------------
async function renderSettingsStorage() {
	const d = await api("/settings");
	let html = '<div class="h2">Library</div>';
	// The privacy line must stay true: with a backup folder chosen, a copy does leave.
	const backupOn = !!String((d.settings.backup_dir || {}).value || "").trim();

	const s0 = d.storage;
	html += await renderBackupSection();
	html += await renderDraftsSection(d);
	const items = (s0.counts && s0.counts.artifacts) || 0;
	const chats = (s0.counts && s0.counts.chats) || 0;
	html +=
		'<div class="shelf">On this Mac</div><div class="group">' +
		'<div class="field"><span class="rowlabel">Space used</span>' +
		'<div class="aside">' +
		items +
		" item" +
		(items === 1 ? "" : "s") +
		(chats ? " and " + chats + " chat" + (chats === 1 ? "" : "s") : "") +
		", " +
		bytes(s0.database.bytes + s0.blobs.bytes) +
		"." +
		(backupOn ? " A copy goes to your backup folder." : " Nothing you save leaves this Mac.") +
		"</div></div></div>";
	html += moreOptions(
		'<div class="group">' +
			'<div class="field"><span class="rowlabel">Library folder</span>' +
			'<div class="aside path">' +
			esc(s0.data_dir) +
			"</div></div>" +
			'<div class="field"><span class="rowlabel">Restore a backup</span>' +
			'<div class="aside">Not in the app yet: it takes the Terminal app (quit Enqueue, then ' +
			'run <span class="mono">enq restore</span> with your backup folder). On a new Mac it asks ' +
			"for your recovery kit. Whatever is here now is set aside, never deleted.</div></div>" +
			'<div class="field"><span class="rowlabel">Rebuild search</span>' +
			'<div class="aside">Starts search over from scratch. Takes a while; try it if search keeps missing things you know are there.</div>' +
			'<button class="btn tertiary" onclick="rebuildIndex(this)">Rebuild</button></div>' +
			"</div>",
	);

	return html;
}

// ---- Backup (Storage tab) -------------------------------------------------
// Backups go into a cloud drive's folder - Proton Drive, so the copy is encrypted end
// to end off this Mac. The live library never moves there (backup.py says why); this
// only chooses the folder, shows the last backup, and starts one on demand.
// How many drafts of each note are kept (drafts.py). A choice of three, staged with
// Save like the other settings; "Apply now" thins at once instead of at the next
// daily pass, after saying what it removes.
const DRAFT_POLICIES = [
	["thinned", "Thin them out over time", "Close together while recent, further apart as they age."],
	["30d", "Keep 30 days", "Older drafts are removed, except how each note began."],
	["off", "Don't keep drafts", "Edits replace the text. Each note keeps only its latest."],
];

async function renderDraftsSection(d) {
	let st;
	try {
		st = await api("/drafts");
	} catch (err) {
		return "";
	}
	const f = d.settings.drafts_keep || {};
	const chosen =
		pendingSettings && pendingSettings.drafts_keep !== undefined
			? pendingSettings.drafts_keep
			: f.value || "thinned";
	const help = (DRAFT_POLICIES.find((x) => x[0] === chosen) || DRAFT_POLICIES[0])[2];
	return (
		'<div class="shelf">Drafts</div><div class="group">' +
		'<div class="aside">Earlier versions of your notes, so you can always go back.</div>' +
		'<div class="field"><label for="s_drafts_keep">How long to keep them</label>' +
		'<select id="s_drafts_keep"' +
		(f.locked ? " disabled" : "") +
		' onchange="stageDraftPolicy(this.value)">' +
		DRAFT_POLICIES.map(
			([value, label]) =>
				'<option value="' + value + '"' + (chosen === value ? " selected" : "") + ">" + esc(label) + "</option>",
		).join("") +
		"</select>" +
		'<div class="aside" id="draftsHelp">' +
		esc(help) +
		" " +
		st.drafts +
		" draft" +
		(st.drafts === 1 ? "" : "s") +
		" of " +
		st.notes +
		" note" +
		(st.notes === 1 ? "" : "s") +
		", " +
		esc(bytes(st.bytes)) +
		'. <button class="linkish" onclick="applyDraftPolicy(this)">Tidy up now</button></div>' +
		(f.locked ? '<div class="pinned">set outside Enqueue (' + esc(f.env_var) + ")</div>" : "") +
		"</div></div>"
	);
}

function stageDraftPolicy(value) {
	stageSetting("drafts_keep", value);
}

async function applyDraftPolicy(button) {
	if (isDirty()) return toast("Save your changes first, then apply.", true);
	const yes = await ask(
		"Tidy up drafts now?",
		"Drafts this setting no longer keeps are removed now instead of tonight. This can't be undone.",
		"Tidy up",
	);
	if (!yes) return;
	button.disabled = true;
	try {
		const r = await api("/drafts/thin", { method: "POST" });
		toast(r.removed ? "Removed " + r.removed + " drafts." : "Nothing to remove.");
	} catch (err) {
		toast(String((err && err.message) || err), true);
	}
	renderSettingsTab("storage");
}

// Backup (backup.py): leads with the one fact that matters, when the last copy was
// made, with Back up now beside it. Any folder works: a cloud drive's folder is what
// carries the copy off this Mac (Proton Drive, iCloud Drive, Dropbox), and Enqueue
// only offers a Proton Drive folder it finds as a shortcut. The folder is chosen with
// the Mac's own picker when the window has one, else typed.
async function renderBackupSection() {
	let b;
	try {
		b = await api("/backup");
	} catch (err) {
		return "";
	}
	const proton = (b.detected || [])[0];
	const picker = !!(window.__TAURI__ && window.__TAURI__.core);
	const choose =
		(proton
			? '<button class="btn primary" onclick="useBackupDir(' +
				esc(JSON.stringify(proton)) +
				')">Use Proton Drive</button>'
			: "") +
		(picker
			? '<button class="btn ' +
				(proton ? "tertiary" : "primary") +
				'" onclick="chooseBackupDir()">Choose a folder…</button>'
			: "");
	let html = '<div class="shelf">Backup</div><div class="group backup">';
	if (!b.dir) {
		html +=
			'<div class="backup-status" data-state="none"><span class="backup-dot" aria-hidden="true"></span>' +
			'<div class="backup-words"><div class="backup-head">Not backed up yet</div>' +
			'<div class="backup-sub">Your library lives only on this Mac. Choose a folder your cloud ' +
			"drive keeps, and a copy goes there every day and each time you quit.</div></div>" +
			'<div class="actions backup-actions">' +
			choose +
			"</div></div>" +
			(picker
				? ""
				: '<div class="field"><label for="backup_dir_input">Folder</label>' +
					'<div class="keyrow">' +
					'<input id="backup_dir_input" placeholder="~/Library/CloudStorage/..." ' +
					'onkeydown="if(event.key===\'Enter\')useBackupDir(this.value)">' +
					'<button class="btn tertiary" ' +
					"onclick=\"useBackupDir(document.getElementById('backup_dir_input').value)\">" +
					"Back up there</button></div></div>");
		return html + "</div>";
	}
	const last = b.last && b.last.folder === b.folder ? b.last : null;
	const stale = last && Date.now() - new Date(last.at).getTime() > 3 * 86400000;
	const state = b.running ? "running" : !last ? "none" : stale ? "stale" : "ok";
	const head = b.running ? "Backing up…" : last ? "Backed up " + since(last.at) : "Not backed up yet";
	const sub = b.running
		? "Making a copy. Keep working."
		: last
			? "Every day, and each time you quit."
			: "The first copy is on its way.";
	// What is kept, oldest on the left: the weekly copies paler than the daily ones.
	const kept = (b.backups || []).map((x) => x.file).sort();
	const today = new Date();
	const bars = kept
		.map((file, i) => {
			const m = file.match(/(\d{4}-\d{2}-\d{2})/);
			const age = m ? (today - new Date(m[1] + "T12:00:00")) / 86400000 : 0;
			const cls = i === kept.length - 1 ? "latest" : age > 7 ? "weekly" : "daily";
			return '<i class="' + cls + '" title="' + esc(m ? m[1] : file) + '"></i>';
		})
		.join("");
	// The folder by the name a person knows it by.
	const where = /\/CloudStorage\/ProtonDrive/.test(b.folder)
		? "Proton Drive"
		: /\/Mobile Documents\/com~apple~CloudDocs/.test(b.dir)
			? "iCloud Drive"
			: /\/CloudStorage\/Dropbox/.test(b.folder)
				? "Dropbox"
				: "The folder " + (b.dir.split("/").filter(Boolean).pop() || b.dir);
	html +=
		'<div class="backup-status" data-state="' +
		state +
		'"><span class="backup-dot" aria-hidden="true"></span>' +
		'<div class="backup-words"><div class="backup-head" id="backupStatus">' +
		esc(head) +
		'</div><div class="backup-sub">' +
		esc(sub) +
		"</div></div>" +
		'<button class="btn primary" id="backupNowBtn" onclick="backupNow(this)"' +
		(b.running ? " disabled" : "") +
		">Back up now</button></div>" +
		(b.running ? '<div class="backup-run" aria-hidden="true"><i></i></div>' : "") +
		'<div class="field"><span class="rowlabel">Where copies go</span>' +
		'<div class="aside" title="' +
		esc(b.folder) +
		'">' +
		esc(where) +
		". Locked with your library's key, so nobody else can read them.</div>" +
		(picker ? '<button class="btn tertiary" onclick="chooseBackupDir()">Change</button>' : "") +
		"</div>" +
		'<div class="field"><span class="rowlabel">Copies kept</span>' +
		'<div class="aside">The last 7 days, then one a week for a month.</div>' +
		(kept.length ? '<div class="actions"><div class="backup-bars">' + bars + "</div></div>" : "") +
		"</div>" +
		backupKitHtml(b.kit_saved, b.library_encrypted) +
		'<div class="field"><span class="rowlabel">Turn off backups</span>' +
		'<div class="aside">Stops new copies. The ones already made stay in the folder.</div>' +
		'<button class="btn tertiary" onclick="useBackupDir(\'\')">Turn off</button></div>';
	return html + "</div>";
}

// The recovery kit: the library key written out (libkey.py). Backups are locked with
// it and Enqueue keeps no other copy, so until the person says they saved it the row
// asks, in the warning's colour.
function backupKitHtml(saved, encrypted) {
	return (
		'<div class="field"><span class="rowlabel">Recovery kit</span>' +
		'<div class="aside' +
		(saved ? "" : " caution") +
		'">' +
		(saved
			? "Saved. It's the only way to open your backups on a new Mac. " +
				(encrypted
					? "The library on this Mac is locked with it too."
					: "The library on this Mac gets locked with it the next time Enqueue starts.")
			: "Only it opens your backups on a new Mac, and Enqueue keeps no other copy. " +
				"Save it where you keep your passwords.") +
		'</div><div class="kit-view" id="kitView" hidden></div>' +
		'<button class="btn ' +
		(saved ? "tertiary" : "primary") +
		'" id="kitShowBtn" onclick="showRecoveryKit(this)">' +
		(saved ? "Show again" : "Show recovery kit") +
		"</button></div>"
	);
}

async function showRecoveryKit(btn) {
	const view = document.getElementById("kitView");
	if (!view) return;
	if (!view.hidden) {
		view.hidden = true;
		view.textContent = "";
		btn.textContent = btn.dataset.label || btn.textContent;
		return;
	}
	let r;
	try {
		r = await api("/backup/kit", { method: "POST" });
	} catch (err) {
		return toast(String(err.message || err), true);
	}
	btn.dataset.label = btn.textContent;
	btn.textContent = "Hide";
	view.innerHTML =
		'<div class="kit-code" aria-label="Recovery kit">' +
		r.kit
			.split("-")
			.map((g) => "<span>" + esc(g) + "</span>")
			.join("") +
		'</div><div class="kit-actions">' +
		'<button class="btn tertiary sm" onclick="copyRecoveryKit(this)">Copy</button>' +
		(r.saved ? "" : '<button class="btn primary sm" onclick="recoveryKitSaved()">I saved it</button>') +
		"</div>";
	view.dataset.kit = r.kit;
	view.hidden = false;
}

async function copyRecoveryKit(btn) {
	const view = document.getElementById("kitView");
	try {
		await navigator.clipboard.writeText(view.dataset.kit || "");
	} catch (err) {
		return toast("Could not copy: " + String(err.message || err), true);
	}
	btn.textContent = "Copied";
	toast("Copied. Paste it into your password manager, then copy something else over it.");
}

async function recoveryKitSaved() {
	try {
		await api("/backup/kit/saved", { method: "POST" });
	} catch (err) {
		return toast(String(err.message || err), true);
	}
	await renderSettingsTab("storage");
	toast("Recovery kit saved. The next time Enqueue starts, it encrypts this library on the Mac too.");
}

// The Mac's folder picker (tauri-plugin-dialog). Cancelling picks nothing.
async function chooseBackupDir() {
	let picked = null;
	try {
		picked = await window.__TAURI__.core.invoke("plugin:dialog|open", {
			options: { directory: true, multiple: false, title: "Choose where backups go" },
		});
	} catch (err) {
		return toast("Could not open the folder picker: " + String(err.message || err), true);
	}
	if (typeof picked === "string" && picked) useBackupDir(picked);
}

async function useBackupDir(path) {
	try {
		await api("/settings", {
			method: "PATCH",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ changes: { backup_dir: (path || "").trim() } }),
		});
	} catch (err) {
		return toast(String(err.message || err), true);
	}
	await renderSettingsTab("storage");
	if (path) watchBackup();
}

async function backupNow(button) {
	if (button) {
		button.disabled = true;
		button.textContent = "Backing up...";
	}
	try {
		await api("/backup", { method: "POST" });
	} catch (err) {
		if (button) {
			button.disabled = false;
			button.textContent = "Back up now";
		}
		return toast(String(err.message || err), true);
	}
	watchBackup();
}

// Follow a running backup until it lands, then redraw the tab with its result.
function watchBackup() {
	let tries = 0;
	const tick = async () => {
		tries += 1;
		let b;
		try {
			b = await api("/backup");
		} catch (err) {
			return;
		}
		if (currentSettingsTab !== "storage") return;
		if (b.running && tries < 300) return setTimeout(tick, 1000);
		await renderSettingsTab("storage");
		if (b.last && !b.running) toast("Backed up.");
	};
	setTimeout(tick, 800);
}

// ---- Trash sub-page ------------------------------------------------------
// ---- Trash tab ------------------------------------------------------------
// DI.6: the retention setting and the count stay on the tab; the item list
// lives behind a disclosure so the tab reads as a setting, not a browser.
async function renderSettingsTrash() {
	const [d, trash] = await Promise.all([
		api("/settings"),
		api("/trash").catch(() => ({ items: [], retention_days: 30 })),
	]);
	let html = '<div class="h2">Trash</div>';

	const td = d.settings.trash_days;
	html +=
		'<div class="shelf">Trash</div><div class="group">' +
		fieldRow("trash_days", esc(SETTING_LABELS.trash_days), {
			type: "number",
			min: 1,
			max: 3650,
			value: td.value,
			locked: td.locked,
			pinned: "set outside Enqueue (" + esc(td.env_var) + ")",
			aside: "Days. After that, deleted things are gone for good. Nothing else is ever removed.",
		}) +
		"</div>";
	html += '<div class="shelf">In the trash</div><div class="group">';
	if (!trash.items.length) {
		html += '<div class="aside">Nothing in the trash.</div>';
	} else {
		html +=
			'<div class="callout warn">Emptying the trash deletes these for good.</div>' +
			'<div class="actions"><button class="btn danger terminal" onclick="emptyTrash(' +
			trash.items.length +
			')">Empty trash (' +
			trash.items.length +
			")</button></div>" +
			'<details class="disclosure"><summary>View deleted items (' +
			trash.items.length +
			')</summary><div class="disclosure-body">' +
			trash.items.map((a) => trashRow(a)).join("") +
			"</div></div></details>";
	}

	html += settingsActionsBar();
	return html;
}

// ---- Sync tab ------------------------------------------------------------
// The Sync tab branches on configuration state:
// - Not configured: Enqueue sync first (the library's key, shown once if it is new,
//   then sign in with Google or Apple in the browser: account.py), and under it the
//   walk for a relay of your own (relay URL -> keyring init -> the relay's password).
// - Configured: who is signed in and the account's devices (Enqueue sync only), the
//   Signal-style linking QR (QR.3), and adding another computer.
async function renderSettingsSync() {
	const d = await api("/settings");
	const sync = d.sync || {};
	let html = '<div class="h2">Sync</div>';

	if (window.syncSetupStep === "signin") {
		// Waiting on the browser, for a first setup and for a switch alike.
		html += '<div class="shelf">Sign in to Enqueue sync</div><div class="group">' + renderSignInWaiting() + "</div>";
	} else if (!sync.relay_configured) {
		html += renderSyncSetup(d, sync);
	} else {
		html += renderSyncConfigured(sync);
	}

	html += settingsActionsBar();
	return html;
}

// The current step of the setup walk, held on window so a re-render of the tab
// keeps the walk position. 1 = relay URL, 2 = recovery (keyring init), 3 = secret.
function renderSyncSetup(_d, sync) {
	const step = window.syncSetupStep || 1;

	// Mid-walk steps own the whole tab so the user is not distracted mid-flow.
	if (step === "join") {
		return '<div class="shelf">Join a library</div><div class="group">' + renderSyncJoin(sync) + "</div>";
	}
	if (step === "recovery") {
		return '<div class="shelf">Use Enqueue on your phone</div><div class="group">' + renderSyncRecovery() + "</div>";
	}
	if (step === 3) {
		return '<div class="shelf">Use Enqueue on your phone</div><div class="group">' + renderSyncStepSecret(sync) + "</div>";
	}
	if (step === "signin") {
		return '<div class="shelf">Sign in to Enqueue sync</div><div class="group">' + renderSignInWaiting() + "</div>";
	}

	// The landing (step 1) offers two first-class choices as separate sections: start a
	// NEW library here, or JOIN one already set up on another device. Joining used to be a
	// buried aside link under the relay field; a second device is a common path and earns
	// its own section.
	return (
		'<div class="shelf">Use Enqueue on your phone</div><div class="group">' +
		renderSyncHosted() +
		"</div>" +
		'<div class="shelf">Already using Enqueue on another computer?</div>' +
		'<div class="group">' +
		'<div class="field"><span class="rowlabel">Join that library</span>' +
		'<div class="aside">This computer gets the same library instead of starting a new one.</div>' +
		'<button class="btn tertiary" onclick="startSyncJoin(event)">Join</button>' +
		"</div></div>" +
		'<details class="more"><summary>Use your own sync server instead</summary>' +
		'<div class="group">' +
		renderSyncStepRelay(sync) +
		"</div></details>"
	);
}

// Enqueue sync: sign in, and the relay is ours to run. What it holds is scrambled with a
// key that never leaves your devices, which is the promise this row has to make plainly.
function renderSyncHosted() {
	return (
		'<div class="aside">Keep your phone and this Mac in step. Everything is scrambled ' +
		"before it leaves your devices, so not even we can read it.</div>" +
		'<div class="field"><span class="rowlabel">Enqueue sync</span>' +
		'<div class="aside">Sign in to turn it on. Signing in only tells us who you are.</div>' +
		signInButtons("startAccountSignIn") +
		"</div>"
	);
}

// The providers' own marks, as each asks: Google's four-colour G on a light button,
// never recoloured; Apple's logo in the text colour. Both buttons look alike so neither
// reads as the "right" one.
const GOOGLE_G =
	'<svg class="signin-mark" viewBox="0 0 18 18" aria-hidden="true">' +
	'<path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.91c1.7-1.57 2.69-3.88 2.69-6.62z"/>' +
	'<path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.91-2.26c-.81.54-1.84.86-3.05.86-2.34 0-4.33-1.58-5.04-3.71H.96v2.33A9 9 0 0 0 9 18z"/>' +
	'<path fill="#FBBC05" d="M3.96 10.71A5.41 5.41 0 0 1 3.68 9c0-.59.1-1.17.28-1.71V4.96H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.04l3-2.33z"/>' +
	'<path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58A9 9 0 0 0 .96 4.96l3 2.33C4.67 5.16 6.66 3.58 9 3.58z"/>' +
	"</svg>";
const APPLE_MARK =
	'<svg class="signin-mark" viewBox="0 0 814 1000" aria-hidden="true"><path fill="currentColor" d="M788.1 340.9c-5.8 4.5-108.2 62.2-108.2 190.5 0 148.4 130.3 200.9 134.2 202.2-.6 3.2-20.7 71.9-68.7 141.9-42.8 61.6-87.5 123.1-155.5 123.1s-85.5-39.5-164-39.5c-76.5 0-103.7 40.8-165.9 40.8s-105.6-57-155.5-127C46.7 790.7 0 663 0 541.8c0-194.4 126.4-297.5 250.8-297.5 66.1 0 121.2 43.4 162.7 43.4 39.5 0 101.1-46 176.3-46 28.5 0 130.9 2.6 198.3 99.2zm-234-181.5c31.1-36.9 53.1-88.1 53.1-139.3 0-7.1-.6-14.3-1.9-20.1-50.6 1.9-110.8 33.7-147.1 75.8-28.5 32.4-55.1 83.6-55.1 135.5 0 7.8 1.3 15.6 1.9 18.1 3.2.6 8.4 1.3 13.6 1.3 45.4 0 102.5-30.4 135.5-71.3z"/></svg>';

function signInButtons(handler) {
	return (
		'<div class="actions signin">' +
		'<button class="btn signin-btn" onclick="' +
		handler +
		"('google')\">" +
		GOOGLE_G +
		"Sign in with Google</button>" +
		'<button class="btn signin-btn" onclick="' +
		handler +
		"('apple')\">" +
		APPLE_MARK +
		"Sign in with Apple</button>" +
		"</div>"
	);
}

function renderSignInWaiting() {
	return (
		'<div class="field"><span class="rowlabel">Finish in your browser</span>' +
		'<div class="aside">A sign-in page opened in your browser. Sign in there, and this ' +
		"page moves on by itself.</div>" +
		'<div class="actions">' +
		'<button class="btn tertiary" onclick="reopenSignIn()">Open it again</button>' +
		'<button class="btn ghost" onclick="cancelSignIn()">Cancel</button>' +
		"</div></div>"
	);
}

function openOutside(url) {
	return bridge ? bridge("open_external", { url }) : window.open(url, "_blank", "noopener");
}

// The library's key comes first (made here, and its recovery phrase shown once, when
// this Mac has none yet); then the browser sign-in, which the engine finishes.
async function startAccountSignIn(provider) {
	const d = await api("/settings");
	const sync = d.sync || {};
	if (!sync.keyring_initialized) {
		window.syncAfterRecovery = provider;
		await initKeyringAndShowRecovery();
		return;
	}
	await beginSignIn(provider);
}

async function beginSignIn(provider, refresh = false) {
	let res;
	try {
		res = await api("/account/sign-in", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ provider, refresh }),
		});
	} catch (err) {
		toast(String(err.message || err), true);
		return;
	}
	window.accountSignInUrl = res.url;
	window.accountSignInRefresh = refresh;
	window.syncSetupStep = "signin";
	await renderSettingsTab("sync");
	try {
		await openOutside(res.url);
	} catch (err) {
		toast(String(err.message || err), true);
	}
	pollSignIn();
}

function reopenSignIn() {
	if (window.accountSignInUrl) openOutside(window.accountSignInUrl);
}

function cancelSignIn() {
	window.syncSetupStep = null;
	window.accountSignInUrl = null;
	renderSettingsTab("sync");
}

// The browser comes back to the engine, not to this page: watch the engine until the
// sign-in lands or fails. Ten minutes, the same as the engine keeps a sign-in open.
async function pollSignIn() {
	const until = Date.now() + 10 * 60 * 1000;
	while (window.syncSetupStep === "signin" && Date.now() < until) {
		await new Promise((done) => setTimeout(done, 1500));
		let me;
		try {
			me = await api("/account");
		} catch {
			continue;
		}
		const progress = me.sign_in || {};
		if (progress.state === "done" && me.signed_in) {
			window.syncSetupStep = null;
			window.accountSignInUrl = null;
			pendingSettings = null;
			toast(
				window.accountSignInRefresh
					? me.picture
						? "Your picture is in."
						: "Signed in again. Google didn't send a picture for this account."
					: me.relink_phone
						? "Moved to Enqueue sync. Link your phone again with the new code."
						: "Signed in. Enqueue sync is on.",
			);
			window.accountSignInRefresh = false;
			await renderSettingsTab("sync");
			return;
		}
		if (progress.state === "failed") {
			window.syncSetupStep = null;
			window.accountSignInUrl = null;
			toast(progress.error || "Sign-in did not finish.", true);
			await renderSettingsTab("sync");
			return;
		}
	}
}

function renderSyncStepRelay(sync) {
	const relayValue = esc(sync.relay_url || "http://127.0.0.1:8788");
	return (
		'<div class="aside">Your phone and this Mac stay in step through a relay: a small ' +
		"server that passes your library between them. It only ever holds scrambled copies, " +
		"so it can't read anything.</div>" +
		'<div class="field">' +
		'<label for="s_sync_relay_url">Relay address</label>' +
		'<input id="s_sync_relay_url" type="url" value="' +
		relayValue +
		'" placeholder="https://...">' +
		'<div class="aside">The address of your relay. Your phone has to be able to reach it, ' +
		"so it should start with https://.</div>" +
		"</div>" +
		'<div class="actions" style="margin-top: var(--sp-4);">' +
		'<button class="btn primary" onclick="advanceSyncSetupAndInit()">Continue</button>' +
		"</div>"
	);
}

// The second-device path: instead of minting a new keyring (a new DEK that could not
// read the first device's data), point at the same relay, pull its encrypted keyring,
// and import the shared DEK with the recovery phrase from the first device.
function startSyncJoin(e) {
	if (e) e.preventDefault();
	window.syncSetupStep = "join";
	renderSettingsTab(currentSettingsTab);
}

function renderSyncJoin(sync) {
	const relayValue = esc(sync.relay_url || "http://127.0.0.1:8788");
	return (
		'<div class="aside">On the other computer, open <strong>Settings, Sync, Add another ' +
		"computer</strong>. It shows a one-time code and phrase; type them here.</div>" +
		'<div class="field" style="margin-top: var(--sp-4);">' +
		'<label for="s_pair_relay">Relay address</label>' +
		'<input id="s_pair_relay" type="url" value="' +
		relayValue +
		'" placeholder="http://127.0.0.1:8788">' +
		"</div>" +
		'<div class="field">' +
		'<label for="s_pair_id">Pairing code</label>' +
		'<input id="s_pair_id" type="text" autocomplete="off" spellcheck="false" ' +
		'placeholder="The code shown on the other device">' +
		"</div>" +
		'<div class="field">' +
		'<label for="s_pair_phrase">Pairing phrase</label>' +
		'<input id="s_pair_phrase" type="text" autocomplete="off" spellcheck="false" ' +
		'placeholder="The phrase shown on the other device">' +
		"</div>" +
		'<div class="actions" style="margin-top: var(--sp-4);">' +
		'<button class="btn primary" onclick="claimPairing()">Pair this device</button>' +
		'<button class="btn ghost" onclick="backSyncSetup(1)">Back</button>' +
		"</div>" +
		// Fallback: the original recovery-phrase join, for libraries set up before pairing
		// existed whose owner still has the recovery phrase.
		'<details class="disclosure" style="margin-top: var(--sp-5);">' +
		"<summary>Join with a recovery phrase instead</summary><div class=\"disclosure-body\">" +
		'<div class="aside">For a library set up before codes existed: the relay address, its ' +
		"password, and the recovery phrase from the first computer.</div>" +
		'<div class="field" style="margin-top: var(--sp-4);"><label for="s_join_relay">Relay address</label>' +
		'<input id="s_join_relay" type="url" value="' +
		relayValue +
		'" placeholder="http://127.0.0.1:8788"></div>' +
		'<div class="field"><label for="s_join_secret">Relay password</label>' +
		'<input id="s_join_secret" type="password" autocomplete="off" placeholder="The secret from the other device"></div>' +
		'<div class="field"><label for="s_join_recovery">Recovery phrase</label>' +
		'<input id="s_join_recovery" type="text" autocomplete="off" spellcheck="false" placeholder="The recovery phrase from the first device"></div>' +
		'<div class="actions" style="margin-top: var(--sp-4);"><button class="btn" onclick="joinExistingLibrary()">Join with recovery phrase</button></div>' +
		"</div></details>"
	);
}

// The joining device claims a one-time pairing offer: relay + pairing code + phrase. The
// engine fetches the sealed envelope, opens it with the phrase, imports the key, and pulls.
async function claimPairing() {
	const relay = (document.getElementById("s_pair_relay") || {}).value || "";
	const id = (document.getElementById("s_pair_id") || {}).value || "";
	const phrase = (document.getElementById("s_pair_phrase") || {}).value || "";
	if (!relay.trim() || !id.trim() || !phrase.trim()) {
		toast("Relay, pairing code, and phrase are all required to pair", true);
		return;
	}
	const btn = event && event.target ? event.target : null;
	if (btn) {
		btn.disabled = true;
		btn.textContent = "Pairing...";
	}
	try {
		await api("/settings/sync/pair/claim", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				relay_url: relay.trim(),
				pairing_id: id.trim(),
				phrase: phrase.trim(),
			}),
		});
	} catch (err) {
		if (btn) {
			btn.disabled = false;
			btn.textContent = "Pair this device";
		}
		toast(String((err && err.message) || err), true);
		return;
	}
	window.syncSetupStep = null;
	pendingSettings = null;
	toast("Paired. Pulling the library down in the background...");
	renderSettingsTab(currentSettingsTab);
}

async function joinExistingLibrary() {
	const relay = (document.getElementById("s_join_relay") || {}).value || "";
	const secret = (document.getElementById("s_join_secret") || {}).value || "";
	const phrase = (document.getElementById("s_join_recovery") || {}).value || "";
	if (!relay.trim() || !secret.trim() || !phrase.trim()) {
		toast("Relay, secret, and recovery phrase are all required to join", true);
		return;
	}
	const btn = event && event.target ? event.target : null;
	if (btn) {
		btn.disabled = true;
		btn.textContent = "Joining...";
	}
	try {
		await api("/settings/sync/join", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				relay_url: relay.trim(),
				secret: secret.trim(),
				recovery_phrase: phrase.trim(),
			}),
		});
	} catch (err) {
		if (btn) {
			btn.disabled = false;
			btn.textContent = "Join library";
		}
		toast(String((err && err.message) || err), true);
		return;
	}
	window.syncSetupStep = null;
	pendingSettings = null;
	toast("Joined. Pulling the library down in the background...");
	renderSettingsTab(currentSettingsTab);
}

async function advanceSyncSetupAndInit() {
	const relayUrl = (document.getElementById("s_sync_relay_url") || {}).value;
	if (!relayUrl || !relayUrl.trim()) {
		toast("Please enter a relay URL", true);
		return;
	}
	window.syncRelayUrl = relayUrl.trim();

	const d = await api("/settings");
	const sync = d.sync || {};

	// A legacy (pre-QR.1 two-slot) keyring cannot be carried forward: the new
	// format drops the password slot, so it is re-initialized in place with a
	// fresh key and recovery phrase, behind a destructive confirmation.
	if (sync.keyring_initialized && sync.keyring_legacy) {
		const yes = await ask(
			"Re-initialize sync keyring?",
			"Your sync keyring is from an older pre-release version. It will be " +
				"re-initialized with a fresh encryption key and a new recovery phrase. " +
				"Anything already synced with the old key can no longer be decrypted " +
				"on this device. This cannot be undone.",
			"Re-initialize",
		);
		if (!yes) {
			window.syncSetupStep = 1;
			renderSettingsTab(currentSettingsTab);
			return;
		}
		await initKeyringAndShowRecovery();
		return;
	}

	// Already initialized and current-format (re-pairing this desktop): skip
	// straight to the secret step. Never re-initialize - that would orphan the
	// current DEK.
	if (sync.keyring_initialized) {
		window.syncSetupStep = 3;
		renderSettingsTab(currentSettingsTab);
		return;
	}

	// Fresh library: initialize the keyring (no password) and show the recovery
	// phrase once.
	await initKeyringAndShowRecovery();
}

async function initKeyringAndShowRecovery() {
	const btn = event && event.target ? event.target : null;
	if (btn) {
		btn.disabled = true;
		btn.textContent = "Initializing...";
	}
	try {
		const res = await api("/settings/keyring-init", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({}),
		});
		// The phrase is shown exactly once, in memory only, and cleared on confirm.
		window.syncRecoveryPhrase = res.recovery_phrase;
		window.syncSetupStep = "recovery";
		renderSettingsTab(currentSettingsTab);
	} catch (err) {
		toast(String(err.message || err), true);
		if (btn) {
			btn.disabled = false;
			btn.textContent = "Initialize and show recovery phrase";
		}
	}
}

function renderSyncRecovery() {
	const phrase = window.syncRecoveryPhrase;
	if (!phrase) {
		// No phrase available - go back to relay step.
		window.syncSetupStep = 1;
		return renderSyncStepRelay({});
	}
	return (
		'<div class="callout warn">' +
		"<b>Write this down. This is the only time you will see it.</b> " +
		"This recovery phrase is the only way to recover your library if you " +
		"lose access to this device. Store it somewhere safe. It will never be shown " +
		"again.</div>" +
		'<div class="field" style="margin-top: var(--sp-4);">' +
		"<label>Recovery phrase</label>" +
		'<div class="mono chip" style="font-size: 14px; letter-spacing: 2px; word-break: break-all;">' +
		esc(phrase) +
		"</div>" +
		"</div>" +
		'<div class="field">' +
		'<label><input type="checkbox" id="s_recovery_confirmed"> ' +
		"I have written down the recovery phrase and stored it safely</label>" +
		"</div>" +
		'<div class="actions" style="margin-top: var(--sp-4);">' +
		'<button class="btn primary" onclick="confirmRecoveryAndAdvance()">I have saved it - continue</button>' +
		"</div>"
	);
}

function renderSyncStepSecret(_sync) {
	return (
		'<div class="aside">Last step: the relay\'s password, so only your devices can use it. ' +
		"Paste the one the relay runs with: your own relay's RELAY_SECRET, or the password " +
		"whoever runs a shared relay gave you.</div>" +
		'<div class="field">' +
		'<label for="s_sync_secret">Relay password</label>' +
		'<input id="s_sync_secret" type="password" autocomplete="off" ' +
		'placeholder="Paste the relay password">' +
		'<div class="aside">Kept in your Mac\'s Keychain.</div>' +
		"</div>" +
		'<div class="actions" style="margin-top: var(--sp-4);">' +
		'<button class="btn primary" onclick="saveSyncSecretAndFinish()">Finish setup</button>' +
		'<button class="btn ghost" onclick="backSyncSetup(2)">Back</button>' +
		"</div>"
	);
}

function backSyncSetup(step) {
	window.syncSetupStep = step;
	renderSettingsTab(currentSettingsTab);
}

function confirmRecoveryAndAdvance() {
	const confirmed = document.getElementById("s_recovery_confirmed").checked;
	if (!confirmed) {
		toast("Please confirm you have saved the recovery phrase", true);
		return;
	}
	window.syncRecoveryPhrase = null;
	const provider = window.syncAfterRecovery;
	if (provider) {
		window.syncAfterRecovery = null;
		beginSignIn(provider);
		return;
	}
	window.syncSetupStep = 3;
	renderSettingsTab(currentSettingsTab);
}

async function saveSyncSecretAndFinish() {
	const relayUrl = window.syncRelayUrl || "http://127.0.0.1:8788";
	const secretField = document.getElementById("s_sync_secret");
	const secret = secretField ? secretField.value.trim() : "";
	if (!secret) {
		toast("Paste the relay's password first.", true);
		secretField?.focus();
		return;
	}
	const btn = event.target;
	btn.disabled = true;
	btn.textContent = "Saving...";
	try {
		const finalSecret = secret;
		// PUT /settings/sync-secret also pushes the keyring to the relay.
		await api("/settings/sync-secret", {
			method: "PUT",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ secret: finalSecret, relay_url: relayUrl }),
		});
		// Persist the relay URL as a plaintext setting.
		await api("/settings", {
			method: "PATCH",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ changes: { sync_relay_url: relayUrl } }),
		});
		window.syncSetupStep = null;
		window.syncRelayUrl = null;
		pendingSettings = null;
		toast("Sync configured");
		await renderSettingsTab("sync");
	} catch (err) {
		toast(String(err.message || err), true);
		btn.disabled = false;
		btn.textContent = "Finish setup";
	}
}

function renderSyncConfigured(sync) {
	const acct = sync.account || {};
	let html = "";
	if (acct.signed_in) html += renderAccountSection(acct);
	else html += renderSyncSwitch();
	html += '<div class="shelf">Link your phone</div><div class="group">';
	if (acct.relink_phone) {
		html +=
			'<div class="callout warn">Link your phone again: show the code below and scan it. ' +
			"Until you do, changes on this Mac don't reach it.</div>";
	}
	html +=
		'<div class="field"><span class="rowlabel">Your code</span>' +
		'<div class="aside">Open Enqueue on your phone and tap <b>Scan QR</b> (on a phone ' +
		"that's already set up: Settings, <b>Re-link with QR</b>). Then point the camera at " +
		"the code.</div>" +
		'<button class="btn primary" id="linkShowBtn" aria-expanded="false" ' +
		'aria-controls="linkQRArea" onclick="toggleLinkCode()">Show the code</button>' +
		"</div>" +
		'<div class="link-qr" id="linkQRArea" hidden>' +
		'<div class="link-qr-code" id="linkQR"></div>' +
		'<p class="link-qr-note">This code opens your library. Keep it to yourself: no ' +
		"screenshots, no sharing. It disappears when you leave this page.</p>" +
		"</div>" +
		"</div>";

	// Pair another COMPUTER (the phone uses the QR above). This mints a one-time code +
	// phrase; you type them into the new computer's "Join Existing Library" screen.
	html +=
		'<div class="shelf">Add another computer</div><div class="group">' +
		'<div class="field"><span class="rowlabel">One-time code</span>' +
		'<div class="aside">Type it into Enqueue on the other computer (Settings, Sync, Join). ' +
		"It works once and expires in 10 minutes.</div>" +
		'<button class="btn tertiary" id="pairOfferBtn" onclick="createPairingOffer()">Make a code</button>' +
		"</div>" +
		'<div id="pairOfferArea" hidden style="margin-top: var(--sp-4);"></div>' +
		"</div>";

	html += moreOptions(
		(acct.signed_in
			? '<div class="shelf">Your Enqueue sync account</div><div class="group">' +
				'<div class="field"><span class="rowlabel">Delete the account</span>' +
				'<div class="aside caution">Every phone and computer stops syncing, and the copy ' +
				"on Enqueue sync is deleted. Your library stays on this Mac and your phone.</div>" +
				'<button class="btn harm" onclick="confirmDeleteAccount()">Delete account</button>' +
				"</div></div>"
			: "") +
			'<div class="shelf">Start sync over</div><div class="group">' +
			'<div class="field"><span class="rowlabel">Start over with a new key</span>' +
			'<div class="aside caution">Throws away the key your devices share. Anything already ' +
			"sent can't be read again. Only for starting fresh.</div>" +
			'<button class="btn harm" onclick="confirmResetSync()">Start over</button>' +
			"</div></div>",
	);

	return html;
}

const PROVIDER_NAMES = { google: "Google", apple: "Apple" };

// A Mac on a relay of its own moves to Enqueue sync with the same sign-in: the library
// goes up whole under the same key (account.py `_move_library`), nothing to write down.
function renderSyncSwitch() {
	return (
		'<div class="shelf">Enqueue sync</div><div class="group">' +
		'<div class="field"><span class="rowlabel">Switch to Enqueue sync</span>' +
		'<div class="aside">Sign in and your library moves to our sync service, still locked ' +
		"with your key. Then link your phone again. Your own server keeps its copy until " +
		"you remove it.</div>" +
		signInButtons("beginSignIn") +
		"</div></div>"
	);
}

function accountAvatar(acct) {
	if (acct.picture) {
		return '<img class="account-avatar" src="/account/picture?t=' + Date.now() + '" alt="">';
	}
	const letter = (acct.name || acct.email || "?").trim().charAt(0).toUpperCase();
	// Google sends the picture only inside a sign-in: with none kept yet, the initial
	// is the way to fetch it (the same sign-in, renewing the session, nothing else).
	if (acct.provider === "google") {
		return (
			'<button class="account-avatar initial" type="button" ' +
			'title="Show your Google picture" aria-label="Show your Google picture" ' +
			"onclick=\"beginSignIn('google', true)\">" +
			esc(letter) +
			"</button>"
		);
	}
	return '<span class="account-avatar initial" aria-hidden="true">' + esc(letter) + "</span>";
}

function renderAccountSection(acct) {
	const how = PROVIDER_NAMES[acct.provider] || "";
	const name = acct.name && acct.name !== acct.email ? acct.name : "";
	setTimeout(loadAccountDevices, 0);
	return (
		'<div class="shelf">Enqueue sync</div><div class="group">' +
		'<div class="field account-row">' +
		'<div class="account-who" id="accountWho">' +
		accountAvatar(acct) +
		'<div class="account-words">' +
		'<span class="rowlabel">' +
		esc(name || acct.email || "Signed in") +
		"</span>" +
		'<div class="aside">' +
		(name && acct.email ? esc(acct.email) + " · " : "") +
		(how ? "Signed in with " + esc(how) : "Signed in") +
		"</div></div></div>" +
		'<button class="btn tertiary" onclick="confirmSignOut()">Sign out</button>' +
		"</div></div>" +
		'<div class="shelf">Devices</div>' +
		'<div class="group" id="accountDevices"><div class="aside">Loading...</div></div>'
	);
}

function deviceWhen(seconds) {
	if (!seconds) return "";
	return new Date(seconds * 1000).toLocaleDateString(undefined, {
		month: "short",
		day: "numeric",
		year: "numeric",
	});
}

async function loadAccountDevices() {
	const box = document.getElementById("accountDevices");
	if (!box) return;
	let res;
	try {
		res = await api("/account/devices");
	} catch (err) {
		box.innerHTML = '<div class="aside">' + esc(String(err.message || err)) + "</div>";
		return;
	}
	const devices = res.devices || [];
	// Asking the account for its devices also fetches its picture the first time.
	const avatar = document.querySelector("#accountWho .account-avatar.initial");
	if (avatar) {
		api("/account")
			.then((me) => {
				if (me.picture) avatar.outerHTML = accountAvatar(me);
			})
			.catch(() => {});
	}
	box.innerHTML =
		'<div class="aside">Every phone and computer syncing with this account. Remove one ' +
		"you no longer use and it stops syncing at once.</div>" +
		devices
			.map((dv) => {
				const seen = dv.last_seen_at ? "last synced " + deviceWhen(dv.last_seen_at) : "not synced yet";
				return (
					'<div class="field"><span class="rowlabel">' +
					esc(dv.name) +
					(dv.this_mac ? " (this Mac)" : "") +
					"</span>" +
					'<div class="aside">Added ' +
					esc(deviceWhen(dv.created_at)) +
					", " +
					esc(seen) +
					"</div>" +
					(dv.this_mac
						? ""
						: '<button class="btn ghost" onclick="removeAccountDevice(\'' +
							esc(dv.id) +
							"', '" +
							esc(dv.name) +
							'\')">Remove</button>') +
					"</div>"
				);
			})
			.join("");
}

async function removeAccountDevice(id, name) {
	const yes = await ask(
		"Remove " + name + "?",
		"It stops syncing right away. What it already has stays on it. To use it again, link it again.",
		"Remove",
	);
	if (!yes) return;
	try {
		await api("/account/devices/" + encodeURIComponent(id), { method: "DELETE" });
	} catch (err) {
		toast(String(err.message || err), true);
		return;
	}
	toast(name + " removed.");
	loadAccountDevices();
}

async function confirmSignOut() {
	const yes = await ask(
		"Sign out of Enqueue sync?",
		"This Mac stops syncing. Your library stays here, and your phone keeps what it has.",
		"Sign out",
	);
	if (!yes) return;
	await api("/account/sign-out", { method: "POST" });
	pendingSettings = null;
	toast("Signed out. This Mac no longer syncs.");
	await renderSettingsTab("sync");
}

async function confirmDeleteAccount() {
	const yes = await ask(
		"Delete your Enqueue sync account?",
		"Every phone and computer stops syncing at once, and the copy on Enqueue sync is " +
			"deleted. Your library stays on this Mac and on your phone. This can't be undone.",
		"Delete account",
	);
	if (!yes) return;
	try {
		await api("/account", { method: "DELETE" });
	} catch (err) {
		toast(String(err.message || err), true);
		return;
	}
	pendingSettings = null;
	toast("Your Enqueue sync account is deleted.");
	await renderSettingsTab("sync");
}

// Main device: mint a one-time pairing offer and show the code + phrase to type into the
// new computer. The DEK never appears here - the engine seals it to the relay under the
// phrase; only the locator (code) and the phrase are shown.
async function createPairingOffer() {
	const btn = document.getElementById("pairOfferBtn");
	const area = document.getElementById("pairOfferArea");
	if (btn) {
		btn.disabled = true;
		btn.textContent = "Generating...";
	}
	let res;
	try {
		res = await api("/settings/sync/pair/offer", { method: "POST" });
	} catch (err) {
		if (btn) {
			btn.disabled = false;
			btn.textContent = "Make a code";
		}
		toast(String((err && err.message) || err), true);
		return;
	}
	const mins = Math.round((res.expires_in || 600) / 60);
	area.innerHTML =
		'<div class="aside">On the other computer, open Settings, Sync, Join, and enter the ' +
		"relay address, this code and this phrase. It needs both, they work once, and they " +
		"expire in " +
		mins +
		" minutes. Do not share them.</div>" +
		'<div class="field" style="margin-top: var(--sp-4);"><label>Relay URL</label>' +
		'<input type="text" readonly value="' +
		esc(res.relay_url || "") +
		'" onclick="this.select()"></div>' +
		'<div class="field"><label>Pairing code</label>' +
		'<input type="text" readonly value="' +
		esc(res.pairing_id || "") +
		'" onclick="this.select()"></div>' +
		'<div class="field"><label>Pairing phrase</label>' +
		'<input type="text" readonly value="' +
		esc(res.phrase || "") +
		'" onclick="this.select()"></div>';
	area.hidden = false;
	if (btn) {
		btn.disabled = false;
		btn.textContent = "Make another code";
	}
}

function toggleLinkCode() {
	const area = document.getElementById("linkQRArea");
	if (area && !area.hidden) hideLinkCode();
	else showLinkCode();
}

async function showLinkCode() {
	const btn = document.getElementById("linkShowBtn");
	const area = document.getElementById("linkQRArea");
	const qr = document.getElementById("linkQR");
	btn.disabled = true;
	btn.textContent = "Making the code...";
	try {
		// QR.3: the command returns ONLY the rendered SVG - there is deliberately no
		// textual form of the payload anywhere (camera-scanning is the only transport).
		// desktop_link_code returns the rendered SVG string directly (no JSON wrapper).
		const response = await bridge("desktop_link_code", {});
		const svg = String(response || "");
		// Parse and inject as a real SVG element via DOMParser - never innerHTML,
		// and never raw content: a non-SVG or malformed document is rejected.
		const parsed = new DOMParser().parseFromString(svg, "image/svg+xml");
		const node = parsed.documentElement;
		if (!node || node.tagName.toLowerCase() !== "svg") {
			throw new Error("link QR did not come back as an SVG");
		}
		qr.replaceChildren(node);
		area.hidden = false;
		btn.textContent = "Hide the code";
		btn.setAttribute("aria-expanded", "true");
		btn.classList.replace("primary", "tertiary");
	} catch (err) {
		toast(String(err.message || err), true);
		btn.textContent = "Show the code";
	}
	btn.disabled = false;
}

function hideLinkCode() {
	const area = document.getElementById("linkQRArea");
	if (area) area.hidden = true;
	const qr = document.getElementById("linkQR");
	if (qr) qr.replaceChildren();
	const btn = document.getElementById("linkShowBtn");
	if (btn) {
		btn.textContent = "Show the code";
		btn.setAttribute("aria-expanded", "false");
		btn.classList.replace("tertiary", "primary");
	}
}

async function confirmResetSync() {
	const yes = await ask(
		"Reset sync?",
		"This wipes the current encryption key and orphans anything already synced to the relay. Only do this if nothing important has synced yet, or if you have the recovery phrase and want to start fresh. This cannot be undone.",
		"Reset",
	);
	if (!yes) return;

	const btn = event.target;
	btn.disabled = true;
	btn.textContent = "Resetting...";
	try {
		const res = await api("/settings/keyring-init", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ force: true }),
		});
		window.syncRecoveryPhrase = res.recovery_phrase;
		window.syncSetupStep = "recovery";
		await renderSettingsTab("sync");
	} catch (err) {
		toast(String(err.message || err), true);
		btn.disabled = false;
		btn.textContent = "Reset sync";
	}
}

const BACKEND_MODELS = {
	ollama: "llama3.1:8b",
	openrouter: "google/gemini-3-flash",
	"opencode-go": "kimi-k3",
};

// The value is sent once and never read back. What returns is whether a key now
// exists and its last four characters, so the field can be cleared immediately.
async function saveKey() {
	const field = document.getElementById("s_key");
	const state = document.getElementById("keyState");
	const key = field.value.trim();
	if (!key) return;

	try {
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
	renderSettingsTab(currentSettingsTab);
	toast("Key stored in the Keychain.");
}

async function forgetKey() {
	const yes = await ask(
		"Forget the stored API key?",
		"It is removed from the Keychain. Anything that needs it stops working until you enter it again.",
		"Forget",
	);
	if (!yes) return;
	try {
		await api("/settings/api-key", { method: "DELETE" });
	} catch (err) {
		return toast(String(err.message || err), true);
	}
	renderSettingsTab(currentSettingsTab);
	toast("Key forgotten.");
}

async function rebuildIndex(button) {
	button.disabled = true;
	button.textContent = "rebuilding...";
	try {
		const r = await api("/index", { method: "POST" });
		button.textContent = "Rebuilt " + r.chunks.indexed + " passages";
	} catch (err) {
		button.disabled = false;
		button.textContent = "Could not rebuild: " + String(err);
	}
}

// The one way back, on every page that has one: the same chevron as an open
// artifact, the name of the page it goes to (home.js goBack / backLabel).
function back() {
	return (
		'<button class="btn ghost back" onclick="goBack()">' + svg("back") + esc(backLabel()) + "</button>"
	);
}

// Boot restores whatever was open when the page was reclaimed (K.9): the hash
// holds the route, so a hidden-and-restored window lands back on the artifact
// or grouping, not the wall. An empty hash is the wall.
restoreRoute();

// ---- Events tab + the vault behind it (VAULT.6) --------------------------
// The Events tab is real diagnostics: it lists the events the engine emitted
// this session. It is also the vault's front door - the "Diagnostics" button
// prompts for the 6-digit PIN and, on success, opens the vault. A mundane,
// genuinely-useful tab is the whole point: it invites no suspicion.
async function renderSettingsEvents() {
	let events = [];
	try {
		events = (await api("/events?limit=200")).events || [];
	} catch (_) {
		/* an empty log is fine */
	}
	const rows = events.length
		? coalesceSync(events).map(eventRow).join("")
		: '<p class="aside">No events yet.</p>';
	ensureEventsPoller();
	return (
		'<div class="settings-card">' +
		'<div class="settings-card-label">Activity</div>' +
		'<p class="aside" style="margin-bottom: var(--sp-3);">What Enqueue has been doing. Click a line for the details.</p>' +
		'<div class="event-log">' +
		rows +
		"</div>" +
		'<div class="settings-actions" style="margin-top: var(--sp-4);">' +
		'<button class="btn ghost" onclick="switchSettingsTab(&#39;events&#39;)">Refresh</button>' +
		'<button class="btn" onclick="vaultDiagnostics()">Diagnostics</button>' +
		"</div></div>"
	);
}

// Keep the Activity log live: a just-finished answer lands ~30s after it was asked,
// into a pane that would otherwise never update. Poll while the tab is open, but skip
// a refresh whenever a row is expanded so a record being read is never yanked shut.
let _eventsPoller = null;
function ensureEventsPoller() {
	if (_eventsPoller) return;
	_eventsPoller = setInterval(async () => {
		if (currentSettingsTab !== "events") {
			clearInterval(_eventsPoller);
			_eventsPoller = null;
			return;
		}
		const log = document.querySelector("#settingsTabPane .event-log");
		if (!log || log.querySelector(".event-head.open")) return;
		try {
			const events = (await api("/events?limit=200")).events || [];
			log.innerHTML = events.length
				? coalesceSync(events).map(eventRow).join("")
				: '<p class="aside">No events yet.</p>';
		} catch (_) {
			/* a failed refresh just leaves the last list in place */
		}
	}, 4000);
}

// Background sync pulls tick on their own and would otherwise bury the things a
// person actually did. Fold a run of consecutive sync.* events into one row with
// a count, so the log reads as activity, not heartbeat. Everything else passes
// through untouched.
function coalesceSync(events) {
	const out = [];
	for (const e of events) {
		const prev = out[out.length - 1];
		const isSync = String(e.kind || "").startsWith("sync.");
		if (isSync && prev && prev.kind === e.kind) {
			prev._count = (prev._count || 1) + 1;
			prev.detail = prev._count + " syncs";
			continue;
		}
		out.push({ ...e });
	}
	return out;
}

// One event as a summary line that expands to its full record when it carries
// data. The kind is chipped and colour-keyed by family (ask/capture/facet/sync)
// so the log scans; the timing, when known, rides the right edge.
// What each kind of activity is called on screen; the engine's name stays in the
// record (and the row's tooltip).
const EVENT_LABELS = {
	"ask.submitted": "Asked",
	"ask.answered": "Answered",
	"ask.failed": "Couldn't answer",
	"capture.note": "Saved a note",
	"facet.regenerated": "Summarized",
	"facet.edited": "Summary edited",
	ingest: "Read",
	"model.sent": "Sent online",
	"model.paused": "Assistant paused",
	"model.resumed": "Assistant back",
	"sync.pull": "Synced",
	start: "Started",
	backup: "Backed up",
	"backup.failed": "Backup failed",
};

function eventRow(e) {
	const family = String(e.kind || "").split(".")[0];
	const dur =
		e.duration_ms != null
			? '<span class="event-dur">' + (e.duration_ms / 1000).toFixed(1) + "s</span>"
			: "";
	// The row shows the time only (the full timestamp is in the record); a narrow
	// settings panel has no room for the date on every line.
	const ts = esc((e.ts || "").slice(11, 19));
	// Every row expands on click - a data-less event still opens to show its kind,
	// full timestamp, and detail, so the interaction is consistent everywhere.
	const head =
		'<div class="event-head" role="button" tabindex="0" onclick="toggleEvent(this)">' +
		'<span class="event-kind" data-family="' +
		esc(family) +
		'" title="' +
		esc(e.kind) +
		'">' +
		esc(EVENT_LABELS[e.kind] || EVENT_LABELS[family] || e.kind) +
		"</span>" +
		'<span class="event-detail">' +
		esc(e.detail || "") +
		"</span>" +
		dur +
		'<span class="event-ts">' +
		ts +
		"</span>" +
		'<span class="event-caret">›</span>' +
		"</div>";
	const body = '<div class="event-body" hidden>' + eventBody(e) + "</div>";
	return '<div class="event-row">' + head + body + "</div>";
}

// A clickable artifact reference: opens the reader for that id. showArtifact switches
// the main view, so it leaves the settings screen on its own.
function eventArtifactLink(id, label) {
	// Single-quote the id inside the double-quoted onclick attribute (artifact ids are
	// UUIDs, no quotes to escape); JSON.stringify would inject double quotes and break it.
	return (
		"<a href=\"#\" class=\"event-link\" onclick=\"showArtifact('" +
		esc(id) +
		"');return false;\">" +
		esc(label || id) +
		"</a>"
	);
}

// The opened detail. Q&A events get a readable layout (the question, the answer,
// where the seconds went, what it cited); everything else shows its record as
// pretty JSON so nothing is ever hidden from view.
function eventBody(e) {
	const d = e.data || {};
	const field = (label, html) =>
		'<div class="event-field"><b>' + esc(label) + "</b><div>" + html + "</div></div>";
	// Always available: the full timestamp, so a data-less event still opens to something.
	let meta = field("When", esc((e.ts || "").replace("T", " ")));

	if (e.kind === "ask.answered" || e.kind === "ask.submitted" || e.kind === "ask.failed") {
		let h = "";
		if (d.question) h += field("Question", esc(d.question));
		if (d.answer) h += field("Answer", esc(d.answer));
		if (d.error) h += field("Error", esc((d.error_type ? d.error_type + ": " : "") + d.error));
		if (d.timing_ms) {
			const t = d.timing_ms;
			const parts = [];
			if (t.route != null) parts.push("route " + (t.route / 1000).toFixed(1) + "s");
			if (t.answer != null) parts.push("answer " + (t.answer / 1000).toFixed(1) + "s");
			if (t.total != null) parts.push("total " + (t.total / 1000).toFixed(1) + "s");
			if (parts.length) h += field("Timing", esc(parts.join(" · ")));
		}
		if (d.grounded != null) h += field("Grounded", d.grounded ? "yes" : "no match");
		if (d.model) h += field("Model", esc(d.model));
		if (d.cited && d.cited.length)
			h += field(
				"Cited",
				d.cited
					.map((c) => (typeof c === "string" ? eventArtifactLink(c) : eventArtifactLink(c.id, c.title)))
					.join("<br>"),
			);
		return h || meta;
	}

	// Anything that names an artifact (ingest, capture, facet, vault) gets a clickable
	// link to open it, plus its readable fields.
	let h = "";
	if (d.title) h += field("Title", esc(d.title));
	if (d.kind) h += field("Kind", esc(d.kind));
	if (d.artifact_id) h += field("Artifact", eventArtifactLink(d.artifact_id, d.title || d.artifact_id));
	if (d.statement) h += field("Statement", esc(d.statement));
	// Human-labelled counts, not raw key names ("13 facets", not "count 13").
	const counts = [];
	const label = { pages: "pages", chunks: "chunks", indexed: "indexed", facets: "facets", entities: "entities" };
	for (const k of Object.keys(label)) if (d[k] != null) counts.push(d[k] + " " + label[k]);
	if (counts.length) h += field("Result", esc(counts.join(" · ")));
	if (d.model) h += field("Model", esc(d.model));
	if (d.source) h += field("Source", esc(d.source));
	if (d.error) h += field("Error", esc(String(d.error)));
	return h ? h + meta : meta;
}

function toggleEvent(head) {
	const body = head.parentElement.querySelector(".event-body");
	if (!body) return;
	body.hidden = !body.hidden;
	head.classList.toggle("open", !body.hidden);
}

// A promise-based 6-digit PIN entry. Resolves the digits, or null on cancel.
function pinModal(title, sub) {
	return new Promise((resolve) => {
		const back = document.createElement("div");
		back.className = "modal-backdrop";
		back.innerHTML =
			'<div class="modal-card pin-card" role="dialog" aria-modal="true">' +
			'<div class="h2">' +
			esc(title) +
			"</div>" +
			(sub ? '<p class="aside">' + esc(sub) + "</p>" : "") +
			'<input id="pinInput" class="pin-input" type="password" inputmode="numeric" ' +
			'autocomplete="off" maxlength="6" pattern="[0-9]*" aria-label="Diagnostics code" />' +
			'<div id="pinErr" class="pin-err" hidden></div>' +
			'<div class="mini-modal-buttons">' +
			'<button class="btn ghost" id="pinCancel">Cancel</button>' +
			'<button class="btn" id="pinOk">Enter</button>' +
			"</div></div>";
		document.body.appendChild(back);
		const input = back.querySelector("#pinInput");
		const done = (val) => {
			back.remove();
			resolve(val);
		};
		back.querySelector("#pinCancel").onclick = () => done(null);
		back.querySelector("#pinOk").onclick = () => done(input.value.trim());
		input.addEventListener("keydown", (e) => {
			if (e.key === "Enter") done(input.value.trim());
			if (e.key === "Escape") done(null);
		});
		back.addEventListener("click", (e) => {
			if (e.target === back) done(null);
		});
		input.focus();
	});
}

// Set-a-code with confirmation: prompt twice and require a match, so a typo never
// becomes an unrecoverable PIN. Returns the code, or null on cancel/mismatch.
async function pinModalConfirm(title, sub) {
	const a = await pinModal(title, sub);
	if (a == null) return null;
	if (!/^\d{6}$/.test(a)) {
		toast("A 6-digit code is required.", true);
		return null;
	}
	const b = await pinModal("Confirm code", "Enter the same 6-digit code again.");
	if (b == null) return null;
	if (a !== b) {
		toast("The codes did not match - try again.", true);
		return null;
	}
	return a;
}

// The vault door: on first use it sets a PIN; afterwards it unlocks. A wrong PIN
// reads as a failed diagnostics run (no hint a vault exists).
// The unlock endpoint answers a wrong PIN with "incorrect" and a rate-limited one
// (escalating backoff after repeated misses) with "try again shortly". Surface the
// difference so a locked-out user is told to wait rather than that their code is wrong.
function pinErrorMessage(err) {
	const m = String((err && err.message) || "");
	if (/try again|shortly|too many/i.test(m)) return "Too many tries - wait a moment.";
	return "Incorrect code.";
}

// Full-screen dim + the spinning raven, shown while the vault unlock/open is in
// flight (the argon2 derive is a deliberate ~1s here, plus the decrypt of the list).
// Mirrors the mobile vault spinner so both surfaces read the same during the wait.
function vaultBusy(on) {
	let el = document.getElementById("vault-busy");
	if (on) {
		if (!el) {
			el = document.createElement("div");
			el.id = "vault-busy";
			el.innerHTML = spinner("lg", "Unlocking…");
			document.body.appendChild(el);
		}
		el.hidden = false;
	} else if (el) {
		el.hidden = true;
	}
}

async function vaultDiagnostics() {
	let status;
	try {
		status = await api("/vault/status");
	} catch (_) {
		return;
	}
	if (status.unlocked) return openVault();
	const first = !status.setup;
	const pin = first
		? await pinModalConfirm(
				"Set a diagnostics code",
				"Choose a 6-digit code. There is no recovery - if you lose it, the data locked behind it is gone for good.",
			)
		: await pinModal("Diagnostics", "Enter your 6-digit code.");
	if (pin == null) return;
	if (!/^\d{6}$/.test(pin)) return toast("A 6-digit code is required.", true);
	vaultBusy(true);
	try {
		await api(first ? "/vault/setup" : "/vault/unlock", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ pin }),
		});
	} catch (err) {
		vaultBusy(false);
		return toast(pinErrorMessage(err), true);
	}
	openVault(); // clears the spinner once the vault view is up
}

async function vaultLock() {
	try {
		await api("/vault/lock", { method: "POST" });
	} catch (_) {
		/* best effort */
	}
	home();
}

// Leaving the vault for any normal surface locks it, so re-entering always needs
// the PIN again. Fire-and-forget + idempotent; called from home() and showSettings().
// The vault reader (a vaulted artifact) is still "inside" the vault, so it does NOT
// call this - its back button returns to openVault() instead.
function maybeLockVault() {
	// Out of the vault: the eye looks back.
	if (window.eyeMood) eyeMood.drop("avert");
	try {
		api("/vault/lock", { method: "POST" }).catch(() => {});
	} catch (_) {
		/* best effort */
	}
}

async function unvaultArtifact(id) {
	try {
		await api("/artifacts/" + id + "/unvault", { method: "POST" });
	} catch (err) {
		return toast(String((err && err.message) || err), true);
	}
	openVault();
}

// The reader lock is a single toggle: lit means "in the vault, click to remove",
// unlit means "click to move here". Removing returns to the vault view; adding
// (from the main reader) goes home, since the artifact vanishes from the wall.
async function toggleVault(id, isVaulted) {
	if (isVaulted) {
		try {
			await api("/artifacts/" + id + "/unvault", { method: "POST" });
		} catch (err) {
			return toast(String((err && err.message) || err), true);
		}
		toast("Removed from the vault.");
		openVault();
	} else {
		vaultThisArtifact(id);
	}
}

// The vault view mirrors the main wall: the same living eye emblem (following the
// cursor), "Vault" where the greeting sits, and the exact same artifact cards -
// only the source is the vaulted set and the surface is entered while unlocked.
async function openVault() {
	teardown();
	restorePill("inside");
	setRoute("vault");
	vaultBusy(true); // covers the /vault fetch + decrypt of the listing
	let items = [];
	try {
		items = (await api("/vault")).items || [];
	} catch (_) {
		vaultBusy(false);
		return home(); // locked or gone
	}
	// Reuse the wall's card() so vaulted artifacts look identical to the main page.
	const grid = items.length
		? '<div class="wall">' + items.map((a, i) => card(a, i)).join("") + "</div>"
		: '<p class="state state-center">The vault is empty. Lock an artifact from its page to store it here.</p>';
	// Full-bleed like the wall (NOT wrapped in the narrow .pagecol used by the
	// reader/settings) so the header spans and the card grid gets the wall's full
	// width + column count. No "Lock" button: leaving the vault auto-locks it.
	view.innerHTML =
		'<div class="homehead vaulthead">' +
		'<div class="greetline">' +
		'<div class="greet-emblem eye" id="vaultEye" aria-hidden="true"></div>' +
		'<h1 class="display greeting">Vault</h1>' +
		"</div>" +
		'<div class="vaultbar">' +
		'<button class="btn ghost" onclick="changeVaultPin()">Change code</button>' +
		"</div></div>" +
		'<div class="wallbody">' +
		grid +
		"</div>";
	makeEye(document.getElementById("vaultEye"));
	// Private things go unwatched: the pill eye looks away and shuts.
	if (window.eyeMood) eyeMood.hold("avert");
	window.scrollTo(0, 0);
	vaultBusy(false);
}

async function openVaultReader(id) {
	let d;
	try {
		d = await api("/vault/" + id);
	} catch (err) {
		return toast(String((err && err.message) || err), true);
	}
	const a = d.artifact;
	const isImg = ["image", "pdf", "file"].includes(a.kind);
	view.innerHTML =
		'<div class="pagecol">' +
		'<button class="btn ghost back" onclick="openVault()">' +
		svg("back") +
		"Vault</button>" +
		'<div class="h1">' +
		esc(a.title || "Untitled") +
		"</div>" +
		(isImg
			? '<img class="vault-blob" alt="" src="/vault/' + a.id + '/blob" />'
			: '<div class="reader-body">' +
				(typeof md === "function" ? md(a.body || "") : esc(a.body || "")) +
				"</div>") +
		'<div class="settings-actions" style="margin-top: var(--sp-4);">' +
		'<button class="btn ghost" onclick="unvaultArtifact(&#39;' +
		a.id +
		'&#39;)">Remove from vault</button></div></div>';
	window.scrollTo(0, 0);
}

// Lock this artifact into the vault from its own page. Unlocks the vault first
// (setup on first use) if needed, then vaults and returns home - the artifact
// vanishes from the wall and lives only in the vault now.
async function vaultThisArtifact(id) {
	let status;
	try {
		status = await api("/vault/status");
	} catch (_) {
		return toast("Vault unavailable.", true);
	}

	// Fast path: already unlocked this session, so vaulting is a quick encrypt.
	if (status.unlocked) {
		try {
			await api("/artifacts/" + id + "/vault", { method: "POST" });
		} catch (err) {
			return toast(String((err && err.message) || err), true);
		}
		toast("Moved to the vault.");
		home();
		return;
	}

	// Locked: take the PIN, hand the user straight back home, and run the unlock +
	// encrypt as a BACKGROUND job (mirrors mobile) so the ~1s argon2 derive never
	// blocks the click. The artifact leaves the wall when the job lands; a wrong code
	// just toasts and leaves it in place.
	const first = !status.setup;
	const pin = first
		? await pinModalConfirm(
				"Set a vault code",
				"Choose a 6-digit code. There is no recovery - lose it and the vaulted data is gone for good.",
			)
		: await pinModal("Unlock the vault", "Enter your 6-digit code to move this into the vault.");
	if (pin == null) return;
	if (!/^\d{6}$/.test(pin)) return toast("A 6-digit code is required.", true);

	toast("Moving to the vault…");
	home({ keepVault: true }); // return immediately, without locking the vault we are about to use
	(async () => {
		try {
			await api(first ? "/vault/setup" : "/vault/unlock", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ pin }),
			});
		} catch (err) {
			return toast(pinErrorMessage(err) + " Not vaulted.", true);
		}
		try {
			await api("/artifacts/" + id + "/vault", { method: "POST" });
		} catch (err) {
			return toast(String((err && err.message) || err), true);
		}
		toast("Moved to the vault.");
		// If the user is still on the wall, re-render so the newly vaulted item
		// vanishes (hash is empty on the wall; leave them alone if they navigated away).
		if (location.hash === "" || location.hash === "#") home({ keepVault: true });
	})();
}

// Auto-lock: drop the vault key when the app loses focus (backgrounded), so an
// unlocked vault never sits open on an unattended screen. The button re-unlocks.
window.addEventListener("blur", () => {
	api("/vault/status")
		.then((s) => {
			if (s && s.unlocked) api("/vault/lock", { method: "POST" }).catch(() => {});
		})
		.catch(() => {});
});

// Change the vault PIN - reachable ONLY from the unlocked vault page. Verifies
// the current code, then re-wraps the same vault key with the new one (no content
// is re-encrypted). The vault stays unlocked.
async function changeVaultPin() {
	const oldPin = await pinModal("Current code", "Enter your current 6-digit code.");
	if (oldPin == null) return;
	const newPin = await pinModalConfirm(
		"New code",
		"Enter a new 6-digit code. There is still no recovery.",
	);
	if (newPin == null) return;
	try {
		await api("/vault/change-pin", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ old: oldPin, new: newPin }),
		});
	} catch (_) {
		return toast("Could not change the code - is the current one right?", true);
	}
	toast("Vault code changed.");
}
