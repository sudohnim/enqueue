"""The artifact route's related list: "Show all", and the person's feedback on a link."""

from __future__ import annotations

from fastapi.testclient import TestClient

from enqueue import db
from enqueue.api.app import create_app
from enqueue.ingest import related


def _note(aid: str) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, status, created_at,"
            " updated_at) VALUES (?, 'note', ?, 'x', ?, 'ok', ?, ?)",
            (aid, f"Note {aid}", aid, db.now(), db.now()),
        )


def _link(a: str, b: str, kind: str = "subject") -> None:
    with db.transaction() as conn:
        for x, y in ((a, b), (b, a)):
            conn.execute(
                "INSERT INTO related (artifact_id, related_id, owner, score, model_version,"
                " created_at, kind, distance) VALUES (?, ?, ?, 0.8, 'm', ?, ?, 0.3)",
                (x, y, a, db.now(), kind),
            )


def _client() -> TestClient:
    return TestClient(create_app(), base_url="http://127.0.0.1:8787")


def test_show_all_lists_every_stored_link(store):
    _note("a")
    for n in range(7):
        _note(f"b{n}")
        _link("a", f"b{n}")
    client = _client()

    first = client.get("/artifacts/a").json()
    every = client.get("/artifacts/a?related=all").json()

    assert len(first["related"]) == related.RELATED_LIMIT
    assert first["related_more"] == 7 - related.RELATED_LIMIT
    assert len(every["related"]) == 7 and every["related_more"] == 0


def test_refusing_a_link_removes_it_and_keeping_puts_it_first(store):
    for aid in ("a", "b", "c"):
        _note(aid)
    _link("a", "b", "idea")
    _link("a", "c", "idea")
    client = _client()

    assert (
        client.post("/related/feedback", json={"a": "a", "b": "x", "verdict": "maybe"}).status_code
        == 400
    )
    client.post("/related/feedback", json={"a": "a", "b": "b", "verdict": "no", "idea": "Both x."})
    client.post("/related/feedback", json={"a": "a", "b": "c", "verdict": "keep"})
    rows = client.get("/artifacts/a").json()["related"]

    assert [(r["id"], r["kept"]) for r in rows] == [("c", True)]
    conn = db.get_conn()
    try:
        assert related.refused(conn, "a") == {"b"}
    finally:
        conn.close()


def test_an_items_links_ride_its_snapshot_and_a_local_one_sends_none(store):
    from enqueue.sync import snapshot

    for aid in ("a", "b"):
        _note(aid)
    _link("a", "b")
    conn = db.get_conn()
    try:
        layers = snapshot.derived_layers(conn, "a")
        assert {(r["artifact_id"], r["related_id"]) for r in layers["related"]} == {
            ("a", "b"),
            ("b", "a"),
        }
        conn.execute("DELETE FROM related")
        snapshot._apply_derived_layers(
            conn, "a", {"artifact": {"id": "a", "updated_at": db.now()}, **layers}, False
        )
        assert conn.execute("SELECT COUNT(*) FROM related WHERE owner = 'a'").fetchone()[0] == 2
        conn.execute("UPDATE artifacts SET local_only = 1 WHERE id = 'a'")
        assert snapshot.derived_layers(conn, "a")["related"] == []
    finally:
        conn.close()
