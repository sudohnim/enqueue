"""Parse Fabric's TipTap HTML export into a flat block list that preserves the tree.

The nesting is semantic and must survive: a top-level <li> is a claim, and nested
<li> elements are the author's elaboration on it. Flattening throws away the thing
that makes these good artifacts.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from bs4 import BeautifulSoup, NavigableString, Tag

# Elements that carry text in their own right when they are not list items.
_STANDALONE = ("p", "h1", "h2", "h3", "h4", "pre", "blockquote")


@dataclass
class ParsedBlock:
    uuid: str
    parent_uuid: str | None
    ordinal: int
    depth: int
    text: str
    created_at: str | None


def _attrs(*tags: Tag | None) -> tuple[str, str | None]:
    """First data-uuid and data-created-at found across the given tags."""
    node_id = None
    created = None
    for t in tags:
        if t is None:
            continue
        node_id = node_id or t.get("data-uuid")
        created = created or t.get("data-created-at")
    return node_id or str(uuid.uuid4()), created


def _own_text(li: Tag) -> tuple[str, Tag | None]:
    """Text belonging to this <li> only, not to its nested lists."""
    carrier = None
    parts: list[str] = []
    for child in li.children:
        if isinstance(child, NavigableString):
            s = str(child).strip()
            if s:
                parts.append(s)
        elif isinstance(child, Tag):
            if child.name in ("ul", "ol"):
                continue
            carrier = carrier or child
            parts.append(_text_of(child))
    return _clean(" ".join(p for p in parts if p)), carrier


def _text_of(tag: Tag) -> str:
    if tag.name == "pre":
        # Code must survive verbatim, newlines included.
        return tag.get_text()
    return tag.get_text(" ")


def _clean(s: str) -> str:
    s = s.replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", s).strip()


def parse_fabric_html(html: str) -> list[ParsedBlock]:
    soup = BeautifulSoup(html, "lxml")
    blocks: list[ParsedBlock] = []
    counter = [0]

    def walk(container: Tag, parent: str | None, depth: int) -> None:
        for li in container.find_all("li", recursive=False):
            text, carrier = _own_text(li)
            node_id, created = _attrs(li, carrier)
            if text:
                blocks.append(ParsedBlock(node_id, parent, counter[0], depth, text, created))
                counter[0] += 1
            for nested in li.find_all(("ul", "ol"), recursive=False):
                walk(nested, node_id if text else parent, depth + 1)

    root = soup.body or soup
    top_lists = [t for t in root.find_all(("ul", "ol"), recursive=False)]
    if not top_lists:
        top_lists = [t for t in root.find_all(("ul", "ol")) if not t.find_parent(("ul", "ol"))]

    for lst in top_lists:
        walk(lst, None, 0)

    # Standalone elements outside any list. Fabric uses these for short notes,
    # pasted essays, and code snippets.
    for tag in root.find_all(_STANDALONE):
        if tag.find_parent("li") is not None:
            continue
        text = _clean(_text_of(tag)) if tag.name != "pre" else _text_of(tag).strip()
        if not text:
            continue
        node_id, created = _attrs(tag)
        blocks.append(ParsedBlock(node_id, None, counter[0], 0, text, created))
        counter[0] += 1

    return blocks


def plain_text(blocks: list[ParsedBlock]) -> str:
    return "\n".join(b.text for b in blocks)
