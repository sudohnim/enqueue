"""Brain food: one relationship drawn across notes from different fields, each day.

Instead of bringing one forgotten note back, the wall shows two or three notes that
make the same point from far-apart fields, and what that shared point is. This is the
far analogy from Epstein's *Range*: comparing cases from different domains is how a
person finds the deep structure under the surface, and the farther apart the cases,
the better the ideas they lead to. But people rarely make the comparison unprompted.

The set comes from the links `ingest/related.py` already keeps. Idea links come
first: the ingest model judged that the two notes make the same point. Only when
there are none, mention links between notes on different subjects (a shared name is
thin fare beside a shared idea). Pairs on the same subject never count. The
pick favours the farthest pairs (`related.distance`), rotating daily through the top
ROTATE so one strong pair does not hold the slot. A third note joins when one of the
pair has another idea link. The same day always gives the same set.

The words come from one call to the chat model per set, cached in `derived_values`
(scope `brain_food`): the shared idea, how each note shows it, and a question to take
further. The call runs in the background; until it lands, or with no model, the card
shows the judge's own sentence for the link. A set with a local-only note goes to the
local model only. The model is shown titles and summary lines, never the notes' text.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import date, datetime, timezone

from pydantic import BaseModel, field_validator

from . import db, prompts

log = logging.getLogger(__name__)

# How many of the farthest pairs the days rotate through.
ROTATE = 7
# The most notes in one set.
MAX_NOTES = 3
# The summary levels the model is shown: subject, mechanism, principle.
LEVELS = (1, 2, 3)
FALLBACK_QUESTION = "Where else have you seen this work?"

_LIVE = "a.deleted_at IS NULL AND a.vaulted_at IS NULL AND a.embedded_at IS NULL"


class _Part(BaseModel):
    id: str
    how: str

    @field_validator("how")
    @classmethod
    def _short(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value or len(value.split()) > 30:
            raise ValueError("how must be one sentence of at most 30 words")
        return value


class _Food(BaseModel):
    idea: str
    parts: list[_Part]
    question: str

    @field_validator("idea")
    @classmethod
    def _one_sentence(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value or len(value.split()) > 30:
            raise ValueError("idea must be one sentence of at most 30 words")
        return value

    @field_validator("question")
    @classmethod
    def _a_question(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value.endswith("?") or len(value.split()) > 30:
            raise ValueError("question must be one question of at most 30 words")
        return value


def _pairs(conn) -> list[dict]:
    """Every pair worth showing, best first: idea links before mention links, the
    farthest first."""
    rows = conn.execute(
        "SELECT r.artifact_id AS a, r.related_id AS b, r.kind, r.distance, r.point, r.via"
        " FROM related r JOIN artifacts a ON a.id = r.artifact_id"
        " JOIN artifacts b ON b.id = r.related_id"
        f" WHERE r.artifact_id < r.related_id AND r.kind IN ('idea', 'mention') AND {_LIVE}"
        " AND b.deleted_at IS NULL AND b.vaulted_at IS NULL AND b.embedded_at IS NULL"
    ).fetchall()
    pairs = [dict(r) for r in rows]
    pairs.sort(key=lambda p: (p["kind"] != "idea", -(p["distance"] or 0.0), p["a"], p["b"]))
    return pairs


def pick(today: date | None = None) -> dict | None:
    """{"ids", "links"} for today's set, or None when the library has no relationship
    across fields yet. `links` are the pairs inside the set, each with its kind, the
    judge's sentence (`point`) or the shared name (`via`)."""
    today = today or datetime.now(timezone.utc).date()
    conn = db.get_conn()
    try:
        pairs = _pairs(conn)
    finally:
        conn.close()
    # A shared name is thin fare beside a shared idea: only when there is no idea link.
    ideas = [p for p in pairs if p["kind"] == "idea"]
    if not pairs:
        return None
    top = (ideas or pairs)[:ROTATE]
    first = top[today.toordinal() % len(top)]
    ids = [first["a"], first["b"]]
    links = [first]
    # A third note: the farthest idea link from either of the two to a note outside.
    for p in pairs:
        if len(ids) >= MAX_NOTES:
            break
        if p["kind"] != "idea" or (p["a"] in ids) == (p["b"] in ids):
            continue
        hub = p["a"] if p["a"] in ids else p["b"]
        # The note both links pass through sits in the middle, so the chain reads across.
        ids = [i for i in ids if i != hub] + [hub, p["b"] if hub == p["a"] else p["a"]]
        links.append(p)
    keep = ("a", "b", "kind", "point", "via")
    return {"ids": ids, "links": [{k: p[k] for k in keep} for p in links]}


