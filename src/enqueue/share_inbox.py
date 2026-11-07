"""Files what the macOS Share extension left in its inbox (desktop/share-extension).

The extension cannot reach the library: it is sandboxed and Enqueue may be closed. It
writes one `<id>.json` per share into the app group's Inbox folder, beside any files it
copied: `{"v": 1, "items": [{"url"} | {"text"} | {"file", "name"}], "title", "note"}`.
The engine files each share and then deletes it; a share it cannot read goes to
`Inbox/failed` instead of being tried forever.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
from pathlib import Path

from . import capture, notes

log = logging.getLogger(__name__)

GROUP = "572NMYL3ZG.com.sudohnim.enqueue"
EVERY_S = 3.0
WEB = re.compile(r"^https?://\S+$", re.I)


def folder() -> Path:
    override = os.getenv("ENQ_SHARE_INBOX")
    if override:
        return Path(override)
    return Path.home() / "Library" / "Group Containers" / GROUP / "Inbox"


def drain() -> int:
    """File every finished share in the inbox; returns how many were filed."""
    inbox = folder()
    if not inbox.is_dir():
        return 0
    filed = 0
    for share in sorted(inbox.glob("*.json")):
        try:
            data = json.loads(share.read_text("utf-8"))
            _file(inbox, data)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            log.warning("share %s could not be filed: %s", share.name, exc)
            _set_aside(inbox, share)
            continue
        for item in data.get("items", []):
            if item.get("file"):
                (inbox / Path(item["file"]).name).unlink(missing_ok=True)
        share.unlink(missing_ok=True)
        filed += 1
    return filed


def _file(inbox: Path, data: dict) -> None:
    title = (data.get("title") or "").strip() or None
    note = (data.get("note") or "").strip()
    items = data.get("items") or []
    if not items and note:
        notes.create(note)
        return
    for item in items:
        text = (item.get("text") or "").strip()
        if item.get("url") or WEB.match(text):
            saved = capture.link(item.get("url") or text, title=title)
        elif item.get("file"):
            path = inbox / Path(item["file"]).name
            saved = capture.upload(path.read_bytes(), item.get("name") or path.name)
        elif text:
            notes.create(text + (f"\n\n{note}" if note else ""))
            continue
        else:
            continue
        if note:
            notes.annotate(saved["id"], note)


def _set_aside(inbox: Path, share: Path) -> None:
    failed = inbox / "failed"
    failed.mkdir(exist_ok=True)
    shutil.move(str(share), failed / share.name)


def _loop() -> None:
    while True:
        try:
            drain()
        except Exception:  # noqa: BLE001 - the loop must outlive one bad share
            log.exception("share inbox")
        threading.Event().wait(EVERY_S)


_thread: threading.Thread | None = None


def start() -> None:
    """Watch the inbox (once). Called at engine startup."""
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_loop, name="share-inbox", daemon=True)
        _thread.start()
