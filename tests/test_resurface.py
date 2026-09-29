"""Resurfacing: which older note comes back to the wall today."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from enqueue import db, opens, resurface

TODAY = date(2026, 9, 29)


def _ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _note(aid: str, days_old: int, title: str | None = None) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, status, created_at,"
            " updated_at) VALUES (?, 'note', ?, 'Some words about it.', ?, 'ok', ?, ?)",
            (aid, title or f"Note {aid}", aid, _ago(days_old), _ago(days_old)),
        )


def _link(a: str, b: str, score: float) -> None:
    with db.transaction() as conn:
        for x, y in ((a, b), (b, a)):
            conn.execute(
                "INSERT INTO related (artifact_id, related_id, score, model_version, created_at)"
                " VALUES (?, ?, ?, 'm', ?)",
                (x, y, score, db.now()),
            )


def test_nothing_old_enough_means_nothing(store):
    _note("fresh", 3)
    assert resurface.pick(TODAY) is None


def test_an_old_quiet_note_comes_back_and_the_pick_holds_for_the_day(store):
    for i in range(5):
        _note(f"old{i}", 40 + i)
    _note("fresh", 2)

    first = resurface.pick(TODAY)

    assert first["id"].startswith("old")
    assert first["reason"]["kind"] == "saved"
    assert resurface.pick(TODAY) == first


def test_a_recently_opened_note_is_left_alone(store):
    _note("opened", 60)
    _note("quiet", 60)
    opens.record("opened", "wall")

    assert resurface.pick(TODAY)["id"] == "quiet"


def test_a_note_linked_to_a_recent_save_wins(store):
    for i in range(5):
        _note(f"old{i}", 50)
    _note("new", 1, title="Kiln log")
    _link("new", "old3", 0.82)

    chosen = resurface.pick(TODAY)

    assert chosen == {
        "id": "old3",
        "reason": {"kind": "related", "via_id": "new", "via_title": "Kiln log"},
    }


def test_the_endpoint_returns_a_wall_item_and_its_reason(store):
    from enqueue.api.app import create_app

    client = TestClient(create_app())
    assert client.get("/resurface").json() == {"item": None, "reason": None}

    _note("old", 30)
    body = client.get("/resurface").json()

    assert body["item"]["id"] == "old"
    assert body["item"]["excerpt"]
    assert body["reason"]["kind"] == "saved"
