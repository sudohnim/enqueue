"""A model on this Mac, through Ollama: whether it is installed and running, which models
it holds, which one to download for this Mac's memory, and the download itself.

Enqueue ships no model. Ollama runs it; this only finds Ollama, starts it, and asks it
to pull a model, so the app stays small and Ollama keeps its models up to date.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:11434"
APP = Path("/Applications/Ollama.app")
CLI = ("/opt/homebrew/bin/ollama", "/usr/local/bin/ollama")
DOWNLOAD_URL = "https://ollama.com/download"

# What Enqueue offers to download, smallest first. `memory_gb` is the least the Mac
# needs for the model to answer at a usable speed beside everything else it runs.
CHOICES = [
    {
        "model": "gemma3:4b",
        "label": "Gemma 3 4B",
        "size_gb": 3.3,
        "memory_gb": 8,
        "vision": True,
        "note": "Fast and small. Reads pictures.",
    },
    {
        "model": "qwen3:8b",
        "label": "Qwen 3 8B",
        "size_gb": 5.2,
        "memory_gb": 16,
        "vision": False,
        "note": "Better summaries and answers. Does not read pictures.",
    },
    {
        "model": "gemma3:12b",
        "label": "Gemma 3 12B",
        "size_gb": 8.1,
        "memory_gb": 24,
        "vision": True,
        "note": "The best of these. Reads pictures.",
    },
]

_LOCK = threading.Lock()
_PULL: dict = {}
_CANCEL = threading.Event()


def memory_gb() -> int:
    try:
        out = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=2
        )
        return round(int(out.stdout.strip()) / 2**30)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def recommended(memory: int) -> str:
    fits = [c["model"] for c in CHOICES if c["memory_gb"] <= memory]
    return fits[-1] if fits else CHOICES[0]["model"]


def _cli() -> str | None:
    return next((p for p in CLI if Path(p).exists()), None) or shutil.which("ollama")


def installed() -> bool:
    return APP.exists() or _cli() is not None


def running() -> bool:
    try:
        return httpx.get(f"{BASE}/api/version", timeout=1).status_code == 200
    except httpx.HTTPError:
        return False


def models() -> list[dict]:
    """The models Ollama holds, each with its size and whether it reads pictures."""
    try:
        listed = httpx.get(f"{BASE}/api/tags", timeout=2).json().get("models") or []
    except (httpx.HTTPError, ValueError):
        return []
    out = []
    for m in listed:
        name = m.get("name") or m.get("model")
        if not name:
            continue
        try:
            shown = httpx.post(f"{BASE}/api/show", json={"model": name}, timeout=2).json()
        except (httpx.HTTPError, ValueError):
            shown = {}
        caps = shown.get("capabilities") or []
        if caps and "completion" not in caps:
            continue  # an embedding model cannot answer
        out.append({"name": name, "size": m.get("size") or 0, "vision": "vision" in caps})
    return out


def start() -> bool:
    """Open Ollama when it is installed but not running. Whether it was asked to start."""
    if sys.platform == "darwin" and APP.exists():
        subprocess.Popen(["/usr/bin/open", "-a", str(APP)])
        return True
    cli = _cli()
    if cli is None:
        return False
    subprocess.Popen(
        [cli, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return True


def pull_state() -> dict | None:
    with _LOCK:
        return dict(_PULL) if _PULL else None


def pull(model: str) -> None:
    """Download `model` in the background; `pull_state` reports it."""
    if model not in {c["model"] for c in CHOICES}:
        raise ValueError(f"Enqueue does not offer {model!r}")
    with _LOCK:
        if _PULL.get("state") == "pulling":
            raise RuntimeError("A download is already running")
        _PULL.clear()
        _PULL.update(model=model, state="pulling", completed=0, total=0, status="starting")
    _CANCEL.clear()
    threading.Thread(target=_pull, args=(model,), name="local-model-pull", daemon=True).start()


def cancel() -> None:
    _CANCEL.set()


def _pull(model: str) -> None:
    try:
        with httpx.stream(
            "POST", f"{BASE}/api/pull", json={"model": model, "stream": True}, timeout=None
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if _CANCEL.is_set():
                    _finish("cancelled")
                    return
                step = json.loads(line) if line.strip() else {}
                if step.get("error"):
                    _finish("failed", step["error"])
                    return
                with _LOCK:
                    _PULL["status"] = step.get("status") or _PULL["status"]
                    if step.get("total"):
                        _PULL["total"] = step["total"]
                        _PULL["completed"] = step.get("completed") or 0
        _finish("done")
    except (httpx.HTTPError, ValueError) as exc:
        _finish("failed", str(exc) or type(exc).__name__)


def _finish(state: str, error: str | None = None) -> None:
    with _LOCK:
        _PULL["state"] = state
        if error:
            _PULL["error"] = error[:300]
    if state == "done":
        from . import events

        events.emit("model.downloaded", f"Downloaded {_PULL.get('model')} to this Mac")


def status() -> dict:
    """Everything the Settings page needs to draw the helper, without a model call."""
    memory = memory_gb()
    up = running()
    return {
        "installed": up or installed(),
        "running": up,
        "models": models() if up else [],
        "choices": CHOICES,
        "recommended": recommended(memory),
        "memory_gb": memory,
        "pull": pull_state(),
        "download_url": DOWNLOAD_URL,
    }
