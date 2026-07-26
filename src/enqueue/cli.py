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
            method, f"{config.API_URL}{path}", timeout=kwargs.pop("timeout", 600), **kwargs
        )
    except httpx.ConnectError:
        typer.secho(
            f"engine is not running at {config.API_URL}\nstart it with:  enq serve",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
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


@app.command("import-fabric")
def import_fabric(path: Path) -> None:
    """Import a Fabric export directory."""
    result = _call("POST", "/import/fabric", json={"path": str(path)})
    _echo(result)
    for name in result.get("with_secrets", []):
        typer.secho(
            f"  credential detected in {name}  (imported as text_only)", fg=typer.colors.YELLOW
        )


@app.command("import-bookmarks")
def import_bookmarks(path: Path) -> None:
    """Import a Netscape bookmarks file. Never fetches the URLs."""
    _echo(_call("POST", "/import/bookmarks", json={"path": str(path)}))


@app.command()
def chunk() -> None:
    """Rebuild chunks from blocks."""
    _echo(_call("POST", "/chunk"))


@app.command("facet-gate")
def facet_gate() -> None:
    """Decide which artifacts never get facets."""
    _echo(_call("POST", "/facet-gate"))


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
def artifacts(limit: int = 20, offset: int = 0) -> None:
    """List artifacts, newest first."""
    result = _call("GET", "/artifacts", params={"limit": limit, "offset": offset})
    typer.echo(f"{result['total']} artifacts")
    for item in result["items"]:
        flag = " [local-only]" if item["local_only"] else ""
        typer.echo(
            f"  {item['captured_at'][:10]}  {item['imported_from'] or '-':<22}"
            f"  {item['title'][:48]:<50}{flag}"
        )


@app.command()
def artifact(artifact_id: str) -> None:
    """Show one artifact in full."""
    _echo(_call("GET", f"/artifacts/{artifact_id}"))


@app.command()
def secrets() -> None:
    """List detected credentials. Values are redacted."""
    result = _call("GET", "/secrets")
    typer.echo(f"{result['count']} credential hits")
    for hit in result["hits"]:
        typer.secho(
            f"  {hit['imported_from']}  {hit['title']}  line {hit['line']}  {hit['kind']}",
            fg=typer.colors.YELLOW,
        )
        typer.echo(f"    {hit['excerpt']}")


if __name__ == "__main__":
    app()
