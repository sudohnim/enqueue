"""Import notes from other apps: a folder, or a .zip, of Markdown, HTML and files.

One reader covers the exports people bring:
Obsidian (a vault of Markdown, YAML frontmatter, `![[picture.png]]` embeds),
Notion ("Markdown & CSV": every name ends in a 32-character id, databases are CSV),
Bear (Markdown or TextBundle folders; a `.bear2bk` backup is a zip of TextBundles),
Standard Notes (a decrypted backup: one JSON file of notes and tags),
Fabric (HTML notepads, their pictures in a "<name> assets" folder, files as they were),
and any other folder of notes.
A note keeps its title, tags and dates; a picture inside it becomes an embedded image;
every other file is saved as a capture. A note already in the library is skipped.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import yaml
from bs4 import BeautifulSoup, NavigableString, Tag

from . import capture, db, events, notes, tags

log = logging.getLogger(__name__)

NOTE_SUFFIXES = {".md", ".markdown", ".mdown", ".txt"}
HTML_SUFFIXES = {".html", ".htm"}
ZIP_SUFFIXES = {".zip", ".bear2bk"}
SKIP_DIRS = {"__MACOSX", ".obsidian", ".trash", ".git", "node_modules"}
MAX_FILE = 100 * 1024 * 1024
MAX_UNPACKED = 8 * 1024 * 1024 * 1024
# Notion ends every exported name in the page's id: "Reading list 1f2e...9a.md".
NOTION_ID = re.compile(r"\s+[0-9a-f]{32}$")
FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)
# `#tag`, `#nested/tag`, and Bear's `#tag with spaces#`; never C#, #1 or a heading.
INLINE_TAG = re.compile(r"(?<![\w#/&])#([^\W\d_][\w/-]*)")
BEAR_TAG = re.compile(r"(?<![\w#/&])#([^\W\d_][^#\n]*?[^\s#])#")
MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
WIKI_EMBED = re.compile(r"!\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
FENCE = re.compile(r"```.*?```|`[^`\n]*`", re.S)

_lock = threading.Lock()
_state: dict = {"state": "idle"}


def state() -> dict:
    """Where the last import stands: idle, running (with counts so far), done or failed."""
    with _lock:
        return dict(_state)


def start(path: str) -> dict:
    """Import `path` on a thread of its own; refuses while another import runs."""
    source = Path(path).expanduser()
    if not source.exists():
        raise FileNotFoundError(f"{source} does not exist")
    with _lock:
        if _state.get("state") == "running":
            raise RuntimeError("an import is already running")
        _state.clear()
        _state.update(state="running", path=str(source), notes=0, files=0, skipped=0, errors=[])
    threading.Thread(target=_run_safely, args=(source,), name="import", daemon=True).start()
    return state()


def _run_safely(source: Path) -> None:
    try:
        run(source)
    except Exception as exc:  # noqa: BLE001 - the page shows why, the engine lives on
        log.exception("import of %s failed", source)
        with _lock:
            _state.update(state="failed", error=str(exc)[:300])


def _count(key: str, error: str | None = None) -> None:
    with _lock:
        _state[key] = _state.get(key, 0) + 1
        if error and len(_state.setdefault("errors", [])) < 50:
            _state["errors"].append(error[:200])


def run(source: Path) -> dict:
    """Import a folder or a zip. Returns how many notes and files came in."""
    with _lock:
        _state.update(state="running", path=str(source), notes=0, files=0, skipped=0, errors=[])
    work = Path(tempfile.mkdtemp(prefix="enqueue-import-"))
    try:
        if source.is_dir():
            roots = [source]
        elif source.suffix.lower() in ZIP_SUFFIXES or zipfile.is_zipfile(source):
            _unzip(source, work)
            roots = [work]
        else:
            roots = []
        _unzip_nested(work)
        seen = _existing_bodies()
        backup = _find_standard_notes(roots)
        if backup is not None:
            _import_standard_notes(backup, seen)
        else:
            _import_files(_walk(roots) if roots else [source], seen)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    with _lock:
        _state["state"] = "done"
        report = dict(_state)
    events.emit(
        "import",
        f"{report['notes']} notes, {report['files']} files from {source.name}",
        data={k: report[k] for k in ("notes", "files", "skipped", "path")},
    )
    return report


# ---- unpacking -----------------------------------------------------------------------


def _unzip(archive: Path, into: Path) -> None:
    """Unpack a zip under `into`, refusing names that climb out of it."""
    target = into / archive.stem
    total = 0
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            out = (target / info.filename).resolve()
            if not out.is_relative_to(target.resolve()):
                raise ValueError(f"{archive.name} holds a file outside itself: {info.filename}")
            total += info.file_size
            if total > MAX_UNPACKED:
                raise ValueError(f"{archive.name} unpacks to more than 8 GB")
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
            stamp = datetime(*info.date_time).timestamp()
            os.utime(out, (stamp, stamp))


def _unzip_nested(work: Path) -> None:
    """Notion splits a big export into zips inside the zip; Bear's backup is one."""
    for _ in range(3):
        nested = [p for p in _all_files(work) if p.suffix.lower() in ZIP_SUFFIXES]
        nested = [p for p in nested if zipfile.is_zipfile(p)]
        if not nested:
            return
        for archive in nested:
            _unzip(archive, archive.parent)
            archive.unlink()


