// What changed between two versions of a note, drawn as the note itself.
//
// Diff.markdown(old, now) returns the newer markdown with what was added and what was
// removed marked inline; Diff.html(old, now) runs it through md() and turns the marks
// into <ins> and <del>. The note keeps its own shape - its lists, headings and code -
// and the changes sit inside it, rather than a code-review view of raw lines.
//
// Lines are matched first, then the words of a line that changed are matched, so
// "book on amex" -> "book on chase" shows one struck word and one new one, not two
// whole lines. Marks never cross a line, and never wrap a line's markdown prefix (its
// indent, list marker, heading hashes, quote mark) or a code fence, so md() parses the
// marked text exactly as it parses the note.
//
// Shared by the desktop and the phone, like md.js. No page, no engine, no model.
const Diff = (() => {
  // Private-use characters stand for the marks until md() has run: md() escapes text,
  // and these survive it untouched.
  const INS = "";
  const INS_END = "";
  const DEL = "";
  const DEL_END = "";
  const MARKS = new RegExp("[" + INS + INS_END + DEL + DEL_END + "]", "g");

  // Longest common subsequence over two arrays, as a list of [op, a-index, b-index]:
  // "=" in both, "-" only in a, "+" only in b. The common head and tail are matched
  // first, so a typical edit compares only the few lines that differ.
  function align(a, b, same) {
    const eq = same || ((x, y) => x === y);
    let head = 0;
    while (head < a.length && head < b.length && eq(a[head], b[head])) head++;
    let tail = 0;
    while (
      tail < a.length - head &&
      tail < b.length - head &&
      eq(a[a.length - 1 - tail], b[b.length - 1 - tail])
    )
      tail++;
    const A = a.slice(head, a.length - tail);
    const B = b.slice(head, b.length - tail);
    const ops = [];
    for (let i = 0; i < head; i++) ops.push(["=", i, i]);
    // Past this size the table costs more than it is worth: what changed is shown as
    // a block removed and a block added.
    if (A.length * B.length > 4000000) {
      A.forEach((_, i) => ops.push(["-", head + i, -1]));
      B.forEach((_, j) => ops.push(["+", -1, head + j]));
    } else {
      const n = A.length;
      const m = B.length;
      const t = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
      for (let i = n - 1; i >= 0; i--)
        for (let j = m - 1; j >= 0; j--)
          t[i][j] = eq(A[i], B[j]) ? t[i + 1][j + 1] + 1 : Math.max(t[i + 1][j], t[i][j + 1]);
      let i = 0;
      let j = 0;
      while (i < n || j < m) {
        if (i < n && j < m && eq(A[i], B[j])) {
          ops.push(["=", head + i, head + j]);
          i++;
          j++;
        } else if (j < m && (i === n || t[i][j + 1] >= t[i + 1][j])) {
          ops.push(["+", -1, head + j]);
          j++;
        } else {
          ops.push(["-", head + i, -1]);
          i++;
        }
      }
    }
    for (let k = tail; k > 0; k--) ops.push(["=", a.length - k, b.length - k]);
    return ops;
  }

  // A line's markdown prefix: what md() reads as structure, never marked.
  const PREFIX = /^(\s*(?:[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+|#{1,6}\s+|>\s?)*)/;
  const FENCE = /^\s*(```|~~~)/;
  // A tab's marker line (js/tabs.js) is structure too: marked, md() would no longer
  // read it as a tab and would show the comment itself.
  const TAB = /^<!--\s*tab:.*-->\s*$/;

  function split(line) {
    const pre = (line.match(PREFIX) || [""])[0];
    return [pre, line.slice(pre.length)];
  }

  function wrap(text, open, close) {
    return text.trim() ? open + text + close : text;
  }

  // One changed line against the line it replaced: the words that differ are marked.
  function words(oldLine, newLine) {
    if (TAB.test(oldLine) || TAB.test(newLine)) return newLine;
    const [oldPre, oldText] = split(oldLine);
    const [newPre, newText] = split(newLine);
    const a = oldText.split(/(\s+)/).filter((s) => s !== "");
    const b = newText.split(/(\s+)/).filter((s) => s !== "");
    let out = "";
    let ins = "";
    let del = "";
    const flush = () => {
      out += wrap(del, DEL, DEL_END) + wrap(ins, INS, INS_END);
      del = "";
      ins = "";
    };
    for (const [op, i, j] of align(a, b)) {
      if (op === "=") {
        flush();
        out += b[j];
      } else if (op === "-") del += a[i];
      else ins += b[j];
    }
    flush();
    // A prefix that changed (a bullet that became a heading) shows on the new line.
    return (newPre || oldPre) + out;
  }

  // How alike two lines are, 0..1, by shared words: alike enough means one was edited
  // into the other; otherwise one was removed and another added.
  function alike(x, y) {
    if (TAB.test(x) !== TAB.test(y)) return 0;
    const a = split(x)[1].split(/\s+/).filter(Boolean);
    const b = split(y)[1].split(/\s+/).filter(Boolean);
    if (!a.length || !b.length) return 0;
    const pairs = align(a, b).filter(([op]) => op === "=").length;
    return (2 * pairs) / (a.length + b.length);
  }

  function markLine(line, open, close) {
    if (!line.trim() || FENCE.test(line) || TAB.test(line)) return line;
    const [pre, text] = split(line);
    return pre + wrap(text, open, close);
  }

  function markdown(oldText, newText) {
    const a = String(oldText || "").split("\n");
    const b = String(newText || "").split("\n");
    const ops = align(a, b);
    const out = [];
    let removed = [];
    let added = [];
    const flush = () => {
      // Each removed line looks ahead among the added ones for the line it became:
      // one alike in words first, else the same kind of line (a list item at the same
      // depth). Added lines it passes over are new lines; a removed line with no match
      // was deleted where it stood.
      let k = 0;
      for (const gone of removed) {
        let at = -1;
        for (let x = k; x < added.length && at < 0; x++) if (alike(gone, added[x]) >= 0.4) at = x;
        const pg = split(gone)[0];
        if (at < 0 && pg.trim())
          for (let x = k; x < added.length && at < 0; x++) if (split(added[x])[0] === pg) at = x;
        if (at < 0) {
          out.push(markLine(gone, DEL, DEL_END));
          continue;
        }
        while (k < at) out.push(markLine(added[k++], INS, INS_END));
        out.push(words(gone, added[k++]));
      }
      while (k < added.length) out.push(markLine(added[k++], INS, INS_END));
      removed = [];
      added = [];
    };
    for (const [op, i, j] of ops) {
      if (op === "=") {
        flush();
        out.push(b[j]);
      } else if (op === "-") removed.push(a[i]);
      else added.push(b[j]);
    }
    flush();
    return out.join("\n");
  }

  const TAGS = { [INS]: "<ins>", [INS_END]: "</ins>", [DEL]: "<del>", [DEL_END]: "</del>" };

  // The newer note rendered with the changes marked. `render` is md().
  function html(oldText, newText, render) {
    return render(markdown(oldText, newText)).replace(MARKS, (c) => TAGS[c]);
  }

  // Whether two versions differ at all, ignoring trailing space.
  function same(x, y) {
    return String(x || "").trimEnd() === String(y || "").trimEnd();
  }

  // When a draft was kept, as the drafts list shows it: "Today", "Yesterday", "Mar 4".
  function day(when) {
    const d = new Date(when);
    const today = new Date();
    const yesterday = new Date();
    yesterday.setDate(today.getDate() - 1);
    if (d.toDateString() === today.toDateString()) return "Today";
    if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
    const sameYear = d.getFullYear() === today.getFullYear();
    return d.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      ...(sameYear ? {} : { year: "numeric" }),
    });
  }

  function time(when) {
    return new Date(when).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }

  return { markdown, html, same, align, day, time, INS, INS_END, DEL, DEL_END };
})();

if (typeof module !== "undefined") module.exports = Diff;
