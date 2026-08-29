"""ORCH-411 — approve countdown: default Accept after a short wait."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

CEO = Path(__file__).resolve().parents[1] / "app" / "static" / "ceo.html"


@pytest.fixture
def jarvis_env(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("JARVIS_MODEL", "openai/gpt-4.1-mini")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-secret-value-XXXX")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-secret-value-YYYY")
    monkeypatch.setenv("BRIDGE_ENABLED", "true")
    monkeypatch.setenv("BRIDGE_TOKEN", "test-bridge-token-secret")
    monkeypatch.setenv("BRIDGE_MAX_TIER_AUTO", "L1")
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.delenv("JARVIS_APPROVE_COUNTDOWN_SEC", raising=False)

    import app.jarvis.bridge_routes as br
    import app.jarvis.gateway as gw
    from app.jarvis import settings_store

    gw._gateway = None
    br._store = None
    settings_store.reset_cache()
    yield ws
    gw._gateway = None
    br._store = None
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


def test_approve_countdown_default_is_ten(jarvis_env):
    from app.jarvis import settings_store

    assert settings_store.DEFAULT_APPROVE_COUNTDOWN_SEC == 10
    assert settings_store.get_approve_countdown_sec() == 10
    view = settings_store.public_view()
    assert view["approve_countdown_sec"] == 10
    assert view["approve_countdown_min"] == 1
    assert view["approve_countdown_max"] == 120


def test_approve_countdown_persists_and_clamps(jarvis_env, monkeypatch):
    from app.jarvis import settings_store

    settings_store.save({"approve_countdown_sec": 7})
    settings_store.reset_cache()
    assert settings_store.get_approve_countdown_sec() == 7
    raw = json.loads(settings_store.settings_path().read_text(encoding="utf-8"))
    assert raw["approve_countdown_sec"] == 7

    settings_store.save({"approve_countdown_sec": 0})
    settings_store.reset_cache()
    assert settings_store.get_approve_countdown_sec() == 1

    settings_store.save({"approve_countdown_sec": 999})
    settings_store.reset_cache()
    assert settings_store.get_approve_countdown_sec() == 120

    settings_store.save({"approve_countdown_sec": None})
    settings_store.reset_cache()
    monkeypatch.setenv("JARVIS_APPROVE_COUNTDOWN_SEC", "15")
    assert settings_store.get_approve_countdown_sec() == 15


def test_validate_update_clamps_approve_wait(jarvis_env):
    from app.jarvis import settings_store

    updates = settings_store.validate_update({"approve_countdown_sec": 3})
    assert updates["approve_countdown_sec"] == 3
    updates = settings_store.validate_update({"approve_countdown_sec": 0})
    assert updates["approve_countdown_sec"] == 1
    updates = settings_store.validate_update({"approve_countdown_sec": 500})
    assert updates["approve_countdown_sec"] == 120


@pytest.mark.asyncio
async def test_settings_http_persists_approve_wait(client, jarvis_env):
    from app.jarvis import settings_store

    got = await client.get("/api/jarvis/settings")
    assert got.status_code == 200
    assert got.json()["approve_countdown_sec"] == 10

    saved = await client.put(
        "/api/jarvis/settings",
        json={"approve_countdown_sec": 12},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["approve_countdown_sec"] == 12
    settings_store.reset_cache()
    assert settings_store.get_approve_countdown_sec() == 12

    bad = await client.put(
        "/api/jarvis/settings",
        json={"approve_countdown_sec": 0},
    )
    assert bad.status_code == 422


def test_ceo_html_shows_countdown_and_settings_field():
    html = CEO.read_text(encoding="utf-8")
    assert 'id="confirmCountdown"' in html
    assert "Accepting in " in html
    assert "Approve wait (seconds)" in html
    assert "approve_countdown_sec" in html
    assert "startConfirmCountdown" in html
    assert "stopConfirmCountdown" in html
    assert "innerHTML" not in html


def test_gateway_auto_accepts_after_timeout(jarvis_env, monkeypatch):
    monkeypatch.setenv("JARVIS_APPROVE_COUNTDOWN_SEC", "1")
    from app.jarvis import settings_store
    from app.jarvis.gateway import ToolGateway

    settings_store.reset_cache()
    g = ToolGateway()
    pending = g.run(
        "run_powershell",
        {"command": "Write-Output hi"},
        source="realtime",
        confirmed=False,
    )
    assert pending.get("needs_confirm") is True
    assert pending.get("approve_countdown_sec") == 1
    assert pending.get("confirm_id")
    cid = pending["confirm_id"]
    assert g.has_pending(cid)

    import time

    end = time.time() + 2.5
    while time.time() < end and g.has_pending(cid):
        time.sleep(0.05)
    assert not g.has_pending(cid)
    resolved = g.take_resolved(cid)
    assert resolved.get("needs_confirm") is not True
    assert resolved.get("decision") != "deny"


def test_explicit_cancel_wins_over_countdown(jarvis_env, monkeypatch):
    monkeypatch.setenv("JARVIS_APPROVE_COUNTDOWN_SEC", "1")
    from app.jarvis import settings_store
    from app.jarvis.gateway import ToolGateway

    settings_store.reset_cache()
    g = ToolGateway()
    pending = g.run(
        "run_powershell",
        {"command": "Write-Output no"},
        source="realtime",
        confirmed=False,
    )
    cid = pending["confirm_id"]
    denied = g.confirm(cid, "deny", source="realtime-ui")
    assert denied.get("decision") == "deny"
    assert not g.has_pending(cid)

    import time

    time.sleep(1.3)
    assert not g.has_pending(cid)
    leftover = g.take_resolved(cid)
    assert leftover.get("decision") == "deny"
    assert leftover.get("message", "").lower().startswith("cancelled")


@pytest.mark.asyncio
async def test_await_resolution_auto_accepts(jarvis_env, monkeypatch):
    monkeypatch.setenv("JARVIS_APPROVE_COUNTDOWN_SEC", "1")
    from app.jarvis import settings_store
    from app.jarvis.gateway import ToolGateway
    from app.jarvis.permissions import Tier

    settings_store.reset_cache()
    g = ToolGateway()
    pending = g.run(
        "home_write",
        {"root": "Documents", "path": "x.txt", "content": "hi"},
        source="child:c_test01",
        max_auto=Tier.L2,
        confirmed=False,
    )
    assert pending.get("needs_confirm") is True
    result = await g.await_resolution_async(pending["confirm_id"])
    assert result.get("needs_confirm") is not True
    assert result.get("decision") != "deny"


@pytest.mark.asyncio
async def test_await_resolution_honors_earlier_deny(jarvis_env, monkeypatch):
    monkeypatch.setenv("JARVIS_APPROVE_COUNTDOWN_SEC", "2")
    from app.jarvis import settings_store
    from app.jarvis.gateway import ToolGateway

    settings_store.reset_cache()
    g = ToolGateway()
    pending = g.run(
        "run_powershell",
        {"command": "Write-Output wait"},
        source="child:c_test02",
        confirmed=False,
    )
    cid = pending["confirm_id"]
    g.confirm(cid, "cancel", source="realtime-ui")
    result = await g.await_resolution_async(cid)
    assert result.get("decision") == "deny"
    assert result.get("ok") is True


@pytest.mark.asyncio
async def test_bridge_auto_accepts_after_timeout(jarvis_env, monkeypatch):
    import app.jarvis.bridge_routes as br

    monkeypatch.setenv("JARVIS_APPROVE_COUNTDOWN_SEC", "1")
    from app.jarvis import settings_store

    settings_store.reset_cache()
    monkeypatch.setattr(
        br,
        "_infer_tool_from_goal",
        lambda goal: ("run_powershell", {"command": "Write-Output hi"}),
    )
    headers = {"X-Jarvis-Bridge-Token": "test-bridge-token-secret"}
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            created = await ac.post(
                "/api/bridge/v1/tasks",
                headers=headers,
                json={"goal": "run a shell command", "source": "opencode"},
            )
            assert created.status_code == 201
            tid = created.json()["task_id"]
            status = None
            for _ in range(40):
                polled = await ac.get(f"/api/bridge/v1/tasks/{tid}", headers=headers)
                status = polled.json()["status"]
                if status == "needs_confirm":
                    break
                await asyncio.sleep(0.05)
            assert status == "needs_confirm"
            for _ in range(40):
                polled = await ac.get(f"/api/bridge/v1/tasks/{tid}", headers=headers)
                status = polled.json()["status"]
                if status != "needs_confirm":
                    break
                await asyncio.sleep(0.1)
            assert status in {"done", "failed"}
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_bridge_explicit_deny_wins(jarvis_env, monkeypatch):
    import app.jarvis.bridge_routes as br

    monkeypatch.setenv("JARVIS_APPROVE_COUNTDOWN_SEC", "1")
    from app.jarvis import settings_store

    settings_store.reset_cache()
    monkeypatch.setattr(
        br,
        "_infer_tool_from_goal",
        lambda goal: ("run_powershell", {"command": "Write-Output no"}),
    )
    headers = {"X-Jarvis-Bridge-Token": "test-bridge-token-secret"}
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            created = await ac.post(
                "/api/bridge/v1/tasks",
                headers=headers,
                json={"goal": "run a shell command", "source": "opencode"},
            )
            tid = created.json()["task_id"]
            task = None
            for _ in range(40):
                polled = await ac.get(f"/api/bridge/v1/tasks/{tid}", headers=headers)
                task = polled.json()
                if task["status"] == "needs_confirm":
                    break
                await asyncio.sleep(0.05)
            assert task and task["status"] == "needs_confirm"
            denied = await ac.post(
                f"/api/bridge/v1/tasks/{tid}/confirm",
                headers=headers,
                json={"confirm_id": task["confirm"]["id"], "decision": "deny"},
            )
            assert denied.status_code == 200
            assert denied.json()["status"] == "failed"
            assert "denied" in (denied.json().get("error") or "").lower()
            await asyncio.sleep(1.3)
            again = await ac.get(f"/api/bridge/v1/tasks/{tid}", headers=headers)
            assert again.json()["status"] == "failed"
            assert "denied" in (again.json().get("error") or "").lower()
    get_settings.cache_clear()
