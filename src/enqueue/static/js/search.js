
  // A pure `#tag` or `tag:name` query (the tag bar, or one typed by hand) gets
  // the Tagged header with a clear control; anything with free text keeps the
  // ordinary results header. Tags carry no whitespace, so a whitespace split is
  // exact: every token is either a whole tag or free text.
  function tagFilterName(q) {
    const tokens = q.trim().split(/\s+/).filter(Boolean);
    if (!tokens.length) return null;
    const names = [];
    for (const t of tokens) {
      const rest = t.startsWith("#")
        ? t.slice(1)
        : t.startsWith("tag:")
          ? t.slice(4)
          : null;
      if (rest && rest.trim()) names.push(rest.trim().toLowerCase());
      else return null;
    }
    return names.join(" ");
  }

  // A filtered wall: the same square cards the home wall draws (card()), under a
  // back link and a count header with a clear control. Used for a pure tag filter
  // and for the untagged listing, so filtering by a tag looks like the wall it came
  // from, not a thin search-result list.
  function filteredWallView(titleHtml, items, emptyMsg) {
    view.innerHTML =
      back() +
      '<div class="shelf center">' +
      titleHtml +
      " &middot; " +
      items.length +
      " item" +
      (items.length === 1 ? "" : "s") +
      ' <button class="tagclear" type="button" onclick="home()">clear filter</button></div>' +
      (items.length
        ? '<div class="wall">' + items.map((a, i) => card(a, i)).join("") + "</div>"
        : '<div class="state">' + emptyMsg + "</div>");
  }

  // A pure tag query (a chip click, or a hand-typed `#name`) is a filter, not a
  // ranked text search: it draws the square wall of everything carrying the tag
  // rather than the search-result list. /artifacts?tags= is the wall-shaped,
  // complete (unpaged here) source; AND semantics across multiple tags.
  async function renderTagWall(q, tagName) {
    view.innerHTML = spinner("lg", "gathering...");
    const names = tagName.split(/\s+/).filter(Boolean);
    let r;
    try {
      r = await api(
        "/artifacts?tags=" + encodeURIComponent(names.join(",")) + "&order=touched&limit=200",
      );
    } catch (err) {
      view.innerHTML = '<div class="state">' + esc(String((err && err.message) || err)) + "</div>";
      return;
    }
    const title = "Tagged " + names.map((n) => "#" + esc(n)).join(" ");
    filteredWallView(title, r.items || [], "Nothing here carries that tag.");
  }

  // The query whose results are on screen, so opening one can report which search
  // found it and at what rank.
  let lastQuery = "";
  let lastHits = [];

  function openHit(id, rank) {
    reportOpen(id, "search", lastQuery, rank);
    // A note with tabs opens on the tab the hit came from (Tabs.find).
    const hit = lastHits[rank - 1];
    if (hit && hit.artifact_id === id) NoteTabs.hint(id, lastQuery, hit.snippet);
    showArtifact(id);
  }

  async function doSearch(q) {
    teardown();
    setRoute("s/" + encodeURIComponent(q));
    const tagName = tagFilterName(q);
    if (tagName) return renderTagWall(q, tagName);
    view.innerHTML = spinner("lg", "searching...");
    // The eye squints and darts while the search thinks, and opens wide on results.
    if (window.eyeMood) eyeMood.hold("search");
    let r;
    try {
      r = await api("/search?limit=20&q=" + encodeURIComponent(q));
    } catch (err) {
      if (window.eyeMood) eyeMood.drop("search");
      const msg = String((err && err.message) || err);
      if (msg.includes("Updating your search index")) {
        // The index is being rebuilt (version mismatch or first run). Show the
        // required message, then poll /doctor and re-run the search when the
        // rebuild lands - the index is never queried in its stale state.
        view.innerHTML = spinner("lg", msg);
        poll(async () => {
          const d = await api("/doctor").catch(() => null);
          if (d && d.index_state === "ready") {
            doSearch(q);
            return true;
          }
          return false;
        });
        return;
      }
      view.innerHTML = '<div class="state">' + esc(msg) + "</div>";
      return;
    }
    if (window.eyeMood) eyeMood.drop("search", r.hits.length ? "found" : null);
    lastQuery = q;
    lastHits = r.hits;
    // Hits the relevance check could not rule on (the model was unreachable) come
    // last from the engine, marked `loose`: shown apart as "Maybe related".
    const sure = r.hits.filter((h) => !h.loose);
    const loose = r.hits.filter((h) => h.loose);
    const terms = searchTerms(q);
    const rank = (h) => r.hits.indexOf(h) + 1;
    view.innerHTML =
      back() +
      '<div class="sr">' +
      '<form class="sr-field" role="search" onsubmit="event.preventDefault(); searchAgain()">' +
      '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>' +
      '<input id="searchfield" type="search" value="' +
      esc(q) +
      '" aria-label="Search your library" autocomplete="off" spellcheck="false" />' +
      '<kbd aria-hidden="true">&#8984;K</kbd></form>' +
      '<div class="sr-count" role="status">' +
      (sure.length ? sure.length + (sure.length === 1 ? " result" : " results") : "No sure results") +
      (r.filters ? '<span class="sr-chip">' + esc(r.filters) + "</span>" : "") +
      "</div>" +
      (sure.length
        ? '<ol class="sr-list">' + sure.map((h) => resultHtml(h, rank(h), terms)).join("") + "</ol>"
        : loose.length
          ? ""
          : '<div class="sr-empty"><p>Nothing in your library matches those words.</p>' +
            "<p>If you are after an idea rather than a phrase, ask the eye instead: it reads by meaning.</p></div>") +
      (loose.length
        ? '<section class="sr-maybe" aria-label="Maybe related">' +
          '<div class="sr-maybe-head">Maybe related<span>Search could not double-check these yet.</span></div>' +
          '<ol class="sr-list">' +
          loose.map((h) => maybeHtml(h, rank(h), terms)).join("") +
          "</ol></section>"
        : "") +
      "</div>";
    view.querySelector(".sr").addEventListener("keydown", resultKeys);
  }

  function searchAgain() {
    const f = document.getElementById("searchfield");
    const q = f && f.value.trim();
    if (q && q !== lastQuery) doSearch(q);
  }

  // The words worth showing a person: what they typed, without the glue words.
  const SR_FILLER = new Set(
    "a an and are as at be by did do for from had has have i in is it me my of on or so that the this to was we what when where which who why with you your about notes note saved".split(" "),
  );
  function searchTerms(q) {
    return [
      ...new Set(
        q
          .toLowerCase()
          .replace(/#\S+|tag:\S+/g, " ")
          .match(/[\p{L}\p{N}']+/gu) || [],
      ),
    ].filter((w) => w.length > 1 && !SR_FILLER.has(w));
  }

  // The passage cut around the lines that hold the searched words, read as sentences.
  function excerptOf(h, terms) {
    const raw = Tabs.plain(h.text || h.snippet || "");
    let lines = raw
      .split("\n")
      .map((l) => mdText(l).replace(/^[•·]\s*/, "").replace(/\*\*|__/g, "").trim())
      // Points run together on one line with " - " read as separate sentences.
      .flatMap((l) => l.split(/\s+[-–—]\s+/))
      .map((l) => l.replace(/\s*[-–—]+\s*$/, "").trim())
      .filter(Boolean);
    if (lines.length && h.title) {
      // A first line that is the title, or opens with it ("Mesopotamia - the..."), is dropped.
      const t = h.title.toLowerCase();
      const first = lines[0].toLowerCase();
      if (first === t) lines = lines.slice(1);
      else if (first.startsWith(t) && /^\s*[-–—:]\s*/.test(lines[0].slice(t.length)))
        lines[0] = lines[0].slice(t.length).replace(/^\s*[-–—:]\s*/, "");
    }
    if (!lines.length) return "";
    const hits = (l) => terms.filter((t) => wordAt(l, t) >= 0).length;
    let at = 0;
    lines.forEach((l, i) => {
      if (hits(l) > hits(lines[at])) at = i;
    });
    // Each line reads as a sentence: a capital to start, a full stop to end.
    const end = (l) => {
      const c = l.charAt(0).toLocaleUpperCase() + l.slice(1);
      return /([.!?:;…]|[.!?]["”’)])$/.test(c) ? c : c + ".";
    };
    let out = "";
    for (let i = at; i < lines.length && out.length < 240; i++) out += (out ? " " : "") + end(lines[i]);
    if (out.length > 260) out = out.slice(0, 260).replace(/\s+\S*$/, "") + "…";
    return (at > 0 ? "…" : "") + out;
  }

  function wordAt(text, term) {
    const m = new RegExp("(^|[^\\p{L}\\p{N}])" + term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "iu").exec(text);
    return m ? m.index + m[1].length : -1;
  }

  // Escaped text with each searched word marked where a word starts with it.
  function marked(text, terms) {
    let html = esc(text);
    if (!terms.length) return html;
    const alt = terms
      .slice()
      .sort((x, y) => y.length - x.length)
      .map((t) => esc(t).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
      .join("|");
    return html.replace(new RegExp("(^|[^\\p{L}\\p{N}&;])(" + alt + ")([\\p{L}\\p{N}]*)", "giu"), "$1<mark>$2$3</mark>");
  }

  const SR_KIND = { note: "Note", link: "Link", pdf: "PDF", image: "Image", file: "File" };
  function metaHtml(h) {
    const bits = [SR_KIND[h.kind] || "Item"];
    if (h.site) bits.push(esc(h.site));
    if (h.updated_at) bits.push(esc(since(h.updated_at)));
    return '<div class="sr-meta"><span class="kindmark"></span>' + bits.join('<span aria-hidden="true">·</span>') + "</div>";
  }

  // Why a result found by meaning is here: the summary line or the name it matched.
  function whyHtml(h, terms) {
    if (!h.matched || !/^(facet|section|entity)/.test(h.why || "")) return "";
    const label = (h.why || "").startsWith("entity") ? "Mentions" : "Same idea";
    return '<div class="sr-why"><b>' + label + "</b>" + marked(h.matched, terms) + "</div>";
  }

  function rowOpen(h, rank) {
    return (
      ' tabindex="0" role="link" data-kind="' +
      esc(h.kind || "") +
      "\" onclick=\"openHit('" +
      h.artifact_id +
      "', " +
      rank +
      ")\" onkeydown=\"rowKey(event, () => openHit('" +
      h.artifact_id +
      "', " +
      rank +
      '))"'
    );
  }

  function resultHtml(h, rank, terms) {
    const excerpt = excerptOf(h, terms);
    return (
      '<li class="sr-item"' +
      rowOpen(h, rank) +
      ">" +
      metaHtml(h) +
      '<h3 class="sr-title">' +
      marked(h.title || "Untitled", terms) +
      "</h3>" +
      whyHtml(h, terms) +
      (excerpt ? '<p class="sr-excerpt">' + marked(excerpt, terms) + "</p>" : "") +
      "</li>"
    );
  }

  function maybeHtml(h, rank, terms) {
    const line = (h.matched && /^(facet|section|entity)/.test(h.why || "") ? h.matched : excerptOf(h, terms)) || "";
    return (
      '<li class="sr-mini"' +
      rowOpen(h, rank) +
      '><span class="kindmark"></span><b>' +
      esc(h.title || "Untitled") +
      "</b><span>" +
      marked(line, terms) +
      "</span></li>"
    );
  }

  // Arrow keys walk the results; from the field, down goes to the first.
  function resultKeys(e) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const rows = [...view.querySelectorAll(".sr-item, .sr-mini")];
    const field = document.getElementById("searchfield");
    const at = rows.indexOf(document.activeElement);
    if (document.activeElement === field && e.key === "ArrowDown" && rows.length) rows[0].focus();
    else if (at >= 0) {
      if (e.key === "ArrowDown" && at + 1 < rows.length) rows[at + 1].focus();
      else if (e.key === "ArrowUp") (at ? rows[at - 1] : field).focus();
    } else return;
    e.preventDefault();
  }

  // The tag bar's "untagged" chip: the complement of a tag filter - every artifact
  // carrying no tag. A listing, not a ranked search, so it reads /artifacts?untagged=1
  // and draws the same square wall of cards a tag filter does.
  async function showUntagged() {
    teardown();
    setRoute("untagged");
    view.innerHTML = spinner("lg", "gathering...");
    let r;
    try {
      r = await api("/artifacts?untagged=1&order=touched&limit=200");
    } catch (err) {
      view.innerHTML =
        '<div class="state">' + esc(String((err && err.message) || err)) + "</div>";
      return;
    }
    filteredWallView(
      "Untagged",
      r.items || [],
      "Everything here carries a tag. Nothing is untagged.",
    );
  }

