"""Regression lock-down for the mobile capture/sync saga fixed this cycle.

These pin the behaviours that were painfully debugged and are easy to break
again - especially by the upcoming VAULT work, which touches the same
build_snapshot / apply_snapshot / pull / blob surface:

  1. A poison snapshot (one that fails to apply) must NOT wedge the pull: it is
     skipped, the rest of the batch applies, and the cursor advances past it.
     (The real incident: a duplicate content_hash raised IntegrityError, the
     exception escaped pull()'s loop, the cursor never advanced, and NOTHING
     synced after it.)
  2. A foreign snapshot whose content_hash duplicates a local artifact is the
     concrete poison from (1) and must be tolerated, not fatal.
  3. The desktop fetches a blob it does not have locally from the relay on
     demand (fetch_blob_to_cache), and blob_path fetches-on-miss - without this
     a phone photo synced its row but never its bytes and /blob 404'd.

The fixtures mirror tests/test_sync.py: a real uvicorn relay on a random port,
the `store` temp-dir fixture, and keyring_file.initialize() for the DEK.
"""

from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest

from enqueue import capture, crypto, db, keyring, keyring_file, notes, settings
from enqueue.relay.app import create_relay
from enqueue.sync import device_id
from enqueue.sync.client import fetch_blob_to_cache, pull
from enqueue.sync.snapshot import read_artifact_snapshot, serialize


@pytest.fixture(autouse=True)
def _reset_dek():
    keyring_file._dek = None
    yield
    keyring_file._dek = None


