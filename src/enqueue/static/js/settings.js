// ---- settings ------------------------------------------------------------
// Not a destination. This is where you go when something is wrong, so it says where
// every value came from: a field you edit that is silently overridden by an
// environment variable is worse than no field.
const SETTING_LABELS = {
	llm_model: "Model",
	llm_url: "Endpoint",
	vision_model: "Vision model (describes images)",
	model_retries: "Retries after a failed answer",
	user_agent: "User agent for link previews",
	hotkey: "Capture hotkey",
	llm_headers: "Extra headers",
	auto_preview: "Resolve links when you save them",
	trash_days: "Days a deleted thing waits before it goes",
};

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

const SETTINGS_TABS = [
	{ id: "ai", label: "AI", render: renderSettingsAI },
	{ id: "features", label: "Features", render: renderSettingsFeatures },
	{ id: "storage", label: "Storage", render: renderSettingsStorage },
	{ id: "trash", label: "Trash", render: renderSettingsTrash },
	{ id: "sync", label: "Sync", render: renderSettingsSync },
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
}

// The tab bar's onclick target: swap only the pane below it.
function switchSettingsTab(name) {
	renderSettingsTab(name);
}

async function showSettings() {
	teardown();
	restorePill("inside");
	view.innerHTML =
		'<div class="pagecol">' +
		'<div class="h1">Settings</div>' +
		// Q.6: a one-line human orientation - names what settings does in
		// product terms and when changes land, warming the bare heading.
		'<p class="aside" style="margin-top: var(--sp-2); margin-bottom: var(--sp-4); max-width: 64ch;">' +
		"Tune how Enqueue captures, thinks, and remembers. Changes save when you press Save." +
		"</p>" +
		settingsTabBar() +
		'<div id="settingsTabPane"></div>' +
		"</div>";
	window.scrollTo(0, 0);
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
	let html = '<div class="h2">AI</div>';

	// Connection: how the app reaches a model - the backend, the model name,
	// the URL, the key, and any extra headers. Reads first, because a person
	// sets the wire before they tune behaviour (N.7b).
	html +=
		'<div class="shelf">Connection</div><div class="group" style="margin-bottom: var(--sp-4);">';
	const chosen = d.settings.llm_backend;
	html +=
		'<div class="field"><label for="s_backend">Answers come from</label>' +
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
		"</select>";
	const picked = d.backends.find((b) => b.name === chosen.value);
	if (picked && !picked.local)
		html +=
			// Q.6: a warmer verb and plain English, same facts. The "yet" and
			// "add one below" point at the key field instead of an env var.
			'<div class="aside caution">When you ask a question, the text of whatever is retrieved goes to ' +
			esc(picked.label) +
			". Anything you marked local only stays here." +
			(picked.needs_key && !picked.key_present
				? " <b>No API key set yet</b>, so calls will fail until you add one below."
				: "") +
			"</div>";
	else if (picked)
		html += '<div class="aside">Nothing leaves this machine.</div>';
	for (const name of ["llm_model"]) {
		const f = d.settings[name];
		html += fieldRow(name, esc(SETTING_LABELS[name]), {
			value: f.value,
			locked: f.locked,
			pinned: "pinned by " + esc(f.env_var) + " in the environment",
		});
	}
	// SET2.2b: FIX.3 - an OpenCode Go model that needs /responses or /messages
	// cannot be reached by Enqueue's /chat/completions adapter. Warn here, in
	// Settings, before the call fails in chat with a misread auth error.
	const modelVal = (d.settings.llm_model && d.settings.llm_model.value) || "";
	if (picked && picked.chat_models) {
		const unsupported = picked.chat_models.unsupported_shape || [];
		if (unsupported.includes(modelVal))
			html +=
				'<div class="aside caution"><b>' +
				esc(modelVal) +
				"</b> is served by OpenCode Go behind an API shape Enqueue does not speak yet " +
				"(/responses or /messages). Enqueue only speaks /chat/completions, so pick a " +
				"model from this list instead: " +
				esc(picked.chat_models.examples) +
				".</div>";
	}
	// SET.1: the endpoint is implied by the backend, so only `custom` - the one
	// backend whose URL is not in config.BACKENDS - shows an Endpoint field.
	if (chosen.value === "custom") {
		const f = d.settings.llm_url;
		html += fieldRow("llm_url", esc(SETTING_LABELS.llm_url), {
			value: f.value,
			locked: f.locked,
			pinned: "pinned by " + esc(f.env_var) + " in the environment",
		});
	}

	html += "</div></div>";

	// --- API Key ---
	html +=
		'<div class="shelf">API Key</div><div class="group" style="margin-bottom: var(--sp-4);">';
	const keyed = d.storage.api_key_present;
	html +=
		'<div class="field"><label for="s_key">API key</label>' +
		(d.storage.api_key_editable
			? '<div class="keyrow">' +
				'<input id="s_key" type="password" autocomplete="off" spellcheck="false" ' +
				'placeholder="' +
				(keyed
					? "stored " + esc(d.storage.api_key_hint || "")
					: "paste a key") +
				'">' +
				'<button class="btn tertiary sm" onclick="saveKey()">Save</button>' +
				(keyed
					? '<button class="btn ghost harm sm" onclick="forgetKey()">Forget</button>'
					: "") +
				"</div>" +
				'<div class="aside">saved in the macOS Keychain, not in any file here.</div>'
			: '<div class="aside caution">' +
				(d.storage.api_key_where === "environment"
					? "Pinned by <b>ENQ_LLM_API_KEY</b> in the environment" +
						(d.storage.api_key_hint
							? " (" + esc(d.storage.api_key_hint) + ")"
							: "") +
						". Unset it to store one here instead."
					: "No keychain on this system.") +
				"</div>") +
		'<div id="keyState" class="aside caution"></div></div>';

	html += "</div></div>";

	// Behavior: how the model is used once connected - retries, the vision
	// model, and the concept-layer rebuild.
	html += '<div class="settings-divider"></div>';
	html +=
		'<div class="shelf">Behavior</div><div class="group" style="margin-bottom: var(--sp-4);">';
	for (const name of ["model_retries", "vision_model"]) {
		const f = d.settings[name];
		html += fieldRow(name, esc(SETTING_LABELS[name]), {
			value: f.value,
			locked: f.locked,
			pinned: "pinned by " + esc(f.env_var) + " in the environment",
		});
	}
	html +=
		'<div class="aside">Images are described by the <b>vision model</b> behind the ' +
		"scenes when they are saved, so they can be found by search and by ask. It must " +
		"be a vision model on the same backend - Ollama's <code>llava</code> or " +
		"<code>moondream</code>, or a hosted vision model. With no vision model, images " +
		"stay unsearchable; the capture itself never waits on this. Images saved before " +
		"it existed are caught up by <code>enq index --images</code>.</div>";
	html += "</div>";

	// The concept layer is generated by the model at capture, so switching to a
	// better model above does not touch what is already stored. This rebuilds it
	// for everything with the current model. It is its own action, not a staged
	// setting: it fires now and runs in the background, so it lives outside the
	// Save/Discard bar below.
	html +=
		'<div class="shelf">Search concepts</div><div class="group" style="margin-bottom: var(--sp-4);">' +
		'<div class="field"><label>Concepts (facets)</label>' +
		'<button class="btn secondary" id="rebuildFacetsBtn" onclick="rebuildFacets()">Rebuild concepts</button>' +
		'<div class="aside">Concepts are what an item could be an example of - ' +
		'"lamp", "sour", "packing list". The model reads them when you save, and ' +
		"search and the looks-like groupings use them. Rebuilding re-analyzes every " +
		"item with the current model; it runs in the background, one model call per item." +
		'</div><div id="facetRebuildState" class="aside"></div></div>';

	html += settingsActionsBar();
	return html;
}