def _faces(conn, ids: list[str]) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT id, kind, title FROM artifacts WHERE id IN (SELECT value FROM json_each(?))",
        (json.dumps(ids),),
    ).fetchall()
    faces = {r["id"]: {"kind": r["kind"], "title": r["title"], "lines": []} for r in rows}
    for r in conn.execute(
        "SELECT artifact_id, level, statement FROM facets"
        " WHERE artifact_id IN (SELECT value FROM json_each(?))"
        f" AND level IN ({','.join('?' * len(LEVELS))}) ORDER BY level, statement",
        (json.dumps(ids), *LEVELS),
    ):
        if r["artifact_id"] in faces:
            faces[r["artifact_id"]]["lines"].append(r["statement"])
    return faces


def _key(ids: list[str], faces: dict[str, dict]) -> tuple[str, str]:
    """The cache key of a set: its ids in order, and a stamp of what the model is shown,
    so the words are written again once a note's summary changes."""
    subject = "|".join(sorted(ids))
    shown = [[faces.get(i, {}).get("title"), faces.get(i, {}).get("lines")] for i in sorted(ids)]
    return subject, hashlib.sha256(json.dumps(shown).encode()).hexdigest()[:16]


def _cached(conn, key: tuple[str, str]) -> dict | None:
    row = conn.execute(
        "SELECT value FROM derived_values WHERE scope = 'brain_food' AND subject = ?"
        " AND attribute = ? AND source = 'model'",
        key,
    ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["value"])
    except ValueError:
        return None


_lock = threading.Lock()
_writing: set[str] = set()
# Sets whose call failed today, so a wall reload does not ask again: {subject: day}.
_failed: dict[str, str] = {}


def _write(ids: list[str], links: list[dict], key: tuple[str, str], day: str) -> None:
    """Ask the chat model for the set's words and cache them. Never raises."""
    from . import privacy
    from .providers import pause
    from .providers.base import get_provider

    try:
        if pause.active():
            return
        conn = db.get_conn()
        try:
            faces = _faces(conn, ids)
        finally:
            conn.close()
        blocks = []
        for i in ids:
            face = faces.get(i) or {"kind": "item", "title": None, "lines": []}
            blocks.append(
                f"note id: {i}\n[{face['kind']}] {face['title'] or '(untitled)'}\n"
                + "\n".join(f"- {line}" for line in face["lines"][:6])
            )
        said = [p["point"] or (f"Both mention {p['via']}." if p["via"] else "") for p in links]
        local = bool(privacy.local_only_ids(ids))
        provider = get_provider(local_only=local, role="chat")
        food = provider.complete(
            system=prompts.BRAIN_FOOD,
            user="Notes:\n\n"
            + "\n\n".join(blocks)
            + "\n\nWhat was already noticed about them:\n"
            + "\n".join(f"- {s}" for s in said if s),
            response_model=_Food,
        )
        parts = {p.id: p.how for p in food.parts if p.id in ids}
        if set(parts) != set(ids):
            raise ValueError("the answer did not cover every note")
        value = json.dumps({"idea": food.idea, "parts": parts, "question": food.question})
        with db.transaction() as conn:
            conn.execute(
                "DELETE FROM derived_values WHERE scope = 'brain_food' AND subject = ?",
                (key[0],),
            )
            conn.execute(
                "INSERT INTO derived_values"
                " (scope, subject, attribute, value, grounded, source, model_version,"
                " created_at) VALUES ('brain_food', ?, ?, ?, 1, 'model', ?, ?)",
                (key[0], key[1], value, getattr(provider, "model", ""), db.now()),
            )
    except Exception as exc:  # noqa: BLE001 - the card falls back to the link's own words
        log.info("brain food not written: %s", exc)
        _failed[key[0]] = day
    finally:
        with _lock:
            _writing.discard(key[0])


def today(day: date | None = None, background: bool = True) -> dict | None:
    """Today's set with its words, or None. `food` is the model's words when written;
    `writing` says they are on the way. `background=False` writes them in this thread
    (tests)."""
    day = day or datetime.now(timezone.utc).date()
    chosen = pick(day)
    if chosen is None:
        return None
    ids = chosen["ids"]
    conn = db.get_conn()
    try:
        key = _key(ids, _faces(conn, ids))
        food = _cached(conn, key)
    finally:
        conn.close()
    writing = False
    if food is None and _failed.get(key[0]) != day.isoformat():
        with _lock:
            writing = key[0] in _writing
            start = not writing
            if start:
                _writing.add(key[0])
        if start:
            args = (ids, chosen["links"], key, day.isoformat())
            if background:
                threading.Thread(target=_write, args=args, daemon=True).start()
                writing = True
            else:
                _write(*args)
                conn = db.get_conn()
                try:
                    food = _cached(conn, key)
                finally:
                    conn.close()
    if food is None:
        first = chosen["links"][0]
        idea = first["point"] or (f"Both mention {first['via']}." if first["via"] else "")
        food = {"idea": idea, "parts": {}, "question": FALLBACK_QUESTION}
    return {"ids": ids, "links": chosen["links"], "food": food, "writing": writing}
