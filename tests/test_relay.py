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


def test_put_an_existing_name_overwrites_in_place(tmp_path):
    # MOBFIX.5: the relay upserts by name. A second PUT overwrites the bytes so a
    # mutation (edit/delete) to an already-synced artifact actually lands.
    client = _client(tmp_path)

    first = client.put("/sync/object/dev/d1/artifacts/a.enc", content=b"one", headers=_auth())
    assert first.status_code == 201

    second = client.put("/sync/object/dev/d1/artifacts/a.enc", content=b"two", headers=_auth())
    assert second.status_code == 201

    # The new bytes win: an overwrite replaces the stored object.
    got = client.get("/sync/object/dev/d1/artifacts/a.enc", headers=_auth())
    assert got.content == b"two"


def test_overwrite_resurfaces_the_object_past_an_old_cursor(tmp_path):
    # MOBFIX.5 cursor subtlety: a device that already pulled an object (cursor past
    # its first position) must still see the OVERWRITE on its next list-changed.
    client = _client(tmp_path)

    client.put("/sync/object/dev/d1/artifacts/a.enc", content=b"v1", headers=_auth())
    listing = client.get("/sync/objects", params={"since": 0}, headers=_auth()).json()
    cursor = listing["cursor"]  # the device has now pulled up to here

    # Nothing new at the head yet.
    assert (
        client.get("/sync/objects", params={"since": cursor}, headers=_auth()).json()["objects"]
        == []
    )

    # Overwrite the same name; it must reappear after the device's old cursor.
    client.put("/sync/object/dev/d1/artifacts/a.enc", content=b"v2", headers=_auth())
    after = client.get("/sync/objects", params={"since": cursor}, headers=_auth()).json()
    assert [o["name"] for o in after["objects"]] == ["dev/d1/artifacts/a.enc"]
    assert after["cursor"] > cursor
    got = client.get("/sync/object/dev/d1/artifacts/a.enc", headers=_auth())
    assert got.content == b"v2"


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


# ---- one relay, many libraries -------------------------------------------------------


def _admin_client(tmp_path, **kw):
    return TestClient(
        create_relay(tmp_path, secret="test-secret", admin_secret="admin-secret-0123456789", **kw)
    )


def _new_library(client, label="friend"):
    made = client.post(
        "/admin/libraries",
        json={"label": label},
        headers={"Authorization": "Bearer admin-secret-0123456789"},
    )
    assert made.status_code == 201
    return made.json()["secret"]


def test_two_libraries_never_see_or_touch_each_other(tmp_path):
    client = _admin_client(tmp_path)
    theirs = _new_library(client)

    # Both write the same shared names (the vault wrap, settings): no collision.
    client.put("/sync/object/lib/vault.enc", content=b"mine", headers=_auth())
    client.put("/sync/object/lib/vault.enc", content=b"theirs", headers=_auth(theirs))
    assert client.get("/sync/object/lib/vault.enc", headers=_auth()).content == b"mine"
    assert client.get("/sync/object/lib/vault.enc", headers=_auth(theirs)).content == b"theirs"

    client.put("/sync/object/dev/d1/artifacts/a.enc", content=b"a", headers=_auth())
    listed = client.get("/sync/objects", params={"since": 0}, headers=_auth(theirs)).json()
    assert [o["name"] for o in listed["objects"]] == ["lib/vault.enc"]
    assert (
        client.get("/sync/object/dev/d1/artifacts/a.enc", headers=_auth(theirs)).status_code == 404
    )

    # A delete reaches only the caller's own library.
    assert (
        client.delete("/sync/object/dev/d1/artifacts/a.enc", headers=_auth(theirs)).status_code
        == 404
    )
    assert client.get("/sync/object/dev/d1/artifacts/a.enc", headers=_auth()).content == b"a"

    # Cursors are per library: one library's writes say nothing of the other's.
    before = client.get("/sync/objects", params={"since": 0}, headers=_auth(theirs)).json()[
        "cursor"
    ]
    for i in range(5):
        client.put(f"/sync/object/blobs/{i}", content=b"x", headers=_auth())
    after = client.get("/sync/objects", params={"since": 0}, headers=_auth(theirs)).json()["cursor"]
    assert before == after


def test_a_change_notice_reaches_only_its_own_library():
    from enqueue.relay.app import RelayHub

    hub = RelayHub()
    mine, theirs = hub.subscribe("a"), hub.subscribe("b")
    hub.publish({"name": "x"}, "a")
    assert mine.qsize() == 1 and theirs.qsize() == 0


