  // Sharing a note as a read-only link (share.py): the title bar's share button and its
  // dialogs. The link carries the key; the relay keeps only sealed bytes.

  const SHARE_SPANS = [
    ["1d", "1 day"],
    ["1w", "1 week"],
    ["never", "Until I stop it"],
  ];

  async function shareCall(id, method, body) {
    const r = await fetch("/artifacts/" + id + "/share", {
      method: method || "GET",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await r.json().catch(() => ({}));
    if (r.ok) return data;
    const d = data.detail || {};
    const err = new Error(d.message || d || r.statusText);
    err.code = d.code || "";
    throw err;
  }

  function shareFailed(err) {
    if (err.code === "pro" && typeof openUpgrade === "function") return openUpgrade("share");
    toast(String(err.message || err), true);
  }

  function shareDay(iso) {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  function shareStatus(s) {
    return (
      "Shared " +
      shareDay(s.shared_at) +
      (s.expires_at ? ", open until " + shareDay(s.expires_at) : ", open until you stop it") +
      (s.passphrase ? ", with a passphrase" : "") +
      "."
    );
  }

  // Lights the title bar's share button when the note is shared.
  async function mountShare(id) {
    const top = document.getElementById("shareToggle");
    if (!top) return;
    let s;
    try {
      s = await shareCall(id);
    } catch (_) {
      s = { shared: false };
    }
    if (!ctx || ctx.id !== id) return;
    top.classList.toggle("lit", !!s.shared);
    top.title = s.shared ? "Shared: see the link" : "Share this note";
    top.setAttribute("aria-label", s.shared ? "Shared" : "Share");
  }

  // The title bar's share button: the link of a shared note, else the dialog that makes one.
  async function shareFromTitle() {
    if (!ctx || ctx.kind !== "note") return;
    const id = ctx.id;
    let s;
    try {
      s = await shareCall(id);
    } catch (err) {
      return shareFailed(err);
    }
    if (!ctx || ctx.id !== id) return;
    return s.shared ? openSharedDialog(id, s) : openShareDialog();
  }

  async function openSharedDialog(id, s) {
    const box = modalShell(
      '<h2 id="shareTitle">Shared note</h2>' +
        "<p>" + esc(shareStatus(s)) + "</p>" +
        (s.url
          ? '<div class="share-link"><input class="share-input" readonly aria-label="Link to the note" value="' +
            esc(s.url) +
            '"><button class="btn primary" type="button" data-act="copy">Copy</button></div>'
          : "") +
        (s.changed
          ? '<p class="share-changed">The link has not caught up with your last edit yet. ' +
            '<button type="button" class="linkish" data-act="send">Send it now</button></p>'
          : "") +
        '<div class="asked share-foot"><button type="button" class="linkish share-stop" data-act="stop">Stop sharing</button>' +
        '<button class="btn secondary" value="no">Done</button></div>',
      { labelledBy: "shareTitle", focusSel: s.url ? '[data-act="copy"]' : '[value="no"]', backdrop: true },
    );
    box.classList.add("share-dialog");
    const field = box.querySelector(".share-input");
    field?.addEventListener("focus", () => field.select());
    box.querySelector('[data-act="copy"]')?.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(field.value);
        toast("Link copied");
      } catch (_) {
        field.select();
      }
    });
    box.querySelector('[data-act="send"]')?.addEventListener("click", () => {
      box.finish(null);
      updateShare();
    });
    box.querySelector('[data-act="stop"]').addEventListener("click", () => {
      box.finish(null);
      stopShare();
    });
    await box.promise;
  }

  async function openShareDialog() {
    if (!ctx || ctx.kind !== "note") return;
    const id = ctx.id;
    const box = modalShell(
      '<h2 id="shareTitle">Share this note</h2>' +
        "<p>Your edits reach the link as you make them.</p>" +
        '<fieldset class="share-span"><legend>The link opens for</legend>' +
        SHARE_SPANS.map(
          ([v, label]) =>
            '<label><input type="radio" name="shareSpan" value="' + v + '"' +
            (v === "1w" ? " checked" : "") + "> " + label + "</label>",
        ).join("") +
        "</fieldset>" +
        '<label class="share-pass"><span>Passphrase <em>(optional)</em></span>' +
        '<input class="share-input" id="sharePass" type="password" autocomplete="new-password"></label>' +
        '<p class="share-hint">With a passphrase, the link alone opens nothing. Send it apart from the link.</p>' +
        '<div class="asked"><button class="btn secondary" value="no">Cancel</button>' +
        '<button class="btn primary" value="yes">Create link</button></div>',
      { labelledBy: "shareTitle", focusSel: '[value="yes"]', backdrop: true },
    );
    box.classList.add("share-dialog");
    const yes = box.querySelector('[value="yes"]');
    yes.onclick = async () => {
      const expires = box.querySelector('input[name="shareSpan"]:checked').value;
      const passphrase = box.querySelector("#sharePass").value;
      yes.disabled = true;
      yes.textContent = "Creating...";
      try {
        const s = await shareCall(id, "POST", { expires, passphrase: passphrase || null });
        box.finish(true);
        mountShare(id);
        openSharedDialog(id, s);
      } catch (err) {
        box.finish(false);
        shareFailed(err);
      }
    };
    await box.promise;
  }

  async function updateShare() {
    if (!ctx) return;
    const id = ctx.id;
    try {
      await shareCall(id, "PUT");
      toast("The link is up to date");
    } catch (err) {
      shareFailed(err);
    }
    mountShare(id);
  }

  async function stopShare() {
    if (!ctx) return;
    const id = ctx.id;
    const yes = await ask(
      "Stop sharing this note?",
      "The link stops working for everyone who has it. Sharing again makes a new link.",
      "Stop sharing",
    );
    if (!yes) return;
    try {
      await shareCall(id, "DELETE");
    } catch (err) {
      shareFailed(err);
    }
    mountShare(id);
  }
