  const ICONS = {
    plus: '<path d="M12 5v14M5 12h14"/>',
    find: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
    // The eye, not a question mark. Asking here is not a support request; it is looking
    // at what you already own and seeing what is in it.
    ask: '<path d="M2.2 12S5.8 5.6 12 5.6 21.8 12 21.8 12 18.2 18.4 12 18.4 2.2 12 2.2 12z"/><circle cx="12" cy="12" r="2.8"/>',
    // Organize: four panes over the whole library, answering like search and ask do.
    // Search narrows, ask converses, organize rearranges.
    grid: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
    back: '<path d="M14.5 6.5L9 12l5.5 5.5"/>',
    chev: '<path d="M6.5 14.5L12 9l5.5 5.5"/>',
    down: '<path d="M12 4v11"/><path d="M7.5 10.5L12 15l4.5-4.5"/><path d="M5 19h14"/>',
    home: '<path d="M4 10.5L12 4l8 6.5"/><path d="M6 9.6V20h12V9.6"/>',
    star: '<path d="M12 4.2l2.3 4.9 5.2.7-3.8 3.7 1 5.3-4.7-2.6-4.7 2.6 1-5.3-3.8-3.7 5.2-.7z"/>',
    trash:
      '<path d="M4 7h16"/><path d="M9.5 7V5h5v2"/><path d="M6.5 7l1 13h9l1-13"/>',
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
    // Move/redistribute: two horizontal arrows pointing outward - one left, one
    // right. Reads as "move this artifact to another place".
    move: '<path d="M3 8h13"/><path d="M12 4l4 4-4 4"/><path d="M21 16H8"/><path d="M12 12l-4 4 4 4"/>',
    note: '<path d="M4 4h11l5 5v11H4z"/><path d="M15 4v5h5"/>',
    upload:
      '<path d="M12 16V4"/><path d="M7 9l5-5 5 5"/><path d="M4 17v3h16v-3"/>',
    link: '<path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1"/>',
    image:
      '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-7 7"/>',
    gear: '<circle cx="12" cy="12" r="3.2"/><path d="M12 2v3M12 19v3M22 12h-3M5 12H2M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1M18.4 18.4l-2.1-2.1M7.7 7.7L5.6 5.6"/>',
    // The rename pencil (K.7/L.3b): a quiet ghost beside a saved-grouping title, not a
    // gear or a menu - renaming is an act on one grouping while you look at it.
    pencil:
      '<path d="M4 20l4.5-1 10-10-3.5-3.5-10 10z"/><path d="M14 6.5l3.5 3.5"/>',
    // The drawer toggle: a double chevron pointing at the drawer. Closed, it points
    // into the content (the drawer lives off the right edge, so it invites you to
    // pull it in); open, it points back out, inviting you to push it away. One
    // button, two directions, read at a glance.
    panelin:
      '<path d="M13.5 6.5L8 12l5.5 5.5"/><path d="M19 6.5L13.5 12l5.5 5.5"/>',
    panelout:
      '<path d="M5.5 6.5L11 12l-5.5 5.5"/><path d="M11 6.5L16.5 12 11 17.5"/>',
  };
  const svg = (k) => '<svg viewBox="0 0 24 24">' + ICONS[k] + "</svg>";

