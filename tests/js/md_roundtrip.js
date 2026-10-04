// Markdown round trip: md() renders a note, htmlToMd() writes the editor back, and the
// two must agree - a note opened and saved without edits comes back byte for byte.
// Every mismatch here is a note that changes shape on its own (an empty bullet
// splitting a list, blank lines appearing between lines typed on the phone, a
// numbered list renumbering from 1).
//
// md.js runs in the browser and htmlToMd() walks DOM nodes, so this loads md.js as a
// plain script and parses md()'s output with a tiny DOM that covers exactly the tags
// md() can produce. Run by tests/test_md_roundtrip.py; exits non-zero on a failure.
"use strict";

const fs = require("fs");
const path = require("path");

const esc = (s) =>
  (s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

const src = fs.readFileSync(path.join(__dirname, "../../src/enqueue/static/js/md.js"), "utf8");
const { md, htmlToMd } = new Function("esc", src + "\nreturn { md, htmlToMd };")(esc);

// ---- a DOM just big enough for md()'s output ----------------------------------
const VOID = new Set(["BR", "IMG"]);
const decode = (s) =>
  s
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&");

function element(tagName, attrs) {
  const el = {
    nodeType: 1,
    tagName,
    attrs,
    childNodes: [],
    parent: null,
    getAttribute: (k) => (k in attrs ? attrs[k] : null),
    hasAttribute: (k) => k in attrs,
    get nextElementSibling() {
      if (!el.parent) return null;
      const sibs = el.parent.childNodes;
      for (let i = sibs.indexOf(el) + 1; i < sibs.length; i++)
        if (sibs[i].nodeType === 1) return sibs[i];
      return null;
    },
  };
  return el;
}

function parse(html) {
  const root = element("DIV", {});
  const stack = [root];
  const re = /<(\/?)([a-zA-Z0-9]+)((?:\s+[a-zA-Z-]+(?:="[^"]*")?)*)\s*\/?>|([^<]+)/g;
  let m;
  while ((m = re.exec(html))) {
    const top = stack[stack.length - 1];
    if (m[4] !== undefined) {
      top.childNodes.push({ nodeType: 3, nodeValue: decode(m[4]), parent: top });
      continue;
    }
    const tag = m[2].toUpperCase();
    if (m[1]) {
      while (stack.length > 1 && stack.pop().tagName !== tag);
      continue;
    }
    const attrs = {};
    for (const a of m[3].matchAll(/([a-zA-Z-]+)(?:="([^"]*)")?/g)) attrs[a[1]] = decode(a[2] ?? "");
    const el = element(tag, attrs);
    el.parent = top;
    top.childNodes.push(el);
    if (!VOID.has(tag)) stack.push(el);
  }
  return root;
}

const roundTrip = (text) => htmlToMd(parse(md(text)));

// ---- cases: each must come back exactly as written ----------------------------
const exact = {
  "nested bullets": "- a\n  - b\n    - c\n- d",
  "a trip plan": "- 24 - Th\n  - depart EWR at 11\n- 25 - Fr\n  - arrive 11am\n  - find drag show?",
  "an empty nested bullet": "- a\n  -\n- b",
  "an empty top-level bullet": "- a\n-\n- b",
  "numbered with a sub-list": "1. one\n2. two\n  - sub\n3. three",
  "numbered from five": "5. five\n6. six",
  "bullets under numbers": "- a\n  1. x\n  2. y\n- b",
  "lines typed one under another": "line one\nline two\nline three",
  "a mix of tight and spaced lines": "a\nb\n\nc\nd",
  "a list right under a line": "para\n- a\n- b",
  "a heading right over a list": "## Title\n- a\n- b",
  "a paragraph after a list": "- a\n- b\n\npara",
  headings: "# H1\n\n## H2\n\ntext",
  "a code block": "```\ncode  line\n  indented\n```",
  "a two-line quote": "> quoted\n> more",
  "a quote then a line": "> q\ntext",
  "inline marks": "**bold** and *it* and `code`",
  "marks inside bullets": "- **b** text\n  - *i* text",
  links: "see [x](https://a.com) and https://b.com",
  "escaped markers": "a \\* not list\n\\- not list",
  "a dash in text": "24 - Th\n- 25 - Fr",
  checkboxes: "- [ ] todo\n- [x] done",
  "raw html is text": "<b>hi</b> & <script>",
  "a lone dash": "-",
  "a negative number": "-5 degrees",
};

// ---- cases that normalise, once, to a stable form ------------------------------
const normalised = {
  "a tab-indented bullet keeps its nesting": ["- a\n\t- b", "- a\n  - b"],
  "star and plus bullets": ["* a\n+ b", "- a\n- b"],
};

let failed = 0;
const fail = (name, want, got) => {
  failed++;
  console.log(`FAIL ${name}\n  want: ${JSON.stringify(want)}\n  got:  ${JSON.stringify(got)}`);
};
for (const [name, text] of Object.entries(exact)) {
  const once = roundTrip(text);
  if (once !== text) fail(name, text, once);
  else if (roundTrip(once) !== once) fail(name + " (second trip)", once, roundTrip(once));
}
for (const [name, [text, want]] of Object.entries(normalised)) {
  const once = roundTrip(text);
  if (once !== want) fail(name, want, once);
  else if (roundTrip(once) !== once) fail(name + " (second trip)", once, roundTrip(once));
}
const total = Object.keys(exact).length + Object.keys(normalised).length;
console.log(`${total - failed}/${total} markdown round trips hold`);
process.exit(failed ? 1 : 0);
