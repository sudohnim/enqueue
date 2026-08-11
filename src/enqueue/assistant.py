"""The assistant: a registry of skills and the router that picks one.

The eye is the one place a person types an unstructured request to the AI.
This module holds the two things that turn that text into a skill: the
registry (skill name -> a small descriptor) and `route(request)`, the cheap
model call that picks a skill. Skills are *not* run here - S3 wires dispatch
into `chats.send`. Keeping the classification and the registry in one place
means adding a skill is a one-file edit: a registry entry and a runner, no
router edit, no dispatch edit, no schema change.

Rule 1 lives here, in code: `route` can never raise and can never return a
name outside the registry. The floor is `answer` - grounded and safe, never
wrong to fall back to.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from .prompts import ASSISTANT_ROUTE
from .providers.base import get_provider
from .schemas import AssistantRoute

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Skill:
    """One thing the assistant knows how to do with a request.

    `describe` is the one line the router prompt shows the model. `run` is
    (chat_id, text) -> the message dict the dispatcher stores: `{role, text,
    grounded, kind, payload, cited}`.
    """

    name: str
    describe: str
    run: Callable[[str, str], dict]


def _run_answer(chat_id: str, text: str) -> dict:
    """The `answer` runner, imported lazily: chats.send imports this module for
    the registry, so a top-level import would be circular."""
    from .chats import run_answer

    return run_answer(chat_id, text)


def _run_organize(chat_id: str, text: str) -> dict:
    """The `organize` runner, imported lazily for the same reason."""
    from .chats import run_organize

    return run_organize(chat_id, text)


# The registry is the source of truth for valid skill names. Nothing else in
# the router or the dispatch loop names a skill specially: a third skill is a
# registry entry and a runner, nothing more.
REGISTRY: dict[str, Skill] = {
    "answer": Skill(
        name="answer",
        describe="answer a question from the collection",
        run=_run_answer,
    ),
    "organize": Skill(
        name="organize",
        describe="organize a set of notes into groups by a computed attribute",
        run=_run_organize,
    ),
}


def route(request: str) -> str:
    """Pick the skill that best fits a request. Never raises, never guesses.

    Rule 1, in code: the model is told to prefer `answer` under doubt, and the
    code enforces it regardless of what the model says - an unrecognized skill
    name, a failed model call, or an empty request all land on `answer`.
    """
    request = request.strip()
    if not request:
        return "answer"

    try:
        result = get_provider().complete(
            system=ASSISTANT_ROUTE.format(skills=_skills_block(), request=request),
            user="",
            response_model=AssistantRoute,
        )
        name = result.skill.strip()
    except Exception as exc:  # noqa: BLE001 - a failed route is a floor, not a crash
        log.warning("routing failed (%s); falling back to answer", type(exc).__name__)
        return "answer"

    if name not in REGISTRY:
        return "answer"
    return name


def _skills_block() -> str:
    """The registry rendered the way the router prompt wants it: name + describe."""
    return "\n".join(f"- {skill.name}: {skill.describe}" for skill in REGISTRY.values())
