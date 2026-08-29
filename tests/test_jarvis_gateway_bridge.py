"""Tests for ToolGateway + Bridge API vertical slice ==GRoK==."""

from __future__ import annotations

import os
from pathlib import Path

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
    monkeypatch.setenv("BRIDGE_MAX_TIER_AUTO", "L1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key-not-real")
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    # reset singletons
    import app.jarvis.gateway as gw

    gw._gateway = None
    yield ws


def test_gateway_disk_space_l0(jarvis_env):
    from app.jarvis.gateway import ToolGateway

    g = ToolGateway()
    r = g.run("get_disk_space", {}, source="test")
    assert r.get("ok") is True
    assert "summary" in r
    assert r.get("drives")


def test_gateway_unknown_tool_denied(jarvis_env):
    from app.jarvis.gateway import ToolGateway

    g = ToolGateway()
    r = g.run("not_a_real_tool", {}, source="test")
    assert r.get("ok") is False
    assert "unknown" in (r.get("error") or "").lower()


def test_gateway_l3_needs_confirm_for_bridge(jarvis_env, monkeypatch):
    monkeypatch.setenv("BRIDGE_MAX_TIER_AUTO", "L1")
    from app.jarvis.gateway import ToolGateway
    import app.jarvis.gateway as gw

    gw._gateway = None
    g = ToolGateway()
    r = g.run(
        "run_powershell",
        {"command": "Get-Date"},
        source="bridge:opencode",
        confirmed=False,
    )
    assert r.get("needs_confirm") is True


def test_gateway_l3_runs_when_confirmed(jarvis_env, monkeypatch):
    monkeypatch.setenv("BRIDGE_MAX_TIER_AUTO", "L1")
    from app.jarvis.gateway import ToolGateway
    import app.jarvis.gateway as gw

    gw._gateway = None
    g = ToolGateway()
    r = g.run(
        "run_powershell",
        {"command": "Write-Output hi"},
        source="bridge:opencode",
        confirmed=True,
    )
    assert r.get("needs_confirm") is not True
    assert "exit_code" in r or r.get("ok") is True


def test_a3_confirm_id_and_confirm_latest(jarvis_env, monkeypatch):
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("BRIDGE_MAX_TIER_AUTO", "L1")
    from app.jarvis.gateway import ToolGateway
    import app.jarvis.gateway as gw

    gw._gateway = None
    g = ToolGateway()
    r = g.run(
        "run_powershell",
        {"command": "Write-Output a3"},
        source="bridge:opencode",
        confirmed=False,
    )
    assert r.get("needs_confirm") is True
    assert r.get("confirm_id", "").startswith("cnf_")
    assert "action_summary" in r
    assert g.pending_confirms()

    denied = g.confirm_latest("cancel", source="bridge:opencode")
    assert denied.get("decision") == "deny" or "cancel" in str(denied.get("message", "")).lower()
    assert not g.pending_confirms()

    r2 = g.run(
        "run_powershell",
        {"command": "Write-Output a3b"},
        source="bridge:opencode",
        confirmed=False,
    )
    cid = r2["confirm_id"]
    ok = g.confirm(cid, "confirm", source="bridge:opencode")
    assert ok.get("needs_confirm") is not True
    err = (ok.get("error") or "").lower()
    assert (
        "exit_code" in ok
        or ok.get("ok") is True
        or "powershell" in err
        or "no such file" in err
    )


def test_a3_allowlisted_app_auto(jarvis_env, monkeypatch):
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("BRIDGE_MAX_TIER_AUTO", "L1")
    from app.jarvis.gateway import ToolGateway
    import app.jarvis.gateway as gw

    gw._gateway = None
    g = ToolGateway()
    # authorize path only — notepad is allowlisted
    d = g.authorize("run_app", {"target": "notepad"}, source="bridge:opencode")
    assert d.allowed is True
    assert d.needs_confirm is False
    assert d.allowlisted is True

    d2 = g.authorize(
        "run_app", {"target": "totally-unknown-app-xyz"}, source="bridge:opencode"
    )
    assert d2.needs_confirm is True


def test_a3_blocked_command(jarvis_env):
    from app.jarvis.gateway import ToolGateway

    g = ToolGateway()
    r = g.run(
        "run_powershell",
        {"command": "Stop-Computer -Force"},
        source="local",
        confirmed=True,
    )
    assert r.get("ok") is False
    assert "blocked" in (r.get("error") or "").lower()


