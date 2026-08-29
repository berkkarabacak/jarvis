"""ORCH-379: look at the Chrome page, not the desktop."""

from __future__ import annotations

import json

import pytest
from PIL import Image


def _image(color: tuple[int, int, int], size: tuple[int, int] = (32, 24)) -> Image.Image:
    return Image.new("RGB", size, color)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "Jarvis"
    root.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(root))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1:8787")
    monkeypatch.delenv("PUBLIC_GUEST_PROFILE", raising=False)
    monkeypatch.delenv("JARVIS_PUBLIC_CLOUD", raising=False)
    monkeypatch.delenv("JARVIS_ALLOW_REAL_CAPTURE", raising=False)
    monkeypatch.delenv("JARVIS_ALLOW_REAL_LAUNCH", raising=False)

    from app.jarvis.capture import reset_capture_backend
    from app.jarvis.tools import reset_launch_backend

    reset_capture_backend()
    reset_launch_backend()
    yield root
    reset_capture_backend()
    reset_launch_backend()


def test_preferred_needles_from_goal_url():
    from app.jarvis.capture import preferred_needles

    needles = preferred_needles(goal="name headlines on https://www.ntv.com.tr", include_last=False)
    low = {n.lower() for n in needles}
    assert "https://www.ntv.com.tr" in low
    assert "ntv.com.tr" in low
    assert "ntv" in low
    assert "ntv" in {
        n.lower() for n in preferred_needles(goal="name the ntv headlines", include_last=False)
    }


def test_preferred_needles_include_last_run_app_target():
    from app.jarvis.capture import preferred_needles, remember_look_target

    remember_look_target(app="chrome", url="https://www.ntv.com.tr")
    needles = preferred_needles(goal="name the headlines", include_last=True)
    low = {n.lower() for n in needles}
    assert "chrome" in low
    assert "ntv.com.tr" in low
    assert "ntv" in low


def test_is_desktop_or_lock_window():
    from app.jarvis.capture import is_desktop_or_lock_window

    assert is_desktop_or_lock_window("Program Manager", "explorer") is True
    assert is_desktop_or_lock_window("Windows Default Lock Screen", "LockApp") is True
    assert is_desktop_or_lock_window(
        "NTV Haber - Haberler, En Son Güncel Haberler - Google Chrome", "chrome"
    ) is False


def test_preferred_chrome_window_beats_desktop_icons(ws):
    from app.jarvis.capture import capture_screen, set_capture_backend

    calls: list[str] = []

    def desktop():
        calls.append("desktop")
        raise AssertionError("desktop grab must not run for a preferred Chrome look")

    def window(**kwargs):
        calls.append("window")
        assert "chrome" in {str(n).lower() for n in (kwargs.get("needles") or [])} or kwargs.get("app")
        return _image((200, 40, 40), (80, 50))

    set_capture_backend({"desktop": desktop, "window": window})
    result = capture_screen(app="chrome", goal="https://www.ntv.com.tr")
    assert result.ok is True, result
    assert result.method == "window"
    assert result.black_frame is False
    assert "desktop" not in calls
    assert calls == ["window"]


def test_black_chrome_does_not_return_explorer_or_lock(ws):
    from app.jarvis.capture import BLACK_FRAME_ERROR, capture_screen, set_capture_backend

    chrome = (22, "NTV Haber - Haberler, En Son Güncel Haberler - Google Chrome", "chrome")
    explorer = (11, "Program Manager", "explorer")
    lock = (33, "Windows Default Lock Screen", "LockApp")
    printed: list[int] = []

    def list_windows():
        return [explorer, chrome, lock]

    def print_window(hwnd):
        printed.append(int(hwnd))
        if int(hwnd) == 22:
            return _image((0, 0, 0), (80, 50))
        if int(hwnd) == 11:
            return _image((30, 80, 30), (80, 50))  # desktop icons
        return _image((10, 10, 80), (80, 50))  # lock screen, not black

    def desktop():
        raise AssertionError("desktop must not substitute for a black Chrome frame")

    set_capture_backend(
        {
            "desktop": desktop,
            "list_windows": list_windows,
            "print_window": print_window,
        }
    )
    result = capture_screen(goal="ntv.com.tr NTV Haber chrome")
    assert result.ok is False, result
    assert result.black_frame is True
    assert result.error == BLACK_FRAME_ERROR
    assert result.title.startswith("NTV Haber")
    assert result.process == "chrome"
    assert 22 in printed
    assert 11 not in printed
    assert 33 not in printed


