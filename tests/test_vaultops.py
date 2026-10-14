"""VAULT.3 - content is encrypted at rest when vaulted, decrypted on un-vault.

The security claim: a vaulted artifact's plaintext (body, title, blob bytes) is
absent from the local DB and blob store, and only the vault key recovers it.
"""

from __future__ import annotations


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
        return conn.execute(
            "SELECT body, title, vaulted_at FROM artifacts WHERE id = ?", (aid,)
        ).fetchone()
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


def test_editing_a_vaulted_note_reseals_and_stays_out_of_the_index(monkeypatch):
    """Editing in the vault must re-encrypt on save: no plaintext body, title, or prior
    version reaches disk, and the note is never re-submitted to the index."""
    import enqueue.sync.client as sc

    monkeypatch.setattr(sc, "push_artifact", lambda *_a, **_k: None)
    import enqueue.ingest.queue as iq

    submitted = []
    monkeypatch.setattr(iq, "submit", lambda aid: submitted.append(aid))

    aid = notes.create(body="original secret body")["artifact"]["id"]
    vaultops.vault_artifact(aid)
    submitted.clear()  # ignore the create's own submit; we only care about the edit

    out = notes.edit(aid, body="updated secret body", title="My Secret")

    # The caller gets plaintext back, so the editor renders the words, not base64.
    assert out["artifact"]["body"] == "updated secret body"
    assert out["artifact"]["title"] == "My Secret"

    # On disk everything is ciphertext - new body, new title, and the prior version.
    row = _db_row(aid)
    assert row["vaulted_at"] is not None
    assert "updated secret body" not in (row["body"] or "")
    assert "My Secret" not in (row["title"] or "")
    disk = config.DB_PATH.read_bytes()
    assert b"updated secret body" not in disk
    assert b"original secret body" not in disk

    # The vault reader decrypts the new content back.
    got = vaultops.get(aid)
    assert got["artifact"]["body"] == "updated secret body"
    assert got["artifact"]["title"] == "My Secret"

    # A vaulted edit never re-enters the search index.
    assert submitted == []


def test_editing_a_vaulted_note_while_locked_is_refused(monkeypatch):
    """No key, no write: a locked vault refuses the edit rather than leaking plaintext."""
    import enqueue.sync.client as sc

    monkeypatch.setattr(sc, "push_artifact", lambda *_a, **_k: None)

    aid = notes.create(body="secret body")["artifact"]["id"]
    vaultops.vault_artifact(aid)
    vault.lock()

    with pytest.raises(ValueError):
        notes.edit(aid, body="attempted edit while locked")

    # Nothing changed; the sealed body still decrypts to the original once unlocked.
    vault.unlock("123456")
    assert vaultops.get(aid)["artifact"]["body"] == "secret body"


# ---- what was derived from a vaulted artifact -----------------------------------------
# A summary says in plain words what the sealed text is about, so vaulting has to
# reach it too: what a model wrote is removed, what the person or the page said is sealed.

SECRET = "The offshore account number is 7741 and nobody knows."


def _derive(aid: str) -> None:
    """Give an artifact the rows ingest and a preview fetch would have written."""
    now = db.now()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO facets (id, artifact_id, level, statement, model_version, trust,"
            " body_version, edited) VALUES ('f-m', ?, 1, 'A note about an offshore account.',"
            " 'm', 0.5, ?, 0)",
            (aid, now),
        )
        conn.execute(
            "INSERT INTO facets (id, artifact_id, level, statement, model_version, trust,"
            " body_version, edited) VALUES ('f-e', ?, 1, 'My hidden money line.', 'edited',"
            " 1.0, ?, 1)",
            (aid, now),
        )
        conn.execute(
            "INSERT INTO entities (id, artifact_id, entity, fact, model_version, body_version,"
            " trust) VALUES ('e-1', ?, 'Cayman Bank', 'An offshore bank.', 'm', ?, 0.5)",
            (aid, now),
        )
        conn.execute(
            "INSERT INTO sections (id, artifact_id, ordinal, summary, model_version,"
            " body_version, created_at) VALUES ('s-1', ?, 0, 'Section about hidden money.',"
            " 'm', ?, ?)",
            (aid, now, now),
        )
        conn.execute(
            "INSERT INTO derived_values (scope, subject, attribute, value, grounded, source,"
            " model_version, created_at) VALUES ('section_summary', ?, 'h', 'Cached offshore"
            " summary.', 1, 'model', 'm', ?)",
            (aid, now),
        )
        conn.execute(
            "INSERT INTO link_previews (artifact_id, status, title, description, site_name,"
            " fetched_at) VALUES (?, 'ok', 'Offshore banking guide', 'How to hide money',"
            " 'bank.example', ?)",
            (aid, now),
        )


