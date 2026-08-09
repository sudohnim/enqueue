"""Facets: what an artifact could be an example of.

Reads a note's markdown body. Captures are skipped by the eligibility gate until
text extraction exists, since there is nothing to abstract from yet.
"""

from __future__ import annotations

import re
import uuid

from pydantic import BaseModel

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


class _RawFacet(BaseModel):
    """A facet as the model returns it, before the quality gate. No validators:
    the whole point is to accept whatever came back, then judge each one in code."""

    level: int
    statement: str


class _RawFacetSet(BaseModel):
    facets: list[_RawFacet]


def generate_for_artifact(conn, artifact_id: str) -> tuple[int, str | None]:
    """Generate and store facets for one artifact. Returns (count, error).

    The quality gate is applied per facet, not to the whole set. A strong model
    returns a fully valid set; a weak one returns a few good abstract facets
    among some that name their subject or run long. Rejecting the whole set on
    one bad facet (the old all-or-nothing) left weak-model libraries with zero
    facets and no conceptual bridge at all. Instead every facet that clears the
    same per-facet bar - the climb check, the length, the no-self-reference rule -
    is kept, and the rest are dropped. Some grounded facets beat none.
    """
    from ..prompts import FACET_GENERATION
    from ..providers.base import get_provider
    from ..schemas import Facet

    row = conn.execute(
        "SELECT title, body, local_only,"
        " (SELECT MAX(created_at) FROM artifact_versions v"
        "  WHERE v.artifact_id = artifacts.id) AS body_version"
        " FROM artifacts WHERE id = ?",
        (artifact_id,),
    ).fetchone()
    text = row["body"] or ""

    provider = get_provider(local_only=bool(row["local_only"]))
    nouns = proper_nouns(text, row["title"])

    try:
        raw = provider.complete(
            system=FACET_GENERATION,
            user=f"Title: {row['title']}\n\n{text}",
            response_model=_RawFacetSet,
            context={"proper_nouns": nouns},
        )
    except Exception as exc:  # noqa: BLE001 - the caller reports and continues
        return 0, f"{type(exc).__name__}: {exc}"[:300]

    # Keep each facet that passes the same per-facet quality bar the strict schema
    # enforces; drop the ones that do not. One long or subject-naming facet no
    # longer discards the good ones alongside it.
    kept: list[Facet] = []
    for rf in raw.facets:
        try:
            kept.append(
                Facet.model_validate(
                    {"level": rf.level, "statement": rf.statement},
                    context={"proper_nouns": nouns},
                )
            )
        except Exception:  # noqa: BLE001 - a facet that fails the bar is simply not kept
            continue

    if not kept:
        return 0, "no facet cleared the quality gate"

    conn.execute("DELETE FROM facets WHERE artifact_id = ?", (artifact_id,))
    for facet in kept:
        conn.execute(
            "INSERT INTO facets"
            " (id, artifact_id, level, statement, model_version, body_version, trust)"
            " VALUES (?,?,?,?,?,?,0.5)",
            (
                str(uuid.uuid4()),
                artifact_id,
                facet.level,
                facet.statement,
                provider.model,
                row["body_version"],
            ),
        )
    return len(kept), None


def _artifact_is_model_stale(conn, artifact_id: str, cache: dict) -> bool:
    """Whether the artifact's stored facets were written by an older model.

    A model upgrade is the only thing that makes facets model-stale; body edits
    are handled by the per-artifact ingest path, not by a batch refresh. An
    artifact with no facets is not stale - there is nothing to catch up, and the
    full `redo` covers it. `cache` maps artifact_id to (has_facets, model) so a
    run over the library calls the provider once per artifact at most.
    """
    if artifact_id not in cache:
        row = conn.execute(
            "SELECT local_only,"
            " (SELECT model_version FROM facets f WHERE f.artifact_id = artifacts.id"
            "  LIMIT 1) AS model_version"
            " FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        if row is None or row["model_version"] is None:
            cache[artifact_id] = False
        else:
            from ..providers.base import get_provider

            cache[artifact_id] = (
                row["model_version"] != get_provider(local_only=bool(row["local_only"])).model
            )
    return cache[artifact_id]


def generate_all(
    limit: int | None = None,
    redo: bool = False,
    stale_only: bool = False,
    verbose: bool = False,
) -> dict:
    """Generate facets for every eligible artifact.

    Commits per artifact so a run of eighty minutes is resumable and does not hold a
    write lock throughout. Artifacts that already have facets are skipped unless redo.

    `stale_only` is the cheap catch-up for a model upgrade: it regenerates only
    artifacts whose stored facets were written by an older model, leaving current
    ones untouched. It is distinct from `redo`, which recomputes everything
    including artifacts that are already current.

    Sequential on purpose: this runs once per artifact and is not on the interactive
    path. Reranking is the loop that needed concurrency.
    """
    report = {"generated": 0, "facets": 0, "skipped": 0, "failed": 0, "errors": [], "levels": {}}

    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT a.id, a.title FROM artifacts a"
            " LEFT JOIN facet_skips s ON s.artifact_id = a.id"
            " WHERE s.artifact_id IS NULL ORDER BY a.created_at"
        ).fetchall()
        if limit:
            rows = rows[:limit]

        cache: dict = {}
        for i, row in enumerate(rows, 1):
            if stale_only:
                if not _artifact_is_model_stale(conn, row["id"], cache):
                    report["skipped"] += 1
                    continue
            elif not redo:
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


def _word_count(body: str | None) -> int:
    return len((body or "").split())


def apply_eligibility_gate() -> dict[str, int]:
    """Decide which artifacts never get facets.

    About a third of a real corpus should not enter the facet layer at all. A kubectl
    command has no honest level-3 abstraction, and forcing one produces noise that
    matches random lenses forever.
    """
    counts = {"too_short": 0, "kind": 0, "text_only": 0, "eligible": 0}

    with db.transaction() as conn:
        conn.execute("DELETE FROM facet_skips")
        rows = conn.execute(
            "SELECT a.id, a.kind, a.status, a.body,"
            " (SELECT COALESCE(SUM(LENGTH(p.text) - LENGTH(REPLACE(p.text, ' ', ''))"
            " + 1), 0) FROM page_text p WHERE p.artifact_id = a.id) AS page_words"
            " FROM artifacts a"
        ).fetchall()

        for row in rows:
            reason = None
            words = _word_count(row["body"] or "") + row["page_words"]

            if row["status"] == "text_only":
                reason = "text_only"
            elif words == 0:
                # Nothing to abstract from: a PDF before text extraction ran, an
                # image before the vision step described it (K.11). The gate is on
                # text, not on kind, so the moment the body or page text lands the
                # same row is eligible - a note, a PDF, an image alike.
                reason = "kind"
            elif words < config.MIN_WORDS_FOR_FACETS:
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
