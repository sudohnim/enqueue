// ---- chats ---------------------------------------------------------------
// Asking is a conversation, not a single shot. The concepts a conversation turns out
// to circle are kept beside it, and each one can still hang a room, which is the
// only reason to store them rather than to name a chat by its first line.

let chat = null;
const rail = null;

function teardown() {
	if (readerWatch) {
		readerWatch.disconnect();
		readerWatch = null;
	}
	// Leaving a screen has to take that screen's pending work with it. `ctx` is what
	// every deferred callback tests itself against, so a `ctx` that outlives its view
	// is a licence for the old screen to redraw itself over the new one.
	clearTimeout(faceWatch);
	faceWatch = null;
	// The drawer belongs to the artifact view; leaving the view takes it with it.
	const drawer = document.getElementById("drawer");
	if (drawer) drawer.classList.remove("open");
	// The greeting eye's timer and pointer listener live only while the home view
	// is up; leaving any surface clears them.
	tearDownEye();

	// A poller watching this chat's pending turns dies with the surface: a stale
	// timer must never re-render a view the person has left.
	stopPolling();
	ctx = null;
	chat = null;
	organizeTurns = {};
	// Unsaved settings edits are staging on a form, not a decision. Leaving the form
	// drops them, so stale values never follow the user between screens.
	pendingSettings = null;
}

// The pending-answer mark: the app's spinning raven beside the violet "Loading…"
// sheen, so a waiting turn has both the brand's motion and the theme's color. Reuses
// the shared .loader/.loader-bird styles; only the caption is the gradient text.
function eyeLoader() {
	return (
		'<div class="loader loader-sm" role="status">' +
		'<img class="loader-bird" src="/static/loading.png" alt="" aria-hidden="true">' +
		'<span class="eye-loading">Loading&hellip;</span>' +
		"</div>"
	);
}

async function startChat(text) {
	const asked = { kind: scope.kind, id: scope.id };
	openPanel();
	showTranscript();
	// Optimistic: the question and a thinking bubble land immediately, so the panel
	// never blinks empty between pressing send and the chat row existing.
	const body = document.getElementById("eyeBody");
	if (body) {
		body.innerHTML =
			'<div class="turn you"><div class="said">' +
			esc(text) +
			"</div></div>" +
			'<div class="turn assistant"><div class="said">' +
			eyeLoader() +
			"</div></div>";
		body.scrollTop = body.scrollHeight;
	}
	let made;
	try {
		made = await api("/chats", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				scope_kind: asked.kind === "artifact" ? "artifact" : "everything",
				scope_id: asked.id || null,
				text,
			}),
		});
	} catch (err) {
		return chatFailed(err, text);
	}
	openEye(made.chat.id, made);
}

async function chatFailed(err, text) {
	const why = await api("/chats/ready").catch(() => ({
		ready: true,
		reason: null,
	}));
	const body = document.getElementById("eyeBody");
	if (!body) return;
	body.innerHTML =
		'<div class="eye-empty"><div class="line">' +
		(why.ready
			? "The assistant could not answer. " +
				esc(String(err)) +
				" Nothing was lost - your question was: " +
				esc(text)
			: "There is nothing to answer from yet: " + esc(why.reason) + ".") +
		"</div></div>";
}

// ---- the eye panel: open / close / list ----------------------------------
// The assistant lives in a docked panel, not a full view. Opening it never leaves
// the wall (the wall stays live behind, and beside, it); closing it returns focus
// to where the eye was pressed. One conversation is open at a time, with the list
// of the rest one button away.

let eyeOpen = false;
let eyeReturnFocus = null;

function panelChromeReady() {
	// Fill the header icon buttons once; svg() is only available after icons.js.
	const set = (id, icon) => {
		const el = document.getElementById(id);
		if (el && !el.dataset.iced) {
			el.innerHTML = svg(icon);
			el.dataset.iced = "1";
		}
	};
	// eyeMenuBtn is state-driven (back arrow in a transcript, list icon in the list),
	// so it is set in showTranscript/showConversations, not once here.
	set("eyeNewBtn", "plus");
	set("eyeCloseBtn", "close");
	set("eyeSend", "send");
}

