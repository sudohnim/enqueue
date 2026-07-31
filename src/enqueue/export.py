"""Export: the library as plain files, no software required to read it back.

The promise that nothing expires is only worth keeping if the library can leave
this machine. Every artifact becomes a markdown file, every capture keeps its
bytes next to it in `files/`, every exhibit becomes its own file, and the only
tool the output needs is a text editor.

Idempotent by content: a file is rewritten only when its rendered text changed
and a capture is copied only when its bytes differ, so re-running an export
touches nothing. Files that a previous export wrote and that no longer exist in
the library are removed, keeping the directory an accurate mirror.

The manifest is bookkeeping, not content: it maps artifact ids to files so that
`verify` can answer "is every non-deleted artifact in the output?" without a
database, and so a stale-file prune knows exactly which files it created.
"""

from __future__ import annotations

import filecmp
import json
import re
import shutil
from pathlib import Path

from . import config, db

MANIFEST = "manifest.json"


def _slug(text: str) -> str:
    """A filesystem-safe fragment from a title."""
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (text or "artifact")[:60]


def _id8(artifact_id: str) -> str:
    return artifact_id[:8]


def _sanitize_filename(name: str) -> str:
    name = Path(name).name  # strip any path components
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name)[:120] or "file"


def _put(target: Path, text: str) -> bool:
    """Write only when the content changed. Returns True when written."""
    try:
        if target.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    target.write_text(text, encoding="utf-8")
    return True


def _copy_blob(src: Path, dst: Path) -> bool:
    """Copy only when the bytes differ. Returns True when copied."""
    if dst.exists() and filecmp.cmp(src, dst, shallow=True):
        return False
    shutil.copy2(src, dst)
    return True


def _read_manifest(root: Path) -> dict | None:
    path = root / MANIFEST
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _render_artifact(row: dict, notes: list[dict], page0: str | None, copy_rel: str | None) -> str:
    parts = [f"# {row['title']}", ""]
    meta = [f"Saved: {row['created_at']}", f"Kind: {row['kind']}"]
    if row.get("source_url"):
        meta.append(f"Source: {row['source_url']}")
    if copy_rel:
        meta.append(f"File: {copy_rel}")
    parts.append(" · ".join(meta))
    parts.append("")

    if row["kind"] == "note" and row.get("body"):
        parts.append(row["body"].rstrip())
        parts.append("")
    elif row["kind"] == "link" and page0:
        parts.append("## Saved text")
        parts.append("")
        parts.append(page0.rstrip())
        parts.append("")

    if notes:
        superseded = {n["supersedes_id"] for n in notes if n["supersedes_id"]}
        parts.append("## Notes")
        parts.append("")
        for entry in notes:
            suffix = " (superseded)" if entry["id"] in superseded else ""
            parts.append(f"- {entry['created_at']}: {entry['text']}{suffix}")
        parts.append("")

    return "\n".join(parts) + "\n"


def _render_exhibit(row: dict, members: list[dict], manifest: dict) -> str:
    parts = [f"# {row['name']}", "", f"Theme: {row['theme']}"]
    if row.get("through_line"):
        parts.append(f"Through line: {row['through_line']}")
    if row.get("thin"):
        parts.append(f"Thin: {row.get('thin_reason') or 'yes'}")
    parts.append("")
    parts.append("## Members")
    parts.append("")
    for number, member in enumerate(members, 1):
        entry = manifest["artifacts"].get(member["artifact_id"])
        parts.append(f"### {number}. {member['title']}")
        if entry:
            parts.append("")
            parts.append(f"[Open the artifact]({entry['file']})")
        parts.append("")
        parts.append(member["placard"])
        parts.append("")
        parts.append(f"- Strength: {member['strength']}")
        if member.get("evidence"):
            parts.append(f"- Evidence: {member['evidence']}")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _render_readme(artifacts: list[dict], exhibits: list[dict], manifest: dict) -> str:
    parts = [
        "# Enqueue library export",
        "",
        f"{len(artifacts)} artifacts, {len(exhibits)} exhibits.",
        "",
        "Everything here is plain text: the markdown files are the library and the",
        "`files/` directory holds the original captures. No database, key, or",
        "enqueue-specific software is needed to read any of it.",
        "",
    ]
    if artifacts:
        parts.append("## Artifacts")
        parts.append("")
        for row in artifacts:
            entry = manifest["artifacts"][row["id"]]
            parts.append(f"- [{row['title']}]({entry['file']}) ({row['kind']})")
        parts.append("")
    if exhibits:
        parts.append("## Exhibits")
        parts.append("")
        for row in exhibits:
            entry = manifest["exhibits"][row["id"]]
            parts.append(f"- [{row['name']}]({entry['file']}) ({row['theme']})")
        parts.append("")
    return "\n".join(parts)


def _prune_stale(root: Path, previous: dict | None, referenced: set[str]) -> list[str]:
    """Remove files a previous export wrote that are no longer part of the library."""
    if not previous:
        return []
    rels: set[str] = set()
    for entry in previous.get("artifacts", {}).values():
        rels.add(entry["file"])
        if entry.get("copy"):
            rels.add(entry["copy"])
    rels |= {entry["file"] for entry in previous.get("exhibits", {}).values()}

    pruned = []
    for rel in sorted(rels - referenced):
        try:
            (root / rel).unlink()
            pruned.append(rel)
        except OSError:
            pass
    return pruned


