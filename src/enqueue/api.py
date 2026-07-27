"""The engine's HTTP API.

All business logic lives behind this boundary. The CLI and the web view are both
clients of it, so the M1 shell has something to talk to on day one.

Binds to 127.0.0.1 only, on every milestone.
"""

from __future__ import annotations

import re
from importlib import resources

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from . import capture, chats, config, db, notes, preview, settings
from .ingest import chunk as chunk_mod
from .ingest import facets as facets_mod
from .ingest import queue as ingest_queue

app = FastAPI(title="Enqueue engine", version="0.2.0")


@app.get("/", response_class=HTMLResponse)
def museum() -> str:
    return resources.files("enqueue").joinpath("static/museum.html").read_text(encoding="utf-8")


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
    changes = {k: int(v) for k, v in req.model_dump(exclude_none=True).items()}
    if not changes:
        raise HTTPException(status_code=400, detail="nothing to change")

    sets = ", ".join(f"{k} = ?" for k in changes)
    with db.transaction() as conn:
        cur = conn.execute(
            f"UPDATE artifacts SET {sets} WHERE id = ?", (*changes.values(), artifact_id)
        )
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="no such artifact")
    return notes.get(artifact_id)


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
        raise HTTPException(status_code=404, detail="no such artifact")

    if row["kind"] == "pdf":
        return {"kind": "pdf", "pages": capture.page_text(artifact_id)}
    return {"kind": row["kind"], "pages": [{"page": 0, "text": row["body"] or ""}]}


ORDERINGS = {
    # When it arrived. This is the museum's default, because the promise is that
    # things land in the order you found them: a note you reopen and fix a typo in has
    # not become newer, and re-sorting on every autosave makes the wall unstable
    # under your own reading.
    "ingested": "pinned DESC, created_at DESC",
    "touched": "pinned DESC, updated_at DESC",
    "title": "pinned DESC, title COLLATE NOCASE ASC",
}


@app.get("/artifacts")
def list_artifacts(limit: int = 60, offset: int = 0, order: str = "ingested") -> dict:
    """Newest first, each with enough content to render rather than a blank.

    Nothing about where an artifact came from is returned. Import provenance is a
    folder by another name, and surfacing it would put the folder metaphor back into
    a product built to refuse it.
    """
    if order not in ORDERINGS:
        raise HTTPException(status_code=400, detail=f"order must be one of {sorted(ORDERINGS)}")

    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, kind, title, body, source_url, mime, filename, created_at,"
            " updated_at, local_only, pinned, status FROM artifacts"
            f" ORDER BY {ORDERINGS[order]} LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()

        items = []
        for row in rows:
            item = dict(row)
            item["excerpt"] = _excerpt(item.pop("body") or "", row["title"])
            item["has_blob"] = row["mime"] is not None and row["kind"] != "link"
            if row["kind"] == "pdf":
                item["pages"] = capture.page_count(row["id"])
            items.append(item)

        return {"total": db.count("artifacts"), "order": order, "items": items}
    finally:
        conn.close()


@app.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str) -> dict:
    try:
        detail = notes.get(artifact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such artifact")

    kind = detail["artifact"]["kind"]
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
        raise HTTPException(status_code=404, detail="no such version")
    return {"id": version_id, "body": body}


@app.get("/artifacts/{artifact_id}/blob")
def get_blob(artifact_id: str):
    found = capture.blob_path(artifact_id)
    if found is None:
        raise HTTPException(status_code=404, detail="this artifact has no stored file")
    path, mime, filename = found
    return FileResponse(path, media_type=mime, filename=filename, content_disposition_type="inline")


@app.get("/artifacts/{artifact_id}/page/{number}")
def get_page(artifact_id: str, number: int, width: int = 900):
    # A client that asks for a zero-width page has measured its layout too early. That
    # is a bug worth fixing on the client, and a blank reader is the wrong way to
    # report it, so the width is clamped to something renderable.
    width = max(120, min(width, 3000))
    png = capture.render_page(artifact_id, number, width=width)
    if png is None:
        raise HTTPException(status_code=404, detail="no such page")
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
        raise HTTPException(status_code=404, detail="no such artifact")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/artifacts/{artifact_id}/annotations", status_code=201)
def add_annotation(artifact_id: str, req: AnnotationCreate) -> dict:
    try:
        return notes.annotate(artifact_id, req.text, supersedes_id=req.supersedes_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such artifact")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/capture/link", status_code=201)
def capture_link(req: LinkCreate) -> dict:
    try:
        return capture.link(req.url, local_only=req.local_only)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/capture/upload", status_code=201)
async def capture_upload(file: UploadFile = File(...), local_only: bool = Form(False)) -> dict:
    data = await file.read()
    try:
        return capture.upload(
            data, file.filename or "upload", mime=file.content_type, local_only=local_only
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/artifacts/{artifact_id}/preview")
def fetch_preview(artifact_id: str) -> dict:
    """Make the one request this link never made at capture time.

    Explicit by design. Saving a link touches nothing; this is the person deciding
    that this particular link is worth telling its publisher about.
    """
    try:
        return preview.fetch(artifact_id) or {}
    except KeyError:
        raise HTTPException(status_code=404, detail="no such artifact")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# ------------------------------------------------------------------------ derived


@app.post("/chunk")
def rebuild_chunks() -> dict:
    return chunk_mod.chunk_all()


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
    from .index import qdrant as qd

    return {"chunks": qd.index_chunks(), "facets": qd.index_facets()}


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
    from .index import qdrant as qd

    return qd.counts()


# ------------------------------------------------------------------------- search


@app.get("/search")
def search(q: str, limit: int = 20) -> dict:
    from .index import qdrant as qd

    hits = qd.search(qd.CHUNKS, q, limit=limit)
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
        raise HTTPException(status_code=400, detail=str(exc))

    if req.text:
        return send_to_chat(made["chat"]["id"], ChatSend(text=req.text))
    return made


@app.get("/chats/{chat_id}")
def get_chat(chat_id: str) -> dict:
    try:
        return chats.get(chat_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such chat")


@app.post("/chats/{chat_id}/messages")
def send_to_chat(chat_id: str, req: ChatSend) -> dict:
    try:
        return chats.send(chat_id, req.text)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such chat")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - a model failure is a 503, not a crash
        raise HTTPException(status_code=503, detail=f"the curator could not answer: {exc}")


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
        raise HTTPException(status_code=404, detail="no such chat")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/chats/{chat_id}")
def delete_chat(chat_id: str) -> dict:
    try:
        return chats.delete(chat_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such chat")


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
        raise HTTPException(status_code=400, detail=str(exc))


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
            raise HTTPException(status_code=404, detail="no such exhibit")
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


@app.patch("/settings")
def write_settings(req: SettingsUpdate) -> dict:
    try:
        return {"settings": settings.update(req.changes), "storage": settings.storage()}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


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

    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT, log_level="warning")
