// Tabs on a note's sheet (desktop): the strip, switching, adding, renaming by
// double-click, reordering by drag, making a tab its own note, and deleting one.
//
// How tabs are kept is js/tabs.js: marker lines in the note's markdown. The editor
// holds ONE tab's text at a time; `ctx.tabs` ({pre, tabs:[{name, text}]}) holds the
// rest, and `noteText()` puts the note back together for every save, the title, the
// drafts comparison and the dirty check. A note with one tab is a plain note again,
// and the strip disappears.
//
// Dragging is pointer events, not HTML5 drag and drop, which the desktop WebView
// handles inconsistently and which owns file drops (the same call as manual.js).

// The whole note as markdown: the tab in the editor read fresh, the others as kept.
function noteText(ed) {
	const editor = ed || document.getElementById("body");
	if (!ctx || ctx.kind !== "note" || !ctx.tabs) return htmlToMd(editor);
	const tabs = ctx.tabs.tabs.map((t, i) =>
		i === ctx.tabAt ? { name: t.name, text: htmlToMd(editor) } : t,
	);
	return Tabs.join(ctx.tabs.pre, tabs);
}

const NoteTabs = (() => {
	const POP_ICON = '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>';
	const icon = (paths) =>
		'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
		paths +
		"</svg>";

	function remember() {
		try {
			sessionStorage.setItem("enqueue.tab." + ctx.id, String(ctx.tabAt));
		} catch (e) {
			/* storage may be unavailable */
		}
	}

	// Where the next opening of a note should land, from the search hit that opened it.
	// Used once.
	let pending = null;

	function hint(id, query, snippet) {
		pending = { id, query, snippet };
	}

	function recalled(id, count, parsed) {
		const h = pending && pending.id === id ? pending : null;
		pending = null;
		if (h && parsed) {
			const found = Tabs.find(parsed, h.query, h.snippet);
			if (found >= 0) return found;
		}
		let at = 0;
		try {
			at = parseInt(sessionStorage.getItem("enqueue.tab." + id) || "0", 10) || 0;
		} catch (e) {
			at = 0;
		}
		return Math.max(0, Math.min(at, count - 1));
	}

	// Keep what the editor holds in the tab it belongs to.
	function capture() {
		const ed = document.getElementById("body");
		if (ctx && ctx.tabs && ed) ctx.tabs.tabs[ctx.tabAt].text = htmlToMd(ed);
	}

	function fill(text) {
		const ed = document.getElementById("body");
		if (!ed) return;
		ed.innerHTML = md(text || "") || "<p><br></p>";
		ed.scrollTop = 0;
	}

	// Focus the editor with the caret INSIDE its first block. A plain focus() on an
	// empty tab put the caret on the editable's own edge, outside the seeded paragraph,
	// so the first keystroke landed in a bare text node and each one after it was
	// wrapped in a paragraph of its own: one line per character (mountEditor guards the
	// same thing for a new note).
	function focusEditor() {
		const ed = document.getElementById("body");
		if (!ed) return;
		ed.focus({ preventScroll: true });
		let block = ed.firstElementChild;
		while (block && block.firstElementChild && /^(UL|OL|LI|BLOCKQUOTE)$/.test(block.tagName))
			block = block.firstElementChild;
		if (!block) return;
		const r = document.createRange();
		r.setStart(block, 0);
		r.collapse(true);
		const sel = window.getSelection();
		sel.removeAllRanges();
		sel.addRange(r);
	}

	function render() {
		const strip = document.getElementById("notetabs");
		if (!strip || !ctx || ctx.kind !== "note") return;
		const sheet = document.querySelector(".docpane.notesheet");
		if (!ctx.tabs) {
			strip.hidden = true;
			strip.innerHTML = "";
			if (sheet) sheet.classList.remove("tabbed");
			return;
		}
		strip.hidden = false;
		if (sheet) sheet.classList.add("tabbed");
		strip.innerHTML =
			ctx.tabs.tabs
				.map((t, i) => {
					const on = i === ctx.tabAt;
					return (
						'<div class="ntab" role="tab" tabindex="' +
						(on ? "0" : "-1") +
						'" aria-selected="' +
						String(on) +
						'" data-at="' +
						i +
						'" title="' +
						(on ? "Double-click to rename, drag to move" : "") +
						'"><span class="ntab-name">' +
						esc(t.name) +
						"</span>" +
						(on
							? '<span class="ntab-tools">' +
								'<button type="button" class="ntab-tool" data-act="pop" tabindex="-1" aria-label="Make ' +
								esc(t.name) +
								' its own note" title="Make it its own note">' +
								icon(POP_ICON) +
								"</button>" +
								'<button type="button" class="ntab-tool" data-act="close" tabindex="-1" aria-label="Delete the tab ' +
								esc(t.name) +
								'" title="Delete tab">' +
								svg("close") +
								"</button></span>"
							: "") +
						"</div>"
					);
				})
				.join("") +
			'<button type="button" class="ntab-add" aria-label="Add a tab" title="Add a tab">' +
			svg("plus") +
			"</button>";
	}

	function show(i) {
		if (!ctx || !ctx.tabs || i === ctx.tabAt || i < 0 || i >= ctx.tabs.tabs.length) return;
		capture();
		ctx.tabAt = i;
		remember();
		fill(ctx.tabs.tabs[i].text);
		render();
	}

	// A change to the tabs themselves (not their text) is saved at once.
	function changed() {
		render();
		if (typeof refreshTitleHeader === "function") refreshTitleHeader();
		if (typeof saveBody === "function") saveBody();
	}

	function add() {
		if (!ctx || ctx.kind !== "note") return;
		const ed = document.getElementById("body");
		if (!ctx.tabs) {
			// The note so far becomes its first tab; its title heading stays above.
			ctx.tabs = Tabs.start(htmlToMd(ed));
			ctx.tabAt = 0;
		} else capture();
		ctx.tabs.tabs.push({ name: "Untitled", text: "" });
		ctx.tabAt = ctx.tabs.tabs.length - 1;
		remember();
		fill("");
		render();
		rename(ctx.tabAt);
	}

	function rename(i) {
		const tab = document.querySelector('.ntab[data-at="' + i + '"]');
		if (!tab || tab.querySelector("input")) return;
		const name = tab.querySelector(".ntab-name");
		const was = ctx.tabs.tabs[i].name;
		const input = document.createElement("input");
		input.className = "ntab-input";
		input.value = was === "Untitled" ? "" : was;
		input.placeholder = "Tab name";
		input.setAttribute("aria-label", "Tab name");
		input.size = Math.max(6, input.value.length + 1);
		name.replaceWith(input);
		tab.classList.add("editing");
		input.focus();
		input.select();
		let done = false;
		const finish = (keep) => {
			if (done) return;
			done = true;
			const value = Tabs.clean(input.value);
			if (keep && input.value.trim() && value !== was) {
				ctx.tabs.tabs[i].name = value;
				changed();
			} else {
				if (keep && was === "Untitled") changed(); // a new tab is saved even unnamed
				else render();
			}
			focusEditor();
		};
		input.addEventListener("input", () => (input.size = Math.max(6, input.value.length + 1)));
		input.addEventListener("keydown", (e) => {
			e.stopPropagation();
			if (e.key === "Enter") {
				e.preventDefault();
				finish(true);
			} else if (e.key === "Escape") {
				e.preventDefault();
				finish(false);
			}
		});
		input.addEventListener("blur", () => finish(true));
	}

	// Down to one tab, the note is plain again: that tab's text joins the title.
	function collapseIfOne() {
		if (ctx.tabs && ctx.tabs.tabs.length <= 1) {
			const body = Tabs.join(ctx.tabs.pre, ctx.tabs.tabs);
			ctx.tabs = null;
			ctx.tabAt = 0;
			fill(body);
		}
	}

	async function remove(i) {
		capture();
		const t = ctx.tabs.tabs[i];
		if (t.text.trim()) {
			const yes = await ask(
				"Delete the tab “" + t.name + "”?",
				"Its text goes with it. It stays in this note's drafts if you need it back.",
				"Delete tab",
			);
			if (!yes) return;
		}
		ctx.tabs.tabs.splice(i, 1);
		ctx.tabAt = Math.min(ctx.tabAt, ctx.tabs.tabs.length - 1);
		remember();
		fill(ctx.tabs.tabs[ctx.tabAt].text);
		collapseIfOne();
		changed();
	}

	async function popOut(i) {
		capture();
		const t = ctx.tabs.tabs[i];
		const id = ctx.id;
		let made;
		try {
			made = await api("/notes", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ body: "# " + t.name + (t.text.trim() ? "\n\n" + t.text : "") }),
			});
		} catch (err) {
			return toast(String((err && err.message) || err), true);
		}
		if (!ctx || ctx.id !== id) return;
		ctx.tabs.tabs.splice(i, 1);
		ctx.tabAt = Math.min(ctx.tabAt, ctx.tabs.tabs.length - 1);
		remember();
		fill(ctx.tabs.tabs[ctx.tabAt].text);
		collapseIfOne();
		changed();
		toast("“" + t.name + "” is its own note now.");
		void made;
	}

	// ---- dragging to reorder ------------------------------------------------------
	function startDrag(e, tab) {
		const strip = document.getElementById("notetabs");
		const from = +tab.dataset.at;
		const startX = e.clientX;
		let moving = false;
		let to = from;
		const tabs = [...strip.querySelectorAll(".ntab")];
		const boxes = tabs.map((t) => t.getBoundingClientRect());
		const move = (ev) => {
			const dx = ev.clientX - startX;
			if (!moving && Math.abs(dx) < 5) return;
			if (!moving) {
				moving = true;
				tab.classList.add("dragging");
				tab.setPointerCapture?.(ev.pointerId);
			}
			tab.style.transform = "translateX(" + dx + "px)";
			const x = boxes[from].left + boxes[from].width / 2 + dx;
			to = from;
			boxes.forEach((b, k) => {
				const mid = b.left + b.width / 2;
				if (k < from && x < mid) to = Math.min(to, k);
				if (k > from && x > mid) to = Math.max(to, k);
			});
			// Neighbours slide out of the way, so the gap shows where it lands.
			const shift = boxes[from].width + 4;
			tabs.forEach((t, k) => {
				if (k === from) return;
				const off = from < to && k > from && k <= to ? -shift : from > to && k >= to && k < from ? shift : 0;
				t.style.transform = off ? "translateX(" + off + "px)" : "";
			});
		};
		const up = () => {
			document.removeEventListener("pointermove", move);
			document.removeEventListener("pointerup", up);
			document.removeEventListener("pointercancel", up);
			tabs.forEach((t) => (t.style.transform = ""));
			tab.classList.remove("dragging");
			if (!moving) return show(from);
			if (to === from) return render();
			capture();
			const active = ctx.tabs.tabs[ctx.tabAt];
			const [moved] = ctx.tabs.tabs.splice(from, 1);
			ctx.tabs.tabs.splice(to, 0, moved);
			ctx.tabAt = ctx.tabs.tabs.indexOf(active);
			remember();
			changed();
		};
		document.addEventListener("pointermove", move);
		document.addEventListener("pointerup", up);
		document.addEventListener("pointercancel", up);
	}

	function mount() {
		const strip = document.getElementById("notetabs");
		if (!strip || strip.dataset.wired) return render();
		strip.dataset.wired = "1";
		strip.addEventListener("pointerdown", (e) => {
			if (e.button !== 0) return;
			const tool = e.target.closest(".ntab-tool, .ntab-add, input");
			if (tool) return;
			const tab = e.target.closest(".ntab");
			if (!tab) return;
			e.preventDefault(); // keep the editor's caret where it is until a tab is chosen
			startDrag(e, tab);
		});
		strip.addEventListener("click", (e) => {
			const add_ = e.target.closest(".ntab-add");
			if (add_) return add();
			const tool = e.target.closest(".ntab-tool");
			if (!tool) return;
			const i = +tool.closest(".ntab").dataset.at;
			if (tool.dataset.act === "pop") popOut(i);
			else remove(i);
		});
		strip.addEventListener("dblclick", (e) => {
			const tab = e.target.closest(".ntab");
			if (tab && !e.target.closest(".ntab-tool")) rename(+tab.dataset.at);
		});
		// Arrow keys move between tabs, as a tab list should.
		strip.addEventListener("keydown", (e) => {
			const tab = e.target.closest(".ntab");
			if (!tab || !ctx.tabs) return;
			const n = ctx.tabs.tabs.length;
			if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
				e.preventDefault();
				show((ctx.tabAt + (e.key === "ArrowRight" ? 1 : n - 1)) % n);
				document.querySelector('.ntab[aria-selected="true"]')?.focus();
			} else if (e.key === "Enter" || e.key === "F2") {
				e.preventDefault();
				rename(ctx.tabAt);
			}
		});
		render();
	}

	return { mount, render, add, show, recalled, hint };
})();
