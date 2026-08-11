"""Conversations: create, ask, answer, rename, pin, delete.

The chat surface is one router; the answer worker that fills pending turns
lives in chats_worker.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import chats

router = APIRouter()


# --------------------------------------------------------------------------- chats


class ChatCreate(BaseModel):
    scope_kind: str = "everything"
    scope_id: str | None = None
    text: str | None = None


class ChatSend(BaseModel):
    text: str
    # Rule 2's server side: the UI re-sends the same text with skill="answer"
    # to leave a routed (non-answer) turn and get a plain answer.
    skill: str | None = None


class ChatEdit(BaseModel):
    title: str | None = None
    pinned: bool | None = None


@router.get("/chats")
def list_chats(limit: int = 40) -> dict:
    return chats.listing(limit=limit)


@router.get("/chats/ready")
def chat_ready() -> dict:
    """Whether there is anything to answer from. Distinguishes the empty cases."""
    return chats.readiness()


@router.get("/chats/passages")
def chat_passages(q: str, scope_kind: str = "everything", scope_id: str | None = None) -> dict:
    """Exactly what an answer to this question would be allowed to read.

    An answer is only ever as good as this list, so it is inspectable. When the
    curator says the collection holds nothing, this is how you tell a retrieval
    failure from an honest one.
    """
    found = chats.passages(q, scope_kind, scope_id)
    return {
        "query": q,
        "passages": [
            {
                "artifact_id": p["artifact_id"],
                "title": p["title"],
                "why": p.get("why"),
                "score": p.get("score"),
                "excerpt": " ".join(p["text"].split())[:240],
            }
            for p in found
        ],
    }


@router.post("/chats", status_code=201)
def create_chat(req: ChatCreate) -> dict:
    if req.text:
        # Submitting returns immediately with a visible pending turn; the answer
        # worker computes it in the background and fills the turn in place. A model
        # failure resolves the turn to 'failed' - the chat and the question stay.
        try:
            return chats.ask(req.text, scope_kind=req.scope_kind, scope_id=req.scope_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except Exception as exc:  # noqa: BLE001 - any other submit failure is a 503
            raise HTTPException(
                status_code=503, detail=f"could not submit the question: {exc}"
            ) from None

    try:
        made = chats.create(scope_kind=req.scope_kind, scope_id=req.scope_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return made


@router.get("/chats/{chat_id}")
def get_chat(chat_id: str) -> dict:
    try:
        return chats.get(chat_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such chat") from None


@router.post("/chats/{chat_id}/messages")
def send_to_chat(chat_id: str, req: ChatSend) -> dict:
    try:
        return chats.send(chat_id, req.text, force_skill=req.skill)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such chat") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as exc:  # noqa: BLE001 - any other submit failure is a 503
        raise HTTPException(
            status_code=503, detail=f"could not submit the question: {exc}"
        ) from None


@router.patch("/chats/{chat_id}")
def edit_chat(chat_id: str, req: ChatEdit) -> dict:
    try:
        result = chats.get(chat_id)
        if req.pinned is not None:
            result = chats.pin(chat_id, req.pinned)
        if req.title is not None:
            result = chats.rename(chat_id, req.title)
        return result
    except KeyError:
        raise HTTPException(status_code=404, detail="no such chat") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.delete("/chats/{chat_id}")
def delete_chat(chat_id: str) -> dict:
    try:
        return chats.delete(chat_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such chat") from None
