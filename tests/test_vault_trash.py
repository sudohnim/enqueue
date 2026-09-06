"""Deleting/restoring a vaulted item must never leave vault-ciphertext in the trash.

The rule: content is encrypted at rest IFF `vaulted_at` is set. So a vaulted item that
leaves the vault by being deleted is decrypted out first - the trash holds the readable
original and restore brings back a normal note. A still-sealed row (an orphan from an
older build, or a locked view) is shown as a neutral label, never raw ciphertext.
"""

from __future__ import annotations

import pytest

from enqueue import db, notes, trash, vault, vaultops


@pytest.fixture(autouse=True)
def _vault(store, monkeypatch):
    # Test the crypto + trash bookkeeping, not sync or re-index.
    monkeypatch.setattr(vaultops, "push_artifact", lambda *_a, **_k: None)
    monkeypatch.setattr(trash, "push_artifact", lambda *_a, **_k: None)
    import enqueue.ingest.queue as iq

    monkeypatch.setattr(iq, "submit", lambda *_a, **_k: None)
    vault.lock()
    vault.setup("123456")
    yield
    vault.lock()


def _row(aid):
    conn = db.get_conn()
    try:
        return conn.execute(
            "SELECT body, title, vaulted_at, deleted_at FROM artifacts WHERE id = ?", (aid,)
        ).fetchone()
    finally:
        conn.close()


def test_delete_vaulted_item_lands_decrypted_in_trash():
    created = notes.create(body="the account number is 8675309")
    aid = created["artifact"]["id"]
    title = created["artifact"]["title"]
    vaultops.vault_artifact(aid)
    assert _row(aid)["vaulted_at"] is not None  # sealed

    trash.delete(aid)  # vault is unlocked

    row = _row(aid)
    assert row["deleted_at"] is not None
    assert row["vaulted_at"] is None  # left the vault
    assert row["body"] == "the account number is 8675309"  # decrypted at rest
    # The trash listing shows the real title, not ciphertext.
    items = {i["id"]: i for i in trash.listing()["items"]}
    assert items[aid]["title"] == title


def test_restore_gives_back_the_original_note():
    created = notes.create(body="secret plans")
    aid = created["artifact"]["id"]
    title = created["artifact"]["title"]
    vaultops.vault_artifact(aid)
    trash.delete(aid)

    trash.restore(aid)

    row = _row(aid)
    assert row["deleted_at"] is None
    assert row["vaulted_at"] is None
    assert row["body"] == "secret plans"
    assert row["title"] == title


def _make_orphan(body: str) -> str:
    """A trashed row that is still vault-ciphertext but has vaulted_at CLEARED - the
    corrupt state an older partial un-vault left behind."""
    created = notes.create(body=body)
    aid = created["artifact"]["id"]
    key = vault.key()
    now = db.now()
    with db.transaction() as conn:
        conn.execute(
            "UPDATE artifacts SET body = ?, title = ?, vaulted_at = NULL, deleted_at = ? WHERE id = ?",
            (vaultops._seal(key, body), vaultops._seal(key, "Orphan title"), now, aid),
        )
    return aid


def test_locked_trash_never_shows_raw_ciphertext():
    # A flagged-vaulted, deleted row viewed while locked -> neutral label.
    created = notes.create(body="hidden")
    aid = created["artifact"]["id"]
    vaultops.vault_artifact(aid)
    now = db.now()
    with db.transaction() as conn:
        conn.execute("UPDATE artifacts SET deleted_at = ? WHERE id = ?", (now, aid))
    vault.lock()

    items = {i["id"]: i for i in trash.listing()["items"]}
    assert items[aid]["title"] == "Locked note"


def test_orphan_is_healed_when_viewed_and_restored_unlocked():
    aid = _make_orphan("orphaned secret")
    # Unlocked listing decrypts the orphan via the auth tag, showing the real title.
    items = {i["id"]: i for i in trash.listing()["items"]}
    assert items[aid]["title"] == "Orphan title"

    trash.restore(aid)
    row = _row(aid)
    assert row["deleted_at"] is None
    assert row["body"] == "orphaned secret"
    assert row["title"] == "Orphan title"


def test_vaulted_image_survives_delete_and_restore():
    import hashlib

    from enqueue import config

    raw = b"RIFF\x00\x00\x00\x00WEBP pretend pixels"
    content_hash = hashlib.sha256(raw).hexdigest()  # blobs are addressed by plaintext sha256
    _insert_image("img9", content_hash, raw)
    vaultops.vault_artifact("img9")
    assert (config.BLOB_DIR / content_hash).read_bytes() != raw  # encrypted at rest

    trash.delete("img9")  # unlocked -> decrypts the blob out
    assert (config.BLOB_DIR / content_hash).read_bytes() == raw  # plaintext image in trash

    trash.restore("img9")
    assert (config.BLOB_DIR / content_hash).read_bytes() == raw  # still the real image


def _insert_image(aid: str, content_hash: str, blob: bytes):
    from enqueue import config

    config.BLOB_DIR.mkdir(parents=True, exist_ok=True)
    (config.BLOB_DIR / content_hash).write_bytes(blob)
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts"
            " (id,kind,title,body,source_url,content_hash,mime,filename,created_at,updated_at,"
            "  local_only,status,pinned,deleted_at,pages,title_explicit)"
            " VALUES (?,'image','pic',NULL,NULL,?, 'image/webp','p.webp',"
            "  '2099-01-01T00:00:00+00:00','2099-01-01T00:00:00+00:00',0,'ok',0,NULL,NULL,0)",
            (aid, content_hash),
        )


def test_double_encrypted_blob_is_recovered_by_hash_verified_decrypt():
    import hashlib

    from enqueue import config, crypto

    raw = b"RIFF\x00\x00\x00\x00WEBP the real pixels"
    ch = hashlib.sha256(raw).hexdigest()
    key = vault.key()
    # A legacy double-encrypted blob (orphan re-vaulted over its own ciphertext).
    _insert_image("imgD", ch, crypto.encrypt(crypto.encrypt(raw, key), key))
    with db.transaction() as conn:
        vaultops.decrypt_in_place(conn, "imgD", key)
    assert (config.BLOB_DIR / ch).read_bytes() == raw  # peeled both layers, hash-verified


def test_blob_sealed_with_a_lost_key_is_left_untouched():
    import hashlib

    from enqueue import config, crypto

    raw = b"RIFF\x00\x00\x00\x00WEBP pixels"
    ch = hashlib.sha256(raw).hexdigest()
    lost_key = b"\x11" * 32  # not the vault key
    sealed = crypto.encrypt(raw, lost_key)
    _insert_image("imgL", ch, sealed)
    with db.transaction() as conn:
        vaultops.decrypt_in_place(conn, "imgL", vault.key())
    # Cannot recover with the wrong key, but must NOT write garbage - blob unchanged.
    assert (config.BLOB_DIR / ch).read_bytes() == sealed


def test_restore_flagged_vaulted_item_requires_unlock():
    created = notes.create(body="needs the key")
    aid = created["artifact"]["id"]
    vaultops.vault_artifact(aid)  # vaulted_at is set
    now = db.now()
    with db.transaction() as conn:
        conn.execute("UPDATE artifacts SET deleted_at = ? WHERE id = ?", (now, aid))
    vault.lock()
    with pytest.raises(ValueError):
        trash.restore(aid)  # flagged sealed + locked -> refuse
