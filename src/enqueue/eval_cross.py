"""Cross-domain search eval: a query in one field must find a note from another field.

Loads evals/cross_domain.yaml plus the main eval corpus (as background) into an
isolated test database, then runs every query through the real /search rollup three
times: chunks only, with facets, and with facets plus query lifting. Facets and lifts
come from evals/cross_domain_facets.json (a committed fixture, so CI needs no model),
or are written fresh with the live models by `enq eval-cross --generate-facets`.
See AGENTS.md "Cross-domain eval".
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path

import yaml

EVALS_DIR = Path(__file__).resolve().parent.parent.parent / "evals"
SUITE_PATH = EVALS_DIR / "cross_domain.yaml"
FACETS_PATH = EVALS_DIR / "cross_domain_facets.json"
MAIN_CORPUS = EVALS_DIR / "corpus"
TEST_DIR = EVALS_DIR / "test-data-cross"

# A query passes when its target ranks in the top PASS_RANK. With ~65 notes a top-10
# bar would be passed by chance too often to mean anything.
PASS_RANK = 3


def load_suite(path: Path = SUITE_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def forbidden_hits(text: str, words: list[str]) -> list[str]:
    """The forbidden words that occur in `text` as whole words (case-insensitive)."""
    lowered = text.lower()
    return [
        w for w in words if re.search(r"(?<![a-z])" + re.escape(w.lower()) + r"(?![a-z])", lowered)
    ]


def score(results: list[dict]) -> dict:
    """Summary of per-query results: pass count, pass rate, MRR over the top 10."""
    total = len(results)
    passed = sum(1 for r in results if r["pass"])
    mrr = sum(1.0 / r["rank"] for r in results if r["rank"]) / total if total else 0.0
    return {
        "total": total,
        "pass": passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "MRR": round(mrr, 4),
    }


def rank_of(expected: list[str], hit_ids: list[str]) -> int | None:
    for rank, aid in enumerate(hit_ids, start=1):
        if aid in expected:
            return rank
    return None


def _main_corpus() -> list[dict]:
    manifest = json.loads((MAIN_CORPUS / "MANIFEST.json").read_text(encoding="utf-8"))
    out = []
    for entry in manifest["artifacts"]:
        content = (MAIN_CORPUS / entry["filename"]).read_text(encoding="utf-8")
        title, _, body = content.partition("\n\n")
        out.append({"id": entry["id"], "title": title.lstrip("# ").strip(), "body": body})
    return out


def note_body(note: dict, main: dict[str, dict] | None = None) -> str:
    """A suite note's full body: any `pad_with` main-corpus documents, then its own."""
    if not note.get("pad_with"):
        return note["body"]
    main = main or {n["id"]: n for n in _main_corpus()}
    return "\n\n".join([*(main[m]["body"] for m in note["pad_with"]), note["body"]])


def _notes(suite: dict) -> list[dict]:
    """Suite notes and decoys (padded where asked), then the main corpus as background."""
    background = _main_corpus()
    main = {n["id"]: n for n in background}
    suite_notes = [
        {"id": n["id"], "title": n["title"], "body": note_body(n, main)}
        for n in suite["notes"] + suite["decoys"]
    ]
    return suite_notes + background


def build(suite: dict) -> None:
    """A fresh test library at TEST_DIR: notes inserted, chunked, chunk-indexed.

    Assumes config already points at TEST_DIR (see `pointed_at_test_dir`).
    """
    from . import db
    from .index.store import get_store
    from .ingest.chunk import chunk_artifact

    now = db.now()
    with db.transaction() as conn:
        for n in _notes(suite):
            conn.execute(
                "INSERT INTO artifacts (id, kind, title, body, content_hash, status,"
                " created_at, updated_at) VALUES (?, 'note', ?, ?, ?, 'ok', ?, ?)",
                (n["id"], n["title"], n["body"], n["id"] + "_hash", now, now),
            )
            chunk_artifact(conn, n["id"])
    get_store.cache_clear()
    store = get_store()
    store.ensure()
    store.upsert_chunks()
    store.write_embed_version()


def load_facets(fixture: dict) -> int:
    """Insert fixture facets, stamped with the current ingest model so search keeps them."""
    from . import db
    from .index.store import get_store
    from .providers.base import model_for

    model = model_for("ingest")
    n = 0
    with db.transaction() as conn:
        for aid, facets in fixture.items():
            for f in facets:
                conn.execute(
                    "INSERT INTO facets (id, artifact_id, level, statement, model_version,"
                    " trust, body_version) VALUES (?,?,?,?,?,?,NULL)",
                    (str(uuid.uuid4()), aid, f["level"], f["statement"], model, f["trust"]),
                )
                n += 1
    get_store().upsert_facets()
    return n


