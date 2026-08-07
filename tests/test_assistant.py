"""The assistant router: one model call that picks a skill, clamped to the floor.

Rule 1 lives here, in code: `route` can never raise and can never return a
skill name outside the registry. The floor is `answer` - grounded and safe,
never wrong to fall back to. The provider is stubbed the way the existing
tests stub it (see tests/test_pivot.py): the module's `get_provider` binding
is replaced with one returning a fake provider, so no real model call ever
happens.
"""

from __future__ import annotations

from enqueue import assistant, chats, pivot
from enqueue.schemas import ChatTitle, ChatTopics


class _FakeProvider:
    """A scripted provider: one reply per call, or the same reply each time."""

    name = "fake"
    model = "fake-model"

    def __init__(self, script):
        self.script = script
        self.calls = 0

    def complete(self, system, user, response_model, context=None, max_retries=None):
        self.calls += 1
        reply = self.script.pop(0) if isinstance(self.script, list) else self.script
        if isinstance(reply, Exception):
            raise reply
        return response_model(**reply)


class _ByNameProvider:
    """Answers each response_model from a name-keyed script, like test_chats."""

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


class TestRoute:
    def test_routes_to_a_named_skill(self, monkeypatch):
        provider = _FakeProvider({"skill": "organize"})
        monkeypatch.setattr(assistant, "get_provider", lambda: provider)

        assert assistant.route("organize my notes by region") == "organize"

    def test_unknown_skill_name_falls_to_answer(self, monkeypatch):
        # Rule 1: a name outside the registry is never run, it falls to answer.
        provider = _FakeProvider({"skill": "translate"})
        monkeypatch.setattr(assistant, "get_provider", lambda: provider)

        assert assistant.route("translate this") == "answer"

    def test_model_error_falls_to_answer(self, monkeypatch):
        # Rule 1: a failed model call is a floor, not a crash.
        provider = _FakeProvider(RuntimeError("the router fell over"))
        monkeypatch.setattr(assistant, "get_provider", lambda: provider)

        assert assistant.route("anything") == "answer"

    def test_empty_request_falls_to_answer_without_calling_the_model(self, monkeypatch):
        provider = _FakeProvider({"skill": "organize"})
        monkeypatch.setattr(assistant, "get_provider", lambda: provider)

        assert assistant.route("") == "answer"
        assert assistant.route("   ") == "answer"
        # The model is never called for an empty request.
        assert provider.calls == 0


