"""ORCH-380 / 383 / 384 / 385 — budget, quality vs price, shared settings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.jarvis.model_router import route_model
from app.jarvis.openrouter_leaders import (
    cheap_catalog_ids,
    reset_leaders_cache_for_tests,
    smart_catalog_ids,
    snapshot_leaders,
)

USAGE_RANK_ONE = "deepseek/deepseek-v4-flash-0731"


@pytest.fixture()
def jarvis_env(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("JARVIS_MODEL", "openai/gpt-4.1-mini")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENAI_REALTIME_VOICE", "marin")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-secret-value-XXXX")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-secret-value-YYYY")
    monkeypatch.setenv("BRIDGE_TOKEN", "bridge-secret-value-ZZZZ")
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.delenv("JARVIS_MODEL_PIN", raising=False)
    monkeypatch.delenv("JARVIS_DISABLE_MODEL_ROUTER", raising=False)
    monkeypatch.delenv("JARVIS_MODEL_PREFERENCE", raising=False)
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")

    import app.jarvis.gateway as gw
    from app.jarvis import settings_store
    from app.jarvis.model_router import reset_state_for_tests

    gw._gateway = None
    settings_store.reset_cache()
    reset_state_for_tests(ws)
    reset_leaders_cache_for_tests()
    yield ws
    gw._gateway = None
    settings_store.reset_cache()
    reset_leaders_cache_for_tests()


@pytest.fixture
async def client(jarvis_env, monkeypatch):
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()


def test_shared_config_persists_across_reload(jarvis_env):
    from app.jarvis import settings_store

    settings_store.save(
        {
            "quality_vs_price": "smart",
            "monthly_budget_usd": 25,
            "daily_budget_usd": 3,
            "look_speed": "10s",
            "model_lock": True,
            "model": "anthropic/claude-sonnet-4",
            "model_lock_pin": "2468",
        }
    )
    settings_store.reset_cache()
    assert settings_store.get_quality_vs_price() == "smart"
    assert settings_store.get_monthly_budget_usd() == 25
    assert settings_store.get_daily_budget_usd() == 3
    assert settings_store.get_look_speed() == "10s"
    assert settings_store.get_model_lock() is True
    assert settings_store.get_model() == "anthropic/claude-sonnet-4"
    assert settings_store.model_lock_pin_set() is True
    raw = json.loads(settings_store.settings_path().read_text(encoding="utf-8"))
    assert raw["quality_vs_price"] == "smart"
    assert raw["monthly_budget_usd"] == 25
    assert raw["daily_budget_usd"] == 3
    assert raw["look_speed"] == "10s"
    assert raw["model_lock"] is True
    assert raw["config_version"] == 2
    assert raw["model_lock_pin"] != "2468"
    assert len(str(raw["model_lock_pin"])) == 64
    view = settings_store.public_view()
    blob = json.dumps(view)
    assert "2468" not in blob
    assert view["model_lock_pin_set"] is True
    assert view["config_version"] == 2
    assert view["config_file"] == "Memory/jarvis_settings.json"
    assert view["budget"]["monthly_cap_usd"] == 25
    assert view["budget"]["daily_cap_usd"] == 3


def test_spend_ledger_survives_reload_and_shows_vs_cap(jarvis_env):
    from app.jarvis import settings_store

    settings_store.save({"monthly_budget_usd": 10, "daily_budget_usd": 2})
    settings_store.record_spend(0.4)
    settings_store.reset_cache()
    status = settings_store.budget_status()
    assert status["monthly_spent_usd"] == 0.4
    assert status["daily_spent_usd"] == 0.4
    assert status["monthly_remaining_usd"] == 9.6
    assert status["daily_remaining_usd"] == 1.6
    assert status["hit"] is False
    assert status["action"] == "ok"
    view = settings_store.public_view()
    assert view["budget"]["monthly_spent_usd"] == 0.4
    assert view["budget"]["daily_cap_usd"] == 2


def test_budget_cap_stops_router(jarvis_env):
    from app.jarvis import settings_store

    settings_store.save({"monthly_budget_usd": 1.0, "quality_vs_price": "smart"})
    settings_store.record_spend(1.0)
    settings_store.reset_cache()
    choice = route_model(
        goal="Create a playable tetris as one HTML file with write_file",
        workspace_root=jarvis_env,
    )
    assert choice.budget_action == "stop"
    assert choice.model == ""
    assert "budget cap" in choice.reason


def test_budget_near_cap_switches_to_cheaper(jarvis_env):
    from app.jarvis import settings_store

    settings_store.save({"monthly_budget_usd": 1.0, "quality_vs_price": "smart"})
    settings_store.record_spend(0.85)
    settings_store.reset_cache()
    status = settings_store.budget_status()
    assert status["action"] == "cheaper"
    choice = route_model(
        goal="Refactor the multi-file codebase architecture carefully",
        workspace_root=jarvis_env,
    )
    assert choice.budget_action == "cheaper"
    assert choice.pinned is False
    assert choice.model
    cheap_free = cheap_catalog_ids(snapshot_leaders(), allow_free=True)
    assert choice.model == cheap_free[0]
    assert "cheaper" in choice.reason


def test_balanced_is_not_cheapest_and_not_usage_rank_one(jarvis_env):
    from app.jarvis import settings_store

    settings_store.save({"quality_vs_price": "balanced"})
    settings_store.reset_cache()
    choice = route_model(
        goal="Create a playable tetris as one HTML file with write_file",
        workspace_root=jarvis_env,
    )
    cheap = cheap_catalog_ids(snapshot_leaders(), allow_free=False)[0]
    smart = smart_catalog_ids(snapshot_leaders())[0]
    assert choice.preference == "balanced"
    assert choice.pinned is False
    assert choice.budget_action == "ok"
    assert choice.model != cheap
    assert choice.model != USAGE_RANK_ONE
    assert choice.model != smart
    assert "balanced" in choice.reason
    assert "#1" not in choice.reason


def test_fast_and_smart_pick_different_models(jarvis_env):
    from app.jarvis import settings_store

    settings_store.save({"quality_vs_price": "fast"})
    settings_store.reset_cache()
    fast = route_model(
        goal="Create a playable tetris as one HTML file with write_file",
        workspace_root=jarvis_env,
    )
    settings_store.save({"quality_vs_price": "smart"})
    settings_store.reset_cache()
    smart = route_model(
        goal="Create a playable tetris as one HTML file with write_file",
        workspace_root=jarvis_env,
    )
    assert fast.preference == "fast"
    assert smart.preference == "quality"
    assert fast.model != smart.model
    assert fast.model == cheap_catalog_ids(snapshot_leaders(), allow_free=False)[0]
    assert smart.model == smart_catalog_ids(snapshot_leaders())[0]
    assert smart.model != USAGE_RANK_ONE


def test_hard_pin_still_wins_over_quality_choice(jarvis_env):
    from app.jarvis import settings_store

    settings_store.save(
        {
            "quality_vs_price": "balanced",
            "model": "anthropic/claude-sonnet-4",
            "model_lock": True,
        }
    )
    settings_store.reset_cache()
    choice = route_model(
        goal="Create a playable tetris as one HTML file with write_file",
        workspace_root=jarvis_env,
    )
    assert choice.pinned is True
    assert choice.model == "anthropic/claude-sonnet-4"
    assert "hard pin" in choice.reason


def test_unlocking_model_lets_quality_drive_router(jarvis_env):
    from app.jarvis import settings_store

    settings_store.save(
        {
            "model": "anthropic/claude-sonnet-4",
            "model_lock": True,
            "quality_vs_price": "fast",
        }
    )
    settings_store.reset_cache()
    pinned = route_model(goal="Build tetris HTML", workspace_root=jarvis_env)
    assert pinned.pinned is True
    updates = settings_store.validate_update({"model_lock": False})
    settings_store.save(updates)
    settings_store.reset_cache()
    choice = route_model(goal="Build tetris HTML", workspace_root=jarvis_env)
    assert choice.pinned is False
    assert choice.preference == "fast"
    assert choice.model != "anthropic/claude-sonnet-4"


def test_look_speed_stays_independent_of_quality(jarvis_env):
    from app.jarvis import settings_store

    settings_store.save({"quality_vs_price": "smart", "look_speed": "1s"})
    settings_store.reset_cache()
    assert settings_store.get_quality_vs_price() == "smart"
    assert settings_store.get_look_speed() == "1s"
    settings_store.save({"look_speed": "off"})
    settings_store.reset_cache()
    assert settings_store.get_quality_vs_price() == "smart"
    assert settings_store.get_look_speed() == "off"


def test_live_job_reads_quality_choice(jarvis_env, monkeypatch):
    from app.jarvis import settings_store
    from app.jarvis.agent import build_jarvis_agent

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    settings_store.save({"quality_vs_price": "balanced"})
    settings_store.reset_cache()
    agent = build_jarvis_agent(
        api_key="sk-test",
        goal="Create a playable tetris as one HTML file with write_file",
    )
    assert agent is not None
    cheap = cheap_catalog_ids(snapshot_leaders(), allow_free=False)[0]
    smart = smart_catalog_ids(snapshot_leaders())[0]
    assert agent._model_route.get("preference") == "balanced"
    assert agent._model != cheap
    assert agent._model != USAGE_RANK_ONE
    assert agent._model != smart


def test_live_job_stops_when_budget_exhausted(jarvis_env, monkeypatch):
    from app.jarvis import settings_store
    from app.jarvis.agent import build_jarvis_agent

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    settings_store.save({"monthly_budget_usd": 0.5})
    settings_store.record_spend(0.5)
    settings_store.reset_cache()
    agent = build_jarvis_agent(
        api_key="sk-test",
        goal="Create a playable tetris as one HTML file with write_file",
    )
    assert agent is not None
    assert agent._model_route.get("budget_action") == "stop"
    assert agent._budget_usd == 0.0


@pytest.mark.asyncio
async def test_http_roundtrip_budget_and_quality(client, jarvis_env):
    from app.jarvis import settings_store

    r = await client.get("/api/jarvis/settings")
    assert r.status_code == 200
    data = r.json()
    assert data["quality_vs_price"] == "balanced"
    assert data["look_speed"] == "off"
    assert "budget" in data
    ids = [c["id"] for c in data["quality_vs_price_choices"]]
    assert ids == ["fast", "balanced", "smart"]

    r = await client.put(
        "/api/jarvis/settings",
        json={
            "quality_vs_price": "fast",
            "monthly_budget_usd": 40,
            "daily_budget_usd": 4,
            "look_speed": "30s",
            "model_lock": False,
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["quality_vs_price"] == "fast"
    assert data["monthly_budget_usd"] == 40
    assert data["daily_budget_usd"] == 4
    assert data["look_speed"] == "30s"
    assert data["budget"]["monthly_cap_usd"] == 40

    settings_store.reset_cache()
    assert settings_store.get_quality_vs_price() == "fast"
    assert settings_store.get_monthly_budget_usd() == 40
    assert settings_store.get_look_speed() == "30s"

    r = await client.put(
        "/api/jarvis/settings",
        json={"quality_vs_price": "turbo"},
    )
    assert r.status_code == 400


def test_pin_required_to_change_lock(jarvis_env):
    from app.jarvis import settings_store

    settings_store.save({"model_lock": True, "model_lock_pin": "1357"})
    settings_store.reset_cache()
    with pytest.raises(ValueError, match="PIN"):
        settings_store.validate_update({"model_lock": False})
    updates = settings_store.validate_update(
        {"model_lock": False, "unlock_pin": "1357"}
    )
    settings_store.save(updates)
    settings_store.reset_cache()
    assert settings_store.get_model_lock() is False
