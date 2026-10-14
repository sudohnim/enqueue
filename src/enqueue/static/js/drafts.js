// A note's drafts (desktop): the list, what changed since one, and going back to it.
//
// The quiet "12 drafts" under a note opens the list in the Details plate (a second
// `.drawer.dpanel`, like the settings guide). Choosing a draft turns the note's sheet
// into a comparison: the note as it is now with what was added since that draft and
// what was removed marked inside it (js/diff.js), or the draft as it was. Restore puts
// it back; the engine keeps today's text as a draft first (drafts.restore), so going
// back never loses anything. The editor is hidden, never rebuilt, while comparing, so
// nothing can be typed into or saved from a draft.
//
// The engine side is src/enqueue/drafts.py; what is kept is its policy.

let draftsState = null; // {id, drafts, keep, selected, mode, body}

function draftsCountLabel(n) {
	return n > 1 ? n + " drafts" : "";
}

function draftsDay(when) {
	const d = new Date(when);
	const today = new Date();
	const y = new Date();
	y.setDate(today.getDate() - 1);
	if (d.toDateString() === today.toDateString()) return "Today";
	if (d.toDateString() === y.toDateString()) return "Yesterday";
	const sameYear = d.getFullYear() === today.getFullYear();
	return d.toLocaleDateString(undefined, {
		month: "short",
		day: "numeric",
		...(sameYear ? {} : { year: "numeric" }),
	});
}

function draftsTime(when) {
	return new Date(when).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function draftsPanel() {
	let panel = document.getElementById("draftsPanel");
	if (panel) return panel;
	panel = document.createElement("aside");
	panel.id = "draftsPanel";
	panel.className = "drawer dpanel drafts";
	panel.setAttribute("aria-label", "Drafts");
	panel.innerHTML =
		'<div class="dpanel-top">' +
		'<img class="dpanel-perch" src="/static/raven-tilt.png" alt="" aria-hidden="true">' +
		'<div class="dpanel-heading"><span class="dpanel-title">Drafts</span>' +
		'<span class="dpanel-voice">Every version is still here.</span></div>' +
		'<button type="button" class="dpanel-close" aria-label="Close drafts" title="Close drafts">' +
		svg("close") +
		"</button></div>" +
		'<div class="dpanel-body" id="draftsBody"></div>';
	view.appendChild(panel);
	panel.querySelector(".dpanel-close").addEventListener("click", () => closeDrafts());
	panel.addEventListener("click", (e) => {
		const row = e.target.closest(".draft-row");
		if (row && row.dataset.draft) return compareDraft(row.dataset.draft);
		if (e.target.closest(".draft-keep")) setKeepDrafts(!draftsState.keep);
	});
	return panel;
}

async function openDrafts(select) {
	if (!ctx || ctx.kind !== "note") return;
	// One plate at a time: the Details panel steps aside.
	if (typeof toggleDrawer === "function") toggleDrawer(false);
	const id = ctx.id;
	let data;
	try {
		data = await api("/artifacts/" + id + "/drafts");
	} catch (err) {
		return toast(String((err && err.message) || err), true);
	}
	if (!ctx || ctx.id !== id) return;
	draftsState = { id, drafts: data.drafts, keep: data.keep, selected: null, mode: "changes", body: null };
	const panel = draftsPanel();
	renderDraftsList();
	const arriving = !panel.classList.contains("open");
	requestAnimationFrame(() => {
		panel.classList.add("open");
		if (arriving) Details.arrive(panel);
	});
	const link = document.getElementById("vers");
	if (link) link.setAttribute("aria-expanded", "true");
	if (select) compareDraft(select);
	else panel.querySelector(".dpanel-close").focus({ preventScroll: true });
}

function closeDrafts() {
	endCompare();
	const panel = document.getElementById("draftsPanel");
	draftsState = null;
	const link = document.getElementById("vers");
	if (link) {
		link.setAttribute("aria-expanded", "false");
		link.focus({ preventScroll: true });
	}
	if (!panel) return;
	panel.classList.remove("open");
	setTimeout(() => {
		if (!draftsState) panel.remove();
	}, 320);
}

function draftsOpen() {
	const panel = document.getElementById("draftsPanel");
	return !!(panel && panel.classList.contains("open"));
}

function renderDraftsList() {
	const body = document.getElementById("draftsBody");
	if (!body || !draftsState) return;
	const s = draftsState;
	let html = "";
	let day = null;
	s.drafts.forEach((d, i) => {
		const now = i === 0 && d.current;
		if (!now) {
			const label = draftsDay(d.at);
			if (label !== day) {
				day = label;
				html += '<div class="draft-day">' + esc(label) + "</div>";
			}
		}
		const isFirst = i === s.drafts.length - 1;
		const words = now ? "" : isFirst ? "First draft" : d.first || "Spacing only";
		html +=
			'<button type="button" class="draft-row' +
			(now ? " now" : "") +
			'"' +
			(now ? " disabled" : ' data-draft="' + esc(d.id) + '"') +
			' aria-pressed="' +
			String(s.selected === d.id) +
			'"><span class="draft-time">' +
			(now ? "Now" : esc(draftsTime(d.at))) +
			'</span><span class="draft-words">' +
			esc(now ? "The note as it is" : words) +
			'</span><span class="draft-delta">' +
			(now || isFirst
				? ""
				: (d.added ? '<span class="plus">+' + d.added + "</span>" : "") +
					(d.removed ? '<span class="minus">−' + d.removed + "</span>" : "")) +
			"</span></button>";
	});
	if (s.drafts.length < 2)
		html +=
			'<p class="draft-empty">' +
			(s.keep
				? "A new draft is kept as you write: one for each few minutes of writing, and how the note began."
				: "Drafts are off for this note, so only its latest text is kept.") +
			"</p>";
	html +=
		'<div class="draft-switch"><span><b>Keep drafts of this note</b><small>' +
		(s.keep ? "Kept by the library's setting, in Settings, Storage." : "Off: edits replace the text, no history.") +
		'</small></span><button type="button" class="toggle summary-switch draft-keep" role="switch" aria-checked="' +
		String(s.keep) +
		'" aria-label="Keep drafts of this note"><span class="knob"></span></button></div>';
	body.innerHTML = html;
}

async function setKeepDrafts(on) {
	const s = draftsState;
	if (!s) return;
	if (!on && s.drafts.length > 1) {
		const yes = await ask(
			"Stop keeping drafts of this note?",
			"Its " + (s.drafts.length - 1) + " earlier drafts are removed. Only the note as it is now stays.",
			"Stop and remove them",
		);
		if (!yes) return renderDraftsList();
	}
	try {
		await api("/artifacts/" + s.id + "/drafts/keep", {
			method: "PUT",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ on }),
		});
	} catch (err) {
		return toast(String((err && err.message) || err), true);
	}
	endCompare();
	await openDrafts();
	const data = draftsState && draftsState.drafts;
	const link = document.getElementById("vers");
	if (link && data) {
		link.dataset.n = data.length;
		link.textContent = draftsCountLabel(data.length);
	}
}

