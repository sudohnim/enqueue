"""The notes a question names: by title, or by a person, place or thing named in them.

A question that lists names ("a council of Taleb, Thrawn, Sun Tzu and Marcus Aurelius")
is one embedding that blurs them all, and a keyword search that needs every word in one
passage finds none of them. So chat (`chats._library_passages`) looks for each name on
its own: a live note whose whole title appears in the question, or whose current
entities do. Plain matching in this process, no model call.
"""

from __future__ import annotations

from .. import db
from ..index.store_sqlite import _FILLER
from .candidates import _word_form, hit_is_stale

# A one-word title or name this short is a word, not a name ("art", "tax").
MIN_ONE_WORD = 4

_LIVE = "a.deleted_at IS NULL AND a.vaulted_at IS NULL AND a.embedded_at IS NULL"


def _named_in(name: str, question: str) -> bool:
    """Whether `name` (word form) appears in `question` (word form) as whole words."""
    words = name.split()
    if not words or all(w in _FILLER for w in words):
        return False
    if len(words) == 1 and (len(name) < MIN_ONE_WORD or name.isdigit()):
        return False
    return f" {name} " in f" {question} "


def named(question: str, limit: int) -> list[str]:
    """Ids of the live notes the question names, best first: a title outranks a name
    inside a note, and a note named twice outranks one named once."""
    from ..ingest.related import MENTION_MAX_SHARED

    asked = _word_form(question)
    if not asked or limit <= 0:
        return []
    score: dict[str, float] = {}
    conn = db.reader()
    try:
        for row in conn.execute(f"SELECT a.id, a.title FROM artifacts a WHERE {_LIVE}"):
            title = _word_form(row["title"] or "")
            if _named_in(title, asked):
                score[row["id"]] = score.get(row["id"], 0.0) + 2.0 + len(title.split()) / 10

        holders: dict[str, set[str]] = {}
        cache: dict = {}
        for row in conn.execute(
            "SELECT e.artifact_id, e.entity, e.body_version FROM entities e"
            f" JOIN artifacts a ON a.id = e.artifact_id WHERE {_LIVE}"
        ):
            name = _word_form(row["entity"])
            if not _named_in(name, asked):
                continue
            if hit_is_stale(conn, dict(row), cache):
                continue
            holders.setdefault(name, set()).add(row["artifact_id"])
        for name, ids in holders.items():
            if len(ids) > MENTION_MAX_SHARED:  # too common to point at anything
                continue
            for aid in ids:
                score[aid] = score.get(aid, 0.0) + 1.0
    finally:
        conn.close()
    return sorted(score, key=lambda aid: (-score[aid], aid))[:limit]
