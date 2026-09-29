"""Real-search eval: the searches a person actually ran, scored against the library.

A search followed by opening one of its results is a labelled example: that query
should find that artifact. Every such pair in the `opens` table becomes a case
(one case per distinct query, expecting any artifact opened from it), and the case
passes when one of them ranks in the top PASS_RANK of the live /search rollup.

It runs inside the engine against the real library (POST /eval/real, `enq
eval-real`), because the cases are private and never leave the machine. The
baseline lives beside the library at DATA_DIR/evals/real-baseline.json.
See AGENTS.md "Real-search eval".
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config, db
from .eval_cross import PASS_RANK, rank_of, score

LIMIT = 10


def baseline_path() -> Path:
    return config.DATA_DIR / "evals" / "real-baseline.json"


def cases() -> list[dict]:
    """One case per distinct query (case- and space-insensitive), newest first."""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT lower(trim(o.query)) AS q, o.artifact_id, MAX(o.opened_at) AS last"
            " FROM opens o JOIN artifacts a ON a.id = o.artifact_id"
            " WHERE o.source = 'search' AND o.query IS NOT NULL"
            " AND a.deleted_at IS NULL AND a.vaulted_at IS NULL"
            " GROUP BY q, o.artifact_id ORDER BY last DESC"
        ).fetchall()
    finally:
        conn.close()
    by_query: dict[str, list[str]] = {}
    for r in rows:
        by_query.setdefault(r["q"], []).append(r["artifact_id"])
    return [{"query": q, "expect": ids} for q, ids in by_query.items()]


def run() -> dict:
    from .retrieve.candidates import search_results

    results = []
    for case in cases():
        hits = [h["artifact_id"] for h in search_results(case["query"], limit=LIMIT)]
        rank = rank_of(case["expect"], hits)
        results.append(
            {
                "query": case["query"],
                "expect": case["expect"],
                "rank": rank,
                "pass": rank is not None and rank <= PASS_RANK,
            }
        )
    summary = score(results)
    summary["found_in_top_10"] = sum(1 for r in results if r["rank"])
    return {"pass_rank": PASS_RANK, **summary, "results": results}


def lost(now: dict, base: dict) -> list[str]:
    """Queries that passed in the baseline and fail now. New and removed cases are
    neither: a query only counts once both runs have it."""
    passed_before = {r["query"] for r in base["results"] if r["pass"]}
    return sorted(
        r["query"] for r in now["results"] if r["query"] in passed_before and not r["pass"]
    )


def check(update_baseline: bool = False) -> dict:
    """Run, compare with the stored baseline, and optionally replace it."""
    now = run()
    path = baseline_path()
    base = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    report = {
        **now,
        "baseline": (
            {k: base[k] for k in ("total", "pass", "MRR", "found_in_top_10")} if base else None
        ),
        "lost": lost(now, base) if base else [],
    }
    if update_baseline:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(now, indent=2) + "\n", encoding="utf-8")
    return report
