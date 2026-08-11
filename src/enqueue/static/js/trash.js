  // ---- the trash -----------------------------------------------------------
  // Everything else here is kept on purpose. This is the one surface where something
  // leaves, so it says what is going, when, and how to stop it.
  // One trash row: kind chip, title, days-left, and the two actions. The
  // standalone trash page and the settings trash tab render the same row.
  function trashRow(a) {
    return (
      '<div class="item" data-kind="' +
      esc(a.kind) +
      '"><div class="item-body">' +
      '<span class="kindrow"><span class="kindmark"></span>' +
      '<span class="kindword">' +
      esc(a.kind) +
      "</span></span>" +
      '<div class="title">' +
      esc(a.title || "Untitled") +
      "</div></div>" +
      '<span class="meta">' +
      (a.days_left > 0
        ? a.days_left + " day" + (a.days_left === 1 ? "" : "s") + " left"
        : "goes at the next launch") +
      "</span>" +
      '<div class="rowacts">' +
      '<button class="btn ghost" onclick="restoreArtifact(&#39;' +
      a.id +
      '&#39;)">Restore</button>' +
      '<button class="btn ghost harm" onclick="purgeArtifact(&#39;' +
      a.id +
      '&#39;)">Delete now</button></div></div>'
    );
  }

  async function showTrash() {
    teardown();
    restorePill("inside");
    view.innerHTML = '<div class="state">...</div>';
    const d = await api("/trash");

    let html =
      '<div class="h2">Trash</div>' +
      '<div class="aside">Deleted things wait ' +
      d.retention_days +
      " day" +
      (d.retention_days === 1 ? "" : "s") +
      ", then go for good. Nothing else here ever expires on its own.</div>";

    if (!d.items.length) {
      html += '<div class="state">Nothing in the trash.</div>';
      view.innerHTML = html;
      return;
    }

    html +=
      '<div class="callout warn">Emptying the trash deletes these files from this ' +
      "machine. It cannot be undone.</div>";

    // A list, not the wall grid. A wall implies keeping, and this page is about not
    // keeping. The full-pill radius on "Empty trash" is the one departure from the
    // 20px control radius in the app, and the shape is what flags it as terminal.
    html +=
      '<div class="trash">' +
      '<div class="trashbar"><span class="meta">' +
      d.items.length +
      " waiting</span>" +
      '<button class="btn danger terminal" onclick="emptyTrash(' +
      d.items.length +
      ')">Empty trash</button></div>';
    html += d.items.map((a) => trashRow(a)).join("");
    html += "</div>";

    view.innerHTML = html;
    window.scrollTo(0, 0);
  }

  // Skips the waiting period for everything at once, so the confirmation counts the
  // things rather than saying "are you sure".
  // The trash actions land on whichever surface is showing them: the settings
  // trash tab re-renders in place, the standalone trash page redraws itself.
  function refreshTrashSurface() {
    if (document.getElementById("settingsTabPane")) renderSettingsTab("trash");
    else showTrash();
  }

  async function emptyTrash(count) {
    const yes = await ask(
      "Empty the trash?",
      "This destroys " +
        count +
        " thing" +
        (count === 1 ? "" : "s") +
        " for good. It cannot be undone.",
      // The verb, repeated. Never "OK", never "Yes".
      "Empty trash",
    );
    if (!yes) return;

    try {
      await api("/trash", { method: "DELETE" });
    } catch (err) {
      return toast(String(err.message || err), true);
    }
    refreshTrashSurface();
    toast("Trash emptied.");
  }

  async function restoreArtifact(id) {
    try {
      await api("/artifacts/" + id + "/restore", { method: "POST" });
    } catch (err) {
      return toast("Not restored. " + String(err.message || err), true);
    }
    refreshTrashSurface();
    toast("Put back.");
  }

  // The only irreversible action in the product, so it is the only one that asks.
  async function purgeArtifact(id) {
    // The title is read from the row rather than passed through the handler: a title
    // is model- or file-derived text, and threading it through an inline onclick
    // string is how that kind of text ends up being parsed as code.
    const row = document.querySelector('[onclick*="' + id + '"]');
    const title =
      row?.closest(".item")?.querySelector(".title")?.textContent || "this";

    const yes = await ask(
      "Delete for good?",
      title + " will be destroyed. This cannot be undone.",
      "Delete",
    );
    if (!yes) return;
    try {
      await api("/trash/" + id, { method: "DELETE" });
    } catch (err) {
      return toast(String(err.message || err), true);
    }
    refreshTrashSurface();
    toast("Gone.");
  }

