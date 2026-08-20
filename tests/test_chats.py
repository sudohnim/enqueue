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


@pytest.fixture(autouse=True)
def _no_real_judge(monkeypatch):
    """No chat test may touch a real model. The Q.3b gray-zone judge (Q.3)
    fires the moment a question lands in the gray zone - here the
    "hyperdimensional cheese grater" test - so stub `get_provider` fail-open
    (keep everything), the gate's error budget, unless a test installs its
    own verdicts.
    """
    from enqueue.retrieve import candidates as cand

    class _KeepAllJudge:
        model = "test-judge"

        def complete(self, *args, **kwargs):
            return cand._GrayZoneResponse(verdicts=[])

    monkeypatch.setattr(cand, "get_provider", lambda *a, **k: _KeepAllJudge())


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

    def test_grounded_without_citations_backfills_what_was_fed(self):
        # FIX.1: a correct grounded answer that forgot to cite is not a failed
        # turn; the passages actually fed to it stand in for the citations.
        answer = Answer.model_validate(
            {"answer": "Yes.", "grounded": True, "cited": []},
            context={"offered_artifact_ids": ["real", "second"]},
        )
        assert answer.grounded is True
        assert answer.cited == ["real", "second"]

    def test_grounded_without_citations_and_nothing_fed_downgrades(self):
        answer = Answer.model_validate(
            {"answer": "Yes.", "grounded": True, "cited": []},
            context={},
        )
        assert answer.grounded is False
        assert answer.cited == []

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
        """Seen in the wild: 'NotesNotFetched', 'CollectionDump'. They pass the word
        count because they contain no spaces, and they cannot be used as a topic."""
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

    def test_a_grounded_answer_without_citations_is_salvaged_not_failed(
        self, store, quiet_queue, monkeypatch
    ):
        """FIX.1: the model returns a correct grounded answer but forgets to cite;
        the validator backfills the passages it was fed instead of raising, so the
        turn lands `done` with the answer text rather than the failure string."""
        note = notes.create(body="# Joints\n\nA joint that moves outlasts one that does not.")
        chat = chats.create()

        found = [
            {
                "artifact_id": note["artifact"]["id"],
                "title": "Joints",
                "text": "A joint that moves outlasts one that does not.",
                "kind": "note",
            }
        ]
        monkeypatch.setattr(chats, "passages", lambda *a, **k: found)

        class _ValidatingProvider:
            """A provider that runs the real Answer validator, unlike FakeProvider."""

            def complete(self, system, user, response_model, context=None, max_retries=3):
                return response_model.model_validate(
                    {"answer": "Movement outlasts rigidity.", "grounded": True, "cited": []},
                    context=context,
                )

        monkeypatch.setattr(chats, "get_provider", lambda *a, **k: _ValidatingProvider())

        msg = chats.run_answer(chat["chat"]["id"], "what outlasts what?")
        assert msg["text"] == "Movement outlasts rigidity."
        assert msg["grounded"] is True
        assert msg["cited"] == [note["artifact"]["id"]]

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

    def test_a_naming_db_write_failure_does_not_lose_a_done_answer(
        self, store, quiet_queue, answered, async_turns, monkeypatch
    ):
        """I8.3: the model-call failure above is caught inside `_name`; the dangerous
        case is a DB write raising after the answer already committed `done`. That
        write must never flip the stored turn to failed or overwrite its text."""
        import contextlib

        chat = chats.create()
        answered.passages = [{"artifact_id": "a", "title": "T", "text": "body", "kind": "note"}]
        answered(
            Answer=Answer(answer="Nothing here bears on it.", grounded=False, cited=[]),
            ChatTitle=ChatTitle(title="On ceramics"),
            ChatTopics=ChatTopics(topics=["kilns", "glazes"]),
        )

        real_transaction = db.transaction

        class _GuardedConn:
            """A stand-in for the yielded connection: only `execute` is used on it
            (the transaction generator commits and closes the real connection), and
            the title write is the one call that raises."""

            def __init__(self, conn):
                self._conn = conn

            def execute(self, sql, *args):
                if sql.startswith("UPDATE chats SET title"):
                    raise RuntimeError("the title write fell over")
                # noqa: S608 - the SQL is forwarded verbatim to the connection's
                # own parameterized execute; this wrapper only intercepts one call.
                return self._conn.execute(sql, *args)

        @contextlib.contextmanager
        def _title_write_fails():
            with real_transaction() as conn:
                yield _GuardedConn(conn)

        monkeypatch.setattr(db, "transaction", _title_write_fails)

        chats.send(chat["chat"]["id"], "what about ceramics?")
        async_turns.resolve()

        result = chats.get(chat["chat"]["id"])
        turn = result["messages"][-1]
        # The finished answer survives a naming DB-write failure, with its text.
        assert turn["status"] == "done"
        assert turn["text"] == "Nothing here bears on it."
        assert turn["kind"] == "answer"
        # The title write really did fail: the chat keeps its initial placeholder
        # rather than the scripted name - and, the point of the test, the failure
        # never touched the completed turn.
        assert result["chat"]["title"] == "New chat"


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


