// ---- views arranged by hand -------------------------------------------------
// A manual view is a saved view with no recipe: the person makes the headers, puts
// artifacts under them, and orders both. No model is involved, ever. It is the same
// saved view as an assistant-made one (same list, same route, same sync to the
// phone); only this page differs, because here everything on it can be moved.
//
// The page keeps the arrangement in `manual` and sends the WHOLE layout back after
// every change (PUT /pivots/{id}/layout): one write path for add, drag, rename,
// move and delete, and the stored order is always what is on screen. Changes render
// first and save behind, so nothing waits on the engine.
//
// Dragging is built on pointer events rather than the browser's own drag and drop,
// which the desktop shell's WebView handles inconsistently (it also owns file drops
// on the window). The dragged card moves in the DOM as the pointer moves, so what
// you see while dragging is exactly what you get on release.

let manual = null; // { id, name, groups: [{ key, ids }], cards: { id: card } }
let manualSaving = Promise.resolve();

const UNSORTED = "Unsorted";
const mvLabel = (key) => key || UNSORTED;

function manualFromResult(result) {
	const cards = {};
	const groups = [];
	for (const g of result.groups || []) {
		for (const item of g.items || []) cards[item.id] = item;
		groups.push({ key: g.key || "", ids: (g.artifact_ids || []).slice() });
	}
	return { groups, cards };
}

// Entry point: renderPivot hands a hand-arranged view here.
function renderManualView(d, name, spec, pivotId) {
	pivotState = { d, request: name, spec, pivot_id: pivotId };
	manual = Object.assign({ id: pivotId, name }, manualFromResult(d));
	manualRender();
	window.scrollTo(0, 0);
}

function manualCounts() {
	const shown = manual.groups.reduce(
		(n, g) => n + g.ids.filter((id) => manual.cards[id]).length,
		0,
	);
	const h = manual.groups.length;
	if (!h) return "Arranged by you";
	return (
		"Arranged by you &middot; " +
		h +
		" header" +
		(h === 1 ? "" : "s") +
		" &middot; " +
		shown +
		" item" +
		(shown === 1 ? "" : "s")
	);
}

function manualGroupHtml(g) {
	const label = mvLabel(g.key);
	const items = g.ids.map((id) => manual.cards[id]).filter(Boolean);
	return (
		'<section class="mvgroup" data-key="' +
		esc(g.key) +
		'">' +
		'<div class="mvhead">' +
		'<button class="mvgrip" type="button" aria-label="Move the header ' +
		esc(label) +
		'. Drag it, or press the up and down arrow keys." title="Drag to reorder">' +
		svg("grip") +
		"</button>" +
		'<button class="mvname" type="button" title="Rename" onclick="manualRename(this)">' +
		esc(label) +
		"</button>" +
		'<span class="mvcount">' +
		items.length +
		"</span>" +
		'<button class="groupdel" type="button" aria-label="Delete the header ' +
		esc(label) +
		'" title="Delete this header" onclick="manualDeleteHeader(this)">' +
		svg("trash") +
		"</button>" +
		"</div>" +
		'<div class="wall mvwall">' +
		items
			.map(
				(a, i) =>
					'<div class="pivotcard mvcard" data-id="' +
					esc(a.id) +
					'">' +
					card(a, i) +
					'<button class="movebtn" type="button" aria-label="Move ' +
					esc(a.title || "Untitled") +
					' to another header" title="Move to another header" onclick="manualMoveCard(event, this)">' +
					svg("move") +
					"</button>" +
					'<button class="removebtn" type="button" aria-label="Remove ' +
					esc(a.title || "Untitled") +
					' from this view" title="Remove from this view" onclick="manualRemoveCard(event, this)">' +
					svg("close") +
					"</button>" +
					"</div>",
			)
			.join("") +
		'<button class="mvadd" type="button" onclick="manualAddTo(this)">' +
		svg("plus") +
		"<span>Add</span></button>" +
		"</div>" +
		"</section>"
	);
}

