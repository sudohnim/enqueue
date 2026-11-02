"""Error reports to PostHog (US): when something breaks, where in the code and how, never
what was in the library.

Every error the engine logs with its traceback (`log.exception` anywhere under
`enqueue`, and uvicorn's unhandled request errors) reaches `ErrorReporter`, which sends
one `$exception` event: the error's type, a cleaned message, and the stack as file,
function and line of Enqueue's own code. Never local variables, source lines or the log
line's own text, which can name an artifact. The message is cut short and stripped of
anything quoted, addresses, e-mail addresses, ids and long tokens, since an error often
repeats its input. A model service's own failures (`ProviderError`: a limit, an outage,
a refused key) are not bugs and are not sent; the Activity log has them. The page's
JavaScript errors come in through `POST /report` and go out the same way.

Tied to a random id made for this install (`telemetry_id`), never an account; no person
profile, no IP or place. Off when the `telemetry` setting is off or no key is set.
"""

from __future__ import annotations

import json
import logging
import platform
import re
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import config

log = logging.getLogger(__name__)

PACKAGE = Path(__file__).resolve().parent
QUIET_S = 600  # the same error from the same place is sent once per this long
MAX_PER_HOUR = 30

_lock = threading.Lock()
_seen: dict[str, float] = {}
_sent_at: list[float] = []

_CLEAN = [
    (re.compile(r"'[^']*'|\"[^\"]*\"|“[^”]*”"), "…"),
    (re.compile(r"https?://\S+"), "<url>"),
    (re.compile(r"\S+@\S+\.\w+"), "<email>"),
    (re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I), "<id>"),
    (re.compile(r"/Users/[^\s:]+"), "<path>"),
    (re.compile(r"\S{32,}"), "<long>"),
]


def clean(message: str) -> str:
    """An error message with what could be the person's own text taken out."""
    text = " ".join(str(message).split())
    for pattern, stand_in in _CLEAN:
        text = pattern.sub(stand_in, text)
    return text[:200]


def enabled() -> bool:
    from . import settings

    return bool(config.POSTHOG_KEY) and str(settings.get("telemetry")).lower() not in (
        "off",
        "false",
        "0",
    )


def environment() -> str:
    """'prod' inside the shipped Mac app (its bundled engine), else 'dev'."""
    return "prod" if ".app/Contents/Resources" in sys.prefix else "dev"


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("enqueue")
    except PackageNotFoundError:
        return "dev"


def install_id() -> str:
    path = config.DATA_DIR / "telemetry_id"
    try:
        return path.read_text().strip()
    except OSError:
        made = str(uuid.uuid4())
        try:
            path.write_text(made)
        except OSError:
            pass
        return made


def _frames(tb) -> list[dict]:
    """Enqueue's own frames, as file, function and line, innermost last."""
    out = []
    for frame in traceback.extract_tb(tb):
        path = Path(frame.filename)
        try:
            rel = path.resolve().relative_to(PACKAGE.parent)
        except ValueError:
            continue
        out.append(
            {
                "filename": str(rel),
                "function": frame.name,
                "lineno": frame.lineno,
                "platform": "python",
                "in_app": True,
            }
        )
    return out[-30:]


def _allowed(key: str) -> bool:
    now = time.monotonic()
    with _lock:
        if now - _seen.get(key, -QUIET_S) < QUIET_S:
            return False
        _sent_at[:] = [t for t in _sent_at if now - t < 3600]
        if len(_sent_at) >= MAX_PER_HOUR:
            return False
        _seen[key] = now
        _sent_at.append(now)
        return True


def report(
    area: str,
    kind: str,
    message: str,
    frames: list[dict] | None = None,
    platform_name: str = "mac",
) -> None:
    """Send one error report. Never raises and never waits on the network."""
    try:
        if not enabled():
            return
        frames = frames or []
        where = frames[-1] if frames else {}
        key = f"{area}|{kind}|{where.get('filename')}|{where.get('lineno')}"
        if not _allowed(key):
            return
        properties = {
            "$exception_list": [
                {
                    "type": kind[:80],
                    "value": clean(message),
                    "mechanism": {"handled": True, "synthetic": False},
                    "stacktrace": {"type": "raw", "frames": frames},
                }
            ],
            "area": area[:60],
            "platform": platform_name,
            "environment": environment(),
            "app_version": _version(),
            "os_version": platform.mac_ver()[0],
            "$process_person_profile": False,
            "$geoip_disable": True,
            "$lib": "enqueue-engine",
        }
        event = {
            "api_key": config.POSTHOG_KEY,
            "event": "$exception",
            "distinct_id": install_id(),
            "properties": properties,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        threading.Thread(target=_send, args=(event,), name="error-report", daemon=True).start()
    except Exception:  # noqa: BLE001 - reporting must never break anything
        pass


def report_exception(area: str, exc: BaseException) -> None:
    from .providers.base import ProviderError

    if isinstance(exc, ProviderError):
        return
    report(area, type(exc).__name__, str(exc), _frames(exc.__traceback__))


def _send(event: dict) -> None:
    try:
        httpx.post(
            f"{config.POSTHOG_HOST}/capture/",
            content=json.dumps(event),
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
    except httpx.HTTPError:
        pass


class ErrorReporter(logging.Handler):
    """Reports every logged error that carries an exception."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        if record.exc_info and record.exc_info[1] is not None:
            area = record.name.removeprefix("enqueue.")
            report_exception(area, record.exc_info[1])


_HANDLER = ErrorReporter()


def install() -> None:
    """Attach the reporter to the engine's loggers and to uvicorn's request errors."""
    for name in ("enqueue", "uvicorn.error"):
        logger = logging.getLogger(name)
        if _HANDLER not in logger.handlers:
            logger.addHandler(_HANDLER)
