"""A note's drafts: how many are kept, what each one changed, and going back to one.

A draft is a row of `artifact_versions`. While a note is being written, the newest
draft follows the writing and a new one is left standing every few minutes
(`notes._append_version`, config.DRAFT_EVERY_S). This module decides what is kept
after that, lists the drafts with what each changed, and restores one.

What is kept follows the library's policy (the `drafts_keep` setting):

- `thinned` (the default): close together while recent, further apart as they age,
  the ladder backups use. Every draft from the last day; the latest of each hour for
  a week; the latest of each day for three months; the latest of each week after.
- `30d`: every draft from the last 30 days, nothing older.
- `off`: none but the latest.

Whatever the policy, a note keeps its latest draft (it is the note's body version,
what summaries and search are stamped with) and, unless drafts are off, its first,
so how it began is never lost. A note whose own switch is off (`keep_drafts = 0`)
keeps only its latest.
"""

from __future__ import annotations

import difflib
import re
from datetime import datetime, timedelta, timezone

from . import db, settings

POLICIES = ("thinned", "30d", "off")
DEFAULT_POLICY = "thinned"

# The thinned ladder: (younger than, keep the latest per bucket of this size).
LADDER = (
    (timedelta(days=1), None),  # everything
    (timedelta(days=7), "hour"),
    (timedelta(days=90), "day"),
    (None, "week"),
)


def policy() -> str:
    value = str(settings.get("drafts_keep") or DEFAULT_POLICY)
    return value if value in POLICIES else DEFAULT_POLICY


def _when(stamp: str) -> datetime:
    try:
        when = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _bucket(when: datetime, size: str) -> tuple:
    if size == "hour":
        return (when.year, when.month, when.day, when.hour)
    if size == "day":
        return (when.year, when.month, when.day)
    iso = when.isocalendar()
    return (iso[0], iso[1])


def keep(drafts: list[tuple[str, str]], rule: str, now: datetime, keep_all: bool = True) -> set:
    """The ids to keep of one note's drafts, given as (id, created_at). Pure."""
    if not drafts:
        return set()
    ordered = sorted(drafts, key=lambda d: (d[1], d[0]))
    latest = ordered[-1][0]
    if rule == "off" or not keep_all:
        return {latest}
    kept = {latest, ordered[0][0]}
    if rule == "30d":
        cutoff = now - timedelta(days=30)
        return kept | {i for i, at in ordered if _when(at) >= cutoff}
    seen: set = set()
    for draft_id, at in reversed(ordered):  # newest first: the first seen per bucket wins
        when = _when(at)
        age = now - when
        for younger_than, size in LADDER:
            if younger_than is None or age < younger_than:
                if size is None:
                    kept.add(draft_id)
                else:
                    key = (size, _bucket(when, size))
                    if key not in seen:
                        seen.add(key)
                        kept.add(draft_id)
                break
    return kept


def thin(artifact_id: str | None = None, now: datetime | None = None) -> int:
    """Remove the drafts the policy no longer keeps, for one note or every note.
    Returns how many were removed."""
    now = now or datetime.now(timezone.utc)
    rule = policy()
    removed = 0
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT v.id, v.artifact_id, v.created_at, a.keep_drafts FROM artifact_versions v"
            " JOIN artifacts a ON a.id = v.artifact_id"
            + (" WHERE v.artifact_id = ?" if artifact_id else ""),
            (artifact_id,) if artifact_id else (),
        ).fetchall()
        by_note: dict[str, list] = {}
        flags: dict[str, bool] = {}
        for r in rows:
            by_note.setdefault(r["artifact_id"], []).append((r["id"], r["created_at"]))
            flags[r["artifact_id"]] = bool(r["keep_drafts"])
        for note, drafts in by_note.items():
            kept = keep(drafts, rule, now, keep_all=flags[note])
            gone = [(d,) for d, _ in drafts if d not in kept]
            if gone:
                conn.executemany("DELETE FROM artifact_versions WHERE id = ?", gone)
                removed += len(gone)
    return removed


