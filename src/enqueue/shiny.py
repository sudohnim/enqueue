"""Something shiny: one relationship drawn across notes from different fields, each day.

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
ROTATE so one strong pair does not hold the slot. "Find another" walks on through the
day's order, past the top ROTATE into every other pair, each with its own words. A third note joins when one of the
pair has another idea link. The same day always gives the same set.

The words come from one call to the chat model per set, cached in `derived_values`
(scope `shiny`): the shared idea, how each note shows it, and a question to take
further. The call runs in the background; until it lands, or with no model, the card
shows the judge's own sentence for the link. A set with a local-only note keeps that
sentence: no model reads it. The model is shown titles and summary lines, never the notes' text.

The day's card holds still; the greeting's raven (js/home.js `callShiny`) hunts for a
fresh connection on demand (`hunt`). It takes a seed note it has not used lately, finds
notes whose idea lines come close to the seed's while their subjects are far apart, and
makes one model call that keeps the truest candidate, or none (it fails closed, like the
related judge), and writes the words. Every pair shown, by the card or a hunt, is
remembered for REMEMBER_DAYS and never hunted again in that time; a seed rests for
SEED_REST_DAYS.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import threading
from datetime import date, datetime, timedelta, timezone

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
# The raven's hunt (`hunt`).
REMEMBER_DAYS = 30
SEED_REST_DAYS = 14
HUNT_SEEDS = 2  # model calls per press, at most
HUNT_CANDIDATES = 5
HUNT_MIN = 0.62  # how close two idea lines must be to be worth the model's look
IDEA_LEVELS = (2, 3)  # mechanism and principle lines

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


def _grow(first: dict, pairs: list[dict]) -> tuple[list[str], list[dict]]:
    """A pair, and a third note when one of the two has another idea link: the
    farthest one to a note outside. The note both links pass through sits in the
    middle, so the chain reads across."""
    ids = [first["a"], first["b"]]
    links = [first]
    for p in pairs:
        if len(ids) >= MAX_NOTES:
            break
        if p["kind"] != "idea" or (p["a"] in ids) == (p["b"] in ids):
            continue
        hub = p["a"] if p["a"] in ids else p["b"]
        ids = [i for i in ids if i != hub] + [hub, p["b"] if hub == p["a"] else p["a"]]
        links.append(p)
    return ids, links


def _order(today: date) -> list[tuple[list[str], list[dict]]]:
    """The day's sets, best first, computed from the links as they stand."""
    conn = db.get_conn()
    try:
        pairs = _pairs(conn)
    finally:
        conn.close()
    # A shared name is thin fare beside a shared idea: only when there is no idea link.
    ideas = [p for p in pairs if p["kind"] == "idea"]
    if not pairs:
        return []
    pool = ideas or pairs
    top, rest = pool[:ROTATE], pool[ROTATE:]
    start = today.toordinal() % len(top)
    # The day's order: the farthest pairs from today's turn on, then everything else.
    # A set whose notes were all in an earlier one is skipped, or "Find another" would
    # show the same three notes again by way of another of their pairs.
    keep = ("a", "b", "kind", "point", "via")
    sets: list[tuple[list[str], list[dict]]] = []
    for first in top[start:] + top[:start] + rest:
        ids, links = _grow(first, pairs)
        if any(set(ids) <= set(shown) for shown, _ in sets):
            continue
        sets.append((ids, [{k: p[k] for k in keep} for p in links]))
    return sets


# The day's sets are chosen once and kept (derived_values, scope `shiny_day`), so the
# card holds still all day: links keep arriving as the related judge works, and a set
# recomputed on every wall refresh changed under the person every few seconds.
def _kept(conn, day: str) -> list | None:
    row = conn.execute(
        "SELECT value FROM derived_values WHERE scope = 'shiny_day' AND subject = ?"
        " AND attribute = 'sets' AND source = 'model'",
        (day,),
    ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["value"])
    except ValueError:
        return None


