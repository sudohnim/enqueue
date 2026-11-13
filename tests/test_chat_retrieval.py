"""What an answer is given to read, and how many model calls it takes to get there.

- a long artifact asked about on its own is searched inside, not cut to its opening;
- a follow-up is searched as the question it stands for, not as its words;
- a plain question is answered without asking the model which skill it is.
"""

from __future__ import annotations

import pytest
from enqueue.index.store import get_store
from enqueue.schemas import Standalone

from enqueue import assistant, chats, config, db


@pytest.fixture
def sqlite_store(store, monkeypatch):
    monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
    get_store.cache_clear()
    s = get_store()
    s.ensure()
    yield s
    get_store.cache_clear()


class _Local:
    """A model on this machine: the small passage budget."""

    model = "local-model"
    base_url = "http://127.0.0.1:11434/v1"


class _Remote:
    model = "remote-model"
    base_url = "https://models.example/v1"


def _long_note(aid: str, parts: list[str]) -> None:
    conn = db.get_conn()
    try:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, status,"
            " created_at, updated_at) VALUES (?, 'note', 'Field manual', ?, ?, 'ok',"
            " datetime('now'), datetime('now'))",
            (aid, "\n\n".join(parts), aid + "_hash"),
        )
        for n, text in enumerate(parts):
            conn.execute(
                "INSERT INTO chunks (id, artifact_id, ordinal, text, chunker)"
                " VALUES (?, ?, ?, ?, 'test')",
                (f"{aid}_c{n:02d}", aid, n, text),
            )
        conn.commit()
    finally:
        conn.close()


_FILLER_PARTS = [
    "Pitch the tent on high ground, away from the river.",
    "Boil water for ten minutes before drinking it.",
    "A sharp axe is safer than a dull one.",
    "Store food in a tree, out of reach of bears.",
    "Mark the trail with stones at every fork.",
    "Dry your socks by the fire each night.",
    "Carry a whistle and three ways to make fire.",
    "Read the clouds in the west before breaking camp.",
    "Wax the canvas before the autumn rains.",
    "Keep the map in a waterproof sleeve.",
    "Rest every hour on a long climb.",
]
_NEEDLE = "Ziggurats were stepped temples built of mud brick in ancient Mesopotamia."


class TestBudget:
    def test_a_hosted_model_reads_more_and_reads_each_passage_whole(self):
        assert chats._budget(_Local()) == (chats.PASSAGES, chats.PASSAGE_WORDS)
        assert chats._budget(_Remote()) == (chats.REMOTE_PASSAGES, chats.REMOTE_PASSAGE_WORDS)

    def test_the_prompt_clips_to_the_models_budget(self):
        seen = {}

        class _Asked(_Remote):
            def complete(self, system, user, response_model, context=None, max_retries=None):
                seen["user"] = user
                return response_model(answer="ok", grounded=True, cited=["a1"])

        long_text = " ".join(f"w{i}" for i in range(300))
        found = [{"artifact_id": "a1", "title": "T", "kind": "note", "text": long_text}]

        chats._ask_model("q", "", found, provider=_Asked())

        assert "w299" in seen["user"]  # 300 words fit a hosted model's 400


class TestScopedChat:
    def test_an_artifact_that_fits_is_read_whole(self, sqlite_store, monkeypatch):
        _long_note("a1", _FILLER_PARTS[:3])
        monkeypatch.setattr(chats, "get_provider", lambda **kw: _Local())

        found = chats.passages("anything", "artifact", "a1")

        assert [p["id"] for p in found] == ["a1_c00", "a1_c01", "a1_c02"]

    def test_a_long_artifact_is_searched_inside(self, sqlite_store, monkeypatch):
        """The matching passage sits past the old cut-off (the first 8 chunks)."""
        _long_note("a1", _FILLER_PARTS + [_NEEDLE])
        sqlite_store.upsert_chunks()
        monkeypatch.setattr(chats, "get_provider", lambda **kw: _Local())

        found = chats.passages("what were ziggurats built of", "artifact", "a1")

        ids = [p["id"] for p in found]
        assert len(found) == chats.PASSAGES
        assert "a1_c11" in ids, "the passage that answers must be read"
        assert ids[0] == "a1_c00", "the opening is always read"
        assert ids == sorted(ids), "passages come in document order"

    def test_a_long_artifact_opens_with_its_summary(self, sqlite_store, monkeypatch):
        _long_note("a1", _FILLER_PARTS + [_NEEDLE])
        sqlite_store.upsert_chunks()
        conn = db.get_conn()
        try:
            conn.execute(
                "INSERT INTO facets (id, artifact_id, level, statement, model_version, trust,"
                " edited) VALUES ('f1', 'a1', 0, 'A manual for living outdoors.', 'x', 1.0, 1)"
            )
            conn.commit()
        finally:
            conn.close()
        monkeypatch.setattr(chats, "get_provider", lambda **kw: _Local())

        found = chats.passages("what is this about", "artifact", "a1")

        assert found[0]["id"] == "overview:a1"
        assert "A manual for living outdoors." in found[0]["text"]
        assert found[0]["artifact_id"] == "a1"
        assert len(found) == chats.PASSAGES

    def test_an_unindexed_long_artifact_falls_back_to_its_opening(self, sqlite_store, monkeypatch):
        _long_note("a1", _FILLER_PARTS + [_NEEDLE])
        monkeypatch.setattr(chats, "get_provider", lambda **kw: _Local())

        found = chats.passages("ziggurats", "artifact", "a1")

        assert [p["id"] for p in found] == [f"a1_c{n:02d}" for n in range(chats.PASSAGES)]


