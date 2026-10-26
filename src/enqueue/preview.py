"""Finding out what a saved link actually is.

Saving a link fetches nothing. That is the right default: a request at capture time
would tell the publisher you read the thing, for every link you ever save, whether
or not you go back to it. The cost is that a link has no face, which makes the
home page a wall of URLs.

A preview is the deal that keeps the default and pays the cost only when it buys
something: one request, for one link, because the person asked for it.

Two rules hold this together.

1. **Nothing remote is ever referenced.** An `og:image` left as a URL and rendered in
   an `<img>` would fetch from the publisher on every view of that card, forever,
   which is worse than the single request the default was avoiding, and silent.
   So the picture is downloaded during this same fetch and stored in the ordinary
   blob store. What is kept is a content hash, never an address.
2. **The response is data, not instructions.** It is parsed for four fields, and
   where the page is an article its body is kept so the link is findable by what
   it says rather than by its metadata alone. Nothing from a page reaches a model
   except through the same secret scan and the same chunking every other artifact
   goes through.
"""

from __future__ import annotations

import contextlib
import os
import threading
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx

from . import blobstore, db, netguard
from .ingest import queue as ingest_queue

# Enough for any <head> worth reading. A page that has not declared itself by then
# is not going to, and the rest is a download nobody asked for.
MAX_BYTES = 512 * 1024
TIMEOUT = 10.0
MAX_REDIRECTS = 5

# The article body of a saved link is kept so the link is findable by what it says,
# not just by the four preview fields. Below this length the "body" is a landing
# page or a script shell, which would pollute the index with nothing worth finding.
BODY_MIN_CHARS = 200
_BODY_EXTRACTOR = "trafilatura"

# Honest and plain. Not a browser string: pretending to be Chrome to get better
# markup is the beginning of the crawler-evasion path this product does not take.
#
# Some publishers want a contact URL in the user agent before they will serve a
# non-browser client, and the way to satisfy that is to say who you are rather than to
# disguise the request. Set ENQ_USER_AGENT to something like
# "Enqueue/0.2 (+https://example.com/you)" if a publisher asks for one.
#
# This comment used to name Wikipedia as refusing the default user agent with a 403.
# That was wrong, and it sent a reader off to change a setting that would have fixed
# nothing. Interleaving the two clients against the same URL with the same string:
#
#   curl                200, every time
#   httpx over HTTP/1.1 403, every time    "Please respect our robot policy"
#   httpx over HTTP/2   200
#
# The discriminator is the TLS handshake, not the user agent: Wikimedia treats a client
# that does not negotiate h2 as a bot, because every browser negotiates it. So the fix
# is to speak the protocol everything else speaks, which is why HTTP/2 is enabled below.
#
# That is a protocol choice, not a disguise, and the difference is the whole line this
# product will not cross. The user agent stays honest and still says what this is; what
# changed is that we stopped sounding like 2012 on the wire. Matching a browser's TLS
# fingerprint to defeat detection would be the other thing, and it stays out.
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
IMAGE_KEYS = (("property", "og:image"), ("name", "twitter:image"), ("property", "og:image:url"))

# A preview picture is decoration. It is never worth a large download, and the cap is
# what stops a hostile or careless page turning one click into a hundred megabytes.
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# SVG is deliberately absent. It can carry script, and this file is served back from
# the engine's own origin, so an SVG preview would run in the same context as the
# app itself. A picture is not worth that.
IMAGE_MIMES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/avif": ".avif",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: str | None, limit: int = 500) -> str | None:
    if not value:
        return None
    collapsed = " ".join(value.split())
    return collapsed[:limit] or None


class PrivateAddress(httpx.RequestError):
    """The link, or a redirect it took, points into a private network."""


def _refuse_private(request: httpx.Request) -> None:
    """Refuse any request, a redirect included, whose host is not on the public internet.

    A saved link (or one synced from the phone) is fetched automatically, so without
    this a link to the router, another service on this machine, or the engine itself
    would be read from inside the network and its text stored as the link's body.
    httpx calls this before every request, so a public page that redirects inward is
    stopped too.
    """
    host = request.url.host
    if not netguard.is_public(host, request.url.port):
        raise PrivateAddress(f"{host} is not a public address", request=request)


def _read_capped(url: str) -> tuple[str, str]:
    """Return (content_type, text), never reading more than MAX_BYTES."""
    with (
        httpx.Client(
            follow_redirects=True,
            timeout=TIMEOUT,
            max_redirects=MAX_REDIRECTS,
            http2=True,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            event_hooks={"request": [_refuse_private]},
        ) as client,
        client.stream("GET", url) as response,
    ):
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
            content = tag.get("content") if tag else None
            if isinstance(content, str) and content:
                return _clean(content)
        return None

    title = meta(TITLE_KEYS)
    if not title and soup.title and soup.title.string:
        title = _clean(soup.title.string, limit=200)

    return {
        "title": _clean(title, limit=200),
        "description": meta(DESC_KEYS),
        "site_name": meta(SITE_KEYS) or urlparse(url).netloc.replace("www.", "") or None,
        # Absolute, because og:image is routinely a site-relative path and a relative
        # one would be resolved against the engine rather than the publisher.
        "image_url": urljoin(url, meta(IMAGE_KEYS)) if meta(IMAGE_KEYS) else None,
    }


