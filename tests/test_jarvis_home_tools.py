"""A2 home folder sandbox + realtime tool schema ==GRoK==."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def home_env(tmp_path, monkeypatch):
    home = tmp_path / "User"
    for name in ("Desktop", "Documents", "Downloads", "Pictures"):
        (home / name).mkdir(parents=True)
    (home / "Documents" / "note.txt").write_text("hello", encoding="utf-8")
    (home / ".ssh").mkdir()
    (home / ".ssh" / "id_rsa").write_text("SECRET", encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    import app.jarvis.gateway as gw

    gw._gateway = None
    yield home


def test_home_list_documents(home_env):
    from app.jarvis.tools import ToolContext, run_tool
    from app.jarvis.workspace import Workspace
    from app.jarvis.memory import JarvisMemory

    ctx = ToolContext(Workspace(), JarvisMemory(Path(home_env).parent / "m.db"))
    raw = run_tool(ctx, "home_list", {"root": "Documents", "path": "."})
    data = json.loads(raw)
    assert data["ok"] is True
    names = {e["name"] for e in data["entries"]}
    assert "note.txt" in names


def test_home_read_ok(home_env):
    from app.jarvis.tools import ToolContext, run_tool
    from app.jarvis.workspace import Workspace
    from app.jarvis.memory import JarvisMemory

    ctx = ToolContext(Workspace(), JarvisMemory(Path(home_env).parent / "m2.db"))
    raw = run_tool(ctx, "home_read", {"root": "Documents", "path": "note.txt"})
    data = json.loads(raw)
    assert data["ok"] is True
    assert data["content"] == "hello"


def test_home_blocks_ssh(home_env):
    from app.jarvis.tools import ToolContext, run_tool
    from app.jarvis.workspace import Workspace
    from app.jarvis.memory import JarvisMemory

    ctx = ToolContext(Workspace(), JarvisMemory(Path(home_env).parent / "m3.db"))
    raw = run_tool(ctx, "home_read", {"root": "Home", "path": ".ssh/id_rsa"})
    data = json.loads(raw)
    assert data["ok"] is False
    assert "blocked" in (data.get("error") or "").lower() or "sensitive" in (
        data.get("error") or ""
    ).lower() or "Permission" in (data.get("error") or "")


def test_home_rejects_escape(home_env, tmp_path):
    from app.jarvis.tools import ToolContext, run_tool
    from app.jarvis.workspace import Workspace
    from app.jarvis.memory import JarvisMemory

    ctx = ToolContext(Workspace(), JarvisMemory(tmp_path / "m4.db"))
    # attempt leave profile via ..
    raw = run_tool(
        ctx, "home_list", {"root": "Documents", "path": "..\\..\\Windows"}
    )
    data = json.loads(raw)
    assert data["ok"] is False


def test_realtime_schema_includes_l0_l2_tools():
    from app.jarvis.realtime import tools_for_realtime

    tools = tools_for_realtime()
    names = {t["name"] for t in tools}
    assert "get_disk_space" in names
    assert "list_github_repos" in names
    assert "system_info" in names
    assert "home_list" in names
    assert "home_read" in names
    assert "home_write" in names
    assert "create_excel" in names
    assert "screenshot" in names
    # disk_space alias not required if get_disk_space present
    assert all(t.get("type") == "function" for t in tools)
    assert all(t.get("description") for t in tools)


def test_gateway_home_list_personal(home_env, monkeypatch):
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("BRIDGE_MAX_TIER_AUTO", "L2")
    from app.jarvis.gateway import ToolGateway
    import app.jarvis.gateway as gw

    gw._gateway = None
    g = ToolGateway()
    r = g.run("home_list", {"root": "Documents"}, source="bridge:opencode")
    assert r.get("ok") is True
