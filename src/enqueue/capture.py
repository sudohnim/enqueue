"""Captures: things from the world.

A capture has no body. Its content is the bytes on disk, frozen, because fidelity
to the source is the reason it was saved. Editing one would destroy the only thing
it was for. Commentary goes in `annotations` instead.

Content-addressed by sha256, so the same file captured twice is one artifact.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import config, db
from .ingest import queue as ingest_queue

MIMES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".svg": "image/svg+xml",
    ".md": "text/markdown",
    ".txt": "text/plain",
}

IMAGE_MIMES = {m for m in MIMES.values() if m.startswith("image/")}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def kind_for(mime: str | None, filename: str) -> str:
    if mime == "application/pdf":
        return "pdf"
    if mime in IMAGE_MIMES:
        return "image"
    return "file"


def title_from_url(url: str) -> str:
    """Best guess until the page is actually fetched.

    Fetching is the announced-crawl path and is out of scope here, so a link starts
    life titled by its own address rather than by a lie.
    """
    parsed = urlparse(url)
    tail = (parsed.path or "").rstrip("/").split("/")[-1]
    tail = re.sub(r"\.(html?|php|aspx?)$", "", tail)
    tail = re.sub(r"[-_]+", " ", tail).strip()
    host = parsed.netloc.replace("www.", "")
    return f"{tail} - {host}" if tail else host or url[:120]


def link(url: str, local_only: bool = False) -> dict:
    """Save a URL. Nothing is fetched: that would tell the publisher you read it."""
    url = url.strip()
    if not url:
        raise ValueError("a link needs a url")
    if not urlparse(url).scheme:
        url = "https://" + url

    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    now = _now()

    with db.transaction() as conn:
        existing = conn.execute(
            "SELECT id FROM artifacts WHERE content_hash = ?", (digest,)
        ).fetchone()
        if existing:
            # Saving something already saved is not a no-op. The person reached for it
            # again, and the wall is ordered by last touch, so the honest answer is to
            # move it to the front rather than to silently do nothing and look broken.
            conn.execute("UPDATE artifacts SET updated_at = ? WHERE id = ?", (now, existing["id"]))
            return {"id": existing["id"], "created": False}

        artifact_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, source_url, content_hash,"
            " created_at, updated_at, local_only, status)"
            " VALUES (?,'link',?,NULL,?,?,?,?,?,'pending')",
            (artifact_id, title_from_url(url), url, digest, now, now, 1 if local_only else 0),
        )

    # Returns before anything is fetched, per hard rule 7. The queue resolves it.
    ingest_queue.submit(artifact_id)
    return {"id": artifact_id, "created": True}


def upload(data: bytes, filename: str, mime: str | None = None, local_only: bool = False) -> dict:
    """Store a file whole. Deduped by content, so re-uploading changes nothing."""
    if not data:
        raise ValueError("empty file")

    digest = hashlib.sha256(data).hexdigest()
    suffix = Path(filename).suffix.lower()
    mime = mime or MIMES.get(suffix, "application/octet-stream")
    now = _now()

    with db.transaction() as conn:
        existing = conn.execute(
            "SELECT id FROM artifacts WHERE content_hash = ?", (digest,)
        ).fetchone()
        if existing:
            conn.execute("UPDATE artifacts SET updated_at = ? WHERE id = ?", (now, existing["id"]))
            return {"id": existing["id"], "created": False}

        config.BLOB_DIR.mkdir(parents=True, exist_ok=True)
        blob = config.BLOB_DIR / digest
        if not blob.exists():
            blob.write_bytes(data)

        artifact_id = str(uuid.uuid4())
        title = re.sub(r"[-_]+", " ", Path(filename).stem).strip() or filename
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, mime, filename,"
            " created_at, updated_at, local_only, status)"
            " VALUES (?,?,?,NULL,?,?,?,?,?,?,'text_only')",
            (
                artifact_id,
                kind_for(mime, filename),
                title,
                digest,
                mime,
                filename,
                now,
                now,
                1 if local_only else 0,
            ),
        )

    # Returns first, per hard rule 7. Extraction and indexing happen behind this.
    ingest_queue.submit(artifact_id)
    return {"id": artifact_id, "created": True}


def blob_path(artifact_id: str) -> tuple[Path, str, str] | None:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT content_hash, mime, filename FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    path = config.BLOB_DIR / row["content_hash"]
    if not path.exists():
        return None
    return path, row["mime"] or "application/octet-stream", row["filename"] or artifact_id


def page_count(artifact_id: str) -> int | None:
    """How many pages, from the row if it is known and from the file if it is not.

    Opening a PDF to count its pages cost 13.5 ms each against a 0.8 ms row query, and
    the wall did it once per PDF on every listing. The answer is a property of an
    immutable file, so it is stored the first time anyone asks and never computed again.
    """
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT pages, content_hash, mime FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
    finally:
        conn.close()

    if row is None or row["mime"] != "application/pdf":
        return None
    if row["pages"] is not None:
        return row["pages"]

    count = _count_pages(config.BLOB_DIR / row["content_hash"])
    if count is not None:
        _remember_pages(artifact_id, count)
    return count


def _count_pages(path: Path) -> int | None:
    """Read the page count off the file itself. The slow path, taken once."""
    if not path.exists():
        return None
    try:
        import fitz

        with fitz.open(path) as doc:
            return doc.page_count
    except Exception:  # noqa: BLE001 - a file that claims to be a PDF and is not
        return None


def _remember_pages(artifact_id: str, count: int) -> None:
    with db.transaction() as conn:
        conn.execute("UPDATE artifacts SET pages = ? WHERE id = ?", (count, artifact_id))


# A file that is already text needs no extractor, only decoding. Without this a .txt
# or .md capture had its contents nowhere in the system: not on screen, not in the
# index, not available to a question. It rendered as an empty glyph.
TEXT_MIMES = {"text/plain", "text/markdown", "text/csv", "application/json", "text/html"}
MAX_TEXT_BYTES = 2 * 1024 * 1024


def _read_text_file(path, mime: str) -> str:
    raw = path.read_bytes()[:MAX_TEXT_BYTES]
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def extract_text(artifact_id: str) -> int:
    """Pull the text out of a PDF, one row per page.

    Until this existed a captured PDF had no text anywhere in the system: it could not
    be searched, could not be asked about, and could not be curated. It was a picture
    of a document.

    Page numbers are kept because "page 9" is how a person refers to a place in a PDF.
    A hit that cannot say where it is has not really found anything.
    """
    found = blob_path(artifact_id)
    if not found:
        return 0

    path, mime, _ = found
    rows: list[tuple[int, str]] = []

    if mime in TEXT_MIMES:
        # One row, page 0. A text file has no pages, and inventing them would make
        # "page 3" mean nothing when a search result cites it.
        try:
            text = _read_text_file(path, mime).strip()
        except OSError:
            return 0
        if text:
            rows.append((0, text))
    elif mime == "application/pdf":
        import fitz

        try:
            with fitz.open(path) as doc:
                # The document is open anyway, so the page count is free here. Anywhere
                # else it costs a file open, which is what the wall used to pay per card.
                _remember_pages(artifact_id, doc.page_count)
                for number in range(doc.page_count):
                    text = doc.load_page(number).get_text("text")
                    # pymupdf's stubs allow list/dict returns for other flag combos;
                    # "text" always yields a string, but the guard costs nothing.
                    if not isinstance(text, str):
                        continue
                    page = text.strip()
                    if page:
                        rows.append((number, page))
        except Exception:  # noqa: BLE001 - a file that claims to be a PDF and is not
            return 0
    else:
        return 0

    with db.transaction() as conn:
        conn.execute("DELETE FROM page_text WHERE artifact_id = ?", (artifact_id,))
        for number, text in rows:
            conn.execute(
                "INSERT INTO page_text (artifact_id, page, text, extractor)"
                " VALUES (?,?,?,'pymupdf')",
                (artifact_id, number, text),
            )
        # A PDF with text is no longer pending: it has something to say.
        if rows:
            conn.execute(
                "UPDATE artifacts SET status = 'ok' WHERE id = ? AND status = 'pending'",
                (artifact_id,),
            )
    return len(rows)


def page_text(artifact_id: str) -> list[dict]:
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT page, text FROM page_text WHERE artifact_id = ? ORDER BY page",
            (artifact_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def find_in_pdf(artifact_id: str, term: str) -> list[dict]:
    """Where a phrase sits on each page, as fractions of the page rectangle.

    Fractions rather than points, because the reader renders pages at whatever width
    the window happens to be and at whatever pixel density the screen has. A fraction
    survives both; a coordinate in points would need the client to know the page size
    and would drift the moment either changed.
    """
    found = blob_path(artifact_id)
    term = (term or "").strip()
    if not found or found[1] != "application/pdf" or not term:
        return []

    import fitz

    hits: list[dict] = []
    try:
        with fitz.open(found[0]) as doc:
            for number in range(doc.page_count):
                page = doc.load_page(number)
                box = page.rect
                if not box.width or not box.height:
                    continue
                for rect in page.search_for(term):
                    hits.append(
                        {
                            "page": number,
                            "x": rect.x0 / box.width,
                            "y": rect.y0 / box.height,
                            "w": (rect.x1 - rect.x0) / box.width,
                            "h": (rect.y1 - rect.y0) / box.height,
                        }
                    )
    except Exception:  # noqa: BLE001 - a file that claims to be a PDF and is not
        return []
    return hits


def render_page(artifact_id: str, number: int, width: int = 900) -> bytes | None:
    """Rasterise a PDF page.

    Browsers cannot be relied on to display an embedded PDF: the in-app browser has
    no PDF plugin and `<embed>` renders an empty box. Rendering server side makes a
    PDF an ordinary image, and it is the same call that will extract page text later.
    """
    found = blob_path(artifact_id)
    if not found or found[1] != "application/pdf":
        return None

    import fitz

    # A file can claim to be a PDF and not be one. That is a 404, not a crash: the
    # artifact is still real and still readable, it simply has no page to render.
    try:
        with fitz.open(found[0]) as doc:
            if not 0 <= number < doc.page_count:
                return None
            page = doc.load_page(number)
            zoom = width / page.rect.width
            return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("png")
    except Exception:
        return None
