"""The assistant included with Enqueue sync, from the Mac's side: its backend is reached
with this Mac's own device token (never a pasted key), and its model list per plan."""

from __future__ import annotations

from enqueue import config, included_ai, keyring, settings


def test_the_included_backend_uses_the_device_token_and_nothing_else(store, monkeypatch):
    monkeypatch.setattr(keyring, "sync_secret_get", lambda: "enqd_mac-token")
    monkeypatch.setattr(keyring, "get", lambda backend=None: "sk-or-my-own-key")
    assert config.llm_api_key(config.INCLUDED_AI_URL) == "enqd_mac-token"
    assert config.llm_api_key("https://openrouter.ai/api/v1") == "sk-or-my-own-key"
    # A relay of one's own holds a library secret, which is never sent as a model key.
    monkeypatch.setattr(keyring, "sync_secret_get", lambda: "a-library-secret")
    assert config.llm_api_key(config.INCLUDED_AI_URL) == "not-signed-in"


def test_settings_offer_the_plans_models(store):
    included = next(b for b in settings.backends() if b["name"] == "enqueue")
    assert included["included"] and not included["needs_key"]
    allowed = {m["id"]: m["allowed"] for m in included["models"]}
    assert allowed["anthropic/claude-haiku-5.5"]
    assert not allowed["anthropic/claude-sonnet-5.5"]
    settings.update({"account_tier": "pro"})
    included = next(b for b in settings.backends() if b["name"] == "enqueue")
    assert all(m["allowed"] for m in included["models"])


def test_the_list_keeps_the_top_models_out_and_the_default_free():
    ids = {m["id"] for m in included_ai.MODELS}
    assert not any("opus" in i or "fable" in i or "astra" in i for i in ids)
    assert included_ai.allowed(included_ai.DEFAULT_MODEL, included_ai.FREE)
    assert included_ai.MONTHLY_CAP_USD["pro"] > included_ai.MONTHLY_CAP_USD["free"]
