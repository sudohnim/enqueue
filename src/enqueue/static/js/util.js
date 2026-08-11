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
    return (n / Math.pow(1024, i)).toFixed(i ? 1 : 0) + " " + units[i];
  }

  // DI.1: settings is one tabbed surface, not four stacked full pages. Each tab
  // renders only the form content below the shared tab bar, and switching tabs
  // swaps that one pane - no teardown, no back button, no loading flash.