def test_see_screen_prefers_last_run_app_chrome(ws, monkeypatch):
    from app.jarvis.capture import remember_look_target, set_capture_backend
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, run_tool
    from app.jarvis.workspace import Workspace
    import app.jarvis.screen_loop as sl

    remember_look_target(app="chrome", url="https://www.ntv.com.tr")
    calls: list[str] = []

    def desktop():
        calls.append("desktop")
        return _image((80, 80, 80), (64, 40))  # desktop icons

    def window(**kwargs):
        calls.append("window")
        needles = [str(n).lower() for n in (kwargs.get("needles") or [])]
        assert "chrome" in needles or "ntv.com.tr" in needles
        return _image((220, 30, 30), (64, 40))

    set_capture_backend({"desktop": desktop, "window": window})

    async def fake_vision(png_bytes, *, user_goal="", http_post=None):
        return "NTV homepage headlines are visible in Chrome."

    monkeypatch.setattr(sl, "vision_describe_png", fake_vision)
    ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))
    raw = run_tool(
        ctx,
        "see_screen",
        {"goal": "name the headlines", "computer": "windows"},
    )
    data = json.loads(raw)
    assert data.get("ok") is True, data
    assert data.get("capture") == "window"
    assert "desktop" not in calls
    assert "NTV homepage" in (data.get("vision_description") or "")


def test_run_app_url_remembers_look_target(ws):
    from app.jarvis.capture import last_look_target
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import (
        ToolContext,
        _run_app,
        set_chrome_exe,
        set_launch_backend,
    )
    from app.jarvis.workspace import Workspace

    set_chrome_exe(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

    def launch(**kwargs):
        return {"ok": True, "started": kwargs.get("cmd"), "argv": kwargs.get("argv"), "window": True}

    set_launch_backend(launch)
    ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))
    result = _run_app(ctx, {"target": "https://www.ntv.com.tr"})
    assert result.get("ok") is True, result
    last = last_look_target()
    assert last.get("app") == "chrome"
    assert "ntv.com.tr" in (last.get("url") or "")


def test_screenshot_preferred_black_is_not_desktop_success(ws):
    from app.jarvis.capture import BLACK_FRAME_ERROR, set_capture_backend
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, _screenshot
    from app.jarvis.workspace import Workspace

    set_capture_backend(
        {
            "desktop": lambda: _image((40, 90, 40), (64, 40)),
            "window": lambda **_k: _image((0, 0, 0), (64, 40)),
        }
    )
    ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))
    result = _screenshot(ctx, {"app": "chrome", "goal": "https://www.ntv.com.tr"})
    assert result.get("ok") is False, result
    assert result.get("black_frame") is True
    assert result.get("error") == BLACK_FRAME_ERROR
    assert not result.get("path")


def test_preferred_capture_does_not_touch_os_during_pytest(ws, monkeypatch):
    from app.jarvis import capture as cap

    cap.reset_capture_backend()

    def boom(*_a, **_k):
        raise AssertionError("OS screen grab / EnumWindows must not run in tests")

    monkeypatch.setattr(cap, "_os_grab_desktop", boom)
    monkeypatch.setattr(cap, "_os_grab_window", boom)
    monkeypatch.setattr(cap, "_win_list_visible_windows", boom)
    monkeypatch.setattr(cap, "_win_print_window", boom)
    monkeypatch.setattr(cap, "_win_candidate_hwnds", boom)
    result = cap.capture_screen(app="chrome", goal="ntv.com.tr")
    assert result.ok is False
    assert "desktop" not in (result.error or "").lower() or "not substituting" in (result.error or "").lower()
