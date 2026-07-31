"""CLI. A thin client over the engine API.

No command here touches the database directly. If the engine is not running, commands
that need it say so rather than reaching around the boundary.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import typer

from . import config

app = typer.Typer(add_completion=False, help="Enqueue: capture anything, organise it later.")


def _call(method: str, path: str, **kwargs) -> dict:
    try:
        response = httpx.request(
            method,
            f"{config.API_URL}{path}",
            timeout=kwargs.pop("timeout", 600),
            **kwargs,
        )
    except httpx.ConnectError:
        typer.secho(
            f"engine is not running at {config.API_URL}\nstart it with:  enq serve",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1) from None
    if response.status_code >= 400:
        typer.secho(f"{response.status_code}: {response.text}", fg=typer.colors.RED)
        raise typer.Exit(1)
    return response.json()


def _echo(payload: dict) -> None:
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


@app.command()
def version() -> None:
    """Print the package version."""
    from importlib.metadata import version as pkg_version

    typer.echo(pkg_version("enqueue"))


@app.command()
def serve() -> None:
    """Run the engine on 127.0.0.1 only."""
    from .api import serve as run

    run()


@app.command()
def health() -> None:
    """Engine status and row counts."""
    _echo(_call("GET", "/health"))


@app.command()
def migrate() -> None:
    """Bring the database to the newest revision.

    The engine does this at startup, so this is for inspecting or repairing a
    database without one running.
    """
    from . import db

    db.migrate()
    typer.echo(f"migrated {config.DB_PATH}")


@app.command()
def facets(limit: int = 0, redo: bool = False) -> None:
    """Generate facets for every eligible artifact. Slow, resumable."""
    _echo(_call("POST", "/facets", json={"limit": limit or None, "redo": redo}, timeout=None))


@app.command()
def index() -> None:
    """Embed chunks and facets into the vector store."""
    _echo(_call("POST", "/index", timeout=None))


@app.command()
def search(query: str, limit: int = 10) -> None:
    """Find artifacts. Hybrid dense plus sparse, no model calls."""
    result = _call("GET", "/search", params={"q": query, "limit": limit})
    for hit in result["hits"]:
        typer.echo(f"  {hit['score']:.3f}  {hit['title'][:44]:<46} {hit['snippet'][:60]}")


@app.command()
def curate(lens: str, keep: int = 15, pool: int = 150, save: bool = False) -> None:
    """Build a room on a theme."""
    result = _call(
        "POST",
        "/curate",
        json={"lens": lens, "keep": keep, "pool": pool, "save": save},
        timeout=None,
    )
    exhibit = result.get("exhibit") or {}

    typer.secho(f"\n{exhibit.get('suggested_name', lens)}", fg=typer.colors.YELLOW, bold=True)
    typer.echo(
        f"{len(result['kept'])} artifacts  ·  {result['rejected']} rejected  ·  {result['considered']} considered"
    )

    if exhibit.get("through_line"):
        typer.echo(f"\n{exhibit['through_line']}\n")
    if exhibit.get("thin"):
        typer.secho(f"thin: {exhibit.get('thin_reason')}\n", fg=typer.colors.RED)

    for member in result["kept"]:
        typer.secho(f"  {member['title'][:52]}", fg=typer.colors.CYAN)
        typer.echo(f"    {member['placard']}")

    for group in exhibit.get("groupings", []):
        typer.secho(f"\n  {group['name']}", bold=True)
        typer.echo(f"    {group['claim']}")

    for tension in exhibit.get("tensions", []):
        typer.secho(f"\n  tension: {' vs '.join(tension['between'])}", fg=typer.colors.MAGENTA)
        typer.echo(f"    {tension['claim']}")

    if result.get("saved_id"):
        typer.echo(f"\nsaved as {result['saved_id']}")


@app.command()
def note(body: str = "") -> None:
    """Write a note. The body is markdown and stays editable."""
    _echo(_call("POST", "/notes", json={"body": body}))


@app.command()
def link(url: str) -> None:
    """Save a URL. Nothing is fetched."""
    _echo(_call("POST", "/capture/link", json={"url": url}))


@app.command()
def artifacts(limit: int = 20) -> None:
    """List artifacts, newest first."""
    result = _call("GET", "/artifacts", params={"limit": limit})
    typer.echo(f"{result['total']} artifacts")
    for a in result["items"]:
        flag = " [local-only]" if a["local_only"] else ""
        typer.echo(f"  {a['kind']:<6} {a['updated_at'][:10]}  {a['title'][:52]}{flag}")


@app.command()
def preview(artifact_id: str) -> None:
    """Fetch what a saved link turns out to be. One request, because you asked."""
    _echo(_call("POST", f"/artifacts/{artifact_id}/preview"))


@app.command()
def chat(question: str, chat_id: str = "") -> None:
    """Ask the collection something. Continues a chat if given one."""
    if chat_id:
        result = _call("POST", f"/chats/{chat_id}/messages", json={"text": question}, timeout=None)
    else:
        result = _call("POST", "/chats", json={"text": question}, timeout=None)

    answer = result["messages"][-1]
    typer.secho(f"\n{result['chat']['title']}", fg=typer.colors.YELLOW, bold=True)
    typer.echo(f"{result['chat']['id']}\n")
    typer.echo(answer["text"])

    if answer["cited"]:
        typer.echo("")
        for source in answer["cited"]:
            typer.secho(f"  {source['title'][:60]}", fg=typer.colors.CYAN)
    elif not answer["grounded"]:
        typer.secho("\n  nothing in the collection carried this", fg=typer.colors.RED)

    if result["topics"]:
        typer.echo("\ntopics: " + ", ".join(t["topic"] for t in result["topics"]))


@app.command()
def chats(limit: int = 20) -> None:
    """List conversations, newest first."""
    result = _call("GET", "/chats", params={"limit": limit})
    for item in result["items"]:
        typer.secho(f"  {item['title'][:52]:<54}{item['id']}", fg=typer.colors.CYAN)
        if item["topics"]:
            typer.echo("    " + " · ".join(item["topics"]))


@app.command()
def chunk() -> None:
    """Rebuild chunks from note bodies."""
    _echo(_call("POST", "/chunk"))


@app.command("facet-gate")
def facet_gate() -> None:
    """Decide which artifacts never get facets."""
    _echo(_call("POST", "/facet-gate"))


# ---------------------------------------------------------------------------
# Test corpus commands (eval harness)
# ---------------------------------------------------------------------------

CORPUS_DIR = Path(__file__).resolve().parent.parent.parent / "evals" / "corpus"
MANIFEST_PATH = CORPUS_DIR / "MANIFEST.json"

test_corpus_app = typer.Typer(help="Manage the synthetic test corpus for search evaluation.")
app.add_typer(test_corpus_app, name="test-corpus")


@test_corpus_app.command()
def verify() -> None:
    """Check generated files against MANIFEST.json.

    Exits non-zero and prints every violation if any assertion fails.
    """
    if not MANIFEST_PATH.exists():
        typer.secho(f"manifest not found at {MANIFEST_PATH}", fg=typer.colors.RED)
        raise typer.Exit(1)
    if not CORPUS_DIR.exists():
        typer.secho(f"corpus dir not found at {CORPUS_DIR}", fg=typer.colors.RED)
        raise typer.Exit(1)

    try:
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        typer.secho(f"could not read manifest: {e}", fg=typer.colors.RED)
        raise typer.Exit(1) from e

    artifacts = manifest["artifacts"]
    violations: list[str] = []

    # --- File count ---
    if len(artifacts) != 50:
        violations.append(f"expected 50 artifacts in manifest, got {len(artifacts)}")

    # --- Every manifest entry has a matching file ---
    for entry in artifacts:
        fp = CORPUS_DIR / entry["filename"]
        if not fp.exists():
            violations.append(f"missing file: {entry['filename']}")

    # --- Every file is in the manifest ---
    manifest_filenames = {e["filename"] for e in artifacts}
    for fp in CORPUS_DIR.iterdir():
        if fp.suffix != ".md":
            continue
        if fp.name not in manifest_filenames:
            violations.append(f"unregistered file: {fp.name}")

    # --- Category checks ---
    for entry in artifacts:
        fp = CORPUS_DIR / entry["filename"]
        if not fp.exists():
            continue
        content = fp.read_text(encoding="utf-8")
        parts = content.split("\n\n", 1)
        title_line = parts[0] if parts else ""
        body = parts[1] if len(parts) > 1 else ""

        cat = entry["category"]

        if cat == "title-only":
            name = entry.get("name", "")
            if not name:
                violations.append(f"{entry['id']}: missing name in manifest")
                continue
            name_parts = name.split()
            in_title = any(p in title_line for p in name_parts)
            in_body = any(p in body for p in name_parts)
            if not in_title:
                violations.append(f"{entry['id']}: name '{name}' not in title")
            if in_body:
                violations.append(f"{entry['id']}: name '{name}' found in body")

        elif cat == "paraphrase":
            term = entry.get("forbidden_term", "")
            if not term:
                violations.append(f"{entry['id']}: missing forbidden_term in manifest")
                continue
            if term in content.lower():
                violations.append(f"{entry['id']}: forbidden term '{term}' found in content")

        elif cat == "rare-string":
            rare = entry.get("rare_string", "")
            if not rare:
                violations.append(f"{entry['id']}: missing rare_string in manifest")
                continue
            if rare not in content:
                violations.append(f"{entry['id']}: rare string '{rare}' not found")

        elif cat == "long":
            wc = len(content.split())
            if wc < 5000:
                violations.append(f"{entry['id']}: {wc} words, need >=5000")

        elif cat == "short":
            wc = len(content.split())
            if wc > 30:
                violations.append(f"{entry['id']}: {wc} words, need <=30")

    # --- Rare string uniqueness ---
    rare_string_artifacts = [e for e in artifacts if e["category"] == "rare-string"]
    for rs_entry in rare_string_artifacts:
        rare = rs_entry["rare_string"]
        for other in artifacts:
            if other["id"] == rs_entry["id"]:
                continue
            fp = CORPUS_DIR / other["filename"]
            if fp.exists() and rare in fp.read_text(encoding="utf-8"):
                violations.append(
                    f"rare string '{rare}' appears in {other['id']} "
                    f"(should be only in {rs_entry['id']})"
                )

    if violations:
        typer.secho(f"{len(violations)} violation(s):", fg=typer.colors.RED, bold=True)
        for v in violations:
            typer.secho(f"  {v}", fg=typer.colors.RED)
        raise typer.Exit(1)
    else:
        typer.secho("All checks passed.", fg=typer.colors.GREEN)


@test_corpus_app.command()
def load() -> None:
    """Ingest evals/corpus/ into a separate test database.

    Idempotent: running twice yields 50 artifacts, not 100.
    The test database is at evals/test-data/ and is completely separate
    from the real library.
    """
    if not CORPUS_DIR.exists():
        typer.secho(f"corpus dir not found at {CORPUS_DIR}", fg=typer.colors.RED)
        raise typer.Exit(1)
    if not MANIFEST_PATH.exists():
        typer.secho(f"manifest not found at {MANIFEST_PATH}", fg=typer.colors.RED)
        raise typer.Exit(1)

    # First verify the corpus is clean
    try:
        _run_verify()
    except SystemExit as e:
        if e.code != 0:
            typer.secho("corpus verification failed; refusing to load", fg=typer.colors.RED)
            raise typer.Exit(1) from e

    test_dir = CORPUS_DIR.parent / "test-data"
    test_dir.mkdir(parents=True, exist_ok=True)
    test_db = test_dir / "enqueue.db"

    # Check if already loaded (use raw sqlite3 for the test DB)
    if test_db.exists():
        try:
            import sqlite3

            conn = sqlite3.connect(str(test_db))
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute("SELECT COUNT(*) AS n FROM artifacts").fetchone()
                if row and row["n"] == 50:
                    typer.secho(
                        f"test database at {test_db} already has {row['n']} artifacts, "
                        "nothing to do",
                        fg=typer.colors.GREEN,
                    )
                    return
            except Exception:
                pass
            finally:
                conn.close()
        except Exception:
            pass

    # Load the corpus into the test database
    try:
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        typer.secho(f"could not read manifest: {e}", fg=typer.colors.RED)
        raise typer.Exit(1) from e

    _load_corpus_into_db(test_dir, manifest["artifacts"])

    typer.secho(f"Loaded test corpus into {test_dir}", fg=typer.colors.GREEN)


@test_corpus_app.command()
def reset() -> None:
    """Delete the test database entirely."""
    test_dir = CORPUS_DIR.parent / "test-data"
    if not test_dir.exists():
        typer.secho("no test database to reset", fg=typer.colors.YELLOW)
        return

    import shutil

    try:
        shutil.rmtree(test_dir)
    except OSError as e:
        typer.secho(f"could not remove test database: {e}", fg=typer.colors.RED)
        raise typer.Exit(1) from e
    typer.secho(f"removed {test_dir}", fg=typer.colors.GREEN)


def _run_verify() -> None:
    """Programmatic verify for use by load."""
    try:
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(1) from e
    artifacts = manifest["artifacts"]

    if len(artifacts) != 50:
        raise SystemExit(1)
    for entry in artifacts:
        fp = CORPUS_DIR / entry["filename"]
        if not fp.exists():
            raise SystemExit(1)

        try:
            content = fp.read_text(encoding="utf-8")
        except OSError as e:
            raise SystemExit(1) from e
        parts = content.split("\n\n", 1)
        body = parts[1] if len(parts) > 1 else ""

        cat = entry["category"]
        if cat == "title-only":
            name = entry.get("name", "")
            name_parts = name.split()
            if any(p in body for p in name_parts):
                raise SystemExit(1)
        elif cat == "paraphrase":
            term = entry.get("forbidden_term", "")
            if term and term in content.lower():
                raise SystemExit(1)
        elif cat == "rare-string":
            rare = entry.get("rare_string", "")
            if rare and rare not in content:
                raise SystemExit(1)
        elif cat == "long":
            if len(content.split()) < 5000:
                raise SystemExit(1)
        elif cat == "short":
            if len(content.split()) > 30:
                raise SystemExit(1)


def _load_corpus_into_db(test_dir: Path, entries: list[dict]) -> None:
    """Load corpus artifacts, chunk them, and index into an isolated Qdrant.

    The test database and Qdrant index live under test_dir, completely separate
    from the real library. Returns (artifact_count, chunk_count).
    """
    from . import config as cfg
    from . import db as db_mod
    from .ingest.chunk import chunk_artifact
    from .index.qdrant import index_chunks, ensure_collections

    test_db = test_dir / "enqueue.db"
    test_qdrant = test_dir / "qdrant"
    test_blobs = test_dir / "blobs"
    test_blobs.mkdir(parents=True, exist_ok=True)
    test_qdrant.mkdir(parents=True, exist_ok=True)

    # Point config to the test directory
    originals = {
        "DATA_DIR": cfg.DATA_DIR,
        "DB_PATH": cfg.DB_PATH,
        "BLOB_DIR": cfg.BLOB_DIR,
        "QDRANT_PATH": cfg.QDRANT_PATH,
    }

    cfg.DATA_DIR = test_dir
    cfg.DB_PATH = test_db
    cfg.BLOB_DIR = test_blobs
    cfg.QDRANT_PATH = test_qdrant

    try:
        db_mod.reset_migration_state()
        db_mod.get_conn().close()  # triggers migrate on the test DB

        # Insert artifacts via the app's db module
        conn = db_mod.get_conn()
        try:
            for entry in entries:
                fp = CORPUS_DIR / entry["filename"]
                content = fp.read_text(encoding="utf-8")
                parts = content.split("\n\n", 1)
                title = parts[0].lstrip("# ").strip() if parts else ""
                body = parts[1] if len(parts) > 1 else ""

                conn.execute(
                    "INSERT OR IGNORE INTO artifacts "
                    "(id, kind, title, body, content_hash, status, "
                    " created_at, updated_at) "
                    "VALUES (?, 'note', ?, ?, ?, 'ok', "
                    " datetime('now'), datetime('now'))",
                    (entry["id"], title, body, entry["id"] + "_hash"),
                )
            conn.commit()
        finally:
            conn.close()

        # Chunk each artifact
        chunk_count = 0
        for entry in entries:
            conn = db_mod.get_conn()
            try:
                made = chunk_artifact(conn, entry["id"])
                chunk_count += made
                conn.commit()
            finally:
                conn.close()

        # Index chunks into the test Qdrant
        ensure_collections()
        idx_result = index_chunks()

        typer.echo(
            f"  artifacts: {len(entries)}  chunks: {chunk_count}  "
            f"indexed: {idx_result.get('indexed', '?')}"
        )
    finally:
        for attr, val in originals.items():
            setattr(cfg, attr, val)
        db_mod.reset_migration_state()


# ---------------------------------------------------------------------------
# Eval command
# ---------------------------------------------------------------------------

EVALS_DIR = Path(__file__).resolve().parent.parent.parent / "evals"
QUERIES_PATH = EVALS_DIR / "queries.yaml"
RESULTS_DIR = EVALS_DIR / "results"


@app.command()
def eval(
    json_path: str = "",
    engine: str = "qdrant",
    ablation: bool = False,
) -> None:
    """Run every query from evals/queries.yaml against the test library.

    Runs locally against the isolated test database + test Qdrant index.
    Does not require the engine to be running.
    """
    import math
    import time

    import yaml as _yaml

    if not QUERIES_PATH.exists():
        typer.secho(f"queries not found at {QUERIES_PATH}", fg=typer.colors.RED)
        raise typer.Exit(1)

    try:
        with open(QUERIES_PATH, encoding="utf-8") as f:
            raw = _yaml.safe_load(f)
    except (OSError, _yaml.YAMLError) as e:
        typer.secho(f"could not read queries: {e}", fg=typer.colors.RED)
        raise typer.Exit(1) from e
    queries = raw["queries"]
    typer.echo(f"Loaded {len(queries)} queries from {QUERIES_PATH}")

    # Determine test data paths
    test_dir = EVALS_DIR / "test-data"
    test_db = test_dir / "enqueue.db"
    test_qdrant = test_dir / "qdrant"

    if not test_db.exists():
        typer.secho(
            f"test database not found at {test_db}\nrun: enq test-corpus load",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    if not test_qdrant.exists():
        typer.secho(
            f"test Qdrant index not found at {test_qdrant}\nrun: enq test-corpus load",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    # Point config at the test data
    from . import config as cfg
    from .index import qdrant as qd

    originals = {"DB_PATH": cfg.DB_PATH, "QDRANT_PATH": cfg.QDRANT_PATH}
    cfg.DB_PATH = test_db
    cfg.QDRANT_PATH = test_qdrant

    # Clear the cached Qdrant client so it re-opens against the test path
    qd.client.cache_clear()

    def _run_search(text: str, limit: int = 10, mode: str = "hybrid") -> list[dict]:
        """Run search against the test Qdrant, return deduplicated artifact IDs."""
        if mode == "dense":
            hits = qd.search_dense(qd.CHUNKS, text, limit=limit * 3)
        else:
            hits = qd.search(qd.CHUNKS, text, limit=limit * 3)
        # Deduplicate by artifact_id, keep lowest distance
        seen: dict[str, float] = {}
        for h in hits:
            aid = h["artifact_id"]
            if aid not in seen or h["score"] > seen[aid]:
                seen[aid] = h["score"]
        ranked = sorted(seen.items(), key=lambda x: -x[1])[:limit]
        return [{"id": aid, "score": round(score, 4)} for aid, score in ranked]

    def _evaluate(queries_list: list[dict], mode: str) -> list[dict]:
        """Run queries with a given mode and return results."""
        out: list[dict] = []
        for q in queries_list:
            t0 = time.time()
            try:
                hits = _run_search(q["query"], limit=10, mode=mode)
            except Exception as exc:
                out.append(
                    {
                        "id": q["id"],
                        "query": q["query"],
                        "category": q["category"],
                        "pass": False,
                        "rank": None,
                        "error": str(exc),
                        "latency": round(time.time() - t0, 3),
                    }
                )
                continue

            elapsed = time.time() - t0
            hit_ids = [h["id"] for h in hits]
            expected = q["expect_artifact_ids"]

            if not expected:
                passed = len(hit_ids) == 0
                out.append(
                    {
                        "id": q["id"],
                        "query": q["query"],
                        "category": q["category"],
                        "pass": passed,
                        "rank": None,
                        "latency": round(elapsed, 3),
                        "n_hits": len(hit_ids),
                        "top_hit_id": hit_ids[0] if hit_ids else None,
                    }
                )
                continue

            best_rank: int | None = None
            for rank, hid in enumerate(hit_ids, start=1):
                if hid in expected:
                    best_rank = rank
                    break

            passed = best_rank is not None and best_rank <= 10
            out.append(
                {
                    "id": q["id"],
                    "query": q["query"],
                    "category": q["category"],
                    "pass": passed,
                    "rank": best_rank,
                    "latency": round(elapsed, 3),
                    "n_hits": len(hit_ids),
                    "top_hit_id": hit_ids[0] if hit_ids else None,
                }
            )
        return out

    if ablation:
        modes = [("hybrid", engine), ("dense", f"{engine}-dense")]
    else:
        modes = [("hybrid", engine)]

    all_results: dict[str, list[dict]] = {}

    for mode, label in modes:
        results = _evaluate(queries, mode)
        all_results[label] = results

        passed_qs = [r for r in results if r.get("pass")]
        total = len(results)
        n_pass = len(passed_qs)

        recall_at_1 = sum(1 for r in passed_qs if r.get("rank") == 1) / total if total else 0.0
        recall_at_10 = len(passed_qs) / total if total else 0.0

        non_zero_ranks = [
            r["rank"] for r in results if r.get("rank") is not None and r["category"] != "nothing"
        ]
        mrr = sum(1.0 / r for r in non_zero_ranks) / len(non_zero_ranks) if non_zero_ranks else 0.0

        nothing_qs = [r for r in results if r["category"] == "nothing"]
        nothing_pass = sum(1 for r in nothing_qs if r.get("pass"))

        latencies = [r.get("latency", 0) for r in results if r.get("latency")]
        sorted_lats = sorted(latencies)
        p50 = sorted_lats[len(sorted_lats) // 2] if sorted_lats else 0.0
        p95 = 0.0
        if sorted_lats:
            try:
                idx = int(math.ceil(0.95 * len(sorted_lats))) - 1
                p95 = sorted_lats[idx]
            except IndexError:
                p95 = sorted_lats[-1]

        typer.echo("")
        typer.secho(f"=== Mode: {label} ===", bold=True)
        typer.secho(f"{'PASS':>4}  {'Rank':>4}  {'Lat':>5}  Query", bold=True)
        typer.echo("-" * 60)
        for r in results:
            status = typer.colors.GREEN if r.get("pass") else typer.colors.RED
            rank_str = str(r.get("rank", "-")) if r.get("rank") is not None else "-"
            lat_str = f"{r.get('latency', 0):.2f}s"
            typer.secho(
                f"{'PASS' if r.get('pass') else 'FAIL':>4}  "
                f"{rank_str:>4}  {lat_str:>5}  {r['id']}",
                fg=status,
            )

        typer.echo("")
        typer.secho(f"--- Summary [{label}] ---", bold=True)
        typer.echo(f"  Total queries:    {total}")
        typer.echo(f"  Pass:             {n_pass}")
        typer.echo(f"  Fail:             {total - n_pass}")
        typer.echo(f"  Recall@1:         {recall_at_1:.3f}")
        typer.echo(f"  Recall@10:        {recall_at_10:.3f}")
        typer.echo(f"  MRR (non-zero):   {mrr:.3f}")
        typer.echo(f"  Nothing-OK:       {nothing_pass}/{len(nothing_qs)}")
        typer.echo(f"  p50 latency:      {p50:.3f}s")
        typer.echo(f"  p95 latency:      {p95:.3f}s")

    # Save JSON if requested
    if json_path:
        out = Path(json_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        summary = {"engine": engine, "modes": {}}
        for label, results in all_results.items():
            passed_qs = [r for r in results if r.get("pass")]
            total = len(results)
            n_recall_1 = sum(1 for r in passed_qs if r.get("rank") == 1)
            recall_at_1 = n_recall_1 / total if total else 0.0
            recall_at_10 = len(passed_qs) / total if total else 0.0
            non_zero_ranks = [
                r["rank"]
                for r in results
                if r.get("rank") is not None and r["category"] != "nothing"
            ]
            mrr = (
                sum(1.0 / r for r in non_zero_ranks) / len(non_zero_ranks)
                if non_zero_ranks
                else 0.0
            )
            nothing_qs = [r for r in results if r["category"] == "nothing"]
            nothing_pass = sum(1 for r in nothing_qs if r.get("pass"))
            latencies = [r.get("latency", 0) for r in results if r.get("latency")]
            sorted_lats = sorted(latencies)
            p50 = sorted_lats[len(sorted_lats) // 2] if sorted_lats else 0.0
            p95 = 0.0
            if sorted_lats:
                try:
                    idx = int(math.ceil(0.95 * len(sorted_lats))) - 1
                    p95 = sorted_lats[idx]
                except IndexError:
                    p95 = sorted_lats[-1]

            summary["modes"][label] = {
                "total": total,
                "pass": len(passed_qs),
                "fail": total - len(passed_qs),
                "recall@1": round(recall_at_1, 4),
                "recall@10": round(recall_at_10, 4),
                "MRR": round(mrr, 4),
                "nothing_ok": nothing_pass,
                "nothing_total": len(nothing_qs),
                "p50_latency": round(p50, 3),
                "p95_latency": round(p95, 3),
                "results": results,
            }
        out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        typer.echo(f"\nWrote results to {out}")

    # Restore config
    for attr, val in originals.items():
        setattr(cfg, attr, val)
    qd.client.cache_clear()


if __name__ == "__main__":
    app()