// ---- comparing --------------------------------------------------------------------

async function compareDraft(vid) {
	const s = draftsState;
	if (!s) return;
	let draft;
	try {
		draft = await api("/artifacts/" + s.id + "/drafts/" + encodeURIComponent(vid));
	} catch (err) {
		return toast(String((err && err.message) || err), true);
	}
	if (!draftsState || draftsState.id !== s.id) return;
	s.selected = vid;
	s.body = draft.body;
	renderDraftsList();
	renderCompare();
}

function renderCompare() {
	const s = draftsState;
	const sheet = document.querySelector(".docpane.notesheet");
	const ed = document.getElementById("body");
	if (!s || !s.selected || !sheet || !ed) return;
	const now = noteText(ed);
	const entry = s.drafts.find((d) => d.id === s.selected);
	sheet.classList.add("comparing");
	let head = sheet.querySelector(".compare");
	if (!head) {
		head = document.createElement("div");
		head.className = "compare";
		sheet.insertBefore(head, sheet.firstChild);
		head.addEventListener("click", (e) => {
			const b = e.target.closest("button");
			if (!b) return;
			if (b.dataset.mode) {
				draftsState.mode = b.dataset.mode;
				renderCompare();
			} else if (b.dataset.act === "done") endCompare(true);
			else if (b.dataset.act === "restore") restoreDraft();
		});
	}
	const when = entry ? draftsDay(entry.at) + ", " + draftsTime(entry.at) : "This draft";
	head.innerHTML =
		'<span class="compare-what"><b>' +
		esc(when) +
		"</b>" +
		(s.mode === "changes" ? " compared with now" : " as it was") +
		'</span><span class="compare-seg" role="group" aria-label="Show">' +
		'<button type="button" data-mode="changes" aria-pressed="' +
		String(s.mode === "changes") +
		'">Changes</button><button type="button" data-mode="was" aria-pressed="' +
		String(s.mode === "was") +
		'">As it was</button></span>' +
		'<button type="button" class="btn ghost sm" data-act="done">Done</button>' +
		'<button type="button" class="btn primary sm" data-act="restore">Restore</button>';
	let pane = sheet.querySelector(".diffview");
	if (!pane) {
		pane = document.createElement("div");
		pane.className = "diffview md notetype";
		pane.setAttribute("aria-live", "polite");
		ed.after(pane);
	}
	if (s.mode === "was") pane.innerHTML = md(s.body || "");
	else if (Diff.same(s.body, now))
		pane.innerHTML = '<p class="diff-none">No change since this draft.</p>' + md(now);
	else pane.innerHTML = Diff.html(s.body, now, md);
	pane.scrollTop = 0;
}

function endCompare(keepList) {
	const sheet = document.querySelector(".docpane.notesheet");
	if (sheet) {
		sheet.classList.remove("comparing");
		sheet.querySelector(".compare")?.remove();
		sheet.querySelector(".diffview")?.remove();
	}
	if (draftsState) {
		draftsState.selected = null;
		draftsState.mode = "changes";
		draftsState.body = null;
		if (keepList) renderDraftsList();
	}
}

async function restoreDraft() {
	const s = draftsState;
	if (!s || !s.selected) return;
	const id = s.id;
	try {
		await api("/artifacts/" + id + "/drafts/" + encodeURIComponent(s.selected) + "/restore", {
			method: "POST",
		});
	} catch (err) {
		return toast(String((err && err.message) || err), true);
	}
	await showArtifact(id);
	await openDrafts();
	toast("Restored. The text it replaced is kept as a draft.");
}

// Escape leaves the comparison first, then the list.
document.addEventListener(
	"keydown",
	(e) => {
		if (e.key !== "Escape" || !draftsOpen()) return;
		if (e.target.closest && e.target.closest("input, textarea, [contenteditable='true']") && !draftsState?.selected)
			return;
		e.stopPropagation();
		if (draftsState && draftsState.selected) endCompare(true);
		else closeDrafts();
	},
	true,
);
