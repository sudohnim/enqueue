"""Artifacts: the wall and artifact page, the trash lifecycle, and capture writes.

Read one or many artifacts, move them through the trash, attach tags and
annotations, and ingest links/uploads/previews. The wall-shaping helpers live
in wall.py; this router is where the wall's rows are assembled.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from .. import capture, db, notes, pivots_saved, preview, trash
from .. import tags as tags_mod
from .wall import ORDERINGS, _link_images, _wall_item, _wall_tags

router = APIRouter()


# --------------------------------------------------------------------------- read


class ArtifactFlags(BaseModel):
    pinned: bool | None = None
    local_only: bool | None = None


@router.patch("/artifacts/{artifact_id}")
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


@router.delete("/artifacts/{artifact_id}")
def bin_artifact(artifact_id: str) -> dict:
    """Move to the trash. Reversible for as long as the retention window lasts."""
    try:
        return trash.delete(artifact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such artifact") from None


@router.post("/artifacts/{artifact_id}/restore")
def restore_artifact(artifact_id: str) -> dict:
    try:
        return trash.restore(artifact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such artifact") from None


@router.get("/trash")
def read_trash() -> dict:
    return trash.listing()


@router.delete("/trash/{artifact_id}")
def purge_artifact(artifact_id: str) -> dict:
    """Destroy one artifact for good. The only irreversible operation in the product."""
    try:
        return trash.purge(artifact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such artifact") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("/trash/purge")
def purge_trash() -> dict:
    return trash.purge_expired()


@router.delete("/trash")
def empty_trash() -> dict:
    """Destroy everything waiting, now, without waiting out the window.

    Separate from `/trash/purge`, which only takes what has already expired. This one
    is the deliberate "I meant it" and the interface confirms before calling it.
    """
    return trash.empty()


@router.get("/artifacts/{artifact_id}/text")
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


@router.get("/artifacts")
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
        # Relevance is not a SQL ordering: there is no score column on the wall. No
        # UI control sends it, but the defensive 400 stays so a future caller gets a
        # clear message instead of a silent empty wall.
        raise HTTPException(
            status_code=400, detail="relevance ordering needs a lens; the wall has none"
        ) from None

    # `pinned` splits the wall into two shelves that are paged separately: the kept
    # few scroll sideways, everything else scrolls down. Without the filter the pinned
    # ones would appear in both.
    where = "deleted_at IS NULL AND vaulted_at IS NULL"
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


@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str) -> dict:
    try:
        detail = notes.get(artifact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such artifact") from None

    # A vaulted artifact reads through the same reader, but its content is decrypted
    # here only while the vault is unlocked (else it stays hidden, like the wall).
    art = detail["artifact"]
    if art.get("vaulted_at"):
        from .. import vault, vaultops

        if not vault.is_unlocked():
            raise HTTPException(status_code=404, detail="no such artifact") from None
        key = vault.key()
        art["title"] = vaultops._open(key, art["title"])
        art["body"] = vaultops._open(key, art["body"])

    kind = detail["artifact"]["kind"]
    if kind in ("file", "image", "pdf"):
        if art.get("vaulted_at"):
            # The bytes live encrypted; the reader loads them from /vault/{id}/blob.
            # Just tell it a file exists, with its mime/name.
            detail["file"] = {
                "bytes": 1,
                "mime": art.get("mime") or "application/octet-stream",
                "name": art.get("filename") or artifact_id,
                "vaulted": True,
            }
        else:
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
    # is stored as JSON with an `included_ids` list; `all_specs` returns every
    # spec in one query (P.2e) instead of a per-view get().
    views = []
    for saved in pivots_saved.all_specs():
        spec = saved["spec"]
        included = set(spec.get("included_ids") or [])
        excluded = set(spec.get("excluded_ids") or [])
        # Mirror pivot.run's membership: an explicit exclusion beats an
        # inclusion, so a chip the user just X'd out of (which excludes the id)
        # must disappear on re-render.
        if artifact_id in included and artifact_id not in excluded:
            views.append({"id": saved["id"], "name": saved["name"]})
    detail["views"] = sorted(views, key=lambda v: v["name"])
    return detail


@router.get("/artifacts/{artifact_id}/versions/{version_id}")
def get_version(artifact_id: str, version_id: str) -> dict:
    body = notes.version_body(artifact_id, version_id)
    if body is None:
        raise HTTPException(status_code=404, detail="no such version") from None
    return {"id": version_id, "body": body}


@router.get("/artifacts/{artifact_id}/blob")
def get_blob(artifact_id: str):
    # A vaulted artifact's blob is encrypted at rest and only served through the
    # unlocked vault route; the normal path must not leak it (even as ciphertext).
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT vaulted_at FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is not None and row["vaulted_at"]:
        raise HTTPException(status_code=404, detail="this artifact has no stored file") from None
    found = capture.blob_path(artifact_id)
    if found is None:
        raise HTTPException(status_code=404, detail="this artifact has no stored file") from None
    path, mime, filename = found
    return FileResponse(path, media_type=mime, filename=filename, content_disposition_type="inline")


@router.get("/artifacts/{artifact_id}/find")
def find_in_artifact(artifact_id: str, q: str) -> dict:
    """Where a phrase appears in a PDF, so the reader can draw over it.

    The pages are pictures, so the browser has no text to highlight of its own. These
    are the rectangles it needs, in page fractions rather than points.
    """
    return {"query": q, "hits": capture.find_in_pdf(artifact_id, q)}


@router.get("/artifacts/{artifact_id}/preview-image")
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


@router.get("/artifacts/{artifact_id}/page/{number}")
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


@router.post("/notes", status_code=201)
def create_note(req: NoteCreate) -> dict:
    return notes.create(body=req.body, title=req.title, local_only=req.local_only)


@router.patch("/artifacts/{artifact_id}/body")
def edit_body(artifact_id: str, req: BodyEdit) -> dict:
    """Rewrite a note. Captures reject this: they have no editable body."""
    try:
        return notes.edit(artifact_id, req.body, title=req.title)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such artifact") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("/artifacts/{artifact_id}/annotations", status_code=201)
def add_annotation(artifact_id: str, req: AnnotationCreate) -> dict:
    try:
        return notes.annotate(artifact_id, req.text, supersedes_id=req.supersedes_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such artifact") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("/artifacts/{artifact_id}/tags", status_code=201)
def add_tag(artifact_id: str, req: TagCreate) -> dict:
    """Attach a tag. A tag is an optional, later act on an artifact that exists."""
    try:
        return tags_mod.add(artifact_id, req.name)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such artifact") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.delete("/artifacts/{artifact_id}/tags/{name}")
def remove_tag(artifact_id: str, name: str) -> dict:
    """Detach a tag by its canonical name."""
    try:
        return tags_mod.remove(artifact_id, name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/tags")
def get_tags() -> dict:
    """Every tag with its artifact count, most-used first."""
    return {"tags": tags_mod.cloud()}


@router.post("/capture/link", status_code=201)
def capture_link(req: LinkCreate) -> dict:
    try:
        return capture.link(req.url, local_only=req.local_only)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/capture/upload", status_code=201)
async def capture_upload(file: UploadFile = File(...), local_only: bool = Form(False)) -> dict:
    data = await file.read()
    try:
        return capture.upload(
            data, file.filename or "upload", mime=file.content_type, local_only=local_only
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/artifacts/{artifact_id}/preview")
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
