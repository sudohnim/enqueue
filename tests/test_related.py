"""Related artifacts: links between notes whose facets make the same point."""

from __future__ import annotations

import pytest

from enqueue import db
from enqueue.ingest import related
from enqueue.retrieve import candidates as cand

SHARED = "Structures last by yielding under stress rather than resisting it."


@pytest.fixture
def sqlite_store(store, monkeypatch):
    from enqueue import config
    from enqueue.index.store import get_store

    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    s = get_store()
    s.ensure()
    yield s
    get_store.cache_clear()


def _note(aid: str, statement: str, model: str | None = None, level: int = 1) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, status, created_at,"
            " updated_at) VALUES (?, 'note', ?, 'x', ?, 'ok', ?, ?)",
            (aid, f"Note {aid}", aid, db.now(), db.now()),
        )
        conn.execute(
            "INSERT INTO facets (id, artifact_id, level, statement, model_version, trust)"
            " VALUES (?, ?, ?, ?, ?, 0.5)",
            (f"f-{aid}", aid, level, statement, model or cand._get_model(False)),
        )


def _links(aid: str) -> list[str]:
    conn = db.get_conn()
    try:
        return [r["id"] for r in related.for_artifact(conn, aid)]
    finally:
        conn.close()


def test_links_are_found_and_stored_both_ways(sqlite_store):
    _note("a", SHARED)
    _note("b", SHARED)
    sqlite_store.upsert_facets()

    assert related.compute("a") >= 1
    assert "b" in _links("a")
    assert "a" in _links("b")  # the older note gains the link too
    assert "a" not in _links("a")


def test_stale_facets_never_link(sqlite_store):
    _note("a", SHARED)
    _note("old", SHARED, model="a-retired-model")
    sqlite_store.upsert_facets()

    related.compute("a")

    assert "old" not in _links("a")


def test_recompute_replaces_links(sqlite_store):
    _note("a", SHARED)
    _note("b", SHARED)
    sqlite_store.upsert_facets()
    related.compute("a")
    with db.transaction() as conn:
        conn.execute("DELETE FROM facets WHERE artifact_id = 'b'")
    sqlite_store.upsert_facets()

    related.compute("a")

    assert _links("a") == [] and _links("b") == []


def test_trashed_notes_are_hidden_and_purge_removes_both_directions(sqlite_store):
    from enqueue import trash

    _note("a", SHARED)
    _note("b", SHARED)
    sqlite_store.upsert_facets()
    related.compute("a")

    trash.delete("b")
    assert "b" not in _links("a")

    trash.purge("b")
    conn = db.get_conn()
    try:
        left = conn.execute(
            "SELECT COUNT(*) AS n FROM related WHERE artifact_id = 'b' OR related_id = 'b'"
        ).fetchone()["n"]
    finally:
        conn.close()
    assert left == 0


def test_artifact_detail_carries_related(sqlite_store):
    from fastapi.testclient import TestClient

    from enqueue.api.app import create_app

    _note("a", SHARED)
    _note("b", SHARED)
    sqlite_store.upsert_facets()
    related.compute("a")

    body = TestClient(create_app()).get("/artifacts/a").json()

    assert [r["id"] for r in body["related"]] == ["b"]
    assert set(body["related"][0]) == {"id", "title", "kind", "score", "via", "point"}


def _entity(aid: str, name: str, model: str | None = None) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO entities (id, artifact_id, entity, fact, model_version, trust)"
            " VALUES (?, ?, ?, 'a fact', ?, 0.5)",
            (f"e-{aid}-{name}", aid, name, model or cand._get_model(False)),
        )


def test_notes_that_name_the_same_thing_are_linked_with_the_name(sqlite_store):
    _note("a", "Kilns reward patience.")
    _note("b", "Markets punish haste.")
    _entity("a", "Nassim Taleb")
    _entity("b", "nassim taleb ")
    sqlite_store.upsert_facets()

    related.compute("a")

    conn = db.get_conn()
    try:
        links = related.for_artifact(conn, "b")
    finally:
        conn.close()
    assert [(r["id"], r["via"]) for r in links] == [("a", "Nassim Taleb")]


def test_common_names_and_stale_entities_link_nothing(sqlite_store):
    _note("a", "One.")
    _entity("a", "Google")
    _entity("a", "Old Name", model="a-retired-model")
    for i in range(related.MENTION_MAX_SHARED):
        _note(f"o{i}", f"Other {i}.")
        _entity(f"o{i}", "Google")
    _note("z", "Two.")
    _entity("z", "Old Name")
    sqlite_store.upsert_facets()

    related.compute("a")

    conn = db.get_conn()
    try:
        links = related.for_artifact(conn, "a")
    finally:
        conn.close()
    assert [r["via"] for r in links if r["via"]] == []


