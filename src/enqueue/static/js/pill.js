  // ---- the pill ------------------------------------------------------------
  let menu = null;
  let scope = { kind: "everything", label: "everything" };

  function closeMenu(restoreFocus) {
    if (menu) {
      menu.remove();
      menu = null;
    }
    const b = document.getElementById("btnAdd");
    if (b) {
      b.setAttribute("aria-expanded", "false");
      // Focus goes back where it came from. Dropping it on BODY leaves a keyboard user
      // at the top of the document with no idea the menu ever opened.
      if (restoreFocus) b.focus();
    }
  }

  // The first slot changes with where you are. On the wall it captures, because that is
  // the only thing you can do to a wall. Inside an object there is nowhere to put a new
  // capture yet and the thing you actually want is out, so it becomes the way out.
  // Search and ask never move: they mean the same thing on every surface.
  let place = "wall";

  function restorePill(where) {
    if (where) place = where;
    closeMenu();
    pill.classList.remove("wide");
    const inside = place === "inside";

    // Wall: Plus + Search + Eye (chat) + Settings. Saved groupings moved into
    // the wall's grouping selector (K.6), so the pill no longer carries a grid
    // button.
    // Inside: Back + Eye (context-aware).
    let html = "";
    if (inside) {
      // Home, not a back arrow: there is no history stack - "out" is always the
      // wall - so the way out wears the same yellow disc as the plus, and only
      // the icon changes. One button that always means the same place.
      html =
        '<button class="keep" aria-label="Home" onclick="home()">' +
        '<span class="disc">' +
        svg("home") +
        "</span></button>" +
        '<button class="round" aria-label="' +
        (scope.kind === "chat" ? "Continue chat" : "Ask about this") +
        '" onclick="chatOrAsk()">' +
        svg("ask") +
        "</button>";
    } else {
      html =
        '<button class="keep" id="btnAdd" aria-expanded="false" ' +
        'onclick="toggleMenu(event)">' +
        '<span class="disc">' +
        svg("plus") +
        "</span></button>" +
        '<button class="round" aria-label="Search" onclick="openField(\'search\')">' +
        svg("find") +
        "</button>" +
        '<button class="round" aria-label="Chat with AI" onclick="openField(\'ask\')">' +
        svg("ask") +
        "</button>" +
        '<button class="round" aria-label="Settings" onclick="showSettings()">' +
        svg("gear") +
        "</button>";
    }
    pill.innerHTML = html;
  }

  // Context-aware eye action inside a chat or the ask field.
  function chatOrAsk() {
    if (scope.kind === "chat" && scope.id) {
      showChat(scope.id);
    } else {
      openField("ask");
    }
  }

  const MENU = [
    ["note", "Note", () => newNote()],
    ["upload", "Upload", () => pickFile("*/*")],
    ["link", "Link", () => openField("link")],
    ["image", "Image", () => pickFile("image/*")],
  ];

  function toggleMenu(e) {
    if (e) e.stopPropagation();
    if (menu) return closeMenu();
    menu = document.createElement("div");
    menu.className = "menu";
    menu.setAttribute("role", "menu");
    // Four equal-weight choices. None of them is the primary, so none of them is
    // yellow, and hover is the recessed fill rather than a colour that would read as
    // "this is the one you want".
    menu.innerHTML = MENU.map(
      ([k, label]) =>
        '<button role="menuitem"><span class="ic">' +
        svg(k) +
        "</span>" +
        label +
        "</button>",
    ).join("");
    document.body.appendChild(menu);
    menu.querySelectorAll("button").forEach((b, i) => {
      b.onclick = (ev) => {
        ev.stopPropagation();
        closeMenu();
        MENU[i][2]();
      };
    });
    document.getElementById("btnAdd").setAttribute("aria-expanded", "true");
    menu.querySelector("button").focus();

    // role="menu" promises arrow navigation. Without it the role is a lie to a screen
    // reader that has already announced a menu.
    menu.addEventListener("keydown", (ev) => {
      const items = [...menu.querySelectorAll("button")];
      const at = items.indexOf(document.activeElement);
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        ev.preventDefault();
        const next =
          (at + (ev.key === "ArrowDown" ? 1 : -1) + items.length) %
          items.length;
        items[next].focus();
      }
      if (ev.key === "Home") {
        ev.preventDefault();
        items[0].focus();
      }
      if (ev.key === "End") {
        ev.preventDefault();
        items[items.length - 1].focus();
      }
    });
  }

  function openField(mode) {
    closeMenu();
    // The wall's home search is the one search surface it shows, so the pill's
    // magnifier and Cmd+K both route here instead of popping a second field.
    if (mode === "search") {
      const hs = document.getElementById("homesearch");
      if (hs) {
        hs.focus();
        hs.select();
        return;
      }
    }
    const hint = {
      search: "find something",
      ask: "ask about " + scope.label,
      link: "paste a url",
    }[mode];
    // CR.6: the pill field's name is the mode, not the placeholder - a placeholder
    // disappears on focus, so the accessible name has to survive it.
    const label = {
      search: "Search your artifacts",
      ask: "Ask about " + scope.label,
      link: "Paste a URL",
    }[mode];
    pill.classList.add("wide");
    pill.innerHTML =
      (mode === "ask"
        ? '<span class="scope">' + esc(scope.label) + "</span>"
        : "") +
      '<input id="field" placeholder="' +
      esc(hint) +
      '" aria-label="' +
      esc(label) +
      '" autocomplete="off">' +
      '<button class="round" aria-label="Close" onclick="restorePill()">' +
      svg("close") +
      "</button>";

    const field = document.getElementById("field");
    field.focus();
    field.onkeydown = (e) => {
      if (e.key === "Escape") return restorePill();
      if (e.key !== "Enter") return;
      const v = field.value.trim();
      if (!v) return;
      restorePill();
      if (mode === "search") doSearch(v);
      else if (mode === "ask") startChat(v);
      else saveLink(v);
    };
  }

  // Cmd+K (or Ctrl+K) jumps to search from anywhere: the home search on the wall,
  // the pill's inline field on any other view. A search never costs a person their
  // place.
  document.addEventListener("keydown", (e) => {
    if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== "k") return;
    e.preventDefault();
    openField("search");
  });

  async function saveLink(url) {
    try {
      await api("/capture/link", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
    } catch (err) {
      // The pill stays open with the address still in it: a failed capture must not
      // also cost you the thing you were capturing.
      openField("link");
      const field = document.getElementById("field");
      if (field) field.value = url;
      toast("Not saved. " + String(err.message || err), true);
      return;
    }
    home();
    toast("Saved.");
  }

  async function newNote() {
    const d = await api("/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body: "" }),
    });
    showArtifact(d.artifact.id, true);
  }

  document.addEventListener("keydown", (e) => {
    // CR.4: Cmd/Ctrl+. is the keyboard twin of the panel button - it opens (and
    // closes) the tags-and-summary drawer from anywhere on an artifact view.
    // The drawer only exists there, so its presence is the guard.
    if ((e.metaKey || e.ctrlKey) && e.key === ".") {
      if (document.getElementById("drawer")) {
        e.preventDefault();
        toggleDrawer();
      }
      return;
    }
    if (e.key === "Escape") {
      // The drawer is an overlay; Escape dismisses it before falling through to the
      // pill handling. A tag edit in progress owns its own Escape (blur the input),
      // so this defers while the tag field is focused.
      const inTagInput =
        e.target && e.target.classList && e.target.classList.contains("tagadd");
      if (!inTagInput && drawerOpen()) {
        toggleDrawer(false);
        return;
      }
      const wasOpen = !!menu;
      closeMenu(true);
      if (!wasOpen && pill.classList.contains("wide")) restorePill();
    }
  });
  document.addEventListener("click", (e) => {
    if (menu && !menu.contains(e.target) && !pill.contains(e.target))
      closeMenu();
  });

  // A WKWebView has no tabs, so `target="_blank"` opens nothing: clicking the address
  // on a saved link did precisely nothing, with no error anywhere to say why. The page
  // has to hand the address to the OS instead.
  //
  // Delegated rather than wired per link, because addresses also come out of rendered
  // markdown, and a rule that only covers the ones this file writes by hand is a rule
  // that breaks the next time something else renders a link.
  const bridge = window.__TAURI__ ? window.__TAURI__.core.invoke : null;

  document.addEventListener("click", (e) => {
    if (!bridge) return; // an ordinary browser can open its own tabs
    const link = e.target.closest && e.target.closest("a[href]");
    if (!link) return;

    const href = link.getAttribute("href") || "";
    if (!/^https?:/i.test(href)) return; // in-page and engine-relative links stay here

    e.preventDefault();
    bridge("open_external", { url: link.href }).catch((err) =>
      toast(String(err && err.message ? err.message : err), true),
    );
  });

  // Drag the window by the top strip. `-webkit-app-region` is inert in this WKWebView,
  // so the move is done by invoking the Rust `window_drag` on mousedown, the same path
  // the capture overlay uses. The search field opts out so a click there types rather
  // than dragging; a plain browser (no bridge) just does nothing, which is correct.
  const topbar = document.getElementById("topbar");
  if (topbar && bridge) {
    topbar.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      if (e.target.closest("input, button, a, [role='button']")) return;
      e.preventDefault();
      // Surface a rejection rather than swallowing it. A silent catch here is exactly
      // what hid the missing ACL grant last time: the invoke failed and the window
      // simply did not move, with nothing to say why.
      bridge("window_drag").catch((err) =>
        toast(
          "Could not drag the window: " +
            String(err && err.message ? err.message : err),
          true,
        ),
      );
    });
  }

