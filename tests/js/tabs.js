// Tabs inside a note (static/js/tabs.js): kept as marker lines in the note's markdown,
// read back exactly, and a note with one tab is a plain note again.
const assert = require("assert");
const path = require("path");
const Tabs = require(path.join(__dirname, "../../src/enqueue/static/js/tabs.js"));

const body = "# Travel process\n\n<!-- tab: Steps -->\n\n- book hotels\n\n<!-- tab: Prompt -->\n\nGOAL: rest\n\n```\n<!-- tab: not a tab -->\n```";
const t = Tabs.parse(body);
assert.strictEqual(t.pre, "# Travel process");
assert.deepStrictEqual(t.tabs.map((x) => x.name), ["Steps", "Prompt"], "a marker inside a code block is code");
assert.strictEqual(t.tabs[1].text, "GOAL: rest\n\n```\n<!-- tab: not a tab -->\n```");
assert.strictEqual(Tabs.join(t.pre, t.tabs), body, "parse then join gives the note back");

assert.strictEqual(Tabs.parse("# Plain\n\nno tabs here"), null);
assert.strictEqual(Tabs.parse(""), null);

// One tab is no tabs.
assert.strictEqual(Tabs.join("# T", [{ name: "Only", text: "words" }]), "# T\n\nwords");
assert.strictEqual(Tabs.join("", []), "");

// Starting tabs keeps the title above them.
assert.deepStrictEqual(Tabs.start("\n# Trip\n\n- a\n- b"), {
  pre: "# Trip",
  tabs: [{ name: "Notes", text: "- a\n- b" }],
});
assert.deepStrictEqual(Tabs.start("just words"), { pre: "", tabs: [{ name: "Notes", text: "just words" }] });

// A name cannot break its marker, or the line.
assert.strictEqual(Tabs.clean("evil --> name\nsecond"), "evil name second");
assert.strictEqual(Tabs.clean("   "), "Untitled");
const tricky = Tabs.join("", [{ name: "a --> b", text: "x" }, { name: "c", text: "" }]);
assert.deepStrictEqual(Tabs.parse(tricky).tabs.map((x) => x.name), ["a b", "c"]);
// An empty tab keeps its place.
assert.strictEqual(Tabs.parse(tricky).tabs[1].text, "");
console.log("tabs ok");