function manualRender() {
	if (!manual) return;
	let html =
		back() +
		'<div class="h1">' +
		esc(manual.name) +
		"</div>" +
		'<div class="meta" id="mvMeta">' +
		manualCounts() +
		"</div>";
	if (!manual.groups.length) {
		html +=
			'<div class="mvempty">' +
			'<div class="h2">Start with a header.</div>' +
			"<p>A header is a shelf you name: <em>To read</em>, <em>Lisbon</em>, <em>Favourites</em>. " +
			"Put anything under it, in the order you want.</p>" +
			'<button class="btn primary" type="button" onclick="manualAddHeader()">' +
			"Add a header</button></div>";
	} else {
		html +=
			'<div id="mvGroups">' +
			manual.groups.map(manualGroupHtml).join("") +
			"</div>" +
			'<div class="mvfoot"><button class="btn secondary" type="button" onclick="manualAddHeader()">' +
			svg("plus") +
			"Add a header</button></div>";
	}
	view.innerHTML = html;
	const root = document.getElementById("mvGroups");
	if (root) manualMountDrag(root);
}

// The layout as the page shows it right now: read from the DOM, so a drag (which
// moves real nodes) and the state can never disagree. Ids the page cannot show (an
// artifact in the trash) stay in their header, at its end.
function manualReadDom() {
	const root = document.getElementById("mvGroups");
	if (!root || !manual) return;
	const old = Object.fromEntries(manual.groups.map((g) => [g.key, g.ids]));
	const seen = new Set();
	const groups = [];
	for (const sec of root.querySelectorAll(".mvgroup")) {
		const ids = [...sec.querySelectorAll(".mvcard")].map((c) => c.dataset.id);
		ids.forEach((id) => seen.add(id));
		groups.push({ key: sec.dataset.key, ids });
	}
	for (const g of groups)
		for (const id of old[g.key] || [])
			if (!seen.has(id) && !manual.cards[id]) g.ids.push(id);
	manual.groups = groups;
	for (const sec of root.querySelectorAll(".mvgroup"))
		sec.querySelector(".mvcount").textContent = String(
			sec.querySelectorAll(".mvcard").length,
		);
	const meta = document.getElementById("mvMeta");
	if (meta) meta.innerHTML = manualCounts();
}

// Save the layout behind the change that is already on screen. Saves run in order;
// a failed one says so and reloads the view from the engine, so the page never
// shows an arrangement that was not kept. `adopt` re-reads the cards from the
// answer (needed when new artifacts joined, which the page has no cards for yet).
function manualSave(adopt) {
	if (!manual) return manualSaving;
	const id = manual.id;
	const body = JSON.stringify({
		groups: manual.groups.map((g) => ({ key: g.key, artifact_ids: g.ids })),
	});
	manualSaving = manualSaving
		.then(() =>
			api("/pivots/" + id + "/layout", {
				method: "PUT",
				headers: { "Content-Type": "application/json" },
				body,
			}),
		)
		.then((next) => {
			if (!adopt || !manual || manual.id !== id || !onSavedView(id)) return;
			Object.assign(manual, manualFromResult(next.result));
			const y = window.scrollY;
			manualRender();
			window.scrollTo(0, y);
		})
		.catch((err) => {
			toast("Not saved. " + String((err && err.message) || err), true);
			if (onSavedView(id)) runSavedGrouping(id, manual && manual.name);
		});
	return manualSaving;
}

function manualKeyOf(el) {
	const sec = el.closest(".mvgroup");
	return sec ? sec.dataset.key : null;
}

function manualNameTaken(name, exceptKey) {
	const want = name.trim().toLowerCase();
	return manual.groups.some(
		(g) => g.key !== exceptKey && mvLabel(g.key).toLowerCase() === want,
	);
}

// ---- headers ------------------------------------------------------------------

function manualAddHeader() {
	if (!manual) return;
	let name = "New header";
	for (let n = 2; manualNameTaken(name, null); n++) name = "New header " + n;
	manual.groups.push({ key: name, ids: [] });
	manualRender();
	manualSave();
	const secs = document.querySelectorAll("#mvGroups .mvgroup");
	const last = secs[secs.length - 1];
	if (!last) return;
	last.scrollIntoView({ block: "center", behavior: "smooth" });
	manualRename(last.querySelector(".mvname"), true);
}