def _all_text(aid: str) -> str:
    conn = db.get_conn()
    try:
        out = []
        for table, cols in (
            ("facets", "statement"),
            ("entities", "entity || ' ' || fact"),
            ("sections", "summary"),
            ("link_previews", "coalesce(title,'') || ' ' || coalesce(description,'')"),
        ):
            # nosemgrep - table and column names are literals from the tuple above
            for r in conn.execute(f"SELECT {cols} AS t FROM {table} WHERE artifact_id = ?", (aid,)):
                out.append(r["t"] or "")
        for r in conn.execute("SELECT value FROM derived_values WHERE subject = ?", (aid,)):
            out.append(r["value"])
        return "\n".join(out)
    finally:
        conn.close()


def test_vaulting_leaves_nothing_readable_that_was_derived_from_the_text():
    aid = notes.create(body=SECRET)["artifact"]["id"]
    _derive(aid)

    vaultops.vault_artifact(aid)

    left = _all_text(aid).lower()
    for word in ("offshore", "hidden", "money", "cayman", "bank"):
        assert word not in left, word
    disk = config.DB_PATH.read_bytes().lower()
    for phrase in (b"offshore account", b"hidden money", b"cayman bank", b"offshore banking guide"):
        assert phrase not in disk, phrase


def test_your_own_summary_line_and_the_preview_come_back_on_unvault():
    aid = notes.create(body=SECRET)["artifact"]["id"]
    _derive(aid)
    vaultops.vault_artifact(aid)

    vaultops.unvault_artifact(aid)

    conn = db.get_conn()
    try:
        lines = [r["statement"] for r in conn.execute("SELECT statement FROM facets")]
        preview = conn.execute("SELECT title, description, site_name FROM link_previews").fetchone()
    finally:
        conn.close()
    assert lines == ["My hidden money line."], "the model's line is written again by ingest"
    assert tuple(preview) == ("Offshore banking guide", "How to hide money", "bank.example")


def test_items_vaulted_by_an_older_build_are_cleaned(monkeypatch):
    aid = notes.create(body=SECRET)["artifact"]["id"]
    vaultops.vault_artifact(aid)
    _derive(aid)  # what an older build left beside a sealed artifact
    pushed = []
    monkeypatch.setattr(vaultops, "push_artifact", lambda i, *a, **k: pushed.append(i))

    # At startup the vault is locked: what a model wrote can still go.
    vault.lock()
    assert vaultops.scrub() > 0
    left = _all_text(aid)
    assert "A note about an offshore account." not in left
    assert "Cayman" not in left and "Cached offshore" not in left
    assert "My hidden money line." in left, "the person's own line waits for the key"

    # Once the vault is opened, the rest is sealed.
    vault.unlock("123456")
    assert vaultops.scrub() > 0
    left = _all_text(aid).lower()
    assert "hidden money" not in left and "offshore banking" not in left
    assert pushed and set(pushed) == {aid}, "the cleaned item is sent to the other devices"
    assert vaultops.scrub() == 0, "nothing left to do the second time"


def test_a_vaulted_snapshot_replaces_the_readable_summary_on_another_device():
    from enqueue.sync import snapshot

    aid = notes.create(body=SECRET)["artifact"]["id"]
    _derive(aid)
    vaultops.vault_artifact(aid)
    conn = db.get_conn()
    try:
        vaulted = snapshot.read_artifact_snapshot(conn, aid)
    finally:
        conn.close()
    assert all("offshore" not in f["statement"].lower() for f in vaulted["facets"])

    # Another device still holds the readable lines it had before the item was vaulted,
    # and the vaulted snapshot it receives carries no summary lines at all.
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO facets (id, artifact_id, level, statement, model_version, trust,"
            " body_version, edited) VALUES ('f-old', ?, 1, 'A note about an offshore account.',"
            " 'm', 0.5, ?, 0)",
            (aid, db.now()),
        )
        snapshot.apply_snapshot(conn, vaulted | {"facets": []})
    conn = db.get_conn()
    try:
        left = conn.execute("SELECT COUNT(*) FROM facets WHERE artifact_id = ?", (aid,)).fetchone()[
            0
        ]
    finally:
        conn.close()
    assert left == 0


def test_the_library_is_closed_to_other_accounts(store):
    import stat

    notes.create(body="anything")
    (config.DATA_DIR / "settings.json").write_text("{}")
    config.DATA_DIR.chmod(0o755)
    config.DB_PATH.chmod(0o644)

    assert db.restrict_permissions() >= 2

    mode = lambda p: stat.S_IMODE(p.stat().st_mode)  # noqa: E731
    assert mode(config.DATA_DIR) == 0o700
    assert mode(config.DB_PATH) == 0o600
    assert mode(config.DATA_DIR / "settings.json") == 0o600
    assert db.restrict_permissions() == 0
