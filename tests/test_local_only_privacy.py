"""A local-only artifact's text never reaches a remote model (privacy.py).

Before the fix, chat answers, the gray-zone judge, model re-ranking and attribute
extraction put local-only text in prompts to whatever backend was configured.
"""

from __future__ import annotations

from enqueue import chats, db, derive, notes, privacy
from enqueue.providers.ollama import OpenAICompatibleProvider
from enqueue.retrieve import candidates, model_rank


class _Remote:
    """A fake remote provider (no loopback base_url) that records its prompts."""

    name = "fake"
    model = "remote-model"
    base_url = "https://models.example/v1"

    def __init__(self, reply=None):
        self.reply = reply or {}
        self.users: list[str] = []

    def complete(self, system, user, response_model, context=None, max_retries=None):
        self.users.append(system + "\n" + user)
        return response_model(**self.reply)


def _note(body: str, local_only: bool = False) -> str:
    aid = notes.create(body=body)["artifact"]["id"]
    if local_only:
        with db.transaction() as conn:
            conn.execute("UPDATE artifacts SET local_only = 1 WHERE id = ?", (aid,))
    return aid


def test_only_a_non_loopback_endpoint_counts_as_remote():
    assert not privacy.is_remote(OpenAICompatibleProvider(base_url="http://127.0.0.1:11434/v1"))
    assert not privacy.is_remote(OpenAICompatibleProvider(base_url="http://localhost:11434/v1"))
    assert privacy.is_remote(OpenAICompatibleProvider(base_url="https://openrouter.ai/api/v1"))


def test_the_gray_zone_judge_never_sees_a_local_only_note(store, quiet_queue, monkeypatch):
    public = _note("Glaze recipes for cone six.")
    private = _note("My therapist's notes on grief.", local_only=True)
    remote = _Remote({"verdicts": [{"id": public, "relevant": False}]})
    monkeypatch.setattr(candidates, "get_provider", lambda **kw: remote)

    kept = candidates.judge_gray_zone(
        "grief",
        [
            {"artifact_id": public, "title": "Glaze", "snippet": "Glaze recipes"},
            {"artifact_id": private, "title": "Grief", "snippet": "therapist grief"},
        ],
    )

    assert private in kept  # unjudged is kept, as for any item the judge does not cover
    assert public not in kept
    assert all(private not in u and "therapist" not in u for u in remote.users)


def test_model_rank_orders_around_a_local_only_note(store, quiet_queue, monkeypatch):
    a, c = _note("First public note."), _note("Second public note.")
    b = _note("A private note.", local_only=True)
    remote = _Remote({"ids": [c, a]})
    import enqueue.providers.base as base_mod

    monkeypatch.setattr(base_mod, "get_provider", lambda **kw: remote)
    hits = [{"artifact_id": i, "title": i, "snippet": "text"} for i in (a, b, c)]

    ranked = [h["artifact_id"] for h in model_rank.order("q", hits)]

    assert ranked == [c, b, a]  # b keeps its place; the model ordered the rest
    assert all(b not in u for u in remote.users)


def test_chat_passages_leave_out_local_only_notes_for_a_remote_model(
    store, quiet_queue, monkeypatch
):
    public = _note("Kiln firing schedule.")
    private = _note("Kiln accident and the hospital visit.", local_only=True)
    found = [
        {"id": "p1", "artifact_id": private, "title": "Kiln accident", "text": "hospital"},
        {"id": "p2", "artifact_id": public, "title": "Kiln firing", "text": "schedule"},
    ]
    monkeypatch.setattr(chats, "_everything_passages", lambda q: list(found))

    monkeypatch.setattr(chats, "get_provider", lambda **kw: _Remote())
    assert [p["artifact_id"] for p in chats.passages("kiln", "everything", None)] == [public]

    local = OpenAICompatibleProvider(base_url="http://127.0.0.1:11434/v1")
    monkeypatch.setattr(chats, "get_provider", lambda **kw: local)
    assert len(chats.passages("kiln", "everything", None)) == 2  # a local model may read it


def test_a_chat_about_a_local_only_note_uses_the_local_model(store, quiet_queue, monkeypatch):
    private = _note("A private journal entry.", local_only=True)
    public = _note("A public note.")
    asked: list[bool] = []
    monkeypatch.setattr(
        chats, "get_provider", lambda local_only=False, **kw: asked.append(local_only) or None
    )

    with db.transaction() as conn:
        for cid, aid in (("c-private", private), ("c-public", public)):
            conn.execute(
                "INSERT INTO chats (id, title, scope_kind, scope_id, created_at, updated_at)"
                " VALUES (?, '', 'artifact', ?, ?, ?)",
                (cid, aid, db.now(), db.now()),
            )
    chats._chat_provider("c-private")
    chats._chat_provider("c-public")

    assert asked == [True, False]


def test_extracting_an_attribute_from_a_local_only_note_stays_local(
    store, quiet_queue, monkeypatch
):
    private = _note("Born in 1961 in Hanoi.", local_only=True)
    asked: list[bool] = []

    def provider(local_only=False, **kw):
        asked.append(local_only)
        raise RuntimeError("no model in tests")

    monkeypatch.setattr(derive, "get_provider", provider)
    derive.extract(private, "birth year", "the year they were born")

    assert asked == [True]
