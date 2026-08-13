"""The sync relay: a dumb byte store with a live change stream.

SYNC.2's contract: a client can PUT an opaque blob, GET it back byte-identical,
list it after a cursor, and an SSE client receives an event on the PUT. The
relay stores opaque bytes and can decrypt nothing - these tests only prove the
byte round-trip and the change feed, never that the relay reads the bytes.
"""

from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from enqueue.relay.app import create_relay


def _client(tmp_path, secret="test-secret"):
    return TestClient(create_relay(tmp_path, secret=secret))


def _auth(secret="test-secret"):
    return {"Authorization": f"Bearer {secret}"}


def test_put_then_get_is_byte_identical(tmp_path):
    client = _client(tmp_path)

    payload = b"\x00\xff\x10opaque-bytes-not-json-\x00\x01"
    put = client.put(
        "/sync/object/dev/d1/artifacts/a.enc",
        content=payload,
        headers=_auth(),
    )
    assert put.status_code == 201
    assert put.json()["name"] == "dev/d1/artifacts/a.enc"
    assert put.json()["size"] == len(payload)

    got = client.get("/sync/object/dev/d1/artifacts/a.enc", headers=_auth())
    assert got.status_code == 200
    assert got.content == payload


def test_put_an_existing_name_is_a_conflict(tmp_path):
    client = _client(tmp_path)

    first = client.put("/sync/object/blobs/abc", content=b"one", headers=_auth())
    assert first.status_code == 201

    second = client.put("/sync/object/blobs/abc", content=b"two", headers=_auth())
    assert second.status_code == 409

    # The first bytes survive: never overwrite in place.
    got = client.get("/sync/object/blobs/abc", headers=_auth())
    assert got.content == b"one"


def test_list_changed_since_shows_new_objects_with_a_cursor(tmp_path):
    client = _client(tmp_path)

    client.put("/sync/object/dev/d1/artifacts/a.enc", content=b"a", headers=_auth())
    client.put("/sync/object/dev/d2/artifacts/b.enc", content=b"b", headers=_auth())

    first = client.get("/sync/objects", params={"since": 0}, headers=_auth())
    assert first.status_code == 200
    names = [o["name"] for o in first.json()["objects"]]
    assert names == ["dev/d1/artifacts/a.enc", "dev/d2/artifacts/b.enc"]
    cursor = first.json()["cursor"]

    # A cursor at the current head lists nothing new.
    empty = client.get("/sync/objects", params={"since": cursor}, headers=_auth())
    assert empty.json()["objects"] == []

    # A new object appears only after the cursor.
    client.put("/sync/object/blobs/c", content=b"c", headers=_auth())
    after = client.get("/sync/objects", params={"since": cursor}, headers=_auth())
    assert [o["name"] for o in after.json()["objects"]] == ["blobs/c"]
    assert after.json()["cursor"] > cursor


def test_get_a_missing_object_is_404(tmp_path):
    client = _client(tmp_path)
    got = client.get("/sync/object/dev/d1/artifacts/nope.enc", headers=_auth())
    assert got.status_code == 404


def test_a_bad_secret_is_rejected(tmp_path):
    client = _client(tmp_path)

    got = client.get("/sync/objects", headers={"Authorization": "Bearer wrong"})
    assert got.status_code == 401

    events = client.get("/sync/events", params={"token": "wrong"})
    assert events.status_code == 401


def _serve(app):
    """Run the relay on a free port with a real uvicorn server, returning
    `(base_url, server, thread)`. A real server is required for the SSE test:
    the in-process TestClient's single event-loop portal deadlocks when a
    background thread PUTs while the main thread streams the event source."""
    import socket

    import httpx
    import uvicorn

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(base + "/sync/objects", headers=_auth(), timeout=1).status_code == 200:
                break
        except Exception:  # noqa: BLE001 - not ready yet, retry
            time.sleep(0.05)
    return base, server, thread


def test_sse_client_receives_an_event_on_put(tmp_path):
    import httpx

    app = create_relay(tmp_path, secret="test-secret")
    base, server, thread = _serve(app)
    seen: list[str] = []
    try:
        with httpx.stream(
            "GET", base + "/sync/events", params={"token": "test-secret"}, timeout=10
        ) as resp:
            assert resp.status_code == 200
            # While the stream is open, PUT an object as a real concurrent request.
            put = httpx.put(
                base + "/sync/object/dev/d1/artifacts/a.enc",
                content=b"hello",
                headers=_auth(),
                timeout=5,
            )
            assert put.status_code == 201
            for line in resp.iter_lines():
                seen.append(line)
                if line.startswith("data: "):
                    break
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    assert "event: object" in seen
    data = [line for line in seen if line.startswith("data: ")]
    assert data, "the event must carry its data payload"
    assert "dev/d1/artifacts/a.enc" in data[0]
