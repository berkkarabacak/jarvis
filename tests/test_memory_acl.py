import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("API_SECRET", "test-secret")
os.environ.setdefault("LLM_PROVIDER", "openrouter")
os.environ.setdefault("OPENROUTER_API_KEY", "or-test")
os.environ.setdefault("TOKEN_PROVIDER", "api_key")
os.environ.setdefault("XAI_API_KEY", "x")


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "m.db"))
    monkeypatch.setenv("API_SECRET", "test-secret")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "x")
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()


H = {"X-Api-Key": "test-secret"}


@pytest.mark.asyncio
async def test_agents_seeded(client):
    r = await client.get("/api/agents", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert any(a["id"] == "scheduler-worker" for a in body["agents"])
    assert any(t["key"] == "scheduler_worker" for t in body["types"])


@pytest.mark.asyncio
async def test_shared_and_private_memory(client):
    # create researcher agent
    r = await client.post(
        "/api/agents",
        headers=H,
        json={"name": "Researcher", "agent_type": "researcher"},
    )
    assert r.status_code == 200
    researcher = r.json()["agent"]["id"]

    shared = await client.post(
        "/api/memories",
        headers=H,
        json={
            "scope": "shared",
            "title": "team note",
            "body": "shared secret sauce",
            "actor_agent_id": "scheduler-worker",
        },
    )
    assert shared.status_code == 200
    shared_id = shared.json()["memory"]["id"]

    private = await client.post(
        "/api/memories",
        headers=H,
        json={
            "scope": "private",
            "title": "private",
            "body": "only mine",
            "actor_agent_id": "scheduler-worker",
        },
    )
    assert private.status_code == 200
    private_id = private.json()["memory"]["id"]

    # researcher can see shared (default allow) but not private of scheduler
    r_list = await client.get(
        f"/api/memories?actor_agent_id={researcher}", headers=H
    )
    assert r_list.status_code == 200
    ids = {m["id"] for m in r_list.json()["memories"]}
    assert shared_id in ids
    assert private_id not in ids

    # scheduler sees both
    s_list = await client.get(
        "/api/memories?actor_agent_id=scheduler-worker", headers=H
    )
    sids = {m["id"] for m in s_list.json()["memories"]}
    assert shared_id in sids and private_id in sids


@pytest.mark.asyncio
async def test_private_memory_denied_to_other(client):
    priv = await client.post(
        "/api/memories",
        headers=H,
        json={
            "scope": "private",
            "body": "nope",
            "actor_agent_id": "scheduler-worker",
        },
    )
    mid = priv.json()["memory"]["id"]
    other = await client.post(
        "/api/agents",
        headers=H,
        json={"name": "Other", "agent_type": "reviewer"},
    )
    oid = other.json()["agent"]["id"]
    # list as other should not include private
    listed = await client.get(f"/api/memories?actor_agent_id={oid}", headers=H)
    assert mid not in {m["id"] for m in listed.json()["memories"]}
