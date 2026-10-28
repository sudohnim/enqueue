"""Something shiny: which notes from different fields share the wall each day, and their words."""

from __future__ import annotations

from datetime import date

import pytest

from enqueue import db, shiny, trash

TODAY = date(2026, 10, 26)
BODY = "What I wrote down in my own words."


@pytest.fixture(autouse=True)
def _fresh_state():
    shiny._failed.clear()
    shiny._writing.clear()


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

    assert shiny.pick(TODAY) is None


def test_an_idea_link_is_preferred_and_the_farthest_first(store):
    for aid in "abcd":
        _note(aid)
    _link("a", "b", "mention", 0.9, via="Seneca")
    _link("c", "d", "idea", 0.6, point="Both say bending outlasts resisting.")

    for n in range(3):  # every day, while an idea link exists
        chosen = shiny.pick(date.fromordinal(TODAY.toordinal() + n))
        assert set(chosen["ids"]) == {"c", "d"}


def test_a_shared_name_across_fields_serves_when_there_is_no_idea(store, writer):
    for aid in "ab":
        _note(aid)
    _link("a", "b", "mention", 0.9, via="Seneca")

    out = shiny.today(TODAY, background=False)

    assert set(out["ids"]) == {"a", "b"}


def test_the_same_day_gives_the_same_set_and_days_rotate(store):
    for aid in "abcdef":
        _note(aid)
    _link("a", "b", "idea", 0.9, point="Both one.")
    _link("c", "d", "idea", 0.8, point="Both two.")
    _link("e", "f", "idea", 0.7, point="Both three.")

    assert shiny.pick(TODAY) == shiny.pick(TODAY)
    days = {
        tuple(sorted(shiny.pick(date.fromordinal(TODAY.toordinal() + n))["ids"])) for n in range(3)
    }
    assert len(days) == 3


def test_a_third_note_joins_through_another_idea_link(store):
    for aid in "abc":
        _note(aid)
    _link("a", "b", "idea", 0.9, point="Both one.")
    _link("b", "c", "idea", 0.5, point="Both two.")

    chosen = shiny.pick(TODAY)

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

    assert shiny.pick(TODAY) is None


def test_the_model_writes_the_words_once_and_they_are_cached(store, writer):
    _note("a", "A willow in a storm.")
    _note("b", "Releasing software in small steps.")
    _link("a", "b", "idea", 0.8, point="Both say bending outlasts resisting.")

    first = shiny.today(TODAY, background=False)
    again = shiny.today(TODAY, background=False)

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

    out = shiny.today(TODAY, background=False)

    assert out["food"] == {
        "idea": "Both say bending outlasts resisting.",
        "parts": {},
        "question": shiny.FALLBACK_QUESTION,
    }
    shiny.today(TODAY, background=False)
    assert len(writer.calls) == 1  # a failed set is not asked again the same day


def test_a_set_with_a_local_only_note_reaches_no_model(store, writer):
    _note("a", local_only=True)
    _note("b")
    _link("a", "b", "idea", 0.8, point="Both one.")

    out = shiny.today(TODAY, background=False)

    assert writer.calls == []
    assert out["food"]["idea"] == "Both one."


def test_purging_a_note_drops_its_cached_words(store, writer):
    _note("a")
    _note("b")
    _link("a", "b", "idea", 0.8, point="Both one.")
    shiny.today(TODAY, background=False)
    trash.delete("a")
    trash.purge("a")

    conn = db.get_conn()
    try:
        left = conn.execute("SELECT COUNT(*) FROM derived_values WHERE scope = 'shiny'")
        assert left.fetchone()[0] == 0
    finally:
        conn.close()


def test_the_endpoint_serves_wall_items(store, writer, monkeypatch):
    from fastapi.testclient import TestClient

    from enqueue.api.app import create_app

    client = TestClient(create_app())
    assert client.get("/shiny").json()["notes"] == []

    _note("a")
    _note("b")
    _link("a", "b", "idea", 0.8, point="Both one.")
    real = shiny.today
    monkeypatch.setattr(shiny, "today", lambda n=0: real(TODAY, n=n, background=False))
    body = client.get("/shiny").json()

    assert sorted(n["id"] for n in body["notes"]) == ["a", "b"]
    assert body["food"]["idea"] == "Things last by bending instead of holding firm."
    assert body["writing"] is False


