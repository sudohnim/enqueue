"""Original files are sealed on disk once the recovery kit is saved, and read back whole."""

import hashlib

import pytest

from enqueue import blobstore, capture, config, libkey


@pytest.fixture
def kit_saved(store, monkeypatch):
    libkey.get()  # a saved kit means the key exists
    monkeypatch.setattr(libkey, "kit_saved", lambda: True)


def test_files_stay_plain_until_the_kit_is_saved(store):
    h = blobstore.write(b"hello there")
    assert (config.BLOB_DIR / h).read_bytes() == b"hello there"


def test_a_file_is_sealed_and_reads_back(kit_saved):
    data = b"%PDF-1.4 secret words " * 100_000  # over one chunk
    h = blobstore.write(data)
    on_disk = (config.BLOB_DIR / h).read_bytes()
    assert b"secret words" not in on_disk and on_disk.startswith(blobstore.MAGIC)
    blobstore._RECENT.clear()
    assert blobstore.read(h) == data
    assert blobstore.size(h) == len(data)


def test_older_plain_files_are_sealed_in_place(store, monkeypatch):
    h = blobstore.write(b"from before")
    libkey.get()
    monkeypatch.setattr(libkey, "kit_saved", lambda: True)
    assert blobstore.seal_all() == 1
    assert b"from before" not in (config.BLOB_DIR / h).read_bytes()
    blobstore._RECENT.clear()
    assert blobstore.read(h) == b"from before"
    assert blobstore.seal_all() == 0


def test_a_changed_byte_is_refused(kit_saved):
    h = blobstore.write(b"x" * 5000)
    file = config.BLOB_DIR / h
    raw = bytearray(file.read_bytes())
    raw[-3] ^= 1
    file.write_bytes(bytes(raw))
    blobstore._RECENT.clear()
    with pytest.raises(blobstore.BlobError):
        blobstore.read(h)


def test_a_captured_file_is_served_from_its_plaintext(kit_saved, quiet_queue):
    from fastapi.testclient import TestClient

    from enqueue.api.app import create_app

    data = b"plain text inside a file\n"
    made = capture.upload(data, "notes.txt", "text/plain")
    digest = hashlib.sha256(data).hexdigest()
    assert data not in (config.BLOB_DIR / digest).read_bytes()
    got = TestClient(create_app()).get(f"/artifacts/{made['id']}/blob")
    assert got.status_code == 200 and got.content == data