def export(directory: str | Path) -> dict:
    """Write the whole library as plain files. Idempotent; returns a summary."""
    root = Path(directory)
    artifacts_dir = root / "artifacts"
    files_dir = root / "files"
    exhibits_dir = root / "exhibits"
    for target in (artifacts_dir, files_dir, exhibits_dir):
        target.mkdir(parents=True, exist_ok=True)

    conn = db.get_conn()
    try:
        artifacts = conn.execute(
            "SELECT * FROM artifacts WHERE deleted_at IS NULL ORDER BY created_at, id"
        ).fetchall()
        annotations = conn.execute(
            "SELECT id, artifact_id, supersedes_id, text, created_at FROM annotations"
            " ORDER BY artifact_id, created_at, id"
        ).fetchall()
        exhibits = conn.execute("SELECT * FROM exhibits ORDER BY created_at, id").fetchall()
        members = conn.execute(
            "SELECT m.exhibit_id, m.artifact_id, m.placard, m.evidence, m.strength,"
            " m.rank, m.origin, a.title, a.kind FROM exhibit_members m"
            " JOIN artifacts a ON a.id = m.artifact_id"
            " WHERE m.ejected_at IS NULL ORDER BY m.exhibit_id, m.rank"
        ).fetchall()
        page0 = {
            r["artifact_id"]: r["text"]
            for r in conn.execute("SELECT artifact_id, text FROM page_text WHERE page = 0")
        }
    finally:
        conn.close()

    notes_by_artifact: dict[str, list[dict]] = {}
    for entry in annotations:
        notes_by_artifact.setdefault(entry["artifact_id"], []).append(dict(entry))

    previous = _read_manifest(root)
    manifest: dict = {"version": 1, "artifacts": {}, "exhibits": {}}
    written: list[str] = []
    unchanged: list[str] = []
    copied: list[str] = []
    missing_blobs: list[str] = []
    referenced: set[str] = set()

    for row in artifacts:
        aid = row["id"]
        rel = f"artifacts/{_slug(row['title'])}-{_id8(aid)}.md"
        copy_rel = None
        if row["kind"] in ("pdf", "image", "file"):
            copy_rel = f"files/{_id8(aid)}-{_sanitize_filename(row['filename'] or row['title'])}"

        text = _render_artifact(dict(row), notes_by_artifact.get(aid, []), page0.get(aid), copy_rel)
        if _put(root / rel, text):
            written.append(rel)
        else:
            unchanged.append(rel)
        referenced.add(rel)
        manifest["artifacts"][aid] = {"file": rel, "kind": row["kind"], "title": row["title"]}

        if copy_rel:
            blob = config.BLOB_DIR / row["content_hash"]
            if blob.exists():
                if _copy_blob(blob, root / copy_rel):
                    copied.append(copy_rel)
                referenced.add(copy_rel)
                manifest["artifacts"][aid]["copy"] = copy_rel
            else:
                missing_blobs.append(aid)

    for row in exhibits:
        eid = row["id"]
        rel = f"exhibits/{_slug(row['name'])}-{_id8(eid)}.md"
        text = _render_exhibit(
            dict(row),
            [dict(m) for m in members if m["exhibit_id"] == eid],
            manifest,
        )
        if _put(root / rel, text):
            written.append(rel)
        else:
            unchanged.append(rel)
        referenced.add(rel)
        manifest["exhibits"][eid] = {"file": rel, "name": row["name"]}

    readme = _render_readme([dict(r) for r in artifacts], [dict(r) for r in exhibits], manifest)
    if _put(root / "README.md", readme):
        written.append("README.md")
    else:
        unchanged.append("README.md")

    manifest_text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    if _put(root / MANIFEST, manifest_text):
        written.append(MANIFEST)
    else:
        unchanged.append(MANIFEST)

    pruned = _prune_stale(root, previous, referenced)

    return {
        "artifacts": len(artifacts),
        "exhibits": len(exhibits),
        "written": written,
        "unchanged": unchanged,
        "copied": copied,
        "missing_blobs": missing_blobs,
        "pruned": pruned,
        "directory": str(root),
    }


def verify(directory: str | Path) -> dict:
    """Check that every non-deleted artifact appears in the existing output."""
    root = Path(directory)
    manifest = _read_manifest(root)
    if manifest is None:
        return {"ok": False, "reason": f"no {MANIFEST} in {root}; run `enq export` first"}

    conn = db.get_conn()
    try:
        expected = [
            r["id"] for r in conn.execute("SELECT id FROM artifacts WHERE deleted_at IS NULL")
        ]
        expected_exhibits = [r["id"] for r in conn.execute("SELECT id FROM exhibits")]
    finally:
        conn.close()

    missing = [aid for aid in expected if aid not in manifest.get("artifacts", {})]
    missing_exhibits = [eid for eid in expected_exhibits if eid not in manifest.get("exhibits", {})]
    gone = [
        aid
        for aid, entry in manifest.get("artifacts", {}).items()
        if not (root / entry["file"]).exists()
    ]

    ok = not missing and not missing_exhibits and not gone
    return {
        "ok": ok,
        "artifacts": len(expected),
        "exhibits": len(expected_exhibits),
        "missing": missing,
        "missing_exhibits": missing_exhibits,
        "missing_files": gone,
    }