// Rename in place: the name turns into a field where it stands. Enter or leaving
// the field keeps it; Escape puts the old name back. `fresh` selects the whole
// placeholder name so typing replaces it.
function manualRename(button, fresh) {
	if (!manual || !button) return;
	const key = manualKeyOf(button);
	const input = document.createElement("input");
	input.className = "mvname mvnameinput";
	input.value = mvLabel(key);
	input.setAttribute("aria-label", "Header name");
	input.maxLength = 120;
	button.replaceWith(input);
	input.focus();
	if (fresh) input.select();
	else input.setSelectionRange(input.value.length, input.value.length);
	let done = false;
	const finish = (keep) => {
		if (done) return;
		done = true;
		const name = input.value.trim().replace(/\s+/g, " ");
		const group = manual.groups.find((g) => g.key === key);
		if (keep && group && name && name !== mvLabel(key)) {
			if (manualNameTaken(name, key)) {
				toast('There is already a header called "' + name + '".', true);
			} else {
				group.key = name;
				manualSave();
			}
		}
		const y = window.scrollY;
		manualRender();
		window.scrollTo(0, y);
	};
	input.addEventListener("keydown", (e) => {
		if (e.key === "Enter") {
			e.preventDefault();
			finish(true);
		} else if (e.key === "Escape") {
			e.preventDefault();
			e.stopPropagation();
			finish(false);
		}
	});
	input.addEventListener("blur", () => finish(true));
}

async function manualDeleteHeader(button) {
	if (!manual) return;
	const key = manualKeyOf(button);
	const group = manual.groups.find((g) => g.key === key);
	if (!group) return;
	const count = group.ids.filter((id) => manual.cards[id]).length;
	if (count) {
		const yes = await ask(
			'Delete "' + mvLabel(key) + '"?',
			"Its " +
				count +
				" item" +
				(count === 1 ? "" : "s") +
				" leave this view. They stay in your library.",
			"Delete header",
		);
		if (!yes) return;
	}
	manual.groups = manual.groups.filter((g) => g !== group);
	const y = window.scrollY;
	manualRender();
	window.scrollTo(0, y);
	manualSave();
	toast('Deleted "' + mvLabel(key) + '".');
}

// ---- cards --------------------------------------------------------------------

function manualRemoveCard(ev, button) {
	if (ev) ev.stopPropagation();
	const cardEl = button.closest(".mvcard");
	if (!cardEl || !manual) return;
	cardEl.remove();
	manualReadDom();
	manualSave();
	toast("Removed from this view.");
}

// The keyboard and pointer-free way to move a card: pick the header it goes under.
async function manualMoveCard(ev, button) {
	if (ev) ev.stopPropagation();
	const cardEl = button.closest(".mvcard");
	if (!cardEl || !manual) return;
	const from = manualKeyOf(cardEl);
	const to = await manualPickHeader(from);
	if (to === null || to === from) return;
	const wall = [...document.querySelectorAll("#mvGroups .mvgroup")]
		.find((s) => s.dataset.key === to)
		?.querySelector(".mvwall");
	if (!wall) return;
	wall.insertBefore(cardEl, wall.querySelector(".mvadd"));
	manualReadDom();
	manualSave();
	toast('Moved to "' + mvLabel(to) + '".');
}

function manualPickHeader(currentKey) {
	const box = modalShell(
		'<h2 id="pickTitle">Move under which header?</h2>' +
			'<div class="pickgroups"></div>' +
			'<div class="asked"><button class="btn secondary" value="no">Cancel</button></div>',
		{ labelledBy: "pickTitle" },
	);
	const list = box.querySelector(".pickgroups");
	const others = manual.groups.filter((g) => g.key !== currentKey);
	for (const g of others) {
		const b = document.createElement("button");
		b.className = "btn tertiary";
		b.textContent = mvLabel(g.key);
		b.onclick = () => box.finish(g.key);
		list.appendChild(b);
	}
	if (!others.length) {
		const only = document.createElement("div");
		only.className = "aside";
		only.textContent = "There is no other header yet. Add one first.";
		list.appendChild(only);
	}
	return box.promise;
}

async function manualAddTo(button) {
	if (!manual) return;
	const key = manualKeyOf(button);
	const ids = await pickArtifacts(mvLabel(key));
	if (!ids || !ids.length) return;
	const group = manual.groups.find((g) => g.key === key);
	if (!group) return;
	const held = new Set(manual.groups.flatMap((g) => g.ids));
	group.ids.push(...ids.filter((id) => !held.has(id)));
	await manualSave(true);
	toast(
		"Added " + ids.length + " item" + (ids.length === 1 ? "" : "s") + " to \"" + mvLabel(key) + "\".",
	);
}

