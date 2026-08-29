import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.executive.adapters.prime import NullPrimeAgent
from app.executive.adapters.routing import HeuristicModelRouter, NullModelRouter
from app.executive.registry import ExecutiveSessionRegistry
from app.executive.runtime import ExecutiveRuntime
from app.executive.store import InMemoryHandoffStore

os.environ.setdefault("API_SECRET", "test-secret")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "")
os.environ.setdefault("TOKEN_PROVIDER", "api_key")
os.environ.setdefault("XAI_API_KEY", "xai-test-key")
os.environ.setdefault("LLM_PROVIDER", "openrouter")
os.environ.setdefault("OPENROUTER_API_KEY", "or-test-key")
os.environ.setdefault("LLM_MODEL_MODE", "fixed")
os.environ.setdefault("DEFAULT_MODEL", "openai/gpt-4.1-mini")

AUTH = {"X-Api-Key": "test-secret"}


@pytest.mark.asyncio
async def test_null_prime_and_heuristic_router_no_network():
    prime = NullPrimeAgent()
    h = await prime.health()
    assert h["rpc"] is False
    assert h["prime_binary"] is False
    assert h.get("available") is False
    assert h.get("availability") == "unavailable"
    assert h.get("credentials_configured") is False
    sess = await prime.start_session(role_name="researcher", model="openrouter/auto")
    assert sess.role_name == "researcher"
    await prime.stop_session(sess.session_id)
    assert (await prime.list_sessions())[0].status == "stopped"

    router = HeuristicModelRouter()
    rh = await router.health()
    assert rh["live_provider"] is False
    cheap = await router.route(task_summary="hi", quality_mode="cheap")
    assert cheap.metadata.get("live_call") is False
    assert cheap.model
    premium = await router.route(
        task_summary="complex multi-step system design",
        quality_mode="premium",
        prior_failures=1,
    )
    assert premium.estimated_cost_usd is not None
    # budget forces cheaper tier
    tight = await router.route(
        task_summary="x",
        quality_mode="premium",
        remaining_budget_usd=0.005,
    )
    assert tight.estimated_cost_usd is not None
    assert tight.estimated_cost_usd <= 0.01

    null_r = NullModelRouter()
    d = await null_r.route(task_summary="x")
    assert d.provider == "none"


@pytest.mark.asyncio
async def test_executive_runtime_spawn_uses_adapters():
    reg = ExecutiveSessionRegistry(handoff_store=InMemoryHandoffStore())
    rt = ExecutiveRuntime(registry=reg, prime=NullPrimeAgent(), router=HeuristicModelRouter())
    health = await rt.adapter_health()
    assert health["live_llm"] is False
    assert health["live_prime_rpc"] is False
    assert health["credentials_in_logs"] is False
    assert health["prime_availability"] in ("unavailable", "error", "ready")
    assert health["router_availability"] in ("plan_only", "unavailable", "error", "ready")
    assert "api_key" not in str(health).lower() or "credentials_configured" in str(health)

    session = await rt.open_mission(mission_id="m-rt-1", brief="Ship landing page")
    assert session.status == "active"
    assert any(s.role_name == "executive" for s in session.specialists.values())

    ref, prime_sess, decision = await rt.spawn_specialist(
        session.session_id,
        role_name="ui-builder",
        quality_mode="cheap",
    )
    assert ref.role_name == "ui-builder"
    assert prime_sess.session_id == ref.instance_id
    assert decision.metadata.get("live_call") is False

    await rt.stop_mission(session.session_id, reason="ceo_stopped")
    assert session.status == "stopped"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "rt.db"))
    monkeypatch.setenv("API_SECRET", "test-secret")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("LLM_MODEL_MODE", "fixed")
    monkeypatch.setenv("DEFAULT_MODEL", "openai/gpt-4.1-mini")
    # This module covers the unwired adapter path: no Prime binary and no live
    # provider calls. Pin the null adapter so the in-process OpenRouter adapter
    # (auto-selected whenever a key is present) does not reach the network here.
    monkeypatch.setenv("EXECUTIVE_PRIME_ADAPTER", "null")
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
async def test_runtime_http_adapters(client):
    r = await client.get("/api/executive/runtime/health", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["live_llm"] is False
    assert body["live_prime_rpc"] is False

    r = await client.post(
        "/api/executive/runtime/route",
        headers=AUTH,
        json={"task_summary": "write tests", "quality_mode": "cheap"},
    )
    assert r.status_code == 200
    assert r.json()["live_call"] is False
    assert r.json()["route"]["model"]

    # ORCH-72 can open a chat with only a brief; ORCH-71 owns the safe ID.
    r = await client.post(
        "/api/executive/runtime/missions",
        headers=AUTH,
        json={"brief": "CEO chat without a client mission id"},
    )
    assert r.status_code == 200, r.text
    snap = r.json()
    uuid.UUID(snap["mission_id"])
    sid = snap["session_id"]
    assert snap["control_plane"]["mission_id"] == snap["mission_id"]
    assert snap["control_plane"]["status"] == "running"

    # The integrated control plane owns mission identifiers.
    r = await client.post(
        "/api/executive/runtime/missions",
        headers=AUTH,
        json={"mission_id": "m-http", "brief": "demo"},
    )
    assert r.status_code == 422
    assert snap["adapters"]["prime"] == "null"
    assert snap["adapters"]["router"] == "heuristic"

    r = await client.post(
        f"/api/executive/runtime/sessions/{sid}/messages",
        json={"message": "hello"},
    )
    assert r.status_code == 401
    r = await client.post(
        f"/api/executive/runtime/sessions/{sid}/messages",
        headers=AUTH,
        json={"message": "hello"},
    )
    assert r.status_code == 503
    assert r.json() == {"detail": "Prime RPC is unavailable"}

    r = await client.post(
        f"/api/executive/runtime/sessions/{sid}/specialists",
        headers=AUTH,
        json={"role_name": "reviewer", "quality_mode": "balanced"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["route"]["metadata"]["live_call"] is False

    r = await client.post(
        f"/api/executive/runtime/sessions/{sid}/stop",
        headers=AUTH,
        json={"status": "stopped", "reason": "ceo_stopped"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "stopped"
