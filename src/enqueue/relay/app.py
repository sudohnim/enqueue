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
import re
import threading
import time
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

    # --- device pairing (PAIR.1) --------------------------------------------------
    # A brand-new device joining the library has no library secret yet - it is inside
    # the payload being handed over - so it cannot authenticate the object routes. The
    # main device seals a one-time envelope {relay, secret, dek} under an Argon2id KEK
    # derived from a pairing PHRASE (the same primitive as the keyring) and PUTs it here
    # (authenticated, since the main device HAS the secret). The joining device GETs it
    # by the capability id WITHOUT the secret. Confidentiality rests on the phrase, which
    # never touches the relay; the id only locates the ciphertext. Envelopes are kept in
    # memory, fetched at most once, and expire - so nothing sensitive lands on disk and a
    # stale or replayed id yields nothing.
    PAIR_TTL = 600  # seconds; a pairing must be claimed within 10 minutes
    PAIR_MAX = 64 * 1024
    pairings: dict[str, tuple[float, bytes]] = {}
    pair_lock = threading.Lock()
    valid_pid = re.compile(r"^[A-Za-z0-9_-]{16,128}$")

    def _prune_pairings(now: float) -> None:
        for k in [k for k, (exp, _) in pairings.items() if exp < now]:
            pairings.pop(k, None)

    @app.put("/pair/{pid}", status_code=201)
    async def put_pair(pid: str, request: Request, _: None = Depends(_require_header)):
        if not valid_pid.match(pid):
            raise HTTPException(status_code=400, detail="bad pairing id")
        body = await request.body()
        if len(body) > PAIR_MAX:
            raise HTTPException(status_code=413, detail="pairing envelope too large")
        now = time.time()
        with pair_lock:
            _prune_pairings(now)
            pairings[pid] = (now + PAIR_TTL, body)
        return {"ok": True, "expires_in": PAIR_TTL}

    @app.get("/pair/{pid}")
    def get_pair(pid: str):
        # No library-secret auth: the id is the one-time capability. The bytes are
        # Argon2-sealed with the pairing phrase, so neither the relay nor an id-guesser
        # can open them. Consumed on the first successful fetch (pop), so a leaked id is
        # useless once the real device has claimed it.
        if not valid_pid.match(pid):
            raise HTTPException(status_code=400, detail="bad pairing id")
        now = time.time()
        with pair_lock:
            _prune_pairings(now)
            item = pairings.pop(pid, None)
        if item is None or item[0] < now:
            raise HTTPException(status_code=404, detail="no such pairing")
        return Response(content=item[1], media_type="application/octet-stream")

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