// Rebuild the whole concept layer with the current model (POST /facets redo).
// The run is long - one model call per item - so the button does not block on
// it: it fires, reports that it is running, and updates when the run reports
// back. Leaving the page does not stop it; generate_all commits per item, so a
// closed tab just leaves a resumable, half-rebuilt layer, never a corrupt one.
async function rebuildFacets() {
	const yes = await ask(
		"Rebuild concepts?",
		"Every item is re-analyzed with the current model. This runs in the background and can take a while.",
		"Rebuild",
	);
	if (!yes) return;
	const btn = document.getElementById("rebuildFacetsBtn");
	const el = document.getElementById("facetRebuildState");
	if (btn) btn.disabled = true;
	if (btn) btn.textContent = "Rebuilding...";
	if (el) el.textContent = "Rebuilding in the background...";
	toast("Rebuilding concepts in the background.");
	api("/facets", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ redo: true }),
	})
		.then((r) => {
			if (el)
				el.textContent =
					"Done. " +
					(r.generated || 0) +
					" items re-analyzed, " +
					(r.facets || 0) +
					" concepts.";
			if (btn) {
				btn.disabled = false;
				btn.textContent = "Rebuild concepts";
			}
		})
		.catch((err) => {
			if (el)
				el.textContent =
					"Rebuild failed: " + String((err && err.message) || err);
			if (btn) {
				btn.disabled = false;
				btn.textContent = "Rebuild concepts";
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

// Switching backend moves the model name with it when one is known. The
// endpoint is implied by the backend itself (SET.1), so nothing stages a URL
// here - only `custom` has a user-typed endpoint, edited in its own field.
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
		'<span class="aside dirty">Changes ready</span>' +
		'<button class="btn primary" onclick="saveSettings()">Save</button>' +
		'<button class="btn ghost" onclick="discardSettings()">Discard</button>' +
		"</div>"
	);
}

// ---- Features sub-page ---------------------------------------------------
// ---- Features tab --------------------------------------------------------
async function renderSettingsFeatures() {
	const d = await api("/settings");
	let html = '<div class="h2">Features</div>';

	html += '<div class="shelf">Capture</div><div class="group">';
	const hk = d.settings.hotkey;
	html +=
		'<div class="field"><label for="s_hotkey">' +
		esc(SETTING_LABELS.hotkey) +
		"</label>" +
		'<button class="recorder" id="s_hotkey"' +
		(hk.locked ? " disabled" : "") +
		' onclick="recordHotkey(this)"><span id="hotkeyLabel">' +
		esc(keyLabel(hk.value)) +
		"</span></button>" +
		(hk.locked
			? '<div class="pinned">pinned by ' + esc(hk.env_var) + "</div>"
			: '<div class="aside">Click, then press the combination you want.</div>') +
		"</div>";
	const ua = d.settings.user_agent;
	html += fieldRow("user_agent", esc(SETTING_LABELS.user_agent), {
		value: ua.value,
		locked: ua.locked,
		placeholder: "Enqueue/0.2 (+https://...)",
		aside: "Some publishers refuse a client with no contact URL.",
	});
	const ap = d.settings.auto_preview;
	const apOn = String(ap.value).toLowerCase() !== "off";
	html +=
		'</div><div class="shelf">Links</div><div class="group">' +
		'<div class="field"><div class="togglerow"><div>' +
		'<span class="rowlabel">' +
		esc(SETTING_LABELS.auto_preview) +
		"</span>" +
		(ap.locked
			? '<div class="pinned">pinned by ' + esc(ap.env_var) + "</div>"
			: '<div class="aside">' +
				(apOn
					? "One request per link, as you save it."
					: "A link stays a bare address until you open it.") +
				"</div>") +
		"</div>" +
		'<button class="toggle" role="switch" aria-checked="' +
		String(apOn) +
		'" aria-label="' +
		esc(SETTING_LABELS.auto_preview) +
		'"' +
		(ap.locked ? ' disabled aria-disabled="true"' : "") +
		' onclick="stagePreviewToggle(this)"><span class="knob"></span></button>' +
		"</div></div></div>";

	html += settingsActionsBar();
	return html;
}

// ---- Storage sub-page ----------------------------------------------------
// ---- Storage tab ----------------------------------------------------------
async function renderSettingsStorage() {
	const d = await api("/settings");
	let html = '<div class="h2">Storage</div>';

	const s0 = d.storage;
	html +=
		// Q.6: the second sentence reveals portability - the data is the
		// user's, in a standard format, at a known path (SQLite is the source
		// of truth per db.py / config.DB_PATH).
		'<div class="callout note"><p>Nothing you keep here leaves this machine. ' +
		"Everything you capture lives in one SQLite file you can back up, move, or read with any tool.</p></div>" +
		'<div class="group"><div class="field">' +
		'<span class="rowlabel">Everything lives at</span>' +
		'<div class="mono chip">' +
		esc(s0.data_dir) +
		"</div></div></div>";
	html +=
		'<div class="shelf">Usage</div><div class="group">' +
		'<div class="field"><div class="facts">' +
		'<b>database</b> <span class="mono">' +
		bytes(s0.database.bytes) +
		"</span><br>" +
		'<b>files</b> <span class="mono">' +
		bytes(s0.blobs.bytes) +
		"</span><br>" +
		Object.entries(s0.counts)
			.map(
				([k, v]) => "<b>" + esc(k) + '</b> <span class="mono">' + v + "</span>",
			)
			.join("<br>") +
		"</div></div>" +
		'<div class="field"><span class="rowlabel">Rebuild the index</span>' +
		'<div class="aside">Everything derived is thrown away and rebuilt.</div>' +
		'<div class="actions"><button class="btn tertiary" ' +
		'onclick="rebuildIndex(this)">Rebuild the index</button></div></div></div>';

	return html;
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
		'<div class="shelf">Retention</div><div class="group">' +
		fieldRow("trash_days", esc(SETTING_LABELS.trash_days), {
			type: "number",
			min: 1,
			max: 3650,
			value: td.value,
			locked: td.locked,
			pinned: "pinned by " + esc(td.env_var),
			aside: "Only things you delete are ever removed.",
		}) +
		"</div>";
	html +=
		'<div class="shelf">Trash</div><div class="group">' +
		'<div class="aside">Deleted things wait ' +
		trash.retention_days +
		" day" +
		(trash.retention_days === 1 ? "" : "s") +
		", then go for good.</div>";
	if (!trash.items.length) {
		html += '<div class="aside">Nothing in the trash.</div>';
	} else {
		html +=
			'<div class="callout warn">Emptying the trash deletes files permanently.</div>' +
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
// - Not configured: the setup walk (relay URL -> passwordless keyring init with
//   the recovery phrase shown once -> sync secret).
// - Configured: the read-only configuration + the Signal-style linking QR (QR.3).
async function renderSettingsSync() {
	const d = await api("/settings");
	const sync = d.sync || {};
	let html = '<div class="h2">Sync</div>';

	if (!sync.relay_configured) {
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

	let html = '<div class="shelf">Set up sync</div><div class="group">';
	if (step === "recovery") {
		html += renderSyncRecovery();
	} else if (step === 3) {
		html += renderSyncStepSecret(sync);
	} else {
		html += renderSyncStepRelay(sync);
	}
	html += "</div>";
	return html;
}

function renderSyncStepRelay(sync) {
	const relayValue = esc(sync.relay_url || "http://127.0.0.1:8788");
	return (
		'<div class="aside">First, the relay that stores your encrypted library ' +
		"snapshots and shares them between devices. The bytes are encrypted - the " +
		"relay cannot read them.</div>" +
		'<div class="field" style="margin-top: var(--sp-4);">' +
		'<label for="s_sync_relay_url">Relay URL</label>' +
		'<input id="s_sync_relay_url" type="url" value="' +
		relayValue +
		'" placeholder="http://127.0.0.1:8788">' +
		'<div class="aside">Default is the local <code>enq relay</code> address ' +
		"from <code>127.0.0.1:8788</code>. A remote relay needs <code>--host 0.0.0.0</code> " +
		"on the machine running it.</div>" +
		"</div>" +
		'<div class="actions" style="margin-top: var(--sp-4);">' +
		'<button class="btn primary" onclick="advanceSyncSetupAndInit()">Continue</button>' +
		"</div>"
	);
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
		'<div class="aside">Finally, the sync secret. This authenticates your ' +
		"devices to the relay. Leave the field empty to generate a secure one, " +
		"or paste the secret from the relay you run.</div>" +
		'<div class="field" style="margin-top: var(--sp-4);">' +
		'<label for="s_sync_secret">Sync secret</label>' +
		'<input id="s_sync_secret" type="password" autocomplete="off" ' +
		'placeholder="Leave empty to generate a secure secret">' +
		'<div class="aside">Stored in the macOS Keychain, never in any file.</div>' +
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
	window.syncSetupStep = 3;
	renderSettingsTab(currentSettingsTab);
}

async function saveSyncSecretAndFinish() {
	const relayUrl = window.syncRelayUrl || "http://127.0.0.1:8788";
	const secretField = document.getElementById("s_sync_secret");
	const secret = secretField ? secretField.value.trim() : "";
	const btn = event.target;
	btn.disabled = true;
	btn.textContent = "Saving...";
	try {
		// Generate a secure secret when the field is empty.
		const finalSecret = secret || generateSyncSecret();
		// PUT /settings/sync-secret also pushes the keyring to the relay.
		await api("/settings/sync-secret", {
			method: "PUT",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ secret: finalSecret }),
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

function generateSyncSecret() {
	const array = new Uint8Array(32);
	crypto.getRandomValues(array);
	return Array.from(array, (b) => b.toString(16).padStart(2, "0")).join("");
}

function renderSyncConfigured(_sync) {
	let html =
		'<div class="shelf">Link a device</div><div class="group" style="margin-bottom: var(--sp-4);">';
	html +=
		'<div class="aside">On your phone, open the Enqueue app and choose "Link a device". ' +
		"The phone camera scans the QR below and receives the encryption key in one " +
		"step - no password, no typing. The QR contains your encryption key: only scan " +
		"it with the Enqueue app, never screenshot it, and never share it." +
		"</div>" +
		'<div class="field" style="margin-top: var(--sp-4);"><label>Linking QR</label>' +
		'<div class="actions" style="gap: var(--sp-2); margin-top: var(--sp-2);">' +
		'<button class="btn primary" id="linkShowBtn" onclick="showLinkCode()">Show linking QR</button>' +
		"</div>" +
		'<div id="linkQRArea" hidden style="margin-top: var(--sp-4);">' +
		'<div id="linkQR" style="text-align: center; margin-bottom: var(--sp-3);"></div>' +
		'<div class="actions" style="margin-top: var(--sp-2);">' +
		'<button class="btn ghost" onclick="hideLinkCode()">Hide QR</button>' +
		"</div>" +
		"</div>" +
		"</div>" +
		"</div>";

	html +=
		'<div class="shelf">Reset sync</div><div class="card" style="margin-top: var(--sp-4);"><div class="group">';
	html +=
		'<div class="aside caution">' +
		"Resetting sync wipes the current encryption key and orphans anything " +
		"already synced to the relay. Only do this if nothing important has " +
		"synced yet, or if you have the recovery phrase and want to start fresh." +
		"</div>" +
		'<div class="actions" style="margin-top: var(--sp-4);">' +
		'<button class="btn harm" onclick="confirmResetSync()">Reset sync</button>' +
		"</div>" +
		"</div>" +
		"</div>";

	return html;
}

async function showLinkCode() {
	const btn = document.getElementById("linkShowBtn");
	const area = document.getElementById("linkQRArea");
	const qr = document.getElementById("linkQR");
	btn.disabled = true;
	btn.textContent = "Generating...";
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
		btn.textContent = "Show linking QR";
		btn.disabled = false;
	} catch (err) {
		toast(String(err.message || err), true);
		btn.textContent = "Show linking QR";
		btn.disabled = false;
	}
}

function hideLinkCode() {
	const area = document.getElementById("linkQRArea");
	area.hidden = true;
	const qr = document.getElementById("linkQR");
	if (qr) qr.replaceChildren();
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

function back() {
	return '<div class="back" onclick="home()">&larr; everything</div>';
}

// Boot restores whatever was open when the page was reclaimed (K.9): the hash
// holds the route, so a hidden-and-restored window lands back on the artifact
// or grouping, not the wall. An empty hash is the wall.
restoreRoute();
