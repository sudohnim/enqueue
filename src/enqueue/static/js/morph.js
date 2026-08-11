  // ---- surfaces ------------------------------------------------------------
  // Enter and Space activate a row, the way they would if it were a real button.
  // Only one card can claim the shared names at a time: `view-transition-name` must be
  // unique in the document or the browser refuses the whole transition. So the names
  // are applied to the card being opened, held across the swap, and released after.
  let morphing = null;

  function claimMorph(id) {
    releaseMorph();
    const card = document.querySelector('.card[data-id="' + id + '"]');
    if (!card) return;

    const frame = card.querySelector("img");
    const title = card.querySelector(".title");
    if (frame) frame.style.viewTransitionName = "artifact-face";
    if (title) title.style.viewTransitionName = "artifact-title";
    morphing = card;
  }

  function releaseMorph() {
    if (!morphing) return;
    morphing.querySelectorAll("img, .title").forEach((el) => {
      el.style.viewTransitionName = "";
    });
    morphing = null;
  }

  // Wraps a navigation so the browser can tween between the two states. Falls straight
  // through where the API is missing, or where the person asked for less motion: a
  // morph is motion, and "reduced" has to mean reduced here too.
  function withMorph(run) {
    const wants = matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (wants || !document.startViewTransition) return run();
    return document.startViewTransition(run).finished.finally(releaseMorph);
  }

  // The fetch happens BEFORE the transition starts, not inside it.
  //
  // startViewTransition snapshots the page, runs the callback, then snapshots again.
  // An awaited fetch inside that callback means the browser holds a frozen frame of
  // the old page while the network happens, then swaps to a half-built new one: the
  // jumble. Warming the cache first makes the callback a synchronous DOM write, which
  // is the only thing the API can actually tween.
  async function openArtifact(id) {
    claimMorph(id);
    const path = "/artifacts/" + id;
    try {
      warmed = { path, body: await api(path) };
    } catch (err) {
      releaseMorph();
      return toast(String(err.message || err), true);
    }
    withMorph(() => showArtifact(id));
  }

