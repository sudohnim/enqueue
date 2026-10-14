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

// A search hit opens on the tab it came from.
const trip = Tabs.parse(
  "# Trip\n\n<!-- tab: Steps -->\n\n- book the hotel in Lisbon early\n\n<!-- tab: Prompt -->\n\nYou are a careful travel agent who plans slow trips",
);
assert.strictEqual(Tabs.find(trip, "anything", "<!-- tab: Prompt -->\n\nYou are a careful"), 1, "a marker names the tab");
assert.strictEqual(Tabs.find(trip, "agent", "You are a careful travel agent who"), 1, "the snippet's words");
assert.strictEqual(Tabs.find(trip, "lisbon hotel", "# Trip"), 0, "the query's words");
assert.strictEqual(Tabs.find(trip, "zebra", "# Trip"), -1, "cannot tell");
assert.strictEqual(Tabs.find(null, "x", "y"), -1);
assert.strictEqual(Tabs.find(trip, "x", "- a <!-- tab: Prompt --> You are"), 1, "a folded snippet's marker");
assert.strictEqual(Tabs.plain("<!-- tab: Prompt --> You are"), "Prompt \u00b7 You are");
console.log("tabs ok");
