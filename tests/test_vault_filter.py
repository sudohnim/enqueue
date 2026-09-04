"""VAULT.4 - a vaulted artifact is excluded from every live surface.

Characterized here on two concrete callables (export + the vault listing) plus the
raw wall/search WHERE clause; the full set of ~12 patched query sites all share
the same `vaulted_at IS NULL` predicate, so these stand in for the surface.
"""

from __future__ import annotations

import pytest

from enqueue import db, export, notes, vault, vaultops


@pytest.fixture(autouse=True)
def _vault(store, monkeypatch):
    monkeypatch.setattr(vaultops, "push_artifact", lambda *_a, **_k: None)
    import enqueue.ingest.queue as iq

    monkeypatch.setattr(iq, "submit", lambda *_a, **_k: None)
    vault.lock()
    vault.setup("123456")
    yield
    vault.lock()


def _live_ids():
    """Ids the wall/search would show: the shared VAULT.4 predicate."""
    conn = db.get_conn()
    try:
        return {
            r["id"]
            for r in conn.execute(
                "SELECT id FROM artifacts WHERE deleted_at IS NULL AND vaulted_at IS NULL"
            ).fetchall()
        }
    finally:
        conn.close()


def test_vaulted_artifact_leaves_the_live_set_and_enters_the_vault(tmp_path):
    a = notes.create(body="SECRET vault body alpha")["artifact"]
    b = notes.create(body="ordinary visible body beta")["artifact"]

    assert {a["id"], b["id"]} <= _live_ids()

    vaultops.vault_artifact(a["id"])

    live = _live_ids()
    assert a["id"] not in live  # gone from every wall/search query
    assert b["id"] in live  # the un-vaulted one is untouched

    # And it is the ONLY thing in the vault listing.
    vault_ids = {i["id"] for i in vaultops.listing()["items"]}
    assert vault_ids == {a["id"]}


def test_export_omits_vaulted_content(tmp_path):
    a = notes.create(body="SECRET vault body alpha")["artifact"]
    notes.create(body="ordinary visible body beta")
    vaultops.vault_artifact(a["id"])

    # Export to a dir OUTSIDE the store (tmp_path is DATA_DIR, which holds the DB +
    # keyring - scanning those would see the legitimately-encrypted row).
    out = tmp_path / "exported"
    export.export(out)

    # No exported file may contain the vaulted note's id or its (now-encrypted)
    # content; the visible note's content must be present.
    blob = ""
    for p in out.rglob("*"):
        if p.is_file():
            try:
                blob += p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                pass
    assert "SECRET vault body alpha" not in blob
    assert a["id"] not in blob
    assert "ordinary visible body beta" in blob


def test_unvault_returns_it_to_the_live_set(tmp_path):
    a = notes.create(body="round trip body")["artifact"]
    vaultops.vault_artifact(a["id"])
    assert a["id"] not in _live_ids()
    vaultops.unvault_artifact(a["id"])
    assert a["id"] in _live_ids()
    assert vaultops.listing()["items"] == []
