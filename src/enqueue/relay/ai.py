"""The assistant included with Enqueue sync: an OpenAI-compatible pass-through to
OpenRouter under Enqueue's own key, for a device of a signed-in account.

A device calls it exactly as it calls OpenRouter with a key of its own (the engine's
`OpenAICompatibleProvider`, the phone's `call_llm_mobile`), with its device token where
the key goes. What happens here, in order:

- the token names the account (and so its plan), as it does for sync;
- the model must be one the plan offers (`included_ai.MODELS`), else 403;
- the month's spend must be under the plan's cap, else 429 with a Retry-After to the
  start of next month, which the engine's usage-limit pause already understands;
- the request goes to OpenRouter with Enqueue's key, refusing every provider that keeps
  or trains on prompts (`provider.data_collection: deny`), with OpenRouter's usage
  accounting on so the reply says what it cost;
- the cost is added to the account's month (`ai_usage`), and the reply goes back as it
  came.

Nothing of a prompt or an answer is kept or logged: the notes pass through this process
on their way to the model and are gone when the reply is sent. Streaming is refused,
since no client streams and a stream's cost arrives only at its end. Things the person
marked as only on their Mac never get here: the engine sends those to the local model.
"""

from __future__ import annotations

import calendar
import logging
import threading
import time
from collections import defaultdict, deque

import httpx
from fastapi import APIRouter, Body, Header, HTTPException, status
from fastapi.responses import JSONResponse

from .. import included_ai
from .accounts import DEVICE_TOKEN_PREFIX, Accounts, tier_of

log = logging.getLogger("enqueue.ai")

# Per account, a burst ceiling on top of the monthly cap: a runaway loop on a device
# stops here long before it spends the month.
PER_MINUTE = 120


def _error(code: int, message: str, kind: str, headers: dict | None = None) -> JSONResponse:
    # OpenAI's error shape, so every client's existing error handling reads it.
    return JSONResponse(
        {"error": {"message": message, "type": kind, "code": code}},
        status_code=code,
        headers=headers,
    )


def _seconds_to_next_month() -> int:
    now = time.gmtime()
    days = calendar.monthrange(now.tm_year, now.tm_mon)[1]
    end = calendar.timegm((now.tm_year, now.tm_mon, days, 23, 59, 59, 0, 0, 0)) + 1
    return max(60, int(end - time.time()))


class _Burst:
    def __init__(self, per_min: int) -> None:
        self.per_min = per_min
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self.lock:
            if len(self.hits) > 1024:
                for old in [k for k, v in self.hits.items() if not v or now - v[-1] > 60]:
                    del self.hits[old]
            q = self.hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_min:
                return False
            q.append(now)
            return True


def router(accounts: Accounts, client: httpx.Client | None = None) -> APIRouter:
    r = APIRouter()
    burst = _Burst(PER_MINUTE)
    upstream = client or httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0))

    def device_account(authorization: str) -> dict:
        scheme, _, token = authorization.partition(" ")
        if scheme != "Bearer" or not token.startswith(DEVICE_TOKEN_PREFIX):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sign in to Enqueue sync first")
        account = accounts.account_for_device(token)
        if account is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "this device is not linked")
        return account

    @r.get("/ai/v1/models")
    def models(authorization: str = Header(default="")):
        account = device_account(authorization)
        tier = tier_of(account)
        return {
            "object": "list",
            "tier": tier,
            "data": [{"object": "model", **m} for m in included_ai.for_tier(tier)],
            "usage": accounts.ai_month(account["id"], tier),
        }

    # A plain (threadpool) route: the call to OpenRouter is a blocking one, and must not
    # hold the event loop the sync change streams run on.
    @r.post("/ai/v1/chat/completions")
    def chat(body: dict = Body(...), authorization: str = Header(default="")):
        account = device_account(authorization)
        key = accounts.s.openrouter_api_key
        if not key:
            return _error(503, "The included assistant is not set up yet.", "unavailable")
        if body.get("stream"):
            return _error(400, "Streaming is not offered.", "invalid_request_error")

        tier = tier_of(account)
        model_id = str(body.get("model") or "")
        if included_ai.model(model_id) is None:
            return _error(
                403, f"{model_id or 'That model'} is not one Enqueue includes.", "model_not_offered"
            )
        if not included_ai.allowed(model_id, tier):
            return _error(403, f"{model_id} comes with Enqueue Pro.", "model_needs_pro")
        month = accounts.ai_month(account["id"], tier)
        if month["used_usd"] >= month["cap_usd"]:
            return _error(
                429,
                "This month's included assistant is used up"
                + ("." if tier == "pro" else ". Enqueue Pro raises it.")
                + " Your own key works without a limit.",
                "usage_limit",
                headers={"Retry-After": str(_seconds_to_next_month())},
            )
        if not burst.allow(account["id"]):
            return _error(429, "Too many requests at once.", "rate_limit", {"Retry-After": "30"})

        sent = {
            **body,
            "stream": False,
            "usage": {"include": True},
            # Never a provider that keeps prompts or trains on them, whatever was asked.
            "provider": {**(body.get("provider") or {}), "data_collection": "deny"},
        }
        sent.pop("user", None)
        try:
            resp = upstream.post(
                accounts.s.openrouter_url.rstrip("/") + "/chat/completions",
                json=sent,
                headers={
                    "Authorization": f"Bearer {key}",
                    "HTTP-Referer": "https://sudohnim.com/enqueue",
                    "X-Title": "Enqueue",
                },
            )
        except httpx.HTTPError as exc:
            log.warning("openrouter unreachable: %s", type(exc).__name__)
            return _error(502, "The assistant could not be reached. Try again.", "upstream")

        if resp.status_code in (401, 402, 403):
            # Enqueue's own key or credit, never the person's: say so as an outage, so
            # a device does not tell its owner that their key was refused.
            log.error("openrouter refused Enqueue's key: %s", resp.status_code)
            return _error(503, "The included assistant is unavailable right now.", "unavailable")
        try:
            data = resp.json()
        except ValueError:
            return _error(502, "The assistant answered with something unreadable.", "upstream")
        if resp.status_code != 200:
            headers = {}
            if resp.headers.get("retry-after"):
                headers["Retry-After"] = resp.headers["retry-after"]
            return JSONResponse(data, status_code=resp.status_code, headers=headers or None)

        usage = data.get("usage") or {}
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        cost = usage.get("cost")
        if not isinstance(cost, (int, float)):
            cost = included_ai.estimate_cost(model_id, prompt, completion)
        accounts.ai_record(account["id"], float(cost), prompt + completion)
        return JSONResponse(data)

    return r
