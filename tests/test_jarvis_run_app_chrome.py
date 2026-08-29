"""ORCH-377: run_app must launch a real chrome.exe and not fake ok."""

from __future__ import annotations

import pytest


NTV = "https://www.ntv.com.tr"
FAKE_CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


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
    from app.jarvis.tools import reset_chrome_exe, reset_launch_backend, set_chrome_exe

    gw._gateway = None
    settings_store.reset_cache()
    reset_launch_backend()
    set_chrome_exe(FAKE_CHROME)
    yield ws
    gw._gateway = None
    settings_store.reset_cache()
    reset_launch_backend()
    reset_chrome_exe()


def _forbid_real_launch(monkeypatch):
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


def test_plan_chrome_and_url_use_resolved_chrome_exe(jarvis_env):
    from app.jarvis.tools import plan_run_app

    as_url = plan_run_app({"target": NTV})
    as_chrome = plan_run_app({"target": "chrome", "url": NTV})
    bare = plan_run_app({"target": "chrome"})
    for plan in (as_url, as_chrome, bare):
        assert plan["ok"] is True, plan
        assert plan["argv"][0] == FAKE_CHROME
        assert str(plan["argv"][0]).lower().endswith("chrome.exe")
        assert "chrome.exe" in plan["cmd"]
    assert as_url["argv"] == [FAKE_CHROME, NTV]
    assert as_chrome["argv"] == [FAKE_CHROME, NTV]
    assert bare["argv"] == [FAKE_CHROME]


def test_plan_notepad_and_calc_stay_bare_names(jarvis_env):
    from app.jarvis.tools import plan_run_app

    notepad = plan_run_app({"target": "notepad"})
    calc = plan_run_app({"target": "calc"})
    assert notepad["ok"] is True
    assert notepad["argv"] == ["notepad"]
    assert notepad["cmd"] == "notepad"
    assert calc["argv"] == ["calc"]
    assert calc["cmd"] == "calc"


def test_resolve_chrome_exe_picks_existing_candidate(tmp_path, monkeypatch):
    from app.jarvis.tools import reset_chrome_exe, resolve_chrome_exe

    reset_chrome_exe()
    fake = tmp_path / "Google" / "Chrome" / "Application" / "chrome.exe"
    fake.parent.mkdir(parents=True)
    fake.write_bytes(b"mz")
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path))
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path / "x86"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert resolve_chrome_exe() == str(fake)
    reset_chrome_exe()


def test_launch_backend_reporting_no_window_is_not_ok(jarvis_env, monkeypatch):
    from app.jarvis.gateway import ToolGateway
    from app.jarvis.tools import set_launch_backend

    _forbid_real_launch(monkeypatch)
    log: list[dict] = []

    def launch(**kwargs):
        log.append(kwargs)
        return {
            "ok": True,
            "window": False,
            "started": kwargs.get("cmd"),
            "argv": kwargs.get("argv"),
        }

    set_launch_backend(launch)
    g = ToolGateway()
    result = g.run("run_app", {"target": NTV}, source="test")
    assert result.get("ok") is False, result
    assert result.get("window") is False
    assert "window" in str(result.get("error") or "").lower()
    assert "retry run_app" in str(result.get("error") or "").lower()
    assert result.get("opened") in (None, "")
    assert log[0]["argv"] == [FAKE_CHROME, NTV]


def test_launch_backend_window_true_stays_ok(jarvis_env, monkeypatch):
    from app.jarvis.gateway import ToolGateway
    from app.jarvis.tools import set_launch_backend

    _forbid_real_launch(monkeypatch)

    def launch(**kwargs):
        return {
            "ok": True,
            "window": True,
            "started": kwargs.get("cmd"),
            "argv": kwargs.get("argv"),
            "opened": kwargs.get("url"),
        }

    set_launch_backend(launch)
    g = ToolGateway()
    result = g.run("run_app", {"target": "chrome", "url": NTV}, source="test")
    assert result.get("ok") is True, result
    assert result.get("opened") == NTV
    assert result.get("window") is True


def test_notepad_launch_does_not_require_a_window(jarvis_env, monkeypatch):
    from app.jarvis.gateway import ToolGateway
    from app.jarvis.tools import set_launch_backend

    _forbid_real_launch(monkeypatch)

    def launch(**kwargs):
        return {"ok": True, "started": kwargs.get("cmd"), "argv": kwargs.get("argv")}

    set_launch_backend(launch)
    g = ToolGateway()
    result = g.run("run_app", {"target": "notepad"}, source="test")
    assert result.get("ok") is True, result
    assert result.get("argv") == ["notepad"]
    assert "window" not in result or result.get("window") is not False


