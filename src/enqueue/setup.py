"""Where this installation stands: what is connected, what is left to set up, and which
settings have stopped doing anything.

Settings shows it (the "left to set up" cards, the marks on the tabs, the line in each
guide that says where you stand) and the eye answers questions about settings from it.
Everything here is read from what the engine already knows. No model call, no network
request, and nothing secret: a key is reported as present or absent, a relay as hosted
or on this machine, never the value.
"""

from __future__ import annotations

import ipaddress
from datetime import datetime, timezone
from urllib.parse import urlsplit

from . import backup, config, db, settings

DONE, TODO, WARN = "done", "todo", "warn"

# A backup older than this, with the library changed since, is worth a word.
BACKUP_STALE_DAYS = 3


def _backend() -> dict:
    name = settings.get("llm_backend")
    for b in settings.backends():
        if b["name"] == name:
            return b
    return {"name": name, "label": str(name), "local": True, "needs_key": False}


def _models() -> dict[str, str]:
    """The model each job runs on. Blank ingestion and search fall back to chat."""
    chat = str(settings.get("llm_model") or "")
    return {
        "chat": chat,
        "ingestion": str(settings.get("summarize_model") or "") or chat,
        "search": str(settings.get("search_model") or "") or chat,
        "images": str(settings.get("vision_model") or ""),
    }


def _has_session_header() -> bool:
    return "x-opencode-session" in str(settings.get("llm_headers") or "").lower()


def _relay_reach(url: str) -> str:
    """'hosted', or 'local' for an address only this machine or this network reaches."""
    host = (urlsplit(url).hostname or "").lower()
    if not host or host == "localhost" or host.endswith(".local"):
        return "local"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "hosted"
    return "local" if (ip.is_loopback or ip.is_private or ip.is_link_local) else "hosted"


def _days_since(stamp: str | None) -> float | None:
    try:
        then = datetime.fromisoformat(stamp or "")
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() / 86400


def _model_step(backend: dict, models: dict) -> dict:
    step = {"id": "model", "tab": "ai", "guide": "answers", "title": "Connect a model"}
    if backend.get("local"):
        return step | {
            "state": DONE,
            "title": "A model is connected",
            "detail": f"On this Mac, {models['chat']}",
        }
    if backend.get("needs_key") and not backend.get("key_present"):
        return step | {
            "state": TODO,
            "guide": "api-key",
            "detail": f"{backend['label']} needs an API key",
        }
    if backend["name"] == "opencode-go" and not _has_session_header():
        return step | {
            "state": TODO,
            "detail": "OpenCode Go needs a session header before it answers",
        }
    return step | {
        "state": DONE,
        "title": "A model is connected",
        "detail": f"{backend['label']}, {models['chat']}",
    }


def _backup_step() -> dict:
    step = {"id": "backup", "tab": "storage", "guide": "backups", "title": "Back up your library"}
    target = backup.configured_dir()
    if target is None:
        return step | {"state": TODO, "detail": "No folder chosen"}
    if not target.parent.exists():
        return step | {"state": WARN, "detail": "The backup folder cannot be found"}
    last = backup.last()
    age = _days_since(last.get("at")) if last else None
    if age is None:
        return step | {"state": TODO, "detail": "The first backup has not run yet"}
    if age > BACKUP_STALE_DAYS:
        return step | {"state": WARN, "detail": f"Last backup was {int(age)} days ago"}
    when = "today" if age < 1 else ("yesterday" if age < 2 else f"{int(age)} days ago")
    return step | {
        "state": DONE,
        "title": "Your library is backed up",
        "detail": f"Last copy {when}",
    }


def _phone_step(sync: dict) -> dict:
    step = {"id": "phone", "tab": "sync", "guide": "relay", "title": "Read on your phone"}
    if not sync["relay_configured"]:
        return step | {"state": TODO, "detail": "Needs a relay"}
    if sync["keyring_locked"]:
        return step | {
            "state": WARN,
            "guide": "recovery-phrase",
            "detail": "This Mac has lost its key. Your recovery phrase restores it",
        }
    if not (sync["secret_present"] and sync["keyring_ready"]):
        return step | {"state": TODO, "detail": "Sync setup is not finished"}
    return step | {
        "state": DONE,
        "guide": "link-phone",
        "title": "Sync is ready",
        "detail": "Link a phone whenever you like",
    }


def _summaries() -> tuple[int, int]:
    """(artifacts whose summary is not from the current model, images with no description)."""
    from .api.admin import _summary_progress

    conn = db.get_conn()
    try:
        stale = int(_summary_progress(conn)["stale"])
        blind = conn.execute(
            "SELECT COUNT(*) AS n FROM artifacts WHERE kind = 'image' AND deleted_at IS NULL"
            " AND vaulted_at IS NULL AND embedded_at IS NULL AND (body IS NULL OR body = '')"
        ).fetchone()["n"]
    finally:
        conn.close()
    return stale, int(blind)


