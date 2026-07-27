"""Finding out what a saved link actually is.

Saving a link fetches nothing. That is the right default: a request at capture time
would tell the publisher you read the thing, for every link you ever save, whether
or not you go back to it. The cost is that a link has no face, which makes the
museum a wall of URLs.

A preview is the deal that keeps the default and pays the cost only when it buys
something: one request, for one link, because the person asked for it.

Two rules hold this together.

1. **Nothing remote is ever referenced.** Only text is stored. An `og:image` left as
   a URL and rendered in an `<img>` would fetch from the publisher on every view,
   forever, which is worse than the single request the default was avoiding.
2. **The response is data, not instructions.** It is parsed for four fields and the
   rest is discarded. Nothing from a page reaches a model except through the same
   secret scan and the same chunking every other artifact goes through.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from . import db
from .ingest import queue as ingest_queue

# Enough for any <head> worth reading. A page that has not declared itself by then
# is not going to, and the rest is a download nobody asked for.
MAX_BYTES = 512 * 1024
TIMEOUT = 10.0
MAX_REDIRECTS = 5

# Honest and plain. Not a browser string: pretending to be Chrome to get better
# markup is the beginning of the crawler-evasion path this product does not take.
#
# Some publishers require a contact URL in the user agent before they will serve a
# non-browser client. Wikipedia is one, and refuses this default with a 403. That is
# their policy working as intended, and the way to satisfy it is to say who you are,
# not to disguise the request. Set ENQ_USER_AGENT to something like
# "Enqueue/0.2 (+https://example.com/you)" if you want those pages to resolve.
USER_AGENT = os.getenv(
    "ENQ_USER_AGENT", "Enqueue/0.2 (personal link preview; one request per saved link)"
)

TITLE_KEYS = (("property", "og:title"), ("name", "twitter:title"))
DESC_KEYS = (
    ("property", "og:description"),
    ("name", "twitter:description"),
    ("name", "description"),
)
SITE_KEYS = (("property", "og:site_name"),)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: str | None, limit: int = 500) -> str | None:
    if not value:
        return None
    collapsed = " ".join(value.split())
    return collapsed[:limit] or None


def _read_capped(url: str) -> tuple[str, str]:
    """Return (content_type, text), never reading more than MAX_BYTES."""
    with httpx.Client(
        follow_redirects=True,
        timeout=TIMEOUT,
        max_redirects=MAX_REDIRECTS,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    ) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            header = response.headers.get("content-type", "")
            content_type = header.split(";")[0].strip()
            encoding = header.split("charset=")[-1].strip() if "charset=" in header else "utf-8"

            chunks, total = [], 0
            for chunk in response.iter_bytes():
                chunks.append(chunk)
                total += len(chunk)
                if total >= MAX_BYTES:
                    break
            raw = b"".join(chunks)[:MAX_BYTES]

    return content_type, raw.decode(encoding or "utf-8", errors="replace")


def parse(html: str, url: str) -> dict:
    """Pull the four fields out of a page. Pure, so it is testable without a network."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")

    def meta(keys) -> str | None:
        for attr, value in keys:
            tag = soup.find("meta", attrs={attr: value})
            if tag and tag.get("content"):
                return _clean(tag["content"])
        return None

    title = meta(TITLE_KEYS)
    if not title and soup.title and soup.title.string:
        title = _clean(soup.title.string, limit=200)

    return {
        "title": _clean(title, limit=200),
        "description": meta(DESC_KEYS),
        "site_name": meta(SITE_KEYS) or urlparse(url).netloc.replace("www.", "") or None,
    }


def _why(exc: Exception) -> str:
    """Turn a transport failure into a sentence.

    A stack-trace string in the interface tells the person nothing they can act on,
    and the three cases that actually happen have three different answers.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return (
                "the publisher refused an unidentified client; set ENQ_USER_AGENT "
                "to a user agent with a contact URL if you want this one"
            )
        if code == 429:
            return "the publisher is rate limiting; try later"
        if code == 404:
            return "that page is gone"
        return f"the publisher answered {code}"
    if isinstance(exc, httpx.TooManyRedirects):
        return "the address kept redirecting"
    if isinstance(exc, httpx.TimeoutException):
        return "the publisher did not answer in time"
    if isinstance(exc, httpx.TransportError):
        return "could not reach the publisher"
    return f"{type(exc).__name__}: {exc}"[:200]


def get(artifact_id: str) -> dict | None:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM link_previews WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _store(artifact_id: str, fields: dict) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO link_previews (artifact_id, status, title, description, site_name,"
            " error, fetched_at) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(artifact_id) DO UPDATE SET status=excluded.status,"
            " title=excluded.title, description=excluded.description,"
            " site_name=excluded.site_name, error=excluded.error,"
            " fetched_at=excluded.fetched_at",
            (
                artifact_id,
                fields["status"],
                fields.get("title"),
                fields.get("description"),
                fields.get("site_name"),
                fields.get("error"),
                _now(),
            ),
        )


def fetch(artifact_id: str) -> dict:
    """Make the one request. Raises KeyError if the artifact is not a saved link."""
    from .capture import title_from_url
    from .notes import _record_secrets

    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT kind, title, source_url, local_only FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise KeyError(artifact_id)
    if row["kind"] != "link" or not row["source_url"]:
        raise ValueError("only a saved link has a page to preview")
    if row["local_only"]:
        raise ValueError(
            "this link is local only, and fetching it would reach the network on its behalf"
        )

    url = row["source_url"]
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError(f"cannot fetch {urlparse(url).scheme or 'that'} links")

    try:
        content_type, html = _read_capped(url)
    except Exception as exc:  # noqa: BLE001 - the reason is shown to the person, not raised
        _store(artifact_id, {"status": "failed", "error": _why(exc)})
        return get(artifact_id)

    if content_type and not content_type.startswith(("text/html", "application/xhtml")):
        _store(artifact_id, {"status": "failed", "error": f"not a web page ({content_type})"})
        return get(artifact_id)

    fields = parse(html, url)
    _store(artifact_id, {"status": "ok", **fields})

    with db.transaction() as conn:
        # The URL-derived title was a placeholder standing in until the page said its
        # own name. Replace it only if it is still that placeholder: a title the
        # person changed is theirs, and the page does not get to overrule it.
        if fields["title"] and row["title"] == title_from_url(url):
            conn.execute(
                "UPDATE artifacts SET title = ?, updated_at = ? WHERE id = ?",
                (fields["title"], _now(), artifact_id),
            )
        # Hard rule 6: scanned before this text can reach a model through chunking.
        _record_secrets(conn, artifact_id, "\n".join(filter(None, fields.values())))

    ingest_queue.submit(artifact_id)
    return get(artifact_id)


def text_for_index(artifact_id: str) -> str:
    """The preview as chunkable text, so a previewed link is findable by what it says."""
    row = get(artifact_id)
    if not row or row["status"] != "ok":
        return ""
    return "\n\n".join(filter(None, (row["title"], row["description"])))
