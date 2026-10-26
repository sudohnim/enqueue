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
from pathlib import Path
from urllib.parse import urlparse

from . import blobstore, db
from .ingest import queue as ingest_queue
from .sync.client import push_artifact

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


def kind_for(mime: str | None, filename: str) -> str:
    if mime == "application/pdf":
        return "pdf"
    if mime in IMAGE_MIMES:
        return "image"
    return "file"


# The id a publisher hangs on the end of an article's address (Medium: a dash and
# twelve hex characters). It is a word in the slug, not a word in the title.
_SLUG_ID = re.compile(r"[ ]+(?=[0-9a-f]*\d)[0-9a-f]{8,16}$")


def title_from_url(url: str) -> str:
    """A link's title until its page is fetched, and for good when the publisher
    refuses the fetch: the article's own words out of its address, as a title.

    `medium.com/x/the-end-of-prestige-0b96b649edf4` is "The end of prestige". The
    publisher's id and the site name are left out: the site is already shown beside
    the title, and "the end of prestige 0b96b649edf4 - medium.com" read as an
    address, not as the thing saved. An address that names nothing (a bare domain,
    one word, a document id) is titled by its site.
    """
    parsed = urlparse(url)
    host = parsed.netloc.replace("www.", "")
    tail = (parsed.path or "").rstrip("/").split("/")[-1]
    tail = re.sub(r"\.(html?|php|aspx?)$", "", tail)
    tail = re.sub(r"[-_]+", " ", tail).strip()
    tail = _SLUG_ID.sub("", tail)
    if len(tail.split()) < 2:
        return host or url[:120]
    return tail[0].upper() + tail[1:]


def _address_title(url: str) -> str:
    """What `title_from_url` returned before it was cleaned up, kept so a title an
    older build wrote is still known for the placeholder it is."""
    parsed = urlparse(url)
    tail = (parsed.path or "").rstrip("/").split("/")[-1]
    tail = re.sub(r"\.(html?|php|aspx?)$", "", tail)
    tail = re.sub(r"[-_]+", " ", tail).strip()
    host = parsed.netloc.replace("www.", "")
    return f"{tail} - {host}" if tail else host or url[:120]


def is_placeholder_title(title: str | None, url: str) -> bool:
    """Whether a link's title is one made from its address (now or by an older build,
    or the bare address the phone saves) rather than the page's name or the person's
    own. Only a placeholder may be replaced, by a preview or by a better placeholder."""
    title = (title or "").strip()
    return not title or title in (title_from_url(url), _address_title(url), url.strip())


def retitle_placeholders() -> int:
    """Give every link still titled by its address the clean form of that title.

    Runs at engine startup; a link already clean, named by its page or renamed by the
    person is left alone, so a second run changes nothing. `updated_at` is not
    touched (the wall keeps its order); the push carries the title to the phone, which
    applies a snapshot with an equal key.
    """
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, title, source_url FROM artifacts WHERE kind = 'link'"
            " AND source_url IS NOT NULL AND title_explicit = 0"
            " AND deleted_at IS NULL AND vaulted_at IS NULL"
        ).fetchall()
    finally:
        conn.close()
    changed = []
    for row in rows:
        clean = title_from_url(row["source_url"])
        if row["title"] != clean and is_placeholder_title(row["title"], row["source_url"]):
            changed.append((clean, row["id"]))
    if not changed:
        return 0
    with db.transaction() as conn:
        conn.executemany("UPDATE artifacts SET title = ? WHERE id = ?", changed)
    for _, artifact_id in changed:
        ingest_queue.submit_background(artifact_id)  # the title is indexed with the text
        push_artifact(artifact_id)
    return len(changed)


def link(url: str, local_only: bool = False, title: str | None = None) -> dict:
    """Save a URL. Nothing is fetched: that would tell the publisher you read it.

    `title` is the page's name when the capture carried one (a share hands over
    "Title" then the address). It stands in for the URL-derived placeholder; a
    preview never overrules it, since only the placeholder is replaced.
    """
    title = " ".join((title or "").split())[:300] or None
    url = url.strip()
    if not url:
        raise ValueError("a link needs a url")
    if not urlparse(url).scheme:
        url = "https://" + url

    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    now = db.now()

    with db.transaction() as conn:
        existing = conn.execute(
            "SELECT id, deleted_at FROM artifacts WHERE content_hash = ?", (digest,)
        ).fetchone()
        if existing:
            if existing["deleted_at"]:
                # Saving a link that sits in the trash is "keep this again": it
                # comes back whole and in front, exactly like re-saving a link that
                # is still on the wall. A no-op against the trash row would read as
                # a save that never happened.
                conn.execute(
                    "UPDATE artifacts SET deleted_at = NULL, updated_at = ?" " WHERE id = ?",
                    (now, existing["id"]),
                )
                artifact_id = existing["id"]
                restored = True
            else:
                # Saving something already saved is not a no-op. The person reached for it
                # again, and the wall is ordered by last touch, so the honest answer is to
                # move it to the front rather than to silently do nothing and look broken.
                conn.execute(
                    "UPDATE artifacts SET updated_at = ? WHERE id = ?",
                    (now, existing["id"]),
                )
                return {"id": existing["id"], "created": False}
        else:
            artifact_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO artifacts (id, kind, title, body, source_url, content_hash,"
                " created_at, updated_at, local_only, status)"
                " VALUES (?,'link',?,NULL,?,?,?,?,?,'pending')",
                (
                    artifact_id,
                    title or title_from_url(url),
                    url,
                    digest,
                    now,
                    now,
                    1 if local_only else 0,
                ),
            )
            restored = False

    # Returns before anything is fetched, per hard rule 7. The queue resolves it.
    ingest_queue.submit(artifact_id)
    push_artifact(artifact_id)
    out = {"id": artifact_id, "created": not restored}
    if restored:
        out["restored"] = True
    return out


