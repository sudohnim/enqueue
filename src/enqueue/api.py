"""The engine's HTTP API.

All business logic lives behind this boundary. The CLI and the web view are both
clients of it, so the M1 shell has something to talk to on day one.

Binds to 127.0.0.1 only, on every milestone.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator

# nosemgrep: python.lang.compatibility.python37.python37-compatibility-importlib2
from importlib import resources

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel

from . import (
    capture,
    chats,
    chats_worker,
    config,
    db,
    derive,
    greeting,
    notes,
    pivot,
    pivots_saved,
    preview,
    settings,
    trash,
)
from . import tags as tags_mod
from .index.store import get_store
from .ingest import chunk as chunk_mod
from .ingest import facets as facets_mod
from .ingest import queue as ingest_queue
from .retrieve import lens as lens_mod

app = FastAPI(title="Enqueue engine", version="0.2.0")


font_dir = resources.files("enqueue").joinpath("static/fonts")
static_dir = resources.files("enqueue").joinpath("static")


@app.get("/fonts/{name:path}")
async def serve_font(name: str) -> Response:
    font_path = os.path.join(str(font_dir), name)
    if not os.path.isfile(font_path):
        raise HTTPException(status_code=404, detail="font not found") from None
    return FileResponse(font_path, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/static/{name:path}")
async def serve_static(name: str) -> Response:
    # The one static asset the pages reference by path (eyeball.png, N.14). The
    # guard keeps the route honest: only real files inside the static dir, never
    # a ".." escape or a directory listing.
    target = os.path.realpath(os.path.join(str(static_dir), name))
    if not os.path.isfile(target) or not target.startswith(str(static_dir) + os.sep):
        raise HTTPException(status_code=404, detail="no such static file") from None
    return FileResponse(target)


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


def _excerpt(body: str, title: str, limit: int = 600) -> str:
    """The opening of a note, kept as markdown so the wall renders its structure.

    The face is the note's own opening, not a paraphrase: a bullet list stays a
    bullet list and a paragraph keeps its line breaks. The opening heading is
    dropped because the card title above it already carries that line. The slice
    stops at a line boundary so no list item or sentence is cut mid-line; the
    client renders the slice with the same markdown renderer the editor uses.
    """
    lines = body.splitlines()
    if lines and lines[0].lstrip("#").strip() == title.strip():
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines.pop(0)

    out: list[str] = []
    used = 0
    for ln in lines:
        used += len(ln) + 1
        if used > limit and out:
            break
        out.append(ln)
    return "\n".join(out).strip()


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
        # `changes` keys come from the ArtifactFlags model (pinned/local_only only),
        # so the SET list is assembled from allowlisted literals, never input.
        # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query,python.lang.security.audit.formatted-sql-query.formatted-sql-query
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


def _wall_tags(conn, artifact_ids: list[str]) -> dict[str, list[str]]:
    """All tags for a batch of artifacts, one query, name lists per id.

    The wall's Tags grouping needs every row's tags up front (an artifact can
    sit under several shelves), so the batch comes back as id -> names and
    `_wall_item` copies its slice into the row.
    """
    if not artifact_ids:
        return {}
    rows = conn.execute(
        "SELECT at.artifact_id, t.name FROM artifact_tags at"
        " JOIN tags t ON t.id = at.tag_id"
        " WHERE at.artifact_id IN (SELECT value FROM json_each(?))",
        (json.dumps(sorted(set(artifact_ids))),),
    ).fetchall()
    out: dict[str, list[str]] = {}
    for row in rows:
        out.setdefault(row["artifact_id"], []).append(row["name"])
    return out


def _wall_item(
    conn, row, with_image: set[str] | None = None, with_tags: dict[str, list[str]] | None = None
) -> dict:
    """One wall row, with everything the client renders, no second call.

    The page-count lazy fill opens the PDF once, then writes the count back so
    no listing ever pays for that row again (the file cannot change, so the
    stored count cannot go stale). Tags ride along for the wall's Tags
    grouping; conversations cannot be tagged, so their slice is always empty.
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
    item["tags"] = (with_tags or {}).get(row["id"], [])
    return item