def test_allowlist_helpers():
    from app.jarvis.allowlist import is_app_allowlisted, is_command_blocked

    assert is_app_allowlisted("notepad")
    assert is_app_allowlisted("C:\\\\Windows\\\\System32\\\\notepad.exe")
    assert is_app_allowlisted("https://example.com")
    assert not is_app_allowlisted("malware-tool-xyz")
    assert is_command_blocked("shutdown /s")
    assert not is_command_blocked("Get-Date")


@pytest.mark.asyncio
async def test_bridge_auth_and_disk_task(jarvis_env, monkeypatch):
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
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
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/api/bridge/v1/status")
            assert r.status_code == 401

            headers = {"X-Jarvis-Bridge-Token": "test-bridge-token-secret"}
            r = await ac.get("/api/bridge/v1/status", headers=headers)
            assert r.status_code == 200
            body = r.json()
            assert body["ok"] is True
            assert body["adapters"]["bridge"] is True

            r = await ac.get("/api/bridge/v1/capabilities", headers=headers)
            assert r.status_code == 200
            names = {t["name"] for t in r.json()["tools"]}
            assert "get_disk_space" in names

            r = await ac.post(
                "/api/bridge/v1/tasks",
                headers=headers,
                json={
                    "goal": "How much free disk space do I have?",
                    "source": "opencode",
                },
            )
            assert r.status_code == 201
            tid = r.json()["task_id"]

            # poll
            final = None
            for _ in range(50):
                r = await ac.get(f"/api/bridge/v1/tasks/{tid}", headers=headers)
                assert r.status_code == 200
                final = r.json()
                if final["status"] in {"done", "failed", "needs_confirm"}:
                    break
                import asyncio

                await asyncio.sleep(0.05)

            assert final is not None
            assert final["status"] == "done", final
            assert final["result"]
            assert "free" in final["result"]["summary"].lower() or "%" in final["result"]["summary"]
            assert not final["result"]["summary"].strip().startswith("{")
            assert "get_disk_space" in final["result"]["tools_used"]


def test_plain_confirm_text_home_list_desktop():
    from app.jarvis.tools import plain_confirm_text

    prompt = plain_confirm_text("home_list", {"root": "Desktop", "path": "."})
    assert prompt == "Look at the files on your Desktop?"
    assert "Run tool" not in prompt
    assert "Say confirm" not in prompt


def test_plain_confirm_text_never_toolish():
    from app.jarvis.tools import plain_confirm_text

    for tool, args in [
        ("home_list", {"root": "Downloads"}),
        ("get_disk_space", {}),
        ("system_info", {}),
        ("run_powershell", {"command": "Get-Date"}),
        ("run_app", {"target": "notepad"}),
    ]:
        text = plain_confirm_text(tool, args)
        assert "?" in text
        assert f"Run tool {tool}" not in text
        assert "Say confirm to approve" not in text
        assert not text.lower().startswith("run tool")


def test_plain_summary_home_list():
    from app.jarvis.tools import plain_summary

    result = {
        "ok": True,
        "root": "Desktop",
        "path": "C:\\Users\\pat\\Desktop",
        "entries": [
            {"name": "Taxes", "type": "dir"},
            {"name": "Photo.jpg", "type": "file"},
            {"name": "Notes.txt", "type": "file"},
        ],
        "summary": "On your Desktop I see: Taxes, Photo.jpg, Notes.txt (3 items).",
    }
    summary = plain_summary("home_list", result)
    assert summary.startswith("On your Desktop I see:")
    assert "Taxes" in summary and "Photo.jpg" in summary
    assert "(3 items)" in summary
    assert "{" not in summary


def test_plain_summary_disk_space_friendly():
    from app.jarvis.tools import plain_summary

    result = {
        "ok": True,
        "drives": [
            {
                "drive": "C:",
                "free": "42.50 GB",
                "total": "256.00 GB",
                "free_percent": 16.6,
            }
        ],
        "summary": "You have 42.50 GB free on C: (of 256.00 GB total).",
    }
    summary = plain_summary("get_disk_space", result)
    assert "free" in summary.lower()
    assert "C:" in summary
    assert not summary.strip().startswith("{")
    assert "You have" in summary


