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
			'<div class="shelf" style="margin-bottom: var(--sp-3)">Nothing kept yet</div>' +
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
	if (wallKept.length) sections.push(["SAVED", wallKept, true]);
	sections.push(["EVERYTHING ELSE", wallFirst, false]);
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
				'"><span class="shelf center">' +
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
		if (pick) runSavedGrouping(pick.id, pick.name);
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
				none.textContent = "Nothing saved yet.";
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
			'<p class="aside">Re-runs live as your library grows. Ask the eye to organize, then keep any arrangement here.</p>' +
			'<div class="pickgroups" id="customPickerList"></div>' +
			'<div class="asked"><button class="btn secondary" value="no">Cancel</button></div>',
		{ labelledBy: "pickTitle", backdrop: true },
	);

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
			'<div class="preview">' +
			(a.kind === "note"
				? esc(mdText(a.excerpt || ""))
				: esc(a.excerpt || (a.kind === "link" ? host(a.source_url) : ""))) +
			"</div>" +
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
				(a.pinned ? ", kept" : ""),
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

// A capture made in the overlay lands in a different window, and this one has no
// way to hear about it. Without this the home page sits stale until you navigate, so
// saving something correctly looked like saving nothing. The wall refreshes only
// when something actually changed; an open artifact or chat re-fetches
// its own rows on focus (K.9) so a capture elsewhere never leaves the open page
// stale - scroll is kept, nothing blinks.
async function refreshIfStale() {
	if (document.hidden || !view) return;
	if (place === "wall") {
		const peek = await api("/artifacts?limit=1&order=ingested").catch(
			() => null,
		);
		if (!peek) return;
		const stamp = peek.total + ":" + ((peek.items[0] || {}).id || "");
		if (stamp !== wallStamp) home({ keepScroll: true });
		return;
	}
	if (pivotState && pivotState.pivot_id) {
		// A saved view is open: re-run it with the current spec so a
		// capture elsewhere is reflected, keeping scroll position.
		const scrollY = window.scrollY;
		let next;
		try {
			next = await api("/pivot/run", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ spec: pivotState.spec }),
			});
		} catch (err) {
			return;
		}
		if (pivotState && pivotState.pivot_id) {
			renderPivot(
				next,
				pivotState.request,
				pivotState.spec,
				pivotState.pivot_id,
			);
			window.scrollTo(0, scrollY);
		}
		return;
	}
	if (scope.kind === "artifact" && scope.id) {
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
	const want = token ? "#" + token : "";
	if (location.hash === want) return;
	// replaceState, not location.hash: the app's own pill is the back button,
	// and browser-history entries for every artifact would make Back a broken
	// walk through views that never re-render. There is no hashchange listener
	// - a second window driving the same page is not a scenario today.
	history.replaceState(null, "", want || location.pathname + location.search);
}