@app.get("/artifacts")
def list_artifacts(
    limit: int = 60,
    offset: int = 0,
    order: str = "touched",
    pinned: bool | None = None,
    tags: str = "",
) -> dict:
    """Newest first, each with enough content to render rather than a blank.

    Nothing about where an artifact came from is returned. Import provenance is a
    folder by another name, and surfacing it would put the folder metaphor back into
    a product built to refuse it.

    `tags` is a comma-separated filter: only artifacts carrying ALL of the named
    tags come back. Conversations cannot be tagged, so a tag filter drops the
    chats limb entirely - a filtered wall is an artifact wall.
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

    # A tag filter is AND semantics across the names, and it applies to artifacts
    # only. The ids are bound with the json_each IN pattern; the filter is part of
    # the artifacts WHERE, and the chats limb below is dropped when it is active.
    tag_names = [tags_mod.normalize(t) for t in tags.split(",") if t.strip()] if tags else []
    tag_ids = tags_mod.ids_with_all(tag_names) if tag_names else None
    if tag_ids is not None:
        where += " AND id IN (SELECT value FROM json_each(:tag_ids))"
    tag_ids_param = json.dumps(sorted(tag_ids)) if tag_ids is not None else None

    # A conversation is the same kind of thing on the wall as a capture: something
    # you come back to, ordered by when you last touched it. So it lives in the same
    # list, sorted by the same clock - never ahead of everything else, which is what
    # made a fresh capture land behind a conversation nobody touched this week.
    # `pinned` filters it the same way it filters artifacts: kept conversations sit
    # on the saved shelf, the rest join the wall. The NULL-or-match test keeps the
    # query parameterized whether or not the filter is applied; named parameters,
    # because SQLite renumbers anonymous `?` placeholders across a UNION's limbs.
    # A tag filter excludes the chats limb: conversations cannot be tagged.
    chats_limb = (
        (
            " UNION ALL"
            " SELECT id, 'chat', title, NULL, NULL, NULL, NULL, created_at,"
            " updated_at, 0, pinned, NULL, NULL FROM chats"
            " WHERE (:pinned IS NULL OR pinned = :pinned)"
        )
        if tag_ids is None
        else ""
    )

    conn = db.get_conn()
    try:
        # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query,python.lang.security.audit.formatted-sql-query.formatted-sql-query
        # `where` and `chats_limb` are assembled only from allowlisted literals
        # plus one fully parameterized json_each clause; tag names and pinned
        # travel as bound parameters, never in the SQL text.
        rows = conn.execute(
            "SELECT id, kind, title, body, source_url, mime, filename, created_at,"
            " updated_at, local_only, pinned, status, pages FROM artifacts"
            f" WHERE {where}"
            f"{chats_limb}"
            f" ORDER BY {ORDERINGS[order]} LIMIT :limit OFFSET :offset",
            {
                "pinned": pinned,
                "limit": limit,
                "offset": offset,
                "tag_ids": tag_ids_param,
            },
        ).fetchall()

        with_image = _link_images(conn, [row["id"] for row in rows if row["kind"] == "link"])
        with_tags = _wall_tags(conn, [row["id"] for row in rows if row["kind"] != "chat"])

        items = [_wall_item(conn, row, with_image, with_tags) for row in rows]
        for item in items:
            if item["kind"] == "chat":
                # A conversation's face is its kind: the title is the thread's name
                # and the excerpt is the fixed label, the same as any other card.
                item["excerpt"] = "conversation"

        # `where` is assembled only from allowlisted literals plus one
        # fully parameterized json_each clause; tag names and pinned
        # travel as bound parameters, never in the SQL text.
        # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query,python.lang.security.audit.formatted-sql-query.formatted-sql-query
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM artifacts WHERE {where}",
            {"tag_ids": tag_ids_param},
        ).fetchone()["n"]
        if tag_ids is None:
            total += conn.execute(
                "SELECT COUNT(*) AS n FROM chats WHERE (:pinned IS NULL OR pinned = :pinned)",
                {"pinned": pinned},
            ).fetchone()["n"]
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

    The lens is stateless: nothing here writes anything, bumps `updated_at`,
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
            with_tags = _wall_tags(conn, ids)
            for r in conn.execute(
                f"SELECT {_ARTIFACT_COLUMNS} FROM artifacts"
                " WHERE id IN (SELECT value FROM json_each(?))",
                (json.dumps(ids),),
            ):
                wall[r["id"]] = _wall_item(
                    conn,
                    r,
                    _link_images(conn, [r["id"]] if r["kind"] == "link" else []),
                    with_tags,
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
    detail["tags"] = tags_mod.for_artifact(artifact_id)

    # Saved-view membership: which saved pivots include this artifact. The spec
    # is stored as JSON with an `included_ids` list; the saved-pivot count is
    # small (tens at most) and this endpoint is per-artifact (low volume), so a
    # Python-side filter is fine - no SQL needed for this read-only join.
    views = []
    for p in pivots_saved.listing():
        try:
            saved = pivots_saved.get(p["id"])
        except (KeyError, ValueError):
            continue
        spec = saved["spec"]
        included = set(spec.get("included_ids") or [])
        excluded = set(spec.get("excluded_ids") or [])
        # Mirror pivot.run's membership: an explicit exclusion beats an
        # inclusion, so a chip the user just X'd out of (which excludes the id)
        # must disappear on re-render.
        if artifact_id in included and artifact_id not in excluded:
            views.append({"id": p["id"], "name": p["name"]})
    detail["views"] = sorted(views, key=lambda v: v["name"])
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


class TagCreate(BaseModel):
    name: str


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


@app.post("/artifacts/{artifact_id}/tags", status_code=201)
def add_tag(artifact_id: str, req: TagCreate) -> dict:
    """Attach a tag. A tag is an optional, later act on an artifact that exists."""
    try:
        return tags_mod.add(artifact_id, req.name)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such artifact") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.delete("/artifacts/{artifact_id}/tags/{name}")
def remove_tag(artifact_id: str, name: str) -> dict:
    """Detach a tag by its canonical name."""
    try:
        return tags_mod.remove(artifact_id, name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.get("/tags")
def get_tags() -> dict:
    """Every tag with its artifact count, most-used first."""
    return {"tags": tags_mod.cloud()}


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
    stale_only: bool = False


@app.post("/facets")
def generate_facets(req: FacetRequest) -> dict:
    return facets_mod.generate_all(limit=req.limit, redo=req.redo, stale_only=req.stale_only)


@app.post("/index")
def build_index() -> dict:
    from .index import bootstrap

    # Rebuild synchronously through the lifecycle: search is blocked for the
    # duration and re-enabled only after the version is written.
    return bootstrap.rebuild_now()


@app.post("/reprocess")
def reprocess() -> dict:
    """Re-read, re-chunk, and re-index everything. Nothing authored is touched."""
    return {"queued": ingest_queue.submit_all()}


@app.post("/reprocess-images")
def reprocess_images() -> dict:
    """Re-queue every image for the vision describe step (K.11).

    The catch-up for images captured before the vision step existed: each one
    without a description gets one, then flows through chunk, facet, and index
    like any other artifact.
    """
    return {"queued": ingest_queue.submit_images()}


@app.post("/ingest/wait")
def ingest_wait(timeout: float = 60.0) -> dict:
    """Block until the ingest queue is drained. For scripts and tests, not the UI."""
    return {"idle": ingest_queue.wait_idle(timeout)}


@app.get("/index/counts")
def index_counts() -> dict:
    return get_store().counts()


@app.get("/doctor")
def doctor() -> dict:
    """Index health: counts, embedding version, and chunks-table sync.

    A diagnostic for the cutover. `index_in_sync` is true when the search
    index holds exactly as many chunk rows as the chunks table (the trash
    path deletes a chunk row and drops its index point together, so a synced
    index stays synced across deletes). `embed_version_current` is true when
    the recorded version matches the running embedding model. `healthy` is
    both. The raw `index_counts` cover all six index tables, so an FTS,
    facets, or entities drift is visible even when the chunks count matches.
    """
    from .index import bootstrap

    index_counts = get_store().counts()
    chunk_count = db.count("chunks")
    embed_version = bootstrap.read_embed_version()
    index_chunks = index_counts.get("chunks")
    in_sync = index_chunks is not None and index_chunks == chunk_count
    version_current = embed_version == config.EMBED_VERSION
    index_state = bootstrap.index_state()
    state_ready = index_state["state"] == "ready"
    return {
        "artifact_count": db.count("artifacts"),
        "chunk_count": chunk_count,
        "facet_count": db.count("facets"),
        "index_counts": index_counts,
        "embed_version": embed_version,
        "embed_version_current": version_current,
        "index_state": index_state["state"],
        "index_progress": index_state["progress"],
        "index_in_sync": in_sync,
        "healthy": in_sync and version_current and state_ready,
    }


# ------------------------------------------------------------------------- search


@app.get("/search")
def search(q: str, limit: int = 20) -> dict:
    from .index import bootstrap
    from .retrieve.candidates import search_results

    if not bootstrap.search_allowed():
        # The index is missing, rebuilding, or built with a different embedding
        # version. Serving results now would silently differ from another
        # device's results (Phase 21): block instead, and never fall back.
        raise HTTPException(
            status_code=503,
            detail="Updating your search index. This will take a moment.",
        )
    # Chunk and facet hits rolled up to one row per artifact (deduplicated),
    # so an artifact whose six chunks match does not occupy every slot.
    return {"query": q, "hits": search_results(q, limit=limit)}


# --------------------------------------------------------------------------- chats


class ChatCreate(BaseModel):
    scope_kind: str = "everything"
    scope_id: str | None = None
    text: str | None = None


class ChatSend(BaseModel):
    text: str
    # Rule 2's server side: the UI re-sends the same text with skill="answer"
    # to leave a routed (non-answer) turn and get a plain answer.
    skill: str | None = None


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
    if req.text:
        # Submitting returns immediately with a visible pending turn; the answer
        # worker computes it in the background and fills the turn in place. A model
        # failure resolves the turn to 'failed' - the chat and the question stay.
        try:
            return chats.ask(req.text, scope_kind=req.scope_kind, scope_id=req.scope_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except Exception as exc:  # noqa: BLE001 - any other submit failure is a 503
            raise HTTPException(
                status_code=503, detail=f"could not submit the question: {exc}"
            ) from None

    try:
        made = chats.create(scope_kind=req.scope_kind, scope_id=req.scope_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
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
        return chats.send(chat_id, req.text, force_skill=req.skill)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such chat") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as exc:  # noqa: BLE001 - any other submit failure is a 503
        raise HTTPException(
            status_code=503, detail=f"could not submit the question: {exc}"
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


@app.post("/curate")
def curate(req: CurateRequest) -> dict:
    from .retrieve.curate import curate as run

    return run(req.lens, keep=req.keep, pool=req.pool)


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
@app.get("/greeting")
def get_greeting() -> dict:
    """The wall's greeting for the current four-hour bucket, cached or fallback.

    Never blocks on the model: a missing phrase returns the time-based fallback
    and starts a background generation for the bucket.
    """
    return greeting.get()


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


class PivotPlanRequest(BaseModel):
    request: str


@app.post("/pivot/plan")
def plan_pivot(req: PivotPlanRequest) -> dict:
    """Turn a natural-language request into a pivot spec, in one planner call.

    The returned spec is a plain dict the client can send straight back to
    POST /pivot/run. A request the planner cannot turn into a runnable spec
    comes back as a 400 with a sentence the UI can show, never a traceback.
    """
    try:
        return {"spec": pivot.plan(req.request)}
    except pivot.PivotError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


class PivotRunRequest(BaseModel):
    spec: dict


@app.post("/pivot/run")
def run_pivot(req: PivotRunRequest) -> dict:
    """Run a pivot spec and return each group's cards, no second round trip.

    The groups come back exactly as pivot.run produced them (key, artifact_ids,
    grounded, largest first) with each group's artifact_ids hydrated into wall
    items so the client renders cards without a second call. `grounded` and
    `truncated` stay in the response: an enrich step means the grouping uses
    the assistant's knowledge rather than the notes' own text, and a truncated
    subset means the largest groups may not be the complete picture.
    """
    result = pivot.run(req.spec)

    conn = db.get_conn()
    try:
        ids = [aid for group in result["groups"] for aid in group["artifact_ids"]]
        wall: dict[str, dict] = {}
        if ids:
            rows = conn.execute(
                f"SELECT {_ARTIFACT_COLUMNS} FROM artifacts"
                " WHERE id IN (SELECT value FROM json_each(?))",
                (json.dumps(ids),),
            ).fetchall()
            with_image = _link_images(conn, [row["id"] for row in rows if row["kind"] == "link"])
            with_tags = _wall_tags(conn, [row["id"] for row in rows])
            for row in rows:
                wall[row["id"]] = _wall_item(conn, row, with_image, with_tags)
    finally:
        conn.close()

    for group in result["groups"]:
        group["items"] = [wall.get(aid, {}) for aid in group["artifact_ids"]]
    return result


class PivotAddableRequest(BaseModel):
    spec: dict


@app.post("/pivot/addable")
def pivot_addable(req: PivotAddableRequest) -> dict:
    """The artifacts a pivot could still take in (N.3a/N.3b add flow).

    The picker must offer only artifacts the view does not already contain: a
    run covers its subset's matches minus exclusions plus inclusions, so an
    artifact already covered is a no-op add (the client used to list the whole
    library and every pick of a covered artifact toasted "already in this
    view" - real, but useless). This resolves the covered set without running
    the step chain (pure SQL, no model calls) and returns the rest. A view
    whose subset covers everything comes back empty, and the picker says
    "Nothing left to add." instead of pretending a pick would do something.
    """
    spec = req.spec
    try:
        ids, _ = pivot.resolve_subset(spec.get("subset") or {"kind": "search", "value": ""})
    except (KeyError, ValueError):
        # A stale or hand-built spec must not 500 the picker; treat it as
        # covering nothing so the view stays addable.
        ids = []
    excluded = set(spec.get("excluded_ids") or [])
    included = set(spec.get("included_ids") or [])
    in_view = set(ids) - excluded | included

    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, title FROM artifacts"
            " WHERE kind != 'chat' ORDER BY updated_at DESC LIMIT 200"
        ).fetchall()
    finally:
        conn.close()
    return {
        "items": [
            {"id": row["id"], "title": row["title"]} for row in rows if row["id"] not in in_view
        ]
    }


class DerivedOverrideRequest(BaseModel):
    scope: str
    subject: str
    attribute: str
    value: str


@app.post("/derived/override")
def derived_override(req: DerivedOverrideRequest) -> dict:
    """Write a user correction for a derived value and return the stored row.

    The correction is stored with source='user', which always wins over the
    model row on read (rule 2: the director beats the curator), so re-running
    the same pivot shows the corrected value. This is how a misfiled item gets
    moved to the right group; it must stay visible because a misfiled item is
    otherwise invisible.
    """
    return derive.override(req.scope, req.subject, req.attribute, req.value)


class SavePivotRequest(BaseModel):
    name: str
    spec: dict


@app.post("/pivots")
def save_pivot(req: SavePivotRequest) -> dict:
    """Save a grouping under a name and return its id.

    The spec is the arrangement's recipe, stored as-is; opening it later re-runs
    it live (POST /pivot/run), so the grouping stays true as the library grows
    rather than freezing into a snapshot. A missing name is a 400, not a 500.
    """
    try:
        return {"id": pivots_saved.save(req.name, req.spec)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.get("/pivots")
def list_pivots() -> dict:
    """Every saved grouping, newest first, name and date only (no spec)."""
    return {"items": pivots_saved.listing()}


@app.get("/pivots/{pivot_id}")
def get_pivot(pivot_id: str) -> dict:
    """One saved grouping with its spec, ready to send to POST /pivot/run."""
    try:
        return pivots_saved.get(pivot_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No saved grouping by that id.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


class PivotRename(BaseModel):
    name: str


@app.patch("/pivots/{pivot_id}")
def rename_pivot(pivot_id: str, req: PivotRename) -> dict:
    """Rename a saved grouping (the pencil beside its name in the custom wall).

    The name is trimmed and must not be empty; the spec (the arrangement) is
    untouched. 404 on an unknown grouping, 400 on an empty name.
    """
    try:
        updated = pivots_saved.rename(pivot_id, req.name)
    except KeyError:
        raise HTTPException(status_code=404, detail="No saved grouping by that id.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"pivot": updated}


@app.delete("/pivots/{pivot_id}")
def delete_pivot(pivot_id: str) -> dict:
    """Forget a saved grouping. Idempotent: deleting one already gone still 200s."""
    pivots_saved.delete(pivot_id)
    return {"deleted": pivot_id}


class PivotExclude(BaseModel):
    artifact_id: str
    undo: bool = False


@app.post("/pivots/{pivot_id}/exclude")
def exclude_pivot_artifact(pivot_id: str, req: PivotExclude) -> dict:
    """Exclude (or, with undo, restore) one artifact in a saved grouping.

    A saved grouping is a computed pivot: its members are whatever the spec
    produces over the current library, so removing a card means excluding its id
    from the spec. This reads the stored spec, appends `artifact_id` to
    `excluded_ids` (or removes it when `undo` is true), and saves it back; the
    next re-run of the grouping leaves the artifact out. The artifact itself is
    never touched - it still lives on the wall and in the library.
    """
    try:
        saved = pivots_saved.get(pivot_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No saved grouping by that id.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    spec = saved["spec"]
    excluded = [aid for aid in (spec.get("excluded_ids") or []) if aid != req.artifact_id]
    if not req.undo:
        excluded.append(req.artifact_id)
    spec["excluded_ids"] = excluded
    pivots_saved.update_spec(pivot_id, spec)
    return {"pivot_id": pivot_id, "excluded_ids": excluded}


class PivotInclude(BaseModel):
    artifact_id: str
    undo: bool = False


@app.post("/pivots/{pivot_id}/include")
def include_pivot_artifact(pivot_id: str, req: PivotInclude) -> dict:
    """Force (or, with undo, un-force) one artifact into a saved grouping.

    A saved grouping's subset filters the library, so an artifact that does not
    match the subset can only appear by being forced in. This reads the stored
    spec, appends `artifact_id` to `included_ids` (or removes it when `undo` is
    true), and saves it back; the next re-run of the grouping places the
    artifact into whichever group its group_by attribute resolves to. The
    artifact is never copied or moved - it just joins this arrangement too.
    """
    try:
        saved = pivots_saved.get(pivot_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No saved grouping by that id.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    spec = saved["spec"]
    included = [aid for aid in (spec.get("included_ids") or []) if aid != req.artifact_id]
    if not req.undo:
        included.append(req.artifact_id)
    spec["included_ids"] = included
    pivots_saved.update_spec(pivot_id, spec)
    return {"pivot_id": pivot_id, "included_ids": included}


def serve() -> None:
    import uvicorn

    try:
        expired = trash.purge_expired()
        if expired["purged"]:
            print(f"[engine] purged {expired['purged']} artifact(s) past the trash window")
    except Exception as exc:  # noqa: BLE001 - never block startup on housekeeping
        print(f"[engine] could not purge the trash: {exc}")

    # Answers interrupted by a restart left pending rows that no worker will ever
    # finish (the in-memory queue died with the old process). Rule 2: a pending
    # turn always resolves, so sweep them to `failed` with a reason a person can
    # read and retry (H5.1).
    try:
        orphaned = chats_worker.sweep_orphaned_pending()
        if orphaned:
            print(f"[engine] interrupted {orphaned} answer(s) from the previous run")
    except Exception as exc:  # noqa: BLE001 - never block startup on housekeeping
        print(f"[engine] could not sweep interrupted answers: {exc}")

    # The wall's greeting is generated in the background so the first render usually
    # finds a phrase already waiting; the page falls back to a time-based one either
    # way, so this never holds the engine open.
    greeting.ensure()

    _warm_embeddings()

    _bootstrap_index()

    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT, log_level="warning")


def _warm_embeddings() -> None:
    """Load the embedding model in the background so the first search is not cold.

    The dense model loads lazily on its first use, which is ~2.9 s on this machine
    (ONNX plus the CoreML session). Nothing at startup touches it when the index is
    already current, so that whole cost landed on the person's first search. A person
    looks at the wall before they search, so warming here on a daemon thread hides it
    behind that gap. It never blocks the engine: a failure is a slower first query,
    not an error.
    """
    import threading

    def _warm() -> None:
        try:
            from .index.embed import embed_one

            embed_one("warm")
        except Exception as exc:  # noqa: BLE001 - a cold first query is the worst case
            print(f"[engine] embedding warm-up skipped: {exc}")

    threading.Thread(target=_warm, name="embed-warm", daemon=True).start()


def _bootstrap_index() -> None:
    """Make the index exist and be current on startup, without blocking it.

    The version compare (Phase 21) happens here: if `index_meta` has no
    embedding version, or its version no longer matches the running model, a
    background rebuild starts and search is blocked until it completes. If
    the index is already current, nothing starts and search is live from the
    first request. A failed rebuild leaves search blocked (no silent
    fallback) and prints to the engine log.
    """
    from .index.bootstrap import remove_legacy_qdrant_dir, start_rebuild_if_needed

    def _progress(indexed: int, total: int) -> None:
        print(f"[engine] building search index: {indexed}/{total} rows", flush=True)

    if start_rebuild_if_needed(on_progress=_progress):
        print(
            "[engine] search index rebuilding in the background; "
            "search is enabled when it completes",
            flush=True,
        )

    # The cutover: the new index now lives inside enqueue.db, so a leftover
    # qdrant-local directory is dead data. Remove it once a run has confirmed
    # the sqlite-vec index (the check above), and log what was deleted.
    removed = remove_legacy_qdrant_dir()
    if removed:
        if "error" in removed:
            print(
                f"[engine] could not remove the legacy qdrant index at "
                f"{removed['path']}: {removed['error']}",
                flush=True,
            )
        else:
            print(
                f"[engine] removed the legacy qdrant index at {removed['path']} "
                f"({removed['files']} files, {removed['bytes'] / 1024:.0f} KiB); "
                "the search index now lives inside enqueue.db",
                flush=True,
            )
