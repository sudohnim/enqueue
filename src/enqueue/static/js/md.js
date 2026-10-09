  // Bare URLs become links. The split on tags keeps this out of anything md() has
  // already turned into markup: the body of an existing <a> (a markdown link), inline
  // <code>, and every attribute value (an image src, an href). Input was escaped before
  // any of this runs, so a URL cannot carry a raw quote or angle bracket out of the
  // href, and only http(s) is matched - never javascript: or a relative path.
  function autolink(html) {
    const count = (s, ch) => s.split(ch).length - 1;
    let inA = 0;
    let inCode = 0;
    return html
      .split(/(<[^>]+>)/)
      .map((part) => {
        if (part.charAt(0) === "<") {
          if (/^<a[\s>]/i.test(part)) inA++;
          else if (/^<\/a>/i.test(part)) inA = Math.max(0, inA - 1);
          else if (/^<code[\s>]/i.test(part)) inCode++;
          else if (/^<\/code>/i.test(part)) inCode = Math.max(0, inCode - 1);
          return part;
        }
        if (inA || inCode) return part;
        return part.replace(/\bhttps?:\/\/[^\s<]+/g, (raw) => {
          // Punctuation after a URL belongs to the sentence ("see https://x.com."),
          // and so do escaped quotes/brackets. A closing paren stays only when the
          // URL opened one itself, so a wiki link like .../Foo_(bar) keeps its ")".
          let url = raw;
          let tail = "";
          for (;;) {
            const m = url.match(/(?:[.,;:!?\]'"]|&(?:quot|#39|gt|lt);)$/);
            const cut = m
              ? m[0]
              : url.endsWith(")") && count(url, "(") < count(url, ")")
                ? ")"
                : "";
            if (!cut) break;
            tail = cut + tail;
            url = url.slice(0, -cut.length);
          }
          if (!/^https?:\/\/[^/?#\s]/.test(url)) return raw; // only a scheme was left
          return (
            '<a class="mdlink" href="' +
            url +
            '" target="_blank" rel="noopener">' +
            url +
            "</a>" +
            tail
          );
        });
      })
      .join("");
  }

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
    // Images come before links: `![alt](src)` contains a `[...](...)`, so the link
    // rule would eat it otherwise. Only same-origin blob paths (/artifacts/{id}/blob,
    // what the paste handler writes) and data: images are allowed as a src - never an
    // arbitrary URL - so a note can never be made to fetch from or point a src at the
    // network. The alt text is already escaped by esc() above.
    t = t.replace(
      /!\[([^\]]*)\]\((\/[^)\s]+|data:image\/[^)\s]+)\)/g,
      '<img src="$2" alt="$1" loading="lazy" />',
    );
    t = t.replace(
      /\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
      '<a class="mdlink" href="$2" target="_blank" rel="noopener">$1</a>',
    );
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    t = t.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    t = autolink(t);

    const out = [];
    const items = [];
    // Whether the line before the current one was blank. A block that follows the
    // previous one with NO blank line between them is marked data-tight, so the
    // serializer writes it back the same way: lines typed one under another (the
    // phone's plain-text editor) used to come back from a desktop save with a blank
    // line wedged between every pair, and the note grew gaps on each round trip.
    let prevBlank = true;
    const tight = () => (!prevBlank && out.length ? " data-tight" : "");
    let listTight = "";
    const quote = [];
    let quoteTight = "";
    const flushQuote = () => {
      if (!quote.length) return;
      // Consecutive quoted lines are ONE quote, its lines kept as line breaks.
      out.push("<blockquote" + quoteTight + ">" + quote.join("<br>") + "</blockquote>");
      quote.length = 0;
    };
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
        if (list.items.length === 1 && it.number && it.number !== 1) list.start = it.number;
      }
      const renderList = (list, top) => {
        let h =
          "<" +
          list.tag +
          (list.start ? ' start="' + list.start + '"' : "") +
          (top ? listTight : "") +
          ">";
        for (const it of list.items) {
          // An empty item is still an item (a bullet you have not filled in yet); the
          // <br> gives the editor a line to put the caret on.
          h += "<li>" + (it.content || "<br>");
          if (it.lists) for (const sub of it.lists) h += renderList(sub);
          h += "</li>";
        }
        return h + "</" + list.tag + ">";
      };
      root.lists.forEach((list, i) => out.push(renderList(list, i === 0)));
      items.length = 0;
    };
    for (const raw of t.split("\n")) {
      // A leading tab is one level, the same as two spaces (what the serializer and
      // the phone's indent tool write), so a tab-indented item keeps its nesting.
      const line = raw.trimEnd().replace(/^[ \t]+/, (lead) => lead.replace(/\t/g, "  "));
      const h = line.match(/^(#{1,3})\s+(.*)$/);
      // The content is optional: "- " (trimmed to "-") is an empty item, not text.
      const li = line.match(/^(\s*)([-*+])(?:\s+(.*))?$/);
      const ol = line.match(/^(\s*)(\d+)\.(?:\s+(.*))?$/);
      const bq = line.match(/^(?:&gt;|>)\s?(.*)$/);
      if (!bq) flushQuote();
      // A line of three or more dashes is a divider. It used to show as the dashes
      // themselves. The count is kept so the note is written back as it was typed.
      const rule = line.match(/^-{3,}$/);
      if (rule) {
        flushList();
        out.push('<hr data-dashes="' + line.length + '"' + tight() + ">");
      } else if (h) {
        flushList();
        out.push("<h" + h[1].length + tight() + ">" + h[2] + "</h" + h[1].length + ">");
      } else if (li || ol) {
        if (!items.length) listTight = tight();
        items.push({
          depth: Math.min(Math.floor((li || ol)[1].length / 2), 8),
          tag: li ? "ul" : "ol",
          content: (li || ol)[3] || "",
          number: ol ? parseInt(ol[2], 10) : 0,
        });
      } else if (bq) {
        flushList();
        if (!quote.length) quoteTight = tight();
        quote.push(bq[1]);
      } else if (/^\x00\d+\x00$/.test(line.trim())) {
        // A code-fence placeholder is the block itself, not prose: wrapping it in a
        // <p> would make the browser split the paragraph around the <pre>, leaving
        // stray empty paragraphs above and below the block. The placeholder is the
        // NUL-delimited index written above ("\x00" escapes, real U+0000 at run
        // time). This test used to look for U+FFFD instead, never matched, and every
        // code block was wrapped in a <p> that the browser's parser then split.
        flushList();
        const fence = held[+line.trim().slice(1, -1)];
        out.push(fence.replace("<pre>", "<pre" + tight() + ">"));
      } else if (!line.trim()) flushList();
      else {
        flushList();
        out.push("<p" + tight() + ">" + line + "</p>");
      }
      prevBlank = !line.trim();
    }
    flushList();
    flushQuote();
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
    // An embedded image reduces to its alt text (usually empty) in a text preview -
    // stripped before the link rule so its leading "!" never leaks into the snippet.
    t = t.replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1");
    t = t.replace(/\[([^\]]+)\]\((?:https?:[^)\s]+|[^)]*)\)/g, "$1");
    // A bare URL is plumbing, not content. Pasted links arrive carrying a path slug
    // and a tracking query ("?stkn=OGM0YjY3..."), which say nothing about the note and
    // crowd the words that do out of a three-line snippet. Reduce it to the host, the
    // one part a person actually recognises. Only the PREVIEW is touched; md() still
    // renders the full, real link in the note itself.
    t = t.replace(/\bhttps?:\/\/([^\s)]+)/g, (whole, rest) => {
      const host = rest.split(/[/?#]/)[0].replace(/^www\./, "");
      return host || whole;
    });
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
        case "A": {
          const href = node.getAttribute("href") || "";
          // A bare URL md() autolinked has text == href. Write it back bare, so
          // opening and saving a note never rewrites `https://x` into
          // `[https://x](https://x)` behind the person's back.
          if (kids === href) return href;
          return "[" + kids + "](" + href + ")";
        }
        case "IMG":
          // The other half of md()'s image rule: a pasted-in image serialises back
          // to `![alt](src)`. An <img> is a void element, so it has no children to
          // fold - the alt and src attributes carry everything.
          return (
            "![" +
            (node.getAttribute("alt") || "") +
            "](" +
            (node.getAttribute("src") || "") +
            ")"
          );
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
      let n = ordered ? parseInt(node.getAttribute("start") || "1", 10) || 1 : 1;
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
        out.push((pad + (ordered ? n++ + ". " : "- ") + text).trimEnd());
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
      // A block md() marked tight followed the one before it with no blank line;
      // write it back that way (drop the separator the previous block left).
      if (node.hasAttribute("data-tight") && lines.length && lines[lines.length - 1] === "")
        lines.pop();

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
          // Two adjacent lists must serialise as ONE list - contiguous, no blank line
          // between them. Editing a nested list can leave the DOM with sibling <ul>s
          // where there was one; a blank separator here would split them in markdown,
          // which then round-trips as a permanent, unfixable gap (the "unprovoked
          // spacing" under a bullet). Only put a blank line before a following non-list
          // block.
          const after = node.nextElementSibling;
          if (!after || (after.tagName !== "UL" && after.tagName !== "OL"))
            lines.push("");
          break;
        }
        case "HR":
          lines.push("-".repeat(Math.max(3, +node.getAttribute("data-dashes") || 3)), "");
          break;
        case "BLOCKQUOTE":
          // One quote, one "> " line per line of it.
          for (const l of inline(node).trim().split("\n")) lines.push(("> " + l).trimEnd());
          lines.push("");
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

