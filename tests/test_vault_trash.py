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