class TestQ5AnswerPathFloor:
    """Q.5: the answer path reads the same relevance floor as /search.

    `passages()` feeds the answer model, and it used to trust the fused RRF
    score from `store.search` - which can look strong on a gibberish query
    (a rank-1 on a low-rank list), so an answer over a no-match question
    grounded on far neighbors instead of refusing. The floor now reads the
    raw per-chunk legs, exactly as `_hybrid_results` does for /search.
    """

    def _library(self, store, monkeypatch):
        conn = db.get_conn()
        try:
            for aid, title, body in [
                ("a1", "Rooftop farming", "A city can feed itself from its rooftops."),
                ("a2", "Ziggurats", "A ziggurat of Ur stood in the desert."),
            ]:
                conn.execute(
                    "INSERT INTO artifacts (id, kind, title, body, content_hash, status,"
                    " created_at, updated_at) VALUES (?, 'note', ?, ?, ?, 'ok',"
                    " datetime('now'), datetime('now'))",
                    (aid, title, body, aid + "_hash"),
                )
                conn.execute(
                    "INSERT INTO chunks (id, artifact_id, ordinal, text, chunker)"
                    " VALUES (?, ?, 0, ?, 'test')",
                    ("c" + aid, aid, body),
                )
            conn.commit()
        finally:
            conn.close()
        from enqueue import config
        from enqueue.index.store import get_store

        monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
        get_store.cache_clear()
        s = get_store()
        s.ensure()
        s.upsert_chunks()
        return s

    def test_a_no_match_question_feeds_the_answer_nothing(self, store, quiet_queue, monkeypatch):
        self._library(store, monkeypatch)

        found = chats.passages("quantum flux capacitor", "library", None)

        # The floor drops the far neighbors instead of letting the answer
        # ground on them, so the refusal (grounded=false) has nothing to
        # point at - exactly the honest "nothing you have saved" answer.
        # "quantum flux capacitor"'s nearest neighbor measures ~0.40 here,
        # below DROP_BELOW, so no passage survives the two-tier gate.
        assert found == [], f"gibberish question must yield no passages, got {found}"

    def test_a_gray_zone_question_is_kept_only_if_the_judge_says_relevant(
        self, store, quiet_queue, monkeypatch
    ):
        """The gray zone (at or above DROP_BELOW, below KEEP_ABOVE) is the
        judge's patch (Q.3b), and the answer path runs the same judge as
        /search. "hyperdimensional cheese grater" measures in the gray zone
        against this corpus, so `passages()` sends it to the judge in one
        batched call: a "not relevant" ruling feeds the answer nothing, a
        "relevant" ruling lets the passage through."""
        from enqueue.retrieve import candidates as cand

        self._library(store, monkeypatch)

        class _Judge:
            model = "test-model"

            def __init__(self, verdicts):
                self.verdicts = verdicts

            def complete(self, system, user, response_model, context=None, max_retries=3):
                return response_model(verdicts=self.verdicts)

        monkeypatch.setattr(
            cand, "get_provider", lambda *a, **k: _Judge([{"id": "a1", "relevant": False}])
        )
        found = chats.passages("hyperdimensional cheese grater", "library", None)
        assert found == [], f"judge said not relevant, expected no passages, got {found}"
        # Clear the judge's cache and rule it relevant.
        conn = db.get_conn()
        try:
            conn.execute("DELETE FROM derived_values WHERE scope = 'gray_judge'")
            conn.commit()
        finally:
            conn.close()
        monkeypatch.setattr(
            cand, "get_provider", lambda *a, **k: _Judge([{"id": "a1", "relevant": True}])
        )
        found = chats.passages("hyperdimensional cheese grater", "library", None)
        assert len(found) == 1
        assert found[0]["artifact_id"] == "a1"

    def test_a_real_question_still_finds_its_passages(self, store, quiet_queue, monkeypatch):
        self._library(store, monkeypatch)

        found = chats.passages("rooftops", "library", None)

        assert found, "a real question must still fill the passage window"
        assert "a1" in {p["artifact_id"] for p in found}


