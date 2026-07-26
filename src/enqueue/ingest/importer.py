"""Import a Fabric export into the artifact store.

Artifacts are append-only. Re-running is safe: dedupe is by content hash.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from .. import config, db
from . import secrets
from .fabric import ParsedBlock, parse_fabric_html, plain_text

NOTE_SUFFIXES = {".html"}
BLOB_SUFFIXES = {".pdf", ".png", ".gif", ".jpg", ".jpeg", ".md", ".txt"}

# Two of anything below and the note is pasted model output rather than the
# author's own writing. Heuristic on purpose: no model call, no network.
_PASTED_PHRASES = (
    "let's break",
    "let me know if",
    "here's a",
    "that's an excellent",
    "in summary",
    "great question",
    "i hope this helps",
    "certainly!",
)
_EMOJI = re.compile("[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff]", re.UNICODE)


@dataclass
class ImportReport:
    imported: int = 0
    skipped_duplicate: int = 0
    blobs: int = 0
    blocks: int = 0
    with_secrets: list[str] | None = None

    def __post_init__(self) -> None:
        if self.with_secrets is None:
            self.with_secrets = []


def _title_from(path: Path) -> str:
    stem = path.stem.replace("_", " ")
    return re.sub(r"\s+", " ", stem).strip()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _earliest_created(blocks: list[ParsedBlock], fallback: str) -> str:
    stamps = sorted(b.created_at for b in blocks if b.created_at)
    return stamps[0] if stamps else fallback


def _normalise(text: str) -> str:
    """Fold typographic punctuation so phrase matching works.

    Fabric stores curly apostrophes, so a straight-quoted phrase list silently misses
    every instance. This was a real bug: PKMS opens with "That's an excellent" and was
    classified as authored.
    """
    return text.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')


def classify_provenance(text: str, blocks: list[ParsedBlock]) -> str:
    words = len(text.split())
    signals = 0
    lowered = _normalise(text)

    if _EMOJI.search(text):
        signals += 1
    if any(p in lowered for p in _PASTED_PHRASES):
        signals += 1
    if sum(1 for b in blocks if b.depth == 0) >= 8 and words > 800:
        signals += 1
    if words > 800 and sum(1 for b in blocks if b.depth >= 1) < 3:
        signals += 1

    return "pasted" if signals >= 2 else "authored"


def import_fabric(root: Path) -> ImportReport:
    """Import every folder of a Fabric export. Idempotent by content hash."""
    report = ImportReport()

    with db.transaction() as conn:
        existing = {r["content_hash"] for r in conn.execute("SELECT content_hash FROM artifacts")}

        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            local_only = 1 if folder.name in config.SKIP_FACETS_FOR_FOLDERS else 0

            for path in sorted(folder.iterdir()):
                if path.name.startswith("."):
                    continue
                suffix = path.suffix.lower()

                if suffix in NOTE_SUFFIXES:
                    _import_note(conn, path, folder.name, local_only, existing, report)
                elif suffix in BLOB_SUFFIXES:
                    _import_blob(conn, path, folder.name, local_only, existing, report)

    return report


def _import_note(conn, path, folder, local_only, existing, report) -> None:
    html = path.read_text(encoding="utf-8", errors="replace")
    blocks = parse_fabric_html(html)
    text = plain_text(blocks)

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if digest in existing:
        report.skipped_duplicate += 1
        return
    existing.add(digest)

    hits = secrets.scan(text)
    status = "text_only" if hits else "ok"
    artifact_id = str(uuid.uuid4())

    conn.execute(
        "INSERT INTO artifacts (id, kind, title, source_url, content_hash, captured_at,"
        " imported_from, provenance, local_only, status) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            artifact_id,
            "note",
            _title_from(path),
            None,
            digest,
            _earliest_created(blocks, _iso(path.stat().st_mtime)),
            f"fabric:{folder}",
            classify_provenance(text, blocks),
            local_only,
            status,
        ),
    )

    id_map: dict[str, str] = {}
    for block in blocks:
        block_id = str(uuid.uuid4())
        id_map[block.uuid] = block_id
        conn.execute(
            "INSERT INTO blocks (id, artifact_id, parent_id, ordinal, depth, text, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                block_id,
                artifact_id,
                id_map.get(block.parent_uuid) if block.parent_uuid else None,
                block.ordinal,
                block.depth,
                block.text,
                block.created_at,
            ),
        )
    report.blocks += len(blocks)

    for hit in hits:
        conn.execute(
            "INSERT INTO secret_hits (id, artifact_id, kind, line, excerpt) VALUES (?,?,?,?,?)",
            (str(uuid.uuid4()), artifact_id, hit.kind, hit.line, hit.excerpt),
        )
    if hits:
        report.with_secrets.append(f"{folder}/{path.name}")

    report.imported += 1


def _import_blob(conn, path, folder, local_only, existing, report) -> None:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest in existing:
        report.skipped_duplicate += 1
        return
    existing.add(digest)

    dest = config.BLOB_DIR / digest
    if not dest.exists():
        dest.write_bytes(raw)

    kind = {".pdf": "pdf", ".png": "image", ".gif": "image", ".jpg": "image", ".jpeg": "image"}.get(
        path.suffix.lower(), "other"
    )

    conn.execute(
        "INSERT INTO artifacts (id, kind, title, source_url, content_hash, captured_at,"
        " imported_from, provenance, local_only, status) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            str(uuid.uuid4()),
            kind,
            _title_from(path),
            None,
            digest,
            _iso(path.stat().st_mtime),
            f"fabric:{folder}",
            "unknown",
            local_only,
            "text_only",
        ),
    )
    report.blobs += 1


def import_bookmarks(path: Path) -> ImportReport:
    """Netscape bookmark format. URL and title only, never fetched."""
    report = ImportReport()
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "lxml")

    with db.transaction() as conn:
        existing = {r["content_hash"] for r in conn.execute("SELECT content_hash FROM artifacts")}

        for anchor in soup.find_all("a"):
            href = anchor.get("href")
            if not href:
                continue
            digest = hashlib.sha256(href.encode("utf-8")).hexdigest()
            if digest in existing:
                report.skipped_duplicate += 1
                continue
            existing.add(digest)

            add_date = anchor.get("add_date")
            captured = _iso(int(add_date) / 1000) if add_date and add_date.isdigit() else _iso(0)

            conn.execute(
                "INSERT INTO artifacts (id, kind, title, source_url, content_hash, captured_at,"
                " imported_from, provenance, local_only, status) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    "bookmark",
                    anchor.get_text(" ").strip() or href,
                    href,
                    digest,
                    captured,
                    "fabric:bookmarks",
                    "unknown",
                    0,
                    "text_only",
                ),
            )
            report.imported += 1

    return report
