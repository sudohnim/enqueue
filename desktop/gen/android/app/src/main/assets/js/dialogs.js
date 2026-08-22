  /// engine, so a version that resolved there never resolved at all: `await
  /// ask(...)` hung and the delete still did not happen. Settling at the source
  /// removes the dependency entirely, and `done` keeps the double path from
  /// resolving twice.
  function modalShell(markup, opts) {
    const o = opts || {};
    const box = document.createElement("dialog");
    box.className = "ask";
    box.innerHTML = markup;
    if (o.labelledBy) box.setAttribute("aria-labelledby", o.labelledBy);

    box.promise = new Promise((resolve) => {
      let done = false;
      const finish = (answer) => {
        if (done) return;
        done = true;
        try {
          box.close();
        } catch (_) {
          // Already closed by the platform; the node still has to go.
        }
        box.remove();
        resolve(answer);
      };
      box.finish = finish;

      const cancel = () =>
        finish(o.cancelValue === undefined ? null : o.cancelValue);
      box.querySelector('[value="no"]').onclick = cancel;
      // Esc means no. `cancel` is the specified path; the keydown is the
      // fallback for engines that skip it, and finish() makes the overlap
      // harmless.
      box.addEventListener("cancel", (e) => {
        e.preventDefault();
        cancel();
      });
      box.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          cancel();
        }
      });
      if (o.backdrop) {
        // A click that lands on the dialog frame itself (the backdrop, or the
        // padding ring around the content) dismisses without picking.
        box.addEventListener("click", (e) => {
          if (e.target === box) cancel();
        });
      }

      document.body.appendChild(box);
      box.showModal();
      const focus = o.focusSel
        ? box.querySelector(o.focusSel)
        : box.querySelector('[value="no"]');
      focus.focus();
    });
    return box;
  }

  /// Ask before doing something irreversible. Resolves true only on the confirm
  /// button.
  ///
  /// Replaces `window.confirm`, which the WKWebView this ships inside does not
  /// implement: it returned false without ever drawing a panel, so every guard
  /// read as "the person said no" and the action was skipped in silence.
  function ask(title, detail, confirmLabel) {
    const box = modalShell(
      '<h2 id="askTitle"></h2><p></p>' +
        '<div class="asked">' +
        '<button class="btn secondary" value="no">Cancel</button>' +
        '<button class="btn danger" value="yes"></button>' +
        "</div>",
      { labelledBy: "askTitle", cancelValue: false },
    );
    box.querySelector("h2").textContent = title;
    box.querySelector("p").textContent = detail;
    const yes = box.querySelector('[value="yes"]');
    yes.textContent = confirmLabel;
    yes.onclick = () => box.finish(true);
    return box.promise;
  }

  // A one-line text prompt, same modal shell as ask() but with a field. Resolves
  // to the trimmed value, or null on cancel/empty. Used to name a saved grouping -
  // naming is the one place a person types a name, and it is never a browser
  // prompt(), which the macOS WKWebView renders inconsistently.
  function askText(title, placeholder, confirmLabel, initial) {
    const box = modalShell(
      '<h2 id="askTitle"></h2>' +
        '<input class="field" id="askField" autocomplete="off">' +
        '<div class="asked">' +
        '<button class="btn secondary" value="no">Cancel</button>' +
        '<button class="btn primary" value="yes"></button>' +
        "</div>",
      { labelledBy: "askTitle", focusSel: "#askField" },
    );
    box.querySelector("h2").textContent = title;
    const field = box.querySelector("#askField");
    field.placeholder = placeholder || "";
    field.value = initial || "";
    box.querySelector('[value="yes"]').textContent = confirmLabel;
    const submit = () => {
      const v = field.value.trim();
      box.finish(v || null);
    };
    box.querySelector('[value="yes"]').onclick = submit;
    // Enter submits from the field; Escape is the shell's job.
    box.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        submit();
      }
    });
    return box.promise;
  }

  // The grouping-name modal gets the rich treatment askText does not: an
  // explanatory line under the title, a properly styled field, and a Save that
  // only wakes once there is something to save. askText stays the plain prompt
  // for any other caller; naming a saved grouping goes through here.
  function askGroupName(title, placeholder, confirmLabel, initial, explainer) {
    const box = modalShell(
      '<h2 id="askTitle"></h2>' +
        "<p></p>" +
        '<input class="namefield" id="askField" autocomplete="off">' +
        '<div class="asked">' +
        '<button class="btn ghost" value="no">Cancel</button>' +
        '<button class="btn primary" value="yes" disabled></button>' +
        "</div>",
      { labelledBy: "askTitle", focusSel: "#askField" },
    );
    box.classList.add("name");
    box.querySelector("h2").textContent = title;
    box.querySelector("p").textContent =
      explainer === undefined
        ? "Saved views re-run live as your library grows."
        : explainer;
    const field = box.querySelector("#askField");
    field.placeholder = placeholder || "";
    field.value = initial || "";
    const save = box.querySelector('[value="yes"]');
    save.textContent = confirmLabel;
    // Save wakes only once there is text to save: a disabled button cannot take
    // focus, so a stray Return before typing can never submit. The field's own
    // Enter handler keeps the trim/empty guard for the typed path.
    const arm = () => {
      save.disabled = field.value.trim().length === 0;
    };
    field.addEventListener("input", arm);
    arm();
    const submit = () => {
      const v = field.value.trim();
      if (!v) return; // an empty Enter does not submit
      box.finish(v);
    };
    save.onclick = submit;
    // Enter submits from the field (an empty Return is a no-op); Escape is the
    // shell's job. The field starts with focus, not the Save button, so
    // nothing is saved by accident.
    box.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        submit();
      }
    });
    return box.promise;
  }

  function pickFile(accept) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = accept;
    input.multiple = true;

    // The input has to be in the document before it is clicked. Chrome opens the
    // panel for a detached input; WKWebView, which is what the macOS window is,
    // silently does nothing, so Upload appeared to do nothing at all in the app while
    // working in a browser. Kept off-screen rather than display:none, because a
    // hidden input is not clickable either.
    input.style.cssText =
      "position:fixed;left:-9999px;top:0;width:1px;height:1px;opacity:0";
    document.body.appendChild(input);
    const done = () => input.remove();

    input.onchange = async () => {
      const failed = [];
      let saved = 0;
      for (const file of input.files) {
        const fd = new FormData();
        fd.append("file", file);
        try {
          const r = await fetch("/capture/upload", {
            method: "POST",
            body: fd,
          });
          if (!r.ok)
            throw new Error(
              (await r.json().catch(() => ({}))).detail || r.statusText,
            );
          saved++;
        } catch (err) {
          failed.push(file.name + ": " + String(err.message || err));
        }
      }
      done();
      home();
      if (failed.length) toast("Not saved. " + failed.join("; "), true);
      else if (saved) toast(saved === 1 ? "Saved." : saved + " saved.");
    };

    // Cancelling the panel fires `cancel` in modern engines and nothing at all in
    // older ones, so the node is also swept on the next focus back to the window.
    input.oncancel = done;
    window.addEventListener(
      "focus",
      () =>
        setTimeout(() => {
          if (!input.files || !input.files.length) done();
        }, 500),
      { once: true },
    );

    input.click();
  }

