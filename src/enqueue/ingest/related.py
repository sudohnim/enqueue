"""Related artifacts: other notes about the same thing, or naming the same thing.

Subject links: each of an artifact's SUBJECT lines (facet level 1, "what it is about")
searches the facet index, and another artifact's closeness is its best subject line's
similarity to any of them. Only subject lines count, on both sides. The higher levels
are written to leave the subject behind, and the "bridge" lines restate a mechanism in
another field's words on purpose (a piano essay gets a line about codebases) so a search
in that field finds it; matching on those linked a data-modeling note to an essay on
piano practice and a tax letter, each explained by a sentence about codebases. Level 0
says what kind of thing it is, which links every set of reading notes to every other.
Mention links: another artifact whose entities name the same person, place or thing
(case-insensitive), scored MENTION_SCORE and carrying the name in `via`; a name that
more than MENTION_MAX_SHARED artifacts mention is too common to connect anything, and
a link's own site ("Medium" on an article saved from medium.com) says where it was
published, not what it is about, so that name never connects it to anything.
The top RELATED_LIMIT at or above RELATED_MIN become links, stored in both directions
(a newer note links back to the older one). Stale facets and entities never count,
and readers only show links to live artifacts. Local and cheap: no model call.

A subject link also keeps its `point`: the related artifact's subject line that matched,
which is what a reader is shown as the reason.

Idea links are the cross-field ones (a book on strategy beside one on statecraft, both
saying incentives beat character), and similarity alone cannot find them honestly: two
abstract sentences score alike for sharing a shape ("X beats Y") as readily as an idea.
So similarity between the lines above the subject level only PROPOSES pairs
(IDEA_MIN, the closest IDEA_CANDIDATES), and the ingest model judges each: the same
point, or not. Only a yes becomes a link, and its `point` is the model's one plain
sentence. A pair nobody has judged yet is not a link: this fails closed, unlike search's
gray-zone judge, because a missing link costs nothing and an invented one misleads.
Verdicts are cached per pair, model and the two items' subject lines
(`derived_values`, scope `related_judge`).

Judging has its own small worker (`start_judge`, one daemon thread) and nothing else
calls the model here. `compute()` uses cached verdicts only and marks an artifact with
unjudged pairs pending (the `related_pending` table); the worker takes pending
artifacts one at a time (`judge_next`), each one model call, and stops for the day at
`JUDGE_DAILY` calls so a library-wide pass cannot spend a provider's allowance (the
first version had no ceiling, sent every note back through the whole ingest pipeline
to make one call, and ran a weekly usage limit dry). A usage limit or outage leaves
the artifact pending and the worker waits it out. A pair with a local-only item is
judged by the local model only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone

from pydantic import BaseModel, field_validator

from .. import db, prompts

log = logging.getLogger(__name__)

RELATED_LIMIT = 5
# Subject-to-subject cosine, set for precision: a missing link costs nothing, a made-up
# one costs trust. Measured on a 141-summary library, pairs at 0.66+ are nearly all
# real, 0.63-0.66 mostly real, and under 0.63 mostly chance (a food list beside a trip).
RELATED_MIN = 0.66
MENTION_SCORE = 0.7
MENTION_MAX_SHARED = 8
SUBJECT_LEVEL = 1
# Hits come back across every level and are filtered to subject lines here, so ask for
# enough that the subject lines among them are not crowded out.
_PER_STATEMENT = 80
# Idea links: similarity between lines above the subject level that makes a pair worth
# asking the model about, and how many pairs one artifact asks about (one model call).
IDEA_MIN = 0.72
IDEA_CANDIDATES = 8
# Bump when the way links are chosen changes: every artifact is recomputed once.
VERSION = "6"
# The most model calls the judge makes in a day (UTC). Each call judges one artifact's
# candidates. 0 turns the judge off: cached verdicts still link, nothing new is asked.
JUDGE_DAILY = int(os.getenv("ENQ_RELATED_JUDGE_DAILY", "40"))


class JudgeOwed(RuntimeError):
    """The judge could not be asked for a reason that will pass (a usage limit, an
    outage). Every link that needs no judge was written; the artifact stays pending."""


class _Verdict(BaseModel):
    id: str
    same: bool
    why: str = ""

    @field_validator("why")
    @classmethod
    def _one_plain_sentence(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) > 220:
            raise ValueError("why must be one sentence of at most 22 words")
        return value


class _Verdicts(BaseModel):
    verdicts: list[_Verdict]


def compute(artifact_id: str, judge: bool = False) -> int:
    """Recompute one artifact's links. Returns how many were written.

    No model is called: idea candidates link only on a cached verdict, and an artifact
    with unjudged ones is marked pending for the judge worker. `judge=True` is the
    worker's own call: it puts the unjudged candidates to the ingest model (one call)
    and raises `JudgeOwed`, after writing what it could, when the model is unavailable
    for now.
    """
    from ..index.store import get_store
    from ..providers.base import is_transient, model_for
    from ..retrieve.candidates import hit_is_stale

    store = get_store()
    conn = db.get_conn()
    try:
        mine = conn.execute(
            "SELECT id, level, statement FROM facets WHERE artifact_id = ? AND level >= ?",
            (artifact_id, SUBJECT_LEVEL),
        ).fetchall()
        # other artifact -> (similarity, this artifact's line, the other's facet id)
        best: dict[str, tuple[float, str, str]] = {}
        ideas: dict[str, tuple[float, str, str]] = {}
        cache: dict = {}
        for facet in mine:
            subject = facet["level"] == SUBJECT_LEVEL
            for hit in store.search_dense(
                store.FACETS, facet["statement"], limit=_PER_STATEMENT, as_query=False
            ):
                other = hit["artifact_id"]
                # A subject line only meets subject lines, an idea line only idea lines.
                if other == artifact_id or (hit["level"] == SUBJECT_LEVEL) != subject:
                    continue
                if hit["level"] < SUBJECT_LEVEL:
                    continue
                if hit["score"] < (RELATED_MIN if subject else IDEA_MIN):
                    continue
                if hit_is_stale(conn, hit, cache):
                    continue
                into = best if subject else ideas
                if other not in into or hit["score"] > into[other][0]:
                    into[other] = (hit["score"], facet["statement"], hit["facet_id"])
        via = _mentions(conn, artifact_id, cache)

        # Idea candidates: the closest pairs not already linked by subject.
        asked = sorted(
            ((other, found) for other, found in ideas.items() if other not in best),
            key=lambda kv: kv[1][0],
            reverse=True,
        )[:IDEA_CANDIDATES]
        lines = _statements(conn, [found[2] for _, found in asked])
        candidates = [
            {"id": other, "score": found[0], "mine": found[1], "theirs": lines[found[2]]}
            for other, found in asked
            if found[2] in lines
        ]
        keys = _pair_keys(conn, artifact_id, [c["id"] for c in candidates])
        model = model_for("ingest")
        why: dict[str, str] = {}
        missing = []
        for c in candidates:
            verdict = _verdict_read(conn, keys[c["id"]], model)
            if verdict is None:
                missing.append(c)
            elif verdict:
                why[c["id"]] = verdict
        owed: Exception | None = None
        if missing and judge:
            try:
                for other, reason in _judge(conn, artifact_id, missing, keys, model).items():
                    if reason:
                        why[other] = reason
                missing = []
            except Exception as exc:  # noqa: BLE001 - a link nobody judged is not a link
                if is_transient(exc):
                    owed = exc
                else:
                    log.warning("related judge failed for %s: %s", artifact_id, exc)
                    missing = []  # would fail the same way again; asked anew on a change

        scores = {other: found[0] for other, found in best.items()}
        scores.update({c["id"]: c["score"] for c in candidates if c["id"] in why})
        for other in via:
            scores.setdefault(other, MENTION_SCORE)
        top = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:RELATED_LIMIT]
        theirs = _statements(conn, [best[other][2] for other, _ in top if other in best])

        now = db.now()
        conn.execute(
            "DELETE FROM related WHERE artifact_id = ? OR related_id = ?",
            (artifact_id, artifact_id),
        )
        for other, score in top:
            found = best.get(other)
            if found:
                # Each direction names the line of the artifact it points AT.
                points = (theirs.get(found[2]), found[1])
            else:
                points = (why.get(other), why.get(other))  # the judge's sentence, or None
            for (a, b), point in zip(((artifact_id, other), (other, artifact_id)), points):
                conn.execute(
                    "INSERT OR REPLACE INTO related"
                    " (artifact_id, related_id, score, model_version, created_at, via, point)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (a, b, round(score, 4), model, now, via.get(other), point),
                )
        _set_pending(conn, artifact_id, bool(missing))
        conn.commit()
        if missing and not judge:
            kick()
        if owed is not None:
            raise JudgeOwed(f"{type(owed).__name__}: {owed}"[:300]) from owed
        return len(top)
    finally:
        conn.close()


def _pair_keys(conn, artifact_id: str, others: list[str]) -> dict[str, tuple[str, str]]:
    """Per other artifact, the cache key of its pair with this one: the two ids in
    order, and a stamp of both items' subject lines, so a verdict is asked again once
    either item is about something else."""
    ids = [artifact_id, *others]
    about: dict[str, list[str]] = {i: [] for i in ids}
    for r in conn.execute(
        "SELECT artifact_id, statement FROM facets WHERE level <= ?"
        " AND artifact_id IN (SELECT value FROM json_each(?)) ORDER BY level, statement",
        (SUBJECT_LEVEL, json.dumps(ids)),
    ):
        about[r["artifact_id"]].append(r["statement"])
    out = {}
    for other in others:
        a, b = sorted((artifact_id, other))
        stamp = hashlib.sha256(json.dumps([about[a], about[b]]).encode()).hexdigest()[:16]
        out[other] = (f"{a}|{b}", stamp)
    return out


def _verdict_read(conn, key: tuple[str, str], model: str) -> str | None:
    """A cached verdict: the judge's sentence for a yes, "" for a no, None when this
    pair has not been judged by this model as the two items now stand."""
    row = conn.execute(
        "SELECT value FROM derived_values WHERE scope = 'related_judge' AND subject = ?"
        " AND attribute = ? AND source = 'model' AND model_version = ?",
        (key[0], key[1], model),
    ).fetchone()
    return None if row is None else row["value"]


def _verdict_write(conn, key: tuple[str, str], model: str, why: str) -> None:
    conn.execute(
        "DELETE FROM derived_values WHERE scope = 'related_judge' AND subject = ?", (key[0],)
    )
    conn.execute(
        "INSERT INTO derived_values"
        " (scope, subject, attribute, value, grounded, source, model_version, created_at)"
        " VALUES ('related_judge', ?, ?, ?, 1, 'model', ?, ?)",
        (key[0], key[1], why, model, db.now()),
    )


def _set_pending(conn, artifact_id: str, pending: bool) -> None:
    if pending:
        conn.execute(
            "INSERT OR IGNORE INTO related_pending (artifact_id, since) VALUES (?, ?)",
            (artifact_id, db.now()),
        )
    else:
        conn.execute("DELETE FROM related_pending WHERE artifact_id = ?", (artifact_id,))


def pending_ids() -> list[str]:
    """Live artifacts with idea candidates nobody has judged yet, longest waiting first."""
    conn = db.get_conn()
    try:
        return [
            r["artifact_id"]
            for r in conn.execute(
                "SELECT p.artifact_id FROM related_pending p JOIN artifacts a"
                " ON a.id = p.artifact_id WHERE a.deleted_at IS NULL"
                " AND a.vaulted_at IS NULL AND a.embedded_at IS NULL ORDER BY p.since"
            )
        ]
    finally:
        conn.close()


def is_pending(artifact_id: str) -> bool:
    conn = db.get_conn()
    try:
        return bool(
            conn.execute(
                "SELECT 1 FROM related_pending WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        )
    finally:
        conn.close()


def _state_get(key: str) -> str | None:
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT value FROM related_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None
    finally:
        conn.close()


def _state_set(key: str, value: str) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO related_state (key, value) VALUES (?, ?)", (key, value)
        )


# ---- the judge worker ---------------------------------------------------------------


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def judged_today() -> int:
    """Model calls the judge has made today (UTC)."""
    day, _, count = (_state_get("judge_day") or "").partition(":")
    return int(count or 0) if day == _today() else 0


def judge_next() -> str:
    """Judge the longest-waiting pending artifact. One model call at most.

    Returns what happened, which is what the worker paces itself by:
    "idle" (nothing pending), "budget" (today's calls are spent, or the judge is off),
    "paused" (a usage limit is in effect), "owed" (the model could not be reached),
    "judged".
    """
    from ..providers import pause

    waiting = pending_ids()
    if not waiting:
        return "idle"
    if judged_today() >= JUDGE_DAILY:
        return "budget"
    if pause.active():
        return "paused"
    # Counted before the call: a call that fails still spent a request.
    _state_set("judge_day", f"{_today()}:{judged_today() + 1}")
    try:
        compute(waiting[0], judge=True)
    except JudgeOwed:
        return "owed"
    return "judged"


_wake = threading.Event()
_judge_thread: threading.Thread | None = None
# How long the worker waits after each outcome before looking again. A kick (a new
# pending artifact) ends an idle wait early; nothing ends the others early.
_WAITS = {"idle": 3600.0, "budget": 1800.0, "paused": 300.0, "owed": 600.0, "judged": 2.0}


def kick() -> None:
    """Tell the judge worker there may be something new to judge."""
    _wake.set()


def _judge_loop() -> None:
    while True:
        try:
            outcome = judge_next()
        except Exception:  # noqa: BLE001 - the worker must outlive one bad artifact
            log.exception("related judge worker")
            outcome = "owed"
        if outcome == "idle":
            _wake.clear()
            # Pending may have been marked between the look and the clear.
            if not pending_ids():
                _wake.wait(_WAITS["idle"])
        else:
            threading.Event().wait(_WAITS[outcome])


def start_judge() -> None:
    """Start the judge worker (once). Called at engine startup."""
    global _judge_thread
    if _judge_thread is None or not _judge_thread.is_alive():
        _judge_thread = threading.Thread(target=_judge_loop, name="related-judge", daemon=True)
        _judge_thread.start()


def _judge(
    conn, artifact_id: str, candidates: list[dict], keys: dict, model: str
) -> dict[str, str]:
    """Ask the ingest model about each candidate; cache and return {other id: the
    sentence for a yes, "" for a no}. A candidate the answer does not cover stays
    unjudged (absent). A pair with a local-only item only ever goes to the local model."""
    from .. import privacy
    from ..providers.base import get_provider

    ids = [artifact_id, *(c["id"] for c in candidates)]
    faces = {
        r["id"]: r
        for r in conn.execute(
            "SELECT id, title, kind FROM artifacts WHERE id IN (SELECT value FROM json_each(?))",
            (json.dumps(ids),),
        )
    }
    about: dict[str, list[str]] = {i: [] for i in ids}
    for r in conn.execute(
        "SELECT artifact_id, statement FROM facets WHERE level = ?"
        " AND artifact_id IN (SELECT value FROM json_each(?))",
        (SUBJECT_LEVEL, json.dumps(ids)),
    ):
        about[r["artifact_id"]].append(r["statement"])

    def face(aid: str) -> str:
        row = faces.get(aid)
        title = (row["title"] if row else None) or "(untitled)"
        return f"[{row['kind'] if row else 'item'}] {title}\nabout: " + " ".join(about[aid][:2])

    private = privacy.local_only_ids(ids)
    out: dict[str, str] = {}
    for local in (False, True):
        batch = [c for c in candidates if (artifact_id in private or c["id"] in private) == local]
        if not batch:
            continue
        provider = get_provider(local_only=local, role="ingest")
        blocks = [
            f"candidate id: {c['id']}\n{face(c['id'])}\n"
            f"line from the item: {c['mine']}\nline from this candidate: {c['theirs']}"
            for c in batch
        ]
        result = provider.complete(
            system=prompts.RELATED_JUDGE,
            user=f"The item:\n{face(artifact_id)}\n\nCandidates:\n\n" + "\n\n".join(blocks),
            response_model=_Verdicts,
        )
        asked = {c["id"] for c in batch}
        for verdict in result.verdicts if result is not None else []:
            if verdict.id not in asked or verdict.id in out:
                continue  # not in the batch: ignore, never cache
            reason = verdict.why if verdict.same and verdict.why else ""
            out[verdict.id] = reason
            # Stamped with the ingest model even when the local one answered (a private
            # pair): that is the name the verdict is read back by.
            _verdict_write(conn, keys[verdict.id], model, reason)
        conn.commit()  # never hold the write lock across the next model call
    return out


def _statements(conn, facet_ids: list[str]) -> dict[str, str]:
    """Facet id -> its statement, for the lines an idea link matched."""
    if not facet_ids:
        return {}
    rows = conn.execute(
        "SELECT id, statement FROM facets WHERE id IN (SELECT value FROM json_each(?))",
        (json.dumps(facet_ids),),
    ).fetchall()
    return {r["id"]: r["statement"] for r in rows}


def refresh_if_outdated() -> int:
    """Recompute every artifact's links once after the way they are chosen changed
    (`VERSION`), so old links do not linger beside new ones. No model is called;
    artifacts left with unjudged pairs wait for the judge worker. Returns how many
    artifacts were recomputed."""
    if _state_get("version") == VERSION:
        return 0
    conn = db.get_conn()
    try:
        ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM artifacts WHERE deleted_at IS NULL AND vaulted_at IS NULL"
                " AND embedded_at IS NULL AND (id IN (SELECT artifact_id FROM facets)"
                " OR id IN (SELECT artifact_id FROM related))"
            )
        ]
    finally:
        conn.close()
    for artifact_id in ids:
        compute(artifact_id)
    _state_set("version", VERSION)
    kick()
    return len(ids)


def _own_sites(conn, artifact_ids: list[str]) -> dict[str, set[str]]:
    """For each link among these artifacts, the lower-cased names of the site it was
    saved from: what its preview calls itself, and the main word of its address
    ("medium" from medium.com), since a site that refuses the preview fetch never
    reports a name. An article names its own site without being about it."""
    from urllib.parse import urlsplit

    out: dict[str, set[str]] = {}
    rows = conn.execute(
        "SELECT a.id, a.source_url, p.site_name FROM artifacts a"
        " LEFT JOIN link_previews p ON p.artifact_id = a.id"
        " WHERE a.id IN (SELECT value FROM json_each(?))",
        (json.dumps(artifact_ids),),
    )
    for r in rows:
        sites = out.setdefault(r["id"], set())
        if r["site_name"]:
            sites.add(r["site_name"].strip().lower())
        labels = (urlsplit(r["source_url"] or "").hostname or "").lower().split(".")
        if len(labels) >= 2:
            sites.add(labels[-2])
    return out


def _mentions(conn, artifact_id: str, cache: dict) -> dict[str, str]:
    """Other live artifacts whose current entities share a name with this one's, mapped
    to the shared name (the rarest one, when several are shared)."""
    from ..retrieve.candidates import hit_is_stale

    mine = [
        dict(r)
        for r in conn.execute(
            "SELECT artifact_id, entity, model_version, body_version FROM entities"
            " WHERE artifact_id = ?",
            (artifact_id,),
        )
    ]
    names = {
        e["entity"].strip().lower(): e["entity"] for e in mine if not hit_is_stale(conn, e, cache)
    }
    for site in _own_sites(conn, [artifact_id]).get(artifact_id, ()):
        names.pop(site, None)
    if not names:
        return {}
    rows = conn.execute(
        "SELECT e.artifact_id, lower(trim(e.entity)) AS name, e.model_version, e.body_version"
        " FROM entities e JOIN artifacts a ON a.id = e.artifact_id"
        " WHERE lower(trim(e.entity)) IN (SELECT value FROM json_each(?))"
        " AND e.artifact_id != ?"
        " AND a.deleted_at IS NULL AND a.vaulted_at IS NULL AND a.embedded_at IS NULL",
        (json.dumps(sorted(names)), artifact_id),
    ).fetchall()
    own = _own_sites(conn, sorted({r["artifact_id"] for r in rows}))
    sharers: dict[str, set[str]] = {}
    for r in rows:
        if r["name"] in own.get(r["artifact_id"], ()):
            continue
        if not hit_is_stale(conn, dict(r), cache):
            sharers.setdefault(r["name"], set()).add(r["artifact_id"])
    out: dict[str, str] = {}
    for name, others in sorted(sharers.items(), key=lambda kv: len(kv[1]), reverse=True):
        if len(others) + 1 > MENTION_MAX_SHARED:
            continue
        for other in others:
            out[other] = names[name]  # rarest name last, so it wins
    return out


def for_artifact(conn, artifact_id: str) -> list[dict]:
    """Live related artifacts, closest first, each with `point` (its summary line that
    matched) and `via` (a shared name); either may be None, never both."""
    rows = conn.execute(
        "SELECT a.id, a.title, a.kind, r.score, r.via, r.point FROM related r JOIN artifacts a"
        " ON a.id = r.related_id WHERE r.artifact_id = ?"
        " AND a.deleted_at IS NULL AND a.vaulted_at IS NULL AND a.embedded_at IS NULL"
        " ORDER BY r.score DESC LIMIT ?",
        (artifact_id, RELATED_LIMIT),
    ).fetchall()
    return [dict(r) for r in rows]