def test_focus_app_missing_chrome_says_retry_run_app(jarvis_env):
    from app.jarvis.desktop import focus_app, set_input_backend

    def missing(**kwargs):
        return {"ok": False, "error": f"no visible window matching {kwargs.get('app')!r}"}

    set_input_backend({"focus_app": missing})
    result = focus_app(app="chrome")
    assert result.get("ok") is False
    err = str(result.get("error") or "").lower()
    assert "no visible window" in err
    assert "retry run_app" in err
    assert "do not ask the user to click chrome" in err


def test_has_visible_window_off_during_pytest(jarvis_env, monkeypatch):
    from app.jarvis import desktop

    desktop.reset_input_backend()
    called = {"win": 0}

    def boom(app: str):
        called["win"] += 1
        raise AssertionError("real EnumWindows must not run in pytest")

    monkeypatch.setattr(desktop, "_win_matching_windows", boom)
    assert desktop.has_visible_window(app="chrome") is False
    assert called["win"] == 0


def test_chrome_launch_uses_argv_without_shell(jarvis_env, monkeypatch):
    import app.jarvis.tools as tools
    from app.jarvis.tools import _launch_planned, plan_run_app, reset_launch_backend

    reset_launch_backend()
    calls: list[tuple] = []

    def fake_popen(*args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(tools, "_real_launch_allowed", lambda: True)
    monkeypatch.setattr(tools.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(tools, "_wait_for_visible_window", lambda app, timeout_s=None: True)
    monkeypatch.setattr(
        tools,
        "_wait_for_loaded_page",
        lambda app, timeout_s=None: {
            "ok": True,
            "window": True,
            "title": "Example Domain - Google Chrome",
            "page_ready": True,
        },
    )

    plan = plan_run_app({"target": NTV})
    result = _launch_planned(plan, str(jarvis_env))
    assert result.get("ok") is True, result
    assert result.get("window") is True
    assert result.get("opened") == NTV
    assert calls, "Popen was not called"
    assert list(calls[0][0][0]) == [FAKE_CHROME, NTV]
    assert calls[0][1].get("shell") is False


def test_chrome_launch_without_window_is_not_ok(jarvis_env, monkeypatch):
    import app.jarvis.tools as tools
    from app.jarvis.tools import _launch_planned, plan_run_app, reset_launch_backend

    reset_launch_backend()
    monkeypatch.setattr(tools, "_real_launch_allowed", lambda: True)
    monkeypatch.setattr(tools.subprocess, "Popen", lambda *a, **k: object())
    monkeypatch.setattr(tools, "_wait_for_visible_window", lambda app, timeout_s=None: False)
    monkeypatch.setattr(
        tools,
        "_wait_for_loaded_page",
        lambda app, timeout_s=None: {
            "ok": False,
            "window": False,
            "title": "",
            "page_ready": False,
        },
    )

    plan = plan_run_app({"target": "chrome", "url": NTV})
    result = _launch_planned(plan, str(jarvis_env))
    assert result.get("ok") is False, result
    assert result.get("window") is False
    assert "retry run_app" in str(result.get("error") or "").lower()
    assert "opened" not in result


def test_notepad_launch_still_uses_shell(jarvis_env, monkeypatch):
    import app.jarvis.tools as tools
    from app.jarvis.tools import _launch_planned, plan_run_app, reset_launch_backend

    reset_launch_backend()
    calls: list[tuple] = []

    def fake_popen(*args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(tools, "_real_launch_allowed", lambda: True)
    monkeypatch.setattr(tools.subprocess, "Popen", fake_popen)

    plan = plan_run_app({"target": "notepad"})
    result = _launch_planned(plan, str(jarvis_env))
    assert result.get("ok") is True, result
    assert calls[0][0][0] == "notepad"
    assert calls[0][1].get("shell") is True


def test_prompts_and_see_hint_say_retry_run_app_not_click_chrome():
    from app.jarvis.agent import SYSTEM_PROMPT
    from app.jarvis.realtime import JARVIS_REALTIME_INSTRUCTIONS
    from app.jarvis.screen_loop import looks_like_jarvis_chat

    for text in (SYSTEM_PROMPT, JARVIS_REALTIME_INSTRUCTIONS):
        low = text.lower()
        assert "retry run_app" in low
        assert "do not ask the user to click chrome" in low
        assert "focus_app" in text

    assert looks_like_jarvis_chat("Jarvis chat with Company Org") is True
