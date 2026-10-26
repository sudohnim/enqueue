// Which artifacts have a picture of their own. Those fill the card and take a band
// across the foot for the title; everything else is set as type inside the square.
function facePicture(a) {
	const drop = ' onerror="this.remove()"';
	if (a.kind === "image")
		return (
			'<img src="/artifacts/' +
			a.id +
			'/blob" alt="" loading="lazy"' +
			drop +
			">"
		);
	if (a.kind === "pdf")
		return (
			'<img src="/artifacts/' +
			a.id +
			'/page/0?width=520" alt="" loading="lazy"' +
			drop +
			">"
		);
	if (a.kind === "link" && a.has_preview_image)
		return (
			'<img src="/artifacts/' +
			a.id +
			'/preview-image" alt="" loading="lazy"' +
			drop +
			">"
		);
	// A note that pasted in an image: the server hands us the first embedded blob src
	// so the card shows the picture instead of a blank preview. `onerror` drops it if
	// the referenced blob is gone, so the card falls back to plain type.
	if (a.face_image)
		return (
			'<img src="' + a.face_image + '" alt="" loading="lazy"' + drop + ">"
		);
	return null;
}

// The dot is a graphic and answers to 3:1; the word beside it carries the meaning and
// answers to 4.5:1 in ink. Neither travels without the other, so no piece of
// information on the wall is carried by colour alone.
const kindRow =
	'<span class="kindrow"><span class="kindmark"></span>' +
	'<span class="kindword">';

// ---- wall grouping (K.6) ------------------------------------------------
// The mode decides how the fetched cards are arranged under the home header.
// Type and Tags regroup the same rows client-side (no refetch, no model
// calls); Custom swaps the body for the saved-groupings list, which lives on
// the server, so that one mode fetches /pivots.

function groupBarHtml() {
	const labels = [
		["touched", "Last touch"],
		["type", "Type"],
		["tags", "Tags"],
		["custom", "Custom"],
	];
	return (
		'<div class="groupbar" role="group" aria-label="Group the wall by">' +
		labels
			.map(
				([mode, label]) =>
					'<button type="button" aria-pressed="' +
					(wallGroup === mode ? "true" : "false") +
					'" data-mode="' +
					mode +
					'">' +
					label +
					"</button>",
			)
			.join("") +
		"</div>"
	);
}

// The wall body for the client-side modes: one arrangement over the same
// fetched cards. Last touch keeps the flat wall - the saved shelf, then
// everything else with the pager foot. Type and Tags group every card into
// sections, kept and fresh together; the pin flag still marks the kept ones.
function wallBodyHtml() {
	const cards = wallKept.concat(wallFirst);
	// Q.2: a fresh library has no guidance - show an empty state in every
	// wall mode instead of empty SAVED / EVERYTHING ELSE sections.
	if (!wallKept.length && !wallFirst.length) {
		return (
			'<div class="state" style="padding: var(--sp-7) var(--sp-4); text-align: center;">' +
			'<div class="shelf" style="margin-bottom: var(--sp-3)">Nothing captured yet</div>' +
			'<div class="aside">Press the + below to capture a note, a link, or a file.</div>' +
			"</div>"
		);
	}
	if (wallGroup === "type") return wallSectionsHtml(kindSections(cards));
	if (wallGroup === "tags") return wallSectionsHtml(tagSections(cards));
	// Last touch: the saved shelf and the pager wall render as the same
	// collapsible .wallgroup sections the Type/Tags modes use, so the header
	// control (toggle + count + chevron) reads identically across modes.
	const sections = [];
	if (wallKept.length) sections.push(["Saved", wallKept, true]);
	sections.push(["Everything else", wallFirst, false]);
	return wallSectionsHtml(sections);
}

// The kind order the wall itself uses: notes first, then the rest of the
// type filter, conversations last. Unknown kinds (none today) append at the
// end under their own name rather than disappearing.
const KIND_SHELVES = [
	["note", "Notes"],
	["link", "Links"],
	["pdf", "PDFs"],
	["image", "Images"],
	["file", "Files"],
	["chat", "Conversations"],
];

function kindSections(items) {
	const byKind = {};
	for (const a of items) {
		(byKind[a.kind] ||= []).push(a);
	}
	const sections = KIND_SHELVES.filter(([k]) => byKind[k]).map(([k, label]) => [
		label,
		byKind[k],
	]);
	for (const k of Object.keys(byKind)) {
		if (!KIND_SHELVES.some(([kk]) => kk === k)) sections.push([k, byKind[k]]);
	}
	return sections;
}

// Tags are multi-valued, so one artifact can sit under several shelves. The
// shelves run in tag-count order (most-tagged first, names tie-broken), and
// whatever carries no tag lands in an Untagged shelf at the end.
function tagSections(items) {
	const byTag = new Map();
	const untagged = [];
	for (const a of items) {
		if (!a.tags || !a.tags.length) {
			untagged.push(a);
			continue;
		}
		for (const t of a.tags) {
			if (!byTag.has(t)) byTag.set(t, []);
			byTag.get(t).push(a);
		}
	}
	const shelves = [...byTag.entries()].sort(
		(a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]),
	);
	const sections = shelves.map(([t, list]) => ["#" + t, list]);
	if (untagged.length) sections.push(["Untagged", untagged]);
	return sections;
}

// Wall sections in every mode (L.4): each shelf is a collapsible section, the
// same shape as a pivot group - a toggle header (label + count + chevron)
// folding its cards away. Collapsed choices persist per mode in
// sessionStorage, so a mode switch and switch back keeps the folds. A section
// entry may carry a third flag for the last-touch SAVED shelf, which gets the
// saved styling and no pager end-marker; the pager shelf carries the wall
// id/end-marker instead.
function wallSectionsHtml(sections) {
	const collapsed = collapsedSet("enqueue.collapsedWall." + wallGroup);
	return sections
		.map(([label, list, isSaved]) => {
			const key = label;
			const isCollapsed = collapsed.has(key);
			return (
				'<section class="wallgroup' +
				(isCollapsed ? " collapsed" : "") +
				'" data-key="' +
				esc(key) +
				'">' +
				'<button class="grouptoggle" type="button" aria-expanded="' +
				String(!isCollapsed) +
				'" title="' +
				esc(isCollapsed ? groupPreview(list) : "") +
				// Left, not centered: this label heads a left-aligned card grid, and a
				// centered label over left-aligned content reads as a mismatch. The count
				// and chevron keep the right edge, so the row still spans the wall.
				'"><span class="shelf">' +
				esc(label) +
				'</span><span class="gmeta">' +
				list.length +
				'</span><span class="gchev" aria-hidden="true">' +
				svg("chev") +
				"</span></button>" +
				'<div class="wall' +
				(isSaved ? " wall--saved" : "") +
				(isSaved ? "" : '" id="wall') +
				'">' +
				list.map((a, i) => card(a, i)).join("") +
				"</div>" +
				(isSaved ? "" : '<div id="wallEnd" class="aside"></div>') +
				"</section>"
			);
		})
		.join("");
}

