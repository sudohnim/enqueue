"""Entities: the proper names in an artifact's text, enriched with one line of world knowledge.

Pure embeddings, and even facets, miss a whole class of question. "Notes on
presidents" never reaches a Roosevelt biography that never says "president":
the biography's own words share no vocabulary with the question, and the facet
layer abstracts what the text is an example of, not who or what it names.

The fix mirrors the title-seed enrich pattern: `field(title)` reads a grounded
value, then `enrich` adds world knowledge to it. Here the grounded value is
the set of proper names extracted from the body itself (one model call), and
each name is then enriched into a one-line fact ("Theodore Roosevelt - 26th
US President") using the same world-knowledge path. Those lines are indexed
the way facets are, so a question phrased in the world's vocabulary reaches
an artifact that never used it.

The extraction call is the only part that reads the artifact; the enrichment
is per-name world knowledge, exactly like `derive.enrich` (ungrounded, so the
grounded/derived distinction travels with it). One bad name never fails the
artifact: each name is enriched and quality-gated on its own, and a failure
drops that line, not the artifact.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel

# The cost bound per artifact. All names are enriched in one call, but a longer list
# is a longer prompt and more lines to gate; the most prominent names come first.
MAX_ENTITIES = 8

_FACT_MIN_WORDS = 6
_FACT_MAX_WORDS = 30


class _RawEntity(BaseModel):
    """A named entity as the model returns it, before the quality gate."""

    name: str


class _RawEntitySet(BaseModel):
    entities: list[_RawEntity]


class _RawFact(BaseModel):
    """One enriched line as the model returns it. `fact` may be empty ("unknown")."""

    fact: str


class _RawNamedFact(BaseModel):
    name: str
    fact: str


class _RawFactSet(BaseModel):
    """Every name's line from one batched enrichment call."""

    facts: list[_RawNamedFact]


def _gate(entity: str, fact: str | None) -> str | None:
    """The per-line quality bar: 6-30 words, a full sentence, and names the entity."""
    fact = (fact or "").strip()
    if not fact:
        return None
    if not (_FACT_MIN_WORDS <= len(fact.split()) <= _FACT_MAX_WORDS):
        return None
    if not fact.rstrip().endswith("."):
        return None
    # The line must name the entity, or it cannot bridge the vocabulary gap.
    if entity.lower() not in fact.lower():
        return None
    return fact


def _enrich_all(provider, names: list[str]) -> dict[str, str | None]:
    """One world-knowledge line per name, from one batched call.

    Each line is gated on its own; a name the reply leaves out gets None. If the
    batched call itself fails, fall back to one call per name so a single bad
    response cannot lose every entity.
    """
    from ..prompts import ENTITY_ENRICH_BATCH

    try:
        raw = provider.complete(
            system=ENTITY_ENRICH_BATCH,
            user="Entities:\n" + "\n".join(names),
            response_model=_RawFactSet,
        )
    except Exception:  # noqa: BLE001 - fall back to the per-name path
        return {name: _enrich_one(provider, name) for name in names}
    replied = {f.name.strip().lower(): f.fact for f in raw.facts}
    return {name: _gate(name, replied.get(name.lower())) for name in names}


def _enrich_one(provider, entity: str) -> str | None:
    """One world-knowledge line for one entity, or None when it cannot be written.

    Mirrors `derive.enrich`: the fact is inferred from the model's knowledge,
    never read from the artifact. A failure or an empty answer produces no line.
    """
    from ..prompts import ENTITY_ENRICH

    try:
        raw = provider.complete(
            system=ENTITY_ENRICH,
            user=f"Entity:\n{entity}",
            response_model=_RawFact,
        )
    except Exception:  # noqa: BLE001 - one bad entity never fails the artifact
        return None

    return _gate(entity, raw.fact)


def generate_for_artifact(conn, artifact_id: str) -> tuple[int, str | None]:
    """Extract one artifact's named entities and enrich each into a fact line.

    Returns (count, error). One bad entity drops that line, never the artifact;
    only an extraction failure or zero surviving lines is an error. Rows are
    replaced wholesale on a successful run, so a regen heals stale entries.
    """
    from ..prompts import ENTITY_EXTRACT
    from ..providers.base import get_provider
    from .source import ingest_text

    row = conn.execute(
        "SELECT title, body, local_only,"
        " (SELECT MAX(created_at) FROM artifact_versions v"
        "  WHERE v.artifact_id = artifacts.id) AS body_version"
        " FROM artifacts WHERE id = ?",
        (artifact_id,),
    ).fetchone()
    if row is None:
        return 0, "no such artifact"
    # Body for a note, extracted pages for a link/PDF/image, plus the person's notes.
    text = ingest_text(conn, artifact_id)

    provider = get_provider(local_only=bool(row["local_only"]), summarize=True)

    try:
        raw = provider.complete(
            system=ENTITY_EXTRACT,
            user=f"Title: {row['title']}\n\n{text}",
            response_model=_RawEntitySet,
        )
    except Exception as exc:  # noqa: BLE001 - the caller reports and continues
        return 0, f"{type(exc).__name__}: {exc}"[:300]

    names = list(
        dict.fromkeys(
            n
            for n in ((rf.name or "").strip() for rf in raw.entities[:MAX_ENTITIES])
            if 2 <= len(n) <= 80
        )
    )
    facts = _enrich_all(provider, names) if names else {}
    kept = [(name, facts[name]) for name in names if facts.get(name)]

    if not kept:
        return 0, "no entity cleared the quality gate"

    conn.execute("DELETE FROM entities WHERE artifact_id = ?", (artifact_id,))
    for name, fact in kept:
        conn.execute(
            "INSERT INTO entities"
            " (id, artifact_id, entity, fact, model_version, body_version, trust)"
            " VALUES (?,?,?,?,?,?,0.5)",
            (
                str(uuid.uuid4()),
                artifact_id,
                name,
                fact,
                provider.model,
                row["body_version"],
            ),
        )
    return len(kept), None
