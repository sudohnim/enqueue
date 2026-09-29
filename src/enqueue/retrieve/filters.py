"""Filters in the words of a search: "that pdf from last month about kilns".

People type what kind of thing they saved and roughly when, next to what it is about.
Embedded as text, "pdf" and "last month" only blur the query; read as filters they
narrow it exactly. `parse` pulls out an unambiguous kind word and a time phrase, and
returns the rest as the text to search. Plain rules, no model call: a search stays
instant, and the same words always mean the same filter.

"note" is deliberately not a kind word: "my notes on X" almost never means "only
notes, not the PDF". Dates are when a thing was saved (`created_at`).
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

KINDS = {
    "pdf": "pdf",
    "pdfs": "pdf",
    "link": "link",
    "links": "link",
    "article": "link",
    "articles": "link",
    "image": "image",
    "images": "image",
    "photo": "image",
    "photos": "image",
    "picture": "image",
    "pictures": "image",
    "screenshot": "image",
    "screenshots": "image",
}

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS.pop("may", None)  # "may" is far more often the verb; "in may" is handled below

_UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}
_LEAD = r"(?:(?:that\s+|which\s+)?(?:i\s+)?(?:saved\s+|added\s+|captured\s+)?(?:from|in|during|since|over)\s+)?"


@dataclass
class Filters:
    kinds: set[str]
    since: str | None = None  # ISO, inclusive
    until: str | None = None  # ISO, exclusive
    label: str = ""  # what was understood, for the results header

    def __bool__(self) -> bool:
        return bool(self.kinds or self.since or self.until)


def _start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc)
    return start, end


def _time(text: str, now: datetime) -> tuple[str, datetime | None, datetime | None, str]:
    """(text without the phrase, since, until, label) for the first time phrase found."""
    today = _start_of_day(now)
    week_start = today - timedelta(days=today.weekday())
    rules = [
        (r"today", lambda m: (today, None, "today")),
        (r"yesterday", lambda m: (today - timedelta(days=1), today, "yesterday")),
        (r"this\s+week", lambda m: (week_start, None, "this week")),
        (r"last\s+week", lambda m: (week_start - timedelta(days=7), week_start, "last week")),
        (
            r"this\s+month",
            lambda m: (today.replace(day=1), None, "this month"),
        ),
        (
            r"last\s+month",
            lambda m: (
                *_month_bounds(now.year - (now.month == 1), (now.month - 2) % 12 + 1),
                "last month",
            ),
        ),
        (r"this\s+year", lambda m: (today.replace(month=1, day=1), None, "this year")),
        (
            r"last\s+year",
            lambda m: (
                datetime(now.year - 1, 1, 1, tzinfo=timezone.utc),
                datetime(now.year, 1, 1, tzinfo=timezone.utc),
                "last year",
            ),
        ),
        (
            r"(?:the\s+)?(?:last|past)\s+(\d{1,3})\s+(day|week|month|year)s?",
            lambda m: (
                today - timedelta(days=int(m.group(1)) * _UNIT_DAYS[m.group(2)]),
                None,
                f"the last {m.group(1)} {m.group(2)}s",
            ),
        ),
        (
            r"(?:in|from|during)\s+(" + "|".join(MONTHS) + r"|may)(?:\s+(\d{4}))?",
            lambda m: _named_month(m, now),
        ),
        (
            r"(?:in|from|during)\s+(\d{4})",
            lambda m: (
                datetime(int(m.group(1)), 1, 1, tzinfo=timezone.utc),
                datetime(int(m.group(1)) + 1, 1, 1, tzinfo=timezone.utc),
                m.group(1),
            ),
        ),
    ]
    for pattern, build in rules:
        lead = "" if pattern.startswith("(?:in|from|during)") else _LEAD
        m = re.search(r"(?<![\w-])" + lead + pattern + r"(?![\w-])", text, re.IGNORECASE)
        if m:
            inner = re.search(pattern, m.group(0), re.IGNORECASE)
            since, until, label = build(inner)
            return text[: m.start()] + " " + text[m.end() :], since, until, label
    return text, None, None, ""


def _named_month(m, now: datetime):
    month = MONTHS.get(m.group(1).lower(), 5)
    if m.group(2):
        year = int(m.group(2))
    else:  # the most recent such month that has started
        year = now.year if month <= now.month else now.year - 1
    start, end = _month_bounds(year, month)
    return start, end, f"{calendar.month_name[month]} {year}"


def parse(q: str, now: datetime | None = None) -> tuple[str, Filters]:
    """(the text left to search, the filters it named)."""
    now = now or datetime.now(timezone.utc)
    text, since, until, when = _time(q, now)
    kinds: set[str] = set()
    kept = []
    for token in text.split():
        word = token.strip(".,;:!?\"'()").lower()
        if word in KINDS:
            kinds.add(KINDS[word])
        else:
            kept.append(token)
    # Words that only frame the filters ("that", "i saved", "about") carry no meaning
    # once the filters are pulled out.
    rest = " ".join(kept)
    if kinds or since:
        rest = re.sub(r"^(?:(?:the|that|a|an|my|some)\s+)+", "", rest, flags=re.IGNORECASE)
        rest = re.sub(
            r"^(?:(?:i\s+)?(?:saved|added|captured)\s+)?(?:about|on|re|regarding)\s+",
            "",
            rest,
            flags=re.IGNORECASE,
        )
        rest = re.sub(r"\s+(?:i\s+)?(?:saved|added|captured)$", "", rest, flags=re.IGNORECASE)
    kind_label = ", ".join(sorted(f"{k.upper() if k == 'pdf' else k}s" for k in kinds))
    label = " · ".join(x for x in (kind_label, f"saved {when}" if when else "") if x)
    return " ".join(rest.split()), Filters(
        kinds=kinds,
        since=since.isoformat() if since else None,
        until=until.isoformat() if until else None,
        label=label,
    )


def matching_ids(filters: Filters) -> set[str]:
    """Live artifact ids that satisfy every filter."""
    import json

    from .. import db

    where = ["deleted_at IS NULL AND vaulted_at IS NULL AND embedded_at IS NULL"]
    params: list = []
    if filters.kinds:
        where.append("kind IN (SELECT value FROM json_each(?))")
        params.append(json.dumps(sorted(filters.kinds)))
    if filters.since:
        where.append("created_at >= ?")
        params.append(filters.since)
    if filters.until:
        where.append("created_at < ?")
        params.append(filters.until)
    conn = db.get_conn()
    try:
        # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query
        # `where` is built only from the literal clauses above; values are bound.
        rows = conn.execute(
            "SELECT id FROM artifacts WHERE " + " AND ".join(where), params
        ).fetchall()
    finally:
        conn.close()
    return {r["id"] for r in rows}