function openPanel() {
	panelChromeReady();
	const panel = document.getElementById("eyePanel");
	const scrim = document.getElementById("eyeScrim");
	if (eyeOpen) return;
	eyeReturnFocus = document.activeElement;
	panel.hidden = false;
	scrim.hidden = false;
	// Two frames so the un-hidden element has a layout before the class that
	// animates it lands - otherwise it snaps open with no slide.
	requestAnimationFrame(() =>
		requestAnimationFrame(() => {
			panel.classList.add("open");
			scrim.classList.add("open");
		}),
	);
	eyeOpen = true;
	document.addEventListener("keydown", eyeEscape);
}

function closeEye() {
	const panel = document.getElementById("eyePanel");
	const scrim = document.getElementById("eyeScrim");
	if (!eyeOpen) return;
	panel.classList.remove("open");
	scrim.classList.remove("open");
	stopPolling();
	document.removeEventListener("keydown", eyeEscape);
	// Hide only after the slide-out finishes, so it animates away rather than
	// vanishing. Matches the 260ms transform in eyepanel.css.
	setTimeout(() => {
		panel.hidden = true;
		scrim.hidden = true;
	}, 280);
	eyeOpen = false;
	if (eyeReturnFocus && eyeReturnFocus.focus) eyeReturnFocus.focus();
	eyeReturnFocus = null;
}

function eyeEscape(e) {
	if (e.key !== "Escape") return;
	// The conversations list is a step inside the panel; Escape backs out of it
	// first, then out of the panel.
	if (!document.getElementById("eyeList").hidden) return showTranscript();
	closeEye();
}

// The canonical entry. `openEye()` with no id opens on a fresh conversation;
// `openEye(id)` opens that thread. `showChat` stays as the name the router and the
// morph animation already call.
async function openEye(id, preloaded) {
	openPanel();
	if (!id) return newConversation();
	if (readerWatch) {
		readerWatch.disconnect();
		readerWatch = null;
	}
	stopPolling();
	showTranscript();
	const body = document.getElementById("eyeBody");
	if (!preloaded) body.innerHTML = spinner("sm", "Opening the conversation");
	let d;
	try {
		d = preloaded || (await api("/chats/" + id));
	} catch (err) {
		body.innerHTML =
			'<div class="eye-empty"><div class="line">Could not open this conversation. ' +
			esc(String(err.message || err)) +
			"</div></div>";
		return;
	}
	chat = d;
	scope = { kind: "chat", id, label: "this conversation" };
	setRoute("c/" + id);
	renderChat(d);
	setField("");
	// A person who left during an answer and came back finds the turn still
	// pending; the poller finishes it without them doing anything (H4.3).
	if (hasPending(d)) startPolling(id);
}

async function showChat(id, preloaded) {
	return openEye(id, preloaded);
}

// A fresh conversation: no chat row exists yet - the first message creates it
// (startChat). Until then the panel shows the empty state and an armed composer.
function newConversation() {
	stopPolling();
	chat = null;
	// Only reset the scope to everything when we are not inside an artifact; an eye
	// opened on an artifact keeps that artifact as what the new thread can read.
	if (scope.kind === "chat") scope = { kind: "everything", label: "everything" };
	setRoute("c");
	const titleEl = document.getElementById("eyeTitle");
	if (titleEl) titleEl.textContent = "New conversation";
	const scopeEl = document.getElementById("eyeScope");
	if (scopeEl) {
		scopeEl.hidden = scope.kind !== "artifact";
		scopeEl.innerHTML =
			scope.kind === "artifact" ? "<span>reading only " + esc(scope.label) + "</span>" : "";
	}
	showTranscript();
	document.getElementById("eyeBody").innerHTML =
		'<div class="eye-empty">' +
		'<div class="eye-mark" aria-hidden="true">' +
		'<svg viewBox="0 0 24 24">' +
		'<path d="M2.2 12S5.8 5.6 12 5.6 21.8 12 21.8 12 18.2 18.4 12 18.4 2.2 12 2.2 12z" ' +
		'style="fill:none;stroke:var(--text);stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round"/>' +
		'<circle cx="12" cy="12" r="3.1" style="fill:var(--accent);stroke:none"/>' +
		"</svg></div>" +
		'<div class="line">Ask anything about the artifacts you saved.</div>' +
		"</div>";
	setField("");
	focusField();
}

