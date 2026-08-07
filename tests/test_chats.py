"""Chats: what is written, when, and what an answer is allowed to claim.

No model runs here. The provider is replaced with one that returns exactly what a
test wants, which is the only way to assert on the failure cases that matter, since
those are precisely the ones a real model produces at random.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from enqueue import api, assistant, chats, db, notes
from enqueue.schemas import Answer, AssistantRoute, ChatTitle, ChatTopics


class FakeProvider:
    """Answers each response_model from a script. Raises when the script says to."""

    router: FakeProvider | None = None

    def __init__(self, **byname):
        self.byname = byname
        self.calls = []

    def complete(self, system, user, response_model, context=None, max_retries=3):
        self.calls.append(response_model.__name__)
        reply = self.byname.get(response_model.__name__)
        if isinstance(reply, Exception):
            raise reply
        if reply is None:
            raise AssertionError(f"no scripted reply for {response_model.__name__}")
        return reply


@pytest.fixture
def answered(monkeypatch):
    """Callable test double: scripts the provider and the passages queue.

    Also scripts the router: since the worker dispatches through the skill registry,
    resolving a recorded job starts with one routing call, and it must pick `answer`
    for these tests (the model is never consulted; Rule 1's floor is stubbed too).
    The request path itself makes zero model calls (Phase H) - these stubs only
    come alive when a test resolves the recorded job through the worker.
    """

    class Answered:
        passages: list = []

        def __call__(self, **byname):
            provider = FakeProvider(**byname)
            monkeypatch.setattr(chats, "get_provider", lambda *a, **k: provider)
            monkeypatch.setattr(chats, "passages", lambda *a, **k: self.passages)
            router = FakeProvider(AssistantRoute=AssistantRoute(skill="answer"))
            monkeypatch.setattr(assistant, "get_provider", lambda *a, **k: router)
            # The router is attached so a test can assert the request path made no
            # routing call either (Phase H: routing moved to the worker).
            provider.router = router
            return provider

    return Answered()


class TestAnswerContract:
    """The validators that stop an answer from lying about where it came from."""

    def test_cannot_cite_what_it_was_not_shown(self):
        with pytest.raises(ValidationError, match="not provided"):
            Answer.model_validate(
                {"answer": "Yes.", "grounded": True, "cited": ["ghost"]},
                context={"offered_artifact_ids": ["real"]},
            )

    def test_grounded_must_name_a_source(self):
        with pytest.raises(ValidationError, match="nothing is cited"):
            Answer.model_validate(
                {"answer": "Yes.", "grounded": True, "cited": []},
                context={"offered_artifact_ids": ["real"]},
            )

    def test_ungrounded_must_not_name_one(self):
        with pytest.raises(ValidationError, match="grounded is false"):
            Answer.model_validate(
                {"answer": "No.", "grounded": False, "cited": ["real"]},
                context={"offered_artifact_ids": ["real"]},
            )

    def test_an_honest_refusal_is_valid(self):
        assert not Answer.model_validate(
            {"answer": "You have not saved anything on this.", "grounded": False, "cited": []},
            context={"offered_artifact_ids": ["real"]},
        ).grounded


class TestNaming:
    def test_a_title_names_the_subject_not_the_exchange(self):
        with pytest.raises(ValidationError, match="names the exchange"):
            ChatTitle(title="Chat about stoic philosophy")

    def test_a_title_is_not_a_sentence(self):
        with pytest.raises(ValidationError, match="drop the final punctuation"):
            ChatTitle(title="What survives stress?")

    def test_topics_must_stand_alone(self):
        with pytest.raises(ValidationError, match="refers to the conversation"):
            ChatTopics(topics=["what this text argues", "resilience"])

    def test_topics_are_noun_phrases(self):
        with pytest.raises(ValidationError, match="is a sentence"):
            ChatTopics(topics=["resilience", "things break under load."])

    def test_a_usable_set_passes(self):
        assert len(ChatTopics(topics=["antifragility", "tolerance in joints"]).topics) == 2

    def test_run_together_identifiers_are_rejected(self):
        """Seen in the wild: 'NotesNotFetched', 'MuseumCollection'. They pass the word
        count because they contain no spaces, and they cannot be used as a lens."""
        with pytest.raises(ValidationError, match="runs words together"):
            ChatTopics(topics=["NotesNotFetched", "resilience"])

    def test_slugs_are_rejected(self):
        with pytest.raises(ValidationError, match="punctuated like a slug"):
            ChatTopics(topics=["stress_resilience", "tolerance"])


class TestTopicsAreNotDerivedFromNothing:
    def test_a_conversation_that_found_nothing_gets_no_topics(
        self, store, quiet_queue, answered, async_turns
    ):
        """A chat where every answer was a refusal has no concept in it to extract,
        and the model invents one rather than returning none."""
        chat = chats.create()
        answered.passages = []
        provider = answered(
            Answer=Answer(
                answer="Nothing you have saved speaks to that.", grounded=False, cited=[]
            ),
            ChatTitle=ChatTitle(title="Nothing on ceramics"),
            ChatTopics=ChatTopics(topics=["ceramics", "brittleness"]),
        )

        chats.send(chat["chat"]["id"], "what about ceramics?")
        async_turns.resolve()
        result = chats.get(chat["chat"]["id"])
        assert result["topics"] == []
        # Not merely discarded: the call is never made, so a refusal costs nothing.
        assert "ChatTopics" not in provider.calls

    def test_a_grounded_conversation_still_gets_them(
        self, store, quiet_queue, answered, async_turns
    ):
        note = notes.create(body="# Joints\n\nA joint that moves outlasts one that does not.")
        chat = chats.create()
        answered.passages = [
            {"artifact_id": note["artifact"]["id"], "title": "Joints", "text": "x", "kind": "note"}
        ]
        answered(
            Answer=Answer(
                answer="Movement outlasts rigidity.", grounded=True, cited=[note["artifact"]["id"]]
            ),
            ChatTitle=ChatTitle(title="Movement over rigidity"),
            ChatTopics=ChatTopics(topics=["tolerance", "failure under load"]),
        )

        chats.send(chat["chat"]["id"], "what outlasts what?")
        async_turns.resolve()
        result = chats.get(chat["chat"]["id"])
        assert {t["topic"] for t in result["topics"]} == {"tolerance", "failure under load"}


class TestPinning:
    def test_pinned_conversations_sort_first(self, store, quiet_queue):
        old = chats.create()
        new = chats.create()
        chats.pin(old["chat"]["id"])

        order = [c["id"] for c in chats.listing()["items"]]
        assert order[0] == old["chat"]["id"]
        assert new["chat"]["id"] in order

        chats.pin(old["chat"]["id"], False)
        assert chats.listing()["items"][0]["id"] == new["chat"]["id"]

    def test_pinning_an_unknown_chat_is_a_key_error(self, store):
        with pytest.raises(KeyError):
            chats.pin("nope")


class TestTurns:
    def test_a_question_and_its_answer_are_written_together(
        self, store, quiet_queue, answered, async_turns
    ):
        note = notes.create(body="# Joints\n\nA joint that moves outlasts one that does not.")
        chat = chats.create()
        answered.passages = [
            {
                "artifact_id": note["artifact"]["id"],
                "title": "Joints",
                "text": "A joint that moves outlasts one that does not.",
                "kind": "note",
            }
        ]
        answered(
            Answer=Answer(
                answer="Movement outlasts rigidity.",
                grounded=True,
                cited=[note["artifact"]["id"]],
            ),
            ChatTitle=ChatTitle(title="Movement over rigidity"),
            ChatTopics=ChatTopics(topics=["tolerance", "failure under load"]),
        )

        pending = chats.send(chat["chat"]["id"], "what outlasts what?")
        # Submit returns with a visible pending turn; the worker fills it in.
        assert pending["messages"][-1]["status"] == "pending"
        async_turns.resolve()

        result = chats.get(chat["chat"]["id"])
        assert [m["role"] for m in result["messages"]] == ["user", "assistant"]
        assert result["messages"][-1]["status"] == "done"
        assert result["messages"][-1]["cited"][0]["title"] == "Joints"
        assert result["chat"]["title"] == "Movement over rigidity"
        assert {t["topic"] for t in result["topics"]} == {"tolerance", "failure under load"}

    def test_a_failed_answer_resolves_to_a_failed_turn(
        self, store, quiet_queue, answered, async_turns
    ):
        """The old bug: the question was written first, the model failed, and asking
        again appended a second copy of the same question. Phase H keeps both rows at
        submit time, so a failure resolves the pending turn rather than leaving the
        question dangling."""
        chat = chats.create()
        answered.passages = [{"artifact_id": "a", "title": "T", "text": "body", "kind": "note"}]
        answered(Answer=RuntimeError("the model fell over"))

        result = chats.send(chat["chat"]["id"], "what outlasts what?")
        assert [m["role"] for m in result["messages"]] == ["user", "assistant"]

        async_turns.resolve()
        after = chats.get(chat["chat"]["id"])
        assert [m["role"] for m in after["messages"]] == ["user", "assistant"]
        assert after["messages"][-1]["status"] == "failed"

    def test_a_citation_the_model_invented_is_dropped(
        self, store, quiet_queue, answered, async_turns
    ):
        note = notes.create(body="# Joints\n\nA joint that moves outlasts one that does not.")
        chat = chats.create()
        answered.passages = [
            {"artifact_id": note["artifact"]["id"], "title": "Joints", "text": "x", "kind": "note"}
        ]
        answered(
            Answer=Answer.model_construct(
                answer="Movement outlasts rigidity.",
                grounded=True,
                cited=[note["artifact"]["id"], "never-offered"],
            ),
            ChatTitle=ChatTitle(title="Movement over rigidity"),
            ChatTopics=ChatTopics(topics=["tolerance", "failure under load"]),
        )

        chats.send(chat["chat"]["id"], "what outlasts what?")
        async_turns.resolve()
        result = chats.get(chat["chat"]["id"])
        assert [c["artifact_id"] for c in result["messages"][-1]["cited"]] == [
            note["artifact"]["id"]
        ]

    def test_naming_failure_does_not_lose_the_answer(
        self, store, quiet_queue, answered, async_turns
    ):
        """Title and topics are conveniences. Losing them must not lose the exchange."""
        chat = chats.create()
        answered.passages = [{"artifact_id": "a", "title": "T", "text": "body", "kind": "note"}]
        answered(
            Answer=Answer(answer="Nothing here bears on it.", grounded=False, cited=[]),
            ChatTitle=RuntimeError("no"),
            ChatTopics=RuntimeError("no"),
        )

        chats.send(chat["chat"]["id"], "what about ceramics?")
        async_turns.resolve()
        result = chats.get(chat["chat"]["id"])
        assert result["messages"][-1]["text"] == "Nothing here bears on it."
        assert result["chat"]["title"] == "what about ceramics?"
        assert result["topics"] == []


class TestScope:
    def test_a_scoped_chat_needs_something_to_be_scoped_to(self, store):
        with pytest.raises(ValueError, match="needs something"):
            chats.create(scope_kind="artifact")

    def test_an_artifact_chat_reads_that_artifact_and_does_not_search(
        self, store, quiet_queue, monkeypatch
    ):
        note = notes.create(body="# Joints\n\nA joint that moves outlasts one that does not.")
        from enqueue.ingest import chunk as chunk_mod

        with db.transaction() as conn:
            chunk_mod.chunk_artifact(conn, note["artifact"]["id"])

        def explode(*a, **k):
            raise AssertionError("a scoped chat must not reach the vector index")

        class _NoIndex:
            CHUNKS = "chunks"
            FACETS = "facets"

            def search(self, *a, **k):
                explode()

        monkeypatch.setattr("enqueue.index.store.get_store", lambda: _NoIndex())

        found = chats.passages("anything", "artifact", note["artifact"]["id"])
        assert found and all(p["artifact_id"] == note["artifact"]["id"] for p in found)


class TestSubmittingReturnsImmediately:
    """A conversation exists once a question is submitted, not once it is answered.

    The request path writes the exchange and returns; the worker resolves the
    pending turn later. A failed answer is a `failed` turn inside the chat - the
    question stays, the chat stays, and nothing is lost.
    """

    def test_a_failed_first_question_resolves_inside_the_chat(
        self, store, quiet_queue, answered, async_turns
    ):
        answered.passages = [{"artifact_id": "a", "title": "T", "text": "body", "kind": "note"}]
        answered(Answer=RuntimeError("the model timed out"))

        made = chats.ask("what outlasts what?")
        assert made["messages"][-1]["status"] == "pending"

        async_turns.resolve()
        after = chats.get(made["chat"]["id"])
        assert after["messages"][-1]["status"] == "failed"
        assert after["messages"][-1]["text"] == "That answer could not be completed."
        # The conversation was not deleted: a failed answer is a failed turn.
        assert [c["id"] for c in chats.listing()["items"]] == [made["chat"]["id"]]

    def test_the_api_submits_a_pending_turn_and_the_worker_resolves_it(
        self, store, quiet_queue, answered, async_turns
    ):
        answered.passages = [{"artifact_id": "a", "title": "T", "text": "body", "kind": "note"}]
        answered(Answer=RuntimeError("the model timed out"))

        client = TestClient(api.app)
        resp = client.post("/chats", json={"text": "what outlasts what?"})

        assert resp.status_code == 201
        made = resp.json()
        assert made["messages"][-1]["status"] == "pending"

        async_turns.resolve()
        reloaded = client.get("/chats/" + made["chat"]["id"]).json()
        assert reloaded["messages"][-1]["status"] == "failed"
        assert [c["id"] for c in client.get("/chats").json()["items"]] == [made["chat"]["id"]]

    def test_a_successful_first_question_creates_exactly_one_conversation(
        self, store, quiet_queue, answered, async_turns
    ):
        answered.passages = []
        answered(
            Answer=Answer(
                answer="Nothing you have saved speaks to that yet.", grounded=False, cited=[]
            ),
            ChatTitle=ChatTitle(title="Movement over rigidity"),
            ChatTopics=ChatTopics(topics=["tolerance", "failure under load"]),
        )

        made = chats.ask("what outlasts what?")
        chat_id = made["chat"]["id"]
        async_turns.resolve()
        made = chats.get(chat_id)

        assert [m["role"] for m in made["messages"]] == ["user", "assistant"]
        assert [c["id"] for c in chats.listing()["items"]] == [chat_id]

    def test_a_successful_first_question_via_the_api(
        self, store, quiet_queue, answered, async_turns
    ):
        note = notes.create(body="# Joints\n\nA joint that moves outlasts one that does not.")
        answered.passages = [
            {
                "artifact_id": note["artifact"]["id"],
                "title": "Joints",
                "text": "A joint that moves outlasts one that does not.",
                "kind": "note",
            }
        ]
        answered(
            Answer=Answer(
                answer="Movement outlasts rigidity.",
                grounded=True,
                cited=[note["artifact"]["id"]],
            ),
            ChatTitle=ChatTitle(title="Movement over rigidity"),
            ChatTopics=ChatTopics(topics=["tolerance", "failure under load"]),
        )

        client = TestClient(api.app)
        resp = client.post("/chats", json={"text": "what outlasts what?"})

        assert resp.status_code == 201
        made = resp.json()
        assert [m["role"] for m in made["messages"]] == ["user", "assistant"]
        assert made["messages"][-1]["status"] == "pending"

        async_turns.resolve()
        reloaded = client.get("/chats/" + made["chat"]["id"]).json()
        assert reloaded["messages"][-1]["status"] == "done"
        assert reloaded["messages"][-1]["cited"][0]["title"] == "Joints"
        assert [c["id"] for c in client.get("/chats").json()["items"]] == [reloaded["chat"]["id"]]

        # Every turn carries its kind, payload, and status.
        for m in reloaded["messages"]:
            assert m["kind"] == "answer"
            assert m["payload"] is None
            assert m["status"] == "done"

    def test_a_failed_second_turn_leaves_the_conversation_untouched(
        self, store, quiet_queue, answered, async_turns
    ):
        answered.passages = []
        answered(
            Answer=Answer(
                answer="Nothing you have saved speaks to that yet.", grounded=False, cited=[]
            ),
            ChatTitle=ChatTitle(title="Movement over rigidity"),
            ChatTopics=ChatTopics(topics=["tolerance", "failure under load"]),
        )
        chat_id = chats.ask("what outlasts what?")["chat"]["id"]
        async_turns.resolve()

        answered.passages = [{"artifact_id": "a", "title": "T", "text": "body", "kind": "note"}]
        answered(Answer=RuntimeError("the model timed out"))
        chats.send(chat_id, "and what else?")
        async_turns.resolve()

        after = chats.get(chat_id)
        assert [m["role"] for m in after["messages"]] == ["user", "assistant", "user", "assistant"]
        assert after["messages"][-1]["status"] == "failed"
        assert [c["id"] for c in chats.listing()["items"]] == [chat_id]

    def test_an_empty_question_is_rejected_before_any_write(self, store, quiet_queue, answered):
        with pytest.raises(ValueError, match="say something"):
            chats.ask("   ")
        assert chats.listing()["items"] == []

    def test_a_bad_scope_is_rejected_before_any_write(self, store, quiet_queue, answered):
        with pytest.raises(ValueError, match="unknown scope"):
            chats.ask("what outlasts what?", scope_kind="everything else")
        assert chats.listing()["items"] == []


class TestRequestPathCallsNoModel:
    """Phase H: submitting never touches the model. The worker owns routing,
    answering, naming, and retopic - the request path only writes the skeleton."""

    def test_send_returns_a_pending_turn_without_calling_the_model(
        self, store, quiet_queue, answered, async_turns
    ):
        chat = chats.create()
        answered.passages = []
        provider = answered(
            Answer=Answer(answer="Nothing here.", grounded=False, cited=[]),
            ChatTitle=ChatTitle(title="Nothing saved"),
            ChatTopics=ChatTopics(topics=["ceramics", "brittleness"]),
        )

        result = chats.send(chat["chat"]["id"], "what outlasts what?")

        assert result["messages"][-1]["status"] == "pending"
        assert result["messages"][-1]["text"] == ""
        # No router, no answer provider: zero model calls on the request path.
        assert provider.calls == []
        assert provider.router.calls == []

        async_turns.resolve()
        done = chats.get(chat["chat"]["id"])
        assert done["messages"][-1]["status"] == "done"

    def test_ask_opens_a_chat_with_a_pending_first_turn(
        self, store, quiet_queue, answered, async_turns
    ):
        answered.passages = []
        provider = answered(
            Answer=Answer(answer="Nothing here.", grounded=False, cited=[]),
            ChatTitle=ChatTitle(title="Nothing saved"),
            ChatTopics=ChatTopics(topics=["ceramics", "brittleness"]),
        )

        made = chats.ask("what outlasts what?")

        assert [m["role"] for m in made["messages"]] == ["user", "assistant"]
        assert made["messages"][-1]["status"] == "pending"
        assert provider.calls == []
        assert provider.router.calls == []

        async_turns.resolve()
        done = chats.get(made["chat"]["id"])
        assert done["messages"][-1]["status"] == "done"


class TestDeletion:
    def test_deleting_a_chat_takes_its_messages_and_topics(
        self, store, quiet_queue, answered, async_turns
    ):
        chat = chats.create()
        answered.passages = []
        answered(
            Answer=Answer(answer="Nothing yet.", grounded=False, cited=[]),
            ChatTitle=ChatTitle(title="Nothing saved"),
            ChatTopics=ChatTopics(topics=["ceramics", "brittleness"]),
        )
        chat_id = chat["chat"]["id"]
        chats.send(chat_id, "what about ceramics?")
        async_turns.resolve()

        chats.delete(chat_id)
        with pytest.raises(KeyError):
            chats.get(chat_id)
        assert chats.listing()["items"] == []


class TestConversationsShareTheWall:
    """A conversation is the same kind of thing on the wall as a capture.

    It sorts into the same /artifacts listing by last touch, so a fresh capture is
    never behind a conversation nobody touched this week, and the saved shelf
    treats a kept conversation exactly like a kept artifact.
    """

    def _wall(self, **params):
        return TestClient(api.app).get("/artifacts", params=params).json()

    def _rewrite_updated(self, artifact: str | None, chat: str | None, iso: str) -> None:
        """Set updated_at by hand so ordering is deterministic, not clock-racy."""
        conn = db.get_conn()
        try:
            if artifact:
                conn.execute("UPDATE artifacts SET updated_at = ? WHERE id = ?", (iso, artifact))
            if chat:
                conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (iso, chat))
            conn.commit()
        finally:
            conn.close()

    def test_conversations_sort_by_last_touch_not_ahead_of_captures(self, store):
        old = notes.create(body="# Joints\n\nA joint that moves outlasts one that does not.")
        chat = chats.create()
        fresh = notes.create(body="# Rooftops\n\nA city can feed itself from its rooftops.")
        old_id = old["artifact"]["id"]
        chat_id = chat["chat"]["id"]
        fresh_id = fresh["artifact"]["id"]

        self._rewrite_updated(old_id, None, "2024-01-01T00:00:00+00:00")
        self._rewrite_updated(None, chat_id, "2024-06-01T00:00:00+00:00")
        self._rewrite_updated(fresh_id, None, "2024-07-01T00:00:00+00:00")

        wall = self._wall(order="touched", pinned=False)
        assert [i["id"] for i in wall["items"]] == [fresh_id, chat_id, old_id]

        chat_row = next(i for i in wall["items"] if i["kind"] == "chat")
        assert chat_row["id"] == chat_id
        assert chat_row["excerpt"] == "conversation"
        assert wall["total"] == 3

    def test_a_kept_conversation_moves_to_the_saved_shelf(self, store):
        note = notes.create(body="# Joints\n\nA joint that moves outlasts one that does not.")
        chat = chats.create()
        note_id = note["artifact"]["id"]
        chat_id = chat["chat"]["id"]
        self._rewrite_updated(note_id, None, "2024-01-01T00:00:00+00:00")
        self._rewrite_updated(None, chat_id, "2024-02-01T00:00:00+00:00")
        chats.pin(chat_id)

        wall = self._wall(order="touched", pinned=False)
        assert [i["id"] for i in wall["items"]] == [note_id]

        kept = self._wall(order="touched", pinned=True)
        assert [i["id"] for i in kept["items"]] == [chat_id]
        assert kept["items"][0]["pinned"] == 1
