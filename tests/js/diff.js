// What changed between two versions of a note (static/js/diff.js): the marks land on
// the words that changed, never on a line's markdown, and the note keeps its shape.
const assert = require("assert");
const path = require("path");
const fs = require("fs");

global.esc = (s) =>
  String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
// md.js is browser code with no module export: load it the way the page does.
eval(fs.readFileSync(path.join(__dirname, "../../src/enqueue/static/js/md.js"), "utf8"));
const Diff = require(path.join(__dirname, "../../src/enqueue/static/js/diff.js"));
const show = (a, b) =>
  Diff.markdown(a, b)
    .replaceAll(Diff.INS, "{+")
    .replaceAll(Diff.INS_END, "+}")
    .replaceAll(Diff.DEL, "[-")
    .replaceAll(Diff.DEL_END, "-]");

// A word changed inside a list item: one struck, one new, the bullet untouched.
assert.strictEqual(
  show("- hotels\n  - book on amex for points", "- hotels\n  - book on chase for points"),
  "- hotels\n  - book on [-amex-]{+chase+} for points",
);
// A line added, a line removed.
assert.strictEqual(show("a\nb\nc", "a\nc\nd"), "a\n[-b-]\nc\n{+d+}");
// A heading's hashes and a quote's mark stay outside the marks.
assert.strictEqual(show("## Old title", "## New title"), "## [-Old-]{+New+} title");
assert.strictEqual(show("> keep this", "> keep that"), "> keep [-this-]{+that+}");
// A numbered item that changed keeps its number.
assert.strictEqual(show("1. first\n2. second", "1. first\n2. later"), "1. first\n2. [-second-]{+later+}");
// Code fences are never wrapped; a line inside one is.
assert.strictEqual(show("```\nx = 1\n```", "```\nx = 2\n```"), "```\nx = [-1-]{+2+}\n```");
// Blank lines carry no mark.
assert.strictEqual(show("a", "a\n\nb"), "a\n\n{+b+}");
// Nothing changed, nothing marked.
assert.strictEqual(show("same\n- list", "same\n- list"), "same\n- list");
// Lines too different to be one edited line are a removal and an addition.
assert.strictEqual(show("totally old words", "brand new sentence here"), "[-totally old words-]\n{+brand new sentence here+}");

// A new sub-item before an item that was edited: the edit is found past it.
assert.strictEqual(
  show("- hotels\n- neighborhoods", "- hotels\n  - DO NOT\n- neighborhoods - use prompt"),
  "- hotels\n  - {+DO NOT+}\n- neighborhoods{+ - use prompt+}",
);

// Rendered: the note's own structure, with <ins>/<del> inside it.
const html = Diff.html("- book on amex\n- DO NOT", "- book on chase\n- DO NOT\n- Antigua", md);
assert.ok(html.includes("<li>book on <del>amex</del><ins>chase</ins></li>"), html);
assert.ok(html.includes("<li><ins>Antigua</ins></li>"), html);
assert.ok(!/[-]/.test(html), "no stand-in character survives");
// Text in the note is still escaped.
assert.ok(Diff.html("a", "a <b>", md).includes("&lt;b&gt;"));

// A big note still compares, without the full table.
const big = Array.from({ length: 3000 }, (_, i) => "line " + i).join("\n");
assert.ok(show(big, big.replace("line 1500", "line changed")).includes("[-1500-]{+changed+}"));
assert.ok(Diff.same("a  \n", "a"));
console.log("diff ok");