def _all_files(base: Path) -> list[Path]:
    out = []
    for root, dirs, names in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        out += [Path(root) / n for n in sorted(names) if not n.startswith(".")]
    return out


def _walk(roots: list[Path]) -> list[Path]:
    """Every file to import; a TextBundle folder counts as one note."""
    out: list[Path] = []
    for base in roots:
        for root, dirs, names in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
            for d in [d for d in dirs if d.endswith(".textbundle")]:
                out.append(Path(root) / d)
                dirs.remove(d)
            out += [Path(root) / n for n in sorted(names) if not n.startswith(".")]
    return out


# ---- notes and files -----------------------------------------------------------------


def _existing_bodies() -> set[str]:
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT body FROM artifacts WHERE kind = 'note' AND deleted_at IS NULL"
            " AND body IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    return {_digest(r["body"]) for r in rows}


def _digest(body: str) -> str:
    return hashlib.sha256(" ".join(body.split()).encode()).hexdigest()


def _import_files(files: list[Path], seen: set[str]) -> None:
    by_name: dict[str, Path] = {}
    for f in files:
        by_name.setdefault(f.name.lower(), f)
    used: set[Path] = set()
    note_files = [f for f in files if _is_note(f)]
    for f in note_files:
        try:
            _import_note(f, by_name, used, seen)
        except Exception as exc:  # noqa: BLE001 - one bad file never stops the rest
            _count("skipped", f"{f.name}: {exc}")
    for f in files:
        if f in note_files or f.resolve() in used or f.is_dir():
            continue
        if f.suffix.lower() == ".csv" and NOTION_ID.search(f.stem.removesuffix("_all")):
            continue  # a Notion database: its pages came in as notes
        if any(p.name.endswith(".textbundle") for p in f.parents):
            continue
        try:
            _import_file(f)
        except Exception as exc:  # noqa: BLE001
            _count("skipped", f"{f.name}: {exc}")


def _is_note(f: Path) -> bool:
    if f.is_dir():
        return f.name.endswith(".textbundle")
    return f.suffix.lower() in NOTE_SUFFIXES | HTML_SUFFIXES


def _import_file(f: Path) -> None:
    size = f.stat().st_size
    if size == 0 or size > MAX_FILE:
        _count("skipped", f"{f.name}: {'empty' if not size else 'over 100 MB'}")
        return
    out = capture.upload(f.read_bytes(), f.name, background=True)
    _count("files" if out.get("created") else "skipped")


def _import_note(f: Path, by_name: dict[str, Path], used: set[Path], seen: set[str]) -> None:
    folder, text, meta = _read_note(f)
    front, body = _frontmatter(text)
    title = _title(front, body, f)
    if not body.strip():
        _count("skipped")
        return
    if _digest(body) in seen:
        _count("skipped")
        return
    body = _embed_pictures(body, folder, by_name, used)
    created = _stamp(front.get("created") or front.get("date") or meta.get("created"))
    updated = _stamp(front.get("updated") or front.get("modified") or meta.get("updated"))
    mtime = datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat()
    names = _tags(front, body, bear=f.is_dir())
    _save(title, body, names, created or updated or mtime, updated or mtime)
    seen.add(_digest(body))


def _read_note(f: Path) -> tuple[Path, str, dict]:
    """The folder pictures are relative to, the note's text, and dates it carries."""
    meta: dict = {}
    if f.is_dir():  # TextBundle
        text_file = next(
            (f / n for n in ("text.md", "text.markdown", "text.txt") if (f / n).exists()), None
        )
        if text_file is None:
            raise ValueError("a TextBundle without text")
        info = f / "info.json"
        if info.exists():
            bear = json.loads(info.read_text("utf-8", "replace")).get("net.shinyfrog.bear", {})
            meta = {"created": bear.get("creationDate"), "updated": bear.get("modificationDate")}
        return f, text_file.read_text("utf-8", "replace"), meta
    raw = f.read_text("utf-8", "replace")
    if f.suffix.lower() in HTML_SUFFIXES:
        raw = html_to_md(raw)
    return f.parent, raw, meta


