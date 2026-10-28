"""CLI. A thin client over the engine API.

No command here touches the database directly. If the engine is not running, commands
that need it say so rather than reaching around the boundary.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import typer
import uvicorn
from httpx import ConnectError

from . import config

app = typer.Typer(add_completion=False, help="Enqueue: capture anything, organise it later.")


def _base_url() -> str:
    """Where the engine listens.

    The engine records its port in `DATA_DIR/port`, so the CLI finds it even when it is
    not on the default port. An explicit ENQ_API_PORT wins. With neither, 8787 is used.
    """
    import os

    if os.getenv("ENQ_API_PORT"):
        return config.API_URL
    try:
        port = (config.DATA_DIR / "port").read_text().strip()
    except OSError:
        return config.API_URL
    return f"http://{config.API_HOST}:{port}" if port.isdigit() else config.API_URL


def _call(method: str, path: str, **kwargs) -> dict:
    base = _base_url()
    try:
        response = httpx.request(
            method,
            f"{base}{path}",
            timeout=kwargs.pop("timeout", 600),
            **kwargs,
        )
    except ConnectError:
        typer.secho(
            f"engine is not running at {base}\nstart it with:  enq serve",
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
def doctor() -> None:
    """Index health: counts, embedding version, and index sync."""
    _echo(_call("GET", "/doctor"))


@app.command()
def backup(wait: bool = typer.Option(True, help="Wait for the backup to land.")) -> None:
    """Back the library up into the folder chosen in Settings (Proton Drive)."""
    import time

    before = (_call("GET", "/backup").get("last") or {}).get("at")
    _call("POST", "/backup")
    if not wait:
        typer.echo("backup started")
        return
    for _ in range(600):
        time.sleep(1)
        state = _call("GET", "/backup")
        latest = state.get("last") or {}
        if not state.get("running") and latest.get("at") != before:
            _echo(latest)
            return
    typer.echo("still running; check Settings > Storage")


@app.command()
def restore(
    source: str = typer.Argument(..., help="A backup folder, or one file in it."),
    kit: str = typer.Option(
        "", "--kit", help="The recovery kit, on a Mac without this library's key."
    ),
) -> None:
    """Put a backup in place as the library. Quit Enqueue first.

    Backups are encrypted with the library's key. On the Mac that made them they open
    as they are; on any other, the recovery kit opens them (asked for when needed).
    The current library is moved aside (never deleted); the search index is rebuilt
    on the next start. Like `migrate`, this works on the files directly, because the
    engine must not be running.
    """
    from . import backup as backups
    from . import datadir, libkey

    datadir.move_legacy()  # restore into the library's current home, not the old one
    try:
        try:
            _echo(backups.restore(source, kit=kit or None))
        except backups.Locked:
            typer.echo("This backup is locked with its library's key. Its recovery kit opens it.")
            entered = typer.prompt("Recovery kit", hide_input=True)
            _echo(backups.restore(source, kit=entered))
    except libkey.KitError as exc:
        typer.echo(f"not restored: {exc}", err=True)
        raise typer.Exit(1) from None
    except backups.BackupError as exc:
        typer.echo(f"not restored: {exc}", err=True)
        raise typer.Exit(1) from None
    typer.echo("Restored. Start Enqueue; it rebuilds the search index on first start.")


@app.command()
def migrate() -> None:
    """Bring the database to the newest revision.

    The engine does this at startup, so this is for inspecting or repairing a
    database without one running.
    """
    from . import datadir, db

    moved = datadir.move_legacy()
    if moved:
        typer.echo(moved)
    db.migrate()
    typer.echo(f"migrated {config.DB_PATH}")


@app.command()
def facets(limit: int = 0, redo: bool = False, stale_only: bool = False) -> None:
    """Queue the summary refresh on the engine's ingest worker; returns at once.

    By default every item whose summary is not current for the active summary model
    is re-summarized (the catch-up after a model switch); --redo re-summarizes
    everything. Progress shows in the Activity log and in `enq doctor`.
    """
    _echo(
        _call(
            "POST",
            "/facets",
            json={"limit": limit or None, "redo": redo, "stale_only": stale_only},
            timeout=None,
        )
    )


@app.command()
def index(
    images: bool = typer.Option(
        False,
        "--images",
        help="Re-queue every image for the vision describe step instead of rebuilding the vector index (K.11).",
    )
) -> None:
    """Rebuild the search index from the database.

    With --images, re-queue every image so the vision step describes the ones
    captured before it existed; the index rebuild itself is not run.
    """
    if images:
        _echo(_call("POST", "/reprocess-images", timeout=None))
    else:
        _echo(_call("POST", "/index", timeout=None))


@app.command()
def reprocess() -> None:
    """Re-read, re-chunk, and re-index every artifact.

    Nothing authored is touched. Re-fetches saved links that have a preview but
    no article body, which is how existing links pick up body indexing after
    this feature ships.
    """
    _echo(_call("POST", "/reprocess", timeout=None))


@app.command()
def export(directory: str, verify: bool = False) -> None:
    """Write the library as plain files. Re-runs update only what changed.

    --verify checks the existing output against the library instead of writing.
    """
    from . import export as export_mod

    target = Path(directory)
    if verify:
        result = export_mod.verify(target)
        if result["ok"]:
            typer.echo(f"export at {target} is complete: {result['artifacts']} artifacts")
        else:
            typer.secho(result["reason"], fg=typer.colors.RED)
            raise typer.Exit(1)
        return

    result = export_mod.export(target)
    typer.echo(f"exported {result['artifacts']} artifacts" f" to {target}")
    typer.echo(f"  wrote {len(result['written'])} files, {len(result['unchanged'])} unchanged")
    if result["copied"]:
        typer.echo(f"  copied {len(result['copied'])} capture files")
    if result["missing_blobs"]:
        typer.secho(
            f"  {len(result['missing_blobs'])} captures had no bytes on disk and were skipped",
            fg=typer.colors.YELLOW,
        )
    if result["pruned"]:
        typer.echo(f"  removed {len(result['pruned'])} stale files")


@app.command()
def search(query: str, limit: int = 10) -> None:
    """Find artifacts. Hybrid dense plus sparse, no model calls."""
    result = _call("GET", "/search", params={"q": query, "limit": limit})
    for hit in result["hits"]:
        typer.echo(f"  {hit['score']:.3f}  {hit['title'][:44]:<46} {hit['snippet'][:60]}")


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


@app.command()
def relay(
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        envvar="RELAY_HOST",
        help="Bind address. Default 127.0.0.1 (local only). Use 0.0.0.0 for LAN.",
    ),
    port: int = typer.Option(
        8788,
        "--port",
        envvar="RELAY_PORT",
        help="Port to listen on (default 8788).",
    ),
    data_dir: str = typer.Option(
        "./relay-data",
        "--data-dir",
        envvar="RELAY_DATA_DIR",
        help="Directory for relay object storage (default ./relay-data).",
    ),
    secret: str = typer.Option(
        "dev-secret",
        "--secret",
        envvar="RELAY_SECRET",
        help="The first library's secret (default dev-secret, local only). RELAY_SECRET.",
    ),
    admin_secret: str = typer.Option(
        "",
        "--admin-secret",
        envvar="RELAY_ADMIN_SECRET",
        help="Turns on the routes `enq relay-admin` uses to add and revoke libraries.",
    ),
) -> None:
    """Run the sync relay.

    The relay is a dumb byte store for end-to-end encrypted snapshots, one space per
    library. It authenticates with each library's Bearer secret and serves SSE for
    change notifications.
    """

    from .relay.app import create_relay

    if host not in ("127.0.0.1", "localhost", "::1"):
        weak = [
            name
            for name, value in (("RELAY_SECRET", secret), ("RELAY_ADMIN_SECRET", admin_secret))
            if value and (value == "dev-secret" or len(value) < 24)
        ]
        if secret == "dev-secret" or weak:
            typer.secho(
                f"refusing to serve on {host} with a weak secret ({', '.join(weak) or 'RELAY_SECRET'}):"
                ' use 24+ random characters, e.g. `python -c "import secrets;'
                ' print(secrets.token_urlsafe(32))"`',
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(1)

    app = create_relay(data_dir=Path(data_dir), secret=secret, admin_secret=admin_secret)
    typer.secho(f"Relay listening on {host}:{port}", fg=typer.colors.GREEN)
    typer.secho(f"Data directory: {data_dir}", fg=typer.colors.CYAN)
    if secret == "dev-secret":
        typer.secho("Bearer secret: dev-secret (local only)", fg=typer.colors.CYAN)
    if admin_secret:
        typer.secho("Library admin routes: on", fg=typer.colors.CYAN)
    uvicorn.run(app, host=host, port=port)


relay_admin = typer.Typer(
    help="Add, list and revoke the libraries a hosted relay serves (needs RELAY_ADMIN_SECRET)."
)
app.add_typer(relay_admin, name="relay-admin")


# Where `enq relay-admin` keeps the relay's admin secret on this Mac, so it never has
# to be typed or pasted; the relay address defaults to this library's own relay.
RELAY_ADMIN_SERVICE = "enqueue-relay-admin"


def _admin(method: str, path: str, url: str, admin_secret: str, **kw) -> httpx.Response:
    from . import keyring
    from . import settings as settings_mod

    url = url or (settings_mod.get("sync_relay_url") or "").strip()
    admin_secret = admin_secret or keyring._get(RELAY_ADMIN_SERVICE) or ""
    if not url or not admin_secret:
        typer.secho(
            "set --url/RELAY_URL and --admin-secret/RELAY_ADMIN_SECRET"
            f" (or keep the admin secret in the Keychain as {RELAY_ADMIN_SERVICE})",
            err=True,
        )
        raise typer.Exit(2)
    resp = httpx.request(
        method,
        url.rstrip("/") + path,
        headers={"Authorization": f"Bearer {admin_secret}"},
        timeout=30,
        **kw,
    )
    if resp.status_code >= 400:
        typer.secho(f"relay answered {resp.status_code}: {resp.text[:200]}", err=True)
        raise typer.Exit(1)
    return resp


_URL = typer.Option(
    "", "--url", envvar="RELAY_URL", help="The relay's https address (default: this library's)."
)


def settings_relay_url() -> str:
    from . import settings as settings_mod

    return (settings_mod.get("sync_relay_url") or "").strip()


_ADMIN = typer.Option("", "--admin-secret", envvar="RELAY_ADMIN_SECRET")


@relay_admin.command("add")
def relay_admin_add(
    label: str = typer.Argument(..., help="Whose library this is, for your own list."),
    quota_gb: float = typer.Option(0, "--quota-gb", help="Storage limit; 0 = the relay's."),
    url: str = _URL,
    admin_secret: str = _ADMIN,
) -> None:
    """Make a library and print its secret, once. Give it to its owner: in Enqueue,
    Settings > Sync > More options > relay address and secret."""
    body = {"label": label}
    if quota_gb:
        body["quota_bytes"] = int(quota_gb * 1024**3)
    made = _admin("POST", "/admin/libraries", url, admin_secret, json=body).json()
    typer.secho(f"library {made['id'][:12]} for {label}", fg=typer.colors.GREEN)
    typer.echo(f"relay:  {url or settings_relay_url()}")
    typer.echo(f"secret: {made['secret']}")
    typer.secho(
        "The relay keeps only a hash: this is the only time the secret is shown.",
        fg=typer.colors.YELLOW,
    )


@relay_admin.command("list")
def relay_admin_list(url: str = _URL, admin_secret: str = _ADMIN) -> None:
    """Every library: who it is for, how much it holds, whether it is revoked."""
    for lib in _admin("GET", "/admin/libraries", url, admin_secret).json()["libraries"]:
        state = "revoked" if lib["revoked_at"] else "live"
        mb = lib["used_bytes"] / 1024**2
        typer.echo(
            f"{lib['id'][:12]}  {state:7}  {mb:9.1f} MB  {lib['objects']:6} objects  {lib['label']}"
        )


@relay_admin.command("revoke")
def relay_admin_revoke(
    library: str = typer.Argument(..., help="The library id (the first characters will do)."),
    url: str = _URL,
    admin_secret: str = _ADMIN,
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask first."),
) -> None:
    """Refuse a library's secret from now on and delete everything it holds (for good)."""
    ids = [
        lib["id"]
        for lib in _admin("GET", "/admin/libraries", url, admin_secret).json()["libraries"]
        if lib["id"].startswith(library)
    ]
    if len(ids) != 1:
        typer.secho(f"{len(ids)} libraries match {library!r}; give more of the id", err=True)
        raise typer.Exit(1)
    if not yes and not typer.confirm(
        f"Revoke {ids[0][:12]} and delete every object it holds? This cannot be undone."
    ):
        raise typer.Exit(1)
    _admin("DELETE", f"/admin/libraries/{ids[0]}", url, admin_secret)
    typer.secho(f"revoked {ids[0][:12]}", fg=typer.colors.GREEN)


