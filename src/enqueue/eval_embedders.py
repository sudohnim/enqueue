"""Compare embedding models on both evals, and suggest each one's relevance floor.

For every candidate: rebuild the main 50-note test library and the cross-domain
library with that model, then report main-eval recall@10, MRR and Nothing-OK, the
cross-domain pass counts, and relevance-floor bars fitted to the model's own cosine
scale. The gray-zone judge is held fail-open (keep everything), as in CI, so the
numbers compare the embedders and not a model's verdicts.

Candidates download from Hugging Face on first use. Only 768-dimensional models are
listed, because the index tables are built at that width. A winner joins
config.EMBED_MODELS with its suggested bars; see AGENTS.md "Embedding models".
"""

from __future__ import annotations

import json
import math
import tempfile
from contextlib import contextmanager
from pathlib import Path

import yaml

from . import config

BGE_QUERY = "Represent this sentence for searching relevant passages: "

CANDIDATES = {
    "BAAI/bge-base-en-v1.5": {"query_prefix": BGE_QUERY, "doc_prefix": ""},
    "nomic-ai/nomic-embed-text-v1.5": {
        "query_prefix": "search_query: ",
        "doc_prefix": "search_document: ",
    },
    "snowflake/snowflake-arctic-embed-m": {"query_prefix": BGE_QUERY, "doc_prefix": ""},
    "snowflake/snowflake-arctic-embed-m-long": {"query_prefix": BGE_QUERY, "doc_prefix": ""},
    "thenlper/gte-base": {"query_prefix": "", "doc_prefix": ""},
    "jinaai/jina-embeddings-v2-base-en": {"query_prefix": "", "doc_prefix": ""},
}

# Room left between the calibration extremes and a suggested bar.
MARGIN = 0.02


def suggest_bars(real_best: list[float], nothing_best: list[float]) -> dict:
    """Floor bars on this model's scale: drop below the weakest real match, keep above
    the strongest no-match neighbour, each with MARGIN to spare."""
    drop = math.floor((min(real_best) - MARGIN) * 100) / 100
    keep = math.ceil((max(nothing_best) + MARGIN) * 100) / 100
    return {"keep_above": max(keep, drop), "drop_below": drop}


@contextmanager
def using(model: str, bars: dict | None = None):
    """Point the embedder (and optionally the floor) at `model`, then restore."""
    from .index import embed
    from .index.store import get_store
    from .retrieve import candidates as cand

    spec = CANDIDATES[model]
    saved = (
        config.EMBED_MODEL,
        config.EMBED_VERSION,
        config.EMBED_QUERY_PREFIX,
        config.EMBED_DOC_PREFIX,
        cand.KEEP_ABOVE,
        cand.DROP_BELOW,
    )
    config.EMBED_MODEL = model
    config.EMBED_VERSION = model.split("/")[-1]
    config.EMBED_QUERY_PREFIX = spec["query_prefix"]
    config.EMBED_DOC_PREFIX = spec["doc_prefix"]
    if bars:
        cand.KEEP_ABOVE, cand.DROP_BELOW = bars["keep_above"], bars["drop_below"]
    embed._model.cache_clear()
    embed.embed_one.cache_clear()
    get_store.cache_clear()
    try:
        yield
    finally:
        (
            config.EMBED_MODEL,
            config.EMBED_VERSION,
            config.EMBED_QUERY_PREFIX,
            config.EMBED_DOC_PREFIX,
            cand.KEEP_ABOVE,
            cand.DROP_BELOW,
        ) = saved
        embed._model.cache_clear()
        embed.embed_one.cache_clear()
        get_store.cache_clear()


def _main_eval(test_dir: Path) -> dict:
    """Build the main test library under `test_dir`, fit the floor, score the queries."""
    from . import db
    from .cli import MANIFEST_PATH, QUERIES_PATH, _load_corpus_into_db
    from .index.store import get_store
    from .retrieve import candidates as cand

    entries = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["artifacts"]
    _load_corpus_into_db(test_dir, entries)
    queries = yaml.safe_load(QUERIES_PATH.read_text(encoding="utf-8"))["queries"]

    saved = config.DB_PATH
    config.DB_PATH = test_dir / "enqueue.db"
    db.reset_migration_state()
    get_store.cache_clear()
    try:
        store = get_store()
        real, nothing = [], []
        for q in queries:
            hits = store.search_dense(store.CHUNKS, q["query"], limit=200)
            if q["category"] == "nothing":
                nothing.append(max(h["score"] for h in hits))
            else:
                expected = set(q["expect_artifact_ids"])
                real.append(
                    max((h["score"] for h in hits if h["artifact_id"] in expected), default=0)
                )
        bars = suggest_bars(real, nothing)
        cand.KEEP_ABOVE, cand.DROP_BELOW = bars["keep_above"], bars["drop_below"]

        found = ranks = nothing_ok = 0
        rr = 0.0
        for q in queries:
            hits = [h["artifact_id"] for h in cand.search_results(q["query"], limit=10)]
            if q["category"] == "nothing":
                nothing_ok += not hits
                continue
            rank = next((i for i, a in enumerate(hits, 1) if a in q["expect_artifact_ids"]), None)
            if rank:
                found += 1
                rr += 1 / rank
            ranks += 1
        return {
            "recall@10": round(found / ranks, 3),
            "MRR": round(rr / ranks, 3),
            "nothing_ok": f"{nothing_ok}/{len(queries) - ranks}",
            "bars": bars,
        }
    finally:
        config.DB_PATH = saved
        db.reset_migration_state()
        get_store.cache_clear()


def run(models: list[str] | None = None) -> list[dict]:
    from . import eval_cross as xd
    from .retrieve import candidates as cand

    real_judge = cand.judge_gray_zone
    cand.judge_gray_zone = lambda query, hits: {h["artifact_id"] for h in hits}
    rows = []
    try:
        for model in models or list(CANDIDATES):
            with using(model), tempfile.TemporaryDirectory() as tmp:
                main = _main_eval(Path(tmp))
                with using(model, main["bars"]):
                    cross = xd.run()["modes"]
            rows.append(
                {
                    "model": model,
                    **main,
                    "cross_chunks": cross["chunks"]["pass"],
                    "cross_enriched": cross["enriched"]["pass"],
                    "cross_total": cross["chunks"]["total"],
                }
            )
    finally:
        cand.judge_gray_zone = real_judge
    return rows
