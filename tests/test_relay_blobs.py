"""The relay's object bytes in a blob store (Cloudflare R2), the index in SQLite.

Every storage rule holds the same with the bytes in the file or in the blob store; the
blob store here is an in-memory fake with the same four calls, and the R2 adapter
itself is run against moto's S3.
"""

from __future__ import annotations

import sqlite3
import threading
import time

import boto3
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from moto import mock_aws

from enqueue.relay import accounts as accounts_mod
from enqueue.relay import blobs as blobs_mod
from enqueue.relay.accounts import AccountSettings
from enqueue.relay.app import create_relay
from enqueue.relay.blobs import BlobStoreError, R2BlobStore
from enqueue.relay.storage import LibraryFull, RelayStorage, library_id


class FakeBlobs:
    """An in-memory bucket. `fail_puts_after` makes every put past that many fail;
    `corrupt` makes reads come back changed."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.lock = threading.Lock()
        self.puts = 0
        self.fail_puts_after: int | None = None
        self.fail_deletes = False
        self.corrupt = False

    def put(self, key, data):
        with self.lock:
            if self.fail_puts_after is not None and self.puts >= self.fail_puts_after:
                raise BlobStoreError("blob store put failed: down")
            self.puts += 1
            self.objects[key] = bytes(data)

    def get(self, key):
        data = self.objects.get(key)
        if data is not None and self.corrupt:
            return data + b"!"
        return data

    def delete(self, key):
        if self.fail_deletes:
            raise BlobStoreError("blob store delete failed: down")
        self.objects.pop(key, None)

    def delete_prefix(self, prefix):
        if self.fail_deletes:
            raise BlobStoreError("blob store delete failed: down")
        gone = [k for k in self.objects if k.startswith(prefix)]
        for k in gone:
            del self.objects[k]
        return len(gone)

    def under(self, library):
        return {k: v for k, v in self.objects.items() if k.startswith(f"{library}/")}


LIB = library_id("first")
OTHER = library_id("second")


def _storage(tmp_path, blobs=None, quota=0):
    s = RelayStorage(tmp_path, legacy_library=LIB, default_quota=quota, blobs=blobs)
    with s._open() as conn:
        s._register(conn, OTHER, "second")
    return s


def _file_holds(tmp_path, needle: bytes) -> bool:
    return any(needle in p.read_bytes() for p in tmp_path.glob("relay.db*"))


@pytest.mark.parametrize("in_r2", [False, True], ids=["in-file", "in-r2"])
def test_every_storage_rule_holds_wherever_the_bytes_live(tmp_path, in_r2):
    blobs = FakeBlobs() if in_r2 else None
    s = _storage(tmp_path, blobs, quota=100)

    assert s.put(LIB, "dev/a/x.enc", b"one") == (1, 3)
    assert s.put(LIB, "dev/a/y.enc", b"twenty") == (2, 6)
    # An upsert takes a fresh cursor at the head of the feed.
    assert s.put(LIB, "dev/a/x.enc", b"three") == (3, 5)
    assert s.get(LIB, "dev/a/x.enc") == b"three"
    assert s.list_changed(LIB, 0) == (
        [{"name": "dev/a/y.enc", "size": 6}, {"name": "dev/a/x.enc", "size": 5}],
        3,
    )
    assert s.list_changed(LIB, 2) == ([{"name": "dev/a/x.enc", "size": 5}], 3)
    assert s.used_bytes(LIB) == 11

    # Another library sees none of it, and has its own cursor.
    assert s.get(OTHER, "dev/a/x.enc") is None
    assert s.list_changed(OTHER, 0) == ([], 0)
    assert s.put(OTHER, "dev/a/x.enc", b"theirs") == (1, 6)
    assert s.get(LIB, "dev/a/x.enc") == b"three"

    # The limit counts what an overwrite replaces.
    s.put(LIB, "dev/a/x.enc", b"z" * 94)
    with pytest.raises(LibraryFull):
        s.put(LIB, "dev/a/x.enc", b"z" * 95)
    assert s.get(LIB, "dev/a/x.enc") == b"z" * 94 and s.used_bytes(LIB) == 100

    assert s.delete(LIB, "dev/a/x.enc") and not s.delete(LIB, "dev/a/x.enc")
    assert s.get(LIB, "dev/a/x.enc") is None and s.used_bytes(LIB) == 6
    if in_r2:
        # One copy per live object, nothing left behind by overwrites or deletes.
        assert sorted(blobs.under(LIB).values()) == [b"twenty"]
        assert sorted(blobs.under(OTHER).values()) == [b"theirs"]


def test_with_r2_the_file_holds_only_the_index(tmp_path):
    blobs = FakeBlobs()
    s = _storage(tmp_path, blobs)
    secret = b"ciphertext-only-in-r2-" * 10
    s.put(LIB, "dev/a/x.enc", secret)
    assert not _file_holds(tmp_path, secret)
    (key,) = blobs.under(LIB)
    # <library>/<hash of the name>/<generation>: the name itself never reaches R2.
    lib, digest, gen = key.split("/")
    assert lib == LIB and len(digest) == 64 and "x.enc" not in key and gen


def test_a_full_library_uploads_nothing(tmp_path):
    blobs = FakeBlobs()
    s = _storage(tmp_path, blobs, quota=4)
    with pytest.raises(LibraryFull):
        s.put(LIB, "dev/a/x.enc", b"12345")
    assert blobs.objects == {} and blobs.puts == 0


def test_an_upload_that_fails_changes_nothing_and_answers_503(tmp_path):
    blobs = FakeBlobs()
    s = _storage(tmp_path, blobs)
    s.put(LIB, "dev/a/x.enc", b"old")
    blobs.fail_puts_after = blobs.puts
    with pytest.raises(BlobStoreError):
        s.put(LIB, "dev/a/x.enc", b"new")
    assert s.get(LIB, "dev/a/x.enc") == b"old"
    assert s.list_changed(LIB, 0)[1] == 1 and s.used_bytes(LIB) == 3

    client = TestClient(create_relay(tmp_path / "app", secret="s" * 30, blob_store=blobs))
    resp = client.put(
        "/sync/object/dev/a/y.enc", content=b"x", headers={"Authorization": f"Bearer {'s' * 30}"}
    )
    assert resp.status_code == 503


def test_a_copy_gone_from_r2_is_an_error_not_a_missing_object(tmp_path):
    blobs = FakeBlobs()
    s = _storage(tmp_path, blobs)
    s.put(LIB, "dev/a/x.enc", b"data")
    blobs.objects.clear()
    with pytest.raises(BlobStoreError):
        s.get(LIB, "dev/a/x.enc")
    blobs_back = FakeBlobs()
    s2 = _storage(tmp_path / "b", blobs_back)
    s2.put(LIB, "dev/a/x.enc", b"data")
    blobs_back.corrupt = True
    with pytest.raises(BlobStoreError):
        s2.get(LIB, "dev/a/x.enc")


def test_concurrent_writes_of_one_name_leave_one_consistent_copy(tmp_path):
    blobs = FakeBlobs()
    s = _storage(tmp_path, blobs)
    payloads = [bytes([i]) * (i + 1) for i in range(20)]
    threads = [threading.Thread(target=s.put, args=(LIB, "dev/a/x.enc", p)) for p in payloads]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    got = s.get(LIB, "dev/a/x.enc")
    assert got in payloads
    assert s.list_changed(LIB, 0)[0] == [{"name": "dev/a/x.enc", "size": len(got)}]
    assert list(blobs.under(LIB).values()) == [got] and s.used_bytes(LIB) == len(got)


def test_the_move_into_r2_is_verified_resumable_and_runs_once(tmp_path):
    plain = _storage(tmp_path)
    for i in range(5):
        plain.put(LIB, f"dev/a/{i}.enc", f"object-number-{i}-".encode() * 20)
    plain.put(OTHER, "dev/b/0.enc", b"other-library-bytes-" * 20)
    before = {i: plain.get(LIB, f"dev/a/{i}.enc") for i in range(5)}
    feed = plain.list_changed(LIB, 0)

    blobs = FakeBlobs()
    blobs.fail_puts_after = 3  # the relay goes down mid-move
    s = _storage(tmp_path, blobs)
    with pytest.raises(BlobStoreError):
        s.move_to_blob_store()
    assert {i: s.get(LIB, f"dev/a/{i}.enc") for i in range(5)} == before

    blobs.fail_puts_after = None
    assert s.move_to_blob_store() == 3
    assert s.move_to_blob_store() == 0
    assert {i: s.get(LIB, f"dev/a/{i}.enc") for i in range(5)} == before
    # Same cursors and sizes; the bytes left the file.
    assert s.list_changed(LIB, 0) == feed
    assert not _file_holds(tmp_path, b"object-number-")
    assert not _file_holds(tmp_path, b"other-library-bytes-")
    assert s.used_bytes(LIB) == sum(len(v) for v in before.values())
    assert len(blobs.objects) == 6


def test_a_copy_that_reads_back_wrong_keeps_the_bytes_in_the_file(tmp_path):
    _storage(tmp_path).put(LIB, "dev/a/x.enc", b"keep-me")
    blobs = FakeBlobs()
    blobs.corrupt = True
    s = _storage(tmp_path, blobs)
    with pytest.raises(BlobStoreError):
        s.move_to_blob_store()
    blobs.corrupt = False
    assert s.get(LIB, "dev/a/x.enc") == b"keep-me" and blobs.objects == {}


def test_a_write_during_the_move_wins_over_the_moved_copy(tmp_path):
    _storage(tmp_path).put(LIB, "dev/a/x.enc", b"old-bytes")
    blobs = FakeBlobs()
    s = _storage(tmp_path, blobs)
    real_put = blobs.put

    def put_and_race(key, data):
        real_put(key, data)
        if data == b"old-bytes":
            # A device overwrites the object while its old copy is being moved.
            blobs.put = real_put
            s.put(LIB, "dev/a/x.enc", b"new-bytes")

    blobs.put = put_and_race
    assert s.move_to_blob_store() == 0
    assert s.get(LIB, "dev/a/x.enc") == b"new-bytes"
    assert list(blobs.objects.values()) == [b"new-bytes"]


def test_revoking_a_library_deletes_its_objects_everywhere(tmp_path):
    blobs = FakeBlobs()
    s = _storage(tmp_path, blobs)
    s.put(OTHER, "dev/a/x.enc", b"gone-soon")
    s.put(LIB, "dev/a/x.enc", b"stays")
    blobs.objects[f"{OTHER}/orphan/0"] = b"left by an earlier failure"
    blobs.fail_deletes = True
    assert s.revoke_library(OTHER)
    # The rows are gone at once; the bytes wait for the blob store to answer.
    assert s.list_changed(OTHER, 0) == ([], 0) and s.used_bytes(OTHER) == 0
    assert blobs.under(OTHER)
    blobs.fail_deletes = False
    assert s.purge_revoked() == 1 and s.purge_revoked() == 0
    assert blobs.under(OTHER) == {}
    assert s.get(LIB, "dev/a/x.enc") == b"stays"


def test_a_library_revoked_before_revoking_deleted_anything_is_cleared(tmp_path):
    s = _storage(tmp_path)
    s.put(OTHER, "dev/a/x.enc", b"old-revoked-bytes")
    with s._open() as conn:  # how an older relay revoked: the flag alone
        conn.execute("UPDATE libraries SET revoked_at = 1 WHERE id = ?", (OTHER,))
    s = _storage(tmp_path, FakeBlobs())
    assert s.move_to_blob_store() == 0  # revoked bytes are not moved, they are deleted
    assert s.purge_revoked() == 1
    with s._open() as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM objects WHERE library = ?", (OTHER,)).fetchone()[0]
            == 0
        )


def test_a_write_racing_a_revoke_leaves_nothing_behind(tmp_path):
    blobs = FakeBlobs()
    s = _storage(tmp_path, blobs)
    real_put = blobs.put

    def put_then_revoke(key, data):
        real_put(key, data)
        s.revoke_library(OTHER)

    blobs.put = put_then_revoke
    with pytest.raises(Exception, match="revoked"):
        s.put(OTHER, "dev/a/x.enc", b"late")
    assert blobs.under(OTHER) == {} and s.list_changed(OTHER, 0) == ([], 0)


def test_the_relay_moves_old_bytes_at_start_and_serves_meanwhile(tmp_path):
    secret = "a-long-first-library-secret"
    plain = TestClient(create_relay(tmp_path, secret=secret))
    auth = {"Authorization": f"Bearer {secret}"}
    assert (
        plain.put("/sync/object/lib/vault.enc", content=b"vault-bytes", headers=auth).status_code
        == 201
    )

    blobs = FakeBlobs()
    app = create_relay(tmp_path, secret=secret, blob_store=blobs)
    client = TestClient(app)
    assert client.get("/sync/object/lib/vault.enc", headers=auth).content == b"vault-bytes"
    deadline = time.time() + 5
    while not blobs.objects and time.time() < deadline:
        time.sleep(0.02)
    assert list(blobs.objects.values()) == [b"vault-bytes"]
    assert client.get("/sync/object/lib/vault.enc", headers=auth).content == b"vault-bytes"


def test_deleting_an_account_deletes_its_bytes_from_r2(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        accounts_mod.Accounts, "_signing_key", lambda self, token, url: key.public_key()
    )
    settings = AccountSettings(
        database_url=f"sqlite:///{tmp_path / 'accounts.db'}",
        jwt_secret="x" * 40,
        environment="test",
        google_client_id="web",
        rate_limit_per_min=1000,
    )
    blobs = FakeBlobs()
    client = TestClient(
        create_relay(
            tmp_path / "relay", secret="s" * 30, account_settings=settings, blob_store=blobs
        )
    )
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": "https://accounts.google.com",
            "aud": "web",
            "sub": "u1",
            "email": "a@example.com",
            "iat": now,
            "exp": now + 600,
        },
        key,
        algorithm="RS256",
    )
    session = client.post("/auth/google", json={"id_token": token}).json()
    bearer = {"Authorization": f"Bearer {session['access_token']}"}
    mac = client.post("/account/devices", json={"name": "Mac"}, headers=bearer).json()
    put = client.put(
        "/sync/object/lib/vault.enc",
        content=b"account-bytes",
        headers={"Authorization": f"Bearer {mac['relay_token']}"},
    )
    assert put.status_code == 201 and blobs.under(mac["library_id"])
    assert client.delete("/account", headers=bearer).status_code == 204
    assert blobs.under(mac["library_id"]) == {}


# ---- the R2 adapter, against moto's S3 ----------------------------------------------


@pytest.fixture
def r2():
    with mock_aws():
        client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        client.create_bucket(Bucket="enqueue-relay")
        yield R2BlobStore("enqueue-relay", client)


def test_the_r2_adapter_stores_reads_and_deletes(r2):
    r2.put("lib/aaa/1", b"\x00bytes\xff")
    assert r2.get("lib/aaa/1") == b"\x00bytes\xff"
    assert r2.get("lib/missing") is None
    r2.delete("lib/aaa/1")
    r2.delete("lib/aaa/1")  # deleting what is gone is fine
    assert r2.get("lib/aaa/1") is None


def test_the_r2_adapter_deletes_a_whole_library_page_by_page(r2):
    for i in range(1003):
        r2._client.put_object(Bucket="enqueue-relay", Key=f"gone/{i}", Body=b"x")
    r2.put("kept/0", b"y")
    assert r2.delete_prefix("gone/") == 1003
    assert r2.delete_prefix("gone/") == 0
    assert r2.get("kept/0") == b"y"


def test_the_r2_adapter_turns_a_refusal_into_a_blob_store_error():
    with mock_aws():
        client = boto3.client(
            "s3", region_name="us-east-1", aws_access_key_id="t", aws_secret_access_key="t"
        )
        with pytest.raises(BlobStoreError):
            R2BlobStore("no-such-bucket", client).put("k", b"v")


def test_r2_is_on_only_with_all_four_settings(monkeypatch):
    for name in blobs_mod.R2_VARS:
        monkeypatch.delenv(name, raising=False)
    assert blobs_mod.from_env() is None
    monkeypatch.setenv("R2_BUCKET", "enqueue-relay")
    with pytest.raises(RuntimeError, match="R2_ACCOUNT_ID"):
        blobs_mod.from_env()
    for name in blobs_mod.R2_VARS:
        monkeypatch.setenv(name, "x")
    store = blobs_mod.from_env()
    assert isinstance(store, R2BlobStore)
    assert store._client.meta.endpoint_url == "https://x.r2.cloudflarestorage.com"


def test_an_old_relay_file_gains_the_index_columns(tmp_path):
    conn = sqlite3.connect(tmp_path / "relay.db")
    conn.execute(
        "CREATE TABLE libraries (id TEXT PRIMARY KEY, label TEXT NOT NULL DEFAULT '',"
        " created_at REAL NOT NULL, revoked_at REAL, quota_bytes INTEGER,"
        " used_bytes INTEGER NOT NULL DEFAULT 0)"
    )
    conn.execute(
        "CREATE TABLE objects (library TEXT NOT NULL, name TEXT NOT NULL, data BLOB NOT NULL,"
        " cursor INTEGER NOT NULL, PRIMARY KEY (library, name))"
    )
    conn.execute("INSERT INTO libraries (id, created_at, used_bytes) VALUES (?, 0, 4)", (LIB,))
    conn.execute("INSERT INTO objects VALUES (?, 'dev/a/x.enc', x'01020304', 7)", (LIB,))
    conn.commit()
    conn.close()
    s = _storage(tmp_path)
    assert s.list_changed(LIB, 0) == ([{"name": "dev/a/x.enc", "size": 4}], 7)
    assert s.put(LIB, "dev/a/x.enc", b"12") == (8, 2) and s.used_bytes(LIB) == 2
