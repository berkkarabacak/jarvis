import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["API_SECRET"] = "test-secret"
os.environ["TOKEN_ENCRYPTION_KEY"] = ""
os.environ["TOKEN_PROVIDER"] = "api_key"
os.environ["XAI_API_KEY"] = "xai-test-key"
os.environ["LLM_PROVIDER"] = "openrouter"
os.environ["OPENROUTER_API_KEY"] = "or-test-key"
os.environ["LLM_MODEL_MODE"] = "fixed"
os.environ["DEFAULT_MODEL"] = "openai/gpt-4.1-mini"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "t.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("API_SECRET", "test-secret")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("LLM_MODEL_MODE", "fixed")
    monkeypatch.setenv("DEFAULT_MODEL", "openai/gpt-4.1-mini")

    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "agent-orchestrator"


@pytest.mark.asyncio
async def test_root_redirects_to_public_ceo_and_keeps_operator_dashboard(client):
    r = await client.get("/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "ceo"

    dashboard = await client.get("/dashboard")
    assert dashboard.status_code == 200

    operator_api = await client.get("/api/status")
    assert operator_api.status_code == 401


@pytest.mark.asyncio
async def test_api_requires_secret(client):
    r = await client.get("/api/status")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_provider_oauth_start_remains_operator_only(client):
    public = await client.post("/oauth/start")
    assert public.status_code == 401

    operator = await client.post(
        "/oauth/start",
        headers={"X-Api-Key": "test-secret"},
    )
    assert operator.status_code == 200
    assert "authorize_url" in operator.json()


@pytest.mark.asyncio
async def test_status_with_secret(client):
    r = await client.get("/api/status", headers={"X-Api-Key": "test-secret"})
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "agent-orchestrator"
    assert body["llm"]["provider"] == "openrouter"
    assert body["llm"]["healthy"] is True
    assert body["database"]["provider"] == "sqlite"
    assert body["database"]["ok"] is True
    assert "memory" in body
    assert "models" in body


@pytest.mark.asyncio
async def test_database_settings(client):
    h = {"X-Api-Key": "test-secret"}
    r = await client.get("/api/settings/database", headers=h)
    assert r.status_code == 200
    assert r.json()["provider"] == "sqlite"
    r2 = await client.post("/api/settings/database/test", headers=h)
    assert r2.status_code == 200
    assert r2.json()["ok"] is True


@pytest.mark.asyncio
async def test_llm_settings_get(client):
    r = await client.get("/api/settings/llm", headers={"X-Api-Key": "test-secret"})
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "openrouter"
    assert body["openrouter_api_key_set"] is True
    assert "or-t" in body["openrouter_api_key_masked"] or "••••" in body["openrouter_api_key_masked"]


@pytest.mark.asyncio
async def test_create_job_with_model_mode(client):
    headers = {"X-Api-Key": "test-secret"}
    r = await client.post(
        "/api/jobs",
        headers=headers,
        json={
            "name": "daily",
            "prompt_template": "Summarize open threads for {{date}}",
            "memory_doc": "# start",
            "model_mode": "auto",
            "model": "ignored-when-auto",
        },
    )
    assert r.status_code == 200
    job = r.json()["job"]
    assert job["name"] == "daily"
    assert job["model_mode"] == "auto"
    jid = job["id"]

    r2 = await client.get(f"/api/jobs/{jid}", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["job"]["memory_doc"] == "# start"