def test_find_another_walks_through_every_pair_then_stops(store, writer):
    for aid in "abcdef":
        _note(aid)
    _link("a", "b", "idea", 0.9, point="Both one.")
    _link("c", "d", "idea", 0.8, point="Both two.")
    _link("e", "f", "idea", 0.7, point="Both three.")

    seen = []
    n = 0
    while True:
        out = shiny.today(TODAY, n=n, background=False)
        seen.append(tuple(sorted(out["ids"])))
        if not out["more"]:
            break
        n += 1

    assert sorted(seen) == [("a", "b"), ("c", "d"), ("e", "f")]
    assert seen[0] == tuple(sorted(shiny.today(TODAY, background=False)["ids"]))
    assert shiny.today(TODAY, n=3, background=False) is None
    assert len(writer.calls) == 3  # each set's words written once


def test_find_another_reaches_past_the_daily_rotation(store):
    for i in range(shiny.ROTATE + 2):
        _note(f"x{i}")
        _note(f"y{i}")
        _link(f"x{i}", f"y{i}", "idea", 0.9 - i * 0.01, point="Both.")

    picks = [shiny.pick(TODAY, n)["ids"][0] for n in range(shiny.ROTATE + 2)]

    assert sorted(picks) == sorted(f"x{i}" for i in range(shiny.ROTATE + 2))
    assert shiny.pick(TODAY, shiny.ROTATE + 1)["more"] is False


def test_the_endpoint_takes_find_another(store, writer, monkeypatch):
    from fastapi.testclient import TestClient

    from enqueue.api.app import create_app

    for aid in "abcd":
        _note(aid)
    _link("a", "b", "idea", 0.9, point="Both one.")
    _link("c", "d", "idea", 0.8, point="Both two.")
    real = shiny.today
    monkeypatch.setattr(shiny, "today", lambda n=0: real(TODAY, n=n, background=False))
    client = TestClient(create_app())

    first, second = client.get("/shiny").json(), client.get("/shiny?n=1").json()

    assert first["more"] is True and second["more"] is False
    assert {n["id"] for n in first["notes"]} != {n["id"] for n in second["notes"]}
    assert client.get("/shiny?n=2").json()["notes"] == []


def test_find_another_never_shows_the_same_notes_again(store):
    for aid in "abc":
        _note(aid)
    _link("a", "b", "idea", 0.9, point="Both one.")
    _link("b", "c", "idea", 0.8, point="Both two.")

    first = shiny.pick(TODAY)

    assert sorted(first["ids"]) == ["a", "b", "c"]
    assert first["more"] is False  # b-c alone is already inside the first set
    assert shiny.pick(TODAY, 1) is None


def test_the_days_set_holds_still_while_new_links_arrive(store, writer):
    for aid in "abcd":
        _note(aid)
    _link("a", "b", "idea", 0.5, point="Both one.")
    first = shiny.pick(TODAY)
    _link("c", "d", "idea", 0.99, point="Both two.")  # farther, found later in the day
    assert shiny.pick(TODAY)["ids"] == first["ids"]
    assert shiny.pick(TODAY, 1) is None  # the new pair is not slipped in either
    shiny.look_again(TODAY)  # the card's "Look again" takes it into account
    shown = [set(shiny.pick(TODAY, n)["ids"]) for n in (0, 1)]
    assert {"c", "d"} in shown


def test_prepare_runs_once_a_day(store, writer):
    _note("a")
    _note("b")
    _link("a", "b", "idea", 0.8, point="Both one.")
    assert shiny.prepare(TODAY) is True
    assert shiny.prepare(TODAY) is False


# ---- the raven's hunt ------------------------------------------------------------------


def _idea(aid: str, line: str = "Things last by bending.") -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO facets (id, artifact_id, level, statement, model_version, trust)"
            " VALUES (?, ?, 2, ?, 'm', 0.5)",
            (f"i-{aid}", aid, line),
        )


class _Hunter:
    model = "chat-model"

    def __init__(self, keep):
        self.keep, self.calls = keep, []

    def complete(self, system, user, response_model, **kwargs):
        self.calls.append(user)
        seed = user.split("id: ", 1)[1].split("\n", 1)[0]
        keep = self.keep(seed, user)
        if not keep:
            return response_model()
        return response_model(
            keep=keep,
            idea="Things last by bending instead of holding firm.",
            parts=[{"id": i, "how": f"{i} bends to last."} for i in (seed, keep)],
            question="Where are you holding firm when bending would last longer?",
        )