def _alerts(backend: dict, models: dict, sync: dict) -> list[dict]:
    """Settings that need a look: something set that no longer does anything, or
    something that changed under what was set."""
    from .providers import pause

    out: list[dict] = []

    def say(ident, level, tab, guide, text):
        out.append({"id": ident, "level": level, "tab": tab, "guide": guide, "text": text})

    paused = pause.status()
    if paused:
        say(
            "model-paused",
            WARN,
            "ai",
            "answers",
            "The model service has stopped answering for now (a usage limit). Summaries and"
            " answers resume on their own.",
        )

    key = settings.api_key_state()
    if backend.get("local") and key["api_key_present"] and key["api_key_where"] == "keychain":
        say(
            "key-unused",
            "note",
            "ai",
            "api-key",
            "A stored API key is not used while answers come from this Mac.",
        )
    if backend.get("local") and str(settings.get("llm_headers") or "").strip():
        say(
            "headers-unused",
            "note",
            "ai",
            "answers",
            "Extra headers are set, but nothing is sent anywhere while answers come from this Mac.",
        )

    if backend["name"] == "opencode-go":
        known = config.GO_CHAT_COMPLETIONS_MODELS
        gone = sorted({m for job, m in models.items() if job != "images" and m and m not in known})
        if gone:
            say(
                "model-unknown",
                WARN,
                "ai",
                "models",
                f"OpenCode Go does not answer for {', '.join(gone)}. Pick another model.",
            )

    stale, blind = _summaries()
    if stale:
        say(
            "summaries-stale",
            "note",
            "ai",
            "concepts",
            f"{stale} {'item is' if stale == 1 else 'items are'} waiting for a summary from"
            f" {models['ingestion']}. Search finds them by their words until then.",
        )
    if blind:
        say(
            "images-undescribed",
            "note",
            "ai",
            "models",
            f"{blind} {'image has' if blind == 1 else 'images have'} no description, so search"
            " finds them by name only.",
        )

    if sync["relay_configured"] and _relay_reach(sync["relay_url"]) == "local":
        say(
            "relay-local",
            WARN,
            "sync",
            "relay",
            "The relay is on this Mac or this network, so a phone can only reach it at home.",
        )
    if sync["keyring_legacy"]:
        say(
            "keyring-legacy",
            WARN,
            "sync",
            "recovery-phrase",
            "Sync still uses the old password setup. Reset sync to move to the recovery phrase.",
        )
    return out


def status() -> dict:
    backend = _backend()
    models = _models()
    sync = settings.sync_state()
    steps = [_model_step(backend, models), _backup_step(), _phone_step(sync)]
    last = backup.last()
    return {
        "steps": steps,
        "alerts": _alerts(backend, models, sync),
        # What the eye may be told about this installation. Nothing secret.
        "facts": {
            "answers_come_from": backend["label"],
            "answers_leave_this_mac": not backend.get("local"),
            "api_key_stored": settings.api_key_state()["api_key_present"],
            "models": models,
            "backup_folder_chosen": backup.configured_dir() is not None,
            "last_backup": (last or {}).get("at"),
            "sync_set_up": steps[2]["state"] == DONE,
            "relay": (_relay_reach(sync["relay_url"]) if sync["relay_configured"] else "not set"),
            "trash_days": settings.get("trash_days"),
            "links_resolved_when_saved": str(settings.get("auto_preview")) == "on",
            "capture_hotkey": settings.get("hotkey"),
            "items": db.count("artifacts"),
        },
    }


def answer(question: str, guides: list[dict]) -> dict:
    """One answer about settings, from the guides the page matched and where this
    installation stands. Never reads the library."""
    import json

    from .prompts import SETTINGS_ANSWER
    from .providers.base import get_provider
    from .schemas import SettingsAnswer

    offered = [g for g in guides if g.get("id") and g.get("text")][:6]
    facts = status()["facts"]
    user = (
        "Guides:\n\n"
        + "\n\n".join(f"[{g['id']}] {g.get('title', '')}\n{g['text']}" for g in offered)
        + "\n\nThis installation:\n"
        + json.dumps(facts, indent=1, default=str)
        + "\n\nQuestion: "
        + question.strip()
    )
    result = get_provider(role="chat").complete(
        system=SETTINGS_ANSWER, user=user, response_model=SettingsAnswer
    )
    ids = {g["id"] for g in offered}
    guide = result.guide if result.guide in ids else None
    return {"answer": result.answer.strip(), "guide": guide}
