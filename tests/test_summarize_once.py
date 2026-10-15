"""Two desktops on one library read each item with the model once.

Before, a desktop that pulled the other's items wrote its own named things, section
summaries and passage placements for every one of them (only the summary lines
travelled), and rewrote the summary lines too whenever its ingest model differed: a
second Mac spent the same credits again. Now every model-written layer rides the
artifact's snapshot, a layer counts as current by the body it was written from (not
the model), and a pulled item waits for the device that wrote it.
"""

from __future__ import annotations

import pytest

from enqueue import config, db, notes
from enqueue.index.store import get_store
from enqueue.ingest import facets as facets_mod
from enqueue.ingest import queue as q
from enqueue.ingest import source
from enqueue.sync import client
from enqueue.sync.snapshot import apply_pulled_snapshot, derived_layers, read_artifact_snapshot

BODY = "\n\n".join(
    f"## Day {i} in Lisbon\n\n"
    + f"Walked through Alfama on day {i} and ate grilled sardines. " * 12
    for i in range(6)
)


class _Model:
    """Answers every ingest step, and counts the calls."""

    name = "fake"

    def __init__(self, model: str):
        self.model = model
        self.calls: list[str] = []

    def complete(self, system, user, response_model, context=None, max_retries=None):
        name = response_model.__name__
        self.calls.append(name)
        if name == "_RawSectionSummary":
            return response_model(summary="A day of walking and eating in Lisbon.")
        if name == "_RawFacetSet":
            return response_model(
                facets=[
                    {"level": 1, "statement": "A travel diary of slow days spent on foot."},
                    {"level": 2, "statement": "Walking a city reveals it better than touring it."},
                ]
            )
        if name == "_RawEntitySet":
            return response_model(entities=[{"name": "Lisbon"}])
        if name == "_RawFactSet":
            return response_model(
                facts=[
                    {
                        "name": "Lisbon",
                        "fact": "Lisbon is the hilly capital city of Portugal on the Tagus river.",
                    }
                ]
            )
        if name == "_RawChunkContextSet":
            n = user.split("Chunks:")[1].count("\n[") + 1
            return response_model(
                contexts=[
                    {"index": i, "context": f"One day of the Lisbon diary ({i})."}
                    for i in range(1, n + 1)
                ]
            )
        raise AssertionError(f"unexpected model call {name}")


class _Mac:
    """One desktop: its own data folder, database and search index."""

    def __init__(self, root, name, monkeypatch, model):
        self.dir = root / name
        self.dir.mkdir()
        self.monkeypatch = monkeypatch
        self.model = _Model(model)

    def use(self):
        import enqueue.providers.base as base_mod

        self.monkeypatch.setattr(config, "DATA_DIR", self.dir)
        self.monkeypatch.setattr(config, "DB_PATH", self.dir / "enqueue.db")
        self.monkeypatch.setattr(config, "BLOB_DIR", self.dir / "blobs")
        self.monkeypatch.setattr(base_mod, "get_provider", lambda **kw: self.model)
        db.reset_migration_state()
        db.migrate()
        get_store.cache_clear()
        get_store().ensure()
        return self


@pytest.fixture
def macs(tmp_path, monkeypatch, quiet_queue):
    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    # A diary long enough to be read in sections, cut into several passages.
    monkeypatch.setattr(config, "FACET_INPUT_CHARS", 2000)
    monkeypatch.setattr(source, "SECTION_CHARS", 1500)
    monkeypatch.setattr(client, "push_artifact", lambda aid: None)
    personal = _Mac(tmp_path, "personal", monkeypatch, "kimi-k3")
    work = _Mac(tmp_path, "work", monkeypatch, "another-model")
    yield personal, work
    get_store.cache_clear()
    db.reset_migration_state()


def _snapshot(aid):
    conn = db.get_conn()
    try:
        snap = read_artifact_snapshot(conn, aid)
    finally:
        conn.close()
    snap["artifact"]["_device_id"] = "device-" + config.DATA_DIR.name
    return snap


def _pull(snapshot):
    """What sync/client.py's pull does with one artifact object."""
    with db.transaction() as conn:
        apply_pulled_snapshot(conn, snapshot)
    client._ingest_pulled({snapshot["artifact"]["id"]: "entities" in snapshot})


def _layers(aid):
    conn = db.get_conn()
    try:
        return derived_layers(conn, aid)
    finally:
        conn.close()