// Pick several artifacts at once: a search box over the library (minus what the view
// already holds), rows that toggle, and one Add. Resolves to the chosen ids, or null.
function pickArtifacts(headerLabel) {
	const box = modalShell(
		'<h2 id="pickTitle"></h2>' +
			'<input class="picksearch" type="search" placeholder="Search your library..." autocomplete="off">' +
			'<div class="pickgroups mvpick"></div>' +
			'<div class="asked">' +
			'<button class="btn secondary" value="no">Cancel</button>' +
			'<button class="btn primary" value="yes" disabled>Add</button>' +
			"</div>",
		{ labelledBy: "pickTitle", focusSel: ".picksearch" },
	);
	box.querySelector("h2").textContent = 'Add to "' + headerLabel + '"';
	const list = box.querySelector(".pickgroups");
	const field = box.querySelector(".picksearch");
	const add = box.querySelector('[value="yes"]');
	const chosen = new Set();
	let all = [];
	let loaded = false;

	const sync = () => {
		add.disabled = !chosen.size;
		add.textContent = chosen.size ? "Add " + chosen.size : "Add";
	};
	const render = () => {
		const q = field.value.trim().toLowerCase();
		list.innerHTML = "";
		const shown = (
			q ? all.filter((a) => (a.title || "").toLowerCase().includes(q)) : all
		).slice(0, 80);
		if (!shown.length) {
			const none = document.createElement("div");
			none.className = "aside";
			none.textContent = !loaded
				? "Loading..."
				: all.length
					? "Nothing matches."
					: "Everything in your library is already in this view.";
			list.appendChild(none);
			return;
		}
		for (const a of shown) {
			const b = document.createElement("button");
			b.type = "button";
			b.className = "btn tertiary mvpickrow";
			b.setAttribute("aria-pressed", String(chosen.has(a.id)));
			b.style.setProperty("--kind", "var(--kind-" + a.kind + ")");
			b.innerHTML =
				'<span class="mvtick" aria-hidden="true">' +
				svg("check") +
				"</span>" +
				'<span class="kindmark" aria-hidden="true"></span>' +
				'<span class="mvpicktitle"></span>';
			b.querySelector(".mvpicktitle").textContent = a.title || "Untitled";
			b.onclick = () => {
				if (chosen.has(a.id)) chosen.delete(a.id);
				else chosen.add(a.id);
				b.setAttribute("aria-pressed", String(chosen.has(a.id)));
				sync();
			};
			list.appendChild(b);
		}
	};
	field.addEventListener("input", render);
	// Ordered as the person picked them, not as the list happens to be sorted.
	add.onclick = () => box.finish([...chosen]);
	render();
	api("/pivot/addable", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ spec: { manual: true }, pivot_id: manual.id }),
	})
		.then((d) => {
			all = d.items || [];
			loaded = true;
			if (box.isConnected) render();
		})
		.catch(() => {
			loaded = true;
			if (box.isConnected) render();
		});
	return box.promise;
}

// ---- creating one -------------------------------------------------------------

// A new hand-arranged view, empty, or (`fromId`) started from another view's groups:
// the way to take an assistant-made view over and arrange it yourself.
async function createManualView(fromId, suggested) {
	const name = await askGroupName(
		fromId ? "Arrange this view by hand" : "New view",
		"Name this view",
		"Create",
		suggested || "",
		fromId
			? "A copy of this view that is yours to arrange: rename its headers, drag things between them, add and remove. The original stays as it is."
			: "A view you arrange yourself: make headers, put anything under them, and drag them into the order you want.",
	);
	if (!name) return;
	let made;
	try {
		made = await api("/pivots/manual", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ name, from_id: fromId || null }),
		});
	} catch (err) {
		return toast("Not created. " + String((err && err.message) || err), true);
	}
	runSavedGrouping(made.id, name);
}

// ---- dragging -----------------------------------------------------------------

let mvDrag = null;