def _frontmatter(text: str) -> tuple[dict, str]:
    text = text.lstrip("﻿")
    m = FRONTMATTER.match(text)
    if not m:
        return {}, text
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}, text
    if not isinstance(data, dict):
        return {}, text
    return {str(k).lower(): v for k, v in data.items()}, text[m.end() :].lstrip("\n")


def _title(front: dict, body: str, f: Path) -> str | None:
    """The frontmatter's title, else None when the body opens with one, else the name."""
    if isinstance(front.get("title"), str) and front["title"].strip():
        return front["title"].strip()
    if re.match(r"\s*#\s+\S", body):
        return None
    stem = f.stem if not f.is_dir() else f.name.removesuffix(".textbundle")
    return NOTION_ID.sub("", stem).strip() or None


def _tags(front: dict, body: str, bear: bool = False) -> list[str]:
    found: list[str] = []
    raw = front.get("tags") or front.get("tag") or []
    if isinstance(raw, str):
        raw = re.split(r"[,\s]+", raw)
    found += [str(t).lstrip("#") for t in raw if str(t).strip()]
    prose = FENCE.sub(" ", body)
    if bear:  # Bear's `#tag with spaces#`
        found += BEAR_TAG.findall(prose)
        prose = BEAR_TAG.sub(" ", prose)
    found += INLINE_TAG.findall(prose)
    out = []
    for t in found:
        try:
            name = tags.normalize(t)
        except ValueError:
            continue
        if name not in out:
            out.append(name)
    return out


