"""CLI. A thin client over the engine API.

No command here touches the database directly. If the engine is not running, commands
that need it say so rather than reaching around the boundary.
"""

from __future__ import annotations

import json

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


if __name__ == "__main__":
    app()