def _keep(day: str, sets: list) -> None:
    with db.transaction() as conn:
        conn.execute("DELETE FROM derived_values WHERE scope = 'shiny_day'")
        conn.execute(
            "INSERT INTO derived_values"
            " (scope, subject, attribute, value, grounded, source, model_version, created_at)"
            " VALUES ('shiny_day', ?, 'sets', ?, 1, 'model', '', ?)",
            (day, json.dumps(sets), db.now()),
        )


def _live(conn, ids: list[str]) -> set[str]:
    rows = conn.execute(
        f"SELECT a.id FROM artifacts a WHERE a.id IN (SELECT value FROM json_each(?)) AND {_LIVE}",
        (json.dumps(ids),),
    ).fetchall()
    return {r["id"] for r in rows}


def pick(today: date | None = None, n: int = 0) -> dict | None:
    """{"ids", "links", "more"} for today's set, or None when the library has no
    relationship across fields yet (or `n` has gone past the last one). `links` are the
    pairs inside the set, each with its kind, the judge's sentence (`point`) or the
    shared name (`via`). `n` is "Find another": 0 is the day's own set, each next one
    the next pair in the day's order; `more` says whether there is another after it.
    The order is chosen once a day and kept; a note trashed since drops its sets."""
    today = today or datetime.now(timezone.utc).date()
    day = today.isoformat()
    conn = db.get_conn()
    try:
        sets = _kept(conn, day)
    finally:
        conn.close()
    if sets is None:
        sets = [[ids, links] for ids, links in _order(today)]
        # Nothing to show yet is not kept: the first connection of the day shows at once.
        if sets:
            _keep(day, sets)
    conn = db.get_conn()
    try:
        live = _live(conn, [i for ids, _ in sets for i in ids])
    finally:
        conn.close()
    sets = [(ids, links) for ids, links in sets if all(i in live for i in ids)]
    if n < 0 or n >= len(sets):
        return None
    ids, links = sets[n]
    return {"ids": ids, "links": links, "more": n + 1 < len(sets)}


def look_again(today: date | None = None) -> None:
    """Choose today's sets again from the links as they stand now (the card's "Look
    again"): new connections found since the morning get their turn."""
    today = today or datetime.now(timezone.utc).date()
    _keep(today.isoformat(), [[ids, links] for ids, links in _order(today)])


def prepare(day: date | None = None) -> bool:
    """Once a day (backup.start_scheduler's beat): choose the day's sets and have the
    model write the first one's words, so the card is ready when the wall opens. True
    when it did anything."""
    day = day or datetime.now(timezone.utc).date()
    conn = db.get_conn()
    try:
        done = _kept(conn, day.isoformat()) is not None
    finally:
        conn.close()
    if done:
        return False
    return today(day, 0, background=False) is not None


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
        "SELECT value FROM derived_values WHERE scope = 'shiny' AND subject = ?"
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
        if privacy.local_only_ids(ids):
            raise LookupError("a local-only note is read by no model")
        provider = get_provider(role="chat")
        food = provider.complete(
            system=prompts.SHINY,
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
                "DELETE FROM derived_values WHERE scope = 'shiny' AND subject = ?",
                (key[0],),
            )
            conn.execute(
                "INSERT INTO derived_values"
                " (scope, subject, attribute, value, grounded, source, model_version,"
                " created_at) VALUES ('shiny', ?, ?, ?, 1, 'model', ?, ?)",
                (key[0], key[1], value, getattr(provider, "model", ""), db.now()),
            )
    except Exception as exc:  # noqa: BLE001 - the card falls back to the link's own words
        log.info("something shiny not written: %s", exc)
        _failed[key[0]] = day
    finally:
        with _lock:
            _writing.discard(key[0])


