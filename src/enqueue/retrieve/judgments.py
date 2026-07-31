"""The judgment cache: same lens, same artifact, same model -> no second call.

Phase 8. Every judgment a lens produces is written to `lens_judgments`, keyed
by (lens_key, artifact_id, model_version). Re-running the same lens reuses the
rows instead of calling the model, so a topic the wall has already curated is
instant next time. Changing the model changes the key's model_version, so a
new model re-judges rather than serving reasoning it never produced.
"""

from __future__ import annotations

import hashlib
import re
import time

from .. import config, db

_WS = re.compile(r"\s+")


def lens_key(lens: str) -> str:
    """Stable normalized key: lowercase, trimmed, whitespace collapsed, hashed.

    Two spellings that differ only by capitalization or extra spacing hash to
    the same key, so "How do we...?" and "  HOW   do we...?" are the same
    topic. Hashing keeps the key fixed-width and opaque in the database.
    """
    normalized = _WS.sub(" ", lens.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def model_version() -> str:
    """What produced the reasoning. Backend plus model, so either change re-judges."""
    return f"{config.LLM_BACKEND}/{config.LLM_MODEL}"


def get(lens: str, artifact_id: str) -> dict | None:
    """A cached judgment for this artifact under this lens, or None.

    A row for a different model_version is treated as absent, so a model
    switch re-judges rather than serving stale reasoning.
    """
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT belongs, strength, placard, evidence FROM lens_judgments"
            " WHERE lens_key = ? AND artifact_id = ? AND model_version = ?",
            (lens_key(lens), artifact_id, model_version()),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    return {
        "belongs": bool(row["belongs"]),
        "strength": row["strength"],
        "placard": row["placard"],
        "evidence": row["evidence"],
    }


def put(
    lens: str,
    artifact_id: str,
    belongs: bool,
    strength: float,
    placard: str,
    evidence: str,
) -> None:
    """Record a judgment. INSERT OR REPLACE: a re-judgment overwrites the row."""
    conn = db.get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO lens_judgments"
            " (lens_key, artifact_id, belongs, strength, placard, evidence,"
            "  model_version, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                lens_key(lens),
                artifact_id,
                1 if belongs else 0,
                strength,
                placard,
                evidence,
                model_version(),
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def clear() -> int:
    """Delete every cached judgment. Returns the number of rows removed."""
    conn = db.get_conn()
    try:
        cur = conn.execute("DELETE FROM lens_judgments")
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def stats() -> dict:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n, COUNT(DISTINCT lens_key) AS k FROM lens_judgments"
        ).fetchone()
    finally:
        conn.close()
    return {"rows": row["n"], "lenses": row["k"]}