// The menu button toggles between the open transcript and the list of every
// conversation - titled the way the wall titles them.
function toggleConversations() {
	if (document.getElementById("eyeList").hidden) showConversations();
	else showTranscript();
}

function showTranscript() {
	document.getElementById("eyeList").hidden = true;
	document.getElementById("eyeBody").hidden = false;
	document.getElementById("eyeFoot").hidden = false;
	// In a transcript the left button is a back arrow to the conversations list -
	// the reported gap: opening a thread left no visible way back to the menu.
	const btn = document.getElementById("eyeMenuBtn");
	if (btn) {
		btn.innerHTML = svg("back");
		btn.setAttribute("aria-label", "Back to conversations");
		btn.setAttribute("aria-pressed", "false");
	}
}

async function showConversations() {
	const list = document.getElementById("eyeList");
	document.getElementById("eyeBody").hidden = true;
	document.getElementById("eyeFoot").hidden = true;
	list.hidden = false;
	// In the list the button is the list icon, and pressing it returns to the thread.
	const btn = document.getElementById("eyeMenuBtn");
	if (btn) {
		btn.innerHTML = svg("list");
		btn.setAttribute("aria-label", "Conversations");
		btn.setAttribute("aria-pressed", "true");
	}
	list.innerHTML = spinner("sm", "Loading conversations");
	let d;
	try {
		d = await api("/chats");
	} catch (err) {
		list.innerHTML =
			'<div class="eye-list-empty">Could not load conversations.</div>';
		return;
	}
	const items = d.items || [];
	if (!items.length) {
		list.innerHTML =
			'<div class="eye-list-empty">No conversations yet. Ask something to start one.</div>';
		return;
	}
	const current = chat && chat.chat ? chat.chat.id : null;
	list.innerHTML =
		'<div class="eye-list-head">Conversations</div>' +
		items
			.map(
				(c) =>
					'<button class="eye-thread" role="button" aria-current="' +
					(c.id === current ? "true" : "false") +
					'" onclick="openEye(\'' +
					c.id +
					"')\">" +
					'<span class="t-title">' +
					esc(c.title || "Conversation") +
					"</span>" +
					'<span class="t-forget" role="button" aria-label="Delete ' +
					esc(c.title || "conversation") +
					'" onclick="event.stopPropagation();dropChat(\'' +
					c.id +
					"')\">" +
					svg("trash") +
					"</span>" +
					"</button>",
			)
			.join("");
}

