"""ORCH-314 remaining Agent Bridge cases (403, cancel, SSE). ==GRoK==

Does not reimplement tests/test_jarvis_gateway_bridge.py (401, status,
capabilities, disk happy path, confirm, ORCH-298/301).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def jarvis_env(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("BRIDGE_ENABLED", "true")
    monkeypatch.setenv("BRIDGE_TOKEN", "test-bridge-token-secret")
    monkeypatch.delenv("JARVIS_BRIDGE_TOKEN", raising=False)
    monkeypatch.setenv("BRIDGE_MAX_TIER_AUTO", "L1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key-not-real")
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    import app.jarvis.gateway as gw
    import app.jarvis.bridge_routes as br

    gw._gateway = None
    br._store = None
    yield ws
    gw._gateway = None
    br._store = None


@asynccontextmanager
async def _bridge_client(*, timeout: float = 10.0):
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app
    import app.jarvis.gateway as gw
    import app.jarvis.bridge_routes as br

    gw._gateway = None
    br._store = None
    app = create_app()
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=transport, base_url="http://127.0.0.1", timeout=timeout
        ) as ac:
            yield ac


def _has_sse_route() -> bool:
    from app.jarvis.bridge_routes import router

    for route in router.routes:
        path = getattr(route, "path", "") or ""
        methods = getattr(route, "methods", set()) or set()
        if path.rstrip("/").endswith("/events") and "GET" in methods:
            return True
    return False


@pytest.mark.asyncio
async def test_bridge_disabled_returns_403(jarvis_env, monkeypatch):
    monkeypatch.setenv("BRIDGE_ENABLED", "false")
    headers = {"X-Jarvis-Bridge-Token": "test-bridge-token-secret"}
    async with _bridge_client() as ac:
        r = await ac.get("/api/bridge/v1/status", headers=headers)
        assert r.status_code == 403
        r = await ac.get("/api/bridge/v1/status")
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_bridge_missing_configured_token_returns_403(jarvis_env, monkeypatch):
    monkeypatch.delenv("BRIDGE_TOKEN", raising=False)
    monkeypatch.delenv("JARVIS_BRIDGE_TOKEN", raising=False)
    monkeypatch.setenv("BRIDGE_ENABLED", "true")
    async with _bridge_client() as ac:
        r = await ac.get("/api/bridge/v1/status")
        assert r.status_code == 403
        r = await ac.get(
            "/api/bridge/v1/status",
            headers={"X-Jarvis-Bridge-Token": "test-bridge-token-secret"},
        )
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_bridge_create_then_cancel(jarvis_env, monkeypatch):
    import app.jarvis.bridge_routes as br

    async def _hold(task_id: str, *, confirmed: bool = False) -> None:
        await asyncio.sleep(60)

    monkeypatch.setattr(br, "_execute_task", _hold)
    headers = {"X-Jarvis-Bridge-Token": "test-bridge-token-secret"}
    async with _bridge_client() as ac:
        created = await ac.post(
            "/api/bridge/v1/tasks",
            headers=headers,
            json={
                "goal": "How much free disk space do I have?",
                "source": "opencode",
            },
        )
        assert created.status_code == 201
        tid = created.json()["task_id"]
        assert created.json()["status"] in {"queued", "running"}

        cancelled = await ac.post(f"/api/bridge/v1/tasks/{tid}/cancel", headers=headers)
        assert cancelled.status_code == 200
        body = cancelled.json()
        assert body["task_id"] == tid
        assert body["status"] == "cancelled"

        polled = await ac.get(f"/api/bridge/v1/tasks/{tid}", headers=headers)
        assert polled.status_code == 200
        assert polled.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_bridge_sse_smoke(jarvis_env):
    if not _has_sse_route():
        pytest.skip("no SSE endpoint on /api/bridge/v1/events")

    headers = {"X-Jarvis-Bridge-Token": "test-bridge-token-secret"}
    async with _bridge_client(timeout=15.0) as ac:
        created = await ac.post(
            "/api/bridge/v1/tasks",
            headers=headers,
            json={
                "goal": "How much free disk space do I have?",
                "source": "opencode",
            },
        )
        assert created.status_code == 201
        tid = created.json()["task_id"]

        events = await ac.get(
            "/api/bridge/v1/events",
            headers=headers,
            params={"task_id": tid},
        )
        assert events.status_code == 200
        ctype = events.headers.get("content-type") or ""
        assert "text/event-stream" in ctype
        text = events.text
        assert tid in text
        assert "event: status" in text
        assert (
            "event: result" in text
            or "event: error" in text
            or '"status": "done"' in text
            or '"status": "failed"' in text
        )
