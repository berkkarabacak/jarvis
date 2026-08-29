"""Public Talk helper picker: top-20 OpenRouter models that actually persist."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.jarvis.openrouter_leaders import SNAPSHOT_MODEL_IDS, helper_models_public

PAGE = Path(__file__).resolve().parents[1] / "deploy" / "jarvis-public" / "index.html"
SECRET = "test-secret-at-least-32-chars-long!!"


def _assert_no_secrets(text: str) -> None:
    assert "sk-or-" not in text
    assert "sk-proj-" not in text
    assert SECRET not in text
    assert "xai-test-key" not in text
    assert "$2.40" not in text


@pytest.fixture
def jarvis_env(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    monkeypatch.setenv("API_SECRET", SECRET)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("DEFAULT_MODEL", "deepseek/deepseek-v4-flash-0731")
    monkeypatch.setenv("JARVIS_MODEL", "deepseek/deepseek-v4-flash-0731")
    monkeypatch.delenv("JARVIS_MODEL_PIN", raising=False)
    monkeypatch.delenv("JARVIS_DISABLE_MODEL_ROUTER", raising=False)
    from app.config import get_settings
    from app.jarvis import settings_store
    import app.jarvis.gateway as gw
    from app.jarvis.openrouter_leaders import reset_leaders_cache_for_tests

    get_settings.cache_clear()
    gw._gateway = None
    settings_store.reset_cache()
    reset_leaders_cache_for_tests()
    yield ws
    gw._gateway = None
    settings_store.reset_cache()
    reset_leaders_cache_for_tests()
    get_settings.cache_clear()


async def _client(app_factory_env, *, host: str):
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, client=(host, 443))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()


@pytest.fixture
async def public_client(jarvis_env):
    async for ac in _client(jarvis_env, host="203.0.113.10"):
        yield ac


@pytest.fixture
async def loopback_client(jarvis_env):
    async for ac in _client(jarvis_env, host="127.0.0.1"):
        yield ac


def test_public_page_has_helper_picker_not_realtime():
    page = PAGE.read_text(encoding="utf-8")
    low = page.lower()
    assert "Who does the extra work" in page
    assert 'id="helper-picks"' in page
    assert "helper_models" in page
    assert "/api/jarvis/settings" in page
    assert "model_lock" in page
    assert "saveTalkSettings" in page
    assert 'data-settings-panel="voice"' in page
    assert 'data-settings-panel="model"' in page
    assert "gpt-realtime" not in low
    assert "innerHTML" not in page
    assert "$2.40" not in page
    assert "openrouter" not in low
    assert "deepseek/" not in low
    assert "api key" not in low
    _assert_no_secrets(page)


@pytest.mark.asyncio
async def test_public_host_can_save_helper_without_api_key(public_client, jarvis_env):
    from app.jarvis import settings_store
    from app.jarvis.model_router import route_model
    from app.jarvis.children import pick_child_model

    helper = "openai/gpt-5.6-luna"
    denied = await public_client.put(
        "/api/jarvis/settings",
        json={"permission_profile": "power", "monthly_budget_usd": 99},
    )
    assert denied.status_code == 401

    invented = await public_client.put(
        "/api/jarvis/settings",
        json={"model": "invented/not-a-real-model", "model_lock": True},
    )
    assert invented.status_code == 400

    realtime = await public_client.put(
        "/api/jarvis/settings",
        json={"model": "gpt-realtime", "model_lock": True},
    )
    assert realtime.status_code == 400

    quality = await public_client.put(
        "/api/jarvis/settings",
        json={"quality_vs_price": "fast"},
    )
    assert quality.status_code == 200, quality.text
    assert quality.json()["quality_vs_price"] == "fast"

    speed = await public_client.put(
        "/api/jarvis/settings",
        json={"model_speed": "careful"},
    )
    assert speed.status_code == 200, speed.text
    assert speed.json()["model_speed"] == "careful"

    saved = await public_client.put(
        "/api/jarvis/settings",
        json={"model": helper, "model_lock": True},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["ok"] is True
    assert body["model"] == helper
    assert body["model_lock"] is True
    assert 1 <= len(body["helper_models"]) <= 20
    ids = [row["id"] for row in body["helper_models"]]
    assert helper in ids
    assert all("gpt-realtime" not in mid for mid in ids)
    _assert_no_secrets(saved.text)

    settings_store.reset_cache()
    assert settings_store.get_model() == helper
    assert settings_store.get_model_lock() is True

    health = await public_client.get("/api/jarvis/health")
    assert health.status_code == 200
    sheet = health.json()
    assert sheet["model"] == helper
    assert 1 <= len(sheet["helper_models"]) <= 20
    assert all(row["id"] in SNAPSHOT_MODEL_IDS for row in sheet["helper_models"])
    assert all("gpt-realtime" not in row["id"] for row in sheet["helper_models"])
    _assert_no_secrets(health.text)

    prefixed = await public_client.get("/jarvis/api/jarvis/health")
    assert prefixed.status_code == 200
    assert prefixed.json()["model"] == helper

    ask = route_model(goal="How much free disk space do I have?", workspace_root=jarvis_env)
    assert ask.pinned is True
    assert ask.model == helper
    child = pick_child_model("Create a file", workspace_root=jarvis_env)
    assert child.pinned is True
    assert child.model == helper


@pytest.mark.asyncio
async def test_loopback_can_still_change_budget(loopback_client, jarvis_env):
    r = await loopback_client.put(
        "/api/jarvis/settings",
        json={"monthly_budget_usd": 40, "daily_budget_usd": 4},
    )
    assert r.status_code == 200, r.text
    assert r.json()["monthly_budget_usd"] == 40


def test_helper_models_payload_has_plain_names(jarvis_env, monkeypatch):
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    rows = helper_models_public()
    assert 1 <= len(rows) <= 20
    by_id = {row["id"]: row for row in rows}
    flash = by_id["deepseek/deepseek-v4-flash-0731"]
    assert flash["name"] == "DeepSeek V4 Flash 0731"
    assert flash["id"] != flash["name"]
    blob = json.dumps(rows)
    assert "gpt-realtime" not in blob
    assert "sk-" not in blob
    _assert_no_secrets(blob)