def _stamp(value) -> str | None:
    """An ISO-8601 UTC time from whatever a note carried, or None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        at = value
    elif isinstance(value, date):
        at = datetime(value.year, value.month, value.day)
    else:
        try:
            at = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at.astimezone(timezone.utc).isoformat()


def _embed_pictures(body: str, folder: Path, by_name: dict[str, Path], used: set[Path]) -> str:
    """Pictures the note shows become embedded images; anything else is left as written."""

    def upload(path: Path | None) -> str | None:
        mime = capture.MIMES.get(path.suffix.lower()) if path is not None else None
        if path is None or not path.is_file() or mime not in capture.IMAGE_MIMES:
            return None
        if path.stat().st_size > MAX_FILE:
            return None
        used.add(path.resolve())
        return capture.upload(path.read_bytes(), path.name, embedded=True)["id"]

    def markdown(m: re.Match) -> str:
        ref = unquote(m.group(2))
        if re.match(r"[a-z][a-z0-9+.-]*:", ref, re.I) or ref.startswith("/"):
            return m.group(0)
        aid = upload((folder / ref).resolve()) or upload(by_name.get(Path(ref).name.lower()))
        return f"![{m.group(1)}](/artifacts/{aid}/blob)" if aid else m.group(0)

    def wiki(m: re.Match) -> str:
        aid = upload(by_name.get(Path(m.group(1).strip()).name.lower()))
        return f"![](/artifacts/{aid}/blob)" if aid else m.group(0)

    return WIKI_EMBED.sub(wiki, MD_IMAGE.sub(markdown, body))


def _save(title: str | None, body: str, names: list[str], created: str, updated: str) -> None:
    from .sync.client import push_artifact

    note = notes.create(body, title=title, at=created, background=True)["artifact"]
    with db.transaction() as conn:
        for name in names:
            tags.attach(conn, note["id"], name, created)
        conn.execute("UPDATE artifacts SET updated_at = ? WHERE id = ?", (updated, note["id"]))
    if names or updated != created:
        push_artifact(note["id"])
    _count("notes")


# ---- Standard Notes -----------------------------------------------------------------


def _find_standard_notes(roots: list[Path]) -> Path | None:
    for base in roots:
        for f in _all_files(base):
            if f.suffix.lower() not in {".txt", ".json"} or f.stat().st_size > 512 * 1024 * 1024:
                continue
            with open(f, "rb") as fh:
                head = fh.read(4096).decode("utf-8", "replace")
            if '"items"' in head and ('"content_type"' in head or '"version"' in head):
                return f
    return None


def _import_standard_notes(path: Path, seen: set[str]) -> None:
    data = json.loads(path.read_text("utf-8"))
    items = [i for i in data.get("items", []) if not i.get("deleted")]
    if any(isinstance(i.get("content"), str) for i in items):
        raise ValueError("this Standard Notes backup is encrypted: export a decrypted one")
    note_tags: dict[str, list[str]] = {}
    for item in items:
        if item.get("content_type") == "Tag":
            name = (item.get("content") or {}).get("title") or ""
            for ref in (item.get("content") or {}).get("references") or []:
                note_tags.setdefault(ref.get("uuid"), []).append(name)
    for item in items:
        content = item.get("content") or {}
        if item.get("content_type") != "Note" or content.get("trashed"):
            continue
        body = content.get("text") or ""
        if not body.strip() or _digest(body) in seen:
            _count("skipped")
            continue
        title = (content.get("title") or "").strip() or None
        names = []
        for t in note_tags.get(item.get("uuid"), []) + _tags({}, body):
            try:
                if (name := tags.normalize(t)) not in names:
                    names.append(name)
            except ValueError:
                continue
        created = _stamp(item.get("created_at")) or db.now()
        _save(title, body, names, created, _stamp(item.get("updated_at")) or created)
        seen.add(_digest(body))


# ---- HTML to Markdown ---------------------------------------------------------------


def html_to_md(html: str) -> str:
    """Markdown for an HTML page's body: headings, lists, quotes, code, links, pictures
    and tables, in the shapes the note editor writes."""
    soup = BeautifulSoup(html, "lxml")
    for junk in soup(["script", "style", "head", "noscript", "template"]):
        junk.decompose()
    root = soup.body or soup
    out = _blocks(root, 0).strip()
    return re.sub(r"\n{3,}", "\n\n", out) + "\n"


_BLOCK = {"p", "div", "section", "article", "main", "header", "footer", "figure", "aside"}


def _blocks(node: Tag, depth: int) -> str:
    parts: list[str] = []
    inline: list[str] = []

    def flush() -> None:
        text = "".join(inline).strip()
        if text:
            parts.append(text)
        inline.clear()

    for child in node.children:
        if isinstance(child, NavigableString):
            inline.append(re.sub(r"\s+", " ", str(child)))
            continue
        if not isinstance(child, Tag):
            continue
        name = child.name
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            flush()
            parts.append("#" * int(name[1]) + " " + _inline(child).strip())
        elif name in {"ul", "ol"}:
            flush()
            parts.append(_list(child, depth))
        elif name == "blockquote":
            flush()
            quoted = _blocks(child, depth).strip()
            parts.append("\n".join("> " + line if line else ">" for line in quoted.splitlines()))
        elif name == "pre":
            flush()
            parts.append("```\n" + child.get_text().rstrip("\n") + "\n```")
        elif name == "hr":
            flush()
            parts.append("---")
        elif name == "table":
            flush()
            parts.append(_table(child))
        elif name in _BLOCK:
            flush()
            inner = _blocks(child, depth).strip()
            if inner:
                parts.append(inner)
        else:
            inline.append(_inline(child))
    flush()
    return "\n\n".join(parts)


def _inline(node) -> str:
    if isinstance(node, NavigableString):
        return re.sub(r"\s+", " ", str(node))
    name = node.name
    inner = "".join(_inline(c) for c in node.children)
    if name == "br":
        return "  \n"
    if name in {"strong", "b"} and inner.strip():
        return f"**{inner.strip()}**"
    if name in {"em", "i"} and inner.strip():
        return f"*{inner.strip()}*"
    if name in {"s", "del", "strike"} and inner.strip():
        return f"~~{inner.strip()}~~"
    if name == "code":
        return f"`{node.get_text()}`"
    if name == "a" and node.get("href"):
        href = node["href"].replace(" ", "%20")
        return f"[{inner.strip() or node['href']}]({href})"
    if name == "img" and node.get("src"):
        return f"![{node.get('alt', '')}]({node['src'].replace(' ', '%20')})"
    if name in {"ul", "ol", "table", "pre", "blockquote"} or name in _BLOCK:
        return " " + _blocks(node, 0) + " "
    return inner


def _list(node: Tag, depth: int) -> str:
    lines = []
    for n, li in enumerate(node.find_all("li", recursive=False), start=1):
        marker = f"{n}." if node.name == "ol" else "-"
        nested = [c for c in li.children if isinstance(c, Tag) and c.name in {"ul", "ol"}]
        for c in nested:
            c.extract()
        checkbox = li.find("input", attrs={"type": "checkbox"})
        text = _inline(li).strip()
        if checkbox is not None:
            text = ("[x] " if checkbox.has_attr("checked") else "[ ] ") + text
        lines.append("  " * depth + f"{marker} {text}")
        lines += [_list(c, depth + 1) for c in nested]
    return "\n".join(lines)


def _table(node: Tag) -> str:
    rows = [
        [
            "".join(_inline(c) for c in cell.children).strip().replace("|", "\\|")
            for cell in tr.find_all(["th", "td"])
        ]
        for tr in node.find_all("tr")
    ]
    rows = [r for r in rows if r]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)