class TestDispatch:
    """The worker is the dispatcher: route -> run -> store a typed turn.

    Submitting returns a pending turn; resolving the recorded job runs the real
    dispatch path. The router is stubbed through assistant.get_provider, the
    answer path through chats.get_provider + chats.passages (exactly how
    test_chats stubs it), and organize's pivot through pivot.plan / pivot.run
    directly, so no real model call ever happens.
    """

    def _stub_router(self, monkeypatch, skill: str):
        provider = _FakeProvider({"skill": skill})
        monkeypatch.setattr(assistant, "get_provider", lambda: provider)
        return provider

    def _stub_answer(self, monkeypatch, passages: list | None = None):
        """The answer path, scripted for the exchange: passages, then the name.
        The refusal branch of _ask_model (empty passages) makes no Answer call;
        naming still calls the provider once for the title."""
        monkeypatch.setattr(chats, "passages", lambda *a, **k: passages or [])
        provider = _ByNameProvider(
            ChatTitle=ChatTitle(title="Movement over rigidity"),
            ChatTopics=ChatTopics(topics=["tolerance", "failure under load"]),
        )
        monkeypatch.setattr(chats, "get_provider", lambda: provider)
        return provider

    def _resolve(self, async_turns, chat_id):
        """Run the recorded worker jobs synchronously and re-read the chat."""
        async_turns.resolve()
        return chats.get(chat_id)

    def test_send_answer_stores_an_answer_turn(self, store, quiet_queue, monkeypatch, async_turns):
        chat = chats.create()
        self._stub_router(monkeypatch, "answer")
        self._stub_answer(monkeypatch)

        chats.send(chat["chat"]["id"], "what outlasts what?")
        result = self._resolve(async_turns, chat["chat"]["id"])

        stored = result["messages"][-1]
        assert stored["role"] == "assistant"
        assert stored["kind"] == "answer"
        assert stored["payload"] is None
        assert stored["status"] == "done"

    def test_send_organize_stores_an_organize_turn(
        self, store, quiet_queue, monkeypatch, async_turns
    ):
        chat = chats.create()
        spec = {
            "subset": {"kind": "ids", "value": "a b"},
            "steps": [{"op": "extract", "attribute": "author", "instruction": "the author"}],
            "group_by": "author",
            "bucketize": False,
            "bucketize_instruction": "",
        }
        groups = {
            "groups": [{"key": "Garcia Marquez", "artifact_ids": ["a", "b"], "grounded": True}],
            "truncated": False,
            "group_by": "author",
        }
        self._stub_router(monkeypatch, "organize")
        monkeypatch.setattr(pivot, "plan", lambda text: spec)
        monkeypatch.setattr(pivot, "run", lambda spec: groups)
        self._stub_answer(monkeypatch)

        chats.send(chat["chat"]["id"], "organize my notes by author")
        result = self._resolve(async_turns, chat["chat"]["id"])

        stored = result["messages"][-1]
        assert stored["kind"] == "organize"
        # The payload round-trips through JSON to the exact spec the turn ran.
        assert stored["payload"] == spec
        assert stored["text"].startswith("Organized 2 notes by author")

    def test_organize_planerror_falls_to_answer(self, store, quiet_queue, monkeypatch, async_turns):
        # Rule 1: a structured skill that cannot execute lands on the floor.
        chat = chats.create()
        self._stub_router(monkeypatch, "organize")

        def boom(text):
            raise pivot.PivotError("Tell me what to group and how.")

        monkeypatch.setattr(pivot, "plan", boom)
        self._stub_answer(monkeypatch)

        chats.send(chat["chat"]["id"], "organize my notes by author")
        result = self._resolve(async_turns, chat["chat"]["id"])

        stored = result["messages"][-1]
        assert stored["kind"] == "answer"
        assert stored["payload"] is None

    def test_organize_runtime_error_falls_to_answer(
        self, store, quiet_queue, monkeypatch, async_turns
    ):
        # Rule 1, the harder case: the plan succeeds but the RUN throws mid-way (a
        # stale index id, a KeyError). This used to escape as a 500 - "the curator
        # could not answer: '<uuid>'". It must fall to the floor like any other
        # organize failure, never crash the turn.
        chat = chats.create()
        self._stub_router(monkeypatch, "organize")
        monkeypatch.setattr(pivot, "plan", lambda text: {"stub": "spec"})

        def boom(spec):
            raise KeyError("14aaa071-06c6-41a4-bd29-4a59a63af79a")

        monkeypatch.setattr(pivot, "run", boom)
        self._stub_answer(monkeypatch)

        chats.send(chat["chat"]["id"], "does i have any notes on presidents")
        result = self._resolve(async_turns, chat["chat"]["id"])

        stored = result["messages"][-1]
        assert stored["kind"] == "answer"
        assert stored["payload"] is None

    def test_force_skill_answer_bypasses_router(self, store, quiet_queue, monkeypatch, async_turns):
        # Rule 2: "answer instead" re-sends the same text forcing answer, and the
        # router is not even consulted - not on the request path, not in the worker.
        chat = chats.create()
        router = self._stub_router(monkeypatch, "organize")
        self._stub_answer(monkeypatch)

        chats.send(chat["chat"]["id"], "organize my notes by author", force_skill="answer")
        result = self._resolve(async_turns, chat["chat"]["id"])

        stored = result["messages"][-1]
        assert stored["kind"] == "answer"
        assert router.calls == 0


class TestAskRoutesTheFirstMessage(TestDispatch):
    """The eye opens a new chat, so the first message must route like any later
    turn. `ask` creates the chat and submits through the worker; a fresh "organize
    my notes by X" is grouped, not answered - and a failing first turn resolves to
    a failed turn inside the chat, never an empty wall entry.
    """

    def test_first_message_routes_to_organize(self, store, quiet_queue, monkeypatch, async_turns):
        spec = {
            "subset": {"kind": "ids", "value": "a b"},
            "steps": [{"op": "extract", "attribute": "author", "instruction": "the author"}],
            "group_by": "author",
            "bucketize": False,
            "bucketize_instruction": "",
        }
        groups = {
            "groups": [{"key": "Garcia Marquez", "artifact_ids": ["a", "b"], "grounded": True}],
            "truncated": False,
            "group_by": "author",
        }
        self._stub_router(monkeypatch, "organize")
        monkeypatch.setattr(pivot, "plan", lambda text: spec)
        monkeypatch.setattr(pivot, "run", lambda spec: groups)
        self._stub_answer(monkeypatch)

        made = chats.ask("organize my notes by author")
        result = self._resolve(async_turns, made["chat"]["id"])

        stored = result["messages"][-1]
        assert stored["kind"] == "organize"
        assert stored["payload"] == spec

    def test_failed_first_turn_resolves_inside_the_chat(
        self, store, quiet_queue, monkeypatch, async_turns
    ):
        # The old promise changed shape: a failing first turn used to delete its
        # own husk. Now the chat exists from submit time, and the failure is a
        # `failed` turn inside it - nothing empty on the wall, nothing lost.
        self._stub_router(monkeypatch, "answer")
        self._stub_answer(monkeypatch)

        def boom(*a, **k):
            raise RuntimeError("the model fell over")

        monkeypatch.setattr(chats, "run_answer", boom)

        made = chats.ask("what outlasts what?")
        assert made["messages"][-1]["status"] == "pending"

        async_turns.resolve()
        after = chats.get(made["chat"]["id"])
        assert after["messages"][-1]["status"] == "failed"
        assert [c["id"] for c in chats.listing()["items"]] == [made["chat"]["id"]]