def _serve(app):
    """Run `app` on a random loopback port; return (base_url, server, thread)."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
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


def _configure(base, monkeypatch):
    settings.update({"sync_relay_url": base})
    monkeypatch.setattr(keyring, "sync_secret_get", lambda: "test-secret")
    keyring_file.initialize()
    return keyring_file.dek()


def _put(base, name, body: bytes):
    r = httpx.put(
        base + f"/sync/object/{name}",
        content=body,
        headers={
            "Authorization": "Bearer test-secret",
            "Content-Type": "application/octet-stream",
        },
        timeout=5,
    )
    assert r.status_code in (201, 409), r.status_code


def _foreign_note_snapshot(*, aid: str, body: str, content_hash: str, updated_at: str) -> dict:
    """A minimal note snapshot as another device would push it."""
    return {
        "artifact": {
            "id": aid,
            "kind": "note",
            "title": body[:40] or "note",
            "body": body,
            "source_url": None,
            "content_hash": content_hash,
            "mime": None,
            "filename": None,
            "created_at": updated_at,
            "updated_at": updated_at,
            "local_only": 0,
            "status": "ok",
            "pinned": 0,
            "deleted_at": None,
            "pages": None,
            "title_explicit": 0,
            "_device_id": "device-FOREIGN",
            "purged_at": None,
        },
        "annotations": [],
        "page_text": [],
        "versions": [],
        "tags": [],
    }


class TestPullResilience:
    def test_a_poison_snapshot_is_skipped_and_the_cursor_advances(self, store, monkeypatch):
        """One un-appliable object must not block the rest of the feed."""
        base, server, thread = _serve(create_relay(store / "relay", secret="test-secret"))
        try:
            dek = _configure(base, monkeypatch)

            # A local note. Its content_hash is what the poison will collide with.
            local = notes.create(body="local original")
            local_hash = local["artifact"]["content_hash"]

            newer = "2099-01-01T00:00:00+00:00"
            # POISON: a DIFFERENT foreign artifact reusing the local content_hash.
            # apply_snapshot's INSERT violates artifacts.content_hash UNIQUE.
            poison = _foreign_note_snapshot(
                aid="poison-dup-hash",
                body="poison",
                content_hash=local_hash,
                updated_at=newer,
            )
            # GOOD: a well-formed foreign note the pull must still apply.
            good = _foreign_note_snapshot(
                aid="good-foreign",
                body="good foreign note",
                content_hash="hash-unique-good",
                updated_at=newer,
            )
            _put(base, "dev/device-FOREIGN/artifacts/poison-dup-hash.enc", crypto.encrypt(serialize(poison), dek))
            _put(base, "dev/device-FOREIGN/artifacts/good-foreign.enc", crypto.encrypt(serialize(good), dek))

            # Pull must NOT raise, must apply the good one, and must advance the cursor.
            result = pull()
            assert result.get("skipped", 0) >= 1  # the poison was skipped, not fatal
            assert read_artifact_snapshot(db.get_conn(), "good-foreign") is not None

            # The cursor advanced past the poison: a second pull is a clean no-op,
            # never re-hitting the poison (the wedge symptom was pulled==0 forever).
            again = pull()
            assert again["pulled"] == 0
        finally:
            server.should_exit = True
            thread.join(timeout=5)

    def test_a_duplicate_content_hash_pull_does_not_wedge(self, store, monkeypatch):
        """The exact incident: a foreign dup-hash object leaves local data intact
        and the pull still completes."""
        base, server, thread = _serve(create_relay(store / "relay", secret="test-secret"))
        try:
            dek = _configure(base, monkeypatch)
            local = notes.create(body="keep me")
            local_id = local["artifact"]["id"]
            local_hash = local["artifact"]["content_hash"]

            dup = _foreign_note_snapshot(
                aid="dup-of-local",
                body="dup",
                content_hash=local_hash,
                updated_at="2099-01-01T00:00:00+00:00",
            )
            _put(base, "dev/device-FOREIGN/artifacts/dup-of-local.enc", crypto.encrypt(serialize(dup), dek))

            pull()  # must not raise

            # The local artifact is untouched; the duplicate did not overwrite it.
            still = read_artifact_snapshot(db.get_conn(), local_id)
            assert still is not None
            assert still["artifact"]["body"] == "keep me"
        finally:
            server.should_exit = True
            thread.join(timeout=5)


class TestBlobFetchOnMiss:
    def test_fetch_blob_to_cache_downloads_and_decrypts(self, store, monkeypatch):
        base, server, thread = _serve(create_relay(store / "relay", secret="test-secret"))
        try:
            dek = _configure(base, monkeypatch)
            raw = b"\x89PNG fake image bytes"
            content_hash = "deadbeef" * 8  # 64 hex chars
            # The relay holds the blob encrypted under the DEK, named by HMAC(hash).
            _put(base, f"blobs/{crypto.blob_name(content_hash, dek)}", crypto.encrypt(raw, dek))

            assert not (store / "blobs" / content_hash).exists()
            assert fetch_blob_to_cache(content_hash) is True
            assert (store / "blobs" / content_hash).read_bytes() == raw
        finally:
            server.should_exit = True
            thread.join(timeout=5)

    def test_blob_path_fetches_from_relay_on_local_miss(self, store, monkeypatch):
        base, server, thread = _serve(create_relay(store / "relay", secret="test-secret"))
        try:
            dek = _configure(base, monkeypatch)
            raw = b"pretend-jpeg-bytes"
            content_hash = "abad1dea" * 8

            # An image row with a content_hash but NO local blob (a pulled-only
            # artifact from another device).
            with db.transaction() as conn:
                conn.execute(
                    "INSERT INTO artifacts"
                    " (id,kind,title,body,source_url,content_hash,mime,filename,"
                    "  created_at,updated_at,local_only,status,pinned,deleted_at,pages,title_explicit)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,0,'ok',0,NULL,NULL,0)",
                    (
                        "img-remote",
                        "image",
                        "photo.jpg",
                        None,
                        None,
                        content_hash,
                        "image/jpeg",
                        "photo.jpg",
                        "2099-01-01T00:00:00+00:00",
                        "2099-01-01T00:00:00+00:00",
                    ),
                )
            _put(base, f"blobs/{crypto.blob_name(content_hash, dek)}", crypto.encrypt(raw, dek))

            found = capture.blob_path("img-remote")
            assert found is not None, "blob_path should fetch-on-miss, not 404"
            path, mime, _filename = found
            assert path.read_bytes() == raw
            assert mime == "image/jpeg"
        finally:
            server.should_exit = True
            thread.join(timeout=5)