// ---- collapsible section headers (L.4/K.10) ----------------------------
// The wall's Type/Tags shelves and the pivot groups both fold their sections;
// they share everything except the sessionStorage key and the section
// selector, so one keyed pair of helpers backs both. The wall keys on the
// mode, the pivot on a stable hash of the recipe (specHash), so the same
// re-run preserves the folds while a different grouping starts open.
function collapsedSet(key) {
	try {
		return new Set(JSON.parse(sessionStorage.getItem(key) || "[]"));
	} catch (_) {
		return new Set();
	}
}

function saveCollapsed(key, set) {
	try {
		sessionStorage.setItem(key, JSON.stringify([...set]));
	} catch (_) {
		// Storage unavailable (private mode, quota): collapsing still works for
		// this render, it just does not survive a re-run or a mode switch.
	}
}

// Bind the collapsible section headers after a Type/Tags wall or a pivot
// grouping renders. The sections live under `view`.
function mountCollapsible(sectionSel, storageKey) {
	// N.10b: one listener per toggle, not delegation - a wall or pivot run
	// yields at most ~10 sections, so the listener count is trivially small,
	// and `view` is a reused container where a persistent delegation listener
	// would need its own teardown lifecycle.
	const collapsed = collapsedSet(storageKey);
	// Each Type/Tags switch rebuilds `#wallbody` via innerHTML (setWallGroup), so
	// these toggles are fresh nodes every time and listeners cannot stack - bind
	// directly. (An earlier clone-replace guard here was pure DOM churn against an
	// already-fresh tree and showed up as switch lag.)
	view.querySelectorAll(sectionSel + " .grouptoggle").forEach((btn) => {
		btn.addEventListener("click", () => {
			const section = btn.closest(sectionSel);
			const key = section.dataset.key;
			section.classList.toggle("collapsed");
			const nowCollapsed = section.classList.contains("collapsed");
			btn.setAttribute("aria-expanded", String(!nowCollapsed));
			if (nowCollapsed) collapsed.add(key);
			else collapsed.delete(key);
			saveCollapsed(storageKey, collapsed);
		});
	});
}

// Switch the wall's grouping mode in place: the header stays, the body
// re-renders from the cards already in hand. Only Custom fetches - the saved
// groupings rows live on the server.
async function setWallGroup(mode) {
	if (!WALL_GROUPS.includes(mode)) return;
	// Custom is not a mode (L.5): it opens the saved-groupings modal over the
	// current wall and returns to the mode that was showing. Only a grouping
	// actually opened takes over the view (runSavedGrouping, route g/<id>); a
	// cancel or backdrop click leaves the wall untouched.
	if (mode === "custom") {
		const pick = await openCustomPicker();
		if (pick && pick.create) createManualView();
		else if (pick) runSavedGrouping(pick.id, pick.name);
		return;
	}
	wallGroup = mode;
	localStorage.setItem("enqueue.wallGroup", mode);
	const bar = view.querySelector(".groupbar");
	if (bar) {
		bar.querySelectorAll("button").forEach((b) => {
			b.setAttribute("aria-pressed", String(b.dataset.mode === mode));
		});
	}
	// The tag bar is the Tags mode's filter row (L.1): show it only when the
	// mode asks for it. Home left it out of the DOM outside Tags mode, so a
	// switch into Tags fetches and builds it once (P.3d); it stays in the DOM
	// afterwards so chips and the all-tags expander keep their state.
	let tagbar = view.querySelector(".tagbar");
	if (mode === "tags" && !tagbar) {
		try {
			const tagcloud = await api("/tags");
			const tags = tagcloud.tags || [];
			if (tags.length) {
				const wrap = document.createElement("div");
				wrap.innerHTML = tagBarHtml(tags);
				tagbar = wrap.firstElementChild;
				view.querySelector(".homehead").appendChild(tagbar);
				bindTagbar(tagbar, view.querySelector(".homehead input"));
			}
		} catch (_) {
			// A failed /tags fetch just means no chips; the wall still works.
		}
	}
	if (tagbar) tagbar.hidden = mode !== "tags";
	const slot = document.getElementById("wallbody");
	if (!slot) return;
	slot.innerHTML = wallBodyHtml();
	// The Type and Tags modes fold their shelves (L.4); the toggle headers are
	// re-bound on every body render.
	if (mode === "type" || mode === "tags")
		mountCollapsible(".wallgroup", "enqueue.collapsedWall." + mode);
	if (mode === "touched") watchWallEnd();
}

// The saved-groupings modal (L.5): selecting "Custom" on the wall opens this
// instead of swapping the wall body, so the wall stays useful behind the dim.
// Each row runs its grouping, renames it (L.3b pencil), or forgets it. Cancel,
// Escape, and a backdrop click all close without touching the wall. Resolves
// to the picked grouping ({ id, name }) or null.
// Render (or re-render) the saved-groupings row list into the picker's list
// container. Shared by the open modal (L.5) and the in-place refresh after a
// rename or forget (L.3b): the rows are the same - run, rename, forget -
// only the run action differs (finish the modal, or run the grouping
// directly). Resolves when the fetch settles, so callers can await it.
function renderPickerRows(box, list, onRun) {
	list.innerHTML = spinner("sm", "opening...");
	return api("/pivots")
		.then((d) => {
			if (!box.isConnected) return; // the modal closed while fetching
			list.innerHTML = "";
			const pivots = d.items || [];
			if (!pivots.length) {
				const none = document.createElement("div");
				none.className = "state";
				none.textContent = "No views yet. Make one of your own below.";
				list.appendChild(none);
				return;
			}
			for (const p of pivots) {
				const row = document.createElement("div");
				row.className = "customrow";
				row.dataset.pivot = p.id;

				const run = document.createElement("button");
				run.className = "btn tertiary rowname";
				run.textContent = p.name;
				run.onclick = () => onRun(p);
				row.appendChild(run);

				// Who arranged it: you, or the assistant. Quiet, but it is the first thing
				// that tells two views apart.
				const how = document.createElement("span");
				how.className = "rowhow";
				how.textContent = p.manual ? "by hand" : "assistant";
				row.appendChild(how);

				const rename = document.createElement("button");
				rename.className = "title-action";
				rename.setAttribute("aria-label", "Rename " + p.name);
				rename.title = "Rename this view";
				rename.innerHTML = svg("pencil");
				rename.onclick = (ev) => {
					ev.stopPropagation();
					renameSavedGrouping(ev, p.id);
				};
				row.appendChild(rename);

				const forget = document.createElement("button");
				forget.className = "forgetbtn";
				forget.innerHTML = svg("close");
				forget.setAttribute("aria-label", "Forget " + p.name);
				forget.onclick = (ev) => {
					ev.stopPropagation();
					forgetSavedGrouping(ev, p.id);
				};
				row.appendChild(forget);

				list.appendChild(row);
			}
		})
		.catch(() => {
			if (!box.isConnected) return;
			list.innerHTML = "";
			const none = document.createElement("div");
			none.className = "aside";
			none.textContent = "Could not load saved views.";
			list.appendChild(none);
		});
}