def generate_lifts(suite: dict) -> dict[str, list[str]]:
    """Lift every query with the live search model (retrieve/lift.py)."""
    from .retrieve import lift

    return {q["id"]: lift.lift(q["query"]) for q in suite["queries"]}


def generate_facets(suite: dict) -> dict:
    """Write facets for the suite's notes and decoys with the live ingest model."""
    from . import db
    from .ingest import facets as facets_mod

    out: dict[str, list[dict]] = {}
    for n in suite["notes"] + suite["decoys"]:
        with db.transaction() as conn:
            count, error = facets_mod.generate_for_artifact(conn, n["id"])
        if error:
            raise RuntimeError(f"{n['id']}: {error}")
        conn = db.get_conn()
        try:
            rows = conn.execute(
                "SELECT level, statement, trust FROM facets WHERE artifact_id = ?"
                " ORDER BY level, statement",
                (n["id"],),
            ).fetchall()
        finally:
            conn.close()
        out[n["id"]] = [dict(r) for r in rows]
    return out


def run_queries(suite: dict) -> list[dict]:
    from .retrieve.candidates import search_results

    results = []
    for q in suite["queries"]:
        hits = [h["artifact_id"] for h in search_results(q["query"], limit=10)]
        rank = rank_of(q["expect"], hits)
        results.append(
            {
                "id": q["id"],
                "rank": rank,
                "pass": rank is not None and rank <= PASS_RANK,
                "top_hit": hits[0] if hits else None,
            }
        )
    return results


class pointed_at_test_dir:
    """Repoint config at a fresh TEST_DIR for the duration, then restore it."""

    def __enter__(self):
        from . import config, db
        from .index.store import get_store

        shutil.rmtree(TEST_DIR, ignore_errors=True)
        (TEST_DIR / "blobs").mkdir(parents=True)
        self._saved = (config.DATA_DIR, config.DB_PATH, config.BLOB_DIR)
        config.DATA_DIR, config.DB_PATH, config.BLOB_DIR = (
            TEST_DIR,
            TEST_DIR / "enqueue.db",
            TEST_DIR / "blobs",
        )
        db.reset_migration_state()
        get_store.cache_clear()
        return self

    def __exit__(self, *exc):
        from . import config, db
        from .index.store import get_store

        config.DATA_DIR, config.DB_PATH, config.BLOB_DIR = self._saved
        db.reset_migration_state()
        get_store.cache_clear()
        return False


def run(generate: bool = False) -> dict:
    """Build the library, run all three modes, return the report.

    `generate=True` writes fresh facets (ingest model) and lifts (search model) and
    saves them as the fixture; otherwise the committed fixture is used (absent means
    no facets and no lifts). Outside `generate`, lifting reads only the fixture, so
    the eval never calls a model.
    """
    from . import settings
    from .index.store import get_store
    from .retrieve import lift

    suite = load_suite()
    fixture = {"facets": {}, "lifts": {}}
    if not generate and FACETS_PATH.exists():
        fixture = json.loads(FACETS_PATH.read_text(encoding="utf-8"))
    real_lift = lift.lift
    with pointed_at_test_dir():
        build(suite)
        chunks_only = run_queries(suite)
        if generate:
            fixture = {"facets": generate_facets(suite), "lifts": generate_lifts(suite)}
            FACETS_PATH.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
            get_store().upsert_facets()
            n_facets = sum(len(v) for v in fixture["facets"].values())
        else:
            n_facets = load_facets(fixture["facets"])
        with_facets = run_queries(suite)

        by_query = {q["query"]: fixture["lifts"].get(q["id"], []) for q in suite["queries"]}
        settings.update({"search_lift": "on"})
        lift.lift = lambda query: by_query.get(query, [])
        try:
            lifted = run_queries(suite)
        finally:
            lift.lift = real_lift
    return {
        "pass_rank": PASS_RANK,
        "facets_loaded": n_facets,
        "lifts_loaded": sum(len(v) for v in fixture["lifts"].values()),
        "modes": {
            "chunks": {**score(chunks_only), "results": chunks_only},
            "facets": {**score(with_facets), "results": with_facets},
            "lifted": {**score(lifted), "results": lifted},
        },
    }
