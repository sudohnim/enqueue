  // Structural markdown typed at the start of a line becomes the real thing, the way
  // it does in any editor that renders as you write.
  const RULES = [
    [/^(#{1,3})\s$/, (m) => "h" + m[1].length],
    [/^```\s?$/, () => "pre"],
    [/^[-*+]\s$/, () => "ul"],
    [/^1\.\s$/, () => "ol"],
    [/^>\s$/, () => "blockquote"],
  ];

  // Tab indents/un-indents a list item. These are DOM moves rather than
  // execCommand("indent"), because the exec command swaps out the text node under
  // the caret (the old one comes back detached and empty), so the caret can't be
  // restored and lands on the line above. Moving the <li> wholesale keeps the text
  // node alive, and produces the canonical nested shape the serializer expects.
  function indentItem(li) {
    const list = li.parentElement;
    const prev = li.previousElementSibling;
    if (!prev) return false; // first item: nothing to nest under
    const nested = document.createElement(list.tagName);
    list.removeChild(li);
    nested.appendChild(li);
    prev.appendChild(nested);
    return true;
  }

  function outdentItem(li) {
    const list = li.parentElement;
    if (!list) return false;
    const grand = list.parentElement;
    if (!grand || grand.tagName !== "LI") return false; // top level: no-op
    grand.parentElement.insertBefore(li, grand.nextSibling);
    if (!list.children.length) list.remove();
    return true;
  }

  function applyInputRules(ed) {
    const sel = window.getSelection();
    if (!sel.rangeCount) return;
    let block = sel.anchorNode;
    while (block && block.parentNode !== ed) block = block.parentNode;
    if (!block) return;
    // The first keystroke of an empty note lands in a bare text node with no block
    // for the structural rules to convert. Give it a paragraph so "- ", "# ", "1. "
    // and "> " work on the very first line too.
    if (block.nodeType !== 1) {
      if (block.nodeType !== 3) return;
      const p = document.createElement("p");
      block.parentNode.insertBefore(p, block);
      p.appendChild(block);
      block = p;
    }
    if (["UL", "OL", "PRE", "BLOCKQUOTE"].includes(block.tagName)) return;

    const text = block.textContent;
    for (const [re, kind] of RULES) {
      const m = text.match(re);
      if (!m) continue;
      const tag = kind(m);
      // A code block is built directly rather than through formatBlock: the fence
      // markers are the whole line and nothing in them is kept, so the empty <pre>
      // simply takes the block's place with the caret already inside it. It is a
      // bare <pre>, not md()'s <pre><code>: Chrome drops an empty <code>'s text
      // node on the first keystroke and inserts outside the wrapper, while a bare
      // pre takes the text the way the caret suggests.
      if (tag === "pre") {
        const pre = document.createElement("pre");
        block.replaceWith(pre);
        const r = document.createRange();
        r.selectNodeContents(pre);
        r.collapse(true);
        const s = window.getSelection();
        s.removeAllRanges();
        s.addRange(r);
        return;
      }
      document.execCommand(
        tag === "ul"
          ? "insertUnorderedList"
          : tag === "ol"
            ? "insertOrderedList"
            : "formatBlock",
        false,
        tag === "ul" || tag === "ol" ? null : tag,
      );
      // Find the element this rule produced. A list command nests the new list
      // inside the paragraph it converted (`<p><ul><li>...`), which is invalid
      // nesting: htmlToMd reads that wrapper as a paragraph and flattens the items
      // to plain text, silently deleting the bullet on save. Unwrap until the list
      // is a direct child of the editor, the shape the serializer expects.
      const isList = tag === "ul" || tag === "ol";
      let made = isList ? block.querySelector("ul, ol") : null;
      if (isList && !made) {
        // Some engines replace the paragraph with the list instead of nesting it,
        // detaching block; fall back to the list under the caret.
        const caret = window.getSelection().anchorNode;
        const el =
          caret && caret.nodeType === 1 ? caret : caret && caret.parentElement;
        made = el && el.closest ? el.closest("ul, ol") : null;
      }
      if (isList) {
        while (made && made.parentNode && made.parentNode !== ed) {
          const wrap = made.parentNode;
          wrap.parentNode.insertBefore(made, wrap);
          wrap.remove();
        }
      } else {
        // formatBlock replaces the block in place; find it from the caret.
        const caret = window.getSelection().anchorNode;
        const el =
          caret && caret.nodeType === 1 ? caret : caret && caret.parentElement;
        made = el && el.closest ? el.closest("h1, h2, h3, blockquote") : null;
      }
      // The marker characters were the instruction, not the content. The caret does
      // not reliably land inside the converted block's text (Chrome collapses it
      // onto the list container), so strip from the block's own first text node.
      const first =
        made && made.firstElementChild
          ? made.firstElementChild.firstChild
          : made
            ? made.firstChild
            : null;
      const host = first && first.nodeType === 3 ? first : null;
      if (host)
        host.nodeValue = host.nodeValue.replace(/^(#{1,3}|[-*+]|1\.|>)\s/, "");
      return;
    }
  }

  let ctx = null;
  // A pending re-look at a link's preview. Held at module scope so leaving the screen
  // can cancel it rather than hoping a stale guard happens to be false.
  let faceWatch = null;
  let faceTries = 0;
  const FACE_LIMIT = 8;

  // ---- tags ---------------------------------------------------------------
  // A tag is an optional, later act on an artifact that already exists. It is
  // added here, on the artifact page, never at capture time and never required.
  // Each chip's remove is one small x - undoing a label is not a big decision.
  function tagRowHtml(tags) {
    return (
      '<div class="tagrow">' +
      (tags || [])
        .map(
          (t) =>
            '<span class="tagchip" data-tag="' +
            esc(t) +
            '"><span class="taglabel">' +
            esc(t) +
            "</span>" +
            '<button class="tagx" aria-label="Remove tag ' +
            esc(t) +
            '" title="Remove tag">' +
            svg("close") +
            "</button></span>",
        )
        .join("") +
      '<input class="tagadd" type="text" placeholder="add tag" autocomplete="off" ' +
      'aria-label="Add a tag" spellcheck="false" />' +
      "</div>"
    );
  }

  // The drawer's Views section: one chip per saved view the artifact is in,
  // plus a trailing ghost button that opens the saved-view picker to add it to
  // another view. Mirrors the tags row's shape - a shelf label above, chips and
  // the add affordance on one wrapping row.
  function viewsRowHtml(views, artifactId) {
    const chips = (views || [])
      .map(
        (v) =>
          '<span class="viewchip" data-pivot="' +
          v.id +
          '" data-name="' +
          esc(v.name) +
          '"><span class="viewlabel">' +
          esc(v.name) +
          "</span>" +
          '<button class="tagx" aria-label="Remove from ' +
          esc(v.name) +
          '" title="Remove from this view">' +
          svg("close") +
          "</button></span>",
      )
      .join("");
    return (
      '<div class="shelf">Views</div>' +
      '<div class="viewsrow">' +
      chips +
      '<button class="viewadd" type="button" onclick="addArtifactToView(\'' +
      esc(artifactId) +
      "')\">+ add to a view</button>" +
      "</div>"
    );
  }

  // The chip names and the input are bound here, not in inline onclick: a tag name
  // is user text, so it travels in a data attribute and is read at click time.
  function mountTagRow(id) {
    const row = view.querySelector(".tagrow");
    if (!row) return;
    row.querySelectorAll(".tagx").forEach((btn) => {
      btn.addEventListener("click", () => {
        removeTag(id, btn.closest(".tagchip").dataset.tag);
      });
    });
    const input = row.querySelector(".tagadd");
    if (input) {
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") addTag(id, input.value);
        else if (e.key === "Escape") {
          input.value = "";
          input.blur();
        }
      });
    }
  }

  // The drawer's view chips bind here, not in inline onclick: the pivot id
  // travels in a data attribute and is read at click time.
  function mountViewsRow(id) {
    const row = view.querySelector(".viewsrow");
    if (!row) return;
    row.querySelectorAll(".viewchip .tagx").forEach((btn) => {
      btn.addEventListener("click", () => {
        const chip = btn.closest(".viewchip");
        removeArtifactFromView(id, chip.dataset.pivot);
      });
    });
  }

  // ---- tags in the drawer --------------------------------------------------
  // The drawer holds the artifact's tags (editable chips) and the summary. The
  // "Add to grouping" row (K.5) was the redundant collections path; Phase M
  // removed it - saved groupings own membership now (M.2).

  async function addTag(id, raw) {
    const name = (raw || "").trim();
    if (!name) return;
    try {
      await api("/artifacts/" + id + "/tags", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const keep = drawerOpen();
      await showArtifact(id);
      if (keep) toggleDrawer(true);
    } catch (err) {
      toast(String((err && err.message) || err), true);
    }
  }

  async function removeTag(id, name) {
    try {
      await api("/artifacts/" + id + "/tags/" + encodeURIComponent(name), {
        method: "DELETE",
      });
      const keep = drawerOpen();
      await showArtifact(id);
      if (keep) toggleDrawer(true);
    } catch (err) {
      toast(String((err && err.message) || err), true);
    }
  }

  // ---- views in the drawer -------------------------------------------------
  // The drawer's Views section (P.1): one chip per saved view the artifact is
  // in, and a ghost button that reuses the saved-view picker to add the
  // artifact to another view. Both re-render the drawer in place, preserving
  // its open state, the same pattern addTag/removeTag use.
  async function addArtifactToView(artifactId) {
    const pick = await openCustomPicker();
    if (!pick) return;
    try {
      await api("/pivots/" + pick.id + "/include", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ artifact_id: artifactId }),
      });
    } catch (err) {
      return toast(String((err && err.message) || err), true);
    }
    toast('Added to "' + pick.name + '".');
    const keep = drawerOpen();
    await showArtifact(artifactId);
    if (keep) toggleDrawer(true);
  }

  async function removeArtifactFromView(artifactId, pivotId) {
    try {
      await api("/pivots/" + pivotId + "/exclude", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ artifact_id: artifactId }),
      });
    } catch (err) {
      return toast(String((err && err.message) || err), true);
    }
    toast("Removed from this view.");
    const keep = drawerOpen();
    await showArtifact(artifactId);
    if (keep) toggleDrawer(true);
  }

  async function showArtifact(id, focus, scrollY) {
    const arriving = !ctx || ctx.id !== id;
    teardown();
    if (arriving) faceTries = 0;
    const d = await api("/artifacts/" + id);
    const a = d.artifact;
    scope = { kind: "artifact", id, label: "this artifact" };
    restorePill("inside");
    setRoute("a/" + id);

    view.setAttribute("data-kind", a.kind);

    const bits = [since(a.updated_at)];
    if (d.file && d.file.bytes) bits.push(bytes(d.file.bytes));
    if (a.source_url) bits.push(host(a.source_url));

    // No primary action anywhere on this page. Nothing you can do to a thing you have
    // already kept is urgent, and a yellow pill here would say otherwise.
    let html =
      '<div class="pagecol">' +
      '<button class="btn ghost back" onclick="home()">' +
      svg("back") +
      "Everything</button>" +
      '<div class="kindrow"><span class="kindmark"></span>' +
      '<span class="kindword">' +
      esc(a.kind) +
      "</span></div>" +
      '<div class="titlerow"><div class="h1" id="titleH1" style="view-transition-name:artifact-title">' +
      esc(a.title || "Untitled") +
      "</div>" +
      (["pdf", "image", "file"].includes(a.kind)
        ? '<a class="title-action" href="/artifacts/' +
          a.id +
          '/blob" download aria-label="Download a copy" title="Download a copy">' +
          svg("down") +
          "</a>"
        : "") +
      // CR.3: pin and the drawer are both "work on this artifact", so they ride
      // together as one tight group; download (a copy) and trash (removal) stand
      // apart from that pair and from each other.
      '<span class="title-group">' +
      '<button class="title-action' +
      (a.pinned ? " lit" : "") +
      '" aria-label="' +
      (a.pinned ? "Kept" : "Keep") +
      '" title="' +
      (a.pinned ? "Kept" : "Keep at the front") +
      '" onclick="pinArtifact(\'' +
      a.id +
      "'," +
      !a.pinned +
      ')">' +
      svg("star") +
      "</button>" +
      '<button class="title-action" id="drawerToggle" aria-label="Tags and summary" aria-expanded="false" title="Tags and summary" onclick="toggleDrawer()">' +
      svg("panelin") +
      "</button></span>" +
      '<button class="title-action danger" aria-label="Move to trash" title="Move to trash" onclick="binArtifact(\'' +
      a.id +
      "')\">" +
      svg("trash") +
      "</button></div>" +
      '<div class="meta">' +
      bits.filter(Boolean).map(esc).join('<span class="sep">&bull;</span>') +
      (a.local_only
        ? '<span class="sep">&bull;</span><span class="badge neutral">local only</span>'
        : "") +
      "</div>" +
      '<div class="actions">' +
      (a.source_url
        ? '<a class="btn secondary" href="' +
          esc(a.source_url) +
          '" target="_blank" rel="noopener">Open original</a>'
        : "") +
      "</div>";

    if (a.source_url)
      html +=
        '<a class="url" href="' +
        esc(a.source_url) +
        '" target="_blank" rel="noopener">' +
        esc(a.source_url) +
        "</a>";

    if (d.secrets.length)
      html +=
        '<div class="callout warn"><p>This holds what looks like a credential, so it ' +
        "stays out of every model call.</p><p>" +
        d.secrets.map((s) => esc(s.excerpt)).join("<br>") +
        "</p></div>";

    // The body builds on its own so the tags and summary can leave the column
    // entirely: the reading pane is one centered column, and everything else on
    // this page lives in the drawer.
    let body = "";

    if (a.kind === "note") {
      // The body is yours. Edited in place, with every version kept.
      const n = d.versions.length;
      // Long-form sits on the warm reading white rather than the raised white, so a
      // whole page of it does not glare against the cream.
      body +=
        '<div class="docpane">' +
        '<div class="editor md" id="body" contenteditable="true" spellcheck="true" ' +
        'role="textbox" aria-multiline="true" aria-label="The note itself" ' +
        'data-placeholder="Start writing. Markdown shorthand becomes formatting as you type."></div>' +
        '<div class="bar"><span id="state" class="meta"></span>' +
        '<span class="meta" style="margin-left:auto" id="vers" data-n="' +
        n +
        '">' +
        (n > 1 ? n + " drafts kept" : "") +
        "</span></div></div>";
      ctx = {
        id,
        kind: "note",
        title: a.title,
        titleExplicit: a.title_explicit,
        saved: a.body || "",
        html: md(a.body || ""),
      };
    } else {
      if (a.kind === "pdf") {
        body += reader(a, d.pages);
      } else if (a.kind === "file") {
        body +=
          fileFacts(d.file) + '<div class="md" id="plain">reading...</div>';
      } else if (a.kind === "image") {
        body +=
          '<div class="docpane"><img class="page" src="/artifacts/' +
          a.id +
          '/blob" alt="' +
          esc(a.title) +
          '"></div>';
      } else if (a.kind === "link") {
        body += linkFace(a, d.preview);
      }
      const current = d.annotations.filter((x) => x.current);
      const last = current.length ? current[current.length - 1] : null;
      body +=
        '<div class="docpane">' +
        '<div class="editor md" id="body" contenteditable="true" spellcheck="true" ' +
        'role="textbox" aria-multiline="true" aria-label="Your notes here" ' +
        'style="min-height:150px" data-placeholder="Your notes here"></div>' +
        '<div class="bar"><span id="state" class="meta"></span></div></div>';
      ctx = {
        id,
        kind: a.kind,
        entryId: last ? last.id : null,
        saved: last ? last.text : "",
        html: md(last ? last.text : ""),
      };
    }

    // How the app keeps its central promise visible: what the model made of this, and
    // the fact that it made it here. Never behind a disclosure. The panel is a summary:
    // facets are the model's compressed reading of the artifact, and it may be generated
    // remotely when the backend is remote, so the old privacy claim was also inaccurate.
    // It lives in the drawer, under the tags.
    let summaryHtml = "";
    if (d.facet_skip_reason)
      summaryHtml =
        '<div class="callout note"><div class="shelf">Summary</div>' +
        "<p>" +
        esc(whyNoFacets(d.facet_skip_reason)) +
        "</p></div>";
    else if (d.facets.length)
      summaryHtml =
        '<div class="callout note"><div class="shelf">Summary</div>' +
        d.facets.map((f) => "<p>" + esc(f.statement) + "</p>").join("") +
        "</div>";

    html +=
      '<div class="bodygrid"><div class="bodycol">' +
      body +
      "</div></div></div>" +
      '<aside class="drawer" id="drawer" aria-label="Tags and summary">' +
      '<div class="drawer-top"><span class="shelf">Tags</span>' +
      '<button class="drawer-close" aria-label="Close tags and summary" title="Close tags and summary" onclick="toggleDrawer(false)">' +
      svg("panelout") +
      "</button></div>" +
      tagRowHtml(d.tags) +
      viewsRowHtml(d.views, id) +
      summaryHtml +
      "</aside>";

    view.innerHTML = html;
    mountTagRow(id);
    mountViewsRow(id);
    mountEditor(focus);
    mountTitleEdit(id);
    if (a.kind === "pdf") mountReader(a.id, d.pages);
    if (a.kind === "file") mountPlain(a.id);
    if (scrollY !== undefined) window.scrollTo(0, scrollY);
    else window.scrollTo(0, 0);
  }

  function drawerOpen() {
    const d = document.getElementById("drawer");
    return !!(d && d.classList.contains("open"));
  }

  // The tags-and-summary drawer. One button toggles it; the chevrons and the
  // aria state read differently open and closed, and Escape closes it from the
  // global handler. The drawer only ever covers the content, never pushes it.
  function toggleDrawer(force) {
    const drawer = document.getElementById("drawer");
    const toggle = document.getElementById("drawerToggle");
    if (!drawer) return;
    const open =
      force !== undefined ? !!force : !drawer.classList.contains("open");
    drawer.classList.toggle("open", open);
    if (toggle) {
      toggle.setAttribute("aria-expanded", String(open));
      toggle.setAttribute(
        "aria-label",
        open ? "Close tags and summary" : "Tags and summary",
      );
      toggle.title = open
        ? "Close the tags and summary drawer"
        : "Tags and summary";
      toggle.innerHTML = svg(open ? "panelout" : "panelin");
    }
  }

  // The gate prints its own enum value otherwise: "No facets: too_short" tells the
  // reader nothing and names an internal state they have no way to know about. Facets
  // are the machine's index of what a thing could be an example of; not having them
  // costs you nothing except being pulled into a room you did not search for by name.
  const NO_FACETS = {
    too_short:
      "Too short to draw anything general out of. Still searchable.",
    text_only:
      "Held out of every model call, because it looks like it contains a credential. " +
      "Still searchable.",
    kind: "Nothing here to read yet. Still searchable.",
  };

  function whyNoFacets(reason) {
    return (
      NO_FACETS[reason] ||
      "Not read yet. Still searchable."
    );
  }

  // ---- a link's face -------------------------------------------------------
  // A saved link has nothing but its address until someone decides it is worth one
  // request. So the page shows what is actually known, and the button that would find
  // out more says what it costs, right where it is.
  function linkFace(a, p) {
    // The shared host() helper names the publisher; a link that cannot be parsed
    // (legacy rows) reads as "the publisher" rather than a raw string.
    const h = host(a.source_url) || "the publisher";

    if (p && p.status === "ok") {
      const shot = p.image_hash
        ? '<img class="shot" style="view-transition-name:artifact-face" src="/artifacts/' +
          a.id +
          '/preview-image" alt="" ' +
          'onerror="this.remove()">'
        : "";
      return (
        shot +
        (p.description
          ? '<div class="lede">' + esc(p.description) + "</div>"
          : "")
      );
    }

    // No row yet means the queue has not reached it. Saving already asked for a
    // preview, so a button here would be a second way to start something that is
    // already happening. It says so, and looks again shortly.
    //
    // The wait has to be bounded and the timer has to be cancellable. Neither was true
    // before: the poll rescheduled itself off a `ctx` that nothing ever cleared, so a
    // link whose preview never arrives (auto-fetch off, or a publisher that never
    // answers) kept firing `showArtifact` forever, which yanked the reader back out of
    // whatever they had navigated to. Going Home did not stop it, because Home did not
    // clear `ctx`. Two bugs stacked into one: an unbounded loop, and a loop that
    // outlived its own screen.
    if (!p) {
      if (faceTries < FACE_LIMIT) {
        faceTries += 1;
        clearTimeout(faceWatch);
        faceWatch = setTimeout(() => {
          if (ctx && ctx.id === a.id) showArtifact(a.id);
        }, 1500);
        return (
          '<div class="aside thinking">asking ' +
          esc(h) +
          " what this is...</div>"
        );
      }
      // Past the limit, saying "asking" would be a lie: nothing is in flight. Offer
      // the one request that is left to decide on.
      return (
        '<div class="aside caution">Nothing has come back from ' +
        esc(h) +
        ". Automatic previews may be off in settings.</div>" +
        '<button class="btn tertiary" id="btnPreview" onclick="fetchPreview(\'' +
        a.id +
        "')\">Ask " +
        esc(h) +
        "</button>"
      );
    }

    // Only a refusal gets a button, because only a refusal is a decision left to
    // make: the publisher said no, and another request is either worth it or not.
    return (
      '<div class="aside caution">' +
      esc(p.error || "that did not resolve") +
      "</div>" +
      '<button class="btn tertiary" id="btnPreview" onclick="fetchPreview(\'' +
      a.id +
      "')\">Try again</button>" +
      '<div class="aside">one more request to ' +
      esc(h) +
      "</div>"
    );
  }

  // Deleting is reversible and says so, because the whole promise of the product is
  // that nothing is lost. The window is the person's own setting, so the confirmation
  // quotes it rather than a number this code invented.
  async function binArtifact(id) {
    let days = 30;
    try {
      days = (await api("/trash")).retention_days;
    } catch (err) {}
    try {
      await api("/artifacts/" + id, { method: "DELETE" });
    } catch (err) {
      return toast("Not deleted. " + String(err.message || err), true);
    }
    home();
    toast(
      "Moved to the trash. Recoverable for " +
        days +
        " day" +
        (days === 1 ? "" : "s") +
        ".",
    );
  }

  async function pinArtifact(id, pinned) {
    try {
      await api("/artifacts/" + id, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pinned }),
      });
    } catch (err) {
      return toast(String(err.message || err), true);
    }
    showArtifact(id, undefined, window.scrollY);
  }

  async function fetchPreview(id) {
    const button = document.getElementById("btnPreview");
    if (button) {
      button.disabled = true;
      button.textContent = "asking " + "...";
    }
    try {
      await api("/artifacts/" + id + "/preview", { method: "POST" });
    } catch (err) {
      if (button) {
        button.disabled = false;
        button.textContent = "Try again";
      }
      return toast(String(err.message || err), true);
    }
    faceTries = 0;
    showArtifact(id);
  }

  // What is known about a file the reader may not be able to show. An upload that
  // renders as a featureless square is indistinguishable from one that never arrived,
  // which is exactly how a successful capture got reported as a failure.
  function fileFacts(file) {
    if (!file)
      return '<div class="aside caution">The stored copy is missing.</div>';
    return (
      '<div class="aside">' +
      esc(file.name) +
      " &middot; " +
      esc(file.mime) +
      " &middot; " +
      bytes(file.bytes) +
      "</div>"
    );
  }

  // A captured text file had its contents nowhere: not on screen, not in the index,
  // not answerable. It rendered as an empty glyph with a filename.
  async function mountPlain(id) {
    const box = document.getElementById("plain");
    if (!box) return;
    try {
      const d = await api("/artifacts/" + id + "/text");
      const text = (d.pages || [])
        .map((p) => p.text)
        .join("\n")
        .trim();
      box.textContent = text || "";
      if (!text) {
        box.className = "state";
        box.innerHTML =
          "saved exactly as it arrived. Nothing in it reads as text, so there is " +
          "nothing to show and nothing to search - it is here, and it is intact.";
      }
    } catch (err) {
      box.className = "aside caution";
      box.textContent = String(err.message || err);
    }
  }

  // ---- finding a phrase inside one thing -----------------------------------
  // Only intercepted for PDFs. Their pages are rendered as images, so the browser has
  // no text to search and its own find is genuinely useless. A note is real text in the
  // DOM, where Cmd+F already works better than anything reimplemented here would, so it
  // is left alone.
  let findState = null;

  async function openFind() {
    // Notes are real text in the DOM, so the browser could search them - except this
    // window has no Edit menu, and without one the webview never binds its own find.
    // So the same field serves both, and only the drawing differs.
    if (!ctx || !["pdf", "note", "file"].includes(ctx.kind)) return false;

    if (!findState || findState.id !== ctx.id) {
      const d = await api("/artifacts/" + ctx.id + "/text").catch(() => null);
      findState = { id: ctx.id, kind: ctx.kind, pages: (d && d.pages) || [] };
    }

    pill.classList.add("wide");
    pill.innerHTML =
      '<input id="findField" placeholder="find in this ' +
      (ctx.kind === "pdf" ? "document" : "note") +
      '" autocomplete="off">' +
      '<span class="scope" id="findCount"></span>' +
      '<button class="round" aria-label="Close" onclick="restorePill()">' +
      svg("close") +
      "</button>";

    const field = document.getElementById("findField");
    field.focus();
    field.oninput = () => runFind(field.value);
    field.onkeydown = (e) => {
      if (e.key === "Escape") {
        clearFind();
        return restorePill();
      }
      if (e.key === "Enter") {
        e.preventDefault();
        stepFind(e.shiftKey ? -1 : 1);
      }
    };
    return true;
  }

  async function runFind(term) {
    const count = document.getElementById("findCount");
    clearFind();
    term = term.trim();
    if (!term) {
      if (count) count.textContent = "";
      return;
    }

    if (findState.kind === "pdf") {
      // The engine knows where the words are; the browser is looking at a picture.
      // Counting matches in the extracted text here and drawing boxes from a separate
      // source would let the two disagree, so both come from the one call.
      const found = await api(
        "/artifacts/" + findState.id + "/find?q=" + encodeURIComponent(term),
      ).catch(() => ({ hits: [] }));
      findState.hits = found.hits || [];
      paintPdfHits();
    } else {
      findState.hits = markInNote(term);
    }

    findState.at = findState.hits.length ? 0 : -1;
    if (count)
      count.textContent = findState.hits.length
        ? "1 of " + findState.hits.length
        : "nothing";
    if (findState.hits.length) goToHit(0);
  }

  // Boxes over the rendered page, positioned as percentages of it, so they stay put
  // at any window width and any pixel density.
  function paintPdfHits() {
    for (const hit of findState.hits) {
      const leaf = document.querySelector(
        '.leaf[data-page="' + hit.page + '"]',
      );
      if (!leaf) continue;
      const mark = document.createElement("span");
      mark.className = "findbox";
      mark.style.left = hit.x * 100 + "%";
      mark.style.top = hit.y * 100 + "%";
      mark.style.width = hit.w * 100 + "%";
      mark.style.height = hit.h * 100 + "%";
      leaf.appendChild(mark);
      hit.node = mark;
    }
  }

  // A note is live text the person can edit, so the matches are wrapped in CSS
  // highlights rather than in elements. Inserting <mark> tags would change the DOM
  // the editor serialises back to markdown, and the next save would write them into
  // the note.
  function markInNote(term) {
    const root =
      document.getElementById("body") || document.getElementById("plain");
    if (!root || !window.CSS || !CSS.highlights) return [];

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const ranges = [];
    const needle = term.toLowerCase();
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const hay = node.nodeValue.toLowerCase();
      let at = hay.indexOf(needle);
      while (at !== -1) {
        const range = new Range();
        range.setStart(node, at);
        range.setEnd(node, at + needle.length);
        ranges.push({ range });
        at = hay.indexOf(needle, at + needle.length);
      }
    }

    CSS.highlights.set(
      "enqueue-find",
      new Highlight(...ranges.map((r) => r.range)),
    );
    return ranges;
  }

  function stepFind(by) {
    const hits = (findState && findState.hits) || [];
    if (!hits.length) return;
    findState.at = (findState.at + by + hits.length) % hits.length;
    document.getElementById("findCount").textContent =
      findState.at + 1 + " of " + hits.length;
    goToHit(findState.at);
  }

  function goToHit(index) {
    const hit = findState.hits[index];
    if (!hit) return;

    document
      .querySelectorAll(".findbox.on")
      .forEach((m) => m.classList.remove("on"));

    if (findState.kind === "pdf") {
      if (hit.node) hit.node.classList.add("on");
      const target =
        hit.node ||
        document.querySelector('.leaf[data-page="' + hit.page + '"]');
      if (target)
        target.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }

    // A Range has no scrollIntoView of its own, so its rectangle is measured and the
    // window moved to it.
    const box = hit.range.getBoundingClientRect();
    window.scrollTo({
      top: window.scrollY + box.top - window.innerHeight / 2,
      behavior: "smooth",
    });
    CSS.highlights.set("enqueue-find-current", new Highlight(hit.range));
  }

  function clearFind() {
    document.querySelectorAll(".findbox").forEach((m) => m.remove());
    if (window.CSS && CSS.highlights) {
      CSS.highlights.delete("enqueue-find");
      CSS.highlights.delete("enqueue-find-current");
    }
  }

  document.addEventListener("keydown", (e) => {
    if (
      (e.metaKey || e.ctrlKey) &&
      e.key === "f" &&
      ctx &&
      ctx.kind === "pdf"
    ) {
      e.preventDefault();
      openFind();
    }
  });

  // ---- the reader ----------------------------------------------------------
  // A PDF is read here, not handed to whatever the operating system would open it
  // with. Pages are rasterised by the engine, so they render in a webview that has no
  // PDF plugin, and they load as they are reached rather than all at once.
  function reader(a, pages) {
    if (!pages)
      return (
        '<div class="state">This file will not open as a document. It is stored ' +
        'exactly as it arrived: <a class="url" href="/artifacts/' +
        a.id +
        '/blob" download>keep a copy</a>.</div>'
      );

    let html = '<div class="reader" id="reader">';
    for (let i = 0; i < pages; i++)
      html +=
        '<div class="leaf"' +
        (i === 0 ? ' style="view-transition-name:artifact-face"' : "") +
        ' data-page="' +
        i +
        '" role="img" aria-label="page ' +
        (i + 1) +
        " of " +
        pages +
        '"></div>';
    return (
      html + "</div>" + '<div class="folio" id="folio">1 / ' + pages + "</div>"
    );
  }

  let readerWatch = null;

  function mountReader(id, pages) {
    if (readerWatch) {
      readerWatch.disconnect();
      readerWatch = null;
    }
    const root = document.getElementById("reader");
    if (!root || !pages) return;

    // Rasterise at the density the screen actually has: a 900px render on a Retina
    // display is a soft page, and soft type is the one thing a reader cannot forgive.
    //
    // Measured at mount, the width is sometimes 0, because the pane has not laid out
    // yet and a zero-width request renders nothing. So it is measured at the moment a
    // page is actually reached, by which point layout has certainly happened.
    const width = () =>
      Math.min(
        2400,
        Math.max(
          700,
          Math.round(root.clientWidth * (window.devicePixelRatio || 1)),
        ),
      );

    const load = (leaf) => {
      if (leaf.dataset.loaded) return;
      leaf.dataset.loaded = "1";
      const img = new Image();
      img.alt = "";
      img.onload = () => {
        // Prepended, not replaced. Pages load lazily, so a find can paint highlight
        // boxes onto a page before its picture arrives; `replaceChildren` then wiped
        // them and the search silently lost a third of its results.
        leaf.prepend(img);
        leaf.classList.add("loaded");
      };
      // A page that will not render is still a page. Removing it would silently
      // renumber the document underneath the reader.
      img.onerror = () => {
        leaf.dataset.loaded = "";
        leaf.classList.add("blank");
        leaf.textContent =
          "page " + (Number(leaf.dataset.page) + 1) + " would not render";
      };
      img.src =
        "/artifacts/" + id + "/page/" + leaf.dataset.page + "?width=" + width();
    };

    // Two observers, because the two jobs want opposite settings. Loading wants to fire
    // early, a screen or two ahead. The page counter wants to fire late and exactly:
    // sharing one observer is what made it read "2 / 9" while page one filled the screen.
    const ahead = new IntersectionObserver(
      (entries) =>
        entries.filter((e) => e.isIntersecting).forEach((e) => load(e.target)),
      { rootMargin: "1200px 0px" },
    );

    const folio = document.getElementById("folio");
    const shown = new Map();
    const here = new IntersectionObserver(
      (entries) => {
        for (const entry of entries)
          shown.set(Number(entry.target.dataset.page), entry.intersectionRatio);
        if (!folio) return;
        // The page you are reading is the one filling most of the screen. Ties go to the
        // earlier page, because that is the one you are still finishing.
        let best = null;
        for (const [page, ratio] of [...shown].sort((a, b) => a[0] - b[0]))
          if (ratio > 0 && (best === null || ratio > shown.get(best) + 0.01))
            best = page;
        if (best !== null) folio.textContent = best + 1 + " / " + pages;
      },
      { threshold: [0, 0.1, 0.25, 0.5, 0.75, 1] },
    );

    root.querySelectorAll(".leaf").forEach((leaf) => {
      ahead.observe(leaf);
      here.observe(leaf);
    });
    readerWatch = {
      disconnect: () => {
        ahead.disconnect();
        here.disconnect();
      },
    };
  }

  function mountEditor(focus) {
    const ed = document.getElementById("body");
    if (!ed || !ctx) return;
    const html = ctx.html || "";
    // An empty note must never mount a bare editable: the first keystroke would
    // land in a bare text node with no block, and each input would re-wrap it in
    // a fresh <p> (applyInputRules' fallback), stacking one paragraph per
    // character. Seed a single empty paragraph so the very first keystroke has a
    // real block to live in; the empty paragraph serialises back to nothing.
    ed.innerHTML = html || "<p><br></p>";

    const lead = ed.firstElementChild;
    if (
      lead &&
      lead.tagName === "H1" &&
      ctx.title &&
      lead.textContent.trim() === ctx.title.trim()
    )
      ed.classList.add("titled");

    ed.addEventListener("input", () => {
      applyInputRules(ed);
      refreshTitleHeader();
    });
    ed.addEventListener("blur", saveBody);
    ed.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && "bi".includes(e.key)) {
        e.preventDefault();
        document.execCommand(e.key === "b" ? "bold" : "italic");
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        saveBody();
      }
      // Inside a code block, Enter is a code newline, not a new block: the break is
      // inserted as text (never a <br>, which the serializer's textContent read
      // would drop) so fences round-trip unchanged. Enter on the last empty line
      // leaves the block instead, back to prose, the way a markdown editor closes a
      // fence. Shift+Enter always stays inside.
      if (e.key === "Enter") {
        const node = window.getSelection().anchorNode;
        const el =
          node && node.nodeType === 1 ? node : node && node.parentElement;
        const pre = el && el.closest ? el.closest("pre") : null;
        if (pre) {
          e.preventDefault();
          const sel = window.getSelection();
          const range = sel.rangeCount && sel.getRangeAt(0);
          // The caret's absolute offset within the block text, whatever text nodes
          // the code is split across, decides whether the last line is empty.
          let abs = -1;
          if (range && range.collapsed) {
            const target = range.endContainer;
            const tOff = range.endOffset;
            let acc = 0;
            const walk = (n) => {
              if (abs >= 0) return;
              if (n.nodeType === 3) {
                if (n === target)
                  abs = acc + Math.min(tOff, n.nodeValue.length);
                acc += n.nodeValue.length;
              } else if (n.nodeType === 1) {
                for (const c of n.childNodes) walk(c);
              }
            };
            walk(pre);
          }
          const text = pre.textContent;
          // The line the caret ends on, ignoring the zero-width marker a fresh
          // Enter-made line carries (see below).
          const plain = text.replace(/\u200b/g, "");
          const lastLine = plain.slice(plain.lastIndexOf("\n") + 1);
          const exit =
            !e.shiftKey &&
            abs === text.length &&
            lastLine === "" &&
            text.endsWith("\u200b");
          if (exit) {
            // The exit paragraph gets a zero-width marker so the caret sits inside
            // a text node: an element-position caret would put the next keystroke
            // at the end of the pre above it.
            const p = document.createElement("p");
            p.appendChild(document.createTextNode("\u200b"));
            pre.after(p);
            const r = document.createRange();
            r.setStart(p.firstChild, 1);
            r.collapse(true);
            sel.removeAllRanges();
            sel.addRange(r);
          } else {
            // The newline is written by rebuilding the code text. execCommand's
            // insertText would emit a <br> (invisible to textContent, lost on
            // save), and splicing a text node by hand parks the caret on the
            // element, where the next keystroke lands wrong. A rebuild keeps the
            // caret inside a text node at the exact offset.
            if (abs < 0) abs = text.length;
            const codeEl = pre.querySelector("code") || pre;
            // A newline at the very end gets a zero-width space after it: Chrome
            // reads a caret after a trailing newline as the end of the previous
            // line and would put the next keystroke on the line above. The marker
            // is invisible, stripped by the serializer, and marks the line as
            // Enter-made, which is what lets a second Enter leave the block.
            const nl = abs === text.length ? "\n\u200b" : "\n";
            codeEl.textContent = text.slice(0, abs) + nl + text.slice(abs);
            const r = document.createRange();
            r.setStart(codeEl.firstChild, abs + nl.length);
            r.collapse(true);
            sel.removeAllRanges();
            sel.addRange(r);
          }
          return;
        }
      }
      // Tab indents: inside a list it nests the item one level deeper (Shift+Tab
      // un-nests it), everywhere else it inserts a tab at the caret. Either way the
      // key never jumps focus to the pill. Outside a list, Shift+Tab keeps the
      // browser default so keyboard users can still move focus backward.
      if (e.key === "Tab") {
        const node = window.getSelection().anchorNode;
        const el =
          node && node.nodeType === 1 ? node : node && node.parentElement;
        const li = el && el.closest ? el.closest("li") : null;
        if (li) {
          e.preventDefault();
          // Indenting the first item of a list has nothing to nest under (matching
          // Word/Notion); outdent at the top level is likewise a no-op. The moves
          // keep the caret's text node alive; Chrome still re-anchors the selection
          // on the list container, so put the caret back where it was afterwards.
          const sel = window.getSelection();
          const saved =
            sel.rangeCount && sel.getRangeAt(0)
              ? {
                  node: sel.getRangeAt(0).startContainer,
                  offset: sel.getRangeAt(0).startOffset,
                }
              : null;
          const moved = e.shiftKey
            ? outdentItem(li)
            : li.parentElement.firstElementChild !== li && indentItem(li);
          if (moved) {
            const restoreCaret = () => {
              if (!saved || !saved.node || !saved.node.parentNode) return;
              try {
                const range = document.createRange();
                range.setStart(
                  saved.node,
                  Math.min(saved.offset, saved.node.length || 0),
                );
                range.collapse(true);
                sel.removeAllRanges();
                sel.addRange(range);
              } catch {
                /* anchor node detached; nothing to restore */
              }
            };
            restoreCaret();
            setTimeout(restoreCaret, 0);
          }
        } else if (!e.shiftKey) {
          e.preventDefault();
          document.execCommand("insertText", false, "\t");
        }
      }
    });
    // Paste as plain text. Pasting styled HTML from a browser would smuggle in tags the
    // serialiser cannot represent, and they would be silently lost on the next save.
    ed.addEventListener("paste", (e) => {
      e.preventDefault();
      document.execCommand(
        "insertText",
        false,
        (e.clipboardData || window.clipboardData).getData("text"),
      );
    });

    if (focus) {
      ed.focus();
      // Place the caret inside the seeded block (before its <br>), never on the
      // editable's element boundary, so the next keystroke types into the <p>.
      // Only the freshly seeded mount needs this; an editor with content keeps
      // the browser's own caret.
      if (!html) {
        const first = ed.firstElementChild;
        const r = document.createRange();
        r.setStart(first.firstChild || first, 0);
        r.collapse(true);
        const s = window.getSelection();
        s.removeAllRanges();
        s.addRange(r);
      }
    }
  }

  // NOTE.2 + NOTE.3: the header always shows the truth about the note's title -
  // the explicit title if one is set, else the live first-line derivation that
  // mirrors notes.py's title_from_body via md.js's titleFromBody (same heading
  // rule, same stripping, same cap), so the header shows exactly what the server
  // will store on save. An explicit title (NOTE.0) is never clobbered by the
  // body, and an in-progress edit (<input> in the header) is never overwritten.
  function refreshTitleHeader() {
    if (!ctx || ctx.kind !== "note") return;
    const h = document.getElementById("titleH1");
    if (!h || h.querySelector("input")) return;
    if (ctx.titleExplicit) {
      h.textContent = ctx.title || "Untitled";
    } else {
      const ed = document.getElementById("body");
      h.textContent = titleFromBody(htmlToMd(ed));
    }
  }

  // NOTE.3: the header title is click-to-edit. Clicking swaps the <h1> for an
  // inline input; Enter or blur commits the explicit title (an empty commit
  // clears it back to the live first-line derivation), Escape cancels without
  // saving. The explicit intent lives server-side (artifacts.title_explicit),
  // so a later body-only save never re-derives over a hand-set title.
  let titleDraft = null;

  function mountTitleEdit(id) {
    titleDraft = null;
    const h = document.getElementById("titleH1");
    if (!h || !ctx || ctx.kind !== "note") return;
    h.classList.add("editable-title");
    h.title = "Click to rename this note";
    h.addEventListener("click", () => beginTitleEdit(h));
  }

  function beginTitleEdit(h) {
    if (titleDraft) return;
    const input = document.createElement("input");
    input.type = "text";
    input.className = "title-edit";
    input.setAttribute("aria-label", "Note title");
    // Pre-fill with what the note is currently titled - explicit or derived - so
    // clearing back to derived is "delete the text", not retyping from memory.
    input.value = titleDraftValue();
    input.placeholder = "Untitled";
    h.textContent = "";
    h.appendChild(input);
    input.focus();
    input.select();
    titleDraft = input;
    input.addEventListener("blur", () => commitTitleEdit(h));
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        input.blur();
      } else if (e.key === "Escape") {
        e.preventDefault();
        cancelTitleEdit(h);
      }
    });
  }

  function titleDraftValue() {
    const ed = document.getElementById("body");
    return ctx.titleExplicit
      ? ctx.title || "Untitled"
      : titleFromBody(htmlToMd(ed));
  }

  function cancelTitleEdit(h) {
    titleDraft = null;
    h.textContent = "";
    refreshTitleHeader();
  }

  async function commitTitleEdit(h) {
    const input = titleDraft;
    titleDraft = null;
    if (!input || !ctx) return;
    const value = input.value.trim();
    const ed = document.getElementById("body");
    const currentBody = ed ? htmlToMd(ed) : ctx.saved || "";
    // An unchanged commit is a no-op: it must not freeze a derived title by
    // accident (a click followed by a click elsewhere is not an edit). Only a
    // changed or cleared title sends a PATCH.
    const currentTitle = ctx.titleExplicit
      ? ctx.title || "Untitled"
      : titleFromBody(currentBody);
    if (value === currentTitle) {
      cancelTitleEdit(h);
      return;
    }
    try {
      const d = await api("/artifacts/" + ctx.id + "/body", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: currentBody, title: value }),
      });
      if (!ctx) return;
      ctx.title = d.artifact.title;
      ctx.titleExplicit = d.artifact.title_explicit;
      ctx.saved = currentBody;
    } catch (err) {
      toast(String((err && err.message) || err), true);
      cancelTitleEdit(h);
      return;
    }
    h.textContent = "";
    refreshTitleHeader();
    const state = document.getElementById("state");
    if (state) {
      state.className = "saved";
      state.textContent = "kept";
      setTimeout(() => {
        if (state.textContent === "kept") state.textContent = "";
      }, 2200);
    }
  }

  async function saveBody() {
    if (!ctx) return;
    const ed = document.getElementById("body"),
      state = document.getElementById("state");
    if (!ed || !state) return;
    const text = htmlToMd(ed);
    if (text === ctx.saved) return;

    try {
      if (ctx.kind === "note") {
        await api("/artifacts/" + ctx.id + "/body", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ body: text }),
        });
        const v = document.getElementById("vers");
        if (v) {
          const n = Number(v.dataset.n || 0) + 1;
          v.dataset.n = n;
          // "3 versions" is a row count. What it means is that nothing you wrote is gone.
          v.textContent = n > 1 ? n + " drafts kept" : "";
        }
      } else {
        if (!text.trim()) return;
        const r = await api("/artifacts/" + ctx.id + "/annotations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, supersedes_id: ctx.entryId }),
        });
        ctx.entryId = r.id;
      }
    } catch (err) {
      state.className = "meta";
      state.textContent = String(err);
      return;
    }

    ctx.saved = text;
    state.className = "saved";
    state.textContent = ctx.kind === "note" ? "kept" : "noted";

    // The rule under the editor fills once in the artifact's own colour. It reads as
    // the page acknowledging the words rather than a toast arriving from elsewhere.
    const bar = state.closest(".bar");
    if (bar) {
      bar.classList.remove("landed");
      void bar.offsetWidth;
      bar.classList.add("landed");
    }
    setTimeout(() => {
      if (state.textContent === "saved") state.textContent = "";
    }, 2200);
  }

  // The exhibit page (M.6): `showExhibit()` and its rename pencil were the
  // redundant collections path Phase M removes. Saved groupings own the
  // grouping concept now; an old #e/<id> bookmark falls back to the wall.

  // Rename a saved grouping (a pivot recipe) from the custom wall or the saved
  // groupings list (L.3b). Same styled modal family as the grouping pencils, but it posts
  // PATCH /pivots/<id> - the spec (the arrangement) is untouched, only the label
  // moves. Re-renders whichever surface shows the list: the open saved-groupings
  // modal (L.5), or the saved-groupings sub-view.
  async function renameSavedGrouping(ev, id) {
    if (ev) ev.stopPropagation();
    const card =
      view.querySelector('.card[data-pivot="' + id + '"]') ||
      document.querySelector('.customrow[data-pivot="' + id + '"]');
    const current = card
      ? (card.querySelector(".title") || card.querySelector(".rowname") || {})
          .textContent
      : "";
    const name = await askGroupName(
      "Rename this view",
      "View name",
      "Save",
      current,
      "Saved views re-run live as your library grows; renaming changes only the label.",
    );
    if (!name || name === current) return;
    try {
      await api("/pivots/" + id, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
    } catch (err) {
      return toast(String((err && err.message) || err), true);
    }
    toast('Renamed to "' + name + '".');
    // Re-render whichever surface shows the list: the open saved-groupings
    // modal (L.5), or the saved-groupings sub-view.
    const picker = document.querySelector("dialog.ask #customPickerList");
    if (picker && picker.closest("dialog").open) {
      await refreshCustomPicker();
      return;
    }
    showSavedGroupings();
  }
