"""The assistant included with Enqueue sync: which models each plan may use, and how
much a month of them may cost.

One list, read by both sides: the relay (relay/ai.py), which enforces it, and the Mac
(the Settings model pickers, setup), which offers it. A person who brings their own key
is never limited by any of this (AGENTS.md, "The paid tier").

Free gets fast, cheap models from Anthropic, OpenAI and Google, and enough of them for
a library's first read and everyday use; Pro adds the mid-level models. The top tier of
each family (Opus, Fable, GPT-6 Astra) is not offered: one long chat with them would
cost more than a month of Pro brings in. Prices are OpenRouter's, in US dollars per
million tokens (input, output), checked 2026-10-20; the relay records what OpenRouter
reports each call actually cost and uses these only when a reply carries no cost.
"""

from __future__ import annotations

FREE = "free"
PRO = "pro"

# id (OpenRouter's), what Settings shows, the plan that unlocks it, whether it can look
# at pictures (the Images job), price in / out per million tokens.
MODELS: list[dict] = [
    {
        "id": "anthropic/claude-haiku-5.5",
        "label": "Claude Haiku 5.5",
        "tier": FREE,
        "vision": True,
        "price": (0.10, 0.50),
    },
    {
        "id": "openai/gpt-6-luna",
        "label": "GPT-6 Luna",
        "tier": FREE,
        "vision": True,
        "price": (0.10, 0.50),
    },
    {
        "id": "google/gemini-3.1-flash-lite",
        "label": "Gemini 3.1 Flash Lite",
        "tier": FREE,
        "vision": True,
        "price": (0.25, 1.50),
    },
    {
        "id": "anthropic/claude-sonnet-5.5",
        "label": "Claude Sonnet 5.5",
        "tier": PRO,
        "vision": True,
        "price": (2.00, 10.00),
    },
    {
        "id": "openai/gpt-6.1-sol",
        "label": "GPT-6.1 Sol",
        "tier": PRO,
        "vision": True,
        "price": (2.00, 10.00),
    },
    {
        "id": "google/gemini-3.8-flash",
        "label": "Gemini 3.8 Flash",
        "tier": PRO,
        "vision": True,
        "price": (0.83, 4.12),
    },
    {
        "id": "deepseek/deepseek-v4-pro",
        "label": "DeepSeek V4 Pro",
        "tier": PRO,
        "vision": False,
        "price": (0.37, 0.73),
    },
    {
        "id": "qwen/qwen3.7-plus",
        "label": "Qwen 3.7 Plus",
        "tier": PRO,
        "vision": True,
        "price": (0.32, 1.28),
    },
]

# What a library starts on: cheap enough for its first read on the free plan.
DEFAULT_MODEL = "anthropic/claude-haiku-5.5"

# What a month of included AI may cost Enqueue, per plan, in US dollars. Pro sells for
# $4.99; after the store's cut this leaves room for storage and a margin. The month is
# the calendar month in UTC.
MONTHLY_CAP_USD = {FREE: 0.50, PRO: 3.00}

_BY_ID = {m["id"]: m for m in MODELS}


def model(model_id: str) -> dict | None:
    return _BY_ID.get(model_id)


def allowed(model_id: str, tier: str) -> bool:
    """Whether a plan may use a model. Pro may use everything free may."""
    m = _BY_ID.get(model_id)
    if m is None:
        return False
    return m["tier"] == FREE or tier == PRO


def estimate_cost(model_id: str, prompt_tokens: int, completion_tokens: int) -> float:
    """A call's cost from its token counts, for a reply that carried no cost."""
    m = _BY_ID.get(model_id)
    if m is None:
        return 0.0
    price_in, price_out = m["price"]
    return (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000


def for_tier(tier: str) -> list[dict]:
    """The list as a picker shows it: every model, each marked usable or not."""
    return [
        {
            "id": m["id"],
            "label": m["label"],
            "tier": m["tier"],
            "vision": m["vision"],
            "allowed": allowed(m["id"], tier),
        }
        for m in MODELS
    ]
