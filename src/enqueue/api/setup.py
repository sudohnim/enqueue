"""Where this installation stands, and questions about settings."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import setup
from ..providers.base import ProviderError

router = APIRouter()


@router.get("/setup")
def read_setup() -> dict:
    """What is connected, what is left to set up, and which settings need a look."""
    return setup.status()


class GuideText(BaseModel):
    id: str
    title: str = ""
    text: str = Field(max_length=4000)


class SettingsQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=600)
    guides: list[GuideText] = Field(default_factory=list, max_length=6)


@router.post("/setup/ask")
def ask_setup(req: SettingsQuestion) -> dict:
    """Answer a question about settings from the guides the page matched. The one
    model call in this feature; the page only makes it when its own match is weak."""
    try:
        return setup.answer(req.question, [g.model_dump() for g in req.guides])
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