def today(day: date | None = None, n: int = 0, background: bool = True) -> dict | None:
    """Today's set (or the `n`th "Find another") with its words, or None. `food` is the
    model's words when written; `writing` says they are on the way; `more` whether
    there is another set after this one. `background=False` writes the words in this
    thread (tests)."""
    day = day or datetime.now(timezone.utc).date()
    chosen = pick(day, n)
    if chosen is None:
        return None
    ids = chosen["ids"]
    _remember("shiny_shown", [_pair(ids)], day.isoformat())
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
    return {
        "ids": ids,
        "links": chosen["links"],
        "food": food,
        "writing": writing,
        "more": chosen["more"],
        "n": n,
    }


# ---- The raven's hunt: a fresh connection on demand ----------------------------------


def _pair(ids: list[str]) -> str:
    return "|".join(sorted(ids))


def _remember(scope: str, subjects: list[str], day: str) -> None:
    """Note that these pairs were shown (or seeds used) on `day`; a later day moves it."""
    with db.transaction() as conn:
        for subject in subjects:
            conn.execute(
                "INSERT INTO derived_values (scope, subject, attribute, value, grounded,"
                " source, model_version, created_at) VALUES (?, ?, '', ?, 1, 'memory', '', ?)"
                " ON CONFLICT (scope, subject, attribute, source) DO UPDATE"
                " SET value = excluded.value, created_at = excluded.created_at"
                " WHERE value < excluded.value",
                (scope, subject, day, db.now()),
            )


def _recent(conn, scope: str, days: int, today: date) -> set[str]:
    since = (today - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT subject FROM derived_values WHERE scope = ? AND source = 'memory' AND value > ?",
        (scope, since),
    ).fetchall()
    return {r["subject"] for r in rows}


def _seeds(conn, rng: random.Random, today: date) -> list[str]:
    """Notes to hunt from: with idea lines, not local-only, not used lately. Each seed is
    drawn from a pool picked at random (new notes, old ones, anything), so a press can
    land anywhere in the library."""
    rows = conn.execute(
        "SELECT a.id, a.created_at, a.updated_at FROM artifacts a"
        f" WHERE {_LIVE} AND a.local_only = 0 AND EXISTS (SELECT 1 FROM facets f"
        " WHERE f.artifact_id = a.id AND f.level IN (?, ?))",
        IDEA_LEVELS,
    ).fetchall()
    resting = _recent(conn, "shiny_seed", SEED_REST_DAYS, today)
    rows = [r for r in rows if r["id"] not in resting]
    old = (today - timedelta(days=60)).isoformat()
    pools = [
        [r["id"] for r in sorted(rows, key=lambda r: r["created_at"], reverse=True)[:25]],
        [r["id"] for r in rows if (r["updated_at"] or "") < old],
        [r["id"] for r in rows],
    ]
    seeds: list[str] = []
    while len(seeds) < HUNT_SEEDS:
        pool = [i for i in rng.choice([p for p in pools if p] or [[]]) if i not in seeds]
        if not pool:
            pool = [i for i in pools[2] if i not in seeds]
            if not pool:
                break
        seeds.append(rng.choice(pool))
    return seeds


