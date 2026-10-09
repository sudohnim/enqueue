// The name matcher (static/js/suggest.js) under node: what a few typed characters
// find, in what order, and what they must not find.
const path = require("path");
const { rank } = require(path.join(__dirname, "../../src/enqueue/static/js/suggest.js"));

const LIBRARY = [
  "Mesopotamia",
  "The Good Life",
  "yardsticks to measure a good life",
  "Workout",
  "Die With Zero",
  "The Psychology of Money",
  "getting rich vs staying rich",
  "33 Strategies of War",
  "Café notes",
  "to do",
  "Party of the People",
].map((title, i) => ({ id: "a" + i, title, kind: "note" }));

const titles = (q, n) => rank(q, LIBRARY, n).map((r) => r.item.title);
let failed = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) {
    failed++;
    console.log("FAIL " + name + "\n  want: " + JSON.stringify(want) + "\n  got:  " + JSON.stringify(got));
  }
}

check("a name typed whole", titles("mesopotamia"), ["Mesopotamia"]);
check("a name half typed", titles("mesop"), ["Mesopotamia"]);
check("two letters swapped", titles("mesopotamai"), ["Mesopotamia"]);
check("a letter missing", titles("mesoptamia"), ["Mesopotamia"]);
check("a slip in a word still being typed", titles("mesopatam"), ["Mesopotamia"]);
check("the exact title, and not one missing a typed word", titles("the good life"), [
  "The Good Life",
]);
check("the exact title leads a longer one", titles("good life"), [
  "The Good Life",
  "yardsticks to measure a good life",
]);
check("words in the middle of a title", titles("good li"), [
  "The Good Life",
  "yardsticks to measure a good life",
]);
check("the inside of a word", titles("potam"), ["Mesopotamia"]);
check("accents do not matter", titles("cafe"), ["Café notes"]);
check("letters run together", titles("goodlife"), [
  "The Good Life",
  "yardsticks to measure a good life",
]);
check("numbers", titles("33 strat"), ["33 Strategies of War"]);
check("one character finds nothing", titles("m"), []);
check("a short word is not slipped", titles("ti"), []);
check("nonsense finds nothing", titles("zzqqxx"), []);
check("one slip is allowed in a six-letter word", titles("monkey"), ["The Psychology of Money"]);
check("a different word is not a slip", titles("donkey"), []);
check("the limit holds", titles("the", 2).length, 2);

const top = rank("good life", LIBRARY)[0];
check("a confident match scores as one", top.score >= 80, true);
check("the typed words are marked where they begin", top.marks, [
  [4, 8],
  [9, 13],
]);
check("a slip is not confident", rank("mesopotamai", LIBRARY)[0].score < 80, true);
check("a slip marks nothing", rank("mesopotamai", LIBRARY)[0].marks, []);

console.log(failed ? failed + " name-matching cases failed" : "name matching holds");
process.exit(failed ? 1 : 0);