// Animate the cards that were pushed aside by a move (first-last-invert-play): each
// one slides from where it was to where it now is, instead of jumping.
function mvFlip(els, change) {
	const before = new Map(els.map((el) => [el, el.getBoundingClientRect()]));
	change();
	if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
	for (const [el, a] of before) {
		if (!el.isConnected) continue;
		const b = el.getBoundingClientRect();
		const dx = a.left - b.left;
		const dy = a.top - b.top;
		if (!dx && !dy) continue;
		el.animate(
			[{ transform: "translate(" + dx + "px," + dy + "px)" }, { transform: "none" }],
			{ duration: 180, easing: "cubic-bezier(0.2, 0.8, 0.2, 1)" },
		);
	}
}

function manualMountDrag(root) {
	root.addEventListener("pointerdown", (e) => {
		if (e.button !== 0 || mvDrag) return;
		const grip = e.target.closest(".mvgrip");
		const cardEl = grip ? null : e.target.closest(".mvcard");
		if (!grip && (!cardEl || e.target.closest(".movebtn, .removebtn"))) return;
		const el = grip ? grip.closest(".mvgroup") : cardEl;
		mvDrag = {
			kind: grip ? "header" : "card",
			el,
			root,
			x0: e.clientX,
			y0: e.clientY,
			x: e.clientX,
			y: e.clientY,
			active: false,
			pointerId: e.pointerId,
			home: { parent: el.parentNode, next: el.nextSibling },
		};
		window.addEventListener("pointermove", mvMove);
		window.addEventListener("pointerup", mvUp);
		window.addEventListener("pointercancel", mvCancel);
		window.addEventListener("keydown", mvKey, true);
	});

	// Keyboard: a focused grip moves its header with the arrow keys; a focused card
	// moves within its header with Alt+Left/Right.
	root.addEventListener("keydown", (e) => {
		const grip = e.target.closest(".mvgrip");
		if (grip && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
			e.preventDefault();
			const sec = grip.closest(".mvgroup");
			const other =
				e.key === "ArrowUp" ? sec.previousElementSibling : sec.nextElementSibling;
			if (!other) return;
			mvFlip([...root.querySelectorAll(".mvgroup")], () =>
				root.insertBefore(sec, e.key === "ArrowUp" ? other : other.nextSibling),
			);
			manualReadDom();
			manualSave();
			sec.querySelector(".mvgrip").focus();
			return;
		}
		const cardEl = e.target.closest(".mvcard");
		if (cardEl && e.altKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
			e.preventDefault();
			const wall = cardEl.parentNode;
			const cards = [...wall.querySelectorAll(".mvcard")];
			const i = cards.indexOf(cardEl);
			const j = e.key === "ArrowLeft" ? i - 1 : i + 1;
			if (j < 0 || j >= cards.length) return;
			mvFlip(cards, () =>
				wall.insertBefore(cardEl, e.key === "ArrowLeft" ? cards[j] : cards[j].nextSibling),
			);
			manualReadDom();
			manualSave();
			(cardEl.querySelector(".card") || cardEl).focus();
		}
	});
}

function mvBegin() {
	const d = mvDrag;
	d.active = true;
	const r = d.el.getBoundingClientRect();
	document.body.classList.add("mv-dragging", "mv-dragging-" + d.kind);
	if (d.kind === "header") {
		// Reordering headers: fold every shelf to its header, so the page becomes a
		// short list to drop into, and keep the grabbed header under the pointer.
		const before = d.el.querySelector(".mvhead").getBoundingClientRect().top;
		d.root.classList.add("mvfolded");
		const after = d.el.querySelector(".mvhead").getBoundingClientRect().top;
		window.scrollBy(0, after - before);
	}
	const ghost = document.createElement("div");
	ghost.className = "mvghost mvghost-" + d.kind;
	if (d.kind === "card") {
		ghost.appendChild(d.el.querySelector(".card").cloneNode(true));
		ghost.style.width = r.width + "px";
		ghost.style.height = r.height + "px";
		d.offX = d.x0 - r.left;
		d.offY = d.y0 - r.top;
	} else {
		ghost.textContent = mvLabel(d.el.dataset.key);
		d.offX = 18;
		d.offY = 18;
	}
	document.body.appendChild(ghost);
	d.ghost = ghost;
	d.el.classList.add("mvlifted");
	d.scroller = requestAnimationFrame(mvAutoScroll);
}

