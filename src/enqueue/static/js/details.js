// The Details panel's voice and reactions, shared by the desktop and the phone
// (the look is css/details.css). The panel is the raven showing what it made of the
// thing, so its header says so in the raven's voice, and the raven standing on that
// header reacts when you correct it. Both apps used to carry their own copy of
// these lines and of the hop.
(function (root) {
  "use strict";

  const READ = [
    "I read it. Here's what stuck.",
    "What I made of this one.",
    "My reading. Correct me.",
  ];

  // The header's line for an artifact. Every line is true of the state it is shown
  // in; which "read it" line an artifact gets is fixed by its id, so it does not
  // change between visits. `state`: {lines, generating, skip}.
  function voice(state, id) {
    state = state || {};
    if (state.lines) {
      let h = 0;
      for (const ch of String(id)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
      return READ[h % READ.length];
    }
    if (state.generating) return "Still reading. One moment.";
    if (state.skip === "too_short") return "Short one. Not much to read into.";
    if (state.skip === "text_only") return "I kept my eyes off this one.";
    return "Haven't read this one yet.";
  }

  // A real opening is an arrival: the raven lands and the sections settle in, once.
  // Call it only when the panel goes from closed to open, never on a re-render.
  function arrive(panel) {
    if (!panel) return;
    panel.classList.add("arriving");
    setTimeout(() => panel.classList.remove("arriving"), 950);
  }

  // You corrected the raven: it takes the note with a hop, and the eye approves.
  function nod(panel) {
    const perch = panel && panel.querySelector(".dpanel-perch");
    if (perch) {
      perch.classList.remove("hop");
      void perch.offsetWidth; // restart the hop if one is still playing
      perch.classList.add("hop");
    }
    if (root.eyeMood) root.eyeMood.play("approve");
  }

  // The line is yours now: its dot takes the accent with a small pop.
  function claim(row) {
    if (row) row.classList.add("claimed");
  }

  root.Details = { voice, arrive, nod, claim };
})(typeof window !== "undefined" ? window : globalThis);