def test_an_unknown_or_revoked_secret_is_refused(tmp_path):
    client = _admin_client(tmp_path)
    assert client.get("/sync/objects", headers=_auth("made-up-secret")).status_code == 401
    assert client.get("/sync/events", params={"token": "made-up-secret"}).status_code == 401

    theirs = _new_library(client)
    assert client.get("/sync/objects", headers=_auth(theirs)).status_code == 200
    from enqueue.relay.storage import library_id

    admin = {"Authorization": "Bearer admin-secret-0123456789"}
    assert client.delete(f"/admin/libraries/{library_id(theirs)}", headers=admin).status_code == 204
    assert client.get("/sync/objects", headers=_auth(theirs)).status_code == 401
    listed = client.get("/admin/libraries", headers=admin).json()["libraries"]
    assert [lib["revoked_at"] is not None for lib in listed] == [False, True]
    assert all("secret" not in lib for lib in listed)


def test_the_admin_routes_are_off_without_an_admin_secret_and_need_it(tmp_path):
    plain = _client(tmp_path / "plain")
    assert plain.post("/admin/libraries", json={}).status_code == 404
    client = _admin_client(tmp_path / "admin")
    assert client.get("/admin/libraries", headers=_auth("wrong")).status_code == 401
    assert (
        client.get("/admin/libraries", headers=_auth()).status_code == 401
    )  # a library is not the admin


def test_a_single_library_relay_keeps_its_objects_when_it_learns_libraries(tmp_path):
    import sqlite3

    with sqlite3.connect(tmp_path / "relay.db") as conn:
        conn.execute(
            "CREATE TABLE objects (name TEXT PRIMARY KEY, data BLOB NOT NULL, cursor INTEGER NOT NULL)"
        )
        conn.execute("CREATE INDEX idx_objects_cursor ON objects(cursor)")
        conn.execute("INSERT INTO objects VALUES ('dev/d1/artifacts/a.enc', x'0102', 7)")

    client = _admin_client(tmp_path)
    listed = client.get("/sync/objects", params={"since": 0}, headers=_auth()).json()
    assert listed == {"objects": [{"name": "dev/d1/artifacts/a.enc", "size": 2}], "cursor": 7}
    assert client.get("/sync/objects", params={"since": 7}, headers=_auth()).json()["objects"] == []
    admin = {"Authorization": "Bearer admin-secret-0123456789"}
    first = client.get("/admin/libraries", headers=admin).json()["libraries"][0]
    assert first["used_bytes"] == 2 and first["objects"] == 1


def test_an_object_too_large_or_a_full_library_is_refused(tmp_path):
    client = _admin_client(tmp_path, max_object_bytes=10, quota_bytes=15)
    assert client.put("/sync/object/blobs/a", content=b"x" * 11, headers=_auth()).status_code == 413
    assert client.put("/sync/object/blobs/a", content=b"x" * 10, headers=_auth()).status_code == 201
    assert client.put("/sync/object/blobs/b", content=b"x" * 6, headers=_auth()).status_code == 413
    # Overwriting counts only the difference, and a delete frees room.
    assert client.put("/sync/object/blobs/a", content=b"x" * 9, headers=_auth()).status_code == 201
    assert client.delete("/sync/object/blobs/a", headers=_auth()).status_code == 204
    assert client.put("/sync/object/blobs/b", content=b"x" * 10, headers=_auth()).status_code == 201


def test_a_public_relay_will_not_start_with_a_weak_secret(tmp_path):
    from typer.testing import CliRunner

    from enqueue.cli import app

    out = CliRunner().invoke(
        app, ["relay", "--host", "0.0.0.0", "--data-dir", str(tmp_path), "--secret", "dev-secret"]
    )
    assert out.exit_code == 1 and "weak secret" in (out.stdout + (out.stderr or ""))


def test_setup_refuses_a_password_the_relay_does_not_know(tmp_path, monkeypatch):
    """A shared relay opens only the libraries it issued: a made-up secret is refused at
    setup instead of being stored and failing every sync after."""
    import pytest
    from fastapi import HTTPException

    from enqueue import keyring
    from enqueue.api import settings as api_settings

    stored = []
    monkeypatch.setattr(keyring, "sync_secret_set", stored.append)
    monkeypatch.setattr(api_settings, "_relay_refuses", lambda url, secret: secret != "good")
    with pytest.raises(HTTPException) as refused:
        api_settings.store_sync_secret(
            api_settings.SyncSecret(secret="made-up", relay_url="https://relay.example")
        )
    assert refused.value.status_code == 400 and stored == []


def test_the_access_log_never_holds_a_secret(tmp_path):
    import logging

    from enqueue.relay.app import create_relay

    create_relay(tmp_path, secret="s" * 30)
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "GET", "/sync/events?since=4&token=the-library-password", "1.1", 200),
        None,
    )
    for f in logging.getLogger("uvicorn.access").filters:
        f.filter(record)
    line = record.getMessage()
    assert "the-library-password" not in line
    assert "token=***" in line and "since=4" in line
