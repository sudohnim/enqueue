  // ---- pivot ---------------------------------------------------------------
  // Grouping is no longer its own pill door: the eye routes an "organize ..."
  // request through the assistant (a typed turn), and the grid button re-runs a
  // saved grouping. Both reuse renderPivot / pivotGroupsHtml below. pivotFailed
  // is shared by runSavedGrouping.
  function pivotFailed(err) {
    view.innerHTML =
      back() +
      '<div class="state">That could not be organized.<br><br><span class="strongtext">' +
      esc(String((err && err.message) || err)) +
      "</span><br><br>Nothing was lost; your library is untouched.</div>";
  }

  // The last pivot, kept so a correction can re-run the exact same spec (cheap,
  // because every derive call is cached) instead of re-planning from the words.
  let pivotState = null;

  // The group markup both surfaces share - the standalone pivot view and the
  // in-chat organize turn. One renderer, two homes: a second grouping renderer
  // would drift from the first the moment either changed. `makeMove` /
  // `makeRemove` build each card's per-card action onclick; the remove control
  // only renders when a callback is supplied (only the saved-grouping view has
  // a pivot to exclude from).
  // Collapsed header tooltip (N.2c): the first few card titles, so hovering a
  // folded group previews its contents without expanding. Native title - the
  // browser draws it, and screen readers announce it.
  function groupPreview(items) {
    return (
      items
        .slice(0, 3)
        .map((t) => t.title)
        .join(", ") + (items.length > 3 ? "..." : "")
    );
  }

  function pivotGroupsHtml(d, makeMove, makeRemove, spec, pivot_id) {
    let html = "";
    // Collapsed choices persist per recipe (K.10): the same spec re-run keeps
    // the groups the person folded away, and a different grouping starts open.
    const collapsed = collapsedSet("enqueue.collapsedGroups." + specHash(spec));

    for (const g of d.groups) {
      const items = g.items || [];
      const key = g.key || "Not determined";
      const isCollapsed = collapsed.has(key);
      html +=
        '<section class="pivotgroup' +
        (isCollapsed ? " collapsed" : "") +
        '" data-key="' +
        esc(key) +
        '">' +
        '<button class="h2 grouptoggle" type="button" aria-expanded="' +
        String(!isCollapsed) +
        '" title="' +
        esc(isCollapsed ? groupPreview(items) : "") +
        '"><span>' +
        esc(key) +
        '</span><span class="gchev" aria-hidden="true">' +
        svg("chev") +
        "</span></button>" +
        (pivot_id
          ? '<button class="groupdel" aria-label="Delete group ' +
            esc(key) +
            ' and all its artifacts from this view" title="Delete this group" ' +
            "onclick=\"deletePivotGroup('" +
            esc(pivot_id) +
            "', '" +
            esc(key) +
            "')\">" +
            svg("trash") +
            "</button>"
          : "") +
        '<div class="meta">' +
        items.length +
        " item" +
        (items.length === 1 ? "" : "s") +
        "</div>" +
        '<div class="wall">' +
        items
          .map(
            (a, i) =>
              '<div class="pivotcard">' +
              card(a, i) +
              '<button class="movebtn" aria-label="Move ' +
              esc(a.title || "Untitled") +
              ' to another group" ' +
              makeMove(a.id) +
              '">' +
              svg("move") +
              "</button>" +
              (makeRemove
                ? '<button class="removebtn" aria-label="Remove ' +
                  esc(a.title || "Untitled") +
                  ' from this view" ' +
                  makeRemove(a.id) +
                  '">' +
                  svg("close") +
                  "</button>"
                : "") +
              "</div>",
          )
          .join("") +
        "</div>" +
        "</section>";
    }
    return html;
  }

  // ---- collapsible group headers (K.10) ----------------------------------
  // A stable hash of the spec names the sessionStorage key, so the same recipe
  // re-run preserves the folded groups while a different grouping starts open.
  function specHash(spec) {
    const s = JSON.stringify(spec || {});
    let h = 5381;
    for (let i = 0; i < s.length; i++) {
      h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
    }
    return h.toString(36);
  }

  // The standalone pivot view: a saved grouping re-run (or a fresh run behind
  // the grid button) rendered under `view`. `pivot_id` is the saved grouping
  // backing this view when there is one - the remove/restore actions need it;
  // a live run without a saved grouping has no remove actions, just moves.
  function renderPivot(d, request, spec, pivot_id) {
    pivotState = { d, request, spec, pivot_id: pivot_id || null };

    let html =
      back() +
      '<div class="h1">' +
      esc(request) +
      "</div>" +
      '<div class="meta">' +
      d.groups.length +
      " group" +
      (d.groups.length === 1 ? "" : "s") +
      " &middot; grouped by " +
      esc(d.group_by) +
      (d.truncated ? " &middot; first 200 only" : "") +
      "</div>";

    html += pivotGroupsHtml(
      d,
      (id) => "onclick=\"pivotMove('" + esc(id) + "')\"",
      pivot_id ? (id) => "onclick=\"pivotRemove('" + esc(id) + "')\"" : null,
      spec,
      pivot_id,
    );
    view.innerHTML = html;
    mountCollapsible(".pivotgroup", "enqueue.collapsedGroups." + specHash(spec));
    removedSection(spec, pivot_id);
    window.scrollTo(0, 0);
  }

  // The "Removed" shelf at the bottom of a saved grouping: the artifacts
  // excluded from this grouping (L.6b), hydrated into the same card shape the
  // groups use, each with a restore button that puts it back. The shelf only
  // renders when the grouping actually has exclusions.
  async function removedSection(spec, pivot_id) {
    if (!pivot_id) return;
    const ids = spec.excluded_ids || [];
    if (!ids.length) return;

    // Fetch the excluded cards in parallel (P.3a): the shelf is a list of
    // ids, and serial round trips made a long exclusion list slow.
    const settled = await Promise.all(
      ids.map(async (id) => {
        try {
          const d = await api("/artifacts/" + id);
          return Object.assign({}, d.artifact, {
            excerpt: d.artifact.body
              ? mdText(d.artifact.body)
                  .slice(0, 200)
                  .replace(/\n[^\n]*$/, "")
              : "",
            has_preview_image:
              d.artifact.kind === "link" && d.preview && !!d.preview.image_url,
          });
        } catch (_) {
          // A deleted artifact just does not render a card in the shelf.
          return null;
        }
      }),
    );
    const items = settled.filter(Boolean);
    if (!items.length) return;

    const box = document.createElement("section");
    box.className = "pivotgroup removedgroup";
    box.setAttribute("data-key", "Removed");
    box.innerHTML =
      '<button class="h2 grouptoggle" type="button" aria-expanded="true"><span>Removed</span><span class="gchev" aria-hidden="true">' +
      svg("chev") +
      "</span></button>" +
      '<div class="meta">' +
      items.length +
      " item" +
      (items.length === 1 ? "" : "s") +
      "</div>" +
      '<div class="wall">' +
      items
        .map(
          (a) =>
            '<div class="pivotcard">' +
            card(a, 0) +
            '<button class="restorebtn" aria-label="Restore ' +
            esc(a.title || "Untitled") +
            ' to this view" onclick="pivotRestore(\'' +
            esc(a.id) +
            "')\">restore</button>" +
            "</div>",
        )
        .join("") +
      "</div>";
    view.appendChild(box);
    box.querySelector(".grouptoggle").addEventListener("click", () => {
      box.classList.toggle("collapsed");
      box
        .querySelector(".grouptoggle")
        .setAttribute(
          "aria-expanded",
          String(!box.classList.contains("collapsed")),
        );
    });
  }

  // Remove a card from this saved grouping (L.6b): write the exclusion into the
  // stored spec, re-run, and re-render. The artifact itself is untouched - it
  // still lives on the wall - it just stops matching this grouping.
  // The shared tail of the exclude flows (L.6b/R.3): write exclusions for one
  // or several artifact ids into the stored spec, re-run the view, and
  // re-render it. The bulk endpoint does the whole list in one request (P.3b),
  // and its response carries the full excluded_ids, so the local spec is
  // synced BEFORE the run so the run actually filters them out. The artifact
  // itself is untouched - it still lives on the wall - it just stops matching
  // this grouping.
  async function excludeAndRerun(pivotId, ids, undo, busy, done) {
    let excluded = pivotState.spec.excluded_ids || [];
    try {
      const resp = await api("/pivots/" + pivotId + "/exclude-many", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          undo ? { artifact_ids: ids, undo: true } : { artifact_ids: ids },
        ),
      });
      excluded = resp.excluded_ids;
    } catch (err) {
      return toast(String((err && err.message) || err), true);
    }
    pivotState.spec = Object.assign({}, pivotState.spec, {
      excluded_ids: excluded,
    });

    view.innerHTML = busy;
    let next;
    try {
      next = await api("/pivot/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spec: pivotState.spec }),
      });
    } catch (err) {
      return pivotFailed(err);
    }
    renderPivot(next, pivotState.request, pivotState.spec, pivotId);
    done();
  }

  async function pivotRemove(id) {
    if (!pivotState || !pivotState.pivot_id) return;
    await excludeAndRerun(
      pivotState.pivot_id,
      [id],
      false,
      spinner("lg", "removing it..."),
      () => toast("Removed from this view."),
    );
  }

  // Delete a whole group from a saved view (R.3): exclude every artifact in the
  // section, then re-run and re-render. The artifacts stay in the library - they
  // just stop matching this arrangement and move to the Removed shelf, where
  // they can be restored one at a time. The confirmation names the group and
  // counts the artifacts before anything is written.
  async function deletePivotGroup(pivotId, groupKey) {
    if (!pivotState || !pivotState.pivot_id || pivotState.pivot_id !== pivotId)
      return;
    const d = pivotState.d;
    const group = d.groups.find(
      (g) => (g.key || "Not determined") === groupKey,
    );
    if (!group) return;
    const ids = group.artifact_ids || [];
    const count = ids.length;
    if (!count) return;
    const yes = await ask(
      'Delete "' + groupKey + '"?',
      "This removes " +
        count +
        " artifact" +
        (count === 1 ? "" : "s") +
        " from this view. They stay in your library - they just no longer appear in this arrangement. You can undo this from the Removed shelf.",
      "Delete group",
    );
    if (!yes) return;
    await excludeAndRerun(
      pivotId,
      ids,
      false,
      spinner("lg", "removing " + count + " artifacts..."),
      () =>
        toast(
          'Deleted "' +
            groupKey +
            '" (' +
            count +
            " artifact" +
            (count === 1 ? "" : "s") +
            " removed).",
        ),
    );
  }

  // Put a removed card back: undo the exclusion and re-run, mirroring pivotRemove.
  async function pivotRestore(id) {
    if (!pivotState || !pivotState.pivot_id) return;
    await excludeAndRerun(
      pivotState.pivot_id,
      [id],
      true,
      spinner("lg", "restoring it..."),
      () => toast("Restored to this view."),
    );
  }

  // Extend a chat organize turn with an artifact (N.3a): pick one from the
  // library and land it in the arrangement by re-running the turn's spec with
  // the id appended to included_ids. The spec lives in memory until the person
  // saves it, so the toast says so - the local mutation is the seed, Save is
  // the persist.
  async function chatAddArtifactToTurn(mid) {
    const st = organizeTurns[mid];
    if (!st) return;
    const id = await pickArtifact(st.spec);
    if (!id) return;
    const included = st.spec.included_ids || [];
    if (included.includes(id)) return toast("That is already in this view.");
    st.spec = Object.assign({}, st.spec, {
      included_ids: included.concat([id]),
    });

    const slot = document.getElementById("org-" + mid);
    if (!slot) return;
    slot.innerHTML = spinner("sm", "adding it...");
    try {
      st.d = await api("/pivot/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spec: st.spec }),
      });
    } catch (err) {
      slot.innerHTML =
        '<div class="state">That view could not be re-run: ' +
        esc(String((err && err.message) || err)) +
        ".</div>";
      return;
    }
    slot.innerHTML = organizeSlotHtml(mid);
    toast("Added to this view. Save the view to keep it.");
  }

  // A modal picker over the person's artifacts: a search box filters the list,
  // picking one resolves its id, cancel resolves null. Built like pickGroup
  // (WKWebView ships no window.prompt) - the choice is captured in a closure,
  // never round-tripped through an HTML attribute. When a spec is passed, the
  // list is the view's *addable* artifacts (N.3a/b fix): a run covers its
  // subset's matches, so offering already-covered artifacts made every pick a
  // no-op that toasted "already in this view".
  function pickArtifact(spec) {
    const box = modalShell(
      '<h2 id="pickTitle">Add an artifact to this view</h2>' +
        '<input class="picksearch" type="search" placeholder="Search your library..." autocomplete="off">' +
        '<div class="pickgroups"></div>' +
        '<div class="asked"><button class="btn secondary" value="no">Cancel</button></div>',
      { labelledBy: "pickTitle", focusSel: ".picksearch" },
    );

    const list = box.querySelector(".pickgroups");
    const field = box.querySelector(".picksearch");
    let all = [];
    // The empty state must tell a loaded-but-empty list (a view that already
    // covers everything) from a fetch that has not landed yet: the picker
    // says "Nothing left to add." for the first and keeps "Loading..." for
    // the second.
    let loaded = false;

    const render = (q) => {
      const ql = (q || "").trim().toLowerCase();
      const shown = ql
        ? all.filter((a) => (a.title || "").toLowerCase().includes(ql))
        : all;
      list.textContent = "";
      if (!shown.length) {
        const none = document.createElement("div");
        if (!ql && !loaded) {
          none.innerHTML = spinner("sm", "Loading your library...");
        } else {
          none.className = "aside";
          none.textContent = ql ? "No artifact matches that." : "Nothing left to add.";
        }
        list.appendChild(none);
        return;
      }
      for (const a of shown) {
        const b = document.createElement("button");
        b.className = "btn tertiary pickrow";
        b.textContent = a.title || "Untitled";
        b.onclick = () => box.finish(a.id);
        list.appendChild(b);
      }
    };

    field.addEventListener("input", () => render(field.value));
    const load = spec
      ? api("/pivot/addable", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ spec }),
        }).then((d) => (d && d.items) || [])
      : api("/artifacts?limit=200&order=touched").then(
          (d) => (d && d.items) || [],
        );
    load
      .then((items) => {
        // A grouping groups artifacts; conversations are not artifacts, so the
        // picker never offers them (a chat has no group_by attribute to read).
        all = items.filter((a) => a.id && a.kind !== "chat");
        loaded = true;
        render(field.value);
      })
      .catch(() => {
        loaded = true;
        render(field.value);
      });

    return box.promise;
  }

  // Correct a misfiled card: write a user override on the grouping attribute for
  // this one artifact, then re-run the same spec so the card lands where the
  // person put it. The override always wins over the model on read (rule 2: the
  // director beats the curator), so the move survives every later re-run. Every
  // field here comes from the run's own data - no attribute name is hardcoded.
  // The correction both move flows start from: which group holds this artifact,
  // which groups exist, and which group the person wants it in instead. Resolves
  // the chosen group key, or null when the picker is cancelled or the override
  // write fails - the callers then leave everything as it is.
  async function chooseMoveGroup(d, id) {
    let current = "";
    for (const g of d.groups) {
      if ((g.artifact_ids || []).includes(id)) {
        current = g.key;
        break;
      }
    }
    const keys = d.groups.map((g) => g.key);

    const target = await pickGroup(keys, current);
    if (target === null) return null;

    try {
      await api("/derived/override", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope: "artifact",
          subject: id,
          attribute: d.group_by,
          value: target,
        }),
      });
    } catch (err) {
      toast(String((err && err.message) || err), true);
      return null;
    }
    return target;
  }

  async function pivotMove(id) {
    if (!pivotState) return;
    const target = await chooseMoveGroup(pivotState.d, id);
    if (target === null) return;

    view.innerHTML = spinner("lg", "moving it...");
    let next;
    try {
      next = await api("/pivot/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spec: pivotState.spec }),
      });
    } catch (err) {
      return pivotFailed(err);
    }
    renderPivot(next, pivotState.request, pivotState.spec, pivotState.pivot_id);
    toast("Moved to " + (target || "Not determined") + ".");
  }

  // A small modal picker: pick which existing group a card belongs in. Resolves the
  // chosen group key, or null on cancel. Built like `ask` (WKWebView ships no
  // window.prompt), with the keys captured in closures so no value is round-tripped
  // through an HTML attribute.
  function pickGroup(keys, currentKey) {
    const box = modalShell(
      '<h2 id="pickTitle">Move to which group?</h2>' +
        '<div class="pickgroups"></div>' +
        '<div class="asked"><button class="btn secondary" value="no">Cancel</button></div>',
      { labelledBy: "pickTitle" },
    );

    const list = box.querySelector(".pickgroups");
    const others = keys.filter((k) => k !== currentKey);
    for (const k of others) {
      const b = document.createElement("button");
      b.className = "btn tertiary";
      b.textContent = k || "Not determined";
      b.onclick = () => box.finish(k);
      list.appendChild(b);
    }
    if (!others.length) {
      const only = document.createElement("div");
      only.className = "aside";
      only.textContent = "There is no other group to move it to yet.";
      list.appendChild(only);
    }

    return box.promise;
  }

