"""The engine's HTTP API.

All business logic lives behind this boundary. The CLI is a thin client and never
touches the database directly, so the M1 shell has something to talk to on day one.

Binds to 127.0.0.1 only, on every milestone.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import config, db
from .ingest import chunk as chunk_mod
from .ingest import facets as facets_mod
from .ingest import importer

app = FastAPI(title="Enqueue engine", version="0.1.0")


@app.get("/", response_class=HTMLResponse)
def museum() -> str:
    """A preview of the museum, served by the engine.

    Not the real client. M1 is a Tauri shell, and this exists to look at real content
    against the design tokens before committing to them. It is a client of the same
    API the shell will use, so nothing here is thrown away twice.
    """
    return resources.files("enqueue").joinpath("static/museum.html").read_text(encoding="utf-8")


class ImportRequest(BaseModel):
    path: str


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "artifacts": db.count("artifacts"),
        "blocks": db.count("blocks"),
        "chunks": db.count("chunks"),
        "facets": db.count("facets"),
    }


@app.get("/artifacts")
def list_artifacts(limit: int = 50, offset: int = 0) -> dict:
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, kind, title, source_url, captured_at, imported_from, provenance,"
            " local_only, status FROM artifacts ORDER BY captured_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return {"total": db.count("artifacts"), "items": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str) -> dict:
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="no such artifact")
        blocks = conn.execute(
            "SELECT id, parent_id, ordinal, depth, text, created_at FROM blocks"
            " WHERE artifact_id = ? ORDER BY ordinal",
            (artifact_id,),
        ).fetchall()
        notes = conn.execute(
            "SELECT id, supersedes_id, text, created_at FROM note_entries"
            " WHERE artifact_id = ? ORDER BY created_at",
            (artifact_id,),
        ).fetchall()
        facets = conn.execute(
            "SELECT id, level, statement, trust FROM facets WHERE artifact_id = ?"
            " ORDER BY level, statement",
            (artifact_id,),
        ).fetchall()
        skip = conn.execute(
            "SELECT reason FROM facet_skips WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        return {
            "artifact": dict(row),
            "blocks": [dict(b) for b in blocks],
            "notes": [dict(n) for n in notes],
            "facets": [dict(f) for f in facets],
            "facet_skip_reason": skip["reason"] if skip else None,
        }
    finally:
        conn.close()


@app.post("/import/fabric")
def import_fabric(req: ImportRequest) -> dict:
    root = Path(req.path).expanduser()
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"not a directory: {root}")
    report = importer.import_fabric(root)
    return {
        "imported": report.imported,
        "blobs": report.blobs,
        "blocks": report.blocks,
        "skipped_duplicate": report.skipped_duplicate,
        "with_secrets": report.with_secrets,
    }


@app.post("/import/bookmarks")
def import_bookmarks(req: ImportRequest) -> dict:
    path = Path(req.path).expanduser()
    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"not a file: {path}")
    report = importer.import_bookmarks(path)
    return {"imported": report.imported, "skipped_duplicate": report.skipped_duplicate}


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


@app.get("/search")
def search(q: str, limit: int = 20) -> dict:
    from .index import qdrant as qd

    hits = qd.search(qd.CHUNKS, q, limit=limit)
    conn = db.get_conn()
    try:
        out = []
        for hit in hits:
            row = conn.execute(
                "SELECT a.title, c.text FROM chunks c JOIN artifacts a ON a.id = c.artifact_id"
                " WHERE c.id = ?",
                (hit["chunk_id"],),
            ).fetchone()
            if row:
                out.append(
                    {
                        "score": round(hit["score"], 4),
                        "artifact_id": hit["artifact_id"],
                        "title": row["title"],
                        "snippet": row["text"][:180].replace("\n", " "),
                    }
                )
        return {"query": q, "hits": out}
    finally:
        conn.close()


class CurateRequest(BaseModel):
    lens: str
    keep: int = 15
    pool: int = 150
    save: bool = False


@app.post("/curate")
def curate(req: CurateRequest) -> dict:
    from .retrieve.curate import curate as run

    return run(req.lens, keep=req.keep, pool=req.pool, save=req.save)


@app.get("/exhibits")
def list_exhibits() -> dict:
    conn = db.get_conn()
    try:
        rows = conn.execute("SELECT * FROM exhibits ORDER BY created_at DESC").fetchall()
        return {"items": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.get("/index/counts")
def index_counts() -> dict:
    from .index import qdrant as qd

    return qd.counts()


@app.get("/secrets")
def secret_report() -> dict:
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT a.title, a.imported_from, s.kind, s.line, s.excerpt"
            " FROM secret_hits s JOIN artifacts a ON a.id = s.artifact_id"
            " ORDER BY a.title"
        ).fetchall()
        return {"count": len(rows), "hits": [dict(r) for r in rows]}
    finally:
        conn.close()


def serve() -> None:
    import uvicorn

    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT, log_level="info")
