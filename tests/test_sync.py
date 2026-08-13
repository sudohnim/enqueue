"""The sync plaintext-prototype guard (SYNC.3b) and the push client (SYNC.4).

While the unencrypted prototype is on, the sync client must refuse any relay
URL whose host is not loopback or a private-LAN address, so it can never upload
to a real or hosted relay. And editing an artifact pushes its snapshot to the
relay, idempotently. The flag flips off only in SYNC.9, after encryption.
"""

from __future__ import annotations

import httpx
import pytest

from enqueue import crypto, db, keyring, keyring_file, notes, settings
from enqueue.relay.app import create_relay
from enqueue.sync import guard
from enqueue.sync.client import pull, push_artifact
from enqueue.sync.snapshot import deserialize, read_artifact_snapshot


@pytest.fixture(autouse=True)
def _reset_dek():
    keyring_file._dek = None
    yield
    keyring_file._dek = None


def test_a_non_local_url_is_now_accepted():
    # SYNC.9: the flag is off (encryption is in), so a hosted relay is allowed.
    assert guard.SYNC_PLAINTEXT_PROTOTYPE is False
    guard.assert_local_relay("https://relay.example/v1")  # must not raise


def test_loopback_and_lan_urls_pass():
    for url in (
        "http://127.0.0.1:8788",
        "http://localhost:8788",
        "http://192.168.1.5:8788",
        "http://10.0.0.2:8788",
        "http://172.16.0.1:8788",
        "http://[::1]:8788",
    ):
        guard.assert_local_relay(url)  # must not raise


def test_an_empty_url_is_not_configured_and_passes():
    guard.assert_local_relay("")  # sync off: no guard needed


class TestPush:
    """SYNC.4: editing an artifact pushes its snapshot to the relay, and
    re-pushing uploads nothing new."""

    def _serve(self, app):
        import socket
        import threading
        import time

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

    def test_edit_pushes_and_repush_is_a_noop(self, store, monkeypatch):
        base, server, thread = self._serve(create_relay(store / "relay", secret="test-secret"))
        try:
            settings.update({"sync_relay_url": base})
            monkeypatch.setattr(keyring, "sync_secret_get", lambda: "test-secret")
            keyring_file.initialize("pw")

            created = notes.create(body="hello relay")
            aid = created["artifact"]["id"]

            # The create path pushed the snapshot; the relay lists it under this
            # device's namespace.
            listing = httpx.get(
                base + "/sync/objects",
                headers={"Authorization": "Bearer test-secret"},
                timeout=5,
            ).json()
            obj_names = [o["name"] for o in listing["objects"]]
            assert len(obj_names) == 1, obj_names
            snap_name = obj_names[0]

            got = httpx.get(
                base + f"/sync/object/{snap_name}",
                headers={"Authorization": "Bearer test-secret"},
                timeout=5,
            )
            assert got.status_code == 200
            # SYNC.8: the relay holds ciphertext, never readable JSON.
            assert b"hello relay" not in got.content
            dek = keyring_file.dek()
            assert dek is not None
            snap = deserialize(crypto.decrypt(got.content, dek))
            assert snap["artifact"]["body"] == "hello relay"
            assert snap["artifact"]["_device_id"]

            # Re-pushing the unchanged snapshot uploads nothing new (409).
            push_artifact(aid)
            after = httpx.get(
                base + "/sync/objects",
                headers={"Authorization": "Bearer test-secret"},
                timeout=5,
            ).json()
            assert [o["name"] for o in after["objects"]] == obj_names
        finally:
            server.should_exit = True
            thread.join(timeout=5)

    def test_pull_applies_a_remote_snapshot(self, store, quiet_queue, monkeypatch):
        base, server, thread = self._serve(create_relay(store / "relay", secret="test-secret"))
        try:
            settings.update({"sync_relay_url": base})
            monkeypatch.setattr(keyring, "sync_secret_get", lambda: "test-secret")
            keyring_file.initialize("pw")

            # Device A: create a note (which pushes it).
            created = notes.create(body="# Title\n\nBody text")
            aid = created["artifact"]["id"]

            conn = db.get_conn()
            try:
                original = read_artifact_snapshot(conn, aid)
            finally:
                conn.close()

            # Simulate device B: an empty library for this artifact and a
            # different device id (so pull does not skip device A's namespace).
            with db.transaction() as tx:
                tx.execute("DELETE FROM annotations WHERE artifact_id = ?", (aid,))
                tx.execute("DELETE FROM page_text WHERE artifact_id = ?", (aid,))
                tx.execute("DELETE FROM artifact_versions WHERE artifact_id = ?", (aid,))
                tx.execute("DELETE FROM artifacts WHERE id = ?", (aid,))
            (store / "device_id").unlink(missing_ok=True)
            # A fresh cursor so pull sees the relay object.
            (store / "sync_cursor").write_text("0")

            result = pull()
            assert result["pulled"] == 1

            conn = db.get_conn()
            try:
                restored = read_artifact_snapshot(conn, aid)
            finally:
                conn.close()
            # Byte-identical to what device A holds, including _device_id.
            assert restored == original
        finally:
            server.should_exit = True
            thread.join(timeout=5)