function renderChat(d) {
	// The scope is a constraint, not a subtitle. Rendered as metadata it read like a
	// caption, and a chat silently locked to one empty link answered "nothing you have
	// saved" to a question the app could answer instantly. Say what it can see, and
	// put the way out next to it.
	const scoped = d.chat.scope_kind !== "everything";
	// Side and corner shape carry the speaker, so there are no name labels under the
	// bubbles. A label on every turn is a thing to read that says nothing.
	const chip = (kind, id, label, handler) =>
		'<button class="src" data-kind="' +
		esc(kind || "") +
		'" onclick="' +
		handler +
		"('" +
		esc(id) +
		"')\">" +
		(kind ? '<span class="kindmark"></span>' : "") +
		esc(label) +
		"</button>";

	// The view rebuilds every render. Drop only the cached turns whose message is
	// no longer in the transcript - the rest keep their prior /pivot/run result so
	// a transcript change elsewhere does not re-fire every organize turn (P.3c).
	const nextTurns = {};
	for (const m of d.messages)
		if (
			m.kind === "organize" &&
			m.role === "assistant" &&
			m.id in organizeTurns
		)
			nextTurns[m.id] = organizeTurns[m.id];
	organizeTurns = nextTurns;

	// The panel's own header carries the title and the controls now, so the
	// transcript is only turns. Title and scope are set on the chrome, not drawn
	// into the scroll region.
	const titleEl = document.getElementById("eyeTitle");
	if (titleEl) titleEl.textContent = d.chat.title || "Conversation";
	const scopeEl = document.getElementById("eyeScope");
	if (scopeEl) {
		if (scoped) {
			scopeEl.hidden = false;
			scopeEl.innerHTML =
				'<span>reading only</span>' +
				chip("", d.chat.scope_id, d.chat.scope_label, "showArtifact");
		} else {
			scopeEl.hidden = true;
			scopeEl.innerHTML = "";
		}
	}

	let html = "";
	for (const m of d.messages) {
		// A typed turn (S4): `answer` (and any unknown kind, defensively) renders
		// exactly as today; `organize` renders its label in the bubble and the
		// grouped view below it, hydrated from the stored spec.
		const organize = m.kind === "organize" && m.role === "assistant";
		// Phase H: the pending turn is a real stored message, not a fake drawn on
		// top. It renders as a thinking bubble the poller refreshes until the
		// worker fills it in; a failed turn shows its reason with a way to ask
		// again (H4.1).
		const pending = m.status === "pending" && m.role === "assistant";
		const failed = m.status === "failed" && m.role === "assistant";
		html +=
			'<div class="turn ' +
			(m.role === "user" ? "you" : "assistant") +
			'">' +
			'<div class="said md">' +
			(m.role === "user"
				? esc(m.text)
				: pending
					? eyeLoader()
					: md(m.text));
		const echoes =
			d.chat.scope_kind === "artifact" &&
			m.cited &&
			m.cited.length === 1 &&
			m.cited[0].artifact_id === d.chat.scope_id;

		// The evidence lives inside the bubble it supports. Outside it, it was a
		// footnote under the most important thing on the page.
		if (m.cited && m.cited.length && !echoes)
			html +=
				'<div class="from">' +
				m.cited
					.map((c) => chip(c.kind, c.artifact_id, c.title, "showArtifact"))
					.join("") +
				"</div>";
		else if (
			!pending &&
			!failed &&
			m.role === "assistant" &&
			!m.grounded &&
			!organize
		)
			html +=
				'<div class="unsourced">Nothing you have saved carried this.</div>';

		// The failed turn is honest about why (Rule 2), and the way out is one
		// click: the cause with a path to the fix when the worker stored one
		// (CR.2), and ask the same question again as a fresh turn (H4.4).
		if (failed) {
			if (m.error)
				html +=
					'<div class="cause">' +
					esc(m.error) +
					' <button class="btn ghost" onclick="showSettings()">Check Settings</button></div>';
			html +=
				'<button class="btn ghost" onclick="retryTurn(\'' +
				esc(m.id) +
				"')\">Try again</button>";
		}
		html += "</div>";

		// The grouped view is not stored in the turn's text: it re-runs the stored
		// spec (S4.2), so a reload shows the same groups without re-planning. The
		// slot starts as a placeholder and hydrates right after this render.
		if (organize)
			html +=
				'<div class="org" id="org-' +
				esc(m.id) +
				'">' +
				spinner("sm", "Building the view...") +
				"</div>";
		html += "</div>";
	}

	const body = document.getElementById("eyeBody");
	body.innerHTML = html;
	// Transcript is the live view; the conversations list is put away whenever a
	// chat renders, so answering always returns you to the thread you asked in.
	showTranscript();
	for (const m of d.messages)
		if (m.kind === "organize" && m.role === "assistant" && m.payload)
			hydrateOrganize(m, d);
	body.scrollTop = body.scrollHeight;
}

