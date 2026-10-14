// Tabs inside a note: how they are kept in the note's markdown. Pure; shared by the
// desktop and the phone, like md.js and diff.js.
//
// A tab starts at a marker line of its own:
//
//     <!-- tab: Prompt -->
//
// an HTML comment, so any other markdown app shows nothing for it and an exported note
// still reads. Whatever comes before the first marker (the note's title heading) is the
// note's preamble, shared by every tab. A note with no marker has no tabs, which is
// every note until someone adds one.
//
// Tabs.parse(body)          {pre, tabs: [{name, text}]}, or null for a note without tabs
// Tabs.join(pre, tabs)      the body again; one tab left means no tabs at all
// Tabs.start(body)          a plain note turned into its first tab
// Tabs.clean(name)          a name that cannot break the marker
const Tabs = (() => {
  const MARKER = /^<!--\s*tab:\s*(.*?)\s*-->\s*$/;

  function clean(name) {
    const out = String(name || "")
      .replace(/-->/g, "")
      .replace(/[\r\n]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    return out.slice(0, 60) || "Untitled";
  }

  function trimBlank(lines) {
    let a = 0;
    let b = lines.length;
    while (a < b && !lines[a].trim()) a++;
    while (b > a && !lines[b - 1].trim()) b--;
    return lines.slice(a, b).join("\n");
  }

  function parse(body) {
    const lines = String(body || "").split("\n");
    const at = [];
    // A marker inside a code fence is code, not a tab.
    let fence = false;
    lines.forEach((line, i) => {
      if (/^\s*(```|~~~)/.test(line)) fence = !fence;
      else if (!fence && MARKER.test(line)) at.push(i);
    });
    if (!at.length) return null;
    const tabs = at.map((start, k) => ({
      name: clean(lines[start].match(MARKER)[1]),
      text: trimBlank(lines.slice(start + 1, k + 1 < at.length ? at[k + 1] : lines.length)),
    }));
    return { pre: trimBlank(lines.slice(0, at[0])), tabs };
  }

  function join(pre, tabs) {
    const list = tabs || [];
    // One tab is no tabs: the note goes back to plain text.
    if (list.length <= 1) {
      return [pre, list[0] ? list[0].text : ""].map((s) => (s || "").trim()).filter(Boolean).join("\n\n");
    }
    const parts = [];
    if ((pre || "").trim()) parts.push(pre.trim());
    for (const t of list) {
      const text = (t.text || "").trim();
      parts.push("<!-- tab: " + clean(t.name) + " -->" + (text ? "\n\n" + text : ""));
    }
    return parts.join("\n\n");
  }

  // A plain note's first tab: its title heading stays above the tabs, as the preamble;
  // everything else becomes the tab.
  function start(body, name) {
    const lines = String(body || "").split("\n");
    let i = 0;
    while (i < lines.length && !lines[i].trim()) i++;
    const heading = i < lines.length && /^#\s+\S/.test(lines[i]);
    return {
      pre: heading ? lines[i].trim() : "",
      tabs: [{ name: clean(name || "Notes"), text: trimBlank(lines.slice(heading ? i + 1 : 0)) }],
    };
  }

  return { parse, join, start, clean, MARKER };
})();

if (typeof module !== "undefined") module.exports = Tabs;