def _candidates(conn, seed: str) -> list[dict]:
    """Notes whose idea lines come close to the seed's while their subject is not the
    seed's, the farthest first: {id, score, distance, mine, theirs}."""
    from .index.store import get_store
    from .ingest.related import RELATED_MIN, SUBJECT_LEVEL
    from .retrieve.candidates import hit_is_stale

    store = get_store()
    lines = conn.execute(
        "SELECT level, statement FROM facets WHERE artifact_id = ? AND level IN (?, ?, ?)",
        (seed, SUBJECT_LEVEL, *IDEA_LEVELS),
    ).fetchall()
    near: dict[str, float] = {}
    best: dict[str, tuple[float, str, str]] = {}
    cache: dict = {}
    for line in lines:
        subject = line["level"] == SUBJECT_LEVEL
        for hit in store.search_dense(store.FACETS, line["statement"], limit=60, as_query=False):
            other = hit["artifact_id"]
            if other == seed:
                continue
            if subject:
                if hit["level"] == SUBJECT_LEVEL:
                    near[other] = max(near.get(other, 0.0), hit["score"])
                continue
            if hit["level"] not in IDEA_LEVELS or hit["score"] < HUNT_MIN:
                continue
            if hit_is_stale(conn, hit, cache):
                continue
            if other not in best or hit["score"] > best[other][0]:
                best[other] = (hit["score"], line["statement"], hit["facet_id"])
    if not best:
        return []
    live = _live(conn, list(best))
    local = {
        r["id"]
        for r in conn.execute(
            "SELECT id FROM artifacts WHERE local_only = 1 AND id IN (SELECT value FROM json_each(?))",
            (json.dumps(list(best)),),
        )
    }
    floor = min(near.values(), default=0.0)
    found = []
    for other, (score, mine, facet_id) in best.items():
        if other not in live or other in local or near.get(other, 0.0) >= RELATED_MIN:
            continue
        theirs = conn.execute("SELECT statement FROM facets WHERE id = ?", (facet_id,)).fetchone()
        found.append(
            {
                "id": other,
                "score": score,
                "distance": round(max(0.0, 1.0 - near.get(other, floor)), 4),
                "mine": mine,
                "theirs": theirs["statement"] if theirs else "",
            }
        )
    found.sort(key=lambda c: (-c["distance"], -c["score"]))
    return found[:HUNT_CANDIDATES]


class _Find(BaseModel):
    keep: str = ""
    idea: str = ""
    parts: list[dict] = []
    question: str = ""


def hunt(today: date | None = None, rng: random.Random | None = None) -> dict:
    """A fresh set for the raven: {"ids", "links", "food"}, or {"none": why} with why
    "nothing" (no connection passed), "paused" (the model service is on a break) or
    "model" (the call failed). At most HUNT_SEEDS model calls."""
    from .providers import pause
    from .providers.base import get_provider

    today = today or datetime.now(timezone.utc).date()
    day = today.isoformat()
    if pause.active():
        return {"none": "paused"}
    rng = rng or random.Random()
    conn = db.get_conn()
    try:
        shown = _recent(conn, "shiny_shown", REMEMBER_DAYS, today)
        seeds = _seeds(conn, rng, today)
    finally:
        conn.close()
    for seed in seeds:
        _remember("shiny_seed", [seed], day)
        conn = db.get_conn()
        try:
            found = [c for c in _candidates(conn, seed) if _pair([seed, c["id"]]) not in shown]
            faces = _faces(conn, [seed, *(c["id"] for c in found)])
        finally:
            conn.close()
        if not found:
            continue

        def block(i: str) -> str:
            face = faces.get(i) or {"kind": "item", "title": None, "lines": []}
            return f"id: {i}\n[{face['kind']}] {face['title'] or '(untitled)'}\n" + "\n".join(
                f"- {line}" for line in face["lines"][:6]
            )

        try:
            answer = get_provider(role="chat").complete(
                system=prompts.SHINY_HUNT,
                user="The note:\n"
                + block(seed)
                + "\n\nCandidates:\n\n"
                + "\n\n".join(block(c["id"]) for c in found),
                response_model=_Find,
            )
        except Exception as exc:  # noqa: BLE001 - the raven says it could not look
            log.info("the raven's hunt failed: %s", exc)
            return {"none": "paused" if pause.active() else "model"}
        chosen = next((c for c in found if c["id"] == answer.keep), None)
        if chosen is None:
            continue
        ids = [seed, chosen["id"]]
        try:
            food = _Food(idea=answer.idea, parts=answer.parts, question=answer.question)
        except ValueError:
            continue
        parts = {p.id: p.how for p in food.parts if p.id in ids}
        if set(parts) != set(ids):
            continue
        _remember("shiny_shown", [_pair(ids)], day)
        link = {"a": ids[0], "b": ids[1], "kind": "idea", "distance": chosen["distance"]}
        link |= {"point": food.idea, "via": None}
        words = {"idea": food.idea, "parts": parts, "question": food.question}
        return {"ids": ids, "links": [link], "food": words}
    return {"none": "nothing"}