function openCustomPicker() {
	const box = modalShell(
		'<h2 id="pickTitle">Saved views</h2>' +
			'<p class="aside">Arrange one yourself, with your own headers and order, or ask the eye to organize and save what it gathers.</p>' +
			'<div class="pickgroups" id="customPickerList"></div>' +
			'<div class="asked"><button class="btn secondary" value="no">Cancel</button>' +
			'<button class="btn primary" id="newManualView" type="button">New view</button></div>',
		{ labelledBy: "pickTitle", backdrop: true },
	);
	box.querySelector("#newManualView").onclick = () => box.finish({ create: true });

	// Render (or re-render) the row list. Called on open, and again by
	// renameSavedGrouping / forgetSavedGrouping after they change a row.
	const refresh = () =>
		renderPickerRows(box, box.querySelector("#customPickerList"), (p) =>
			box.finish({ id: p.id, name: p.name }),
		);
	refresh();
	return box.promise;
}

// Refresh the saved-groupings modal's row list after a rename or forget from
// inside it. A no-op when no picker is open, so the shared row actions also
// work from the saved-groupings sub-view.
async function refreshCustomPicker() {
	const dialog = document.querySelector("dialog.ask #customPickerList");
	if (!dialog) return;
	const box = dialog.closest("dialog");
	if (!box || !box.open) return;
	await renderPickerRows(box, box.querySelector("#customPickerList"), (p) => {
		try {
			box.close();
		} catch (_) {
			// Already closed by the platform; the node still has to go.
		}
		box.remove();
		runSavedGrouping(p.id, p.name);
	});
}

function card(a, i) {
	const bits = [since(a.created_at)];
	if (a.local_only) bits.push("local only");
	if (a.status === "text_only" && a.kind === "note")
		bits.push("holds a credential");

	// A conversation is a sixth kind on the wall: same card, same dot, same clock,
	// but it opens the thread instead of the artifact. The word is the app's own
	// name for the kind, not the storage table's.
	const word = a.kind === "chat" ? "conversation" : a.kind;
	const open = a.kind === "chat" ? "showChat" : "openArtifact";

	// "pending" is the engine's word for an artifact nothing has read yet, which is
	// the one thing the wall marks in the accent.
	const unread = a.status === "pending";
	const picture = facePicture(a);
	const flag = a.pinned
		? '<span class="flag" aria-hidden="true">' + svg("star") + "</span>"
		: "";

	const inside = picture
		? picture +
			flag +
			'<div class="cardband">' +
			kindRow +
			esc(word) +
			"</span></span>" +
			'<div class="title">' +
			esc(a.title || "Untitled") +
			"</div></div>"
		: '<div class="cardfoot" style="margin-top:0">' +
			kindRow +
			esc(word) +
			"</span></span>" +
			flag +
			"</div>" +
			'<div class="title">' +
			esc(a.title || "Untitled") +
			"</div>" +
			// The clamp rides an inner span, not .preview itself: .preview is a flex item
			// of the flex-column card, and a flex item's `display:-webkit-box` is
			// blockified to flow-root, which silently kills -webkit-line-clamp. The span
			// is an ordinary child, so the clamp (and the browser-painted ellipsis) holds.
			'<div class="preview"><span>' +
			(a.kind === "note"
				? esc(mdText(a.excerpt || ""))
				: esc(a.excerpt || (a.kind === "link" ? host(a.source_url) : ""))) +
			"</span></div>" +
			'<div class="cardfoot"><span class="meta">' +
			bits.map(esc).join(" ") +
			"</span>" +
			(unread ? '<span class="unread"></span>' : "") +
			"</div>";

	return (
		'<div class="card' +
		(picture ? " pictorial" : "") +
		(i < 18 ? " hang" : "") +
		'" data-kind="' +
		esc(a.kind) +
		'" data-id="' +
		esc(a.id) +
		'" ' +
		'tabindex="0" role="button"' +
		' aria-label="' +
		esc(
			(a.title || "Untitled") +
				", " +
				word +
				", " +
				bits.join(", ") +
				(unread ? ", not read yet" : "") +
				(a.pinned ? ", pinned" : ""),
		) +
		'"' +
		(i < 18 ? ' style="animation-delay:' + i * 22 + 'ms"' : "") +
		' onclick="' +
		open +
		"('" +
		a.id +
		"')\"" +
		" onkeydown=\"if(event.key==='Enter'||event.key===' '){event.preventDefault();" +
		open +
		"('" +
		a.id +
		"')}\">" +
		inside +
		"</div>"
	);
}

// Ingestion time by default. The promise is that things sit in the order you found
// them, and sorting by last touched means fixing a typo silently moves a note to the
// front of your own library.

// What the wall was showing last time it drew. Compared on focus so a refresh only
// happens when something actually changed, rather than reflowing the grid and
// throwing away your scroll position every time you tab back.
let wallStamp = null;

// What the wall was drawn from: how many items, and the most recently touched pinned and
// unpinned one with when. An edit made on another device moves an item up without
// adding one, so the time is part of it; counting alone left a phone's edit out of
// order here until something changed on this Mac.
function wallStampOf(kept, first) {
	const top = (page) => {
		const a = (page.items || [])[0] || {};
		return (a.id || "") + "@" + (a.updated_at || "");
	};
	return kept.total + first.total + ":" + top(kept) + ":" + top(first);
}

// A pull lands while the window is open and in front, too: look again every half
// minute while the wall is showing (two one-row requests).
setInterval(() => {
	if (place !== "wall") return;
	// Never under someone's hands: typing in the search, or a menu or dialog open.
	const at = document.activeElement;
	if (at && (at.matches("input, textarea") || at.isContentEditable)) return;
	if (document.querySelector(".acctmenu, dialog[open], .menu")) return;
	refreshIfStale();
}, 30000);

// A capture made in the overlay lands in a different window, and this one has no
// way to hear about it. Without this the home page sits stale until you navigate, so
// saving something correctly looked like saving nothing. The wall refreshes only
// when something actually changed; an open artifact or chat re-fetches
// its own rows on focus (K.9) so a capture elsewhere never leaves the open page
// stale - scroll is kept, nothing blinks.
async function refreshIfStale() {
	if (document.hidden || !view) return;
	// The welcome sends people to the browser to sign in and back: never redraw the
	// wall over it when they return, even if something synced meanwhile.
	if (typeof welcomeOpen === "function" && welcomeOpen()) return;
	if (place === "wall") {
		const peek = await Promise.all([
			api("/artifacts?pinned=true&order=touched&limit=1"),
			api("/artifacts?pinned=false&order=touched&limit=1"),
		]).catch(() => null);
		if (!peek) return;
		const stamp = wallStampOf(peek[0], peek[1]);
		if (stamp !== wallStamp) {
			// Something new arrived while you were away: the eye startles.
			const before = wallStamp ? parseInt(wallStamp, 10) : null;
			const total = peek[0].total + peek[1].total;
			await home({ keepScroll: true });
			if (window.eyeMood && before !== null && total > before) eyeMood.play("startle");
		}
		return;
	}
	// A saved view is LOCKED: it never recomputes on its own, so coming back to the
	// window leaves it exactly as it is (Rebuild is the one way to re-run it). This
	// used to re-run the whole spec on every focus - model judgments and all - and
	// then draw the view over whichever page was open by the time it answered.
	if (pivotState && pivotState.pivot_id) return;
	if (scope.kind === "artifact" && scope.id) {
		// Never rebuild an editor under the person's hands. Words not yet stored are
		// saved first and the page stays as it is; a page is re-read only when the
		// store has something this one does not show (an edit made on the phone, a
		// preview or summary that landed while away).
		if (editorDirty()) {
			await saveBody();
			return;
		}
		const fresh = await api("/artifacts/" + scope.id).catch(() => null);
		if (!fresh || !ctx || ctx.id !== scope.id) return;
		const editing = document.activeElement === document.getElementById("body");
		if (ctx.kind === "note") {
			const a = fresh.artifact;
			if ((a.body || "") === ctx.saved && a.title === ctx.title) return;
			if (editing || editorDirty()) return;
		} else if (editing || editorDirty()) {
			return;
		}
		showArtifact(scope.id, false, window.scrollY);
	} else if (scope.kind === "chat" && scope.id) {
		showChat(scope.id);
	}
}

