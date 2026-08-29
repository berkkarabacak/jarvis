"""ORCH-372: focus_app brings the target window to the front before looking."""

from __future__ import annotations

import base64

import pytest

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


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
    monkeypatch.delenv("JARVIS_ALLOW_REAL_INPUT", raising=False)

    import app.jarvis.gateway as gw
    from app.jarvis import settings_store
    from app.jarvis.desktop import reset_input_backend

    gw._gateway = None
    settings_store.reset_cache()
    reset_input_backend()
    yield ws
    gw._gateway = None
    settings_store.reset_cache()
    reset_input_backend()


def _fake_focus(log, *, known=("chrome", "msedge", "notepad", "ntv.com.tr", "Chrome")):
    from app.jarvis.desktop import set_input_backend

    def focus_app(**kwargs):
        log.append(("focus_app", kwargs))
        needle = str(kwargs.get("app") or "").strip().lower()
        if needle in {k.lower() for k in known}:
            return {
                "ok": True,
                "app": kwargs.get("app"),
                "title": "ntv.com.tr - Google Chrome",
                "process": "chrome",
                "focused": True,
            }
        return {"ok": False, "error": f"no visible window matching {kwargs.get('app')!r}"}

    set_input_backend({"focus_app": focus_app})


def test_focus_app_chrome_no_needs_confirm_even_after_taint(jarvis_env):
    from app.jarvis.gateway import ToolGateway
    from app.jarvis.permissions import Tier, requires_confirm, skips_confirm

    log = []
    _fake_focus(log)
    g = ToolGateway()

    assert skips_confirm("focus_app")
    assert requires_confirm("focus_app", max_auto=Tier.L0) is False
    assert requires_confirm("focus_app", max_auto=Tier.L2) is False

    g._tracker("test").observe("screenshot")
    assert g._tracker("test").tainted is True

    result = g.run("focus_app", {"app": "chrome"}, source="test")
    assert result.get("ok") is True, result
    assert result.get("needs_confirm") in (None, False)
    assert "confirm_id" not in result
    assert "nonce_code" not in result
    assert "nonce_prompt" not in result
    assert log == [("focus_app", {"app": "chrome"})]


def test_focus_app_skips_second_docker_exec_after_fail(jarvis_env):
    from app.jarvis.computer import (
        bind_desktop_backend,
        linux_focus_app,
        note_focus_fail,
        recent_focus_fail,
        reset_computer_state,
        set_computer_exec,
        JARVIS_COMPUTER,
    )

    reset_computer_state()
    bind_desktop_backend(JARVIS_COMPUTER)
    calls: list[list[str]] = []

    def fake(inner, **_kwargs):
        calls.append(list(inner))
        return {"ok": False, "error": "docker exec failed"}

    set_computer_exec(fake)
    first = linux_focus_app(app="chrome")
    assert first.get("ok") is False
    assert first.get("focused") is False
    assert "docker exec failed" not in str(first.get("error") or "").lower()
    assert "no visible window" in str(first.get("error") or "").lower()
    assert recent_focus_fail("chrome") is True
    assert len(calls) == 1

    second = linux_focus_app(app="chrome")
    assert second.get("ok") is False
    assert second.get("skipped") is True
    assert "not retrying docker exec" in str(second.get("error") or "")
    assert len(calls) == 1

    note_focus_fail("chrome")
    reset_computer_state()
    assert recent_focus_fail("chrome") is False


def test_focus_app_unknown_returns_ok_false(jarvis_env):
    from app.jarvis.desktop import focus_app
    from app.jarvis.gateway import ToolGateway

    log = []
    _fake_focus(log)
    g = ToolGateway()
    result = g.run("focus_app", {"app": "not-a-real-app-xyz"}, source="test")
    assert result.get("ok") is False, result
    assert result.get("needs_confirm") in (None, False)
    assert "confirm_id" not in result
    assert "no visible window" in str(result.get("error") or "").lower()

    direct = focus_app(app="not-a-real-app-xyz")
    assert direct.get("ok") is False


def test_pytest_does_not_call_real_set_foreground(jarvis_env, monkeypatch):
    from app.jarvis import desktop

    desktop.reset_input_backend()
    called = {"win": 0}

    def boom(**kwargs):
        called["win"] += 1
        raise AssertionError("real SetForegroundWindow must not run in pytest")

    monkeypatch.setattr(desktop, "_win_focus_app", boom)
    result = desktop.focus_app(app="chrome")
    assert result.get("ok") is False
    assert "test" in str(result.get("error") or "").lower()
    assert called["win"] == 0


def test_focus_app_in_specs_tiers_and_look_loop():
    from app.jarvis.permissions import TOOL_TIERS, Tier
    from app.jarvis.realtime import tools_for_realtime
    from app.jarvis.screen_loop import DESKTOP_JOB_TOOLS, LookLoop, look_decision
    from app.jarvis.tools import TOOL_SPECS

    names = {
        (spec.get("function") or {}).get("name")
        for spec in TOOL_SPECS
        if spec.get("type") == "function"
    }
    assert "focus_app" in names
    rt = {t["name"] for t in tools_for_realtime()}
    assert "focus_app" in rt
    assert TOOL_TIERS["focus_app"] == Tier.L1
    assert "focus_app" in DESKTOP_JOB_TOOLS

    off = LookLoop("off")
    assert look_decision(off, "focus_app") is False
    assert off.desktop is True


def test_prompts_mention_focus_before_looking():
    from app.jarvis.agent import SYSTEM_PROMPT
    from app.jarvis.realtime import JARVIS_REALTIME_INSTRUCTIONS

    for text in (SYSTEM_PROMPT, JARVIS_REALTIME_INSTRUCTIONS):
        low = text.lower()
        assert "focus_app" in text
        assert "focus" in low and "browser" in low
        assert "do not ask the user to retry" in low
        assert "this chat" in low
        assert "retry run_app" in low
        assert "do not ask the user to click chrome" in low


