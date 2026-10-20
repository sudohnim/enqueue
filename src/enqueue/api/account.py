"""Enqueue sync: sign in with Google or Apple, this account's devices, signing out.

The sign-in itself happens in the person's browser and comes back here
(`/account/google/callback`, `/account/apple/done`); those two answer with a small page
for that browser tab, and Settings, which is waiting on `GET /account`, moves on.
"""

from __future__ import annotations

from html import escape

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from .. import account

router = APIRouter()


class SignIn(BaseModel):
    provider: str = Field(pattern="^(google|apple)$")
    # Already signed in: only renew the session and the name and picture.
    refresh: bool = False


class DeviceName(BaseModel):
    name: str = Field(default="Phone", min_length=1, max_length=100)


def _refuse(exc: account.AccountError, code: int = 400) -> HTTPException:
    return HTTPException(status_code=code, detail=str(exc))


@router.get("/account")
def read_account() -> dict:
    """Who is signed in, and how the sign-in in progress is going. No network."""
    return account.state()


@router.post("/account/sign-in")
def start_sign_in(req: SignIn) -> dict:
    """The address to open in the browser. Settings opens it and waits."""
    try:
        return {"url": account.begin(req.provider, refresh=req.refresh)}
    except account.AccountError as exc:
        raise _refuse(exc, 409) from None


def _page(ok: bool, message: str) -> HTMLResponse:
    """What the browser tab shows once it comes back here."""
    title = "Signed in to Enqueue" if ok else "Enqueue sign-in did not finish"
    body = (
        "You're signed in. Go back to Enqueue; you can close this tab."
        if ok
        else escape(message) + " Go back to Enqueue and try again."
    )
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="/static/css/tokens.css">
<style>
  body {{ margin: 0; min-height: 100vh; display: grid; place-items: center;
    background: var(--bg); color: var(--text); font-family: var(--sans); }}
  main {{ max-width: 420px; padding: 32px 24px; text-align: center; }}
  img {{ width: 72px; height: auto; }}
  h1 {{ font-family: var(--display); font-weight: var(--w-display); font-size: 26px;
    margin: 16px 0 8px; }}
  p {{ color: var(--text-dim); line-height: 1.5; margin: 0; }}
</style></head>
<body><main><img src="/static/raven-mark.png" alt="">
<h1>{title}</h1><p>{body}</p></main></body></html>""",
        status_code=200 if ok else 400,
    )


@router.get("/account/google/callback", response_class=HTMLResponse)
def google_back(code: str | None = None, state: str | None = None, error: str | None = None):
    try:
        account.finish_google(code, state, error)
    except account.AccountError as exc:
        return _page(False, str(exc))
    return _page(True, "")


@router.get("/account/apple/done", response_class=HTMLResponse)
def apple_back(handoff: str | None = None, state: str | None = None, error: str | None = None):
    try:
        account.finish_apple(handoff, state, error)
    except account.AccountError as exc:
        return _page(False, str(exc))
    return _page(True, "")


@router.get("/account/picture")
def read_picture():
    """The signed-in account's picture, kept on this Mac (none for Apple)."""
    found = account.picture_file()
    if found is None:
        raise HTTPException(status_code=404, detail="no picture")
    return FileResponse(found, headers={"Cache-Control": "no-cache"})


@router.get("/account/devices")
def list_devices() -> dict:
    try:
        return {"devices": account.devices()}
    except account.AccountError as exc:
        raise _refuse(exc, 502) from None


@router.post("/account/device-token")
def device_token(req: DeviceName) -> dict:
    """A relay token for one more device: what the phone's linking code carries when
    this Mac syncs through Enqueue sync (desktop_link_code). Asked for by the shell,
    which sends no Origin; a page from another site is refused by the guard."""
    try:
        return {"relay_token": account.new_device_token(req.name)}
    except account.AccountError as exc:
        raise _refuse(exc, 502) from None


@router.delete("/account/devices/{device_id}")
def remove_device(device_id: str) -> dict:
    try:
        account.remove_device(device_id)
    except account.AccountError as exc:
        raise _refuse(exc) from None
    return {"devices": account.devices()}


@router.post("/account/sign-out")
def sign_out() -> dict:
    account.sign_out()
    return account.state()


@router.delete("/account")
def delete_account() -> dict:
    try:
        account.delete_account()
    except account.AccountError as exc:
        raise _refuse(exc, 502) from None
    return account.state()
