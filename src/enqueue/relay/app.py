"""The sync relay: a standalone FastAPI service, not part of the local engine.

It is a dumb byte store. It holds per-device snapshot objects and
content-addressed blobs keyed by name, serves them back, and streams a
"something changed" signal over SSE. It parses none of the bytes and can
decrypt nothing. The protocol is in AGENTS.md, "The relay".

One relay serves many libraries: the secret a request carries says which library it
is in (storage.library_id), and a library sees and touches only its own objects.
Libraries are made and revoked through the admin routes (RELAY_ADMIN_SECRET), which
`enq relay-admin` calls; the secret the relay is started with is a library too.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from pathlib import Path

import hmac

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from .storage import LibraryFull, RelayStorage, library_id

# The largest object a device may store (a PDF, a photo): 100 MiB unless set.
MAX_OBJECT_BYTES = int(os.getenv("RELAY_MAX_OBJECT_BYTES", str(100 * 1024 * 1024)))
# Each library's storage limit, unless the library has its own: 5 GiB; 0 for none.
DEFAULT_QUOTA_BYTES = int(os.getenv("RELAY_QUOTA_BYTES", str(5 * 1024**3)))


# The change stream takes its secret in the address (`?token=`, since an EventSource
# cannot set a header), and the server's access log writes every address out: the
# hosted relay's logs held each library's password in plain text. Blank it there.
_TOKEN_IN_PATH = re.compile(r"([?&]token=)[^&\s]*")


class _HideTokens(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                _TOKEN_IN_PATH.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args
            )
        if isinstance(record.msg, str):
            record.msg = _TOKEN_IN_PATH.sub(r"\1***", record.msg)
        return True


def hide_tokens_in_access_log() -> None:
    """Install the filter once on uvicorn's access logger (safe to call again)."""
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _HideTokens) for f in access.filters):
        access.addFilter(_HideTokens())


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
    """In-memory fan-out per library: a subscriber receives its own library's events.

    A subscriber is an asyncio.Queue. `publish` is called by the PUT endpoint
    (from any thread); it hands the event to every live subscriber queue of that
    library. The SSE generator drains its own queue and yields `event: object` lines.
    """

    def __init__(self) -> None:
        self._subscribers: dict[asyncio.Queue, str] = {}
        self._lock = threading.Lock()

    def subscribe(self, library: str = "") -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subscribers[q] = library
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.pop(q, None)

    def publish(self, event: dict, library: str = "") -> None:
        with self._lock:
            for q, owner in self._subscribers.items():
                if owner == library:
                    q.put_nowait(event)