class TestFacetEntityFloor:
    """FIX.2 (Q.10): the facet and entity branches of `passages()` used to add
    hits with no floor check, so a question whose only match was a weak
    facet/entity vector could ground an answer the same way /search once did.
    They now face the same two-tier gate as the chunk branch.
    """

    def _library(self, store, monkeypatch):
        conn = db.get_conn()
        try:
            conn.execute(
                "INSERT INTO artifacts (id, kind, title, body, content_hash, status,"
                " created_at, updated_at) VALUES ('a1', 'note', 'Trade routes',"
                " 'Goods moved along the river, season by season.', 'a1_hash', 'ok',"
                " datetime('now'), datetime('now'))"
            )
            conn.execute(
                "INSERT INTO chunks (id, artifact_id, ordinal, text, chunker)"
                " VALUES ('c1', 'a1', 0, 'Goods moved along the river, season by season.', 'test')"
            )
            conn.execute(
                "INSERT INTO facets (id, artifact_id, level, statement, model_version, trust)"
                " VALUES ('f1', 'a1', 3, 'Ziggurats rose above the mud-brick cities.',"
                " 'test-model', 0.9)"
            )
            conn.execute(
                "INSERT INTO entities (id, artifact_id, entity, fact, model_version, trust)"
                " VALUES ('e1', 'a1', 'Ziggurat', 'A stepped temple in ancient Mesopotamia.',"
                " 'test-model', 0.5)"
            )
            conn.commit()
        finally:
            conn.close()
        from enqueue import config
        from enqueue.index.store import get_store
        from enqueue.providers.base import get_provider

        monkeypatch.setattr(config, "VECTOR_STORE", "sqlite-vec")
        get_store.cache_clear()
        s = get_store()
        s.ensure()
        s.upsert_chunks()
        s.upsert_facets()
        s.upsert_entities()
        # A facet/entity written by a different model is skipped as stale
        # (I2.3); mark them current so the floor, not staleness, is under test.
        model = get_provider(local_only=False).model
        conn = db.get_conn()
        try:
            conn.execute("UPDATE facets SET model_version = ? WHERE id = 'f1'", (model,))
            conn.execute("UPDATE entities SET model_version = ? WHERE id = 'e1'", (model,))
            conn.commit()
        finally:
            conn.close()
        return s

    def test_a_weak_facet_entity_match_feeds_the_answer_nothing(
        self, store, quiet_queue, monkeypatch
    ):
        self._library(store, monkeypatch)

        found = chats.passages("quantum flux capacitor", "library", None)

        assert found == [], f"weak facet/entity neighbors must not ground an answer, got {found}"

    def test_a_real_facet_match_still_retrieves_its_passage(self, store, quiet_queue, monkeypatch):
        self._library(store, monkeypatch)

        found = chats.passages("ziggurat", "library", None)

        assert found, "a lexical facet match must still fill the passage window"
        assert "a1" in {p["artifact_id"] for p in found}


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


class TestListingTopicsBatching:
    """P.2f: listing() filters chat_topics to the page, not the whole table."""

    def test_topics_query_is_filtered_to_the_listed_chats(self, store, monkeypatch):
        conn = db.get_conn()
        try:
            conn.execute(
                "INSERT INTO chats (id, title, created_at, updated_at) VALUES"
                " ('c1', 'one', '2026-01-01', '2026-01-02')"
            )
            conn.execute(
                "INSERT INTO chats (id, title, created_at, updated_at) VALUES"
                " ('c2', 'two', '2026-01-01', '2026-01-03')"
            )
            conn.execute(
                "INSERT INTO chat_topics (id, chat_id, topic, created_at) VALUES"
                " ('t1', 'c1', 'rooftops', '2026-01-01')"
            )
            conn.execute(
                "INSERT INTO chat_topics (id, chat_id, topic, created_at) VALUES"
                " ('t2', 'c2', 'ziggurats', '2026-01-01')"
            )
            conn.commit()
        finally:
            conn.close()

        statements: list[str] = []
        real = chats.db.get_conn

        def traced(*args, **kwargs):
            c = real(*args, **kwargs)
            c.set_trace_callback(lambda sql: statements.append(sql))
            return c

        monkeypatch.setattr(chats.db, "get_conn", traced)

        items = chats.listing(limit=1)["items"]
        assert [c["id"] for c in items] == ["c2"]
        # Only c2's topic is loaded; c1's stays untouched.
        assert items[0]["topics"] == ["ziggurats"]

        topic_sql = [
            s for s in statements if "chat_topics" in s and s.lstrip().startswith("SELECT")
        ]
        assert len(topic_sql) == 1, f"expected one topics SELECT, saw: {topic_sql}"
        assert "json_each" in topic_sql[0], "the topics SELECT must filter by listed chat ids"