// ---- typed turns: the in-chat organize view -------------------------------
// The organize turns currently on screen: message id -> {d (last run), spec,
// userText}. They reuse the same run endpoint and the same group markup as the
// standalone pivot; only the home differs. A correction re-runs the turn's own
// spec, cheap because every derive call is cached.
let organizeTurns = {};

// Re-run a turn's stored spec and fill its slot. One run endpoint, no fork: the
// same POST /pivot/run the standalone pivot used. Only turns whose spec
// actually changed re-fire the run (P.3c): a poll that flipped some other
// turn's status (or appended a new typed answer) re-renders the transcript,
// but every unchanged organize turn hydrates from the prior run instead of a
// fresh /pivot/run call.
function hydrateOrganize(m, d) {
	const slot = document.getElementById("org-" + m.id);
	if (!slot) return;
	const idx = d.messages.indexOf(m);
	const userText =
		idx > 0 && d.messages[idx - 1].role === "user"
			? d.messages[idx - 1].text
			: m.text;

	const cached = organizeTurns[m.id];
	if (cached && JSON.stringify(cached.spec) === JSON.stringify(m.payload)) {
		// The spec is unchanged: keep the prior /pivot/run result (refresh the
		// userText in case the prior turn was edited without touching the spec).
		organizeTurns[m.id] = { d: cached.d, spec: cached.spec, userText };
		slot.innerHTML = organizeSlotHtml(m.id);
		mountCollapsible(
			".pivotgroup",
			"enqueue.collapsedGroups." + specHash(m.payload),
		);
		return;
	}

	api("/pivot/run", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ spec: m.payload }),
	})
		.then((result) => {
			organizeTurns[m.id] = { d: result, spec: m.payload, userText };
			slot.innerHTML = organizeSlotHtml(m.id);
			mountCollapsible(
				".pivotgroup",
				"enqueue.collapsedGroups." + specHash(m.payload),
			);
		})
		.catch((err) => {
			slot.innerHTML =
				'<div class="state">That view could not be re-run: ' +
				esc(String((err && err.message) || err)) +
				".</div>";
		});
}

// The turn's groups plus its controls (Rule 2: the routing is declared - the
// label is in the bubble - and reversible - "Answer instead" is always here).
function organizeSlotHtml(mid) {
	const st = organizeTurns[mid];
	if (!st) return "";
	// The actions sit at the top of the turn's result (K.8), above the first
	// group: they act on the whole grouping, and a person reads the actions
	// before the cards. The buttons stay ghost - they are reversible.
	return (
		'<div class="org-actions">' +
		'<button class="btn ghost" onclick="saveGrouping(\'' +
		mid +
		"')\">Save view</button>" +
		'<button class="btn ghost" onclick="chatAddArtifactToTurn(\'' +
		mid +
		"')\">Add artifact</button>" +
		'<button class="btn ghost" onclick="answerInstead(\'' +
		mid +
		"')\">Answer instead</button>" +
		"</div>" +
		pivotGroupsHtml(
			st.d,
			(id) => "onclick=\"chatPivotMove('" + mid + "','" + esc(id) + "')\"",
			// The turn has no saved pivot to remove from: no remove control (the
			// null keeps it out), and the spec rides in its own slot so the
			// collapsed-set keying works - it was landing in makeRemove before,
			// which called the spec object as a function on every card.
			null,
			st.spec,
			null,
		)
	);
}