def create_relay(
    data_dir: Path | None = None,
    secret: str | None = None,
    admin_secret: str | None = None,
    max_object_bytes: int | None = None,
    quota_bytes: int | None = None,
    account_settings=None,
    ai_client=None,
) -> FastAPI:
    """Build the relay app. Every argument defaults to its env override.

    `secret` is the first library's secret (the one a single-library relay always ran
    with): it is registered at startup, and objects stored before libraries existed
    move into it. `admin_secret` turns on the routes that make and revoke libraries.
    `account_settings` (relay/accounts.py; from DATABASE_URL by default) turns on
    sign-in and device tokens: the hosted relay. A self-hosted one has neither.
    Injectable so tests can point the store at a temp dir and known secrets without
    touching process-global env state.
    """
    hide_tokens_in_access_log()
    the_secret = secret or os.getenv("RELAY_SECRET", "dev-secret")
    the_admin = admin_secret if admin_secret is not None else os.getenv("RELAY_ADMIN_SECRET")
    max_object = max_object_bytes if max_object_bytes is not None else MAX_OBJECT_BYTES
    storage = RelayStorage(
        data_dir or Path(os.getenv("RELAY_DATA_DIR", "./relay-data")),
        legacy_library=library_id(the_secret),
        default_quota=DEFAULT_QUOTA_BYTES if quota_bytes is None else quota_bytes,
    )
    hub = RelayHub()

    from .accounts import AccountSettings, Accounts
    from .accounts import router as accounts_router

    if account_settings is None:
        account_settings = AccountSettings.from_env()
    accounts = Accounts(account_settings, storage) if account_settings else None

    app = FastAPI(title="Enqueue sync relay", version="0.3.1")
    if accounts is not None:
        from .ai import router as ai_router

        app.include_router(accounts_router(accounts))
        # The included assistant (relay/ai.py): Enqueue's OpenRouter key, metered per
        # account. `ai_client` is the HTTP client it calls OpenRouter with (tests).
        app.include_router(ai_router(accounts, ai_client))

    def _library(secret: str) -> str:
        lid = storage.library_for(secret) if secret else None
        if lid is None and accounts is not None and secret:
            # A signed-in device's own token (relay/accounts.py), for its account's
            # library; checked only after a library secret, so the self-hosted path
            # never touches the account database.
            lid = accounts.library_for_device(secret)
            if lid is not None and not storage.is_live(lid):
                lid = None
        if lid is None:
            raise HTTPException(status_code=401, detail="bad secret")
        return lid

    def _require_header(authorization: str = Header(default="")) -> str:
        """The library the request's secret opens (401 when none does)."""
        scheme, _, secret = authorization.partition(" ")
        return _library(secret if scheme == "Bearer" else "")

    def _require_admin(authorization: str = Header(default="")) -> None:
        if not the_admin:
            raise HTTPException(status_code=404, detail="not found")
        if not hmac.compare_digest(authorization.encode(), f"Bearer {the_admin}".encode()):
            raise HTTPException(status_code=401, detail="bad admin secret")

    async def _body(request: Request) -> bytes:
        """The request body, refused past `max_object` before it is all read."""
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > max_object:
            raise HTTPException(status_code=413, detail="object too large")
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > max_object:
                raise HTTPException(status_code=413, detail="object too large")
            chunks.append(chunk)
        return b"".join(chunks)

    @app.get("/health")
    def health() -> dict:
        # Unauthenticated liveness probe for the deploy script and Railway. It
        # reveals nothing: no object names, no counts, just that the app is up.
        return {"status": "ok"}

    @app.get("/sync/objects")
    def list_objects(since: int = 0, library: str = Depends(_require_header)):
        objects, cursor = storage.list_changed(library, since)
        return {"objects": objects, "cursor": cursor}

    @app.get("/sync/object/{name:path}")
    def get_object(name: str, library: str = Depends(_require_header)):
        data = storage.get(library, name)
        if data is None:
            raise HTTPException(status_code=404, detail="no such object")
        return Response(content=data, media_type="application/octet-stream")

    @app.put("/sync/object/{name:path}", status_code=201)
    async def put_object(name: str, request: Request, library: str = Depends(_require_header)):
        # UPSERT by name (MOBFIX.5): create or overwrite, always 201. An overwrite
        # takes a fresh cursor so the change feed re-surfaces the updated object.
        data = await _body(request)
        try:
            cursor, size = storage.put(library, name, data)
        except LibraryFull as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        hub.publish({"name": name, "cursor": cursor}, library)
        return {"name": name, "size": size}

    @app.delete("/sync/object/{name:path}", status_code=204)
    def delete_object(name: str, library: str = Depends(_require_header)):
        # A device clears its own superseded objects (the names from before the relay
        # names were hashed, sync/client.py `repush_relay_v2`).
        if not storage.delete(library, name):
            raise HTTPException(status_code=404, detail="no such object")
        return Response(status_code=204)

    # --- libraries (admin) ----------------------------------------------------------
    # Only with RELAY_ADMIN_SECRET set; `enq relay-admin` is the client. A new library's
    # secret is returned once and never stored: the relay keeps only its hash.

    @app.post("/admin/libraries", status_code=201)
    async def add_library(request: Request, _: None = Depends(_require_admin)):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - an empty or bad body is a library with no label
            body = {}
        quota = body.get("quota_bytes")
        lid, secret = storage.add_library(
            str(body.get("label") or "")[:100], int(quota) if quota is not None else None
        )
        return {"id": lid, "secret": secret}

    @app.get("/admin/libraries")
    def list_libraries(_: None = Depends(_require_admin)):
        return {"libraries": storage.libraries()}

    @app.delete("/admin/libraries/{lid}", status_code=204)
    def revoke_library(lid: str, _: None = Depends(_require_admin)):
        if not storage.revoke_library(lid):
            raise HTTPException(status_code=404, detail="no such library")
        return Response(status_code=204)

    @app.put("/admin/accounts/pro")
    async def grant_pro(request: Request, _: None = Depends(_require_admin)):
        """Pro for an account by its email, for `days` (0 ends it; omitted: for good).
        For the owner and for support; a purchase sets it through the webhook."""
        if accounts is None:
            raise HTTPException(status_code=404, detail="no accounts on this relay")
        body = await request.json()
        found = accounts.accounts_by_email(str(body.get("email") or ""))
        if not found:
            raise HTTPException(status_code=404, detail="no account with that email")
        days = body.get("days")
        until = None if days == 0 else (time.time() + float(days) * 86400 if days else None)
        if days is None:
            from .accounts import FOREVER

            until = FOREVER
        for account in found:
            accounts.set_pro_until(account["id"], until)
        return {"accounts": [accounts.plan(accounts.get_account(a["id"])) for a in found]}

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
    PAIR_COUNT = 256  # waiting at once, across every library: memory, not disk
    pairings: dict[str, tuple[float, bytes]] = {}
    pair_lock = threading.Lock()
    valid_pid = re.compile(r"^[A-Za-z0-9_-]{16,128}$")

    def _prune_pairings(now: float) -> None:
        for k in [k for k, (exp, _) in pairings.items() if exp < now]:
            pairings.pop(k, None)

    @app.put("/pair/{pid}", status_code=201)
    async def put_pair(pid: str, request: Request, _: str = Depends(_require_header)):
        if not valid_pid.match(pid):
            raise HTTPException(status_code=400, detail="bad pairing id")
        body = await request.body()
        if len(body) > PAIR_MAX:
            raise HTTPException(status_code=413, detail="pairing envelope too large")
        now = time.time()
        with pair_lock:
            _prune_pairings(now)
            if pid not in pairings and len(pairings) >= PAIR_COUNT:
                raise HTTPException(status_code=429, detail="too many pairings waiting")
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
        library = _library(token)
        queue = hub.subscribe(library)
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