class TestSearchWithin:
    def test_it_only_returns_the_artifacts_own_chunks(self, sqlite_store):
        _long_note("a1", _FILLER_PARTS[:2])
        _long_note("a2", [_NEEDLE, "Another passage about temples."])
        sqlite_store.upsert_chunks()

        best = sqlite_store.search_within("a1", "ziggurat temples", 5)

        assert best and all(cid.startswith("a1_") for cid in best)


class _Rewriter(_Remote):
    def __init__(self, reply):
        self.reply = reply
        self.users: list[str] = []

    def complete(self, system, user, response_model, context=None, max_retries=None):
        self.users.append(user)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class TestFollowUp:
    def _chat(self, turns: list[tuple[str, str]]) -> dict:
        chat = chats.create()["chat"]
        with db.transaction() as conn:
            for role, text in turns:
                chats._append(conn, chat["id"], role, text)
        return chat

    def test_a_first_question_is_searched_as_typed(self, store, monkeypatch):
        chat = self._chat([("user", "what did I save about kilns")])
        monkeypatch.setattr(chats, "get_provider", lambda **kw: pytest.fail("no model call"))

        assert chats._standalone(chat, "what did I save about kilns") == (
            "what did I save about kilns"
        )

    def test_a_follow_up_is_restated_from_the_conversation(self, store, monkeypatch):
        chat = self._chat(
            [
                ("user", "what did I save about kilns"),
                ("assistant", "Two notes: cone six firing and raku."),
                ("user", "tell me more about the second one"),
            ]
        )
        model = _Rewriter(Standalone(question="What did I save about raku firing?", claims=[]))
        monkeypatch.setattr(chats, "get_provider", lambda **kw: model)

        asked = chats._standalone(chat, "tell me more about the second one")

        assert asked == "What did I save about raku firing?"
        assert "cone six firing and raku" in model.users[0]
        assert model.users[0].endswith("Latest message: tell me more about the second one")

    def test_the_claims_it_returns_are_kept_for_lifting(self, store, monkeypatch):
        from enqueue.retrieve import lift

        chat = self._chat([("user", "kilns"), ("assistant", "Raku."), ("user", "and why")])
        claim = "Rapid cooling fixes a surface before it can settle into uniformity."
        model = _Rewriter(Standalone(question="Why is raku fired fast?", claims=[claim]))
        monkeypatch.setattr(chats, "get_provider", lambda **kw: model)

        chats._standalone(chat, "and why")

        assert lift._read("Why is raku fired fast?", "remote-model") == [claim]

    def test_without_the_model_a_short_follow_up_carries_the_question_before(
        self, store, monkeypatch
    ):
        chat = self._chat(
            [("user", "what did I save about kilns"), ("assistant", "Two."), ("user", "and raku?")]
        )
        monkeypatch.setattr(chats, "get_provider", lambda **kw: _Rewriter(RuntimeError("down")))

        assert chats._standalone(chat, "and raku?") == "what did I save about kilns and raku?"

    def test_without_the_model_a_long_follow_up_stands_as_typed(self, store, monkeypatch):
        text = "now show me everything I have written about sourdough starters instead"
        chat = self._chat([("user", "kilns"), ("assistant", "Two."), ("user", text)])
        monkeypatch.setattr(chats, "get_provider", lambda **kw: _Rewriter(RuntimeError("down")))

        assert chats._standalone(chat, text) == text

    def test_a_slow_model_does_not_hold_the_answer(self, store, monkeypatch):
        import threading

        release = threading.Event()

        class _Slow(_Remote):
            def complete(self, *a, **k):
                release.wait(5)
                raise RuntimeError("too late")

        chat = self._chat([("user", "kilns"), ("assistant", "Two."), ("user", "and raku?")])
        monkeypatch.setattr(chats, "get_provider", lambda **kw: _Slow())
        monkeypatch.setattr(config, "CHAT_PREP_WAIT_S", 0.05)

        try:
            assert chats._standalone(chat, "and raku?") == "kilns and raku?"
        finally:
            release.set()


