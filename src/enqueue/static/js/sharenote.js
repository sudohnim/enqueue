  // Sharing a note as a read-only link (share.py): the Details panel's Share section
  // and its dialog. The link carries the key; the relay keeps only sealed bytes.

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

  function shareSectionHtml(s) {
    const head =
      '<div class="dsec-head"><span class="dsec-label">Share</span></div>';
    if (!s.shared) {
      return (
        head +
        '<p class="facet-empty">Anyone with the link can read the note as it is now. Enqueue cannot.</p>' +
        '<button class="btn secondary share-start" type="button" onclick="openShareDialog()">Share this note</button>'
      );
    }
    const when =
      "Shared " +
      shareDay(s.shared_at) +
      (s.expires_at ? ", open until " + shareDay(s.expires_at) : ", open until you stop it") +
      (s.passphrase ? ", with a passphrase" : "") +
      ".";
    return (
      head +
      '<p class="facet-empty">' + esc(when) + "</p>" +
      (s.url
        ? '<div class="share-link"><input class="share-input" readonly aria-label="Link to the note" value="' +
          esc(s.url) +
          '"><button class="btn secondary" type="button" onclick="copyShareLink()">Copy</button></div>'
        : "") +
      (s.changed
        ? '<p class="share-changed">You changed the note since you shared it. ' +
          '<button type="button" class="linkish" onclick="updateShare()">Update the shared copy</button></p>'
        : "") +
      '<button type="button" class="linkish share-stop" onclick="stopShare()">Stop sharing</button>'
    );
  }

  async function mountShare(id) {
    const box = document.getElementById("shareSec");
    if (!box) return;
    let s;
    try {
      s = await shareCall(id);
    } catch (_) {
      s = { shared: false };
    }
    if (!ctx || ctx.id !== id) return;
    box.innerHTML = shareSectionHtml(s);
  }

  async function copyShareLink() {
    const field = document.querySelector("#shareSec .share-link input");
    if (!field) return;
    try {
      await navigator.clipboard.writeText(field.value);
      toast("Link copied");
    } catch (_) {
      field.select();
    }
  }

  async function openShareDialog() {
    if (!ctx || ctx.kind !== "note") return;
    const id = ctx.id;
    const box = modalShell(
      '<h2 id="shareTitle">Share this note</h2>' +
        "<p>Anyone with the link can read the note as it is now. Later edits stay here until you update the shared copy.</p>" +
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
      { labelledBy: "shareTitle", focusSel: '[value="yes"]' },
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
        if (s.url) {
          try {
            await navigator.clipboard.writeText(s.url);
            toast("Link copied");
          } catch (_) {
            toast("Link created");
          }
        }
        mountShare(id);
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
      toast("Shared copy updated");
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