def test_plain_summary_system_info_hides_cpu_family():
    from app.jarvis.tools import plain_summary, _clean_processor

    cleaned = _clean_processor("Intel64 Family 6 Model 142 Stepping 10, GenuineIntel")
    assert "Family" not in cleaned
    assert "Model" not in cleaned
    assert "Stepping" not in cleaned

    result = {
        "ok": True,
        "hostname": "LAPTOP-1",
        "os": "Windows-11-10.0.22631-SP0",
        "ram_total": "16.00 GB",
        "ram_available": "8.00 GB",
        "processor": cleaned,
    }
    summary = plain_summary("system_info", result)
    assert "LAPTOP-1" in summary
    assert "Family" not in summary
    assert "Stepping" not in summary
    assert not summary.strip().startswith("{")


def test_gateway_confirm_prompt_is_plain_english(jarvis_env, monkeypatch):
    monkeypatch.setenv("BRIDGE_MAX_TIER_AUTO", "L1")
    from app.jarvis.gateway import ToolGateway
    import app.jarvis.gateway as gw

    gw._gateway = None
    g = ToolGateway()
    r = g.run(
        "run_powershell",
        {"command": "Get-Date"},
        source="bridge:opencode",
        confirmed=False,
    )
    assert r.get("needs_confirm") is True
    assert "Run tool" not in (r.get("action_summary") or "")
    assert "Say confirm to approve" not in (r.get("user_prompt") or "")
    assert "Say confirm to approve" not in (r.get("action_summary") or "")
    # Plain action question
    assert "computer command" in (r.get("action_summary") or "").lower()
    assert r.get("user_prompt") == r.get("action_summary")


def test_gateway_disk_summary_is_plain(jarvis_env):
    from app.jarvis.gateway import ToolGateway

    g = ToolGateway()
    r = g.run("get_disk_space", {}, source="test")
    assert r.get("ok") is True
    summary = r.get("summary") or ""
    assert summary
    assert not summary.strip().startswith("{")
    assert "free" in summary.lower()


def test_orch298_preview_redacts_secret_values(jarvis_env, monkeypatch):
    """Password VALUES must not survive audit preview (old _SECRET_RE left them)."""
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "locked")
    from app.jarvis.gateway import ToolGateway
    import app.jarvis.gateway as gw

    gw._gateway = None
    g = ToolGateway()
    leaked = g._preview({"password": "hunter2-super-secret", "cmd": "echo hi"})
    assert "hunter2" not in leaked
    assert "super-secret" not in leaked
    assert "password" in leaked.lower() or "redact" in leaked.lower()


def test_orch301_bare_confirm_latest_refuses_approve(jarvis_env, monkeypatch):
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("BRIDGE_MAX_TIER_AUTO", "L1")
    from app.jarvis.gateway import ToolGateway
    import app.jarvis.gateway as gw

    gw._gateway = None
    g = ToolGateway()
    r = g.run(
        "run_powershell",
        {"command": "Write-Output bare"},
        source="bridge:opencode",
        confirmed=False,
    )
    assert r.get("needs_confirm") is True
    assert r.get("nonce_prompt")
    assert r.get("nonce_code")

    refused = g.confirm_latest("confirm", source="bridge:opencode")
    assert refused.get("ok") is False
    assert "bare confirm" in (refused.get("error") or "").lower()
    assert g.pending_confirms(), "pending must remain after bare confirm"

    # Spoken nonce still works (exec may fail on non-Windows; confirm must clear)
    code = r["nonce_code"]
    spoken = g.resolve_spoken(f"confirm {code}", source="bridge:opencode")
    assert spoken.get("needs_confirm") is not True
    assert not g.pending_confirms()
    # Either ran, or reached the tool layer (missing powershell on Linux CI)
    err = (spoken.get("error") or "").lower()
    assert (
        "exit_code" in spoken
        or spoken.get("ok") is True
        or "powershell" in err
        or "no such file" in err
    )


def test_orch301_ui_confirm_id_still_approves(jarvis_env, monkeypatch):
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("BRIDGE_MAX_TIER_AUTO", "L1")
    from app.jarvis.gateway import ToolGateway
    import app.jarvis.gateway as gw

    gw._gateway = None
    g = ToolGateway()
    r = g.run(
        "run_powershell",
        {"command": "Write-Output ui"},
        source="bridge:opencode",
        confirmed=False,
    )
    ok = g.confirm(r["confirm_id"], "confirm", source="bridge:opencode")
    assert ok.get("needs_confirm") is not True
    assert not g.pending_confirms()
    err = (ok.get("error") or "").lower()
    assert (
        "exit_code" in ok
        or ok.get("ok") is True
        or "powershell" in err
        or "no such file" in err
    )