class TestRouterGate:
    def test_a_question_is_answered_without_asking_the_model(self, monkeypatch):
        monkeypatch.setattr(assistant, "get_provider", lambda **kw: pytest.fail("no model call"))

        assert assistant.route("what did I save about kubernetes?") == "answer"
        assert assistant.route("summarize my notes on stoicism") == "answer"

    @pytest.mark.parametrize(
        "request_text",
        [
            "organize my saved things by kind",
            "group my book notes by the author's region",
            "Sort these by year",
            "categorise my links by topic",
        ],
    )
    def test_a_request_to_rearrange_still_asks(self, monkeypatch, request_text):
        class _Router:
            def complete(self, system, user, response_model, context=None, max_retries=None):
                return response_model(skill="organize")

        monkeypatch.setattr(assistant, "get_provider", lambda **kw: _Router())

        assert assistant.route(request_text) == "organize"


class TestEditedSummaryLines:
    def test_a_hand_written_line_is_never_stale(self, store):
        from enqueue.retrieve.candidates import hit_is_stale

        conn = db.get_conn()
        try:
            conn.execute(
                "INSERT INTO artifacts (id, kind, title, body, content_hash, status,"
                " created_at, updated_at) VALUES ('a1', 'note', 'T', 'b', 'h', 'ok',"
                " datetime('now'), datetime('now'))"
            )
            conn.commit()
            hit = {"artifact_id": "a1", "model_version": "edited", "body_version": "old"}
            assert hit_is_stale(conn, dict(hit), {}) is True
            assert hit_is_stale(conn, hit | {"edited": True}, {}) is False
        finally:
            conn.close()


def _named_note(aid: str, title: str, text: str, entities: tuple[str, ...] = ()) -> None:
    conn = db.get_conn()
    try:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, status,"
            " created_at, updated_at) VALUES (?, 'note', ?, ?, ?, 'ok',"
            " datetime('now'), datetime('now'))",
            (aid, title, text, aid + "_hash"),
        )
        conn.execute(
            "INSERT INTO chunks (id, artifact_id, ordinal, text, chunker)"
            " VALUES (?, ?, 0, ?, 'test')",
            (aid + "_c0", aid, text),
        )
        for n, name in enumerate(entities):
            conn.execute(
                "INSERT INTO entities (id, artifact_id, entity, fact, model_version)"
                " VALUES (?, ?, ?, '', 'test-model')",
                (f"{aid}_e{n}", aid, name),
            )
        conn.commit()
    finally:
        conn.close()


class TestNamedInTheQuestion:
    """A question that listed five names was answered "nothing mentions Thrawn" while
    a note called Thrawn was in the library: one embedding blurred the names, and the
    keyword search needed every word in one passage."""

    QUESTION = "do i have notes on a council of taleb, thrawn, sun tzu and marcus aurelius"

    def test_a_note_whose_title_the_question_names_is_read(self, sqlite_store):
        _named_note("t1", "Thrawn", "Art reveals a culture's military doctrine.")
        for n, text in enumerate(_FILLER_PARTS[:6]):
            _named_note(f"f{n}", f"Camp tip {n}", text)
        sqlite_store.upsert_chunks()

        found = chats._library_passages(self.QUESTION, 4)

        assert found[0]["artifact_id"] == "t1"
        assert found[0]["why"] == "named"

    def test_a_note_naming_someone_the_question_names_is_read(self, sqlite_store):
        _named_note("o1", "The Odyssey", "Opportunities multiply as they are seized.", ("Sun Tzu",))
        sqlite_store.upsert_chunks()

        found = chats._library_passages(self.QUESTION, 4)

        assert "o1" in {p["artifact_id"] for p in found}

    def test_a_short_word_or_a_common_name_points_at_nothing(self, store):
        from enqueue.retrieve.names import named

        _named_note("w1", "Art", "Brush strokes.")
        for n in range(9):
            _named_note(f"g{n}", f"Page {n}", "Text.", ("Google",))

        assert named("is there art in my google docs", 4) == []

    def test_a_trashed_note_is_not_named(self, store):
        from enqueue.retrieve.names import named

        _named_note("t1", "Thrawn", "Doctrine.")
        conn = db.get_conn()
        try:
            conn.execute("UPDATE artifacts SET deleted_at = datetime('now') WHERE id = 't1'")
            conn.commit()
        finally:
            conn.close()

        assert named(self.QUESTION, 4) == []
