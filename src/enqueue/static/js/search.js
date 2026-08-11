
  // A pure `#tag` or `tag:name` query (the tag bar, or one typed by hand) gets
  // the Tagged header with a clear control; anything with free text keeps the
  // ordinary results header.
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

  async function doSearch(q) {
    teardown();
    setRoute("s/" + encodeURIComponent(q));
    view.innerHTML = '<div class="state thinking">searching...</div>';
    let r;
    try {
      r = await api("/search?limit=20&q=" + encodeURIComponent(q));
    } catch (err) {
      const msg = String((err && err.message) || err);
      if (msg.includes("Updating your search index")) {
        // The index is being rebuilt (version mismatch or first run). Show the
        // required message, then poll /doctor and re-run the search when the
        // rebuild lands - the index is never queried in its stale state.
        view.innerHTML = '<div class="state thinking">' + esc(msg) + "</div>";
        const timer = setInterval(async () => {
          const d = await api("/doctor").catch(() => null);
          if (d && d.index_state === "ready") {
            clearInterval(timer);
            doSearch(q);
          }
        }, 1000);
        return;
      }
      view.innerHTML = '<div class="state">' + esc(msg) + "</div>";
      return;
    }
    const tagName = tagFilterName(q);
    view.innerHTML =
      '<div class="back" onclick="home()">&larr; everything</div>' +
      '<div class="shelf center">' +
      (tagName
        ? "Tagged #" +
          esc(tagName) +
          " &middot; " +
          r.hits.length +
          " result" +
          (r.hits.length === 1 ? "" : "s") +
          ' <button class="tagclear" type="button" onclick="home()">clear filter</button>'
        : r.hits.length +
          " result" +
          (r.hits.length === 1 ? "" : "s") +
          " for &ldquo;" +
          esc(q) +
          "&rdquo;") +
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