// Keep this arrangement: name the spec that produced the turn and store it, so
// the grid button can re-open and re-run it live. The spec is the recipe, not a
// snapshot - naming is the only text a person types; grouping never prompts.
async function saveGrouping(mid) {
	const st = organizeTurns[mid];
	if (!st) return;
	const name = await askGroupName(
		"Name this view",
		"e.g. By author region",
		"Save",
	);
	if (!name) return;
	try {
		await api("/pivots", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ name, spec: st.spec }),
		});
	} catch (err) {
		return toast(String((err && err.message) || err), true);
	}
	toast('Saved as "' + name + '". Open it under Custom on the wall.');
}

// Correct a misfiled card inside a chat organize turn: write a user override on
// the grouping attribute for this one artifact, then re-run the turn's own spec
// so the card lands where the person put it. The override always wins on read,
// so the move survives every later re-run (S4.4).
async function chatPivotMove(mid, id) {
	const st = organizeTurns[mid];
	if (!st) return;
	const target = await chooseMoveGroup(st.d, id);
	if (target === null) return;

	const slot = document.getElementById("org-" + mid);
	if (!slot) return;
	slot.innerHTML = spinner("sm", "moving it...");
	try {
		st.d = await api("/pivot/run", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ spec: st.spec }),
		});
	} catch (err) {
		slot.innerHTML =
			'<div class="state">That view could not be re-run: ' +
			esc(String((err && err.message) || err)) +
			".</div>";
		return;
	}
	slot.innerHTML = organizeSlotHtml(mid);
	toast("Moved to " + (target || "Not determined") + ".");
}

// Rule 2's way back, in one click: re-send the same words forcing `answer`
// (the dispatcher's force_skill), appending a fresh answer turn below.
function answerInstead(mid) {
	const st = organizeTurns[mid];
	if (!st || !chat) return;
	sendInChat(st.userText, "answer");
}

// A conversation is scaffolding around the collection, not part of it, so this
// removes it outright rather than sending it to the trash: there is no original to
// recover, and the artifacts it cited are untouched either way.
async function dropChat(id) {
	const row = document.querySelector('.eye-thread[onclick*="' + id + '"] .t-title');
	const name = row ? row.textContent.trim() : "this conversation";
	const yes = await ask(
		"Delete this conversation?",
		name + " will be removed. The artifacts it cited stay where they are.",
		"Delete",
	);
	if (!yes) return;

	try {
		await api("/chats/" + id, { method: "DELETE" });
	} catch (err) {
		return toast("Not deleted. " + String(err.message || err), true);
	}
	toast("Conversation deleted.");
	// Deleting the open thread drops back to a fresh conversation; deleting one from
	// the list just refreshes the list in place. Either way the panel stays open.
	const wasOpen = chat && chat.chat && chat.chat.id === id;
	if (!document.getElementById("eyeList").hidden) {
		if (wasOpen) chat = null;
		return showConversations();
	}
	if (wasOpen) newConversation();
}

