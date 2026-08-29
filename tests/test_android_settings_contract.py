"""ORCH-387 — Android binds to GET/PUT /api/jarvis/settings (ORCH-380 keys)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


ANDROID_WIRED_KEYS = (
    "permission_profile",
    "look_speed",
    "quality_vs_price",
    "monthly_budget_usd",
    "daily_budget_usd",
)


@pytest.fixture
def jarvis_env(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("JARVIS_MODEL", "openai/gpt-4.1-mini")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENAI_REALTIME_VOICE", "marin")
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")

    from app.jarvis import settings_store

    settings_store.reset_cache()
    yield ws
    settings_store.reset_cache()


@pytest.fixture
async def client(jarvis_env):
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_android_look_speed_round_trip(client):
    headers = {"X-Api-Key": "test-secret-at-least-32-chars-long!!"}
    got = await client.get("/api/jarvis/settings", headers=headers)
    assert got.status_code == 200
    assert "look_speed" in got.json()

    saved = await client.put(
        "/api/jarvis/settings",
        headers=headers,
        json={"look_speed": "30s", "permission_profile": "locked"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["look_speed"] == "30s"
    assert saved.json()["permission_profile"] == "locked"

    again = await client.get("/api/jarvis/settings", headers=headers)
    assert again.json()["look_speed"] == "30s"


@pytest.mark.asyncio
async def test_android_rejects_invented_settings_keys(client):
    headers = {"X-Api-Key": "test-secret-at-least-32-chars-long!!"}
    r = await client.put(
        "/api/jarvis/settings",
        headers=headers,
        json={"budget_usd": 8, "quality_mode": "smart"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_android_orch380_keys_when_server_publishes_them(client):
    headers = {"X-Api-Key": "test-secret-at-least-32-chars-long!!"}
    got = await client.get("/api/jarvis/settings", headers=headers)
    assert got.status_code == 200
    body = got.json()
    if "quality_vs_price" not in body or "budget" not in body:
        pytest.skip("ORCH-380 persist keys are not on this server revision yet")
    for key in ANDROID_WIRED_KEYS:
        assert key in body
    assert "model_lock_pin" not in body

    android_put = {
        "quality_vs_price": "smart",
        "monthly_budget_usd": 20,
        "daily_budget_usd": 2,
        "look_speed": "10s",
    }
    assert "model_preference" not in android_put
    assert "model_speed" not in android_put

    saved = await client.put(
        "/api/jarvis/settings",
        headers=headers,
        json=android_put,
    )
    assert saved.status_code == 200, saved.text
    data = saved.json()
    assert data["quality_vs_price"] == "smart"
    assert data["look_speed"] == "10s"
    assert "model_lock_pin" not in data
    budget = data["budget"]
    assert budget["action"] in {"ok", "cheaper", "stop"}
    assert "monthly_spent_usd" in budget
