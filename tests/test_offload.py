"""Which originals may leave this Mac (C4a)."""

from __future__ import annotations

import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import uvicorn

from enqueue import blobstore, capture, crypto, db, keyring, keyring_file, offload, settings
from enqueue.relay.app import create_relay
from enqueue.sync.client import push_artifact

RELAY = "https://relay.example"
OLD = "2020-01-01T00:00:00+00:00"


def _serve(store):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(
        uvicorn.Config(
            create_relay(store / "relay", secret="test-secret"),
            host="127.0.0.1",
            port=port,
            log_level="error",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if (
                httpx.get(
                    base + "/sync/objects",
                    headers={"Authorization": "Bearer test-secret"},
                    timeout=1,
                ).status_code
                == 200
            ):
                break
        except Exception:  # noqa: BLE001 - not ready yet
            time.sleep(0.05)
    return base, server, thread


def _seed(kind="pdf", name=None, pinned=0, local_only=0, relay=RELAY, thumb=False, opened=None):
    aid = name or str(uuid.uuid4())
    digest = blobstore.write(b"x", str(uuid.uuid4()))
    now = db.now()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts"
            " (id, kind, title, content_hash, mime, status, pinned, local_only,"
            " created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (aid, kind, "A capture", digest, "application/pdf", "ok", pinned, local_only, OLD, OLD),
        )
        conn.execute(
            "INSERT INTO blob_relay (content_hash, relay, pushed_at) VALUES (?,?,?)",
            (digest, relay.rstrip("/"), now),
        )
        if thumb:
            conn.execute(
                "INSERT INTO thumbs (artifact_id, content_hash, width) VALUES (?,?,?)",
                (aid, digest, 520),
            )
        if opened is not None:
            conn.execute(
                "INSERT INTO opens (artifact_id, source, opened_at) VALUES (?,?,?)",
                (aid, "wall", opened),
            )
    return aid


def test_candidates_are_old_originals_on_this_relay(store):
    good = _seed()

    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    _seed(pinned=1)
    _seed(local_only=1)
    _seed(opened=yesterday)
    _seed(relay="https://other.example")
    _seed(kind="image")
    _seed(kind="image", thumb=True)
    _seed(kind="note")

    got = offload.candidates(db.get_conn(), 30, RELAY)
    ids = [r["id"] for r in got]
    assert good in ids
    assert len(ids) == 2


def test_on_relay_checks_the_exact_sealed_bytes(store, monkeypatch):
    base, server, thread = _serve(store)
    try:
        settings.update({"sync_relay_url": base})
        monkeypatch.setattr(keyring, "sync_secret_get", lambda: "test-secret")
        keyring_file.initialize()

        digest = blobstore.write(b"the original file bytes", str(uuid.uuid4()))
        aid = str(uuid.uuid4())
        now = db.now()
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO artifacts"
                " (id, kind, title, content_hash, mime, status, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (aid, "file", "A file", digest, "application/octet-stream", "ok", now, now),
            )
        push_artifact(aid)

        assert offload.on_relay(digest) is True

        dek = keyring_file.dek()

        class Resp:
            def __init__(self, status, size=None):
                self.status_code = status
                self.headers = {} if size is None else {"X-Object-Size": str(size)}

        monkeypatch.setattr(httpx.Client, "head", lambda self, *a, **k: Resp(404))
        assert offload.on_relay(digest) is False

        real = len(crypto.seal_payload(blobstore.read(digest), dek))
        monkeypatch.setattr(httpx.Client, "head", lambda self, *a, **k: Resp(200, real + 1))
        assert offload.on_relay(digest) is False
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_run_frees_only_when_on_and_fetches_back(store, monkeypatch):
    base, server, thread = _serve(store)
    try:
        settings.update({"sync_relay_url": base})
        monkeypatch.setattr(keyring, "sync_secret_get", lambda: "test-secret")
        keyring_file.initialize()

        payload = b"the original file bytes that leave this Mac"
        digest = blobstore.write(payload, str(uuid.uuid4()))
        aid = str(uuid.uuid4())
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO artifacts"
                " (id, kind, title, content_hash, mime, status, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (aid, "file", "A file", digest, "application/octet-stream", "ok", OLD, OLD),
            )
        push_artifact(aid)

        settings.update({"offload_originals": "off"})
        assert offload.run() == {"freed": 0, "bytes": 0}
        assert blobstore.exists(digest)

        settings.update({"offload_originals": "on"})
        result = offload.run()
        assert result["freed"] == 1
        assert result["bytes"] == len(payload)
        assert not blobstore.exists(digest)

        blob = capture.blob_path(aid)
        assert blob is not None
        assert blob[0].read_bytes() == payload
    finally:
        server.should_exit = True
        thread.join(timeout=5)
