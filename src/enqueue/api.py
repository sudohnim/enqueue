"""The engine's HTTP API.

All business logic lives behind this boundary. The CLI and the web view are both
clients of it, so the M1 shell has something to talk to on day one.

Binds to 127.0.0.1 only, on every milestone.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from importlib import resources

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel

from . import capture, chats, config, db, notes, preview, settings, trash
from .index.store import get_store
from .ingest import chunk as chunk_mod
from .ingest import facets as facets_mod
from .ingest import queue as ingest_queue
from .retrieve import lens as lens_mod

app = FastAPI(title="Enqueue engine", version="0.2.0")


font_dir = resources.files("enqueue").joinpath("static/fonts")


@app.get("/fonts/{name:path}")
async def serve_font(name: str) -> Response:
    font_path = os.path.join(str(font_dir), name)
    if not os.path.isfile(font_path):
        raise HTTPException(status_code=404, detail="font not found") from None
    return FileResponse(font_path, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/", response_class=HTMLResponse)
def museum() -> str:
    return resources.files("enqueue").joinpath("static/museum.html").read_text(encoding="utf-8")


@app.get("/capture", response_class=HTMLResponse)
def capture_window() -> str:
    return resources.files("enqueue").joinpath("static/capture.html").read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "artifacts": db.count("artifacts"),
        "versions": db.count("artifact_versions"),
        "chunks": db.count("chunks"),
        "facets": db.count("facets"),
        "chats": db.count("chats"),
    }


# --------------------------------------------------------------------------- read


def _excerpt(body: str, title: str, limit: int = 280) -> str:
    """The line under a title in the museum.

    A note's face is its own opening, so it is shown as prose rather than as source.
    Two things get in the way: the markdown characters, which are instructions and not
    words, and the opening heading, which is already the title directly above it.
    """
    lines = body.splitlines()
    if lines and lines[0].lstrip("#").strip() == title.strip():
        lines = lines[1:]

    text = " ".join(" ".join(lines).split())
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links keep their words
    text = re.sub(r"^[#>\s]+", "", text)
    text = re.sub(r"[*_`#]+", "", text)
    return text[:limit].strip()


class ArtifactFlags(BaseModel):
    pinned: bool | None = None
    local_only: bool | None = None


@app.patch("/artifacts/{artifact_id}")
def set_flags(artifact_id: str, req: ArtifactFlags) -> dict:
    """Flags only. An artifact's content is never edited through here."""
    try:
        changes = {k: int(v) for k, v in req.model_dump(exclude_none=True).items()}
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"flags must be integers: {exc}") from None
    if not changes:
        raise HTTPException(status_code=400, detail="nothing to change") from None

    sets = ", ".join(f"{k} = ?" for k in changes)
    with db.transaction() as conn:
        cur = conn.execute(
            f"UPDATE artifacts SET {sets} WHERE id = ?", (*changes.values(), artifact_id)
        )
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="no such artifact") from None
    return notes.get(artifact_id)