def _fetch_image(url: str) -> tuple[str, str] | None:
    """Download a preview picture and store it. Returns (content_hash, mime).

    Stored locally so the card can be drawn without ever contacting the publisher
    again. Everything here is a limit: the type must be a real raster image, the size
    is capped, and nothing is written until the bytes have been seen.
    """

    if urlparse(url).scheme not in ("http", "https"):
        return None

    try:
        with (
            httpx.Client(
                follow_redirects=True,
                timeout=TIMEOUT,
                max_redirects=MAX_REDIRECTS,
                # Same protocol as the page fetch. A picture served from the same host that
                # just answered would otherwise be requested over a connection that host
                # has already decided it does not like.
                http2=True,
                headers={"User-Agent": USER_AGENT, "Accept": "image/*"},
                event_hooks={"request": [_refuse_private]},
            ) as client,
            client.stream("GET", url) as response,
        ):
            response.raise_for_status()
            mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if mime not in IMAGE_MIMES:
                return None

            chunks, total = [], 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    return None
                chunks.append(chunk)
        data = b"".join(chunks)
    except Exception:  # noqa: BLE001 - a missing picture is not a failed preview
        return None

    if not data:
        return None

    digest = blobstore.write(data)
    return digest, mime


def image(artifact_id: str) -> tuple[bytes, str] | None:
    """The stored picture for a link, as (bytes, mime)."""
    row = get(artifact_id)
    if not row or not row.get("image_hash") or not blobstore.exists(row["image_hash"]):
        return None
    return blobstore.read(row["image_hash"]), row.get("image_mime") or "application/octet-stream"


def _why(exc: Exception) -> str:
    """Turn a transport failure into a sentence.

    A stack-trace string in the interface tells the person nothing they can act on,
    and the three cases that actually happen have three different answers.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            # Two different causes wear this status, and guessing wrong costs a person
            # a configuration change that fixes nothing. Retrying is the cheaper test,
            # so it is named first.
            return "the site turned the preview away"
        if code == 429:
            return "the publisher is rate limiting; try later"
        if code == 404:
            return "that page is gone"
        return f"the publisher answered {code}"
    if isinstance(exc, PrivateAddress):
        return "that address is on a private network, and previews only fetch public pages"
    if isinstance(exc, httpx.TooManyRedirects):
        return "the address kept redirecting"
    if isinstance(exc, httpx.TimeoutException):
        return "the publisher did not answer in time"
    if isinstance(exc, httpx.TransportError):
        return "could not reach the publisher"
    return f"{type(exc).__name__}: {exc}"[:200]


def _extract_body(html: str, url: str) -> str:
    """The article body out of a page's HTML, or "" when there is no article.

    Pure, so it is testable without a network. A page that defeats extraction (a
    login wall, a JavaScript shell, a landing page) is not a failure; it is simply
    a link with nothing to say beyond its preview, and the preview metadata stays
    the whole of its indexable text.
    """
    import trafilatura

    try:
        text = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_links=False,
            include_tables=True,
            favor_recall=False,
        )
    except Exception:  # noqa: BLE001 - a page that defeats extraction is not a failure
        return ""
    if not text:
        return ""
    collapsed = "\n\n".join(line.strip() for line in text.splitlines() if line.strip())
    if len(collapsed) < BODY_MIN_CHARS:
        return ""
    return collapsed


def has_body(artifact_id: str) -> bool:
    """True when the fetched page's article body is stored and chunkable."""
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM page_text WHERE artifact_id = ? AND page = 0 AND extractor = ?",
            (artifact_id, _BODY_EXTRACTOR),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def needs_fetch(artifact_id: str) -> bool:
    """True when fetching would add something: no preview yet, or a preview that
    succeeded but never captured the article body.

    This is what lets an old link heal itself: it was previewed before bodies were
    kept, so it has metadata and no body, and the next pass through the ingest queue
    fetches it again and captures what it now can.
    """
    row = get(artifact_id)
    if row is None:
        return True
    if row["status"] != "ok":
        return False
    return not has_body(artifact_id) and not _body_tried(artifact_id)