class TestPassageShapeForTheAnswerModel:
    """L.1: the answer passage carries the artifact kind and marks annotation
    text as a note ON the artifact, so the model can tell an image with a
    user-supplied note from a standalone text note. Reproduces the bug from
    PLAN Phase L ("just text and not an image")."""

    class _RecordingProvider(FakeProvider):
        def __init__(self, **byname):
            super().__init__(**byname)
            self.last_user = ""

        def complete(self, system, user, response_model, context=None, max_retries=3):
            self.last_user = user
            return super().complete(system, user, response_model, context, max_retries)

    def test_passage_header_carries_the_kind(self, store, monkeypatch):
        """Before L.1: the passage header was `[id] title\\n text` with no kind,
        so the model could not distinguish an image-with-annotation from a note.
        After L.1: the header is `[image] title\\n text` so the kind is on screen."""
        captured = self._RecordingProvider(
            Answer=Answer(
                answer="It is an image of a small reindeer with a pink hat.",
                grounded=True,
                cited=["aid-image"],
            )
        )
        monkeypatch.setattr(chats, "get_provider", lambda *a, **k: captured)
        chats._ask_model(
            question="what is the chopper image?",
            history="",
            found=[
                {
                    "artifact_id": "aid-image",
                    "title": "chopper.png",
                    "kind": "image",
                    "text": "tony tony chopper",
                }
            ],
        )

        assert "[image] (id: aid-image) chopper.png" in captured.last_user, (
            "the kind prefix must ride with the passage header so the model knows "
            "the artifact kind (L.1), and the artifact id must be on screen so the "
            "model can cite it (CHATBUG.1); got:\n" + captured.last_user
        )

    def test_annotation_sourced_chunk_text_is_tagged_as_a_note(self, store):
        """Before L.1: chunk text merged annotation prose with artifact body
        silently, so a passage over an image whose only text was an annotation
        looked identical to a passage over a note. After L.1: annotation text
        is prefixed so the model can see it is commentary ON the artifact,
        not the artifact's own body. PLAN Phase L chopper repro."""
        import hashlib
        import uuid

        from enqueue import config
        from enqueue.ingest import chunk as ingest_chunk

        # An image whose vision describe failed (status='text_only', body NULL):
        # the only searchable text on the artifact is the user-supplied
        # annotation we are about to add. This is the chopper repro from PLAN.
        artifact_id = str(uuid.uuid4())
        data = b"\x89PNG\r\n\x1a\n" + artifact_id.encode()
        digest = hashlib.sha256(data).hexdigest()
        blob = config.BLOB_DIR / digest
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(data)
        now = "2024-01-01T00:00:00+00:00"
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO artifacts (id, kind, title, body, content_hash, mime,"
                " filename, created_at, updated_at, status) VALUES (?, 'image',"
                " 'chopper.png', NULL, ?, 'image/png', 'chopper.png', ?, ?,"
                " 'text_only')",
                (artifact_id, digest, now, now),
            )
            conn.execute(
                "INSERT INTO annotations (id, artifact_id, text, created_at) VALUES"
                " (?, ?, 'tony tony chopper', ?)",
                (str(uuid.uuid4()), artifact_id, now),
            )

        conn = db.get_conn()
        try:
            ingest_chunk.chunk_artifact(conn, artifact_id)
            chunks = conn.execute(
                "SELECT text FROM chunks WHERE artifact_id = ?", (artifact_id,)
            ).fetchall()
        finally:
            conn.close()

        joined = "\n\n".join(c["text"] for c in chunks)
        assert "(note added by you) tony tony chopper" in joined, (
            "annotation text must carry the (note added by you) marker so the "
            "model can attribute the line to a user-supplied note on the "
            "artifact, not the artifact's own body (L.1); got:\n" + joined
        )
