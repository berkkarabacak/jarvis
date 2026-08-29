"""ORCH-375: open a URL in Chrome without clicking the address bar."""

from __future__ import annotations

import pytest


NTV = "https://www.ntv.com.tr"
FAKE_CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


@pytest.fixture
def chrome_exe():
    from app.jarvis.tools import reset_chrome_exe, set_chrome_exe

    set_chrome_exe(FAKE_CHROME)
    yield FAKE_CHROME
    reset_chrome_exe()


@pytest.fixture
def jarvis_env(tmp_path, monkeypatch, chrome_exe):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("JARVIS_MODEL", "openai/gpt-4.1-mini")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-secret-value-XXXX")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-secret-value-YYYY")
    monkeypatch.setenv("BRIDGE_TOKEN", "bridge-secret-value-ZZZZ")
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.delenv("PUBLIC_GUEST_PROFILE", raising=False)
    monkeypatch.delenv("JARVIS_PUBLIC_CLOUD", raising=False)
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1:8787")
    monkeypatch.delenv("JARVIS_ALLOW_REAL_LAUNCH", raising=False)

    import app.jarvis.gateway as gw
    from app.jarvis import settings_store
    from app.jarvis.tools import reset_chrome_exe, reset_launch_backend

    gw._gateway = None
    settings_store.reset_cache()
    reset_launch_backend()
    yield ws
    gw._gateway = None
    settings_store.reset_cache()
    reset_launch_backend()
    reset_chrome_exe()


def _forbid_real_launch(monkeypatch):
    """Fail the test if Popen or startfile would open a real browser."""
    import os
    import subprocess

    import app.jarvis.tools as tools

    def boom_popen(*args, **kwargs):
        raise AssertionError(f"subprocess.Popen must not run in tests: {args!r} {kwargs!r}")

    def boom_startfile(*args, **kwargs):
        raise AssertionError(f"os.startfile must not run in tests: {args!r} {kwargs!r}")

    monkeypatch.setattr(subprocess, "Popen", boom_popen)
    monkeypatch.setattr(tools.subprocess, "Popen", boom_popen)
    monkeypatch.setattr(os, "startfile", boom_startfile, raising=False)
    monkeypatch.setattr(tools.os, "startfile", boom_startfile, raising=False)


def _capture_launch(log):
    from app.jarvis.tools import set_launch_backend

    def launch(**kwargs):
        log.append(kwargs)
        out = {
            "ok": True,
            "started": kwargs.get("cmd"),
            "argv": kwargs.get("argv"),
        }
        if kwargs.get("url"):
            out["opened"] = kwargs["url"]
        return out

    set_launch_backend(launch)


def test_plan_url_as_target_launches_chrome(chrome_exe):
    from app.jarvis.tools import plan_run_app

    plan = plan_run_app({"target": NTV})
    assert plan["ok"] is True
    assert plan["kind"] == "url"
    assert plan["app"] == chrome_exe
    assert plan["url"] == NTV
    assert plan["argv"] == [chrome_exe, NTV]
    assert plan["cmd"] == f'"{chrome_exe}" {NTV}'
    assert plan["argv"][0].lower().endswith("chrome.exe")


def test_plan_chrome_with_url_arg(chrome_exe):
    from app.jarvis.tools import plan_run_app

    plan = plan_run_app({"target": "chrome", "url": NTV})
    assert plan["ok"] is True
    assert plan["argv"] == [chrome_exe, NTV]
    assert plan["cmd"] == f'"{chrome_exe}" {NTV}'


def test_plan_chrome_without_url_still_just_chrome(chrome_exe):
    from app.jarvis.tools import plan_run_app

    plan = plan_run_app({"target": "chrome"})
    assert plan["ok"] is True
    assert plan["kind"] == "app"
    assert plan["app"] == chrome_exe
    assert plan["url"] == ""
    assert plan["argv"] == [chrome_exe]
    assert plan["cmd"] == f'"{chrome_exe}"'


def test_url_target_and_chrome_url_skip_confirm_like_chrome(jarvis_env):
    from app.jarvis.gateway import ToolGateway

    g = ToolGateway()
    chrome = g.authorize("run_app", {"target": "chrome"}, source="test")
    as_target = g.authorize("run_app", {"target": NTV}, source="test")
    with_url = g.authorize(
        "run_app", {"target": "chrome", "url": NTV}, source="test"
    )
    url_only = g.authorize("run_app", {"url": NTV}, source="test")

    for decision in (chrome, as_target, with_url, url_only):
        assert decision.allowed is True, decision
        assert decision.needs_confirm is False, decision
        assert decision.allowlisted is True, decision