def _retry(aid):
    conn = db.get_conn()
    try:
        return conn.execute("SELECT * FROM facet_retry WHERE artifact_id = ?", (aid,)).fetchone()
    finally:
        conn.close()


def test_the_second_mac_takes_every_layer_and_calls_no_model(macs):
    personal, work = macs
    personal.use()
    aid = notes.create(body=BODY)["artifact"]["id"]
    q.process(aid)
    assert {"_RawSectionSummary", "_RawFacetSet", "_RawFactSet", "_RawChunkContextSet"} <= set(
        personal.model.calls
    )
    written = _layers(aid)
    assert written["entities"] and written["sections"] and written["chunk_contexts"]
    snapshot = _snapshot(aid)

    work.use()
    _pull(snapshot)
    q.process(aid)

    assert work.model.calls == []
    assert _layers(aid) == written
    conn = db.get_conn()
    try:
        placed = conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE artifact_id = ? AND context IS NULL", (aid,)
        ).fetchone()["n"]
        assert facets_mod.is_current(conn, aid)
    finally:
        conn.close()
    assert placed == 0  # every passage took the placement written on the other Mac
    assert _retry(aid) is None

    from enqueue.retrieve.candidates import search_results

    assert any(r["artifact_id"] == aid for r in search_results("Alfama sardines"))


def test_a_pulled_note_waits_for_the_mac_that_wrote_it(macs, monkeypatch):
    personal, work = macs
    monkeypatch.setattr(config, "PEER_SUMMARY_WAIT_S", 1800)
    personal.use()
    aid = notes.create(body=BODY)["artifact"]["id"]
    unsummarized = _snapshot(aid)  # pushed as typed, before the quiet wait ran
    q.process(aid)
    summarized = _snapshot(aid)

    work.use()
    _pull(unsummarized)
    q.process(aid)
    assert work.model.calls == []
    assert _retry(aid)["last_error"] == q.AWAITING
    conn = db.get_conn()
    try:  # indexed for its words already, while the summary waits
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE artifact_id = ?", (aid,)
        ).fetchone()["n"]
    finally:
        conn.close()

    _pull(summarized)
    q.process(aid)
    assert work.model.calls == []
    assert _retry(aid) is None


def test_a_note_from_the_phone_is_summarized_by_one_desktop(macs, monkeypatch):
    personal, work = macs
    personal.use()
    aid = notes.create(body=BODY)["artifact"]["id"]
    phone = _snapshot(aid)
    for key in ("entities", "sections", "section_cache", "chunk_contexts", "related_verdicts"):
        phone.pop(key)  # a phone never sends these

    work.use()
    _pull(phone)
    q.process(aid)  # PEER_PHONE_WAIT_S is 0 in tests: this desktop's turn came first
    assert "_RawFacetSet" in work.model.calls
    from_work = _snapshot(aid)

    personal.use()
    _pull(from_work)
    q.process(aid)
    assert personal.model.calls == []


def test_a_phone_snapshot_never_wipes_what_a_desktop_wrote(macs):
    personal, _ = macs
    personal.use()
    aid = notes.create(body=BODY)["artifact"]["id"]
    q.process(aid)
    written = _layers(aid)
    phone = _snapshot(aid)
    for key in ("entities", "sections", "section_cache", "chunk_contexts", "related_verdicts"):
        phone.pop(key)
    phone["artifact"]["updated_at"] = "2999-01-01T00:00:00+00:00"

    _pull(phone)
    assert _layers(aid) == written


def test_a_vaulted_snapshot_leaves_nothing_readable_behind(macs):
    personal, _ = macs
    personal.use()
    aid = notes.create(body=BODY)["artifact"]["id"]
    q.process(aid)
    vaulted = _snapshot(aid)
    vaulted["artifact"]["vaulted_at"] = "2999-01-01T00:00:00+00:00"
    vaulted["artifact"]["updated_at"] = "2999-01-01T00:00:00+00:00"
    vaulted.update(
        entities=[], sections=[], section_cache=[], chunk_contexts=[], related_verdicts=[]
    )

    with db.transaction() as conn:
        apply_pulled_snapshot(conn, vaulted)
        left = {
            table: conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE artifact_id = ?", (aid,)
            ).fetchone()["n"]
            for table in ("entities", "sections")
        }
        cached = conn.execute(
            "SELECT COUNT(*) AS n FROM derived_values WHERE subject = ?"
            " AND scope IN ('section_summary', 'chunk_context')",
            (aid,),
        ).fetchone()["n"]
    assert left == {"entities": 0, "sections": 0} and cached == 0
