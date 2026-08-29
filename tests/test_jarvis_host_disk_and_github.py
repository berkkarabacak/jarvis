"""Host free-space (Windows C:) and GitHub repo list — Windows app product fix."""

from __future__ import annotations

import json
from collections import namedtuple
from pathlib import Path

import pytest

Usage = namedtuple("usage", "total used free")


@pytest.fixture
def jarvis_env(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    import app.jarvis.gateway as gw
    from app.jarvis import mcp_registry, mcp_tokens, settings_store

    gw._gateway = None
    settings_store.reset_cache()
    mcp_registry.reset_cache()
    mcp_tokens.reset_cipher_cache()
    yield ws
    gw._gateway = None
    settings_store.reset_cache()
    mcp_registry.reset_cache()
    mcp_tokens.reset_cipher_cache()


def _win_exists(path: str) -> bool:
    raw = str(path).replace("/", "\\").upper()
    return raw.startswith("C:")


def _win_usage(_path: str) -> Usage:
    # 256 GB total, 42.5 GB free — a spoken number the tests can see.
    return Usage(total=256 * 1024**3, used=int(213.5 * 1024**3), free=int(42.5 * 1024**3))


def test_host_free_space_windows_shaped_c_drive():
    from app.jarvis.host_disk import host_disk_space

    out = host_disk_space(
        drive="",
        exists=_win_exists,
        disk_usage=_win_usage,
        platform="nt",
    )
    assert out["ok"] is True
    assert out["host"] is True
    assert out["drives"]
    assert out["drives"][0]["drive"] == "C:"
    assert out["drives"][0]["free_bytes"] == int(42.5 * 1024**3)
    assert "42.50 GB" in out["summary"]
    assert "C:" in out["summary"]
    assert "free" in out["summary"].lower()


def test_get_disk_space_tool_uses_windows_shaped_host(monkeypatch, tmp_path):
    from app.jarvis import host_disk
    from app.jarvis.tools import ToolContext, run_tool
    from app.jarvis.workspace import Workspace

    monkeypatch.setattr(host_disk, "windows_shaped", lambda **_k: True)
    monkeypatch.setattr(host_disk.os.path, "exists", _win_exists)
    monkeypatch.setattr(host_disk.shutil, "disk_usage", _win_usage)

    ctx = ToolContext(Workspace(tmp_path / "Jarvis"), memory=None)
    data = json.loads(run_tool(ctx, "get_disk_space", {}))
    assert data["ok"] is True
    assert data["drives"][0]["drive"] == "C:"
    assert "42.50 GB" in data["summary"]


def test_open_your_computer_free_space_stays_on_windows_host():
    from app.jarvis.bridge_routes import _infer_tool_from_goal
    from app.jarvis.computer import (
        WINDOWS,
        goal_asks_host_disk,
        goal_targets_jarvis_computer,
        resolve_desktop_backend,
    )

    goal = "Open your computer and tell me the free space on your computer."
    assert goal_asks_host_disk(goal) is True
    assert goal_targets_jarvis_computer(goal) is True
    assert resolve_desktop_backend(goal=goal) == WINDOWS
    assert _infer_tool_from_goal(goal) == ("get_disk_space", {})


def test_linux_desktop_act_still_routes_to_jarvis_computer():
    from app.jarvis.computer import JARVIS_COMPUTER, resolve_desktop_backend

    assert (
        resolve_desktop_backend(goal="open notepad on your computer")
        == JARVIS_COMPUTER
    )


def test_get_disk_space_still_works_when_job_bound_to_linux(tmp_path, monkeypatch):
    from app.jarvis import host_disk
    from app.jarvis.computer import JARVIS_COMPUTER, bind_desktop_backend, reset_computer_state
    from app.jarvis.tools import ToolContext, run_tool
    from app.jarvis.workspace import Workspace

    reset_computer_state()
    monkeypatch.setattr(host_disk, "windows_shaped", lambda **_k: True)
    monkeypatch.setattr(host_disk.os.path, "exists", _win_exists)
    monkeypatch.setattr(host_disk.shutil, "disk_usage", _win_usage)
    bind_desktop_backend(JARVIS_COMPUTER)
    try:
        ctx = ToolContext(Workspace(tmp_path / "Jarvis"), memory=None)
        data = json.loads(run_tool(ctx, "get_disk_space", {}))
        assert data["ok"] is True
        assert "C:" in data["summary"]
        assert "42.50 GB" in data["summary"]
    finally:
        reset_computer_state()


def test_infer_github_repos_phrases():
    from app.jarvis.bridge_routes import _infer_tool_from_goal

    assert _infer_tool_from_goal("Get my GitHub repositories") == (
        "list_github_repos",
        {},
    )
    assert _infer_tool_from_goal("list my repos") == ("list_github_repos", {})
    assert _infer_tool_from_goal("what are my github repos") == (
        "list_github_repos",
        {},
    )


def test_voice_hint_covers_my_repos():
    from app.jarvis.mcp_presets import list_presets_public, preset_voice_instructions

    github = next(p for p in list_presets_public() if p["id"] == "github")
    hints = " ".join(github["voice_hints"]).lower()
    assert "my github repositories" in hints
    assert "my repos" in hints
    instr = preset_voice_instructions()
    assert "list_github_repos" in instr
    assert "Settings" in instr


def test_realtime_schema_includes_list_github_repos():
    from app.jarvis.realtime import (
        JARVIS_REALTIME_INSTRUCTIONS,
        build_instructions,
        tools_for_realtime,
    )

    names = {t["name"] for t in tools_for_realtime()}
    assert "list_github_repos" in names
    assert "get_disk_space" in names
    text = build_instructions()
    assert "list_github_repos" in text
    assert "C:" in JARVIS_REALTIME_INSTRUCTIONS or "Windows host" in JARVIS_REALTIME_INSTRUCTIONS
    from app.jarvis.virtual_pc import hosted_linux_talk

    if hosted_linux_talk():
        assert "Windows laptop" not in text
        assert "C:" not in text
    else:
        assert "C:" in text or "Windows host" in text


def test_list_github_repos_from_settings_token(jarvis_env):
    from app.jarvis.github_repos import list_github_repos
    from app.jarvis.mcp_presets import register_preset

    register_preset("github", token="ghp_test_token_for_repos", refresh=False, root=jarvis_env)

    def fetch(_url, _headers):
        return [
            {
                "name": "agent-orchestrator",
                "full_name": "berkkarabacak/agent-orchestrator",
                "private": True,
                "html_url": "https://github.com/berkkarabacak/agent-orchestrator",
            },
            {
                "name": "notes",
                "full_name": "berkkarabacak/notes",
                "private": True,
            },
        ]

    out = list_github_repos(root=jarvis_env, fetch=fetch, which=lambda _n: None)
    assert out["ok"] is True
    assert out["connected"] is True
    assert out["source"] == "token"
    assert "agent-orchestrator" in out["names"][0]
    assert "notes" in out["summary"]


def test_list_github_repos_from_env_token(jarvis_env, monkeypatch):
    from app.jarvis.github_repos import list_github_repos

    monkeypatch.setenv("GH_TOKEN", "ghp_env_token")

    def fetch(_url, headers):
        assert "Bearer ghp_env_token" in headers["Authorization"]
        return [{"name": "solo", "full_name": "berkkarabacak/solo", "private": False}]

    out = list_github_repos(
        root=jarvis_env,
        env={"GH_TOKEN": "ghp_env_token"},
        fetch=fetch,
        which=lambda _n: None,
    )
    assert out["connected"] is True
    assert out["names"] == ["berkkarabacak/solo"]
    assert "solo" in out["summary"]


def test_list_github_repos_from_gh_cli(jarvis_env):
    from app.jarvis.github_repos import list_github_repos

    class Result:
        returncode = 0
        stdout = json.dumps(
            [
                {
                    "name": "private-app",
                    "nameWithOwner": "berkkarabacak/private-app",
                    "isPrivate": True,
                    "url": "https://github.com/berkkarabacak/private-app",
                }
            ]
        )
        stderr = ""

    def run(argv, **_kwargs):
        assert argv[0] == "gh"
        assert "repo" in argv
        return Result()

    out = list_github_repos(
        root=jarvis_env,
        env={},
        which=lambda name: "/usr/bin/gh" if name == "gh" else None,
        run=run,
    )
    assert out["ok"] is True
    assert out["connected"] is True
    assert out["source"] == "gh"
    assert "berkkarabacak/private-app" in out["names"]
    assert "private-app" in out["summary"]


def test_list_github_repos_missing_token_points_to_settings(jarvis_env):
    from app.jarvis.github_repos import NOT_CONNECTED, list_github_repos
    from app.jarvis.tools import plain_summary

    out = list_github_repos(
        root=jarvis_env,
        env={},
        which=lambda _n: None,
    )
    assert out["ok"] is True
    assert out["connected"] is False
    assert out["repos"] == []
    assert "not connected" in out["summary"].lower()
    assert "Settings" in out["summary"]
    assert "there was a problem" not in out["summary"].lower()
    assert NOT_CONNECTED in out["summary"] or "Connectors" in out["summary"]
    spoken = plain_summary("list_github_repos", out)
    assert "not connected" in spoken.lower()
    assert "Settings" in spoken


def test_gateway_list_github_repos_missing_token(jarvis_env, monkeypatch):
    from app.jarvis.gateway import ToolGateway
    import app.jarvis.github_repos as ghmod

    def fake_list(**_kwargs):
        return {
            "ok": True,
            "connected": False,
            "repos": [],
            "names": [],
            "summary": ghmod.NOT_CONNECTED,
        }

    monkeypatch.setattr(ghmod, "list_github_repos", fake_list)
    g = ToolGateway()
    r = g.run("list_github_repos", {}, source="realtime")
    assert r.get("ok") is True
    assert "not connected" in (r.get("summary") or "").lower()
    assert "Settings" in (r.get("summary") or "")
    assert r.get("blocked") is not True


def test_list_github_repos_is_l0_and_trusted(jarvis_env):
    from app.jarvis.permissions import Tier, tool_tier
    from app.jarvis.taint import returns_untrusted

    assert tool_tier("list_github_repos") == Tier.L0
    assert returns_untrusted("list_github_repos") is False