@relay_admin.command("pro")
def relay_admin_pro(
    email: str = typer.Argument(..., help="The account's sign-in email."),
    days: int = typer.Option(-1, "--days", help="How long; 0 ends Pro; omitted: for good."),
    url: str = _URL,
    admin_secret: str = _ADMIN,
) -> None:
    """Give an Enqueue sync account Pro (the owner, support) without a purchase."""
    body = {"email": email} if days < 0 else {"email": email, "days": days}
    made = _admin("PUT", "/admin/accounts/pro", url, admin_secret, json=body).json()
    for plan in made["accounts"]:
        typer.secho(f"account {plan['account_id'][:8]}: {plan['tier']}", fg=typer.colors.GREEN)


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
    """Programmatic verify for use by load: the real command, exit code mapped."""
    try:
        verify()
    except typer.Exit as e:
        if e.exit_code != 0:
            raise SystemExit(1) from e


def _load_corpus_into_db(test_dir: Path, entries: list[dict]) -> None:
    """Load corpus artifacts, chunk them, and index into an isolated store.

    The test database and search index live under test_dir, completely
    separate from the real library. Returns (artifact_count, chunk_count).
    """
    from . import config as cfg
    from . import db as db_mod
    from .index.store import get_store
    from .ingest.chunk import chunk_artifact

    test_db = test_dir / "enqueue.db"
    test_blobs = test_dir / "blobs"
    test_blobs.mkdir(parents=True, exist_ok=True)

    # Point config to the test directory
    originals = {
        "DATA_DIR": cfg.DATA_DIR,
        "DB_PATH": cfg.DB_PATH,
        "BLOB_DIR": cfg.BLOB_DIR,
    }

    cfg.DATA_DIR = test_dir
    cfg.DB_PATH = test_db
    cfg.BLOB_DIR = test_blobs

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

        # Index chunks into the isolated test store
        get_store.cache_clear()
        store = get_store()
        store.ensure()
        idx_result = store.upsert_chunks()
        store.write_embed_version()

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


