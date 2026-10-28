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

from . import config, backup, db, settings

DONE, TODO, WARN = "done", "todo", "warn"

# A backup older than this, with the library changed since, is worth a word.
BACKUP_STALE_DAYS = 3


def _backend() -> dict:
    name = settings.get("llm_backend")
    for b in settings.backends():
        if b["name"] == name:
            return b
    return next(b for b in settings.backends() if b["name"] == config.LLM_BACKEND)


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
    step = {"id": "model", "tab": "ai", "guide": "answers", "title": "Connect an assistant"}
    if backend.get("included"):
        if not backend.get("signed_in"):
            return step | {
                "state": TODO,
                "guide": "relay",
                "detail": "Sign in under Sync to use the included assistant",
            }
        return step | {
            "state": DONE,
            "title": "Assistant connected",
            "detail": "Included with Enqueue",
        }
    if backend["name"] == "local":
        from . import catalog

        held = catalog.cached("local")
        if held is None:
            return step | {"state": TODO, "detail": "Ollama is not running on this Mac"}
        if not held["chat"]:
            return step | {"state": TODO, "detail": "Download a model to this Mac"}
        return step | {"state": DONE, "title": "Assistant connected", "detail": backend["label"]}
    if backend.get("needs_key") and not backend.get("key_present"):
        return step | {
            "state": TODO,
            "guide": "api-key",
            "detail": f"{backend['label']} needs your account key",
        }
    if backend["name"] == "opencode-go" and not _has_session_header():
        return step | {
            "state": TODO,
            "detail": "OpenCode Go needs one more setting before it answers",
        }
    return step | {
        "state": DONE,
        "title": "Assistant connected",
        "detail": backend["label"],
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
    from . import libkey

    if not libkey.kit_saved():
        # Backups are locked with the library key; without the kit they cannot be
        # opened on a new Mac, so the step is not done until it is kept somewhere.
        return step | {
            "state": WARN,
            "title": "Save your recovery kit",
            "detail": "Only it opens your backups on a new Mac",
        }
    when = "today" if age < 1 else ("yesterday" if age < 2 else f"{int(age)} days ago")
    return step | {
        "state": DONE,
        "title": f"Backed up {when}",
        "detail": f"Last copy {when}",
    }


def _phone_step(sync: dict) -> dict:
    step = {"id": "phone", "tab": "sync", "guide": "relay", "title": "Phone not linked"}
    if not sync["relay_configured"]:
        return step | {
            "state": TODO,
            "detail": "Sign in under Sync to keep it in step with this Mac",
        }
    if sync["keyring_locked"]:
        return step | {
            "state": WARN,
            "guide": "recovery-phrase",
            "title": "Sync needs your recovery phrase",
            "detail": "This Mac has lost its sync key. Your recovery phrase brings it back",
        }
    if not (sync["secret_present"] and sync["keyring_ready"]):
        return step | {"state": TODO, "detail": "Setup isn't finished"}
    return step | {
        "state": DONE,
        "guide": "link-phone",
        "title": "Ready for your phone",
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
            "The online assistant has paused for now (a usage limit). It picks up again on"
            " its own.",
        )

    if pause.key_refused():
        say(
            "key-refused",
            WARN,
            "ai",
            "api-key",
            "The online assistant turned down your key, so nothing is being read or"
            " answered. Paste a new one under Your key.",
        )

    if backend["name"] in ("opencode-go", "openrouter", "anthropic", "openai", "local"):
        from . import catalog

        gone = sorted(
            {
                m
                for job, m in models.items()
                if m and catalog.unknown(backend["name"], m, vision=job == "images", recheck=False)
            }
        )
        if gone:
            say(
                "model-unknown",
                WARN,
                "ai",
                "models",
                f"{backend['label']} doesn't offer {', '.join(gone)}, so that job isn't"
                " running. Pick another under More options.",
            )

    if backend.get("included"):
        from . import included_ai

        tier = backend.get("tier") or "free"
        locked = sorted(
            {
                m
                for m in models.values()
                if m and included_ai.model(m) and not included_ai.allowed(m, tier)
            }
        )
        offered = sorted(
            {m for m in models.values() if m and included_ai.model(m) is None and m != ""}
        )
        if locked:
            say(
                "model-needs-pro",
                WARN,
                "ai",
                "models",
                f"{', '.join(locked)} comes with Enqueue Pro. Pick another under More options,"
                " or go Pro on your phone.",
            )
        if offered:
            say(
                "model-unknown",
                WARN,
                "ai",
                "models",
                f"The included assistant doesn't offer {', '.join(offered)}. Pick one under"
                " More options.",
            )

    stale, blind = _summaries()
    if stale:
        say(
            "summaries-stale",
            "note",
            "ai",
            "concepts",
            f"{stale} {'item is' if stale == 1 else 'items are'} waiting for a summary."
            " Search still finds them by their words.",
        )
    if blind:
        say(
            "images-undescribed",
            "note",
            "ai",
            "models",
            f"{blind} {'image has' if blind == 1 else 'images have'} no description yet, so"
            " search finds them by name only.",
        )

    if sync["relay_configured"] and _relay_reach(sync["relay_url"]) == "local":
        say(
            "relay-local",
            WARN,
            "sync",
            "relay",
            "Your relay is on this Mac or your home network, so your phone can only sync at home.",
        )
    if sync["keyring_legacy"]:
        say(
            "keyring-legacy",
            WARN,
            "sync",
            "recovery-phrase",
            "Sync still uses an older setup. Start sync over to move to the new one.",
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
            "answers_leave_this_mac": True,
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