@pytest.fixture
def hunter(monkeypatch):
    from enqueue.providers import base

    box = {}

    def make(keep, candidates):
        box["h"] = _Hunter(keep)
        monkeypatch.setattr(base, "get_provider", lambda **kw: box["h"])
        monkeypatch.setattr(
            shiny,
            "_candidates",
            lambda conn, seed: [
                {"id": c, "score": 0.7, "distance": 0.6, "mine": "m", "theirs": "t"}
                for c in candidates(seed)
            ],
        )
        return box["h"]

    return make


def _library(*ids):
    for aid in ids:
        _note(aid)
        _idea(aid)


def test_the_raven_finds_a_fresh_connection_and_remembers_it(store, hunter):
    import random

    _library("a", "b")
    h = hunter(
        lambda seed, user: "b" if seed == "a" else "a", lambda seed: ["b" if seed == "a" else "a"]
    )

    out = shiny.hunt(TODAY, random.Random(1))

    assert sorted(out["ids"]) == ["a", "b"]
    assert out["food"]["idea"].startswith("Things last")
    assert set(out["food"]["parts"]) == {"a", "b"}
    assert len(h.calls) == 1
    # Shown once, it is never hunted again within REMEMBER_DAYS.
    assert shiny.hunt(TODAY, random.Random(2)) == {"none": "nothing"}


def test_a_pair_the_daily_card_showed_is_not_hunted(store, hunter, writer):
    import random

    _library("a", "b")
    _link("a", "b", "idea", 0.8, point="Both one.")
    shiny.today(TODAY, background=False)
    hunter(lambda seed, user: "b", lambda seed: ["b" if seed == "a" else "a"])

    assert shiny.hunt(TODAY, random.Random(1)) == {"none": "nothing"}


def test_the_raven_fails_closed_when_nothing_truly_matches(store, hunter):
    import random

    _library("a", "b", "c")
    h = hunter(lambda seed, user: "", lambda seed: [i for i in ("a", "b", "c") if i != seed])

    assert shiny.hunt(TODAY, random.Random(1)) == {"none": "nothing"}
    assert len(h.calls) == shiny.HUNT_SEEDS


def test_a_seed_rests_and_local_only_notes_never_seed(store, hunter):
    import random

    _library("a", "b")
    _note("p", local_only=True)
    _idea("p")
    seeds = []
    hunter(lambda seed, user: seeds.append(seed) or "", lambda seed: ["x"])

    shiny.hunt(TODAY, random.Random(1))
    shiny.hunt(TODAY, random.Random(2))

    assert "p" not in seeds
    assert len(seeds) == len(set(seeds))  # each seed rests after its turn


def test_the_hunt_endpoint_serves_the_card(store, hunter):
    from fastapi.testclient import TestClient

    from enqueue.api import app

    _library("a", "b")
    hunter(
        lambda seed, user: "b" if seed == "a" else "a", lambda seed: ["b" if seed == "a" else "a"]
    )

    out = TestClient(app).post("/shiny/hunt").json()

    assert out["hunted"] is True
    assert sorted(n["id"] for n in out["notes"]) == ["a", "b"]


def test_candidates_share_an_idea_from_a_far_subject(store, monkeypatch):
    from enqueue import config
    from enqueue.index.store import get_store
    from enqueue.providers.base import model_for

    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    index = get_store()
    index.ensure()
    idea = "Whoever moves first sets the terms the others must answer."
    lines = {
        "prince": ("A sixteenth-century manual on holding power in an Italian city.", idea),
        "war": ("A catalogue of military campaigns and how each was won.", idea),
        "twin": ("A sixteenth-century manual on holding power in an Italian city.", idea),
    }
    for aid, (subject, line) in lines.items():
        _note(aid)
        with db.transaction() as conn:
            for level, text in ((1, subject), (3, line)):
                conn.execute(
                    "INSERT INTO facets (id, artifact_id, level, statement, model_version,"
                    " trust) VALUES (?, ?, ?, ?, ?, 0.5)",
                    (f"{aid}-{level}", aid, level, text, model_for("ingest")),
                )
    index.upsert_facets()
    conn = db.get_conn()
    try:
        found = [c["id"] for c in shiny._candidates(conn, "prince")]
    finally:
        conn.close()
        get_store.cache_clear()

    assert "war" in found
    assert "twin" not in found  # the same subject is no surprise
