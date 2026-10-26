"""Brain food: which notes from different fields share the wall each day, and their words."""

from __future__ import annotations

from datetime import date

import pytest

from enqueue import brainfood, db, trash

TODAY = date(2026, 10, 26)
BODY = "What I wrote down in my own words."


@pytest.fixture(autouse=True)
def _fresh_state():
    brainfood._failed.clear()
    brainfood._writing.clear()


def _note(aid: str, subject: str = "", local_only: bool = False) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, status, created_at,"
            " updated_at, local_only) VALUES (?, 'note', ?, ?, ?, 'ok', ?, ?, ?)",
            (aid, f"Note {aid}", BODY, aid, db.now(), db.now(), int(local_only)),
        )
        if subject:
            conn.execute(
                "INSERT INTO facets (id, artifact_id, level, statement, model_version, trust)"
                " VALUES (?, ?, 1, ?, 'm', 0.5)",
                (f"f-{aid}", aid, subject),
            )


def _link(a: str, b: str, kind: str, distance: float, point=None, via=None) -> None:
    with db.transaction() as conn:
        for x, y in ((a, b), (b, a)):
            conn.execute(
                "INSERT INTO related (artifact_id, related_id, score, model_version,"
                " created_at, via, point, kind, distance) VALUES (?,?,0.8,'m',?,?,?,?,?)",
                (x, y, db.now(), via, point, kind, distance),
            )


class _Writer:
    model = "chat-model"

    def __init__(self, error=None):
        self.error, self.calls, self.local = error, [], []

    def complete(self, system, user, response_model, **kwargs):
        self.calls.append(user)
        if self.error:
            raise self.error
        ids = [line.split(": ", 1)[1] for line in user.splitlines() if line.startswith("note id")]
        return response_model(
            idea="Things last by bending instead of holding firm.",
            parts=[{"id": i, "how": f"{i} bends to last."} for i in ids],
            question="Where in your week are you holding firm when bending would last longer?",
        )


@pytest.fixture
def writer(monkeypatch):
    from enqueue.providers import base

    w = _Writer()

    def provider(local_only=False, **kw):
        w.local.append(local_only)
        return w

    monkeypatch.setattr(base, "get_provider", provider)
    return w


def test_nothing_without_a_relationship_across_fields(store):
    _note("a")
    _note("b")
    _link("a", "b", "subject", 0.1, point="Same book.")

    assert brainfood.pick(TODAY) is None


def test_an_idea_link_is_preferred_and_the_farthest_first(store):
    for aid in "abcd":
        _note(aid)
    _link("a", "b", "mention", 0.9, via="Seneca")
    _link("c", "d", "idea", 0.6, point="Both say bending outlasts resisting.")

    for n in range(3):  # every day, while an idea link exists
        chosen = brainfood.pick(date.fromordinal(TODAY.toordinal() + n))
        assert set(chosen["ids"]) == {"c", "d"}


def test_a_shared_name_across_fields_serves_when_there_is_no_idea(store, writer):
    for aid in "ab":
        _note(aid)
    _link("a", "b", "mention", 0.9, via="Seneca")

    out = brainfood.today(TODAY, background=False)

    assert set(out["ids"]) == {"a", "b"}


def test_the_same_day_gives_the_same_set_and_days_rotate(store):
    for aid in "abcdef":
        _note(aid)
    _link("a", "b", "idea", 0.9, point="Both one.")
    _link("c", "d", "idea", 0.8, point="Both two.")
    _link("e", "f", "idea", 0.7, point="Both three.")

    assert brainfood.pick(TODAY) == brainfood.pick(TODAY)
    days = {
        tuple(sorted(brainfood.pick(date.fromordinal(TODAY.toordinal() + n))["ids"]))
        for n in range(3)
    }
    assert len(days) == 3


def test_a_third_note_joins_through_another_idea_link(store):
    for aid in "abc":
        _note(aid)
    _link("a", "b", "idea", 0.9, point="Both one.")
    _link("b", "c", "idea", 0.5, point="Both two.")

    chosen = brainfood.pick(TODAY)

    assert sorted(chosen["ids"]) == ["a", "b", "c"]
    assert chosen["ids"][1] == "b"  # the note that links to both sits in the middle
    assert len(chosen["links"]) == 2


def test_trashed_and_vaulted_notes_never_appear(store):
    for aid in "abcd":
        _note(aid)
    _link("a", "b", "idea", 0.9, point="Both one.")
    _link("c", "d", "idea", 0.8, point="Both two.")
    trash.delete("a")
    with db.transaction() as conn:
        conn.execute("UPDATE artifacts SET vaulted_at = ? WHERE id = 'c'", (db.now(),))

    assert brainfood.pick(TODAY) is None


def test_the_model_writes_the_words_once_and_they_are_cached(store, writer):
    _note("a", "A willow in a storm.")
    _note("b", "Releasing software in small steps.")
    _link("a", "b", "idea", 0.8, point="Both say bending outlasts resisting.")

    first = brainfood.today(TODAY, background=False)
    again = brainfood.today(TODAY, background=False)

    assert first["food"]["idea"] == "Things last by bending instead of holding firm."
    assert first["food"]["parts"] == {"a": "a bends to last.", "b": "b bends to last."}
    assert first["food"]["question"].endswith("?")
    assert again["food"] == first["food"]
    assert len(writer.calls) == 1
    assert "A willow in a storm." in writer.calls[0]
    assert BODY not in writer.calls[0]  # the notes' own text is never sent


def test_without_a_model_the_card_shows_the_links_own_words(store, writer):
    writer.error = RuntimeError("no model")
    _note("a")
    _note("b")
    _link("a", "b", "idea", 0.8, point="Both say bending outlasts resisting.")

    out = brainfood.today(TODAY, background=False)

    assert out["food"] == {
        "idea": "Both say bending outlasts resisting.",
        "parts": {},
        "question": brainfood.FALLBACK_QUESTION,
    }
    brainfood.today(TODAY, background=False)
    assert len(writer.calls) == 1  # a failed set is not asked again the same day


def test_a_set_with_a_local_only_note_uses_the_local_model(store, writer):
    _note("a", local_only=True)
    _note("b")
    _link("a", "b", "idea", 0.8, point="Both one.")

    brainfood.today(TODAY, background=False)

    assert writer.local == [True]


def test_purging_a_note_drops_its_cached_words(store, writer):
    _note("a")
    _note("b")
    _link("a", "b", "idea", 0.8, point="Both one.")
    brainfood.today(TODAY, background=False)
    trash.delete("a")
    trash.purge("a")

    conn = db.get_conn()
    try:
        left = conn.execute("SELECT COUNT(*) FROM derived_values WHERE scope = 'brain_food'")
        assert left.fetchone()[0] == 0
    finally:
        conn.close()


def test_the_endpoint_serves_wall_items(store, writer, monkeypatch):
    from fastapi.testclient import TestClient

    from enqueue.api.app import create_app

    client = TestClient(create_app())
    assert client.get("/brainfood").json()["notes"] == []

    _note("a")
    _note("b")
    _link("a", "b", "idea", 0.8, point="Both one.")
    real = brainfood.today
    monkeypatch.setattr(brainfood, "today", lambda: real(TODAY, background=False))
    body = client.get("/brainfood").json()

    assert sorted(n["id"] for n in body["notes"]) == ["a", "b"]
    assert body["food"]["idea"] == "Things last by bending instead of holding firm."
    assert body["writing"] is False
