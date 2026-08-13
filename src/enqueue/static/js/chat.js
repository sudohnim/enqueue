  // ---- chats ---------------------------------------------------------------
  // Asking is a conversation, not a single shot. The concepts a conversation turns out
  // to circle are kept beside it, and each one can still hang a room, which is the
  // only reason to store them rather than to name a chat by its first line.

  let chat = null;
  const rail = null;

  function teardown() {
    if (readerWatch) {
      readerWatch.disconnect();
      readerWatch = null;
    }
    // Leaving a screen has to take that screen's pending work with it. `ctx` is what
    // every deferred callback tests itself against, so a `ctx` that outlives its view
    // is a licence for the old screen to redraw itself over the new one.
    clearTimeout(faceWatch);
    faceWatch = null;
    // The drawer belongs to the artifact view; leaving the view takes it with it.
    const drawer = document.getElementById("drawer");
    if (drawer) drawer.classList.remove("open");
    // The greeting eye's timer and pointer listener live only while the home view
    // is up; leaving any surface clears them.
    tearDownEye();

    // A poller watching this chat's pending turns dies with the surface: a stale
    // timer must never re-render a view the person has left.
    stopPolling();
    ctx = null;
    chat = null;
    organizeTurns = {};
    // Unsaved settings edits are staging on a form, not a decision. Leaving the form
    // drops them, so stale values never follow the user between screens.
    pendingSettings = null;
  }

  async function startChat(text) {
    const asked = { kind: scope.kind, id: scope.id };
    view.innerHTML = spinner("lg", "reading what you saved...");
    let made;
    try {
      made = await api("/chats", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope_kind: asked.kind === "artifact" ? "artifact" : "everything",
          scope_id: asked.id || null,
          text,
        }),
      });
    } catch (err) {
      return chatFailed(err, text);
    }
    showChat(made.chat.id, made);
  }

  async function chatFailed(err, text) {
    const why = await api("/chats/ready").catch(() => ({
      ready: true,
      reason: null,
    }));
    view.innerHTML =
      '<div class="back" onclick="home()">&larr; everything</div>' +
      '<div class="state">' +
      (why.ready
        ? 'The assistant could not answer.<br><br><span class="strongtext">' +
          esc(String(err)) +
          "</span><br><br>Nothing was lost. Your question was " +
          esc(text) +
          "."
        : "There is nothing to answer from yet: " + esc(why.reason) + ".") +
      "</div>";
  }

  async function showChat(id, preloaded) {
    if (readerWatch) {
      readerWatch.disconnect();
      readerWatch = null;
    }
    stopPolling();
    const d = preloaded || (await api("/chats/" + id));
    chat = d;
    scope = { kind: "chat", id, label: "this conversation" };
    setRoute("c/" + id);
    renderChat(d);
    composer();
    // A person who left during an answer and came back finds the turn still
    // pending; the poller finishes it without them doing anything (H4.3).
    if (hasPending(d)) startPolling(id);
  }

  function renderChat(d) {
    // The scope is a constraint, not a subtitle. Rendered as metadata it read like a
    // caption, and a chat silently locked to one empty link answered "nothing you have
    // saved" to a question the app could answer instantly. Say what it can see, and
    // put the way out next to it.
    const scoped = d.chat.scope_kind !== "everything";
    // Side and corner shape carry the speaker, so there are no name labels under the
    // bubbles. A label on every turn is a thing to read that says nothing.
    const chip = (kind, id, label, handler) =>
      '<button class="src" data-kind="' +
      esc(kind || "") +
      '" onclick="' +
      handler +
      "('" +
      esc(id) +
      "')\">" +
      (kind ? '<span class="kindmark"></span>' : "") +
      esc(label) +
      "</button>";

    // The view rebuilds every render. Drop only the cached turns whose message is
    // no longer in the transcript - the rest keep their prior /pivot/run result so
    // a transcript change elsewhere does not re-fire every organize turn (P.3c).
    const nextTurns = {};
    for (const m of d.messages)
      if (m.kind === "organize" && m.role === "assistant" && m.id in organizeTurns)
        nextTurns[m.id] = organizeTurns[m.id];
    organizeTurns = nextTurns;

    let html =
      '<div class="transcript">' +
      '<button class="btn ghost back" onclick="home()">' +
      svg("back") +
      "Everything</button>" +
      '<div class="titlerow"><div class="h2">' +
      esc(d.chat.title) +
      "</div>" +
      '<button class="btn ghost harm" onclick="dropChat(\'' +
      d.chat.id +
      "')\">Delete</button></div>" +
      (scoped
        ? '<div class="from scopebar">' +
          '<span class="meta">reading only</span>' +
          chip("", d.chat.scope_id, d.chat.scope_label, "showArtifact") +
          "</div>"
        : '<div class="meta">reading everything</div>');

    for (const m of d.messages) {
      // A typed turn (S4): `answer` (and any unknown kind, defensively) renders
      // exactly as today; `organize` renders its label in the bubble and the
      // grouped view below it, hydrated from the stored spec.
      const organize = m.kind === "organize" && m.role === "assistant";
      // Phase H: the pending turn is a real stored message, not a fake drawn on
      // top. It renders as a thinking bubble the poller refreshes until the
      // worker fills it in; a failed turn shows its reason with a way to ask
      // again (H4.1).
      const pending = m.status === "pending" && m.role === "assistant";
      const failed = m.status === "failed" && m.role === "assistant";
      html +=
        '<div class="turn ' +
        (m.role === "user" ? "you" : "assistant") +
        '">' +
        '<div class="said md">' +
        (m.role === "user"
          ? esc(m.text)
          : pending
            ? spinner("sm", "Reading what you saved...")
            : md(m.text));
      const echoes =
        d.chat.scope_kind === "artifact" &&
        m.cited &&
        m.cited.length === 1 &&
        m.cited[0].artifact_id === d.chat.scope_id;

      // The evidence lives inside the bubble it supports. Outside it, it was a
      // footnote under the most important thing on the page.
      if (m.cited && m.cited.length && !echoes)
        html +=
          '<div class="from">' +
          m.cited
            .map((c) => chip(c.kind, c.artifact_id, c.title, "showArtifact"))
            .join("") +
          "</div>";
      else if (
        !pending &&
        !failed &&
        m.role === "assistant" &&
        !m.grounded &&
        !organize
      )
        html +=
          '<div class="unsourced">Nothing you have saved carried this.</div>';

      // The failed turn is honest about why (Rule 2), and the way out is one
      // click: the cause with a path to the fix when the worker stored one
      // (CR.2), and ask the same question again as a fresh turn (H4.4).
      if (failed) {
        if (m.error)
          html +=
            '<div class="cause">' +
            esc(m.error) +
            ' <button class="btn ghost" onclick="showSettings()">Check Settings</button></div>';
        html +=
          '<button class="btn ghost" onclick="retryTurn(\'' +
          esc(m.id) +
          "')\">Try again</button>";
      }
      html += "</div>";

      // The grouped view is not stored in the turn's text: it re-runs the stored
      // spec (S4.2), so a reload shows the same groups without re-planning. The
      // slot starts as a placeholder and hydrates right after this render.
      if (organize)
        html +=
          '<div class="org" id="org-' +
          esc(m.id) +
          '">' +
          spinner("sm", "Building the view...") +
          "</div>";
      html += "</div>";
    }

    view.innerHTML = html + "</div>";
    for (const m of d.messages)
      if (m.kind === "organize" && m.role === "assistant" && m.payload)
        hydrateOrganize(m, d);
    window.scrollTo(0, document.body.scrollHeight);
  }

  // ---- typed turns: the in-chat organize view -------------------------------
  // The organize turns currently on screen: message id -> {d (last run), spec,
  // userText}. They reuse the same run endpoint and the same group markup as the
  // standalone pivot; only the home differs. A correction re-runs the turn's own
  // spec, cheap because every derive call is cached.
  let organizeTurns = {};

  // Re-run a turn's stored spec and fill its slot. One run endpoint, no fork: the
  // same POST /pivot/run the standalone pivot used. Only turns whose spec
  // actually changed re-fire the run (P.3c): a poll that flipped some other
  // turn's status (or appended a new typed answer) re-renders the transcript,
  // but every unchanged organize turn hydrates from the prior run instead of a
  // fresh /pivot/run call.
  function hydrateOrganize(m, d) {
    const slot = document.getElementById("org-" + m.id);
    if (!slot) return;
    const idx = d.messages.indexOf(m);
    const userText =
      idx > 0 && d.messages[idx - 1].role === "user"
        ? d.messages[idx - 1].text
        : m.text;

    const cached = organizeTurns[m.id];
    if (cached && JSON.stringify(cached.spec) === JSON.stringify(m.payload)) {
      // The spec is unchanged: keep the prior /pivot/run result (refresh the
      // userText in case the prior turn was edited without touching the spec).
      organizeTurns[m.id] = { d: cached.d, spec: cached.spec, userText };
      slot.innerHTML = organizeSlotHtml(m.id);
      mountCollapsible(".pivotgroup", "enqueue.collapsedGroups." + specHash(m.payload));
      return;
    }

    api("/pivot/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec: m.payload }),
    })
      .then((result) => {
        organizeTurns[m.id] = { d: result, spec: m.payload, userText };
        slot.innerHTML = organizeSlotHtml(m.id);
        mountCollapsible(".pivotgroup", "enqueue.collapsedGroups." + specHash(m.payload));
      })
      .catch((err) => {
        slot.innerHTML =
          '<div class="state">That view could not be re-run: ' +
          esc(String((err && err.message) || err)) +
          ".</div>";
      });
  }

  // The turn's groups plus its controls (Rule 2: the routing is declared - the
  // label is in the bubble - and reversible - "Answer instead" is always here).
  function organizeSlotHtml(mid) {
    const st = organizeTurns[mid];
    if (!st) return "";
    // The actions sit at the top of the turn's result (K.8), above the first
    // group: they act on the whole grouping, and a person reads the actions
    // before the cards. The buttons stay ghost - they are reversible.
    return (
      '<div class="org-actions">' +
      '<button class="btn ghost" onclick="saveGrouping(\'' +
      mid +
      "')\">Save view</button>" +
      '<button class="btn ghost" onclick="chatAddArtifactToTurn(\'' +
      mid +
      "')\">Add artifact</button>" +
      '<button class="btn ghost" onclick="answerInstead(\'' +
      mid +
      "')\">Answer instead</button>" +
      "</div>" +
      pivotGroupsHtml(
        st.d,
        (id) => "onclick=\"chatPivotMove('" + mid + "','" + esc(id) + "')\"",
        // The turn has no saved pivot to remove from: no remove control (the
        // null keeps it out), and the spec rides in its own slot so the
        // collapsed-set keying works - it was landing in makeRemove before,
        // which called the spec object as a function on every card.
        null,
        st.spec,
        null,
      )
    );
  }

  // Keep this arrangement: name the spec that produced the turn and store it, so
  // the grid button can re-open and re-run it live. The spec is the recipe, not a
  // snapshot - naming is the only text a person types; grouping never prompts.
  async function saveGrouping(mid) {
    const st = organizeTurns[mid];
    if (!st) return;
    const name = await askGroupName(
      "Name this view",
      "e.g. By author region",
      "Save",
    );
    if (!name) return;
    try {
      await api("/pivots", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, spec: st.spec }),
      });
    } catch (err) {
      return toast(String((err && err.message) || err), true);
    }
    toast('Saved as "' + name + '". Open it under Custom on the wall.');
  }

  // Correct a misfiled card inside a chat organize turn: write a user override on
  // the grouping attribute for this one artifact, then re-run the turn's own spec
  // so the card lands where the person put it. The override always wins on read,
  // so the move survives every later re-run (S4.4).
  async function chatPivotMove(mid, id) {
    const st = organizeTurns[mid];
    if (!st) return;
    const target = await chooseMoveGroup(st.d, id);
    if (target === null) return;

    const slot = document.getElementById("org-" + mid);
    if (!slot) return;
    slot.innerHTML = spinner("sm", "moving it...");
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
    toast("Moved to " + (target || "Not determined") + ".");
  }

  // Rule 2's way back, in one click: re-send the same words forcing `answer`
  // (the dispatcher's force_skill), appending a fresh answer turn below.
  function answerInstead(mid) {
    const st = organizeTurns[mid];
    if (!st || !chat) return;
    sendInChat(st.userText, "answer");
  }

  // A conversation is scaffolding around the collection, not part of it, so this
  // removes it outright rather than sending it to the trash: there is no original to
  // recover, and the artifacts it cited are untouched either way.
  async function dropChat(id) {
    const row = document.querySelector('.thread[onclick*="' + id + '"]');
    const name = row ? row.textContent.trim() : "this conversation";
    const yes = await ask(
      "Delete this conversation?",
      name + " will be removed. The artifacts it cited stay where they are.",
      "Delete",
    );
    if (!yes) return;

    try {
      await api("/chats/" + id, { method: "DELETE" });
    } catch (err) {
      return toast("Not deleted. " + String(err.message || err), true);
    }
    if (chat && chat.chat.id === id) {
      chat = null;
      home();
    } else {
      home();
    }
    toast("Conversation deleted.");
  }

  // ---- saved groupings: the grid button's home -----------------------------
  // A saved grouping is an arrangement's recipe (the spec), not a frozen result.
  // Opening one re-runs it live, so a note captured since it was saved lands in
  // its group - the arrangement stays true as the library grows. The grid button
  // opens this list; a row runs its grouping; the small cross forgets it.
  async function showSavedGroupings() {
    teardown();
    // A sub-view, not the wall: show the inside pill so Home is a way out. This is
    // the bug fix - an empty saved-groupings list was a dead end with no way back.
    restorePill("inside");
    setRoute("g");
    const list = await api("/pivots").catch(() => ({ items: [] }));
    let html = '<div class="shelf">Saved views</div>';
    if (!list.items.length) {
      html +=
        '<div class="aside">Nothing saved yet. Ask the eye to organize your ' +
        "notes, then save the view you want to keep.</div>";
    } else {
      html +=
        '<div class="wall">' +
        list.items
          .map(
            (p) =>
              '<div class="card" data-pivot="' +
              p.id +
              '" tabindex="0" role="button" onclick="runSavedGrouping(\'' +
              p.id +
              "','" +
              esc(p.name).replace(/'/g, "\\'") +
              "')\">" +
              '<div style="padding:24px 16px">' +
              '<div class="title">' +
              esc(p.name) +
              "</div>" +
              '<button class="title-action" aria-label="Rename ' +
              esc(p.name) +
              '" title="Rename this view" onclick="renameSavedGrouping(event,\'' +
              p.id +
              "')\">" +
              svg("pencil") +
              "</button>" +
              '<button class="movebtn" aria-label="Forget ' +
              esc(p.name) +
              '" onclick="forgetSavedGrouping(event,\'' +
              p.id +
              "')\">forget</button>" +
              "</div></div>",
          )
          .join("") +
        "</div>";
    }
    view.innerHTML = html;
  }

  // Run a saved grouping: fetch its spec, run it live, and render it in the same
  // standalone pivot view (renderPivot) the planner produced - so a move works
  // through the same path. The saved name stands in for the words that planned it.
  async function runSavedGrouping(id, name) {
    teardown();
    restorePill("inside");
    setRoute("g/" + id);
    view.innerHTML = spinner("lg", "Building the view...");
    let saved;
    try {
      saved = await api("/pivots/" + id);
    } catch (err) {
      return pivotFailed(err);
    }
    let d;
    try {
      d = await api("/pivot/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spec: saved.spec }),
      });
    } catch (err) {
      return pivotFailed(err);
    }
    renderPivot(d, name || saved.name, saved.spec, saved.id);
  }

  async function forgetSavedGrouping(ev, id) {
    if (ev) ev.stopPropagation();
    try {
      await api("/pivots/" + id, { method: "DELETE" });
    } catch (err) {
      return toast(String((err && err.message) || err), true);
    }
    toast("View forgotten.");
    // If the forget happened inside the saved-groupings modal (L.5), refresh its
    // list in place; otherwise re-render the saved-groupings sub-view.
    const picker = document.querySelector("dialog.ask #customPickerList");
    if (picker && picker.closest("dialog").open) {
      await refreshCustomPicker();
      return;
    }
    showSavedGroupings();
  }

  function composer() {
    closeMenu();
    pill.classList.add("wide");
    pill.innerHTML =
      '<input id="field" placeholder="ask about ' +
      esc(chat.chat.scope_label) +
      '" autocomplete="off">' +
      '<button aria-label="Leave" onclick="home()">' +
      svg("close") +
      "</button>";

    const field = document.getElementById("field");
    field.focus();
    field.onkeydown = (e) => {
      if (e.key === "Escape") return home();
      if (e.key !== "Enter") return;
      const v = field.value.trim();
      if (!v) return;
      field.value = "";
      sendInChat(v);
    };
  }

  async function sendInChat(text, skill) {
    const id = chat.chat.id;
    let d;
    try {
      // Submitting returns immediately with a pending turn; the worker computes
      // the answer off the request thread. Nothing here awaits the model (H4.2).
      d = await api("/chats/" + id + "/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // `skill` forces a route (Rule 2's "answer instead"). JSON.stringify
        // drops an undefined value, so a plain send carries no skill at all.
        body: JSON.stringify({ text, skill }),
      });
    } catch (err) {
      chat = await api("/chats/" + id);
      renderChat(chat);
      const note = document.createElement("div");
      note.className = "callout warn";
      note.textContent = String(err);
      view.appendChild(note);
      return;
    }
    chat = d;
    renderChat(d);
    composer();
    // The turn is pending; the poller watches it resolve and stops when done.
    startPolling(id);
  }

  // ---- pending turns: the poller that watches them resolve -----------------
  // A submitted answer is computed after the request has returned. While any turn
  // in the open chat is pending, one poller re-reads the transcript every couple
  // of seconds and re-renders on change; it stops when none are pending. Leaving
  // the surface cancels it (teardown), so a stale poller never redraws a screen
  // it no longer owns, and opening a different chat starts its own.
  let pollTimer = null;
  let pollChatId = null;

  function stopPolling() {
    clearTimeout(pollTimer);
    pollTimer = null;
    pollChatId = null;
  }

  function hasPending(d) {
    return (d.messages || []).some((m) => m.status === "pending");
  }

  function startPolling(id) {
    // One poller per chat: opening a different surface (or a different chat)
    // cancels the old one before the new one starts.
    if (pollChatId !== id) stopPolling();
    if (pollTimer) return;
    pollChatId = id;
    pollTimer = setTimeout(pollTick, 2000);
  }

  async function pollTick() {
    const id = pollChatId;
    if (!id) return;
    let d;
    try {
      d = await api("/chats/" + id);
    } catch (err) {
      // The chat is gone (deleted while we waited): stop, don't thrash.
      stopPolling();
      return;
    }
    if (pollChatId !== id) return; // canceled while the fetch was in flight
    const open = chat && chat.chat.id === id;
    if (open && transcriptChanged(chat, d)) {
      chat = d;
      renderChat(d);
    }
    if (hasPending(d)) pollTimer = setTimeout(pollTick, 2000);
    else stopPolling();
  }

  // Re-render only when the transcript actually moved: a poller that redraws the
  // whole view on an unchanged tick would yank a person who scrolled up to read
  // back to the bottom every two seconds.
  function transcriptChanged(a, b) {
    if (!a || !b) return true;
    if (a.chat.title !== b.chat.title) return true;
    if ((a.topics || []).length !== (b.topics || []).length) return true;
    if (a.messages.length !== b.messages.length) return true;
    return a.messages.some((m, i) => {
      const n = b.messages[i];
      return (
        m.id !== n.id ||
        m.status !== n.status ||
        m.text !== n.text ||
        m.kind !== n.kind ||
        m.grounded !== n.grounded
      );
    });
  }

  // A failed turn's way back: ask the same question again as a fresh turn. The
  // text is the user message that preceded the failed turn - the question it was
  // answering (H4.4).
  function retryTurn(mid) {
    if (!chat) return;
    const idx = chat.messages.findIndex((m) => m.id === mid);
    if (idx < 1) return;
    const prev = chat.messages[idx - 1];
    if (prev.role !== "user") return;
    sendInChat(prev.text);
  }

