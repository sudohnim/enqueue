"""Two-sided questions: each side searched on its own, both reach the answer."""

from __future__ import annotations

import pytest

from enqueue import chats
from enqueue.retrieve.decompose import parts


@pytest.mark.parametrize(
    "question, sides",
    [
        ("Compare my notes on stoicism and epicureanism?", ["stoicism", "epicureanism"]),
        ("contrast wedging clay with kneading bread", ["wedging clay", "kneading bread"]),
        (
            "What's the difference between sourdough and yeast bread",
            ["sourdough", "yeast bread"],
        ),
        ("how does agile compare to waterfall?", ["agile", "waterfall"]),
        ("kanban vs scrum", ["kanban", "scrum"]),
    ],
)
def test_comparisons_split_into_their_sides(question, sides):
    assert parts(question) == sides


@pytest.mark.parametrize(
    "question",
    [
        "what did I save about bread and butter pudding",
        "notes on salt and pepper",
        "compare",
    ],
)
def test_other_questions_stay_whole(question):
    assert parts(question) == []


def _p(pid):
    return {"id": pid, "score": 1.0}


def test_sides_are_interleaved_then_topped_up_from_the_whole(monkeypatch):
    results = {
        "kanban": [_p("k1"), _p("k2"), _p("k3")],
        "scrum": [_p("s1")],
        "kanban vs scrum": [_p("k1"), _p("w1")],
    }
    monkeypatch.setattr(chats, "_library_passages", lambda q: results[q])

    found = chats.passages("kanban vs scrum", "library", None)

    assert [p["id"] for p in found] == ["k1", "s1", "k2", "k3", "w1"]


def test_a_plain_question_searches_once(monkeypatch):
    asked = []
    monkeypatch.setattr(chats, "_library_passages", lambda q: asked.append(q) or [])

    chats.passages("what did I save about kilns", "library", None)

    assert asked == ["what did I save about kilns"]