def upload(
    data: bytes,
    filename: str,
    mime: str | None = None,
    local_only: bool = False,
    embedded: bool = False,
) -> dict:
    """Store a file whole. Deduped by content, so re-uploading changes nothing.

    `embedded` marks an image pasted inside a note: it is a real artifact (so its
    bytes ride the blob store and its sync), but `embedded_at` keeps it off the wall
    and out of search, and it skips ingest - an inline picture is note content, not
    a standalone thing to OCR, chunk, or summarize.
    """
    if not data:
        raise ValueError("empty file")

    digest = hashlib.sha256(data).hexdigest()
    suffix = Path(filename).suffix.lower()
    mime = mime or MIMES.get(suffix, "application/octet-stream")
    now = db.now()

    with db.transaction() as conn:
        existing = conn.execute(
            "SELECT id, deleted_at FROM artifacts WHERE content_hash = ?", (digest,)
        ).fetchone()
        if existing:
            if existing["deleted_at"]:
                # Re-adding something that sits in the trash is "keep this again": it
                # comes back whole and in front, exactly like re-saving something that
                # is still on the wall. A no-op against the trash row would read as a
                # save that never happened.
                conn.execute(
                    "UPDATE artifacts SET deleted_at = NULL, updated_at = ?" " WHERE id = ?",
                    (now, existing["id"]),
                )
                artifact_id = existing["id"]
                restored = True
            else:
                conn.execute(
                    "UPDATE artifacts SET updated_at = ? WHERE id = ?",
                    (now, existing["id"]),
                )
                return {"id": existing["id"], "created": False}
        else:
            blobstore.write(data, digest)

            artifact_id = str(uuid.uuid4())
            title = re.sub(r"[-_]+", " ", Path(filename).stem).strip() or filename
            conn.execute(
                "INSERT INTO artifacts (id, kind, title, body, content_hash, mime, filename,"
                " created_at, updated_at, local_only, status, embedded_at)"
                " VALUES (?,?,?,NULL,?,?,?,?,?,?,'text_only',?)",
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
                    now if embedded else None,
                ),
            )
            restored = False

    # Returns first, per hard rule 7. Extraction and indexing happen behind this -
    # but an embedded image is note content, not a standalone artifact, so it skips
    # ingest entirely (no OCR, chunking, or facets). It still pushes, so its row and
    # blob reach the other devices.
    if not embedded:
        ingest_queue.submit(artifact_id)
    push_artifact(artifact_id)
    out = {"id": artifact_id, "created": not restored}
    if restored:
        out["restored"] = True
    return out


class Blob:
    """An original file, read through blobstore (sealed on disk once the kit is saved)."""

    suffix = ""

    def __init__(self, content_hash: str):
        self.content_hash = content_hash

    def read_bytes(self) -> bytes:
        return blobstore.read(self.content_hash)

    def size(self) -> int:
        return blobstore.size(self.content_hash)

    @property
    def path(self) -> Path:
        return blobstore.path(self.content_hash)


def open_pdf(blob: Blob):
    """A PDF opened from its bytes, never from the (sealed) file on disk."""
    import fitz

    return fitz.open(stream=blob.read_bytes(), filetype="pdf")


def blob_path(artifact_id: str) -> tuple[Blob, str, str] | None:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT content_hash, mime, filename FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    if not row["content_hash"]:
        return None
    if not blobstore.exists(row["content_hash"]):
        # A blob captured on another device (e.g. a phone photo) lives only on the
        # relay until we fetch it. Pull it on demand, then serve from the local
        # cache like any other blob. Lazy import avoids a sync<->capture cycle.
        from .sync.client import fetch_blob_to_cache

        if not fetch_blob_to_cache(row["content_hash"]) or not blobstore.exists(
            row["content_hash"]
        ):
            return None
    return (
        Blob(row["content_hash"]),
        row["mime"] or "application/octet-stream",
        row["filename"] or artifact_id,
    )


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

    count = _count_pages(Blob(row["content_hash"])) if row["content_hash"] else None
    if count is not None:
        _remember_pages(artifact_id, count)
    return count


def _count_pages(blob: Blob) -> int | None:
    """Read the page count off the file itself. The slow path, taken once."""
    if not blobstore.exists(blob.content_hash):
        return None
    try:
        with open_pdf(blob) as doc:
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
        try:
            with open_pdf(path) as doc:
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

    hits: list[dict] = []
    try:
        with open_pdf(found[0]) as doc:
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
        with open_pdf(found[0]) as doc:
            if not 0 <= number < doc.page_count:
                return None
            page = doc.load_page(number)
            zoom = width / page.rect.width
            return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("png")
    except Exception:
        return None