// ---- saved groupings: the grid button's home -----------------------------
// A saved grouping is an arrangement's recipe (the spec), not a frozen result.
// Opening one re-runs it live, so a note captured since it was saved lands in
// its group - the arrangement stays true as the library grows. The grid button
// opens this list; a row runs its grouping; the small cross forgets it.
async function showSavedGroupings() {
	teardown();
	// A sub-view, not the wall: show the inside pill so Home is a way out. This is
	// the bug fix - an empty saved-groupings list was a dead end with no way back.
	restorePill("inside");
	setRoute("g");
	const list = await api("/pivots").catch(() => ({ items: [] }));
	let html = '<div class="shelf">Saved views</div>';
	if (!list.items.length) {
		html +=
			'<div class="aside">Nothing saved yet. Ask the eye to organize your ' +
			"notes, then save the view you want to keep.</div>";
	} else {
		html +=
			'<div class="wall">' +
			list.items
				.map(
					(p) =>
						'<div class="card" data-pivot="' +
						p.id +
						'" tabindex="0" role="button" onclick="runSavedGrouping(\'' +
						p.id +
						"','" +
						esc(p.name).replace(/'/g, "\\'") +
						"')\">" +
						'<div style="padding:24px 16px">' +
						'<div class="title">' +
						esc(p.name) +
						"</div>" +
						'<button class="title-action" aria-label="Rename ' +
						esc(p.name) +
						'" title="Rename this view" onclick="renameSavedGrouping(event,\'' +
						p.id +
						"')\">" +
						svg("pencil") +
						"</button>" +
						'<button class="movebtn" aria-label="Forget ' +
						esc(p.name) +
						'" onclick="forgetSavedGrouping(event,\'' +
						p.id +
						"')\">forget</button>" +
						"</div></div>",
				)
				.join("") +
			"</div>";
	}
	view.innerHTML = html;
}

// Run a saved grouping: fetch its spec, run it live, and render it in the same
// standalone pivot view (renderPivot) the planner produced - so a move works
// through the same path. The saved name stands in for the words that planned it.
async function runSavedGrouping(id, name) {
	teardown();
	restorePill("inside");
	setRoute("g/" + id);
	view.innerHTML = spinner("lg", "Building the view...");
	// /open serves the cached grouping instantly when the view has been run before,
	// and computes + caches it on the first open. The expensive model judgments are
	// what the cache skips, so a re-open is immediate.
	let opened;
	try {
		opened = await api("/pivots/" + id + "/open");
	} catch (err) {
		return pivotFailed(err);
	}
	// A saved view is LOCKED: once materialized it never auto-recomputes, so CRUD on the
	// library (new captures, edits, deletes) never disturbs it and opening is always
	// instant. New artifacts are pulled in only by an explicit Rebuild (the button in
	// the header), which re-runs the spec and re-freezes the result.
	renderPivot(opened.result, name || opened.name, opened.spec, opened.id);
}

async function forgetSavedGrouping(ev, id) {
	if (ev) ev.stopPropagation();
	try {
		await api("/pivots/" + id, { method: "DELETE" });
	} catch (err) {
		return toast(String((err && err.message) || err), true);
	}
	toast("View forgotten.");
	// If the forget happened inside the saved-groupings modal (L.5), refresh its
	// list in place; otherwise re-render the saved-groupings sub-view.
	const picker = document.querySelector("dialog.ask #customPickerList");
	if (picker && picker.closest("dialog").open) {
		await refreshCustomPicker();
		return;
	}
	showSavedGroupings();
}

// ---- the panel composer --------------------------------------------------
// The footer field is static markup in home.html; these drive it. The field grows
// with its content up to a cap, the send action is dead until there is something to
// send, and Enter sends while Shift+Enter makes a newline.
function focusField() {
	const f = document.getElementById("eyeField");
	if (f) f.focus();
}

function setField(v) {
	const f = document.getElementById("eyeField");
	if (!f) return;
	f.value = v || "";
	autoGrowField();
}

function autoGrowField() {
	const f = document.getElementById("eyeField");
	if (!f) return;
	f.style.height = "auto";
	f.style.height = Math.min(f.scrollHeight, 140) + "px";
	const send = document.getElementById("eyeSend");
	if (send) send.disabled = !f.value.trim();
}

// The form's submit handler (Enter, or the send button).
function eyeSend(e) {
	if (e && e.preventDefault) e.preventDefault();
	const f = document.getElementById("eyeField");
	const v = (f.value || "").trim();
	if (!v) return false;
	setField("");
	// No chat row yet means this is the first turn of a fresh conversation.
	if (chat && chat.chat) sendInChat(v);
	else startChat(v);
	return false;
}

async function sendInChat(text, skill) {
	const id = chat.chat.id;
	let d;
	try {
		// Submitting returns immediately with a pending turn; the worker computes
		// the answer off the request thread. Nothing here awaits the model (H4.2).
		d = await api("/chats/" + id + "/messages", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			// `skill` forces a route (Rule 2's "answer instead"). JSON.stringify
			// drops an undefined value, so a plain send carries no skill at all.
			body: JSON.stringify({ text, skill }),
		});
	} catch (err) {
		chat = await api("/chats/" + id);
		renderChat(chat);
		toast(String(err.message || err), true);
		return;
	}
	chat = d;
	renderChat(d);
	focusField();
	// The turn is pending; the poller watches it resolve and stops when done.
	startPolling(id);
}

