  // Focus is drawn by `:focus-visible` in one rule for the whole app. The engine
  // already knows the difference between a Tab and a click, and the hand-rolled
  // keyboard-nav class this replaces had drifted into four different ring colours.

  const view = document.getElementById("view");
  const pill = document.getElementById("pill");
  const esc = (s) =>
    (s ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );

  // One-entry cache for the artifact about to be opened. The morph needs the detail
  // payload in hand before the transition begins; without it the callback awaits the
  // network mid-transition and the browser tweens between two unfinished frames.
  let warmed = null;

  const api = async (p, o) => {
    if (!o && warmed && warmed.path === p) {
      const hit = warmed.body;
      warmed = null;
      return hit;
    }
    const r = await fetch(p, o);
    if (!r.ok)
      throw new Error(
        (await r.json().catch(() => ({}))).detail || r.statusText,
      );
    return r.json();
  };

  // Capture is the one act the whole product rests on, and it used to fail in silence:
  // a link that errored and an upload that 500ed both re-rendered the wall exactly like
  // success. "Nothing is ever lost" cannot be true of a thing that can drop your capture
  // without saying so, so both paths now report, and a failure keeps what you typed.
  function toast(message, bad) {
    const old = document.getElementById("toast");
    if (old) old.remove();
    const node = document.createElement("div");
    node.id = "toast";
    node.className = "toast" + (bad ? " bad" : "");
    node.setAttribute("role", "status");
    node.textContent = message;
    document.body.appendChild(node);
    setTimeout(() => node.remove(), bad ? 8000 : 2600);
  }

  /// One modal shell for every dialog in the app (M.6a). Owns dialog creation,
  /// the done guard, finish(), the close-in-try/catch + remove, the Cancel
  /// button, the cancel event and the Escape keydown, so none of the dialogs
  /// can drift from one another.
  ///
  /// The box comes back synchronously with `finish` and `promise` on it: a
  /// dialog wires its own rows or confirm button to `box.finish(value)`, and
  /// callers await `box.promise`. Cancel, Escape and (when `backdrop` is set) a
  /// click on the frame itself resolve `cancelValue` (null unless the dialog
  /// overrides it, as ask does with false). Focus lands on the Cancel button by
  /// default, so a stray Return can never trigger a confirm; `focusSel` moves
  /// it to a field.
  ///
  /// The promise is settled inside each handler rather than on the dialog's
  /// `close` event. Measured here, `close()` does not fire `close` in this
  function rowKey(event, run) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      run();
    }
  }

  function host(url) {
    try {
      return new URL(url).hostname.replace(/^www\./, "");
    } catch (e) {
      return url || "";
    }
  }

  // "Three weeks ago" is a thing people remember. A date is not, which is why the
  // wall counts backwards from now rather than printing an ISO string nobody reads.
  function since(iso) {
    const then = new Date(iso);
    if (isNaN(then)) return "undated";
    const mins = Math.round((Date.now() - then.getTime()) / 60000);
    if (mins < 2) return "just now";
    if (mins < 60) return mins + " minutes ago";
    const hours = Math.round(mins / 60);
    if (hours < 24) return hours === 1 ? "an hour ago" : hours + " hours ago";
    const days = Math.round(hours / 24);
    if (days < 7) return days === 1 ? "yesterday" : days + " days ago";
    const weeks = Math.round(days / 7);
    if (days < 60) return weeks === 1 ? "last week" : weeks + " weeks ago";
    const months = Math.round(days / 30);
    if (days < 365) return months === 1 ? "last month" : months + " months ago";
    const years = Math.round(days / 365);
    return years === 1 ? "last year" : years + " years ago";
  }

  function bytes(n) {
    if (!n) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    const i = Math.min(
      units.length - 1,
      Math.floor(Math.log(n) / Math.log(1024)),
    );
    return (n / 1024 ** i).toFixed(i ? 1 : 0) + " " + units[i];
  }

  // ANIM.1: the one reusable loading mark. `spinner("lg", "searching...")` is the
  // big centred raven for a full-view wait; `spinner("sm", ...)` is the small
  // inline raven for a conversation or row. Returns markup; the caption is the
  // text a screen reader announces, and it still communicates the wait under
  // reduced motion when the bird stops spinning.
  function spinner(size, caption) {
    const cls = size === "lg" ? "loader loader-lg" : "loader loader-sm";
    const bird =
      '<img class="loader-bird" src="/static/loading.png" alt="" aria-hidden="true">';
    const cap = caption
      ? '<span class="loader-caption">' + esc(caption) + "</span>"
      : "";
    return '<div class="' + cls + '" role="status">' + bird + cap + "</div>";
  }

  // ANIM.4: the capture-success flight. The raven flies in from the left edge to
  // centre, holds, and fades - a rehearsed one-off on a successful capture. A
  // second capture restarts it (the old bird is replaced, never stacked), and the
  // bird is pointer-events: none so it never blocks a click or the next capture.
  // Returns a promise that resolves when the flight ends, so the capture overlay
  // can hold its dismiss until the bird has been seen.
  function captureFlight() {
    const old = document.getElementById("captureFlight");
    if (old) old.remove();

    const img = document.createElement("img");
    img.id = "captureFlight";
    img.className = "capture-flight";
    img.src = "/static/capture-bird.png?v=" + Date.now();
    img.alt = "";
    img.setAttribute("aria-hidden", "true");
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      img.classList.add("reduced");
    }
    document.body.appendChild(img);

    return new Promise((resolve) => {
      setTimeout(() => {
        // No-op if a second capture already removed this bird and mounted its own.
        img.remove();
        resolve();
      }, 1900);
    });
  }

  // CAP.3: the capture overlay signals a completed capture through the shell
  // (capture_done -> "capture-flight" event), so the raven flies full-screen here in
  // the main window rather than as a tiny sweep in the 600x264 overlay. A no-op when
  // there is no Tauri (plain-browser view).
  if (window.__TAURI__ && window.__TAURI__.event && window.__TAURI__.event.listen) {
    window.__TAURI__.event.listen("capture-flight", () => captureFlight());
  }

  // DI.1: settings is one tabbed surface, not four stacked full pages. Each tab
  // renders only the form content below the shared tab bar, and switching tabs
  // swaps that one pane - no teardown, no back button, no loading flash.
