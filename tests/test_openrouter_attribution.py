"""OpenRouter marketplace attribution uses the canonical public Talk URL."""

from __future__ import annotations

from app.llm.openrouter_attribution import (
    OPENROUTER_APP_CATEGORIES,
    OPENROUTER_APP_TITLE,
    OPENROUTER_APP_URL,
    openrouter_attribution_headers,
)


def test_openrouter_attribution_points_at_canonical_talk():
    assert OPENROUTER_APP_URL == "https://aicontrolroom.nl/jarvis/"
    assert OPENROUTER_APP_TITLE == "Jarvis"
    assert OPENROUTER_APP_CATEGORIES == "personal-agent,general-chat"
    headers = openrouter_attribution_headers()
    assert headers["HTTP-Referer"] == "https://aicontrolroom.nl/jarvis/"
    assert headers["X-Title"] == "Jarvis"
    assert headers["X-OpenRouter-Title"] == "Jarvis"
    assert headers["X-OpenRouter-Categories"] == "personal-agent,general-chat"
    assert "berkkarabacak.com/jarvis" not in headers["HTTP-Referer"]


def test_openrouter_provider_defaults_use_canonical_talk():
    from app.llm.factory import build_llm_provider
    from app.llm.openrouter import OpenRouterLlmProvider

    provider = OpenRouterLlmProvider(api_key="test")
    assert provider.site_url == "https://aicontrolroom.nl/jarvis/"
    assert provider.app_title == "Jarvis"

    class _Settings:
        llm_provider = "openrouter"
        llm_model_mode = "auto"
        llm_timeout_seconds = 10
        grok_timeout_seconds = 10
        default_model = "openrouter/auto"
        openrouter_api_key = "test"

    built = build_llm_provider(_Settings(), token_provider=None)
    assert isinstance(built, OpenRouterLlmProvider)
    assert built.site_url == "https://aicontrolroom.nl/jarvis/"