def _rows(aid: str) -> dict[str, dict]:
    conn = db.get_conn()
    try:
        return {r["id"]: r for r in related.for_artifact(conn, aid)}
    finally:
        conn.close()


def test_an_idea_link_keeps_the_line_that_matched(sqlite_store):
    """Each direction names the line of the note it points at: that is the reason shown."""
    theirs = "Structures endure by yielding under stress instead of resisting it."
    _note("a", SHARED)
    _note("b", theirs)
    sqlite_store.upsert_facets()

    related.compute("a")

    assert _rows("a")["b"]["point"] == theirs
    assert _rows("b")["a"]["point"] == SHARED
    assert _rows("a")["b"]["via"] is None


def test_only_subject_lines_link(sqlite_store):
    """A line above the subject level is written to leave the subject behind (and the
    bridge lines borrow another field's words on purpose), so it never makes a link."""
    _note("a", SHARED)
    _note("abstract", SHARED, level=3)
    sqlite_store.upsert_facets()

    related.compute("a")
    related.compute("abstract")

    assert _links("a") == []
    assert _links("abstract") == []


def test_links_from_an_older_rule_are_recomputed_once(sqlite_store):
    _note("a", SHARED)
    _note("b", SHARED)
    sqlite_store.upsert_facets()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO related (artifact_id, related_id, score, model_version, created_at)"
            " VALUES ('a', 'gone', 0.9, 'm', ?)",
            (db.now(),),
        )

    assert related.refresh_if_outdated() == 2
    assert _rows("a")["b"]["point"] == SHARED
    conn = db.get_conn()
    try:
        assert not conn.execute("SELECT 1 FROM related WHERE related_id = 'gone'").fetchone()
    finally:
        conn.close()
    assert related.refresh_if_outdated() == 0


def _mention(aid: str, name: str) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO entities (id, artifact_id, entity, fact, model_version, trust)"
            " VALUES (?, ?, ?, 'A fact.', ?, 0.5)",
            (f"e-{aid}-{name}", aid, name, cand._get_model(False)),
        )


def test_a_links_own_site_is_not_a_shared_mention(sqlite_store):
    """Two articles saved from the same site both "mention" it; that is not a link. A
    note that names the site is about it, so a name shared between notes still links."""
    subjects = {
        "post1": "How sourdough starters are fed and kept alive over months.",
        "post2": "The orbital mechanics of a satellite transfer between two planets.",
        "note1": "A ledger of household repairs and what each one cost.",
        "note2": "Rules for a card game played with two decks.",
    }
    for aid, subject in subjects.items():
        _note(aid, subject)
        _mention(aid, "Medium")
    # The site refused the preview, so only the address says where each came from.
    with db.transaction() as conn:
        conn.execute(
            "UPDATE artifacts SET source_url = 'https://medium.com/@someone/' || id"
            " WHERE id IN ('post1', 'post2')"
        )
    sqlite_store.upsert_facets()

    related.compute("post1")
    related.compute("note1")

    assert _links("post1") == []
    assert _links("note1") == ["note2"]


# ---- idea links: similarity proposes, the model judges -----------------------------

IDEA = "Reliability under pressure follows from incentives rather than from character."


class _Judge:
    """Stands in for the ingest model: answers every candidate the same way."""

    model = "judge"

    def __init__(self, same=True, why="Both say incentives predict behaviour.", error=None):
        self.same, self.why, self.error, self.calls = same, why, error, []

    def complete(self, system, user, response_model, **kwargs):
        self.calls.append(user)
        if self.error:
            raise self.error
        ids = [
            line.split(": ", 1)[1] for line in user.splitlines() if line.startswith("candidate id")
        ]
        return response_model(verdicts=[{"id": i, "same": self.same, "why": self.why} for i in ids])


@pytest.fixture
def idea_pair(sqlite_store, monkeypatch):
    """Two notes about different things whose idea lines (level 3) say the same."""
    _note("prince", "A sixteenth-century manual on holding power in an Italian city.")
    _note("war", "A catalogue of military campaigns and how each was won.")
    for aid in ("prince", "war"):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO facets (id, artifact_id, level, statement, model_version, trust)"
                " VALUES (?, ?, 3, ?, ?, 0.5)",
                (f"idea-{aid}", aid, IDEA, cand._get_model(False)),
            )
    sqlite_store.upsert_facets()
    model = cand._get_model(False)

    def use(judge):
        from enqueue.providers import base

        judge.model = model  # facets are current only for the model that wrote them
        monkeypatch.setattr(base, "get_provider", lambda *a, **k: judge)
        return judge

    return use


