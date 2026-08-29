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

AUTH = {"X-Api-Key": "test-secret"}


@pytest.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "exec.db"
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


def _packet(**over):
    base = {
        "from_role": "ui-builder",
        "to_role": "executive",
        "objective": "build page",
        "attempted_work": "wrote markup",
        "outcome": "done",
        "confidence": 0.8,
        "evidence_refs": ["a1"],
        "risks": ["mobile layout"],
        "memory_updates": [{"scope": "team", "title": "ui", "body": "hero shipped"}],
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_executive_session_api_flow(client):
    r = await client.post(
        "/api/executive/sessions",
        headers=AUTH,
        json={"mission_id": "m-api-1", "brief": "demo", "confidence_target": 70},
    )
    assert r.status_code == 200, r.text
    snap = r.json()
    sid = snap["session_id"]
    assert snap["runtime"]["prime_agent"] is False
    assert snap["status"] == "active"

    r = await client.post(
        f"/api/executive/sessions/{sid}/specialists",
        headers=AUTH,
        json={"role_name": "playwright-reviewer"},
    )
    assert r.status_code == 200
    assert r.json()["specialist"]["role_name"] == "playwright-reviewer"

    r = await client.post(
        f"/api/executive/sessions/{sid}/handoffs",
        headers=AUTH,
        json={"packet": _packet(), "memory_scope": "team"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["handoff"]["seq"] == 1
    assert body["confidence"]["score"] >= 0
    assert "mobile layout" in body["snapshot"]["unresolved_risks"]

    r = await client.post(
        f"/api/executive/sessions/{sid}/evidence",
        headers=AUTH,
        json={"kind": "automated_test", "weight": 1.2, "passed": True, "summary": "ok"},
    )
    assert r.status_code == 200

    r = await client.get(f"/api/executive/sessions/{sid}/confidence", headers=AUTH)
    assert r.status_code == 200
    assert "score" in r.json()

    r = await client.get(
        f"/api/executive/sessions/{sid}/memory",
        headers=AUTH,
        params={"scope": "team"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["body"] == "hero shipped"

    r = await client.get(
        "/api/executive/missions/m-api-1/handoffs",
        headers=AUTH,
    )
    assert r.status_code == 200
    assert len(r.json()["handoffs"]) == 1

    r = await client.post(
        f"/api/executive/sessions/{sid}/transition",
        headers=AUTH,
        json={"status": "completed", "reason": "confidence_reached"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"

    # closed session rejects handoffs
    r = await client.post(
        f"/api/executive/sessions/{sid}/handoffs",
        headers=AUTH,
        json={"packet": _packet(confidence=0.5)},
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_executive_api_requires_secret(client):
    r = await client.post(
        "/api/executive/sessions",
        json={"mission_id": "x"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_sqlite_handoff_store_roundtrip(tmp_path):
    from pathlib import Path

    from app.db import Database
    from app.executive.handoff import parse_handoff
    from app.executive.store import SqliteHandoffStore

    db = Database(Path(tmp_path) / "h.db")
    await db.connect()
    store = SqliteHandoffStore(db)
    await store.ensure_schema()
    pkt = parse_handoff(
        {
            "from_role": "a",
            "to_role": "executive",
            "objective": "o",
            "attempted_work": "w",
            "outcome": "x",
            "confidence": 0.55,
        }
    )
    row = await store.append(
        mission_id="m-sql", session_id="s1", packet=pkt, memory_scope="run"
    )
    got = await store.get(row.id)
    assert got is not None
    assert got.packet.confidence == 0.55
    listed = await store.list_for_mission("m-sql", memory_scope="run")
    assert len(listed) == 1
    await db.close()
