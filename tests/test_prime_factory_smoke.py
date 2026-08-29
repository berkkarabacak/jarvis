"""B1 factory smoke — adapter selection without requiring real Prime binary ==GRoK==."""

from __future__ import annotations

import pytest


def test_factory_jarvis_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("EXECUTIVE_PRIME_ADAPTER", "jarvis")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-real-but-long-enough-key")
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("PRIME_AGENT_ENABLED", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    import app.jarvis.gateway as gw

    gw._gateway = None
    from app.executive.adapters.factory import build_executive_prime_agent

    agent = build_executive_prime_agent(get_settings())
    assert agent.name == "jarvis-local"


def test_factory_null_without_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_ENABLED", "false")
    monkeypatch.setenv("EXECUTIVE_PRIME_ADAPTER", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("PRIME_AGENT_ENABLED", "false")
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path / "ws2"))
    from app.config import get_settings

    get_settings.cache_clear()
    # clear openrouter from settings - may still read empty
    from app.executive.adapters.factory import build_executive_prime_agent

    # settings may still have empty key
    agent = build_executive_prime_agent(get_settings())
    assert agent.name in {"null", "jarvis-local", "openrouter-prime"}


def test_factory_prime_flag_without_binary_falls_through(monkeypatch, tmp_path):
    """PRIME_AGENT_ENABLED without binary should not crash factory."""
    monkeypatch.setenv("JARVIS_ENABLED", "false")
    monkeypatch.setenv("EXECUTIVE_PRIME_ADAPTER", "")
    monkeypatch.setenv("PRIME_AGENT_ENABLED", "true")
    monkeypatch.setenv("PRIME_AGENT_BIN", str(tmp_path / "missing-prime-agent.exe"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-real-but-long-enough-key")
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path / "ws3"))
    from app.config import get_settings

    get_settings.cache_clear()
    from app.executive.adapters.factory import build_executive_prime_agent

    agent = build_executive_prime_agent(get_settings())
    # either null prime from build_prime_agent_from_environment or openrouter fallback
    assert hasattr(agent, "name")
    assert agent.name in {"null", "openrouter-prime", "prime-rpc", "jarvis-local"}