def test_an_unjudged_pair_is_not_a_link(idea_pair):
    judge = idea_pair(_Judge())

    related.compute("prince")

    assert _links("prince") == []
    assert related.is_pending("prince")
    assert judge.calls == []


def test_the_judges_yes_links_both_ways_with_its_sentence(idea_pair):
    judge = idea_pair(_Judge())

    related.compute("prince", judge=True)

    assert _rows("prince")["war"]["point"] == "Both say incentives predict behaviour."
    assert _rows("war")["prince"]["point"] == "Both say incentives predict behaviour."
    assert not related.is_pending("prince")
    related.compute("war", judge=True)  # the pair is cached: the other side asks nothing
    assert len(judge.calls) == 1
    assert "prince" in _links("war")


def test_the_judges_no_is_remembered_and_links_nothing(idea_pair):
    judge = idea_pair(_Judge(same=False, why=""))

    related.compute("prince", judge=True)
    related.compute("prince", judge=True)

    assert _links("prince") == []
    assert not related.is_pending("prince")
    assert len(judge.calls) == 1


def test_a_rate_limited_judge_owes_the_artifact_and_invents_nothing(idea_pair):
    from enqueue.providers.pause import ModelPaused

    idea_pair(_Judge(error=ModelPaused("paused")))

    with pytest.raises(related.JudgeOwed):
        related.compute("prince", judge=True)

    assert _links("prince") == []
    assert related.is_pending("prince")
    assert related.pending_ids() == ["prince"]


def test_a_changed_subject_asks_again(idea_pair):
    judge = idea_pair(_Judge(same=False, why=""))
    related.compute("prince", judge=True)
    with db.transaction() as conn:
        conn.execute("UPDATE facets SET statement = 'A manual on ruling.' WHERE id = 'f-prince'")

    related.compute("prince", judge=True)

    assert len(judge.calls) == 2


def test_a_private_pair_only_goes_to_the_local_model(idea_pair, monkeypatch):
    from enqueue.providers import base

    asked = []

    judge = idea_pair(_Judge())

    def provider(local_only=False, **kwargs):
        if kwargs.get("role") == "ingest":
            asked.append(local_only)
        return judge

    monkeypatch.setattr(base, "get_provider", provider)
    with db.transaction() as conn:
        conn.execute("UPDATE artifacts SET local_only = 1 WHERE id = 'war'")

    related.compute("prince", judge=True)

    assert asked == [True]


# ---- the judge worker: one artifact at a time, inside a daily budget -----------------


def test_the_worker_judges_what_is_pending_and_then_idles(idea_pair):
    judge = idea_pair(_Judge())
    related.compute("prince")  # marks it pending; no model call

    assert related.judge_next() == "judged"

    assert "war" in _links("prince")
    assert len(judge.calls) == 1
    assert related.judged_today() == 1
    assert related.judge_next() == "idle"


def test_the_worker_stops_at_the_days_budget(idea_pair, monkeypatch):
    judge = idea_pair(_Judge())
    related.compute("prince")
    monkeypatch.setattr(related, "JUDGE_DAILY", 0)

    assert related.judge_next() == "budget"

    assert judge.calls == []
    assert related.is_pending("prince")


def test_the_worker_waits_out_a_usage_limit_without_spending_a_call(idea_pair, monkeypatch):
    from enqueue.providers import pause

    judge = idea_pair(_Judge())
    related.compute("prince")
    monkeypatch.setattr(pause, "active", lambda: True)

    assert related.judge_next() == "paused"

    assert judge.calls == []
    assert related.judged_today() == 0


def test_an_unreachable_model_leaves_the_artifact_pending(idea_pair):
    from enqueue.providers.pause import ModelPaused

    idea_pair(_Judge(error=ModelPaused("limit")))
    related.compute("prince")

    assert related.judge_next() == "owed"

    assert _links("prince") == []
    assert related.is_pending("prince")


def test_ingest_never_calls_the_judge(idea_pair):
    """Ingest recomputes links from what is cached; the model is the worker's alone."""
    from enqueue.ingest import facets

    judge = idea_pair(_Judge())

    facets._reindex("prince")

    assert judge.calls == []
    assert related.is_pending("prince")