// Boot reads the hash and restores the view that was open when the page was
// reclaimed, so a hidden-and-restored window never lands on the wall while an
// artifact was open. Anything unrecognized falls back to the wall.
function restoreRoute() {
	const raw = location.hash.replace(/^#/, "");
	if (!raw) return home();
	const [kind, ...rest] = raw.split("/");
	const id = rest.join("/");
	if (kind === "a" && id) return showArtifact(id);
	if (kind === "c" && id) return showChat(id);
	if (kind === "g" && !id) return showSavedGroupings();
	if (kind === "g" && id) return runSavedGrouping(id);
	if (kind === "s" && id) {
		try {
			return doSearch(decodeURIComponent(id));
		} catch (_) {
			return home();
		}
	}
	return home();
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

// The tag bar's chips (L.1): the top eight tags plus an all-tags expander
// that reveals the rest. Rendered only in Tags mode; setWallGroup builds or
// toggles it in place so chips and expander state survive mode switches.
function tagBarHtml(tags) {
	const top = tags.slice(0, 8);
	const rest = tags.slice(8);
	let html =
		'<div class="tagbar"' + (wallGroup === "tags" ? "" : " hidden") + ">";
	html += top
		.map(
			(t) =>
				'<button class="tagchip" data-tag="' +
				esc(t.name) +
				'" type="button">#' +
				esc(t.name) +
				"</button>",
		)
		.join("");
	if (rest.length)
		html +=
			'<button class="tagchip all" type="button" aria-expanded="false">all tags</button>' +
			rest
				.map(
					(t) =>
						'<button class="tagchip more" data-tag="' +
						esc(t.name) +
						'" type="button" hidden>#' +
						esc(t.name) +
						"</button>",
				)
				.join("");
	html += "</div>";
	return html;
}

// Bind the tag chips to the same search the searchbar runs: the input shows
// the `#name` query and results come back filtered. The all-tags chip
// reveals whatever the top eight did not cover.
function bindTagbar(tagbar, hs) {
	if (!tagbar) return;
	tagbar.querySelectorAll(".tagchip[data-tag]").forEach((chip) => {
		chip.addEventListener("click", () => {
			const q = "#" + chip.dataset.tag;
			if (hs) hs.value = q;
			doSearch(q);
		});
	});
	const all = tagbar.querySelector(".tagchip.all");
	if (all) {
		all.addEventListener("click", () => {
			const show = all.getAttribute("aria-expanded") !== "true";
			all.setAttribute("aria-expanded", String(show));
			tagbar
				.querySelectorAll(".tagchip.more")
				.forEach((c) => (c.hidden = !show));
		});
	}
}

async function home(opts) {
	// Leaving for the wall locks the vault (if open), so re-entry needs the PIN.
	if (typeof maybeLockVault === "function") maybeLockVault();
	const wasReading = chat;
	const keepAt = opts && opts.keepScroll ? window.scrollY : null;
	teardown();
	scope = { kind: "everything", label: "everything" };
	view.removeAttribute("data-kind");
	restorePill("wall");
	setRoute("");
	view.innerHTML = spinner("lg", "opening...");

	const [kept, first] = await Promise.all([
		api("/artifacts?pinned=true&order=touched&limit=200"),
		api("/artifacts?pinned=false&order=touched&limit=" + PAGE),
	]);
	// /tags is paid for only in Tags mode (P.3d): every other grouping leaves
	// the tag bar out of the DOM, and setWallGroup builds it on demand.
	const tagcloud = wallGroup === "tags" ? await api("/tags") : { tags: [] };

	if (!kept.total && !first.total) {
		// No illustration and no button. The capture pill is already on screen and it
		// is the call to action; a second one here would be the same instruction twice.
		view.innerHTML =
			'<div class="empty"><div class="display">Nothing here yet</div>' +
			'<div class="state">Anything you drop on the pill below is kept exactly as it ' +
			"arrived and read on this machine, in the order you found it. No folder, no tag, " +
			"no reason required. Nothing here expires.</div></div>";
		return;
	}

	// The emblem is the same eye at every hour; the greeting phrase below it
	// carries the time of day. The eye is decorative, so it is hidden from the
	// accessibility tree; the phrase says everything.
	const hour = new Date().getHours();
	const fallback =
		hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
	let html =
		'<div class="homehead">' +
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
		fallback +
		'<span class="greet-mark">.</span></h1>' +
		"</div>" +
		'<div class="searchbar">' +
		'<svg viewBox="0 0 24 24" aria-hidden="true">' +
		'<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>' +
		'<input id="homesearch" type="search" placeholder="Search your artifacts" aria-label="Search your artifacts" autocomplete="off" spellcheck="false" />' +
		'<kbd class="hint" aria-hidden="true">&#8984;K</kbd>' +
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
	wallStamp = first.total + ":" + ((first.items[0] || {}).id || "");
	wallKept = kept.items;
	wallFirst = first.items;

	// The wall body renders in the chosen grouping mode (K.6). Custom fetches
	// /pivots after the shell is in place, so its slot starts empty.
	html += '<div class="wallbody" id="wallbody"></div>';

	view.innerHTML = html;
	makeEye(document.getElementById("greetEye"));

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
	if (hs) {
		hs.addEventListener("keydown", (e) => {
			if (e.key === "Escape") {
				hs.value = "";
				hs.blur();
			} else if (e.key === "Enter") {
				const q = hs.value.trim();
				if (q) doSearch(q);
			}
		});
	}
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

// The greeting is hardcoded and picked by the clock: the engine answers
// without a model call and the time-based fallback is already on screen, so
// this is a quiet swap, never a wait. Fetched once per home render.
async function refreshGreeting() {
	const el = document.querySelector(".homehead .greeting");
	if (!el) return;
	try {
		const r = await api("/greeting");
		if (!r || !r.text) return;
		// The phrase is the h1's first text node; the P.7 lavender period rides
		// in a trailing span, so swapping only the text node keeps the mark.
		const phrase = el.firstChild ? el.firstChild.nodeValue : el.textContent;
		if (r.text !== phrase) {
			el.firstChild.nodeValue = r.text;
			el.classList.remove("swap");
			void el.offsetWidth;
			el.classList.add("swap");
		}
	} catch (err) {
		// The wall keeps its fallback; a failed greeting is not worth an error state.
	}
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
