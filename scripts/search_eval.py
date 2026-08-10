"""Golden-set recall harness for /search.

Loads `evals/search/queries.json`, runs each query through the real
`retrieve.candidates.search_results` rollup, and prints per-query hit/miss
plus recall@10 and MRR. Deterministic and offline: it runs against the
fixture database built by `scripts/seed_search_eval.py` (built on demand
when missing), never against a live engine.

Usage: uv run python scripts/search_eval.py [db_path]

Exit code: 0 when the golden set file exists and the run completes; 1 when
the file is missing (or the run fails). The numbers are the retrieval
baseline every ranking change in phase R is measured against.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUERIES = ROOT / "evals" / "search" / "queries.json"
DEFAULT_DB = ROOT / "evals" / "search" / "eval.db"


def _load_queries() -> list[dict]:
    try:
        data = json.loads(QUERIES.read_text())
    except FileNotFoundError:
        print(f"missing golden set: {QUERIES}", file=sys.stderr)
        sys.exit(1)
    return data


def main(db_path: Path) -> None:
    queries = _load_queries()

    if not db_path.exists():
        from seed_search_eval import seed

        seed(db_path)

    from enqueue import config, db
    from enqueue.index.store import get_store
    from enqueue.retrieve.candidates import search_results

    config.DATA_DIR = db_path.parent
    config.DB_PATH = db_path
    config.BLOB_DIR = db_path.parent / "blobs"
    config.VECTOR_STORE = "sqlite-vec"
    db.reset_migration_state()
    db.migrate()
    get_store.cache_clear()

    recall = 0
    mrr = 0.0
    print(f"{'query':<52} {'rank':<6} hit")
    for case in queries:
        query = case["query"]
        needle = case["expect_id_substring"]
        hits = search_results(query, limit=10)
        ids = [h["artifact_id"] for h in hits]
        found = next((i for i, aid in enumerate(ids) if needle in aid), None)
        if found is not None:
            recall += 1
            mrr += 1.0 / (found + 1)
        print(
            f"{query[:50]:<52} {str(found + 1 if found is not None else '-') + '':<6} {'HIT' if found is not None else 'miss'}"
        )

    total = len(queries)
    print(f"\nrecall@10: {recall}/{total} ({recall / total:.3f})")
    print(f"MRR:       {mrr / total:.3f}")


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    main(path)