def test_window_match_process_and_title():
    from app.jarvis.desktop import _window_matches

    assert _window_matches("chrome", "ntv.com.tr - Google Chrome", "chrome")
    assert _window_matches("Chrome", "Inbox - Gmail", "chrome")
    assert _window_matches("ntv.com.tr", "ntv.com.tr - Google Chrome", "chrome")
    assert _window_matches("msedge", "Start", "msedge")
    assert _window_matches("edge", "Bing", "msedge")
    assert _window_matches("notepad", "Untitled - Notepad", "notepad")
    assert not _window_matches("chrome", "Slack", "slack")
    assert not _window_matches("not-a-real-app-xyz", "Desktop", "explorer")


def test_pick_focus_window_skips_untitled_chrome():
    from app.jarvis.desktop import _pick_focus_window

    untitled = (11, "Untitled - Google Chrome", "chrome")
    page = (22, "NTV Haber - Haberler, En Son Güncel Haberler - Google Chrome", "chrome")
    assert _pick_focus_window([untitled, page]) == page
    assert _pick_focus_window([untitled]) == untitled
    assert _pick_focus_window([]) is None


def test_raise_hwnd_set_foreground_success_skips_workarounds():
    from app.jarvis.desktop import FakeRaiseApi, SW_RESTORE, raise_hwnd

    api = FakeRaiseApi(foreground=1, set_fg_ok=True)
    out = raise_hwnd(42, api)
    assert out["focused"] is True
    assert out["raise"] == "SetForegroundWindow"
    assert ("show_window", 42, SW_RESTORE) in api.calls
    assert ("set_foreground", 42) in api.calls
    assert not any(c[0] == "attach_thread_input" for c in api.calls)
    assert not any(c[0] == "alt_pulse" for c in api.calls)


def test_raise_hwnd_attach_thread_input_when_set_foreground_fails():
    from app.jarvis.desktop import FakeRaiseApi, raise_hwnd

    api = FakeRaiseApi(foreground=1, set_fg_ok=False, attach_makes_fg=True)
    out = raise_hwnd(42, api)
    assert out["focused"] is True
    assert out["raise"] == "AttachThreadInput"
    assert "SetForegroundWindow" in out["attempts"]
    assert any(c[0] == "attach_thread_input" and c[3] is True for c in api.calls)
    assert any(c[0] == "attach_thread_input" and c[3] is False for c in api.calls)
    assert not any(c[0] == "alt_pulse" for c in api.calls)


def test_raise_hwnd_alt_pulse_when_attach_fails():
    from app.jarvis.desktop import FakeRaiseApi, raise_hwnd

    api = FakeRaiseApi(foreground=1, set_fg_ok=False, alt_makes_fg=True)
    out = raise_hwnd(42, api)
    assert out["focused"] is True
    assert out["raise"] == "alt"
    assert "AttachThreadInput" in out["attempts"]
    assert any(c[0] == "alt_pulse" for c in api.calls)


def test_raise_hwnd_all_fail_is_not_focused():
    from app.jarvis.desktop import FakeRaiseApi, _FOCUS_FAILED, raise_hwnd

    api = FakeRaiseApi(foreground=1, set_fg_ok=False)
    out = raise_hwnd(42, api)
    assert out["focused"] is False
    assert out["error"] == _FOCUS_FAILED
    assert "SetForegroundWindow" in out["attempts"]
    assert "AttachThreadInput" in out["attempts"]
    assert "alt" in out["attempts"]


def test_focus_app_focused_false_is_not_ok(jarvis_env):
    from app.jarvis.desktop import _FOCUS_FAILED, focus_app, set_input_backend

    def pretend(**kwargs):
        return {
            "ok": True,
            "app": kwargs.get("app"),
            "title": "NTV Haber - Google Chrome",
            "process": "chrome",
            "focused": False,
        }

    set_input_backend({"focus_app": pretend})
    result = focus_app(app="chrome")
    assert result.get("ok") is False, result
    assert result.get("focused") is False
    err = str(result.get("error") or "").lower()
    assert "not brought to the front" in err or _FOCUS_FAILED.split("(")[0].strip() in err
    assert "do not ask the user to click chrome" in err


def test_see_screen_hints_wrong_window_for_jarvis_chat():
    from app.jarvis.screen_loop import looks_like_jarvis_chat

    chat = "Company Org, Berk K., Plugins — this Jarvis chat is in front of Chrome."
    assert looks_like_jarvis_chat(chat) is True
    assert looks_like_jarvis_chat("Chrome is focused. NTV homepage headlines.") is False


@pytest.mark.asyncio
async def test_see_screen_result_sets_wrong_window_hint(jarvis_env):
    from app.jarvis.screen_loop import run_see_screen

    desc = "The Jarvis chat is showing Company Org, Berk K., and Plugins. Chrome is behind."

    async def fake_post():
        return {"choices": [{"message": {"content": desc}}]}

    shot = {
        "ok": True,
        "path": "Exports/screenshots/x.png",
        "png_base64_full": base64.b64encode(_PNG).decode("ascii"),
    }
    result = await run_see_screen(
        shot, workspace_root=jarvis_env, user_goal="", http_post=fake_post
    )
    assert result.get("ok") is True, result
    assert result.get("looks_like_wrong_window") is True
    hint = str(result.get("hint") or "")
    assert "focus_app" in hint
    assert "retry run_app" in hint.lower()
    assert "do not ask the user to click chrome" in hint.lower()
