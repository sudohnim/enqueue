// The tour (TOUR.1): "How Enqueue works", opened from the ? on the home header.
//
// Seven cards, about a minute, each with a small WORKING demo rather than a screenshot:
// you type into the capture box, pick a search, ask the eye, rewrite a summary line,
// gather a view. Nothing in it touches the library - the demos run on a handful of
// made-up artifacts, and say so where you type.
//
// One script and one stylesheet (css/tour.css) for the desktop home and the phone. The
// words, the order and the examples live here once, so the two never tell different
// stories; a card only changes the words that are true of one device (click or tap, the
// hotkey or the + menu). Each shell calls Tour.attach with its platform.
//
// It is opened on request and never by itself. Until it has been opened once, the ?
// carries a small accent bead. The vault is left out on purpose: its door is unmarked,
// and a tour anyone holding the device can open is no place to mark it.
(function () {
  const VERSION = 1; // bump when the tour changes enough to put the bead back
  const SEEN = "enq.tourSeen.v" + VERSION;
  const NS = "http://www.w3.org/2000/svg";
  const EASE = "cubic-bezier(0.16, 1, 0.3, 1)";

  // The icon set's 24px stroke grammar; a three-number entry is a circle.
  const ICONS = {
    help: ["M9.2 9.2a2.9 2.9 0 0 1 5.6 1c0 1.9-2.8 2.4-2.8 4.3", "M12 17.6v.01"],
    close: ["M6 6l12 12M18 6L6 18"],
    find: [[11, 11, 7], "M20 20l-3.5-3.5"],
    laptop: ["M5 5.5h14a1 1 0 0 1 1 1V15H4V6.5a1 1 0 0 1 1-1z", "M2.5 18.5h19"],
    phone: ["M8.5 3h7A1.5 1.5 0 0 1 17 4.5v15a1.5 1.5 0 0 1-1.5 1.5h-7A1.5 1.5 0 0 1 7 19.5v-15A1.5 1.5 0 0 1 8.5 3z", "M11 17.8h2"],
    lock: ["M8 11V8.2a4 4 0 0 1 8 0V11", "M6.5 11h11v8.5h-11z"],
  };
  const EYE_OUTLINE =
    "M2.2 12S5.8 5.6 12 5.6 21.8 12 21.8 12 18.2 18.4 12 18.4 2.2 12 2.2 12z";

  let opts = { platform: "desktop", hotkey: "Alt+Shift+E", assets: "/static/" };
  let stage = null;
  let parts = null;
  let index = 0;
  let cleanup = null;
  let lastFocus = null;
  let hidden = [];

  const still = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---- small builders ---------------------------------------------------------------
  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  function icon(name) {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", "tour-ico");
    for (const d of ICONS[name]) {
      const shape = document.createElementNS(NS, Array.isArray(d) ? "circle" : "path");
      if (Array.isArray(d)) {
        shape.setAttribute("cx", d[0]);
        shape.setAttribute("cy", d[1]);
        shape.setAttribute("r", d[2]);
      } else {
        shape.setAttribute("d", d);
      }
      svg.appendChild(shape);
    }
    return svg;
  }
  const KIND_WORD = { note: "note", link: "link", pdf: "pdf", image: "image", file: "file" };
  function kindRow(kind) {
    const row = el("span", "tour-kind");
    row.append(el("i"), el("span", null, KIND_WORD[kind]));
    return row;
  }
  // The miniature of a wall tile: kind dot and word, the title, an optional last line.
  function tile(kind, title, meta) {
    const t = el("div", "tour-tile");
    t.dataset.kind = kind;
    t.append(kindRow(kind), el("div", "tour-tile-title", title));
    if (meta) t.append(el("div", "tour-tile-meta", meta));
    return t;
  }
  function button(cls, label) {
    const b = el("button", "tour-btn " + cls, label);
    b.type = "button";
    return b;
  }
  // "Alt+Shift+E" as the keys a Mac prints on its caps.
  function keycaps(combo) {
    const glyph = { alt: "⌥", option: "⌥", shift: "⇧", cmd: "⌘", command: "⌘", super: "⌘", meta: "⌘", ctrl: "⌃", control: "⌃", cmdorctrl: "⌘", commandorcontrol: "⌘" };
    const frag = document.createDocumentFragment();
    for (const part of String(combo || "").split("+")) {
      const key = part.trim();
      if (!key) continue;
      frag.append(el("kbd", "tour-key", glyph[key.toLowerCase()] || key.toUpperCase()));
    }
    return frag;
  }
  // Text with keycaps in it: strings and {keys: "Alt+Shift+E"} in reading order.
  function rich(node, pieces) {
    for (const piece of pieces) {
      if (typeof piece === "string") node.append(piece);
      else node.append(keycaps(piece.keys));
    }
    return node;
  }
  // Pick one of a few examples: a row of chips, the first chosen to begin with.
  function choices(labels, onPick) {
    const row = el("div", "tour-chips");
    const chips = labels.map((label, i) => {
      const chip = el("button", "tour-chip", label);
      chip.type = "button";
      chip.setAttribute("aria-pressed", "false");
      chip.addEventListener("click", () => pick(i));
      row.append(chip);
      return chip;
    });
    function pick(i) {
      chips.forEach((c, n) => c.setAttribute("aria-pressed", String(n === i)));
      onPick(i);
    }
    return { row, pick };
  }
  // Move things, then let them glide from where they were (FLIP).
  function glide(nodes, change) {
    const before = new Map(nodes.map((n) => [n, n.getBoundingClientRect()]));
    change();
    if (still()) return;
    for (const n of nodes) {
      const a = before.get(n);
      const b = n.getBoundingClientRect();
      const dx = a.left - b.left;
      const dy = a.top - b.top;
      if (!dx && !dy) continue;
      n.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }], {
        duration: 460,
        easing: EASE,
      });
    }
  }
  function rise(node, i) {
    node.classList.add("tour-rise");
    node.style.setProperty("--i", i || 0);
    return node;
  }

  // ---- the seven demos --------------------------------------------------------------
  // Each fills the plate it is given and may return a function that stops what it started.

  function demoWelcome(plate) {
    plate.classList.add("bare");
    const wrap = el("div", "tour-welcome");
    const raven = el("img", "tour-raven");
    raven.src = opts.assets + "raven-mark.png";
    raven.alt = "";
    const pile = el("div", "tour-pile");
    [
      tile("note", "Lift heavier each week", "just now"),
      tile("pdf", "Why forests need small fires", "yesterday"),
      tile("link", "Time Out Market, Lisbon", "3 days ago"),
      tile("image", "Whiteboard, Tuesday", "last week"),
    ].forEach((t, i) => {
      t.style.setProperty("--i", i);
      pile.append(t);
    });
    wrap.append(raven, pile);
    plate.append(wrap);
  }

  function demoCapture(plate) {
    const phone = opts.platform === "mobile";
    const wrap = el("div", "tour-cap");
    const card = el("form", "tour-cap-card");
    const head = el("div", "tour-cap-head");
    const raven = el("img");
    raven.src = opts.assets + "raven-mark.png";
    raven.alt = "";
    const heading = el("strong", null, "Capture your thoughts");
    heading.append(el("span", "tour-accent", "."));
    head.append(raven, heading);
    const input = el("input", "tour-input");
    input.type = "text";
    input.placeholder = "A thought, a link, or markdown";
    input.setAttribute("aria-label", "Try a capture. Nothing typed here is saved.");
    input.autocomplete = "off";
    input.enterKeyHint = "done";
    const row = el("div", "tour-cap-row");
    const hint = el("span");
    if (phone) hint.textContent = "+ in the pill, then Note";
    else rich(hint, [{ keys: opts.hotkey }, " from anywhere"]);
    const save = button("primary", "Save");
    save.type = "submit";
    row.append(hint, save);
    card.append(head, input, row);

    const wall = el("div", "tour-cap-wall");
    const empty = el("p", "tour-cap-empty", "It lands on your wall, newest first.");
    wall.append(empty);
    const room = phone ? 2 : 3;
    card.addEventListener("submit", (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return input.focus();
      const link = /^(https?:\/\/|www\.)\S+$/i.test(text);
      const title = link ? text.replace(/^https?:\/\//i, "").replace(/^www\./i, "").split(/[/?#]/)[0] : text;
      const t = tile(link ? "link" : "note", title.length > 60 ? title.slice(0, 58) + "…" : title, "just now");
      t.classList.add("tour-land");
      empty.remove();
      wall.prepend(t);
      while (wall.children.length > room) wall.lastElementChild.remove();
      input.value = "";
      raven.classList.remove("tour-hop");
      void raven.offsetWidth; // restart the hop if it is still playing
      raven.classList.add("tour-hop");
    });
    wrap.append(card, wall);
    plate.append(wrap);
  }

  function demoFind(plate) {
    const QUERIES = [
      {
        q: "getting stronger from stress",
        hits: [
          ["note", "Lift heavier each week", "by your meaning"],
          ["pdf", "Why forests need small fires", "by the idea"],
        ],
      },
      { q: "hydro", hits: [["note", "Hydroponics shopping list", "by part of a word"]] },
      { q: "pecan pie recipes", hits: [] },
    ];
    const wrap = el("div", "tour-find");
    const field = el("div", "tour-field");
    const typed = el("span");
    field.append(icon("find"), typed);
    const results = el("div", "tour-results");
    results.setAttribute("aria-live", "polite");
    let timer = 0;
    function show(i) {
      const { q, hits } = QUERIES[i];
      clearInterval(timer);
      results.replaceChildren();
      const done = () => {
        typed.textContent = q;
        if (!hits.length) {
          const none = el("p", "tour-none");
          none.append(el("strong", null, "Nothing found."), "You never saved anything about that, so it says so.");
          results.append(rise(none, 0));
          return;
        }
        hits.forEach(([kind, title, why], n) => {
          const hit = tile(kind, title);
          hit.classList.add("tour-hit");
          hit.append(el("span", "tour-why", why));
          results.append(rise(hit, n));
        });
      };
      if (still()) return done();
      // Typed by the clock, not by the tick, so a throttled timer cannot stall it.
      const began = performance.now();
      typed.textContent = "";
      timer = setInterval(() => {
        const n = Math.floor((performance.now() - began) / 22);
        typed.textContent = q.slice(0, n);
        if (n >= q.length) {
          clearInterval(timer);
          done();
        }
      }, 22);
    }
    const picker = choices(QUERIES.map((x) => x.q), show);
    wrap.append(field, picker.row, results);
    plate.append(wrap);
    picker.pick(0);
    return () => clearInterval(timer);
  }

  // The ask eye, drawn here so the card owns it: it watches the pointer and blinks.
  function eye() {
    const box = el("div", "tour-eye");
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    const lid = document.createElementNS(NS, "path");
    lid.setAttribute("d", EYE_OUTLINE);
    const iris = document.createElementNS(NS, "circle");
    iris.setAttribute("cx", 12);
    iris.setAttribute("cy", 12);
    iris.setAttribute("r", 3.4);
    svg.append(lid, iris);
    box.append(svg);
    const look = (e) => {
      const r = box.getBoundingClientRect();
      const dx = e.clientX - (r.left + r.width / 2);
      const dy = e.clientY - (r.top + r.height / 2);
      const far = Math.hypot(dx, dy) || 1;
      const reach = Math.min(1, far / 220);
      iris.style.transform = `translate(${(dx / far) * 2.6 * reach}px, ${(dy / far) * 1.5 * reach}px)`;
    };
    if (!still()) window.addEventListener("pointermove", look, { passive: true });
    return { box, stop: () => window.removeEventListener("pointermove", look) };
  }

  function demoAsk(plate) {
    const ASKS = [
      {
        q: "What did I save about getting stronger?",
        a: "Two things point the same way. Your lifting note adds a little weight each week so the body adapts. The forests paper argues that small fires spare a forest the large one. Both gain from a stress they can absorb.",
        cites: [
          ["note", "Lift heavier each week"],
          ["pdf", "Why forests need small fires"],
        ],
      },
      {
        q: "What is my passport number?",
        a: "Nothing you saved answers that, so there is no guess to give.",
        cites: [],
      },
    ];
    const wrap = el("div", "tour-ask");
    const watcher = eye();
    const talk = el("div", "tour-talk");
    talk.setAttribute("aria-live", "polite");
    function show(i) {
      const { q, a, cites } = ASKS[i];
      talk.replaceChildren(rise(el("p", "tour-q", q), 0), rise(el("p", "tour-a", a), 2));
      if (!cites.length) return;
      const row = el("div", "tour-cites");
      for (const [kind, title] of cites) {
        const cite = el("span", "tour-cite");
        cite.dataset.kind = kind;
        cite.append(el("i"), title);
        row.append(cite);
      }
      talk.append(rise(row, 4));
    }
    const picker = choices(ASKS.map((x) => x.q), show);
    wrap.append(watcher.box, picker.row, talk);
    plate.append(wrap);
    picker.pick(0);
    return watcher.stop;
  }

  function demoReads(plate) {
    const wrap = el("div", "tour-drawer");
    wrap.dataset.kind = "pdf";
    const lines = el("div", "tour-lines");
    [
      "Small, frequent fires clear the brush that feeds a catastrophic one.",
      "Putting out every fire leaves a forest more fragile, not safer.",
      "An example of a system that gains from a stress it can absorb.",
    ].forEach((text) => lines.append(line(text)));
    // A summary line is a button until it is pressed; then it is a field with the same
    // words in it. Enter or leaving keeps the change and marks the line as yours.
    function line(text, edited) {
      const b = el("button", "tour-line", text);
      b.type = "button";
      b.setAttribute("aria-label", "Rewrite: " + text);
      if (edited) b.dataset.edited = "";
      b.addEventListener("click", () => {
        const box = el("textarea", "tour-line");
        box.value = text;
        box.rows = 2;
        box.setAttribute("aria-label", "Summary line");
        let settled = false;
        const settle = (keep) => {
          if (settled) return;
          settled = true;
          const next = box.value.trim();
          const changed = keep && next && next !== text;
          const fresh = line(changed ? next : text, changed || edited);
          box.replaceWith(fresh);
          if (document.activeElement === document.body) fresh.focus();
        };
        box.addEventListener("keydown", (e) => {
          e.stopPropagation(); // arrows and Enter belong to the field, not the deck
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            settle(true);
          } else if (e.key === "Escape") settle(false);
        });
        box.addEventListener("blur", () => settle(true));
        b.replaceWith(box);
        box.focus();
        box.select();
      });
      return b;
    }
    const related = el("div", "tour-rel");
    related.append(
      tile("note", "Lift heavier each week", "Both say small stress, repeated, makes a thing stronger."),
      tile("note", "Yosemite, day two", "Both mention Yosemite."),
    );
    wrap.append(
      kindRow("pdf"),
      el("h3", "tour-drawer-title", "Why forests need small fires"),
      el("p", "tour-label", "Summary"),
      lines,
      el("p", "tour-label", "Related"),
      related,
    );
    plate.append(wrap);
  }

  function demoViews(plate) {
    const ITEMS = [
      ["link", "Time Out Market", "Eat"],
      ["link", "Alfama flat, 4 nights", "Stay"],
      ["note", "Miradouro at sunset", "See"],
      ["note", "Pastéis de Belém, go early", "Eat"],
      ["image", "Tram 28 map", "See"],
    ];
    const tiles = ITEMS.map(([kind, title]) => tile(kind, title));
    const wrap = el("div", "tour-views");
    const head = el("div", "tour-views-head");
    const gather = button("plate", "");
    head.append(el("strong", null, "Lisbon trip"), gather);
    const board = el("div", "tour-board");
    let gathered = false;
    function shelf(name, members) {
      const s = el("div", "tour-shelf");
      if (name) s.append(el("p", "tour-label", name));
      const row = el("div", "tour-shelf-tiles");
      row.append(...members);
      s.append(row);
      return s;
    }
    function lay() {
      gather.textContent = gathered ? "Scatter them again" : "Gather with the eye";
      if (!gathered) return board.replaceChildren(shelf("", tiles));
      const names = ["Eat", "Stay", "See"];
      board.replaceChildren(
        ...names.map((name) => shelf(name, tiles.filter((_, i) => ITEMS[i][2] === name))),
      );
    }
    gather.addEventListener("click", () => {
      gathered = !gathered;
      glide(tiles, lay);
    });
    lay();
    wrap.append(head, board);
    plate.append(wrap);
  }

  function demoYours(plate) {
    const phone = opts.platform === "mobile";
    const wrap = el("div");
    const route = el("div", "tour-route");
    const node = (name, title, sub) => {
      const n = el("div", "tour-tile tour-node");
      n.append(icon(name), el("strong", null, title), el("span", null, sub));
      return n;
    };
    const wire = el("div", "tour-wire");
    const seal = el("span", "tour-seal");
    seal.append(icon("lock"));
    wire.append(seal, el("span", null, "sealed"));
    route.append(
      node("laptop", phone ? "Your Mac" : "This Mac", "the whole library"),
      wire,
      node("phone", phone ? "This phone" : "Your phone", "a copy, in your pocket"),
    );
    const facts = el("dl", "tour-facts");
    [
      [phone ? "Lives on your Mac" : "Lives on this Mac", "One folder. No account."],
      ["Sealed on the way", "Only your devices hold the key."],
      ["Fingerprint lock", phone ? "In Settings, on this phone." : "On the phone, in its Settings."],
      ["Your own backups", "Daily, into a drive folder you pick."],
    ].forEach(([term, detail]) => {
      const pair = el("div");
      pair.append(el("dt", null, term), el("dd", null, detail));
      facts.append(pair);
    });
    wrap.append(route, facts);
    plate.append(wrap);
  }

  // ---- the cards --------------------------------------------------------------------
  // title: the words, then the last word (with its full stop) in the accent - the
  // greeting's own convention. copy: strings and keycaps in reading order.
  function cards() {
    const phone = opts.platform === "mobile";
    const press = phone ? "Tap" : "Click";
    return [
      {
        title: ["Save first, organise", "never."],
        copy: ["Catch a thing the moment you meet it: a thought, a link, a PDF, a photo. No folder, no tag, no title. When it matters again, Enqueue brings it back."],
        note: ["Seven cards, about a minute."],
        demo: demoWelcome,
      },
      {
        title: ["Catch it from", "anywhere."],
        copy: phone
          ? ["Tap + for a note, a link, a photo or a file. Long-press the app icon and Quick capture floats a box over whatever app you are in."]
          : ["Press ", { keys: opts.hotkey }, " over whatever you are doing. Type a thought, paste a link or drop a file, then press Enter. The raven takes it and you are back where you were."],
        note: ["Try it. Nothing you type here is saved."],
        demo: demoCapture,
      },
      {
        title: ["Find it by the", "idea."],
        copy: ["Search reads your words, your meaning, and what each thing is an example of. Ask for something you never saved and it says so, instead of handing you a wall of maybes."],
        note: phone ? null : [{ keys: "Cmd+K" }, " opens search from anywhere in the app."],
        demo: demoFind,
      },
      {
        title: ["Ask the", "eye."],
        copy: ["Ask in plain words. The answer is written from your own library and names what it used. When nothing you saved answers the question, it tells you that too."],
        note: null,
        demo: demoAsk,
      },
      {
        title: ["It reads what you", "keep."],
        copy: ["Each thing gets a few summary lines: what it says, and what it is an example of. Rewrite any line and yours is kept. Things that are about the same subject, or make the same point, find each other."],
        note: [press + " a line to rewrite it."],
        demo: demoReads,
      },
      {
        title: ["Shelve it your", "way."],
        copy: phone
          ? ["A view is a saved way of looking at your library. Arrange one at the desk, or ask the eye to gather a subject, and it shows here in the same order."]
          : ["A view is a saved way of looking at your library. Drag tiles under your own headers, or ask the eye to gather a subject for you. It shows on your phone in the same order."],
        note: null,
        demo: demoViews,
      },
      {
        title: ["Yours, and", "private."],
        copy: phone
          ? ["Your library lives on your Mac. It reaches this phone end-to-end encrypted, so the relay in between only ever holds a sealed copy."]
          : ["Your library lives on this Mac. It reaches your phone end-to-end encrypted, so the relay in between only ever holds a sealed copy."],
        note: null,
        demo: demoYours,
      },
    ];
  }

  // ---- the stage --------------------------------------------------------------------
  function build() {
    if (stage) return;
    stage = el("div", "tour");
    stage.hidden = true;
    stage.setAttribute("role", "dialog");
    stage.setAttribute("aria-modal", "true");
    stage.setAttribute("aria-label", "How Enqueue works");

    const top = el("div", "tour-top");
    const shut = el("button", "tour-close");
    shut.type = "button";
    shut.setAttribute("aria-label", "Close");
    shut.title = "Close";
    shut.append(icon("close"));
    shut.addEventListener("click", close);
    top.append(shut);

    const body = el("div", "tour-body");
    const slide = el("div", "tour-slide");
    body.append(slide);

    const foot = el("div", "tour-foot");
    const steps = el("div", "tour-steps");
    steps.setAttribute("aria-hidden", "true");
    const nav = el("div", "tour-nav");
    const back = button("ghost", "Back");
    const next = button("primary", "Next");
    back.addEventListener("click", () => go(index - 1));
    next.addEventListener("click", () => go(index + 1));
    nav.append(back, next);
    foot.append(steps, nav);

    stage.append(top, body, foot);
    document.body.append(stage);
    parts = { body, slide, steps, back, next };

    stage.addEventListener("keydown", onKey);
    swipe(body);
  }

  function render(dir) {
    const deck = cards();
    const card = deck[index];
    if (cleanup) cleanup();
    cleanup = null;

    const text = el("div", "tour-text");
    text.style.setProperty("--tour-dir", dir);
    text.setAttribute("aria-live", "polite");
    const title = el("h2", "tour-title", card.title[0] + " ");
    title.append(el("span", "tour-accent", card.title[1]));
    text.append(title, rich(el("p", "tour-copy"), card.copy));
    if (card.note) text.append(rich(el("p", "tour-note"), card.note));

    const plate = el("div", "tour-demo");
    parts.slide.replaceChildren(text, plate);
    cleanup = card.demo(plate) || null;
    parts.body.scrollTop = 0;

    parts.steps.replaceChildren(
      ...deck.map((_, i) => {
        const bar = el("span", "tour-step");
        if (i <= index) bar.dataset.on = "";
        return bar;
      }),
    );
    stage.setAttribute("aria-label", `How Enqueue works, card ${index + 1} of ${deck.length}`);
    parts.back.hidden = index === 0;
    parts.next.textContent = index === deck.length - 1 ? "Start capturing" : "Next";
  }

  function go(to) {
    const count = cards().length;
    if (to >= count) return close();
    if (to < 0) return;
    const dir = to > index ? 1 : -1;
    index = to;
    render(dir);
  }

  function onKey(e) {
    if (e.key === "Escape") {
      e.preventDefault();
      return close();
    }
    const typing = /^(INPUT|TEXTAREA)$/.test(e.target.tagName);
    if (!typing && e.key === "ArrowRight") go(index + 1);
    else if (!typing && e.key === "ArrowLeft") go(index - 1);
    else if (e.key === "Tab") trap(e);
  }
  // Keep Tab inside the stage (the page behind is inert too; this covers engines
  // that do not honour `inert`).
  function trap(e) {
    const stops = [...stage.querySelectorAll("button, input, textarea")].filter(
      (n) => !n.hidden && !n.disabled && n.offsetParent !== null,
    );
    if (!stops.length) return;
    const first = stops[0];
    const last = stops[stops.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }
  // A sideways swipe turns the card, unless it began in a field or on a control.
  function swipe(area) {
    let start = null;
    area.addEventListener("pointerdown", (e) => {
      const busy = e.target.closest && e.target.closest("input, textarea, button");
      start = busy || e.pointerType === "mouse" ? null : { x: e.clientX, y: e.clientY };
    });
    area.addEventListener("pointerup", (e) => {
      if (!start) return;
      const dx = e.clientX - start.x;
      const dy = e.clientY - start.y;
      start = null;
      if (Math.abs(dx) < 56 || Math.abs(dx) < Math.abs(dy) * 1.6) return;
      go(index + (dx < 0 ? 1 : -1));
    });
    area.addEventListener("pointercancel", () => (start = null));
  }

  function markSeen() {
    document.documentElement.classList.remove("tour-unseen");
    try {
      localStorage.setItem(SEEN, "1");
    } catch (e) {
      /* the bead may come back next launch; harmless */
    }
  }

  function open(from) {
    build();
    if (!stage.hidden) return;
    lastFocus = from && from.focus ? from : document.activeElement;
    // Everything behind the stage goes inert: not clickable, not in the tab order,
    // not read out.
    hidden = [...document.body.children].filter((n) => n !== stage && !n.inert);
    hidden.forEach((n) => (n.inert = true));
    index = 0;
    document.documentElement.classList.add("tour-on");
    stage.hidden = false;
    render(1);
    markSeen();
    parts.next.focus();
  }

  function close() {
    if (!stage || stage.hidden) return;
    if (cleanup) cleanup();
    cleanup = null;
    stage.hidden = true;
    document.documentElement.classList.remove("tour-on");
    parts.slide.replaceChildren();
    hidden.forEach((n) => (n.inert = false));
    hidden = [];
    // Back to the ? that opened it. The home header can be redrawn while the tour is
    // up, which replaces that button, so fall back to the one on the page now.
    const back =
      lastFocus && document.contains(lastFocus) ? lastFocus : document.querySelector("[data-tour-open]");
    if (back && back.focus) back.focus();
    lastFocus = null;
  }

  // The ? as markup, for a header built from a string (the desktop home).
  function triggerHtml() {
    return (
      '<button type="button" class="tour-open" data-tour-open aria-label="How Enqueue works" title="How Enqueue works">' +
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="' +
      ICONS.help[0] +
      '"/><path d="' +
      ICONS.help[1] +
      '"/></svg></button>'
    );
  }

  function attach(options) {
    opts = Object.assign(opts, options || {});
    let seen = true;
    try {
      seen = !!localStorage.getItem(SEEN);
    } catch (e) {
      seen = true; // no storage: no bead, rather than one that never clears
    }
    document.documentElement.classList.toggle("tour-unseen", !seen);
    document.addEventListener("click", (e) => {
      const trigger = e.target.closest && e.target.closest("[data-tour-open]");
      if (!trigger) return;
      e.preventDefault();
      open(trigger);
    });
  }

  window.Tour = {
    attach,
    open: () => open(),
    close,
    triggerHtml,
    isOpen: () => !!stage && !stage.hidden,
    // Late facts, such as the capture hotkey once Settings has answered.
    set: (more) => Object.assign(opts, more || {}),
  };
})();
