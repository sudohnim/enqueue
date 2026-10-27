const ICONS = {
	plus: '<path d="M12 5v14M5 12h14"/>',
	check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
	// Six dots: the handle a header is dragged by.
	grip: '<circle cx="9" cy="6" r="1.1"/><circle cx="15" cy="6" r="1.1"/><circle cx="9" cy="12" r="1.1"/><circle cx="15" cy="12" r="1.1"/><circle cx="9" cy="18" r="1.1"/><circle cx="15" cy="18" r="1.1"/>',
	find: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
	// The eye, not a question mark. Asking here is not a support request; it is looking
	// at what you already own and seeing what is in it.
	ask: '<path d="M2.2 12S5.8 5.6 12 5.6 21.8 12 21.8 12 18.2 18.4 12 18.4 2.2 12 2.2 12z"/><circle cx="12" cy="12" r="2.8"/>',
	// Organize: four panes over the whole library, answering like search and ask do.
	// Search narrows, ask converses, organize rearranges.
	grid: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
	back: '<path d="M14.5 6.5L9 12l5.5 5.5"/>',
	// The note editor's formatting bar (js/artifact.js edbarHtml), in the same line
	// grammar as everything else: no filled glyphs, no letterforms borrowed from a font.
	bold: '<path d="M7.5 5h5.6a3.4 3.4 0 0 1 0 6.8H7.5z"/><path d="M7.5 11.8h6.6a3.6 3.6 0 0 1 0 7.2H7.5z"/>',
	italic: '<path d="M10.5 5h7"/><path d="M6.5 19h7"/><path d="M14 5l-4 14"/>',
	heading: '<path d="M5 5.5v13"/><path d="M15 5.5v13"/><path d="M5 12h10"/><path d="M19 9v9.5"/>',
	subheading: '<path d="M6 9v9.5"/><path d="M13.5 9v9.5"/><path d="M6 13.8h7.5"/><path d="M17.5 12.5v6"/>',
	bullets: '<circle cx="5" cy="7" r="1.1"/><circle cx="5" cy="12" r="1.1"/><circle cx="5" cy="17" r="1.1"/><path d="M10 7h10"/><path d="M10 12h10"/><path d="M10 17h10"/>',
	numbers: '<path d="M10.5 7h9.5"/><path d="M10.5 12h9.5"/><path d="M10.5 17h9.5"/><path d="M4.3 6l1.5-.9v4.4"/><path d="M4.1 14.6c.5-1 2.4-.9 2.4.4 0 1.1-2.4 1.7-2.4 3.2h2.6"/>',
	indent: '<path d="M4 6h16"/><path d="M11 12h9"/><path d="M4 18h16"/><path d="M4 9.8l3 2.2-3 2.2"/>',
	outdent: '<path d="M4 6h16"/><path d="M11 12h9"/><path d="M4 18h16"/><path d="M7.2 9.8l-3 2.2 3 2.2"/>',
	quote: '<path d="M5 6v12"/><path d="M10 8h10"/><path d="M10 12h10"/><path d="M10 16h6"/>',
	code: '<path d="M8.5 7.5L4 12l4.5 4.5"/><path d="M15.5 7.5L20 12l-4.5 4.5"/><path d="M13.4 5.5l-2.8 13"/>',
	chev: '<path d="M6.5 14.5L12 9l5.5 5.5"/>',
	down: '<path d="M12 4v11"/><path d="M7.5 10.5L12 15l4.5-4.5"/><path d="M5 19h14"/>',
	home: '<path d="M4 10.5L12 4l8 6.5"/><path d="M6 9.6V20h12V9.6"/>',
	star: '<path d="M12 4.2l2.3 4.9 5.2.7-3.8 3.7 1 5.3-4.7-2.6-4.7 2.6 1-5.3-3.8-3.7 5.2-.7z"/>',
	trash:
		'<path d="M4 7h16"/><path d="M9.5 7V5h5v2"/><path d="M6.5 7l1 13h9l1-13"/>',
	close: '<path d="M6 6l12 12M18 6L6 18"/>',
	// A folder tab over a sheet: "add a tab" in a note's formatting bar.
	tab: '<path d="M4 9V6a1 1 0 0 1 1-1h5l2 3h7a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z"/><path d="M4 9h16"/>',
	lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
	// Move/redistribute: two horizontal arrows pointing outward - one left, one
	// right. Reads as "move this artifact to another place".
	move: '<path d="M3 8h13"/><path d="M12 4l4 4-4 4"/><path d="M21 16H8"/><path d="M12 12l-4 4 4 4"/>',
	note: '<path d="M4 4h11l5 5v11H4z"/><path d="M15 4v5h5"/>',
	upload:
		'<path d="M12 16V4"/><path d="M7 9l5-5 5 5"/><path d="M4 17v3h16v-3"/>',
	link: '<path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1"/>',
	image:
		'<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-7 7"/>',
	gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
	// The rename pencil (K.7/L.3b): a quiet ghost beside a saved-grouping title, not a
	// gear or a menu - renaming is an act on one grouping while you look at it.
	pencil:
		'<path d="M4 20l4.5-1 10-10-3.5-3.5-10 10z"/><path d="M14 6.5l3.5 3.5"/>',
	// The drawer toggle: a double chevron pointing at the drawer. Closed, it points
	// into the content (the drawer lives off the right edge, so it invites you to
	// pull it in); open, it points back out, inviting you to push it away. One
	// button, two directions, read at a glance.
	// The Details toggle: the same mark as the phone's (mobile.html).
	info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8h.01"/>',
	panelin:
		'<path d="M13.5 6.5L8 12l5.5 5.5"/><path d="M19 6.5L13.5 12l5.5 5.5"/>',
	panelout:
		'<path d="M5.5 6.5L11 12l-5.5 5.5"/><path d="M11 6.5L16.5 12 11 17.5"/>',
	// The conversations menu in the eye panel: a plain list, three rules, the last
	// short so it reads as a list and not a hamburger nav.
	list: '<path d="M4 7h16"/><path d="M4 12h16"/><path d="M4 17h10"/>',
	// Send a message: an upward arrow, the same stroke as the rest, so the composer's
	// one violet control still speaks the icon system's language.
	send: '<path d="M12 20V5"/><path d="M6 11l6-6 6 6"/>',
	// Regenerate a summary: a circular arrow. Two arcs with a small arrowhead so it
	// reads as "run this again", not a loading spinner.
	refresh:
		'<path d="M20 11a8 8 0 1 0-.9 4.5"/><path d="M20 5v6h-6"/>',
};
const svg = (k) => '<svg viewBox="0 0 24 24">' + ICONS[k] + "</svg>";