def test_unknown_app_still_needs_confirm(jarvis_env):
    from app.jarvis.gateway import ToolGateway

    g = ToolGateway()
    d = g.authorize(
        "run_app", {"target": "totally-unknown-app-xyz"}, source="test"
    )
    assert d.needs_confirm is True


def test_run_app_url_target_uses_backend_not_browser(jarvis_env, monkeypatch):
    from app.jarvis.gateway import ToolGateway

    _forbid_real_launch(monkeypatch)
    log: list[dict] = []
    _capture_launch(log)
    g = ToolGateway()
    result = g.run("run_app", {"target": NTV}, source="test")
    assert result.get("ok") is True, result
    assert result.get("needs_confirm") in (None, False)
    assert "confirm_id" not in result
    assert result.get("opened") == NTV
    assert result.get("argv") == [FAKE_CHROME, NTV]
    assert log[0]["argv"] == [FAKE_CHROME, NTV]
    assert log[0]["url"] == NTV
    assert str(log[0]["argv"][0]).lower().endswith("chrome.exe")


def test_run_app_chrome_url_uses_backend_not_browser(jarvis_env, monkeypatch):
    from app.jarvis.gateway import ToolGateway

    _forbid_real_launch(monkeypatch)
    log: list[dict] = []
    _capture_launch(log)
    g = ToolGateway()
    result = g.run("run_app", {"target": "chrome", "url": NTV}, source="test")
    assert result.get("ok") is True, result
    assert result.get("needs_confirm") in (None, False)
    assert result.get("opened") == NTV
    assert result.get("argv") == [FAKE_CHROME, NTV]
    assert log[0]["cmd"] == f'"{FAKE_CHROME}" {NTV}'


def test_run_app_chrome_without_url_still_works(jarvis_env, monkeypatch):
    from app.jarvis.gateway import ToolGateway

    _forbid_real_launch(monkeypatch)
    log: list[dict] = []
    _capture_launch(log)
    g = ToolGateway()
    result = g.run("run_app", {"target": "chrome"}, source="test")
    assert result.get("ok") is True, result
    assert result.get("needs_confirm") in (None, False)
    assert result.get("opened") in (None, "")
    assert result.get("argv") == [FAKE_CHROME]
    assert result.get("started") == f'"{FAKE_CHROME}"'
    assert len(log) == 1
    assert log[0]["cmd"] == f'"{FAKE_CHROME}"'
    assert log[0]["argv"] == [FAKE_CHROME]
    assert log[0]["app"] == FAKE_CHROME
    assert log[0]["url"] == ""
    assert log[0]["kind"] == "app"


def test_pytest_does_not_launch_real_browser(jarvis_env, monkeypatch):
    from app.jarvis.tools import reset_launch_backend, run_tool
    from app.jarvis.workspace import Workspace

    reset_launch_backend()
    _forbid_real_launch(monkeypatch)
    import json

    from app.jarvis.tools import ToolContext

    ctx = ToolContext(Workspace(jarvis_env), memory=None)
    raw = run_tool(ctx, "run_app", {"target": NTV})
    parsed = json.loads(raw)
    assert parsed.get("ok") is False
    assert "test" in str(parsed.get("error") or "").lower()


def test_run_app_spec_accepts_url():
    from app.jarvis.realtime import tools_for_realtime
    from app.jarvis.tools import TOOL_SPECS

    spec = next(
        s
        for s in TOOL_SPECS
        if (s.get("function") or {}).get("name") == "run_app"
    )
    props = (spec["function"]["parameters"] or {}).get("properties") or {}
    assert "url" in props
    assert "target" in props
    desc = str(spec["function"].get("description") or "").lower()
    assert "url" in desc
    assert "chat" in desc

    rt = {t["name"]: t for t in tools_for_realtime()}
    assert "url" in (rt["run_app"].get("parameters") or {}).get("properties", {})


def test_prompts_say_do_not_type_url_into_this_chat():
    from app.jarvis.agent import SYSTEM_PROMPT
    from app.jarvis.realtime import JARVIS_REALTIME_INSTRUCTIONS

    for text in (SYSTEM_PROMPT, JARVIS_REALTIME_INSTRUCTIONS):
        low = text.lower()
        assert "do not type a url into this chat" in low
        assert "run_app" in text
        assert "open" in low and "url" in low
        assert "address bar" in low or "top of the chrome window" in low
        assert "message box" in low
        assert "retry run_app" in low
        assert "do not ask the user to click chrome" in low