# A page can be fetched perfectly and still have no article in it (an Instagram post,
# an app shell). Such a link used to count as "needs a fetch" forever, and since a
# fetch re-queues the artifact for ingest and ingest fetches whatever needs it, one
# such link fetched its page, re-ingested and re-pushed itself to the relay every
# second or two for as long as the engine ran (353 times in ten minutes, each one a
# request to the site and a sync to every other device). A fetch that found no body
# is now remembered, so the heal is tried once; "Try again" still forces a new one.
def _body_tried(artifact_id: str) -> bool:
    row = get(artifact_id)
    return bool(row and row.get("body_tried"))


def _mark_body_tried(conn, artifact_id: str, tried: bool) -> None:
    conn.execute(
        "UPDATE link_previews SET body_tried = ? WHERE artifact_id = ?",
        (1 if tried else 0, artifact_id),
    )


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
            " error, image_hash, image_mime, fetched_at) VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(artifact_id) DO UPDATE SET status=excluded.status,"
            " title=excluded.title, description=excluded.description,"
            " site_name=excluded.site_name, error=excluded.error,"
            " image_hash=excluded.image_hash, image_mime=excluded.image_mime,"
            " fetched_at=excluded.fetched_at",
            (
                artifact_id,
                fields["status"],
                fields.get("title"),
                fields.get("description"),
                fields.get("site_name"),
                fields.get("error"),
                fields.get("image_hash"),
                fields.get("image_mime"),
                _now(),
            ),
        )


# ---- the browser fallback -------------------------------------------------------
# Some publishers (Medium, behind its bot wall) refuse any client that is not a
# browser, whatever it says about itself: the plain request above gets a 403 every
# time. Such a page, or one with nothing to say until its scripts run, is opened once
# more in the Mac's own WebKit, off screen and in a process of its own
# (webkit_page.py), the way the person would open it in Safari. On by default (the
# `preview_browser` setting turns it off): it costs a few seconds per such link and
# nothing on the others.
#
# The line this does not cross is the one drawn at USER_AGENT above: a real browser
# loading a page is not a disguise, but faking one is. So it says it is WebKit, keeps
# no cookies, and a page that still refuses a real browser stays refused.
BROWSER_TIMEOUT_S = 30.0
# At most this many pages open at once (a browser per page is not free).
_BROWSERS = threading.BoundedSemaphore(2)


class BrowserMissing(RuntimeError):
    """This machine has no preview browser (it is not a Mac)."""


def browser_enabled() -> bool:
    from . import settings

    return str(settings.get("preview_browser") or "on").lower() in ("on", "1", "true")


def browser_available() -> bool:
    """Whether this machine can open a page in the preview browser (a Mac)."""
    from . import webkit_page

    return webkit_page.available()


def _read_browser(url: str) -> tuple[str, str]:
    """Return (content_type, html) for a page opened in the preview browser."""
    from . import webkit_page

    if not webkit_page.available():
        raise BrowserMissing("no preview browser on this machine")
    with _BROWSERS:
        code, html = webkit_page.read(url, BROWSER_TIMEOUT_S)
    if code >= 400:
        raise RuntimeError(f"the browser could not open the page ({code})")
    return "text/html", html[: MAX_BYTES * 4]


def _why_browser(exc: Exception) -> str:
    if isinstance(exc, BrowserMissing):
        return "this computer has no preview browser"
    if "(401)" in str(exc) or "(403)" in str(exc):
        return "the site turned the preview away, even in a browser"
    return "the site did not open in a browser either"


def _worth_a_browser(exc: Exception | None, fields: dict | None) -> bool:
    """Whether the plain fetch's outcome is one a real browser could plausibly fix:
    a refusal, or a page with nothing to say until its scripts run."""
    if exc is not None:
        return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (401, 403)
    return fields is not None and not (fields.get("title") or fields.get("description"))


