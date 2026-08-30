"""The sync relay: a standalone FastAPI service, not part of the local engine.

It is a dumb byte store. It holds per-device snapshot objects and
content-addressed blobs keyed by name, serves them back, and streams a
"something changed" signal over SSE. It parses none of the bytes and can
decrypt nothing. See `docs/sync-relay.md` for the protocol.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from .storage import RelayStorage


async def _sse_stream(request: Request, queue: asyncio.Queue, hub: RelayHub):
    """Drain one subscriber's queue into SSE `event: object` lines.

    A 15s heartbeat (a comment line) keeps half-open sockets from lingering; the
    client library's own auto-reconnect handles transient drops, so nothing here
    retries on its own.
    """
    try:
        yield ": connected\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
                yield f"event: object\ndata: {json.dumps(event)}\n\n"
            except TimeoutError:
                yield ": ping\n\n"
    finally:
        hub.unsubscribe(queue)


class RelayHub:
    """In-memory fan-out: every subscriber receives every published event.

    A subscriber is an asyncio.Queue. `publish` is called by the PUT endpoint
    (from any thread); it hands the event to every live subscriber queue. The
    SSE generator drains its own queue and yields `event: object` lines.
    """

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, event: dict) -> None:
        with self._lock:
            for q in self._subscribers:
                q.put_nowait(event)


def create_relay(data_dir: Path | None = None, secret: str | None = None) -> FastAPI:
    """Build the relay app. `data_dir` and `secret` default to env overrides.

    They are injectable so tests can point the store at a temp dir and a known
    secret without touching process-global env state.
    """
    storage = RelayStorage(data_dir or Path(os.getenv("RELAY_DATA_DIR", "./relay-data")))
    hub = RelayHub()
    the_secret = secret or os.getenv("RELAY_SECRET", "dev-secret")

    app = FastAPI(title="Enqueue sync relay", version="0.2.0")

    def _require_header(authorization: str = Header(default="")) -> None:
        if authorization != f"Bearer {the_secret}":
            raise HTTPException(status_code=401, detail="bad secret")

    @app.get("/health")
    def health() -> dict:
        # Unauthenticated liveness probe for the deploy script and Railway. It
        # reveals nothing: no object names, no counts, just that the app is up.
        return {"status": "ok"}

    @app.get("/sync/objects")
    def list_objects(since: int = 0, _: None = Depends(_require_header)):
        objects, cursor = storage.list_changed(since)
        return {"objects": objects, "cursor": cursor}

    @app.get("/sync/object/{name:path}")
    def get_object(name: str, _: None = Depends(_require_header)):
        data = storage.get(name)
        if data is None:
            raise HTTPException(status_code=404, detail="no such object")
        return Response(content=data, media_type="application/octet-stream")

    @app.put("/sync/object/{name:path}", status_code=201)
    async def put_object(name: str, request: Request, _: None = Depends(_require_header)):
        # UPSERT by name (MOBFIX.5): create or overwrite, always 201. An overwrite
        # takes a fresh cursor so the change feed re-surfaces the updated object.
        data = await request.body()
        cursor, size = storage.put(name, data)
        hub.publish({"name": name, "cursor": cursor})
        return {"name": name, "size": size}

    @app.get("/sync/events")
    async def events(request: Request, token: str):
        if token != the_secret:
            raise HTTPException(status_code=401, detail="bad secret")
        queue = hub.subscribe()
        return StreamingResponse(_sse_stream(request, queue, hub), media_type="text/event-stream")

    return app


def serve() -> None:
    """Run the relay standalone (uvicorn)."""
    import uvicorn

    app = create_relay()
    host = os.getenv("RELAY_HOST", "127.0.0.1")
    _port = os.getenv("RELAY_PORT", "8788")
    try:
        port = int(_port)
    except ValueError:
        port = 8788
    uvicorn.run(app, host=host, port=port)