@app.delete("/artifacts/{artifact_id}")
def bin_artifact(artifact_id: str) -> dict:
    """Move to the trash. Reversible for as long as the retention window lasts."""
    try:
        return trash.delete(artifact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such artifact") from None


@app.post("/artifacts/{artifact_id}/restore")
def restore_artifact(artifact_id: str) -> dict:
    try:
        return trash.restore(artifact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such artifact") from None


@app.get("/trash")
def read_trash() -> dict:
    return trash.listing()


@app.delete("/trash/{artifact_id}")
def purge_artifact(artifact_id: str) -> dict:
    """Destroy one artifact for good. The only irreversible operation in the product."""
    try:
        return trash.purge(artifact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such artifact") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/trash/purge")
def purge_trash() -> dict:
    return trash.purge_expired()


@app.delete("/trash")
def empty_trash() -> dict:
    """Destroy everything waiting, now, without waiting out the window.

    Separate from `/trash/purge`, which only takes what has already expired. This one
    is the deliberate "I meant it" and the interface confirms before calling it.
    """
    return trash.empty()


@app.get("/artifacts/{artifact_id}/text")
def artifact_text(artifact_id: str) -> dict:
    """The readable text of an artifact, with page numbers when it has pages.

    This is what makes find-in-document possible for a PDF: the pages are rendered as
    images, so the browser has nothing to search until the text comes back separately.
    """
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT kind, body FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="no such artifact") from None

    # A capture has no body, so its text is whatever extraction found. A note is its
    # own text. Both come back in the same shape so the reader does not have to care.
    if row["kind"] in ("pdf", "file", "image"):
        return {"kind": row["kind"], "pages": capture.page_text(artifact_id)}
    return {"kind": row["kind"], "pages": [{"page": 0, "text": row["body"] or ""}]}


ORDERINGS = {
    # When it was last touched. This is the wall's default: saving, editing, or
    # annotating an artifact bumps `updated_at`, so the wall rises to what you
    # are working on. "Ingested" is the museum-shelf order, the order things
    # landed in; it stays available but is not the default. (The previous text
    # here claimed ingested was the default; the endpoint has always defaulted
    # to touched, and notes.py says the wall is ordered by last touch.)
    "ingested": "created_at DESC",
    "touched": "updated_at DESC",
    "title": "title COLLATE NOCASE ASC",
    # Relevance has no SQL ordering: there is no score column on the wall. The
    # control advertises it so the ordering control can express the lens mode;
    # POST /lens serves it, and the plain wall rejects it with a clear message.
    "relevance": None,
}


_ARTIFACT_COLUMNS = (
    "id, kind, title, body, source_url, mime, filename, created_at,"
    " updated_at, local_only, pinned, status, pages"
)


def _link_images(conn, link_ids: list[str]) -> set[str]:
    """Which of these links have a preview image. One query, no per-row opens."""
    if not link_ids:
        return set()
    # json_each keeps the IN clause fully parameterized: the ids travel as one
    # JSON string argument, never interpolated into the SQL text.
    return {
        r["artifact_id"]
        for r in conn.execute(
            "SELECT artifact_id FROM link_previews"
            " WHERE artifact_id IN (SELECT value FROM json_each(?))"
            " AND image_hash IS NOT NULL",
            (json.dumps(link_ids),),
        )
    }


def _wall_item(conn, row, with_image: set[str] | None = None) -> dict:
    """One wall row, with everything the client renders, no second call.

    The page-count lazy fill opens the PDF once, then writes the count back so
    no listing ever pays for that row again (the file cannot change, so the
    stored count cannot go stale).
    """
    item = dict(row)
    item["excerpt"] = _excerpt(item.pop("body") or "", row["title"])
    item["has_blob"] = row["mime"] is not None and row["kind"] != "link"
    if row["kind"] != "pdf":
        item.pop("pages", None)
    elif item["pages"] is None:
        item["pages"] = capture.page_count(row["id"])
    if row["kind"] == "link":
        item["has_preview_image"] = row["id"] in (with_image or set())
    return item


@app.get("/artifacts")
def list_artifacts(
    limit: int = 60,
    offset: int = 0,
    order: str = "touched",
    pinned: bool | None = None,
) -> dict:
    """Newest first, each with enough content to render rather than a blank.

    Nothing about where an artifact came from is returned. Import provenance is a
    folder by another name, and surfacing it would put the folder metaphor back into
    a product built to refuse it.
    """
    if order not in ORDERINGS:
        raise HTTPException(
            status_code=400, detail=f"order must be one of {sorted(ORDERINGS)}"
        ) from None
    if order == "relevance":
        # Relevance is not a SQL ordering: there is no score column on the wall. The
        # control advertises it, POST /lens serves it, and the plain wall says so.
        raise HTTPException(
            status_code=400, detail="relevance ordering needs a lens; use POST /lens"
        ) from None

    # `pinned` splits the wall into two shelves that are paged separately: the kept
    # few scroll sideways, everything else scrolls down. Without the filter the pinned
    # ones would appear in both.
    where = "deleted_at IS NULL"
    if pinned:
        where += " AND pinned = 1"
    elif pinned is not None:
        where += " AND pinned = 0"

    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, kind, title, body, source_url, mime, filename, created_at,"
            " updated_at, local_only, pinned, status, pages FROM artifacts"
            f" WHERE {where}"
            f" ORDER BY {ORDERINGS[order]} LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()

        with_image = _link_images(conn, [row["id"] for row in rows if row["kind"] == "link"])

        items = [_wall_item(conn, row, with_image) for row in rows]

        total = conn.execute(f"SELECT COUNT(*) AS n FROM artifacts WHERE {where}").fetchone()["n"]
        return {
            "total": total,
            "order": order,
            "offset": offset,
            # So the client knows whether to keep asking without guessing from a
            # short page, which is wrong exactly when the last page is full.
            "more": offset + len(items) < total,
            "items": items,
        }
    finally:
        conn.close()


class LensRequest(BaseModel):
    lens: str
    judge_top: int | None = None
    limit: int = 60
    offset: int = 0


@app.post("/lens")
def apply_lens_view(req: LensRequest) -> Response:
    """Split the wall into related and other for a topic, ephemerally, live.

    Returns a Server-Sent Events stream: the `split` event arrives as soon as
    stage one finishes, with both sections already bucketed by score and the
    candidates listed in `judging`; `judgment` events follow, one per
    artifact, carrying the placard and the final placement (`verdict` is
    belongs, no, or failed); `done` closes with the totals. The person sees
    the two sections before the model has spoken, and placards fill in as
    judgments arrive.

    The lens is stateless: nothing here writes an exhibit, bumps `updated_at`,
    or modifies any artifact (the judgment cache is the one table written, and
    that is its purpose). Clearing the lens is a client-side act - drop the
    lens state and re-request with the normal ordering; the wall returns to
    touched order because the lens left no trace.
    """
    return StreamingResponse(
        _lens_sse(req), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


def _lens_sse(req: LensRequest) -> Iterator[str]:
    for event in lens_mod.split_and_judge(req.lens, judge_top=req.judge_top):
        yield f"data: {json.dumps(event)}\n\n"


def _consume_lens(req: LensRequest) -> dict:
    """The synchronous reading of the lens stream, for callers (and tests)
    that want the final state in one dict rather than a stream of events."""
    result: dict = {}
    placements: dict[str, dict] = {}
    for event in lens_mod.split_and_judge(req.lens, judge_top=req.judge_top):
        if event["stage"] == "split":
            result = event
        elif event["stage"] == "judgment":
            placements[event["artifact_id"]] = event
        else:
            result.update(event)

    # Apply the judgments to the split: move verdicts into place, fill
    # placards, drop the stage-only fields, and page the two sections
    # independently, the way pinned and unpinned page on the wall.
    for entry in result["related"] + result["other"]:
        event = placements.get(entry["artifact_id"])
        if not event:
            continue
        if event["verdict"] == "belongs":
            entry.update(
                {
                    "judged": True,
                    "strength": event["strength"],
                    "placard": event["placard"],
                    "evidence": event["evidence"],
                }
            )
        elif event["verdict"] == "no":
            entry["judged"] = True
        else:
            entry["judged"] = False

    # Same fields the wall renders, so the client needs no second call.
    conn = db.get_conn()
    try:
        ids = [e["artifact_id"] for e in result["related"] + result["other"] + result["pinned"]]
        wall: dict[str, dict] = {}
        if ids:
            for r in conn.execute(
                f"SELECT {_ARTIFACT_COLUMNS} FROM artifacts"
                " WHERE id IN (SELECT value FROM json_each(?))",
                (json.dumps(ids),),
            ):
                wall[r["id"]] = _wall_item(
                    conn, r, _link_images(conn, [r["id"]] if r["kind"] == "link" else [])
                )
    finally:
        conn.close()

    for entry in result["related"] + result["other"] + result["pinned"]:
        entry.update(wall.get(entry["artifact_id"], {}))

    def page(items: list[dict]) -> tuple[list[dict], int, bool]:
        return (
            items[req.offset : req.offset + req.limit],
            len(items),
            req.offset + req.limit < len(items),
        )

    related, related_total, related_more = page(result["related"])
    other, other_total, other_more = page(result["other"])

    out = dict(result)
    for key in ("stage", "judging", "judge_total", "cache_hits"):
        out.pop(key, None)
    out.update(
        {
            "related": related,
            "related_total": related_total,
            "related_more": related_more,
            "other": other,
            "other_total": other_total,
            "other_more": other_more,
            "pinned": result["pinned"],
            "offset": req.offset,
            "limit": req.limit,
        }
    )
    return out


@app.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str) -> dict:
    try:
        detail = notes.get(artifact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such artifact") from None

    kind = detail["artifact"]["kind"]
    if kind in ("file", "image", "pdf"):
        found = capture.blob_path(artifact_id)
        detail["file"] = (
            {"bytes": found[0].stat().st_size, "mime": found[1], "name": found[2]}
            if found
            else None
        )
    if kind == "pdf":
        # The reader needs to know how many pages to expect before it can render one.
        detail["pages"] = capture.page_count(artifact_id)
    if kind == "link":
        detail["preview"] = preview.get(artifact_id)
    return detail


@app.get("/artifacts/{artifact_id}/versions/{version_id}")
def get_version(artifact_id: str, version_id: str) -> dict:
    body = notes.version_body(artifact_id, version_id)
    if body is None:
        raise HTTPException(status_code=404, detail="no such version") from None
    return {"id": version_id, "body": body}


@app.get("/artifacts/{artifact_id}/blob")
def get_blob(artifact_id: str):
    found = capture.blob_path(artifact_id)
    if found is None:
        raise HTTPException(status_code=404, detail="this artifact has no stored file") from None
    path, mime, filename = found
    return FileResponse(path, media_type=mime, filename=filename, content_disposition_type="inline")


@app.get("/artifacts/{artifact_id}/find")
def find_in_artifact(artifact_id: str, q: str) -> dict:
    """Where a phrase appears in a PDF, so the reader can draw over it.

    The pages are pictures, so the browser has no text to highlight of its own. These
    are the rectangles it needs, in page fractions rather than points.
    """
    return {"query": q, "hits": capture.find_in_pdf(artifact_id, q)}


@app.get("/artifacts/{artifact_id}/preview-image")
def get_preview_image(artifact_id: str):
    """A link's picture, served from here rather than from the publisher.

    This is the whole reason the bytes were downloaded: the card can be drawn as many
    times as you like without anyone learning you looked at it again.
    """
    found = preview.image(artifact_id)
    if found is None:
        raise HTTPException(status_code=404, detail="no picture for this link") from None
    path, mime = found
    return FileResponse(
        path,
        media_type=mime,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            # Belt and braces: content-addressed, type-checked on the way in, and
            # still told not to be sniffed into something executable.
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@app.get("/artifacts/{artifact_id}/page/{number}")
def get_page(artifact_id: str, number: int, width: int = 900):
    # A client that asks for a zero-width page has measured its layout too early. That
    # is a bug worth fixing on the client, and a blank reader is the wrong way to
    # report it, so the width is clamped to something renderable.
    width = max(120, min(width, 3000))
    png = capture.render_page(artifact_id, number, width=width)
    if png is None:
        raise HTTPException(status_code=404, detail="no such page") from None
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


# -------------------------------------------------------------------------- write


class NoteCreate(BaseModel):
    body: str = ""
    title: str | None = None
    local_only: bool = False


class BodyEdit(BaseModel):
    body: str
    title: str | None = None


class AnnotationCreate(BaseModel):
    text: str
    supersedes_id: str | None = None


class LinkCreate(BaseModel):
    url: str
    local_only: bool = False


@app.post("/notes", status_code=201)
def create_note(req: NoteCreate) -> dict:
    return notes.create(body=req.body, title=req.title, local_only=req.local_only)


@app.patch("/artifacts/{artifact_id}/body")
def edit_body(artifact_id: str, req: BodyEdit) -> dict:
    """Rewrite a note. Captures reject this: they have no editable body."""
    try:
        return notes.edit(artifact_id, req.body, title=req.title)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such artifact") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/artifacts/{artifact_id}/annotations", status_code=201)
def add_annotation(artifact_id: str, req: AnnotationCreate) -> dict:
    try:
        return notes.annotate(artifact_id, req.text, supersedes_id=req.supersedes_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such artifact") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/capture/link", status_code=201)
def capture_link(req: LinkCreate) -> dict:
    try:
        return capture.link(req.url, local_only=req.local_only)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.post("/capture/upload", status_code=201)
async def capture_upload(file: UploadFile = File(...), local_only: bool = Form(False)) -> dict:
    data = await file.read()
    try:
        return capture.upload(
            data, file.filename or "upload", mime=file.content_type, local_only=local_only
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.post("/artifacts/{artifact_id}/preview")
def fetch_preview(artifact_id: str) -> dict:
    """Make the one request this link never made at capture time.

    Explicit by design. Saving a link touches nothing; this is the person deciding
    that this particular link is worth telling its publisher about.
    """
    try:
        return preview.fetch(artifact_id) or {}
    except KeyError:
        raise HTTPException(status_code=404, detail="no such artifact") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


# ------------------------------------------------------------------------ derived


@app.post("/chunk")
def rebuild_chunks() -> dict:
    return chunk_mod.chunk_all()


@app.get("/lens-cache/stats")
def lens_cache_stats() -> dict:
    """How many judgments are remembered, across how many lenses."""
    from .retrieve import judgments

    return judgments.stats()


@app.post("/lens-cache/clear")
def lens_cache_clear() -> dict:
    """Forget every cached judgment. Returns the number of rows removed."""
    from .retrieve import judgments

    return {"cleared": judgments.clear()}


@app.post("/facet-gate")
def facet_gate() -> dict:
    return facets_mod.apply_eligibility_gate()


class FacetRequest(BaseModel):
    limit: int | None = None
    redo: bool = False


@app.post("/facets")
def generate_facets(req: FacetRequest) -> dict:
    return facets_mod.generate_all(limit=req.limit, redo=req.redo)


@app.post("/index")
def build_index() -> dict:
    from .index.store import get_store

    store = get_store()
    return {"chunks": store.upsert_chunks(), "facets": store.upsert_facets()}


@app.post("/reprocess")
def reprocess() -> dict:
    """Re-read, re-chunk, and re-index everything. Nothing authored is touched."""
    return {"queued": ingest_queue.submit_all()}


@app.post("/ingest/wait")
def ingest_wait(timeout: float = 60.0) -> dict:
    """Block until the ingest queue is drained. For scripts and tests, not the UI."""
    return {"idle": ingest_queue.wait_idle(timeout)}


@app.get("/index/counts")
def index_counts() -> dict:
    return get_store().counts()


# ------------------------------------------------------------------------- search


@app.get("/search")
def search(q: str, limit: int = 20) -> dict:
    store = get_store()
    hits = store.search(store.CHUNKS, q, limit=limit)
    conn = db.get_conn()
    try:
        out = []
        for hit in hits:
            row = conn.execute(
                "SELECT a.title, a.kind, c.text FROM chunks c"
                " JOIN artifacts a ON a.id = c.artifact_id WHERE c.id = ?",
                (hit["chunk_id"],),
            ).fetchone()
            if row:
                out.append(
                    {
                        "score": round(hit["score"], 4),
                        "artifact_id": hit["artifact_id"],
                        "title": row["title"],
                        "kind": row["kind"],
                        "snippet": " ".join(row["text"].split())[:200],
                    }
                )
        return {"query": q, "hits": out}
    finally:
        conn.close()


# --------------------------------------------------------------------------- chats


class ChatCreate(BaseModel):
    scope_kind: str = "everything"
    scope_id: str | None = None
    text: str | None = None


class ChatSend(BaseModel):
    text: str


class ChatEdit(BaseModel):
    title: str | None = None
    pinned: bool | None = None


@app.get("/chats")
def list_chats(limit: int = 40) -> dict:
    return chats.listing(limit=limit)


@app.get("/chats/ready")
def chat_ready() -> dict:
    """Whether there is anything to answer from. Distinguishes the empty cases."""
    return chats.readiness()


@app.get("/chats/passages")
def chat_passages(q: str, scope_kind: str = "everything", scope_id: str | None = None) -> dict:
    """Exactly what an answer to this question would be allowed to read.

    An answer is only ever as good as this list, so it is inspectable. When the
    curator says the collection holds nothing, this is how you tell a retrieval
    failure from an honest one.
    """
    found = chats.passages(q, scope_kind, scope_id)
    return {
        "query": q,
        "passages": [
            {
                "artifact_id": p["artifact_id"],
                "title": p["title"],
                "why": p.get("why"),
                "score": p.get("score"),
                "excerpt": " ".join(p["text"].split())[:240],
            }
            for p in found
        ],
    }


@app.post("/chats", status_code=201)
def create_chat(req: ChatCreate) -> dict:
    try:
        made = chats.create(scope_kind=req.scope_kind, scope_id=req.scope_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    if req.text:
        return send_to_chat(made["chat"]["id"], ChatSend(text=req.text))
    return made


@app.get("/chats/{chat_id}")
def get_chat(chat_id: str) -> dict:
    try:
        return chats.get(chat_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such chat") from None


@app.post("/chats/{chat_id}/messages")
def send_to_chat(chat_id: str, req: ChatSend) -> dict:
    try:
        return chats.send(chat_id, req.text)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such chat") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as exc:  # noqa: BLE001 - a model failure is a 503, not a crash
        raise HTTPException(
            status_code=503, detail=f"the curator could not answer: {exc}"
        ) from None


@app.patch("/chats/{chat_id}")
def edit_chat(chat_id: str, req: ChatEdit) -> dict:
    try:
        result = chats.get(chat_id)
        if req.pinned is not None:
            result = chats.pin(chat_id, req.pinned)
        if req.title is not None:
            result = chats.rename(chat_id, req.title)
        return result
    except KeyError:
        raise HTTPException(status_code=404, detail="no such chat") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.delete("/chats/{chat_id}")
def delete_chat(chat_id: str) -> dict:
    try:
        return chats.delete(chat_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such chat") from None


class CurateRequest(BaseModel):
    lens: str
    keep: int = 15
    pool: int = 150
    save: bool = False


@app.post("/curate")
def curate(req: CurateRequest) -> dict:
    from .retrieve.curate import curate as run

    return run(req.lens, keep=req.keep, pool=req.pool, save=req.save)


class ExhibitSave(BaseModel):
    """A room that was already built, being kept.

    Curating costs three model passes. Re-running it just to set a flag would make
    keeping a room as expensive as making one, so the result comes back and is saved
    as it stands.
    """

    lens: str
    exhibit: dict
    kept: list[dict]


@app.post("/exhibits", status_code=201)
def save_exhibit(req: ExhibitSave) -> dict:
    from .retrieve.curate import save as run_save

    try:
        return {"id": run_save(req.lens, req.exhibit, req.kept)}
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.get("/exhibits")
def list_exhibits() -> dict:
    conn = db.get_conn()
    try:
        rows = conn.execute("SELECT * FROM exhibits ORDER BY created_at DESC").fetchall()
        return {"items": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.get("/exhibits/{exhibit_id}")
def get_exhibit(exhibit_id: str) -> dict:
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM exhibits WHERE id = ?", (exhibit_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="no such exhibit") from None
        members = conn.execute(
            "SELECT m.artifact_id, m.placard, m.strength, m.rank, a.title, a.kind"
            " FROM exhibit_members m JOIN artifacts a ON a.id = m.artifact_id"
            " WHERE m.exhibit_id = ? AND m.ejected_at IS NULL ORDER BY m.rank",
            (exhibit_id,),
        ).fetchall()
        return {"exhibit": dict(row), "members": [dict(m) for m in members]}
    finally:
        conn.close()


@app.get("/settings")
def read_settings() -> dict:
    return {
        "settings": settings.all_settings(),
        "storage": settings.storage(),
        "backends": settings.backends(),
    }


class SettingsUpdate(BaseModel):
    changes: dict


class ApiKey(BaseModel):
    key: str


@app.put("/settings/api-key")
def store_api_key(req: ApiKey) -> dict:
    """Put the key in the macOS Keychain. It is never written to settings.json.

    The body is not logged and the value is never returned: what comes back is only
    whether a key now exists and its last four characters.
    """
    from . import keyring

    try:
        keyring.set(req.key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return settings.api_key_state()


@app.delete("/settings/api-key")
def forget_api_key() -> dict:
    from . import keyring

    keyring.clear()
    return settings.api_key_state()


@app.patch("/settings")
def write_settings(req: SettingsUpdate) -> dict:
    try:
        return {"settings": settings.update(req.changes), "storage": settings.storage()}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.get("/secrets")
def secret_report() -> dict:
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT a.id, a.title, s.kind, s.line, s.excerpt FROM secret_hits s"
            " JOIN artifacts a ON a.id = s.artifact_id ORDER BY a.title"
        ).fetchall()
        return {"count": len(rows), "hits": [dict(r) for r in rows]}
    finally:
        conn.close()


def serve() -> None:
    import uvicorn

    try:
        expired = trash.purge_expired()
        if expired["purged"]:
            print(f"[engine] purged {expired['purged']} artifact(s) past the trash window")
    except Exception as exc:  # noqa: BLE001 - never block startup on housekeeping
        print(f"[engine] could not purge the trash: {exc}")

    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT, log_level="warning")
