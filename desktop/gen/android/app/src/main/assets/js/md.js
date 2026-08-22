  // Self-contained markdown. A CDN would make the app reach the network to render
  // something you wrote, which is the opposite of the promise. Escapes before parsing,
  // so no input path can render raw HTML.
  function md(src) {
    let t = esc(src);
    const held = [];
    t = t.replace(
      /```([\s\S]*?)```/g,
      (m, code) =>
        "\x00" +
        (held.push(
          // Only the newline right after the opening fence is decorative and is
          // dropped; the first real line is kept as typed. The serializer writes
          // bare fences, so a lang tag the editor typed (or one in hand-written
          // markdown) is content, not metadata - stripping it would destroy text
          // on the save/reopen round trip.
          "<pre><code>" + code.replace(/^\n/, "") + "</code></pre>",
        ) -
          1) +
        "\x00",
    );
    t = t.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    t = t.replace(
      /\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>',
    );
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    t = t.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");

    const out = [];
    const items = [];
    const flushList = () => {
      if (!items.length) return;
      // Build the list tree from indented items, then render it. Two spaces of
      // indentation is one level, matching what the editor's indent command and the
      // markdown serializer produce, so a nested list round-trips unchanged.
      const root = { lists: [] };
      const stack = [];
      for (const it of items) {
        while (stack.length && stack[stack.length - 1].depth > it.depth)
          stack.pop();
        let top = stack[stack.length - 1];
        if (top && top.depth === it.depth && top.tag !== it.tag) {
          stack.pop();
          top = stack[stack.length - 1];
        }
        let list =
          top && top.depth === it.depth && top.tag === it.tag ? top : null;
        if (!list) {
          list = { tag: it.tag, depth: it.depth, items: [] };
          // A jumped indentation (more than one level at once) has no item to hang
          // the new list under, so it degrades to nesting under the nearest shallower
          // item rather than dropping content or crashing.
          const parent =
            top && top.depth < it.depth
              ? top.items[top.items.length - 1]
              : null;
          const owner = parent ? (parent.lists ||= []) : root.lists;
          owner.push(list);
          stack.push(list);
        }
        const item = { content: it.content };
        list.items.push(item);
      }
      const renderList = (list) => {
        let h = "<" + list.tag + ">";
        for (const it of list.items) {
          h += "<li>" + it.content;
          if (it.lists) for (const sub of it.lists) h += renderList(sub);
          h += "</li>";
        }
        return h + "</" + list.tag + ">";
      };
      for (const list of root.lists) out.push(renderList(list));
      items.length = 0;
    };
    for (const raw of t.split("\n")) {
      const line = raw.trimEnd();
      const h = line.match(/^(#{1,3})\s+(.*)$/);
      const li = line.match(/^(\s*)([-*+])\s+(.*)$/);
      const ol = line.match(/^(\s*)(\d+)\.\s+(.*)$/);
      const bq = line.match(/^(?:&gt;|>)\s?(.*)$/);
      if (h) {
        flushList();
        out.push("<h" + h[1].length + ">" + h[2] + "</h" + h[1].length + ">");
      } else if (li || ol) {
        items.push({
          depth: Math.min(Math.floor((li || ol)[1].length / 2), 8),
          tag: li ? "ul" : "ol",
          content: (li || ol)[3],
        });
      } else if (bq) {
        flushList();
        out.push("<blockquote>" + bq[1] + "</blockquote>");
      } else if (/^\ufffd\d+\ufffd$/.test(line)) {
        // A code-fence placeholder is the block itself, not prose: wrapping it in a
        // <p> would make the browser split the paragraph around the <pre>, leaving
        // stray empty paragraphs above and below the block. The placeholder bytes
        // reach the browser as U+FFFD: the raw NULs in this file are not valid
        // UTF-8, and both sides of the round trip are corrupted identically.
        flushList();
        out.push(held[+line.slice(1, -1)]);
      } else if (!line.trim()) flushList();
      else {
        flushList();
        out.push("<p>" + line + "</p>");
      }
    }
    flushList();
    return out.join("").replace(/\x00(\d+)\x00/g, (m, i) => held[+i]);
  }

  // The wall preview must be a plain, clamped snippet. Rendered markdown brings
  // block children - headings, nested lists - into a line-clamped box, where they
  // paint over each other instead of clamping with an ellipsis. Strip the syntax
  // first so the box only ever holds a text run, which clamps cleanly.
  function mdText(src) {
    let t = src;
    t = t.replace(/```[\s\S]*?```/g, " ");
    t = t.replace(/`([^`\n]+)`/g, "$1");
    t = t.replace(/\[([^\]]+)\]\((?:https?:[^)\s]+|[^)]*)\)/g, "$1");
    t = t.replace(/\*\*([^*]+)\*\*/g, "$1");
    t = t.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1$2");
    t = t.replace(/^\s{0,3}#{1,6}\s+/gm, "");
    // List markers become a leading interpunct (N.5): the item stays a bullet,
    // just without the markdown syntax, and the newline survives so a bulleted
    // note reads as bullets, not a run-on phrase.
    t = t.replace(/^\s{0,3}(?:[-*+]|\d+[.)])\s+/gm, "• ");
    t = t.replace(/^\s{0,3}>\s?/gm, "");
    // Collapse runs of spaces and tabs inside a line, but keep newlines - they
    // carry the list and paragraph structure the preview needs.
    t = t.replace(/[^\S\n]+/g, " ");
    // A paragraph break is at most one blank line.
    t = t.replace(/\n{3,}/g, "\n\n");
    return t.trim();
  }

  // Turn the edited document back into markdown. Only the tags md() can produce need
  // handling, which is what keeps this tractable: the editor and the parser are two
  // halves of one contract rather than a general HTML converter.
  function htmlToMd(root) {
    const inline = (node) => {
      if (node.nodeType === 3) return node.nodeValue;
      if (node.nodeType !== 1) return "";
      const kids = [...node.childNodes].map(inline).join("");
      switch (node.tagName) {
        case "BR":
          return "\n";
        case "STRONG":
        case "B":
          return kids.trim() ? "**" + kids + "**" : "";
        case "EM":
        case "I":
          return kids.trim() ? "*" + kids + "*" : "";
        case "CODE":
          return "`" + kids + "`";
        case "A":
          return "[" + kids + "](" + (node.getAttribute("href") || "") + ")";
        default:
          return kids;
      }
    };

    // Lists are written indented, two spaces per level, so a nested list survives
    // the round trip. An item's sub-lists sit inside its <li> (or directly under the
    // list, which some engines produce) and are serialised one level deeper.
    const listToMd = (node, depth) => {
      const pad = "  ".repeat(depth);
      const ordered = node.tagName === "OL";
      let n = 1;
      const out = [];
      for (const child of node.childNodes) {
        if (child.nodeType !== 1) continue;
        if (child.tagName === "UL" || child.tagName === "OL") {
          out.push(...listToMd(child, depth + 1));
          continue;
        }
        if (child.tagName !== "LI") continue;
        const parts = [];
        const nested = [];
        for (const cc of child.childNodes) {
          if (cc.nodeType === 1 && (cc.tagName === "UL" || cc.tagName === "OL"))
            nested.push(cc);
          else parts.push(cc);
        }
        const text = parts
          .map(inline)
          .join("")
          .replace(/\u00a0/g, " ")
          .trim();
        out.push(pad + (ordered ? n++ + ". " : "- ") + text);
        for (const sub of nested) out.push(...listToMd(sub, depth + 1));
      }
      return out;
    };

    const lines = [];
    for (const node of root.childNodes) {
      if (node.nodeType === 3) {
        const t = node.nodeValue.trim();
        if (t) lines.push(t, "");
        continue;
      }
      if (node.nodeType !== 1) continue;

      switch (node.tagName) {
        case "H1":
          lines.push("# " + inline(node).trim(), "");
          break;
        case "H2":
          lines.push("## " + inline(node).trim(), "");
          break;
        case "H3":
          lines.push("### " + inline(node).trim(), "");
          break;
        case "UL":
        case "OL": {
          lines.push(...listToMd(node, 0));
          lines.push("");
          break;
        }
        case "BLOCKQUOTE":
          lines.push("> " + inline(node).trim(), "");
          break;
        case "PRE": {
          // The <pre> may wrap its text in the <code> md() produces, and a line
          // break may be a literal newline or a <br> from editing. Walk the raw
          // text so both come out as real newlines; textContent would drop <br>s.
          // The zero-width marker after an Enter-made newline is dropped too.
          let code = "";
          const walk = (n) => {
            if (n.nodeType === 3) code += n.nodeValue.replace(/\u200b/g, "");
            else if (n.nodeType === 1) {
              if (n.tagName === "BR") code += "\n";
              else for (const c of n.childNodes) walk(c);
            }
          };
          walk(node);
          lines.push("```", code.replace(/\n$/, ""), "```", "");
          break;
        }
        case "DIV":
        case "P": {
          const t = inline(node)
            .replace(/\u200b/g, "")
            .replace(/\u00a0/g, " ")
            .trimEnd();
          lines.push(t.trim() ? t : "", t.trim() ? "" : null);
          break;
        }
        default: {
          const t = inline(node).trim();
          if (t) lines.push(t, "");
        }
      }
    }
    return lines
      .filter((l) => l !== null)
      .join("\n")
      .replace(/\n{3,}/g, "\n\n")
      .replace(/^\n+|\n+$/g, "");
  }

  // A note's title is its first markdown heading, else the first non-empty line,
  // else Untitled - a character-for-character mirror of notes.py:title_from_body
  // (same heading regex, same * _ ` stripping, same 120-char cap), so the live
  // header the user types against equals exactly what the server will store.
  function titleFromBody(body) {
    var lines = body.split(/\r?\n/);
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim();
      if (!line) continue;
      var m = line.match(/^#{1,6}\s+(.*)$/);
      var text = (m ? m[1] : line).trim().replace(/[*_`]/g, "").trim();
      if (text) return text.slice(0, 120);
    }
    return "Untitled";
  }