// ---- pending turns: the poller that watches them resolve -----------------
// A submitted answer is computed after the request has returned. While any turn
// in the open chat is pending, one poller re-reads the transcript every couple
// of seconds and re-renders on change; it stops when none are pending. Leaving
// the surface cancels it (teardown), so a stale poller never redraws a screen
// it no longer owns, and opening a different chat starts its own.
let pollTimer = null;
let pollChatId = null;
// UIUX.4: back off from 2s toward 8s while a turn stays pending, so a slow
// answer stops re-fetching the whole transcript every 2s. Reset on each start.
const POLL_MIN = 2000;
const POLL_MAX = 8000;
let pollDelay = POLL_MIN;

function stopPolling() {
	clearTimeout(pollTimer);
	pollTimer = null;
	pollChatId = null;
	pollDelay = POLL_MIN;
}

function hasPending(d) {
	return (d.messages || []).some((m) => m.status === "pending");
}

function startPolling(id) {
	// One poller per chat: opening a different surface (or a different chat)
	// cancels the old one before the new one starts.
	if (pollChatId !== id) stopPolling();
	if (pollTimer) return;
	pollChatId = id;
	pollDelay = POLL_MIN;
	pollTimer = setTimeout(pollTick, pollDelay);
}

async function pollTick() {
	const id = pollChatId;
	if (!id) return;
	let d;
	try {
		d = await api("/chats/" + id);
	} catch (err) {
		// The chat is gone (deleted while we waited): stop, don't thrash.
		stopPolling();
		return;
	}
	if (pollChatId !== id) return; // canceled while the fetch was in flight
	const open = chat && chat.chat.id === id;
	if (open && transcriptChanged(chat, d)) {
		chat = d;
		renderChat(d);
	}
	if (hasPending(d)) {
		pollDelay = Math.min(pollDelay * 1.5, POLL_MAX);
		pollTimer = setTimeout(pollTick, pollDelay);
	} else stopPolling();
}

// Re-render only when the transcript actually moved: a poller that redraws the
// whole view on an unchanged tick would yank a person who scrolled up to read
// back to the bottom every two seconds.
function transcriptChanged(a, b) {
	if (!a || !b) return true;
	if (a.chat.title !== b.chat.title) return true;
	if ((a.topics || []).length !== (b.topics || []).length) return true;
	if (a.messages.length !== b.messages.length) return true;
	return a.messages.some((m, i) => {
		const n = b.messages[i];
		return (
			m.id !== n.id ||
			m.status !== n.status ||
			m.text !== n.text ||
			m.kind !== n.kind ||
			m.grounded !== n.grounded
		);
	});
}

// A failed turn's way back: ask the same question again as a fresh turn. The
// text is the user message that preceded the failed turn - the question it was
// answering (H4.4).
function retryTurn(mid) {
	if (!chat) return;
	const idx = chat.messages.findIndex((m) => m.id === mid);
	if (idx < 1) return;
	const prev = chat.messages[idx - 1];
	if (prev.role !== "user") return;
	sendInChat(prev.text);
}

// ---- boot the panel composer ---------------------------------------------
// The footer field is static in home.html, so it exists as soon as this script
// runs (scripts sit at the end of <body>). Grow-on-type, Enter to send, Shift+Enter
// for a newline. The form's submit handler (eyeSend) covers the send button.
(function bootEyeComposer() {
	const f = document.getElementById("eyeField");
	if (!f) return;
	f.addEventListener("input", autoGrowField);
	f.addEventListener("keydown", (e) => {
		if (e.key === "Enter" && !e.shiftKey) {
			e.preventDefault();
			eyeSend(e);
		}
	});
})();