def stats() -> dict:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n, COUNT(DISTINCT artifact_id) AS notes,"
            " COALESCE(SUM(LENGTH(body)), 0) AS bytes FROM artifact_versions"
        ).fetchone()
    finally:
        conn.close()
    return {"policy": policy(), "drafts": row["n"], "notes": row["notes"], "bytes": row["bytes"]}


# ---- what each draft changed -----------------------------------------------------

_WORD = re.compile(r"\S+")


def _changed(before: str, after: str) -> dict:
    """Words added and removed going from `before` to `after`, and the first few words
    of the change, for a draft's row in the list."""
    a = _WORD.findall(before or "")
    b = _WORD.findall(after or "")
    added = removed = 0
    first = ""
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        added += j2 - j1
        removed += i2 - i1
        if not first:
            words = (b[j1:j2] or a[i1:i2])[:8]
            # A trailing dash or bullet carried over from the next line says nothing.
            while words and not any(ch.isalnum() for ch in words[-1]):
                words.pop()
            first = " ".join(words)
    return {"added": added, "removed": removed, "first": first}


def _open_for(row, body: str | None) -> str:
    """A vaulted note's drafts are sealed; open them while the vault is."""
    if not row["vaulted_at"]:
        return body or ""
    from . import vault, vaultops

    if not vault.is_unlocked():
        raise PermissionError("Unlock the vault to see this note's drafts.")
    return vaultops._open(vault.key(), body) or ""


def listing(artifact_id: str) -> dict:
    """A note's drafts, newest first, each with what it changed from the one before."""
    conn = db.get_conn()
    try:
        note = conn.execute(
            "SELECT kind, body, vaulted_at, keep_drafts FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        if note is None or note["kind"] != "note":
            raise KeyError(artifact_id)
        rows = conn.execute(
            "SELECT id, body, created_at FROM artifact_versions WHERE artifact_id = ?"
            " ORDER BY created_at, id",
            (artifact_id,),
        ).fetchall()
    finally:
        conn.close()
    out = []
    before = ""
    for r in rows:
        body = _open_for(note, r["body"])
        out.append({"id": r["id"], "at": r["created_at"], **_changed(before, body)})
        before = body
    out.reverse()
    current = _open_for(note, note["body"])
    # The newest draft holds the note as it is now; the list says "Now" for it.
    if out:
        out[0]["current"] = before == current
    return {
        "drafts": out,
        "keep": bool(note["keep_drafts"]),
        "policy": policy(),
    }


def body(artifact_id: str, version_id: str) -> str:
    conn = db.get_conn()
    try:
        note = conn.execute(
            "SELECT vaulted_at FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        row = conn.execute(
            "SELECT body FROM artifact_versions WHERE id = ? AND artifact_id = ?",
            (version_id, artifact_id),
        ).fetchone()
    finally:
        conn.close()
    if note is None or row is None:
        raise KeyError(version_id)
    return _open_for(note, row["body"])


def restore(artifact_id: str, version_id: str) -> dict:
    """Put a draft back as the note's text. Today's text is kept as a draft of its own
    first, so restoring can never lose anything."""
    from . import notes

    text = body(artifact_id, version_id)
    return notes.edit(artifact_id, text, keep_current=True)


def set_keep(artifact_id: str, on: bool) -> dict:
    """Switch a note's drafts on or off. Off keeps only the latest (its body version)."""
    with db.transaction() as conn:
        row = conn.execute("SELECT kind FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if row is None or row["kind"] != "note":
            raise KeyError(artifact_id)
        conn.execute("UPDATE artifacts SET keep_drafts = ? WHERE id = ?", (int(on), artifact_id))
    removed = 0 if on else thin(artifact_id)
    return {"keep": on, "removed": removed}
