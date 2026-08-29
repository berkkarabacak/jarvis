import os

import pytest

os.environ.setdefault("API_SECRET", "test-secret")
os.environ.setdefault("TOKEN_PROVIDER", "api_key")
os.environ.setdefault("XAI_API_KEY", "xai-test-key")
os.environ.setdefault("LLM_PROVIDER", "openrouter")
os.environ.setdefault("OPENROUTER_API_KEY", "or-test-key")


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "cp.db"))
    monkeypatch.setenv("API_SECRET", "test-secret")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")

    from app.config import get_settings

    get_settings.cache_clear()
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()


H = {"X-Api-Key": "test-secret"}


@pytest.mark.asyncio
async def test_control_plane_status(client):
    r = await client.get("/api/control-plane/status", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["epic"] == "ORCH-70"
    assert body["capabilities"]["hard_budget_checks"] is True
    assert body["capabilities"]["real_container_isolation"] is False


@pytest.mark.asyncio
async def test_mission_lifecycle_and_worker_boundary(client):
    created = await client.post(
        "/api/control-plane/missions",
        headers=H,
        json={
            "title": "Ship control plane slice",
            "brief": "lifecycle test",
            "budget_limit_cents": 1000,
        },
    )
    assert created.status_code == 200, created.text
    mid = created.json()["mission"]["id"]
    assert created.json()["mission"]["status"] == "draft"

    started = await client.post(f"/api/control-plane/missions/{mid}/start", headers=H)
    assert started.status_code == 200, started.text
    detail = started.json()
    assert detail["mission"]["status"] == "running"
    assert detail["workers"]
    assert detail["workers"][0]["status"] == "active"
    assert detail["workers"][0]["isolation_mode"] == "logical"

    done = await client.post(
        f"/api/control-plane/missions/{mid}/complete",
        headers=H,
        json={"commit_cents": 0},
    )
    assert done.status_code == 200
    m = done.json()["mission"]
    assert m["status"] == "succeeded"
    assert m["terminal"] is True

    detail2 = await client.get(f"/api/control-plane/missions/{mid}", headers=H)
    workers = detail2.json()["workers"]
    assert all(w["status"] == "terminated" for w in workers)
    audit_types = {e["event_type"] for e in detail2.json()["audit"]}
    assert "mission.created" in audit_types
    assert "mission.started" in audit_types
    assert "worker.terminated" in audit_types
    assert "mission.succeeded" in audit_types


@pytest.mark.asyncio
async def test_hard_budget_deny_and_reserve_commit(client):
    created = await client.post(
        "/api/control-plane/missions",
        headers=H,
        json={"title": "Budgeted work", "budget_limit_cents": 500},
    )
    mid = created.json()["mission"]["id"]
    await client.post(f"/api/control-plane/missions/{mid}/start", headers=H)

    ok = await client.post(
        f"/api/control-plane/missions/{mid}/budget/reserve",
        headers=H,
        json={"amount_cents": 300, "note": "estimate"},
    )
    assert ok.status_code == 200
    assert ok.json()["mission"]["reserved_cents"] == 300

    denied = await client.post(
        f"/api/control-plane/missions/{mid}/budget/reserve",
        headers=H,
        json={"amount_cents": 300, "note": "too much"},
    )
    assert denied.status_code == 409
    detail = denied.json()["detail"]
    assert detail["error"] == "budget_denied"
    assert detail["denial"]["denied"] is True
    assert detail["denial"]["available_cents"] == 200

    # Mission still running — deny does not kill
    m = await client.get(f"/api/control-plane/missions/{mid}", headers=H)
    assert m.json()["mission"]["status"] == "running"
    assert m.json()["mission"]["reserved_cents"] == 300

    committed = await client.post(
        f"/api/control-plane/missions/{mid}/budget/commit",
        headers=H,
        json={"amount_cents": 250},
    )
    assert committed.status_code == 200
    body = committed.json()["mission"]
    assert body["spend_cents"] == 250
    assert body["reserved_cents"] == 50

    killed = await client.post(
        f"/api/control-plane/missions/{mid}/kill",
        headers=H,
        json={"reason": "stop"},
    )
    assert killed.status_code == 200
    assert killed.json()["mission"]["status"] == "killed"
    assert killed.json()["mission"]["reserved_cents"] == 0

    audit = await client.get(
        f"/api/control-plane/missions/{mid}/audit", headers=H
    )
    types = [e["event_type"] for e in audit.json()["audit"]]
    assert "budget.denied" in types
    assert "budget.reserved" in types
    assert "budget.committed" in types
    assert "mission.killed" in types


@pytest.mark.asyncio
async def test_invalid_transition(client):
    created = await client.post(
        "/api/control-plane/missions",
        headers=H,
        json={"title": "No skip", "budget_limit_cents": 100},
    )
    mid = created.json()["mission"]["id"]
    # complete from draft is invalid
    bad = await client.post(
        f"/api/control-plane/missions/{mid}/complete", headers=H, json={}
    )
    assert bad.status_code == 409
    assert bad.json()["detail"]["error"] == "invalid_transition"


@pytest.mark.asyncio
async def test_unit_budget_service(tmp_path):
    from app.control_plane.service import build_control_plane
    from app.control_plane.models import BudgetError
    from app.db import Database

    db = Database(tmp_path / "u.db")
    await db.connect()
    try:
        cp = build_control_plane(db)
        await cp.ensure_ready()
        m = await cp.create_mission(title="u", budget_limit_cents=100)
        await cp.start_mission(m.id)
        await cp.reserve_budget(m.id, amount_cents=80)
        with pytest.raises(BudgetError) as ei:
            await cp.reserve_budget(m.id, amount_cents=30)
        assert ei.value.denial is not None
        assert ei.value.denial.available_cents == 20
    finally:
        await db.close()