def fetch(artifact_id: str) -> dict | None:
    """Make the one request. Raises KeyError if the artifact is not a saved link."""
    from .capture import is_placeholder_title
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

    fields: dict | None = None
    try:
        content_type, html = _read_capped(url)
    except Exception as exc:  # noqa: BLE001 - the reason is shown to the person, not raised
        if not (browser_enabled() and _worth_a_browser(exc, None)):
            _store(artifact_id, {"status": "failed", "error": _why(exc)})
            return get(artifact_id)
        html = ""
    else:
        if content_type and not content_type.startswith(("text/html", "application/xhtml")):
            _store(artifact_id, {"status": "failed", "error": f"not a web page ({content_type})"})
            return get(artifact_id)
        fields = parse(html, url)

    if fields is None or (browser_enabled() and _worth_a_browser(None, fields)):
        try:
            _, browser_html = _read_browser(url)
        except Exception as exc:  # noqa: BLE001 - the reason is shown to the person
            if fields is None:
                _store(artifact_id, {"status": "failed", "error": _why_browser(exc)})
                return get(artifact_id)
        else:
            html, fields = browser_html, parse(browser_html, url)
    assert fields is not None
    body_text = _extract_body(html, url)

    # One more request, inside the same act the person already chose, and then the
    # bytes are ours. A missing or refused picture is not a failed preview.
    image_url = fields.pop("image_url", None)
    if image_url:
        found_image = _fetch_image(image_url)
        if found_image:
            fields["image_hash"], fields["image_mime"] = found_image

    _store(artifact_id, {"status": "ok", **fields})

    with db.transaction() as conn:
        # The URL-derived title was a placeholder standing in until the page said its
        # own name. Replace it only if it is still that placeholder: a title the
        # person changed is theirs, and the page does not get to overrule it.
        if fields["title"] and is_placeholder_title(row["title"], url):
            conn.execute(
                "UPDATE artifacts SET title = ?, updated_at = ? WHERE id = ?",
                (fields["title"], _now(), artifact_id),
            )
        # The article body is kept so the link is findable by what it says, not just
        # by its four preview fields. Page 0 is the convention page_text uses for
        # text without real pages; the extractor name separates it from PDF pages.
        _mark_body_tried(conn, artifact_id, tried=not body_text)
        if body_text:
            conn.execute(
                "DELETE FROM page_text WHERE artifact_id = ? AND page = 0 AND extractor = ?",
                (artifact_id, _BODY_EXTRACTOR),
            )
            conn.execute(
                "INSERT INTO page_text (artifact_id, page, text, extractor) VALUES (?,0,?,?)",
                (artifact_id, body_text, _BODY_EXTRACTOR),
            )
        # Hard rule 6: scanned before this text can reach a model through chunking.
        _record_secrets(
            conn,
            artifact_id,
            "\n\n".join(
                filter(
                    None,
                    (
                        fields.get("title"),
                        fields.get("description"),
                        fields.get("site_name"),
                        body_text,
                    ),
                )
            ),
        )

    ingest_queue.submit(artifact_id)
    # The phone cannot fetch pages itself, so a fresh preview must travel: re-push the
    # artifact (the preview and its picture ride the snapshot). Best-effort, and it
    # keeps updated_at unless the title changed above, which already bumped it.
    with contextlib.suppress(Exception):
        from .sync.client import push_artifact

        push_artifact(artifact_id)
    return get(artifact_id)


def fetch_quietly(artifact_id: str) -> None:
    """Fetch in the background and swallow everything.

    Used on the automatic path, where nobody is waiting and a publisher that refuses
    is not worth interrupting a capture for. The row records the reason either way, so
    the artifact can still explain itself when it is opened.
    """
    with contextlib.suppress(Exception):
        fetch(artifact_id)


def auto_enabled() -> bool:
    from . import settings

    return str(settings.get("auto_preview") or "on").lower() not in ("off", "0", "false")


# An explicit "Try again" (or a bulk re-fetch) marks a link here, then submits it to
# the ingest worker. The worker refetches on the background thread - non-blocking, one
# request per saved link - bypassing the auto/needs_fetch gates the automatic path
# uses (a failed link is deliberately NOT auto-retried, but the person asked for this).
_forced_lock = threading.Lock()
_forced: set[str] = set()


def force(artifact_id: str) -> None:
    with _forced_lock:
        _forced.add(artifact_id)


def take_forced(artifact_id: str) -> bool:
    """Whether this artifact was explicitly forced, clearing the mark. One-shot."""
    with _forced_lock:
        if artifact_id in _forced:
            _forced.discard(artifact_id)
            return True
        return False


def text_for_index(artifact_id: str) -> str:
    """The preview as chunkable text, so a previewed link is findable by what it says."""
    row = get(artifact_id)
    if not row or row["status"] != "ok":
        return ""
    return "\n\n".join(filter(None, (row["title"], row["description"])))


def retry_refused_once() -> int:
    """One-shot: links whose preview failed before the WebKit preview browser are fetched
    once more, on the background lane, so they heal without a "Try again" each.

    Most of them are publishers that refused a plain request (Medium) or headless
    Chromium (the NYT, The Atlantic); WebKit opens them. Guarded by the
    `preview_webkit_retried` setting, so a link that still fails is not asked again.
    """
    from . import settings

    if settings.get("preview_webkit_retried") or not (browser_enabled() and browser_available()):
        return 0
    conn = db.get_conn()
    try:
        ids = [
            r[0]
            for r in conn.execute(
                "SELECT a.id FROM artifacts a JOIN link_previews p ON p.artifact_id = a.id"
                " WHERE a.kind = 'link' AND a.local_only = 0 AND a.deleted_at IS NULL"
                " AND a.vaulted_at IS NULL AND p.status = 'failed'"
            )
        ]
    finally:
        conn.close()
    for artifact_id in ids:
        force(artifact_id)
        ingest_queue.submit_background(artifact_id)
    settings.update({"preview_webkit_retried": True})
    return len(ids)