@app.command()
def eval(
    json_path: str = "",
    engine: str = "sqlite-vec",
    ablation: bool = False,
) -> None:
    """Run every query from evals/queries.yaml against the test library.

    Runs locally against the isolated test database + test search index.
    Does not require the engine to be running. `engine` labels the report;
    after the cutover the only backend is sqlite-vec.
    """
    import math
    import time

    import yaml as _yaml

    if engine not in ("sqlite-vec", "sqlite_vec"):
        raise typer.BadParameter(
            f"unknown engine {engine!r}; only sqlite-vec exists after the cutover"
        )

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

    if not test_db.exists():
        typer.secho(
            f"test database not found at {test_db}\nrun: enq test-corpus load",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    # Point config at the test data. The engine is sqlite-vec; the index
    # lives inside the test database, so the readiness check below reads the
    # sqlite-vec table counts.
    from . import config as cfg
    from .index.store import get_store

    originals: dict[str, object] = {"DB_PATH": cfg.DB_PATH}
    cfg.DB_PATH = test_db
    originals["VECTOR_STORE"] = cfg.VECTOR_STORE
    cfg.VECTOR_STORE = "sqlite-vec"

    # A fresh store instance so it re-opens against the test path
    get_store.cache_clear()
    store = get_store()

    counts = store.counts()
    if counts.get("chunks") is None or counts.get("facets") is None:
        typer.secho(
            f"test index not found for engine {engine!r}\n"
            f"run: ENQ_VECTOR_STORE={engine} enq test-corpus load",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    def _run_search(text: str, limit: int = 10, mode: str = "hybrid") -> list[dict]:
        """Run search against the test index, return deduplicated artifact IDs."""
        if mode == "dense":
            hits = store.search_dense(store.CHUNKS, text, limit=limit * 3)
        elif mode == "rollup":
            # Q.4: drive the eval through the same /search rollup the wall and
            # the answer path use, including the Q.3 relevance floor. The
            # raw hybrid mode above measures retrieval quality without the
            # floor; rollup measures what a person actually sees. The store's
            # dense + keyword legs tolerate a missing table (upgraded DB or
            # minimal test corpus), so missing facets/entities gracefully
            # become no-hits rather than failing the whole call.
            from .retrieve.candidates import search_results

            # Fetch wider than `limit` so the floor's drop + dedupe still
            # gives `limit` survivors; matches the raw-hybrid mode's wider
            # prefetch window.
            rows = search_results(text, limit=limit * 3)
            return [{"id": h["artifact_id"], "score": h["score"]} for h in rows[:limit]]
        else:
            hits = store.search(store.CHUNKS, text, limit=limit * 3)
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
        modes = [("hybrid", engine), ("dense", f"{engine}-dense"), ("rollup", f"{engine}-rollup")]
    else:
        modes = [("hybrid", engine), ("rollup", f"{engine}-rollup")]

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
    get_store.cache_clear()


@app.command("eval-cross")
def eval_cross(json_path: str = "", generate_facets: bool = False) -> None:
    """Cross-domain search eval (evals/cross_domain.yaml): chunks, enriched, lifted.

    Runs locally against an isolated test library; the engine need not be running.
    `--generate-facets` writes fresh facets and entities (ingestion model) and query
    lifts (search model), which need an API key, and saves them as
    evals/cross_domain_facets.json.
    """
    from . import eval_cross as xd

    report = xd.run(generate=generate_facets)
    typer.echo(
        f"facets loaded: {report['facets_loaded']}  entities loaded: "
        f"{report['entities_loaded']}  lifts loaded: {report['lifts_loaded']}"
        f"  (pass = target in top {xd.PASS_RANK})"
    )
    modes = report["modes"]
    typer.secho(f"{'query':<24}" + "".join(f"{m:>10}" for m in modes), bold=True)
    for i, r in enumerate(modes["chunks"]["results"]):
        ranks = "".join(f"{modes[m]['results'][i]['rank'] or '-':>10}" for m in modes)
        typer.echo(f"{r['id']:<24}{ranks}")
    for label, mode in modes.items():
        typer.echo(f"{label:<8} pass {mode['pass']}/{mode['total']}  MRR {mode['MRR']:.3f}")
    if json_path:
        Path(json_path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        typer.echo(f"wrote {json_path}")


@app.command("eval-embedders")
def eval_embedders(models: str = "") -> None:
    """Compare embedding models on the main and cross-domain evals, each with a relevance
    floor fitted to its own scale. `--models a,b` limits the run; the default is every
    candidate in eval_embedders.CANDIDATES. Candidates download on first use.
    """
    from . import eval_embedders as ee

    chosen = [m.strip() for m in models.split(",") if m.strip()] or None
    unknown = [m for m in chosen or [] if m not in ee.CANDIDATES]
    if unknown:
        raise typer.BadParameter(f"not a candidate: {', '.join(unknown)}")
    rows = ee.run(chosen)
    typer.secho(
        f"{'model':<42}{'recall@10':>10}{'MRR':>7}{'nothing':>9}{'cross':>7}{'+facets':>9}"
        f"{'keep':>7}{'drop':>7}",
        bold=True,
    )
    for r in rows:
        typer.echo(
            f"{r['model']:<42}{r['recall@10']:>10}{r['MRR']:>7}{r['nothing_ok']:>9}"
            f"{r['cross_chunks']:>4}/{r['cross_total']:<2}{r['cross_enriched']:>6}/{r['cross_total']:<2}"
            f"{r['bars']['keep_above']:>7}{r['bars']['drop_below']:>7}"
        )


@app.command("eval-real")
def eval_real(update_baseline: bool = False) -> None:
    """Score the searches you actually ran (a search, then opening a result) against
    your library. Fails when a query that passed in the stored baseline fails now.
    `--update-baseline` stores this run as the new baseline.
    """
    report = _call("POST", "/eval/real", params={"update_baseline": update_baseline})
    if not report["total"]:
        typer.echo("No real searches yet: search, then open a result, and it becomes a case.")
        return
    for r in report["results"]:
        mark = "pass" if r["pass"] else "FAIL"
        typer.echo(f"{mark}  {r['rank'] or '-':>3}  {r['query']}")
    typer.echo(
        f"pass {report['pass']}/{report['total']} (top {report['pass_rank']})  "
        f"found in top 10 {report['found_in_top_10']}  MRR {report['MRR']:.3f}"
    )
    base = report["baseline"]
    if base:
        typer.echo(f"baseline pass {base['pass']}/{base['total']}  MRR {base['MRR']:.3f}")
    if update_baseline:
        typer.echo("stored this run as the baseline")
    elif report["lost"]:
        for q in report["lost"]:
            typer.secho(f"no longer passing: {q}", fg=typer.colors.RED)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
