"""The answer worker: a submitted job fills its pending turn, off the request.

The router is stubbed through `assistant.get_provider` and the answer path
through `chats.get_provider` + `chats.passages`, exactly as tests/test_assistant.py
does, so no real model call ever happens. The compute core is run synchronously
for the resolution tests; only the off-the-request test goes through the thread.
"""

from __future__ import annotations

import time

from enqueue import assistant, chats, chats_worker, db, notes
from enqueue.schemas import Answer, ChatTitle, ChatTopics


class _FakeProvider:
    """One scripted reply, or a script: used for the router (assistant.get_provider)."""

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


def _stub_router(monkeypatch, skill: str = "answer"):
    """The router: one cheap model call that picks a skill, stubbed to `skill`."""
    provider = _FakeProvider({"skill": skill})
    monkeypatch.setattr(assistant, "get_provider", lambda: provider)
    return provider


def _stub_answer(monkeypatch, passages: list | None = None, answer=None):
    """The answer path, scripted: passages, then naming and topics after `done`.

    `answer` is the scripted Answer reply; it is only consulted when passages are
    non-empty (the refusal branch of `_ask_model` returns without a model call).
    """
    monkeypatch.setattr(chats, "passages", lambda *a, **k: passages or [])
    byname = {
        "ChatTitle": ChatTitle(title="Movement over rigidity"),
        "ChatTopics": ChatTopics(topics=["tolerance", "failure under load"]),
    }
    if answer is not None:
        byname["Answer"] = answer
    provider = _ByNameProvider(**byname)
    monkeypatch.setattr(chats, "get_provider", lambda: provider)
    return provider


def _seed_pending(chat_id: str, text: str = "what outlasts what?") -> str:
    """Write a user turn plus a pending assistant turn, exactly as send does."""
    with db.transaction() as conn:
        chats._append(conn, chat_id, "user", text)
        message_id = chats._append(conn, chat_id, "assistant", "", status="pending")
    return message_id


def _row(message_id: str):
    conn = db.get_conn()
    try:
        return conn.execute("SELECT * FROM chat_messages WHERE id = ?", (message_id,)).fetchone()
    finally:
        conn.close()


def _citation_count(message_id: str) -> int:
    conn = db.get_conn()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM chat_citations WHERE message_id = ?", (message_id,)
        ).fetchone()["n"]
    finally:
        conn.close()


class TestSweep:
    """Startup housekeeping: pending rows from a dead worker are bound (H5.1)."""

    def test_startup_sweeps_orphaned_pending(self, store, quiet_queue):
        chat = chats.create()
        first = _seed_pending(chat["chat"]["id"], text="what outlasts what?")
        second = _seed_pending(chat["chat"]["id"], text="how does a city feed itself?")
        # A completed turn must survive the sweep untouched.
        with db.transaction() as conn:
            chats._append(conn, chat["chat"]["id"], "user", "already answered")
            done_id = chats._append(conn, chat["chat"]["id"], "assistant", "Stored.")

        assert _row(first)["status"] == "pending"
        assert _row(second)["status"] == "pending"

        assert chats_worker.sweep_orphaned_pending() == 2

        assert _row(first)["status"] == "failed"
        assert _row(first)["text"] == "That answer was interrupted. Ask again."
        assert _row(second)["status"] == "failed"
        assert _row(second)["text"] == "That answer was interrupted. Ask again."
        assert _row(done_id)["status"] == "done"
        assert _row(done_id)["text"] == "Stored."

    def test_sweep_is_idempotent(self, store, quiet_queue):
        chat = chats.create()
        message_id = _seed_pending(chat["chat"]["id"])

        assert chats_worker.sweep_orphaned_pending() == 1
        # A second sweep finds nothing left pending.
        assert chats_worker.sweep_orphaned_pending() == 0
        assert _row(message_id)["status"] == "failed"

    def test_worker_fills_a_pending_turn_to_done(self, store, quiet_queue, monkeypatch):
        note = notes.create(body="# Joints\n\nA joint that moves outlasts one that does not.")
        chat = chats.create()
        message_id = _seed_pending(chat["chat"]["id"])
        _stub_router(monkeypatch)
        _stub_answer(
            monkeypatch,
            [
                {
                    "artifact_id": note["artifact"]["id"],
                    "title": "Joints",
                    "text": "A joint that moves outlasts one that does not.",
                    "kind": "note",
                }
            ],
            answer=Answer(
                answer="Movement outlasts rigidity.",
                grounded=True,
                cited=[note["artifact"]["id"]],
            ),
        )

        chats_worker.compute(
            chats_worker.Job(chat["chat"]["id"], message_id, "what outlasts what?", None)
        )

        row = _row(message_id)
        assert row["status"] == "done"
        assert row["text"] == "Movement outlasts rigidity."
        assert row["kind"] == "answer"
        assert row["grounded"] == 1
        # Naming and retopic ran after `done`, exactly as send used to.
        assert chats.get(chat["chat"]["id"])["chat"]["title"] == "Movement over rigidity"
        assert {t["topic"] for t in chats.get(chat["chat"]["id"])["topics"]} == {
            "tolerance",
            "failure under load",
        }

    def test_worker_marks_a_failed_turn(self, store, quiet_queue, monkeypatch):
        chat = chats.create()
        message_id = _seed_pending(chat["chat"]["id"])
        _stub_router(monkeypatch)
        monkeypatch.setattr(
            chats,
            "passages",
            lambda *a, **k: [{"artifact_id": "a", "title": "T", "text": "body", "kind": "note"}],
        )
        provider = _ByNameProvider(Answer=RuntimeError("the model fell over"))
        monkeypatch.setattr(chats, "get_provider", lambda: provider)

        chats_worker.compute(
            chats_worker.Job(chat["chat"]["id"], message_id, "what outlasts what?", None)
        )

        row = _row(message_id)
        assert row["status"] == "failed"
        # A short human sentence a person can read, never the raw exception.
        assert row["text"] == "That answer could not be completed."
        assert _citation_count(message_id) == 0

    def test_worker_runs_off_the_request(self, store, quiet_queue, monkeypatch):
        chat = chats.create()
        message_id = _seed_pending(chat["chat"]["id"])
        _stub_router(monkeypatch)

        def slow_answer(chat_id, text):
            time.sleep(0.3)
            return {
                "role": "assistant",
                "text": "Slow but stored.",
                "grounded": False,
                "kind": "answer",
                "payload": None,
                "cited": [],
            }

        monkeypatch.setattr(chats, "run_answer", slow_answer)
        monkeypatch.setattr(
            chats,
            "get_provider",
            lambda: _ByNameProvider(ChatTitle=ChatTitle(title="Slow but stored")),
        )

        chats_worker.submit(
            chats_worker.Job(chat["chat"]["id"], message_id, "what outlasts what?", None)
        )

        # submit returned before the (slow) compute finished: still pending.
        assert _row(message_id)["status"] == "pending"

        assert chats_worker.wait_idle()
        assert _row(message_id)["status"] == "done"
        assert _row(message_id)["text"] == "Slow but stored."
