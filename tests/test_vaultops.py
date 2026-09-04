"""VAULT.3 - content is encrypted at rest when vaulted, decrypted on un-vault.

The security claim: a vaulted artifact's plaintext (body, title, blob bytes) is
absent from the local DB and blob store, and only the vault key recovers it.
"""

from __future__ import annotations

import json

import pytest

from enqueue import config, db, notes, vault, vaultops


@pytest.fixture(autouse=True)
def _vault(store, monkeypatch):
    # Isolate from sync + the ingest pipeline; we test the crypto, not re-index.
    monkeypatch.setattr(vaultops, "push_artifact", lambda *_a, **_k: None)
    import enqueue.ingest.queue as iq

    monkeypatch.setattr(iq, "submit", lambda *_a, **_k: None)
    vault.lock()
    vault.setup("123456")
    yield
    vault.lock()


def _db_row(aid):
    conn = db.get_conn()
    try:
        return conn.execute("SELECT body, title, vaulted_at FROM artifacts WHERE id = ?", (aid,)).fetchone()
    finally:
        conn.close()


def test_vaulting_a_note_encrypts_body_and_title_at_rest():
    created = notes.create(body="the secret is 42")
    aid = created["artifact"]["id"]
    plain_title = created["artifact"]["title"]

    vaultops.vault_artifact(aid)

    row = _db_row(aid)
    assert row["vaulted_at"] is not None
    # The plaintext is gone from the row; the columns hold opaque base64 ciphertext.
    assert row["body"] != "the secret is 42"
    assert "the secret is 42" not in (row["body"] or "")
    assert row["title"] != plain_title
    # And gone from the whole DB file on disk.
    disk = (config.DB_PATH).read_bytes()
    assert b"the secret is 42" not in disk

    # The vault reader decrypts it back.
    got = vaultops.get(aid)
    assert got["artifact"]["body"] == "the secret is 42"
    assert got["artifact"]["title"] == plain_title


def test_unvault_restores_plaintext():
    created = notes.create(body="restore me exactly")
    aid = created["artifact"]["id"]
    title = created["artifact"]["title"]
    vaultops.vault_artifact(aid)
    vaultops.unvault_artifact(aid)
    row = _db_row(aid)
    assert row["vaulted_at"] is None
    assert row["body"] == "restore me exactly"
    assert row["title"] == title


def test_vaulting_drops_chunks_from_the_index():
    created = notes.create(body="indexable body text here")
    aid = created["artifact"]["id"]
    conn = db.get_conn()
    try:
        conn.execute(
            "INSERT INTO chunks (id, artifact_id, ordinal, text, chunker) VALUES (?,?,?,?,?)",
            ("c1", aid, 0, "indexable body text here", "test"),
        )
        conn.commit()
    finally:
        conn.close()
    vaultops.vault_artifact(aid)
    conn = db.get_conn()
    try:
        n = conn.execute("SELECT COUNT(*) FROM chunks WHERE artifact_id = ?", (aid,)).fetchone()[0]
    finally:
        conn.close()
    assert n == 0


def test_blob_is_encrypted_at_rest_and_decrypts_on_read():
    raw = b"\xff\xd8\xff pretend jpeg secret pixels"
    content_hash = "cafe" * 16  # 64 hex
    config.BLOB_DIR.mkdir(parents=True, exist_ok=True)
    (config.BLOB_DIR / content_hash).write_bytes(raw)
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts"
            " (id,kind,title,body,source_url,content_hash,mime,filename,created_at,updated_at,"
            "  local_only,status,pinned,deleted_at,pages,title_explicit)"
            " VALUES ('img1','image','photo',NULL,NULL,?, 'image/jpeg','photo.jpg',"
            "  '2099-01-01T00:00:00+00:00','2099-01-01T00:00:00+00:00',0,'ok',0,NULL,NULL,0)",
            (content_hash,),
        )

    vaultops.vault_artifact("img1")
    on_disk = (config.BLOB_DIR / content_hash).read_bytes()
    assert on_disk != raw and raw not in on_disk  # ciphertext at rest

    dec = vaultops.blob_bytes("img1")
    assert dec is not None
    data, mime, _name = dec
    assert data == raw
    assert mime == "image/jpeg"

    vaultops.unvault_artifact("img1")
    assert (config.BLOB_DIR / content_hash).read_bytes() == raw  # plaintext restored


def test_operations_require_an_unlocked_vault():
    created = notes.create(body="x")
    aid = created["artifact"]["id"]
    vault.lock()
    with pytest.raises(vault.VaultError):
        vaultops.vault_artifact(aid)
