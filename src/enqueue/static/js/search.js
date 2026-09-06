
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
      '<div class="back" onclick="home()">&larr; everything</div>' +
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

  async function doSearch(q) {
    teardown();
    setRoute("s/" + encodeURIComponent(q));
    const tagName = tagFilterName(q);
    if (tagName) return renderTagWall(q, tagName);
    view.innerHTML = spinner("lg", "searching...");
    let r;
    try {
      r = await api("/search?limit=20&q=" + encodeURIComponent(q));
    } catch (err) {
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
    view.innerHTML =
      '<div class="back" onclick="home()">&larr; everything</div>' +
      '<div class="shelf center">' +
      r.hits.length +
      " result" +
      (r.hits.length === 1 ? "" : "s") +
      " for &ldquo;" +
      esc(q) +
      "&rdquo;" +
      "</div>" +
      (r.hits.length
        ? r.hits
            .map(
              (h) =>
                '<div class="item" tabindex="0" role="button"' +
                " onclick=\"showArtifact('" +
                h.artifact_id +
                "')\"" +
                " onkeydown=\"rowKey(event, () => showArtifact('" +
                h.artifact_id +
                "'))\">" +
                '<div class="item-body"><div class="title">' +
                esc(h.title) +
                "</div>" +
                '<div class="excerpt">' +
                esc(h.snippet) +
                "</div>" +
                '<div class="meta">' +
                h.score.toFixed(3) +
                "</div></div></div>",
            )
            .join("")
        : '<div class="state">Nothing matched those words.<br><br>Search finds things you can ' +
          "name. If you are chasing an idea rather than a phrase, ask instead and let the room " +
          "assemble itself.</div>");
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

