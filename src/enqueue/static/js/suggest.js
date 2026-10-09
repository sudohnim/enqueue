// Name matching: which artifacts a few typed characters are naming.
//
// Typing a thing's name is the plainest search there is, and it should not cost a
// search: no embedding, no index, no model, no request. This ranks a list of
// {id, title, kind} against what has been typed, in the page, as fast as a
// keystroke. It is shared by the desktop (the candidates under the search bar) and
// the phone (folded into its live results), the way linkpop and the tour are.
//
// What counts, best first:
//   the title IS what was typed
//   the title starts with it
//   every typed word starts a word of the title            ("good li" -> The Good Life)
//   the title contains it                                    ("potam" -> Mesopotamia)
//   every typed word is one slip away from a title word      ("mesopotamai")
// A slip is one wrong, missing, extra or swapped letter (two in a long word), and a
// word still being typed is compared with the start of the title's word. Words of
// one or two letters must match exactly: a slip in "to" matches half the library.
(function (root) {
  "use strict";

  // Lowercase, accents folded, anything that is not a letter or digit a space.
  function norm(s) {
    return String(s || "")
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase()
      .replace(/[^\p{L}\p{N}]+/gu, " ")
      .trim();
  }

  // Edit distance with swapped neighbours counted once, abandoned past `max`.
  function slips(a, b, max) {
    if (Math.abs(a.length - b.length) > max) return max + 1;
    let prev2 = null;
    let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
    for (let i = 1; i <= a.length; i++) {
      const cur = [i];
      let best = i;
      for (let j = 1; j <= b.length; j++) {
        const cost = a[i - 1] === b[j - 1] ? 0 : 1;
        let d = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
        if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1])
          d = Math.min(d, prev2[j - 2] + 1);
        cur.push(d);
        if (d < best) best = d;
      }
      if (best > max) return max + 1;
      prev2 = prev;
      prev = cur;
    }
    return prev[b.length];
  }

  function allowed(word) {
    return word.length < 4 ? 0 : word.length < 8 ? 1 : 2;
  }

  // How far a typed word is from a title word: 0 when it starts it, else the slips
  // against the whole word or (a word still being typed) against its beginning.
  function wordGap(typed, word) {
    if (word.startsWith(typed)) return 0;
    const max = allowed(typed);
    if (!max) return Infinity;
    let gap = slips(typed, word, max);
    if (word.length > typed.length)
      gap = Math.min(gap, slips(typed, word.slice(0, typed.length), max));
    return gap <= max ? gap : Infinity;
  }

  function score(q, qWords, title) {
    if (!title) return 0;
    if (title === q) return 100;
    if (title.startsWith(q)) return 90;
    const words = title.split(" ");
    let total = 0;
    for (const typed of qWords) {
      let best = Infinity;
      for (const w of words) {
        const g = wordGap(typed, w);
        if (g < best) best = g;
        if (!g) break;
      }
      if (best === Infinity) {
        total = Infinity;
        break;
      }
      total += best;
    }
    if (total === 0) return 80;
    // Two letters sit inside half the titles there are; three begin to name one.
    if (q.length >= 3 && title.includes(q)) return 70;
    if (total !== Infinity) return 60 - total * 5;
    // One word with letters run together or split ("goodlife").
    const squashed = title.replace(/ /g, "");
    const one = q.replace(/ /g, "");
    if (one.length >= 4 && squashed.includes(one)) return 50;
    return 0;
  }

  // The parts of the title, as written, that the typed words account for: for the
  // candidate list to set in ink. Exact pieces only; a slip marks nothing.
  function marks(query, title) {
    const out = [];
    const lower = String(title).toLowerCase();
    for (const typed of norm(query).split(" ")) {
      if (!typed) continue;
      let from = 0;
      while (from <= lower.length) {
        const at = lower.indexOf(typed, from);
        if (at === -1) break;
        // Only where a word begins: "art" marks Art, not the middle of "party".
        if (at === 0 || !/[\p{L}\p{N}]/u.test(lower[at - 1])) {
          out.push([at, at + typed.length]);
          break;
        }
        from = at + 1;
      }
    }
    out.sort((a, b) => a[0] - b[0]);
    const merged = [];
    for (const m of out) {
      const last = merged[merged.length - 1];
      if (last && m[0] <= last[1]) last[1] = Math.max(last[1], m[1]);
      else merged.push(m);
    }
    return merged;
  }

  // The best `limit` of `items` for `query`, each {item, score, marks}. Nothing for
  // fewer than two typed characters. `score` 80 and up is a confident name match.
  function rank(query, items, limit) {
    const q = norm(query);
    if (q.length < 2) return [];
    const qWords = q.split(" ");
    const found = [];
    for (const item of items || []) {
      const title = norm(item.title);
      const s = score(q, qWords, title);
      if (s > 0) found.push({ item, score: s, len: title.length });
    }
    found.sort((a, b) => b.score - a.score || a.len - b.len);
    return found.slice(0, limit || 6).map((f) => ({
      item: f.item,
      score: f.score,
      marks: marks(query, f.item.title || ""),
    }));
  }

  const api = { rank, norm, STRONG: 80 };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Suggest = api;
})(typeof window !== "undefined" ? window : globalThis);