window.addEventListener("focus", refreshIfStale);
document.addEventListener("visibilitychange", refreshIfStale);

// ---- hash router (K.9) --------------------------------------------------
// The home page is a single-page app with all view state in memory and no URL.
// macOS can reclaim a hidden webview, and the capture flow hides the window,
// so a reload re-inits the page and used to land on the wall no matter what
// was open. Every navigation now writes a route token to the hash and boot
// restores the same view. Tokens: empty = wall, #a/<id> = artifact,
// #c/<id> = chat, #g = saved-groupings list,
// #g/<id> = a saved grouping run, #s/<query> = search results.
function setRoute(token) {
	navArrive(token || "");
	const want = token ? "#" + token : "";
	if (location.hash === want) return;
	// replaceState, not location.hash: browser-history entries for every artifact
	// would make the browser's own Back a walk through views that never re-render.
	// The way back is the app's (goBack, below). There is no hashchange listener -
	// a second window driving the same page is not a scenario today.
	history.replaceState(null, "", want || location.pathname + location.search);
}

// ---- the way back -------------------------------------------------------
// The back button on a page goes to the page you came from, not to the wall: tags
// -> books -> a note -> back used to land on the wall, and the pill already has a
// home button for that. Every navigation passes through setRoute, so the trail is
// kept there: the route tokens you came through, each with where it was scrolled.
// Arriving on the wall starts the trail over (nothing is behind the wall). It lives
// in sessionStorage so a webview macOS reclaimed still knows the way back.
const NAV_KEY = "enqueue.navTrail";
let navTrail = [];
try {
	navTrail = JSON.parse(sessionStorage.getItem(NAV_KEY) || "[]");
	if (!Array.isArray(navTrail)) navTrail = [];
} catch (_) {
	navTrail = [];
}
let navAt = location.hash.replace(/^#/, "");
let navReturning = false;
// Where the page was scrolled when the person last acted: a view is torn down
// before its successor sets the route, and by then the scroll is gone.
let navY = 0;
for (const kind of ["pointerdown", "keydown"])
	document.addEventListener(kind, () => (navY = window.scrollY), true);

function navArrive(token) {
	if (token === navAt) return;
	if (!navReturning) {
		if (token === "") navTrail = [];
		else navTrail.push({ token: navAt, y: navY });
		if (navTrail.length > 50) navTrail.shift();
	}
	navAt = token;
	try {
		sessionStorage.setItem(NAV_KEY, JSON.stringify(navTrail));
	} catch (_) {
		// A full or disabled store only costs the trail across a reload.
	}
}

// Open the view a route token names. Anything unrecognized is the wall.
function openRoute(raw) {
	if (!raw) return home();
	const [kind, ...rest] = raw.split("/");
	const id = rest.join("/");
	if (kind === "a" && id) return showArtifact(id);
	// The conversation is a panel over the wall, so the wall is drawn first; opened
	// alone it sat over a page that said "opening..." for good.
	if (kind === "c" && id) return home().then(() => showChat(id));
	if (kind === "g" && !id) return showSavedGroupings();
	if (kind === "g" && id) return runSavedGrouping(id);
	if (kind === "s" && id) {
		try {
			return doSearch(decodeURIComponent(id));
		} catch (_) {
			return home();
		}
	}
	if (kind === "untagged" && !id) return showUntagged();
	if (kind === "settings" && !id) return showSettings();
	return home();
}

// Go back one page, to where it was scrolled. With nothing behind, the wall.
async function goBack() {
	const prev = navTrail.pop();
	if (!prev) return home();
	navReturning = true;
	try {
		await openRoute(prev.token);
	} finally {
		navReturning = false;
		navArrive(prev.token);
	}
	requestAnimationFrame(() => window.scrollTo(0, prev.y || 0));
}

// What the back button says: the page it goes to.
function backLabel() {
	const prev = navTrail[navTrail.length - 1];
	const token = prev ? prev.token : "";
	if (!token) return "Everything";
	const [kind, ...rest] = token.split("/");
	const id = rest.join("/");
	if (kind === "s" && id) {
		let q = id;
		try {
			q = decodeURIComponent(id);
		} catch (_) {
			// Shown as it is.
		}
		return q.length > 28 ? q.slice(0, 27) + "\u2026" : q;
	}
	if (kind === "g") return id ? "View" : "Views";
	if (kind === "untagged") return "Untagged";
	if (kind === "settings") return "Settings";
	return "Back";
}

// Boot reads the hash and restores the view that was open when the page was
// reclaimed, so a hidden-and-restored window never lands on the wall while an
// artifact was open. Anything unrecognized falls back to the wall.
function restoreRoute() {
	return openRoute(location.hash.replace(/^#/, ""));
}

// One order, always: what you touched last. The bar of alternatives was three
// controls for a decision nobody makes twice, sitting above the thing they were
// meant to help you read.
const PAGE = 48;
let wall = null;

// The wall's grouping mode (K.6): how the fetched cards are arranged under the
// home header. Last touch is the flat list the wall has always been; Type and
// Tags regroup the same rows client-side. Custom is not a mode - it opens the
// saved-groupings modal (L.5) and returns to the mode that was showing, so it
// is never persisted and never the boot state.
const WALL_GROUPS = ["type", "touched", "tags", "custom"];
let wallGroup = localStorage.getItem("enqueue.wallGroup");
if (!WALL_GROUPS.includes(wallGroup) || wallGroup === "custom")
	wallGroup = "touched";

// The cards home() fetched last time, kept for the client-side regroups.
let wallKept = [];
let wallFirst = [];

// The tag bar's chips (L.1): every tag as a chip on one line that scrolls sideways
// when they overflow (centered while they fit), plus an "untagged" chip anchored at
// the very end that stays put while the tags scroll under it - the complement,
// artifacts carrying no tag at all. Rendered only in Tags mode; setWallGroup builds
// or toggles it in place so it survives mode switches. The untagged chip lives
// OUTSIDE the scroll track so it never scrolls away.
function tagBarHtml(tags) {
	let html =
		'<div class="tagbar"' + (wallGroup === "tags" ? "" : " hidden") + ">";
	html += '<div class="tagbar-scroll"><div class="tagbar-track">';
	html += tags
		.map(
			(t) =>
				'<button class="tagchip" data-tag="' +
				esc(t.name) +
				'" type="button">#' +
				esc(t.name) +
				"</button>",
		)
		.join("");
	html += "</div></div>";
	html +=
		'<button class="tagchip untagged" data-untagged="1" type="button">untagged</button>';
	html += "</div>";
	return html;
}

// ---- search candidates ----------------------------------------------------
// Typing a thing's name should not cost a search. As you type, the artifacts the
// words could be naming drop down under the field (js/suggest.js, matched in the
// page against the list of titles: no request, no index, no model), and Enter on
// one opens it. The last row is always the full search, for when it is not a name
// you are typing. A confident name match is preselected, so "mesop" + Enter opens
// Mesopotamia; anything looser, a misspelling included, is offered in the list but
// leaves Enter on the full search, as before.
let suggestTitles = null;
let suggestFetched = 0;
async function loadSuggestTitles() {
	if (suggestTitles && Date.now() - suggestFetched < 20000) return;
	try {
		suggestTitles = (await api("/titles")).titles || [];
		suggestFetched = Date.now();
	} catch (_) {
		if (!suggestTitles) suggestTitles = [];
	}
}

function suggestMarked(title, marks) {
	let out = "";
	let at = 0;
	for (const [a, b] of marks) {
		out += esc(title.slice(at, a)) + "<b>" + esc(title.slice(a, b)) + "</b>";
		at = b;
	}
	return out + esc(title.slice(at));
}

function mountSuggest(hs, list) {
	let rows = []; // candidates, then the full-search row last
	let sel = -1;
	const close = () => {
		list.hidden = true;
		list.innerHTML = "";
		rows = [];
		sel = -1;
		hs.setAttribute("aria-expanded", "false");
		hs.removeAttribute("aria-activedescendant");
	};
	const paintSel = () => {
		list.querySelectorAll("[role=option]").forEach((el, i) => {
			el.setAttribute("aria-selected", String(i === sel));
			if (i === sel) {
				hs.setAttribute("aria-activedescendant", el.id);
				el.scrollIntoView({ block: "nearest" });
			}
		});
	};
	const act = (i) => {
		const row = rows[i];
		const q = hs.value.trim();
		if (!row || !q) return;
		close();
		if (row.id) {
			hs.blur();
			openArtifact(row.id, "suggest");
		} else doSearch(q);
	};
	const draw = () => {
		const q = hs.value.trim();
		// A tag filter or a quoted phrase is an instruction to the search, not a name.
		if (q.length < 2 || !suggestTitles || /^["#]/.test(q) || /^tag:/.test(q)) return close();
		const found = Suggest.rank(q, suggestTitles, 6);
		rows = found.map((f) => ({ id: f.item.id }));
		rows.push({ id: null });
		// Enter opens only what was actually named: a confident match. A guess from a
		// misspelling is offered in the list, never taken ("monkey" must not open the
		// note on money), so Enter stays on the search there.
		sel = found.length && found[0].score >= Suggest.STRONG ? 0 : rows.length - 1;
		list.innerHTML =
			found
				.map(
					(f, i) =>
						'<div class="suggest-row" role="option" id="sg' +
						i +
						'" data-i="' +
						i +
						'" data-kind="' +
						esc(f.item.kind) +
						'"><span class="kindmark" aria-hidden="true"></span>' +
						'<span class="suggest-title">' +
						suggestMarked(f.item.title, f.marks) +
						'</span><span class="suggest-kind">' +
						esc(f.item.kind) +
						"</span></div>",
				)
				.join("") +
			'<div class="suggest-row suggest-all" role="option" id="sg' +
			found.length +
			'" data-i="' +
			found.length +
			'">' +
			'<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>' +
			'<span class="suggest-title">Search everything for <q>' +
			esc(q) +
			"</q></span>" +
			'<kbd aria-hidden="true">&#8629;</kbd></div>';
		list.hidden = false;
		hs.setAttribute("aria-expanded", "true");
		paintSel();
	};

	hs.setAttribute("role", "combobox");
	hs.setAttribute("aria-autocomplete", "list");
	hs.setAttribute("aria-controls", "suggestList");
	hs.setAttribute("aria-expanded", "false");
	hs.addEventListener("focus", async () => {
		await loadSuggestTitles();
		if (document.activeElement === hs) draw();
	});
	hs.addEventListener("input", draw);
	// Leaving the field puts the list away. Clicks inside it never take the focus
	// (mousedown below), so this only fires on a real leave.
	hs.addEventListener("blur", close);
	list.addEventListener("mousedown", (e) => e.preventDefault());
	list.addEventListener("click", (e) => {
		const row = e.target.closest("[data-i]");
		if (row) act(+row.dataset.i);
	});
	list.addEventListener("mousemove", (e) => {
		const row = e.target.closest("[data-i]");
		if (row && +row.dataset.i !== sel) {
			sel = +row.dataset.i;
			paintSel();
		}
	});
	hs.addEventListener("keydown", (e) => {
		const open = !list.hidden;
		if (e.key === "ArrowDown" || e.key === "ArrowUp") {
			if (!open) return;
			e.preventDefault();
			sel = (sel + (e.key === "ArrowDown" ? 1 : rows.length - 1)) % rows.length;
			paintSel();
		} else if (e.key === "Enter") {
			const q = hs.value.trim();
			if (!q) return;
			if (open && sel >= 0) act(sel);
			else {
				close();
				doSearch(q);
			}
		} else if (e.key === "Escape") {
			// First Escape puts the candidates away; the next clears the field, so an
			// emptied field is still a way back to the wall.
			if (open) return close();
			hs.value = "";
			hs.blur();
		}
	});
}

// Bind the tag chips to the same search the searchbar runs: the input shows
// the `#name` query and results come back filtered. The trailing "untagged"
// chip is the complement - a listing of artifacts with no tag, not a search.
function bindTagbar(tagbar, hs) {
	if (!tagbar) return;
	tagbar.querySelectorAll(".tagchip[data-tag]").forEach((chip) => {
		chip.addEventListener("click", () => {
			const q = "#" + chip.dataset.tag;
			if (hs) hs.value = q;
			doSearch(q);
		});
	});
	const untagged = tagbar.querySelector(".tagchip[data-untagged]");
	if (untagged) {
		untagged.addEventListener("click", () => {
			if (hs) hs.value = "";
			showUntagged();
		});
	}
}

async function home(opts) {
	// Leaving for the wall locks the vault (if open), so re-entry needs the PIN.
	// `keepVault` skips that: the optimistic "move to vault" flow lands on the wall
	// while its background unlock+encrypt is still running, and locking here would
	// race that and cancel it. The window-blur auto-lock still covers leaving the app.
	if (!(opts && opts.keepVault) && typeof maybeLockVault === "function") maybeLockVault();
	const wasReading = chat;
	const keepAt = opts && opts.keepScroll ? window.scrollY : null;
	teardown();
	scope = { kind: "everything", label: "everything" };
	view.removeAttribute("data-kind");
	restorePill("wall");
	setRoute("");
	view.innerHTML = spinner("lg", "opening...");
	// The first open on a new Mac can wait on a Keychain prompt hidden behind the
	// window: after a while say so, rather than spin without a word.
	const slow = setTimeout(() => {
		const line = view.querySelector(".loader-caption");
		const note =
			"Still opening your library. If macOS is asking whether Enqueue may use your Keychain, choose Always Allow.";
		if (line) line.textContent = note;
		else view.insertAdjacentHTML("beforeend", '<p class="state" id="openSlow">' + esc(note) + "</p>");
	}, 8000);
	let kept, first;
	try {
		[kept, first] = await Promise.all([
			api("/artifacts?pinned=true&order=touched&limit=200"),
			api("/artifacts?pinned=false&order=touched&limit=" + PAGE),
		]);
	} catch (e) {
		clearTimeout(slow);
		view.innerHTML =
			'<div class="homehead"><h1 class="display greeting">Your library did not open.</h1>' +
			'<p class="state">' +
			esc(e.message || "The engine did not answer.") +
			'</p><button class="btn primary" type="button" onclick="home()">Try again</button></div>';
		return;
	}
	clearTimeout(slow);
	// /tags is paid for only in Tags mode (P.3d): every other grouping leaves
	// the tag bar out of the DOM, and setWallGroup builds it on demand.
	const tagcloud = wallGroup === "tags" ? await api("/tags") : { tags: [] };

	if (!kept.total && !first.total) {
		// A fresh library opens on the first-run welcome, once (js/welcome.js).
		if (await maybeWelcome()) return;
		// An empty library still gets the normal greeting (the living emblem + the
		// time-of-day phrase), so a fresh install opens on the brand, not a wall of prose.
		// One short line points at the capture pill already on screen; no second button.
		const hour = new Date().getHours();
		const fallback =
			greetingLeader(hour);
		view.innerHTML =
			'<div class="homehead">' +
			greetDateHtml() +
			// Top right: the account (js/accountmenu.js) and the ? (js/welcome.js).
			homeCornerHtml() +
			'<div class="greetline">' +
			'<div class="greet-emblem eye" id="greetEye" aria-hidden="true"></div>' +
			'<h1 class="display greeting">' +
			greetingInner(fallback) +
			"</h1>" +
			"</div>" +
			'<div class="state">Nothing here yet. Just add your artifacts.</div>' +
			"</div>";
		makeEye(document.getElementById("greetEye"));
		paintAccountChip();
		return;
	}

	// The emblem is the same eye at every hour; the greeting phrase below it
	// carries the time of day. The eye is decorative, so it is hidden from the
	// accessibility tree; the phrase says everything.
	const hour = new Date().getHours();
	const fallback =
		greetingLeader(hour);
	let html =
		'<div class="homehead">' +
		greetDateHtml() +
		// Top right: the account (js/accountmenu.js) and the ? (js/welcome.js).
		homeCornerHtml() +
		'<div class="greetline">' +
		// O.3: the eyeball PNG is split into a frame (the socket: outline, lashes,
		// ground) and a small pupil image (only the purple iris, transparent
		// surround), so the cursor-follow the old SVG eye had is restored as a
		// real follow - only the iris leans inside the fixed socket. The blinkwrap
		// (socket and frame clipped together) is injected by makeEye (icons.js,
		// EYE.1), so the same living eye mounts anywhere; this container is the
		// greeting emblem only. The eye is decorative, so it is hidden from the
		// accessibility tree; the greeting phrase carries the meaning.
		'<div class="greet-emblem eye" id="greetEye" aria-hidden="true"></div>' +
		'<h1 class="display greeting">' +
		greetingInner(fallback) +
		"</h1>" +
		"</div>" +
		'<div class="searchbar">' +
		'<svg viewBox="0 0 24 24" aria-hidden="true">' +
		'<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>' +
		'<input id="homesearch" type="search" placeholder="Search your artifacts" aria-label="Search your artifacts" autocomplete="off" spellcheck="false" />' +
		'<kbd class="hint" aria-hidden="true">&#8984;K</kbd>' +
		'<div class="suggest" id="suggestList" role="listbox" aria-label="Artifacts by name" hidden></div>' +
		"</div>" +
		groupBarHtml();
	// The tag bar is a set of exact filters, secondary to the searchbar: the
	// top tags as chips, an all-tags chip only when the top eight do not cover
	// them. It belongs to the Tags wall mode (L.1); in every other mode it is
	// left out of the DOM entirely and setWallGroup builds it on demand.
	if (wallGroup === "tags" && (tagcloud.tags || []).length)
		html += tagBarHtml(tagcloud.tags);
	html += "</div>";
	// M.1: the wall header goes straight from .homehead into the wall body.
	// The "Collections" shelf is gone; saved groupings own that concept.

	wall = { offset: first.items.length, more: first.more, loading: false };
	wallStamp = wallStampOf(kept, first);
	wallKept = kept.items;
	wallFirst = first.items;

	// The wall body renders in the chosen grouping mode (K.6). Custom fetches
	// /pivots after the shell is in place, so its slot starts empty.
	html += '<div class="reading" id="reading" role="status" aria-live="polite" hidden></div>';
	html += '<div class="shiny" id="shiny" hidden></div>';
	html += '<div class="wallbody" id="wallbody"></div>';

	view.innerHTML = html;
	makeEye(document.getElementById("greetEye"));
	paintAccountChip();
	refreshShiny();
	refreshReading();

	const bodySlot = view.querySelector(".wallbody");
	// Custom is never a boot or persistent mode (L.5): it opens a modal on
	// demand. The wall body always renders one of the client-side arrangements.
	bodySlot.innerHTML = wallBodyHtml();
	if (wallGroup === "type" || wallGroup === "tags" || wallGroup === "touched")
		mountCollapsible(".wallgroup", "enqueue.collapsedWall." + wallGroup);
	// The home search lives inside the greeting header and is re-created on every
	// home render, so its keys are bound here, not once at startup. Enter searches;
	// Escape clears so an emptied field is a way back to the wall.
	const hs = view.querySelector(".homehead input");
	if (hs) mountSuggest(hs, view.querySelector("#suggestList"));
	// A tag chip runs the same search the searchbar runs: the input shows the
	// `#name` query and the results come back filtered. The all-tags chip
	// reveals whatever the top eight did not cover.
	bindTagbar(view.querySelector(".tagbar"), hs);
	// The grouping selector (K.6): one of four arrangements for the same wall.
	// Switching re-renders the body in place; the header stays put.
	const gbar = view.querySelector(".groupbar");
	if (gbar) {
		gbar.querySelectorAll("button").forEach((b) => {
			b.addEventListener("click", () => setWallGroup(b.dataset.mode));
		});
	}
	if (wallGroup === "touched") watchWallEnd();
	refreshGreeting();
	if (keepAt !== null) window.scrollTo(0, keepAt);
	else if (wasReading) window.scrollTo(0, 0);
}

// The phrase on screen before /greeting answers: each daypart's leader, on the same
// windows as greeting.py (morning 6-12, afternoon 12-18, evening 18-24, night 0-6).
function greetingLeader(hour) {
	if (hour >= 6 && hour < 12) return "Up before the worms";
	if (hour >= 12 && hour < 18) return "Afternoon, guv'nah";
	if (hour >= 18) return "Think about winding down";
	return "Still up?";
}

// The greeting's inner markup: the phrase with its last word in the accent and
// the accent mark after it, so the time-of-day line ends on the raven's colour. The
// mark is the phrase's own ending ("Still up?") or a period when it has none. A
// one-word phrase is all accent. The text is escaped by construction (esc).
function greetingInner(text) {
	const raw = String(text || "").trim();
	const end = (raw.match(/[.?!]+$/) || ["."])[0];
	const words = raw.slice(0, raw.length - (/[.?!]+$/.test(raw) ? end.length : 0)).split(/\s+/);
	const last = words.pop() || "";
	const lead = words.length ? esc(words.join(" ")) + " " : "";
	return (
		'<span class="greet-lead">' +
		lead +
		'</span><span class="greet-last">' +
		esc(last) +
		'</span><span class="greet-mark">' +
		esc(end) +
		"</span>"
	);
}

// The small date line above the greeting ("Sunday, September 27"): it anchors the
// time-of-day phrase to today, the way a journal page does.
function greetDateHtml() {
	const d = new Date().toLocaleDateString(undefined, {
		weekday: "long",
		month: "long",
		day: "numeric",
	});
	return '<div class="greet-date">' + esc(d) + "</div>";
}

// The greeting is hardcoded and picked by the clock: the engine answers
// without a model call and the time-based fallback is already on screen, so
// this is a quiet swap, never a wait. Fetched once per home render.
async function refreshGreeting() {
	const el = document.querySelector(".homehead .greeting");
	if (!el) return;
	try {
		const r = await api("/greeting");
		if (!r || !r.text) return;
		// Compare without the trailing mark (the accent ending is added on render).
		const bare = (t) => String(t).trim().replace(/[.?!]+$/, "");
		if (bare(r.text) !== bare(el.textContent)) {
			el.innerHTML = greetingInner(r.text);
			el.classList.remove("swap");
			void el.offsetWidth;
			el.classList.add("swap");
		}
	} catch (err) {
		// The wall keeps its fallback; a failed greeting is not worth an error state.
	}
}

// The first big read (reading.py, GET /reading): after an import, a switch of AI model,
// or a sync that brings a whole library onto this Mac, the assistant writes its few
// lines about each item one by one for a while. One quiet line above the wall says how
// far it is and why, and goes away when it is done. Checked on every wall render, and
// polled only while the line is up.
let readingTimer = null;
const READING_POLL_MS = 8000;

function readingWhy(r) {
	if (r.state === "key")
		return (
			"Stopped: your AI service turned down the key. " +
			'<a href="#" class="reading-fix">Check it in Settings</a>.'
		);
	if (r.state === "paused") {
		const at = r.paused_until
			? new Date(r.paused_until).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
			: "";
		return (
			"Paused: your AI service hit its usage limit. It goes on by itself" +
			(at ? " at " + esc(at) : "") +
			"."
		);
	}
	if (r.state === "retrying")
		return "The assistant didn't answer just now, so it tries again in a moment.";
	return (
		"The assistant is writing a few lines about each thing you saved, so search " +
		"finds it by what it's about. Search by words works the whole time."
	);
}

async function refreshReading() {
	clearTimeout(readingTimer);
	readingTimer = null;
	const slot = document.getElementById("reading");
	if (!slot) return;
	let r;
	try {
		r = await api("/reading");
	} catch {
		r = null;
	}
	// The wall may have been left while the request was out.
	if (slot !== document.getElementById("reading")) return;
	// Once up, the line stays until the reading is done, even when fewer than the
	// threshold are left, so it does not blink off at 351 of 360.
	const keep = r && (r.show || (!slot.hidden && r.remaining > 0 && r.state !== "idle"));
	if (!keep) {
		slot.hidden = true;
		slot.innerHTML = "";
		return;
	}
	const pct = r.total ? Math.round((100 * r.done) / r.total) : 0;
	slot.innerHTML =
		'<div class="reading-head">' +
		'<span class="reading-title">Reading your library</span>' +
		'<span class="reading-count">' +
		r.done.toLocaleString() +
		" of " +
		r.total.toLocaleString() +
		"</span></div>" +
		'<div class="reading-bar' +
		(r.state === "reading" ? "" : " still") +
		'" aria-hidden="true"><span style="width:' +
		pct +
		'%"></span></div>' +
		'<div class="reading-why">' +
		readingWhy(r) +
		"</div>";
	slot.dataset.state = r.state;
	slot.hidden = false;
	const fix = slot.querySelector(".reading-fix");
	if (fix)
		fix.addEventListener("click", (e) => {
			e.preventDefault();
			currentSettingsTab = "ai";
			showSettings();
		});
	readingTimer = setTimeout(refreshReading, READING_POLL_MS);
}

// Something shiny (shiny.py): two or three notes from different fields that make the
// same point, side by side above the wall, with the idea they share and a question to
// take it further. One set a day; "Find another" walks on to the next, and the wall
// keeps showing the last one found until tomorrow. The model's words are written in
// the background; until they land the card shows the link's own sentence and asks
// again a few times. "Not today" hides it until tomorrow in this browser only.
const SHINY_DISMISSED = "enqueue.shiny.dismissed";
const SHINY_AT = "enqueue.shiny.at";
const SHINY_RETRY_MS = 6000;
const SHINY_RETRIES = 4;
// Bumped by every new fetch, so a late retry for an earlier set never draws over it.
let shinyGen = 0;

function todayStamp() {
	return new Date().toISOString().slice(0, 10);
}

function shinyAt() {
	try {
		const at = JSON.parse(localStorage.getItem(SHINY_AT) || "null");
		if (at && at.day === todayStamp() && Number.isInteger(at.n) && at.n > 0) return at.n;
	} catch (_) {
		// No storage, or something unreadable in it: start from the day's own set.
	}
	return 0;
}

function setShinyAt(n) {
	try {
		localStorage.setItem(SHINY_AT, JSON.stringify({ day: todayStamp(), n }));
	} catch (_) {
		// Remembered for this visit only.
	}
}

async function refreshShiny(tries = 0, n = shinyAt()) {
	const slot = document.getElementById("shiny");
	if (!slot) return;
	try {
		if (localStorage.getItem(SHINY_DISMISSED) === todayStamp()) return;
	} catch (_) {
		// No storage (private window): the card simply always shows.
	}
	const gen = ++shinyGen;
	let r;
	try {
		r = await api("/shiny?n=" + n);
	} catch (_) {
		return;
	}
	if (gen !== shinyGen || !document.body.contains(slot)) return;
	// The set remembered for today is gone (a note trashed since): start over.
	if ((!r || !r.notes || r.notes.length < 2) && n > 0) {
		setShinyAt(0);
		return refreshShiny(0, 0);
	}
	if (!r || !r.notes || r.notes.length < 2) return;
	const food = r.food || {};
	const parts = food.parts || {};
	const next = r.more ? "Find another" : "Back to the first";
	slot.innerHTML =
		'<section class="shiny-card" aria-label="Something shiny">' +
		'<div class="shiny-head"><span class="shiny-kicker">Something shiny</span>' +
		'<button class="shiny-dismiss" type="button">Not today</button></div>' +
		(food.idea ? '<p class="shiny-idea">' + esc(food.idea) + "</p>" : "") +
		'<div class="shiny-notes">' +
		r.notes
			.map(
				(a) =>
					'<button class="shiny-note" type="button" data-id="' +
					esc(a.id) +
					'"><span class="shiny-title">' +
					esc(a.title || "Untitled") +
					"</span>" +
					(parts[a.id] ? '<span class="shiny-how">' + esc(parts[a.id]) + "</span>" : "") +
					"</button>",
			)
			.join("") +
		"</div>" +
		'<div class="shiny-foot">' +
		(food.question ? '<p class="shiny-question">' + esc(food.question) + "</p>" : "") +
		// Hidden when there is only the one set: nothing else to find.
		(r.more || n > 0
			? '<button class="shiny-another" type="button">' + next + (r.more ? svg("chev") : "") + "</button>"
			: "") +
		"</div></section>";
	slot.hidden = false;
	slot.querySelectorAll(".shiny-note").forEach((b) => {
		b.addEventListener("click", () => openArtifact(b.dataset.id, "shiny"));
	});
	slot.querySelector(".shiny-dismiss").addEventListener("click", () => {
		try {
			localStorage.setItem(SHINY_DISMISSED, todayStamp());
		} catch (_) {
			// Hidden for this visit only.
		}
		slot.hidden = true;
	});
	const another = slot.querySelector(".shiny-another");
	if (another)
		another.addEventListener("click", () => {
			const to = r.more ? n + 1 : 0;
			setShinyAt(to);
			slot.querySelector(".shiny-card").classList.add("shiny-turning");
			refreshShiny(0, to).then(() => slot.querySelector(".shiny-another")?.focus());
		});
	if (r.writing && tries < SHINY_RETRIES)
		setTimeout(() => {
			if (gen === shinyGen && document.body.contains(slot) && !slot.hidden)
				refreshShiny(tries + 1, n);
		}, SHINY_RETRY_MS);
}

/// Drag-and-drop ingestion.
///
/// The whole window is a drop target, so there is no drop zone to find: when a
/// file, image, or external text drag crosses into the window, the room dims and
/// a card opens to receive (the acknowledgement in `#dropover`). Releasing routes
/// through the same paths the pill uses - files and images to /capture/upload,
/// text to /notes - so nothing about ingestion is new; only the gesture is.
/// A drag that begins inside this document (moving a note's own text around) is
/// left to the browser and never hijacked into a capture.
const dropOver = document.getElementById("dropover");
let dropDepth = 0; // balanced enter/leave count, survives child nodes
let internalDrag = false; // true while a drag originates inside this document
let dropBusy = false; // quiet while the accept beat plays out

// Any drag that did not begin inside this document is a candidate: a file or
// image from the Finder, or selected text from another app. WebKit does not
// always surface the "Files" type on dragover the way Blink does, so eligibility
// is decided by origin, not by what the engine happens to report in `types`.
const externalDrag = (dt) => !internalDrag && !!dt;

document.addEventListener("dragstart", () => {
	internalDrag = true;
});
document.addEventListener("dragend", () => {
	internalDrag = false;
	dropDepth = 0;
});

function showDrop() {
	if (dropBusy || !dropOver.hidden) return;
	dropOver.dataset.state = "ready";
	dropOver.hidden = false;
	requestAnimationFrame(() => dropOver.classList.add("on"));
}
function hideDrop() {
	if (dropOver.hidden) return;
	dropOver.classList.remove("on");
	setTimeout(() => {
		if (!dropOver.classList.contains("on")) dropOver.hidden = true;
	}, 320);
}

document.addEventListener("dragenter", (e) => {
	dropDepth++;
	if (externalDrag(e.dataTransfer)) {
		e.preventDefault();
		showDrop();
	}
});
document.addEventListener("dragover", (e) => {
	if (externalDrag(e.dataTransfer)) e.preventDefault();
});
document.addEventListener("dragleave", () => {
	if (--dropDepth <= 0) {
		dropDepth = 0;
		hideDrop();
	}
});
window.addEventListener("blur", () => {
	dropDepth = 0;
	hideDrop();
});

async function ingestDrop(files, text) {
	const failed = [];
	let kept = 0;
	for (const file of files) {
		const fd = new FormData();
		fd.append("file", file);
		try {
			const r = await fetch("/capture/upload", { method: "POST", body: fd });
			if (!r.ok)
				throw new Error(
					(await r.json().catch(() => ({}))).detail || r.statusText,
				);
			kept++;
		} catch (err) {
			failed.push(file.name + ": " + String(err.message || err));
		}
	}
	if (text) {
		try {
			const r = await fetch("/notes", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ body: text }),
			});
			if (!r.ok)
				throw new Error(
					(await r.json().catch(() => ({}))).detail || r.statusText,
				);
			kept++;
		} catch (err) {
			failed.push("text: " + String(err.message || err));
		}
	}
	home();
	if (failed.length) toast("Upload failed. " + failed.join("; "), true);
	else if (kept) toast(kept === 1 ? "Uploaded." : kept + " uploaded.");
}

document.addEventListener("drop", (e) => {
	if (dropBusy) return;
	const dt = e.dataTransfer;
	if (!externalDrag(dt)) return; // an internal move; let the browser do it
	// The DataTransfer is only valid inside this event, so the payload is read now.
	const files = Array.from(dt.files ? dt.files : []);
	const text = (dt.getData("text/plain") || "").trim();
	if (!files.length && !text) return;
	e.preventDefault();
	internalDrag = false;
	dropDepth = 0;
	dropBusy = true;
	dropOver.dataset.state = "accept";
	setTimeout(() => {
		dropOver.classList.remove("on");
		setTimeout(() => {
			dropOver.hidden = true;
			dropBusy = false;
		}, 320);
	}, 560);
	ingestDrop(files, text);
});

// Loads the next page when the foot of the wall comes near, so the collection is
// not silently truncated at whatever number the first request asked for.
let wallWatch = null;

function watchWallEnd() {
	if (wallWatch) wallWatch.disconnect();
	const foot = document.getElementById("wallEnd");
	if (!foot) return;

	wallWatch = new IntersectionObserver(
		(entries) => {
			if (entries.some((e) => e.isIntersecting)) loadMore();
		},
		{ rootMargin: "600px 0px" },
	);
	wallWatch.observe(foot);
}

async function loadMore() {
	if (!wall || wall.loading || !wall.more) return;
	wall.loading = true;

	const foot = document.getElementById("wallEnd");
	if (foot) foot.innerHTML = spinner("sm", "loading more...");

	const next = await api(
		"/artifacts?pinned=false&order=touched&limit=" +
			PAGE +
			"&offset=" +
			wall.offset,
	).catch(() => null);

	if (!next) {
		wall.loading = false;
		if (foot) foot.textContent = "could not load more";
		return;
	}

	const grid = document.getElementById("wall");
	if (grid) {
		grid.insertAdjacentHTML("beforeend", next.items.map(card).join(""));
	}

	wall.offset += next.items.length;
	wall.more = next.more;
	wall.loading = false;
	if (foot) foot.textContent = wall.more ? "" : "";
	if (!wall.more && wallWatch) wallWatch.disconnect();
}
