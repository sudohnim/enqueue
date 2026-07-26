"""Facet eligibility, and the proper-noun set that forces abstraction.

Facet generation itself is task E4 and is not implemented yet: it depends on the
model decision recorded at the top of docs/PROGRESS.md.
"""

from __future__ import annotations

import re
import uuid

from .. import config, db

_CAP_WORD = re.compile(r"\b([A-Z][a-z]{2,})\b")
_SENTENCE_START = re.compile(r"(?:^|[.!?]\s+|\n\s*)([A-Z][a-z]{2,})")

_STOPWORDS = {
    "the",
    "and",
    "but",
    "for",
    "with",
    "that",
    "this",
    "you",
    "your",
    "his",
    "her",
    "they",
    "when",
    "what",
    "how",
    "why",
    "who",
    "not",
    "are",
    "was",
    "were",
    "one",
    "two",
    "all",
    "any",
    "can",
    "may",
    "will",
    "from",
    "into",
    "then",
    "than",
    "there",
    "here",
    "some",
    "more",
    "most",
    "such",
    "only",
    "also",
    "just",
    "like",
}


def proper_nouns(text: str, title: str) -> set[str]:
    """Words a level-2-or-above facet must not use, lowercased.

    Capitalised words that are not sentence-initial, plus every word of the title.
    A regex and a stoplist are enough. No model, no spaCy.
    """
    sentence_initial = {m.group(1).lower() for m in _SENTENCE_START.finditer(text)}
    capitalised = {m.group(1).lower() for m in _CAP_WORD.finditer(text)}

    nouns = {w for w in capitalised - sentence_initial if w not in _STOPWORDS}
    nouns |= {w.lower() for w in re.findall(r"[A-Za-z]{3,}", title)}
    return {w for w in nouns if w not in _STOPWORDS}


def generate_for_artifact(conn, artifact_id: str) -> tuple[int, str | None]:
    """Generate and store facets for one artifact. Returns (count, error)."""
    from ..prompts import FACET_GENERATION
    from ..providers.base import get_provider
    from ..schemas import FacetSet

    row = conn.execute(
        "SELECT title, local_only FROM artifacts WHERE id = ?", (artifact_id,)
    ).fetchone()
    blocks = conn.execute(
        "SELECT text, depth FROM blocks WHERE artifact_id = ? ORDER BY ordinal", (artifact_id,)
    ).fetchall()
    text = "\n".join(("  " * b["depth"]) + b["text"] for b in blocks)

    provider = get_provider(local_only=bool(row["local_only"]))
    nouns = proper_nouns(text, row["title"])

    try:
        result = provider.complete(
            system=FACET_GENERATION,
            user=f"Title: {row['title']}\n\n{text}",
            response_model=FacetSet,
            context={"proper_nouns": nouns},
        )
    except Exception as exc:  # noqa: BLE001 - the caller reports and continues
        return 0, f"{type(exc).__name__}: {exc}"[:300]

    conn.execute("DELETE FROM facets WHERE artifact_id = ?", (artifact_id,))
    for facet in result.facets:
        conn.execute(
            "INSERT INTO facets (id, artifact_id, level, statement, model_version, trust)"
            " VALUES (?,?,?,?,?,0.5)",
            (str(uuid.uuid4()), artifact_id, int(facet.level), facet.statement, provider.model),
        )
    return len(result.facets), None


def generate_all(limit: int | None = None, redo: bool = False, verbose: bool = False) -> dict:
    """Generate facets for every eligible artifact.

    Commits per artifact so a run of eighty minutes is resumable and does not hold a
    write lock throughout. Artifacts that already have facets are skipped unless redo.

    Sequential on purpose: this runs once per artifact and is not on the interactive
    path. Reranking is the loop that needed concurrency.
    """
    report = {"generated": 0, "facets": 0, "skipped": 0, "failed": 0, "errors": [], "levels": {}}

    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT a.id, a.title FROM artifacts a"
            " LEFT JOIN facet_skips s ON s.artifact_id = a.id"
            " WHERE s.artifact_id IS NULL ORDER BY a.captured_at"
        ).fetchall()
        if limit:
            rows = rows[:limit]

        for i, row in enumerate(rows, 1):
            if not redo:
                have = conn.execute(
                    "SELECT COUNT(*) n FROM facets WHERE artifact_id = ?", (row["id"],)
                ).fetchone()["n"]
                if have:
                    report["skipped"] += 1
                    continue

            count, error = generate_for_artifact(conn, row["id"])
            conn.commit()

            if error:
                report["failed"] += 1
                report["errors"].append({"title": row["title"], "error": error})
            else:
                report["generated"] += 1
                report["facets"] += count
            if verbose:
                status = f"FAILED {error[:60]}" if error else f"{count} facets"
                print(f"[{i}/{len(rows)}] {row['title'][:44]:<46} {status}", flush=True)

        for r in conn.execute("SELECT level, COUNT(*) n FROM facets GROUP BY level"):
            report["levels"][str(r["level"])] = r["n"]
    finally:
        conn.close()

    return report


def _word_count(conn, artifact_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(LENGTH(text) - LENGTH(REPLACE(text, ' ', '')) + 1), 0) AS n"
        " FROM blocks WHERE artifact_id = ?",
        (artifact_id,),
    ).fetchone()
    return int(row["n"])


def apply_eligibility_gate() -> dict[str, int]:
    """Decide which artifacts never get facets.

    About a third of a real corpus should not enter the facet layer at all. A kubectl
    command has no honest level-3 abstraction, and forcing one produces noise that
    matches random lenses forever.
    """
    counts = {"too_short": 0, "kind": 0, "text_only": 0, "eligible": 0}

    with db.transaction() as conn:
        conn.execute("DELETE FROM facet_skips")
        rows = conn.execute("SELECT id, kind, status, imported_from FROM artifacts").fetchall()

        for row in rows:
            folder = (row["imported_from"] or "").split(":")[-1]
            reason = None

            if row["status"] == "text_only":
                reason = "text_only"
            elif row["kind"] != "note" or folder in config.SKIP_FACETS_FOR_FOLDERS:
                reason = "kind"
            elif _word_count(conn, row["id"]) < config.MIN_WORDS_FOR_FACETS:
                reason = "too_short"

            if reason:
                conn.execute(
                    "INSERT INTO facet_skips (artifact_id, reason) VALUES (?,?)",
                    (row["id"], reason),
                )
                counts[reason] += 1
            else:
                counts["eligible"] += 1

    return counts