function mvPlace() {
	const d = mvDrag;
	d.ghost.style.transform =
		"translate(" + (d.x - d.offX) + "px," + (d.y - d.offY) + "px)";
	if (d.kind === "header") {
		const secs = [...d.root.querySelectorAll(".mvgroup")].filter((s) => s !== d.el);
		const before = secs.find((s) => {
			const r = s.querySelector(".mvhead").getBoundingClientRect();
			return d.y < r.top + r.height / 2;
		});
		if ((before || null) === d.el.nextElementSibling) return;
		mvFlip([...d.root.querySelectorAll(".mvgroup")], () =>
			d.root.insertBefore(d.el, before || null),
		);
		return;
	}
	const under = document.elementFromPoint(d.x, d.y);
	const sec = under && under.closest(".mvgroup");
	const wall = sec && sec.querySelector(".mvwall");
	if (!wall) return;
	const cards = [...wall.querySelectorAll(".mvcard")].filter((c) => c !== d.el);
	// Reading order: the first card the pointer is before - above its row, or in its
	// row and left of its middle. None means the end, just before the Add tile.
	const before =
		cards.find((c) => {
			const r = c.getBoundingClientRect();
			return d.y < r.top || (d.y < r.bottom && d.x < r.left + r.width / 2);
		}) || wall.querySelector(".mvadd");
	if (before === d.el.nextElementSibling && d.el.parentNode === wall) return;
	const affected = [
		...new Set([...d.el.parentNode.querySelectorAll(".mvcard"), ...cards]),
	].filter((c) => c !== d.el);
	mvFlip(affected, () => wall.insertBefore(d.el, before));
}

function mvAutoScroll() {
	const d = mvDrag;
	if (!d || !d.active) return;
	const edge = 90;
	if (d.y < edge) window.scrollBy(0, -Math.ceil((edge - d.y) / 6));
	else if (d.y > window.innerHeight - edge)
		window.scrollBy(0, Math.ceil((d.y - (window.innerHeight - edge)) / 6));
	mvPlace();
	d.scroller = requestAnimationFrame(mvAutoScroll);
}

function mvMove(e) {
	const d = mvDrag;
	if (!d || e.pointerId !== d.pointerId) return;
	d.x = e.clientX;
	d.y = e.clientY;
	if (!d.active) {
		if (Math.hypot(d.x - d.x0, d.y - d.y0) < 6) return;
		mvBegin();
	}
	e.preventDefault();
}

function mvEnd(keep) {
	const d = mvDrag;
	if (!d) return;
	mvDrag = null;
	window.removeEventListener("pointermove", mvMove);
	window.removeEventListener("pointerup", mvUp);
	window.removeEventListener("pointercancel", mvCancel);
	window.removeEventListener("keydown", mvKey, true);
	if (!d.active) return;
	cancelAnimationFrame(d.scroller);
	d.ghost.remove();
	d.el.classList.remove("mvlifted");
	document.body.classList.remove("mv-dragging", "mv-dragging-card", "mv-dragging-header");
	if (d.kind === "header") {
		const top = d.el.querySelector(".mvhead").getBoundingClientRect().top;
		d.root.classList.remove("mvfolded");
		window.scrollBy(0, d.el.querySelector(".mvhead").getBoundingClientRect().top - top);
	}
	if (!keep) d.home.parent.insertBefore(d.el, d.home.next);
	// A drag ends with a click on whatever is under the pointer; that click must not
	// open the card that was just dropped.
	const swallow = (ev) => {
		ev.stopPropagation();
		ev.preventDefault();
	};
	window.addEventListener("click", swallow, { capture: true, once: true });
	setTimeout(() => window.removeEventListener("click", swallow, true), 0);
	if (keep) {
		manualReadDom();
		manualSave();
	}
}

function mvUp(e) {
	if (mvDrag && e.pointerId === mvDrag.pointerId) mvEnd(true);
}
function mvCancel() {
	mvEnd(false);
}
function mvKey(e) {
	if (e.key === "Escape" && mvDrag && mvDrag.active) {
		e.preventDefault();
		e.stopPropagation();
		mvEnd(false);
	}
}
