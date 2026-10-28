// The guides behind the ? marks: every one is whole, links only to guides that exist,
// and the in-page matcher finds the right one for the ways people ask.
const assert = require("assert");
const path = require("path");
const Guides = require(path.join(__dirname, "../../src/enqueue/static/js/guides.js"));

const TABS = new Set(["ai", "features", "storage", "trash", "sync", "events", "phone"]);
for (const g of Guides.LIST) {
  for (const field of ["id", "tab", "title", "voice", "what", "need", "words"])
    assert.ok(g[field] && typeof g[field] === "string", g.id + " lacks " + field);
  assert.ok(TABS.has(g.tab), g.id + " names a tab that does not exist");
  assert.ok(g.steps.length >= 1 && g.steps.length <= 5, g.id + ": one to five steps");
  assert.ok(g.know.length >= 1, g.id + " has nothing under good to know");
  for (const other of g.also) assert.ok(Guides.get(other), g.id + " goes with a missing guide: " + other);
  const all = [g.title, g.voice, g.what, g.need, ...g.steps, ...g.know].join(" ");
  assert.ok(!all.includes("—"), g.id + " uses an em dash");
  assert.ok(!/vault/i.test(all), g.id + " names the vault, whose door is unmarked");
}
assert.strictEqual(new Set(Guides.LIST.map((g) => g.id)).size, Guides.LIST.length, "ids are unique");

// What people type, and the guide it must put first.
const ASKS = [
  ["relay", "relay"],
  ["what is the relay", "relay"],
  ["how do i get this on my phone", "link-phone"],
  ["scan qr code", "link-phone"],
  ["if my mac dies do i lose everything", "backups"],
  ["back up", "backups"],
  ["proton drive", "backups"],
  ["restore a backup on a new mac", "backups"],
  ["api key", "api-key"],
  ["where is my key stored", "api-key"],
  ["which model should i use", "models"],
  ["images are not described", "models"],
  ["does my data leave this machine", "answers"],
  ["included assistant", "answers"],
  ["rebuild concepts", "concepts"],
  ["summaries are old", "concepts"],
  ["search is missing things", "index"],
  ["rebuild index", "index"],
  ["change the capture shortcut", "hotkey"],
  ["link previews", "link-previews"],
  ["medium links have no title", "link-previews"],
  ["i deleted a note by accident", "trash"],
  ["how long does trash keep things", "trash"],
  ["i lost my recovery phrase", "recovery-phrase"],
  ["second computer", "pair-computer"],
  ["reset sync", "reset-sync"],
  ["why did my question fail", "activity"],
  ["make search better", "search-options"],
];
for (const [typed, want] of ASKS) {
  const got = Guides.match(typed, { platform: "desktop" });
  assert.ok(got.length, '"' + typed + '" matched nothing');
  assert.strictEqual(got[0].guide.id, want, '"' + typed + '" put ' + got[0].guide.id + " first");
}

// Each app is offered its own guides only.
assert.ok(Guides.all("phone").length >= 4 && Guides.all("phone").every((g) => g.tab === "phone"));
assert.ok(Guides.all("desktop").every((g) => g.tab !== "phone"));
assert.strictEqual(Guides.match("trash", { platform: "phone" })[0].guide.id, "phone-trash");
assert.strictEqual(Guides.match("trash", { platform: "desktop" })[0].guide.id, "trash");
assert.strictEqual(Guides.match("fingerprint", { platform: "phone" })[0].guide.id, "app-lock");
for (const g of Guides.LIST)
  for (const other of g.also)
    assert.deepStrictEqual(Guides.get(other).on, g.on, g.id + " goes with a guide from the other app");
assert.ok(Guides.html(Guides.get("relay"), { level: "todo", text: "Needs <a> relay" }).includes("Needs &lt;a&gt; relay"));
assert.ok(Guides.mark("relay", true).includes('aria-expanded="true"'));

// A name typed outright is sure; a vague question is offered, not assumed.
assert.ok(Guides.sure(Guides.match("relay")), "a guide's own name is a sure match");
assert.ok(Guides.sure(Guides.match("api key")));
assert.ok(!Guides.sure(Guides.match("is it safe")), "a vague question is not a sure match");
assert.deepStrictEqual(Guides.match("the of and"), [], "filler alone matches nothing");
assert.deepStrictEqual(Guides.match(""), []);

// Where an installation stands: an alert about the guide wins over its step.
const setup = {
  steps: [
    { id: "backup", state: "todo", detail: "No folder chosen" },
    { id: "phone", state: "done", detail: "Link a phone whenever you like" },
  ],
  alerts: [{ guide: "relay", level: "warn", text: "The relay is on this Mac." }],
};
assert.deepStrictEqual(Guides.stand("backups", setup), { level: "todo", text: "No folder chosen" });
assert.deepStrictEqual(Guides.stand("relay", setup), { level: "warn", text: "The relay is on this Mac." });
assert.strictEqual(Guides.stand("link-phone", setup).level, "done");
assert.strictEqual(Guides.stand("hotkey", setup), null);
assert.strictEqual(Guides.stand("backups", null), null);

assert.ok(Guides.text(Guides.get("relay")).includes("Steps: 1."));
console.log("guides ok: " + Guides.LIST.length + " guides, " + ASKS.length + " asks");
