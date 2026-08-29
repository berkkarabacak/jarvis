"""about:blank / empty / Untitled is not a loaded Chrome page."""

from __future__ import annotations

import json

import pytest
from PIL import Image


EXAMPLE = "https://example.com"
WIKI = "https://en.wikipedia.org/wiki/Example"
FAKE_CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


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
    monkeypatch.delenv("JARVIS_ALLOW_REAL_INPUT", raising=False)

    from app.jarvis.capture import reset_capture_backend
    from app.jarvis.desktop import reset_input_backend
    from app.jarvis.tools import reset_chrome_exe, reset_launch_backend, set_chrome_exe

    reset_capture_backend()
    reset_input_backend()
    reset_launch_backend()
    set_chrome_exe(FAKE_CHROME)
    yield root
    reset_capture_backend()
    reset_input_backend()
    reset_launch_backend()
    reset_chrome_exe()


def test_blank_title_is_not_a_loaded_page():
    from app.jarvis.desktop import (
        BLANK_PAGE_ERROR,
        has_loaded_page_window,
        is_placeholder_title,
        set_input_backend,
    )

    assert is_placeholder_title("about:blank - Google Chrome") is True
    assert is_placeholder_title("about:blank") is True
    assert is_placeholder_title("") is True
    assert is_placeholder_title("   ") is True
    assert is_placeholder_title("Untitled - Google Chrome") is True
    assert is_placeholder_title("Untitled") is True
    assert is_placeholder_title("Adsız - Google Chrome") is True
    assert is_placeholder_title("Adsız") is True
    assert is_placeholder_title("Adsiz - Google Chrome") is True
    assert is_placeholder_title("New Tab - Google Chrome") is True
    assert is_placeholder_title("Bu sayfa Ayrılsın mı?") is True
    assert is_placeholder_title("Bu sayfa Ayrılsın mı? - Google Chrome") is True
    assert is_placeholder_title("Leave this page?") is True
    assert is_placeholder_title("Leave this page? - Google Chrome") is True
    assert is_placeholder_title("Çevrildi") is True
    assert is_placeholder_title("Çevrildi - Google Chrome") is True
    assert is_placeholder_title("Cevrildi - Google Chrome") is True
    assert is_placeholder_title("Sayfalar geri yüklensin mi?") is True
    assert is_placeholder_title("Sayfalar geri yüklensin mi? - Google Chrome") is True
    assert is_placeholder_title("Restore pages?") is True
    assert is_placeholder_title("Restore pages? - Google Chrome") is True
    assert is_placeholder_title("Bu sayfa çevrilsin mi?") is True
    assert is_placeholder_title("Bu sayfa çevrilsin mi? - Google Chrome") is True
    assert is_placeholder_title("Translate this page?") is True
    assert is_placeholder_title("Translate this page? - Google Chrome") is True
    assert is_placeholder_title("Example Domain - Google Chrome") is False
    assert is_placeholder_title("Moon - Wikipedia - Google Chrome") is False
    assert is_placeholder_title("Wikipedia - Google Chrome") is False
    assert is_placeholder_title("ntv.com.tr - Google Chrome") is False
    assert "not a loaded page" in BLANK_PAGE_ERROR.lower()
    assert "about:blank" in BLANK_PAGE_ERROR.lower()
    assert "do not invent page text" in BLANK_PAGE_ERROR.lower()

    set_input_backend(
        {
            "list_windows": lambda app="": [
                (11, "about:blank - Google Chrome", "chrome"),
            ]
        }
    )
    assert has_loaded_page_window(app="chrome") is False

    set_input_backend(
        {
            "list_windows": lambda app="": [
                (11, "about:blank - Google Chrome", "chrome"),
                (22, "Example Domain - Google Chrome", "chrome"),
            ]
        }
    )
    assert has_loaded_page_window(app="chrome") is True

    set_input_backend(
        {"list_windows": lambda app="": [(11, "Untitled - Google Chrome", "chrome")]}
    )
    assert has_loaded_page_window(app="chrome") is False

    set_input_backend(
        {"list_windows": lambda app="": [(11, "Adsız - Google Chrome", "chrome")]}
    )
    assert has_loaded_page_window(app="chrome") is False

    set_input_backend(
        {"list_windows": lambda app="": [(11, "Bu sayfa Ayrılsın mı?", "chrome")]}
    )
    assert has_loaded_page_window(app="chrome") is False

    set_input_backend(
        {"list_windows": lambda app="": [(11, "Leave this page?", "chrome")]}
    )
    assert has_loaded_page_window(app="chrome") is False

    set_input_backend(
        {"list_windows": lambda app="": [(11, "Çevrildi - Google Chrome", "chrome")]}
    )
    assert has_loaded_page_window(app="chrome") is False

    set_input_backend(
        {"list_windows": lambda app="": [(11, "Sayfalar geri yüklensin mi?", "chrome")]}
    )
    assert has_loaded_page_window(app="chrome") is False

    set_input_backend(
        {"list_windows": lambda app="": [(11, "Restore pages?", "chrome")]}
    )
    assert has_loaded_page_window(app="chrome") is False

    set_input_backend(
        {"list_windows": lambda app="": [(11, "Bu sayfa çevrilsin mi?", "chrome")]}
    )
    assert has_loaded_page_window(app="chrome") is False

    set_input_backend(
        {"list_windows": lambda app="": [(11, "Translate this page?", "chrome")]}
    )
    assert has_loaded_page_window(app="chrome") is False


def test_live_leave_page_title_and_mojibake_are_placeholders():
    """Exact XPS13 leave-page title, plus encoding-mangled audit-log forms."""
    from app.jarvis.desktop import is_placeholder_title

    live = "Bu sayfa Ayrılsın mı?"
    assert is_placeholder_title(live) is True
    # UTF-8 bytes of ı (C4 B1) read as cp1252 — reproduced from the live title.
    mojibake = live.encode("utf-8").decode("cp1252")
    assert mojibake == "Bu sayfa AyrÄ±lsÄ±n mÄ±?"
    assert is_placeholder_title(mojibake) is True
    # ASCII fold and the audit-log lookalike (ı/ş mangled to e/i).
    assert is_placeholder_title("Bu sayfa Ayrilsin mi?") is True
    assert is_placeholder_title("Bu sayfa Aevrilsin mi?") is True
    assert is_placeholder_title("adsiz") is True
    assert is_placeholder_title("Example Domain - Google Chrome") is False
    assert is_placeholder_title("Moon - Wikipedia - Google Chrome") is False


def test_restore_and_translate_titles_are_placeholders_not_leave_page():
    """XPS13 restore/translate dialogs are not-loaded; Escape-dismissable, unlike leave-page."""
    from app.jarvis.desktop import is_dismissible_chrome_dialog, is_placeholder_title

    restore_tr = "Sayfalar geri yüklensin mi?"
    translate_tr = "Bu sayfa çevrilsin mi?"
    for title in (
        restore_tr,
        "Restore pages?",
        "Restore pages? - Google Chrome",
        translate_tr,
        "Translate this page?",
        "Translate this page? - Google Chrome",
    ):
        assert is_placeholder_title(title) is True, title
        assert is_dismissible_chrome_dialog(title) is True, title

    # UTF-8 of ü (C3 BC) / ç (C3 A7) read as cp1252.
    restore_mojibake = restore_tr.encode("utf-8").decode("cp1252")
    translate_mojibake = translate_tr.encode("utf-8").decode("cp1252")
    assert is_placeholder_title(restore_mojibake) is True
    assert is_placeholder_title(translate_mojibake) is True
    assert is_dismissible_chrome_dialog(restore_mojibake) is True
    assert is_dismissible_chrome_dialog(translate_mojibake) is True

    assert is_dismissible_chrome_dialog("Bu sayfa Ayrılsın mı?") is False
    assert is_dismissible_chrome_dialog("Leave this page?") is False
    assert is_dismissible_chrome_dialog("Çevrildi - Google Chrome") is False
    assert is_dismissible_chrome_dialog("Adsız - Google Chrome") is False
    assert is_dismissible_chrome_dialog("about:blank - Google Chrome") is False
    assert is_dismissible_chrome_dialog("Example Domain - Google Chrome") is False
    assert is_dismissible_chrome_dialog("Moon - Wikipedia - Google Chrome") is False
    assert is_placeholder_title("Example Domain - Google Chrome") is False
    assert is_placeholder_title("Moon - Wikipedia - Google Chrome") is False


def test_preferred_capture_skips_blank_when_last_run_app_has_url(ws):
    from app.jarvis.capture import (
        capture_screen,
        remember_look_target,
        set_capture_backend,
    )

    remember_look_target(app="chrome", url=EXAMPLE)
    printed: list[int] = []

    def list_windows():
        return [
            (11, "about:blank - Google Chrome", "chrome"),
            (22, "Example Domain - Google Chrome", "chrome"),
        ]

    def print_window(hwnd):
        printed.append(int(hwnd))
        if int(hwnd) == 11:
            return _image((250, 250, 250), (80, 50))
        return _image((200, 40, 40), (80, 50))

    set_capture_backend(
        {
            "desktop": lambda: (_ for _ in ()).throw(
                AssertionError("desktop must not run")
            ),
            "list_windows": list_windows,
            "print_window": print_window,
        }
    )
    result = capture_screen(goal="name the headlines")
    assert result.ok is True, result
    assert result.title.startswith("Example Domain")
    assert 11 not in printed
    assert 22 in printed


def test_preferred_capture_skips_about_blank_when_goal_has_url(ws):
    from app.jarvis.capture import capture_screen, set_capture_backend

    blank = (11, "about:blank - Google Chrome", "chrome")
    page = (22, "Example Domain - Google Chrome", "chrome")
    printed: list[int] = []

    def list_windows():
        return [blank, page]

    def print_window(hwnd):
        printed.append(int(hwnd))
        if int(hwnd) == 11:
            return _image((250, 250, 250), (80, 50))  # white about:blank
        return _image((200, 40, 40), (80, 50))

    def desktop():
        raise AssertionError("desktop must not substitute for about:blank")

    set_capture_backend(
        {
            "desktop": desktop,
            "list_windows": list_windows,
            "print_window": print_window,
        }
    )
    result = capture_screen(goal=EXAMPLE)
    assert result.ok is True, result
    assert result.title.startswith("Example Domain")
    assert result.process == "chrome"
    assert 22 in printed
    assert 11 not in printed


def test_preferred_capture_blank_only_is_not_a_loaded_page(ws):
    from app.jarvis.desktop import BLANK_PAGE_ERROR
    from app.jarvis.capture import capture_screen, set_capture_backend

    printed: list[int] = []

    def list_windows():
        return [(11, "about:blank - Google Chrome", "chrome")]

    def print_window(hwnd):
        printed.append(int(hwnd))
        return _image((250, 250, 250), (80, 50))

    set_capture_backend(
        {
            "desktop": lambda: (_ for _ in ()).throw(
                AssertionError("desktop must not run")
            ),
            "list_windows": list_windows,
            "print_window": print_window,
        }
    )
    result = capture_screen(goal=EXAMPLE)
    assert result.ok is False, result
    assert result.black_frame is False
    assert result.error == BLANK_PAGE_ERROR
    assert "about:blank" in (result.title or "").lower()
    assert printed == []


def test_see_screen_skips_about_blank_when_url_in_goal(ws, monkeypatch):
    from app.jarvis.capture import set_capture_backend
    from app.jarvis.desktop import BLANK_PAGE_ERROR
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, run_tool
    from app.jarvis.workspace import Workspace
    import app.jarvis.screen_loop as sl

    printed: list[int] = []

    def list_windows():
        return [
            (11, "about:blank - Google Chrome", "chrome"),
            (22, "Example Domain - Google Chrome", "chrome"),
        ]

    def print_window(hwnd):
        printed.append(int(hwnd))
        if int(hwnd) == 11:
            return _image((250, 250, 250), (64, 40))
        return _image((220, 30, 30), (64, 40))

    set_capture_backend(
        {
            "desktop": lambda: (_ for _ in ()).throw(
                AssertionError("desktop must not run")
            ),
            "list_windows": list_windows,
            "print_window": print_window,
        }
    )

    async def fake_vision(png_bytes, *, user_goal="", http_post=None):
        return "Example Domain is the page heading."

    monkeypatch.setattr(sl, "vision_describe_png", fake_vision)
    ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))
    raw = run_tool(ctx, "see_screen", {"goal": EXAMPLE, "computer": "windows"})
    data = json.loads(raw)
    assert data.get("ok") is True, data
    assert "Example Domain" in (data.get("title") or "")
    assert "Example Domain" in (data.get("vision_description") or "")
    assert 11 not in printed
    assert 22 in printed
    assert BLANK_PAGE_ERROR not in str(data.get("error") or "")


def test_looks_like_blank_page_ignores_vision_essay():
    from app.jarvis.screen_loop import looks_like_blank_page

    essay = (
        "A Restore pages dialog sits over the BBC homepage. "
        "World news headlines are visible behind it. "
        "A cookie banner is at the bottom."
    )
    assert looks_like_blank_page(essay) is False
    assert looks_like_blank_page("Restore pages?") is False
    assert looks_like_blank_page("Sayfalar geri yüklensin mi?") is False
    assert looks_like_blank_page("about:blank - Google Chrome") is True
    assert looks_like_blank_page("Untitled - Google Chrome") is True


@pytest.mark.asyncio
async def test_see_screen_keeps_restore_vision_when_title_empty(ws, monkeypatch):
    """Hosted Talk: desktop grab has no HWND title; vision mentions Restore + the page."""
    from app.jarvis.capture import remember_look_target
    from app.jarvis.desktop import BLANK_PAGE_ERROR
    from app.jarvis.screen_loop import run_see_screen
    import app.jarvis.screen_loop as sl

    remember_look_target(app="chrome", url="https://www.bbc.com")

    async def fake_vision(png_bytes, *, user_goal="", http_post=None):
        return (
            "A Restore pages dialog sits over the BBC homepage. "
            "World news headlines are visible behind it. "
            "A cookie banner is at the bottom."
        )

    monkeypatch.setattr(sl, "vision_describe_png", fake_vision)
    looked = await run_see_screen(
        {"ok": True, "title": "", "path": ""},
        workspace_root=ws,
        user_goal="what do you see on your screen",
    )
    assert looked.get("ok") is True, looked
    assert "BBC" in (looked.get("vision_description") or "")
    assert "Restore pages" in (looked.get("vision_description") or "")
    assert BLANK_PAGE_ERROR not in str(looked.get("error") or "")
    assert looked.get("looks_like_blank_page") is not True


def test_see_screen_dismisses_restore_then_looks_again(ws, monkeypatch):
    """Restore pages? on the VM: Escape, then a fresh look. He speaks from vision."""
    from app.jarvis.capture import set_capture_backend
    from app.jarvis.computer import JARVIS_COMPUTER, bind_desktop_backend, reset_computer_state
    from app.jarvis.desktop import set_input_backend
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, run_tool
    from app.jarvis.workspace import Workspace
    import app.jarvis.screen_loop as sl

    bind_desktop_backend(JARVIS_COMPUTER)
    n = {"i": 0}
    sent: list[str] = []

    def desktop():
        n["i"] += 1
        return _image((200, 40, 40), (80, 50))

    def list_windows():
        if n["i"] >= 2:
            return [(22, "BBC - Home - Chromium", "x11")]
        return [(11, "Restore pages?", "x11")]

    def fake_keys(**kwargs):
        combo = str(kwargs.get("combo") or "")
        sent.append(combo)
        return {"ok": True, "combo": combo}

    async def fake_vision(png_bytes, *, user_goal="", http_post=None):
        if n["i"] >= 2:
            return (
                "BBC homepage. A World news headline is on the page. "
                "A cookie dialog sits at the bottom."
            )
        return (
            "Chrome shows Restore pages? BBC World is visible behind the dialog. "
            "A cookie banner sits at the bottom of the page."
        )

    set_capture_backend(
        {
            "desktop": desktop,
            "list_windows": list_windows,
            "print_window": lambda hwnd: (_ for _ in ()).throw(
                AssertionError("hosted look grabs the desktop")
            ),
        }
    )
    set_input_backend({"keys": fake_keys, "list_windows": lambda app="": list_windows()})
    monkeypatch.setattr(sl, "vision_describe_png", fake_vision)
    try:
        ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))
        raw = run_tool(ctx, "see_screen", {"goal": "what do you see on your screen"})
        data = json.loads(raw)
        assert data.get("ok") is True, data
        assert "BBC" in (data.get("vision_description") or "")
        assert "I could not see the screen" not in str(data)
        assert sent == ["escape"]
        assert n["i"] >= 2
    finally:
        reset_computer_state()


def test_see_screen_keeps_real_title_even_if_vision_mentions_leave_page(ws, monkeypatch):
    """Live fail: title was Example Domain / Moon, see_screen still BLANK_PAGE_ERROR."""
    from app.jarvis.capture import set_capture_backend
    from app.jarvis.desktop import BLANK_PAGE_ERROR
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, run_tool
    from app.jarvis.workspace import Workspace
    import app.jarvis.screen_loop as sl

    set_capture_backend(
        {
            "desktop": lambda: (_ for _ in ()).throw(
                AssertionError("desktop must not run")
            ),
            "list_windows": lambda: [
                (22, "Example Domain - Google Chrome", "chrome")
            ],
            "print_window": lambda hwnd: _image((220, 30, 30), (64, 40)),
        }
    )

    async def fake_vision(png_bytes, *, user_goal="", http_post=None):
        return "Bu sayfa Ayrılsın mı? Leave this page?"

    monkeypatch.setattr(sl, "vision_describe_png", fake_vision)
    ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))
    raw = run_tool(ctx, "see_screen", {"goal": EXAMPLE, "computer": "windows"})
    data = json.loads(raw)
    assert data.get("ok") is True, data
    assert "Example Domain" in (data.get("title") or "")
    assert data.get("vision_description")
    assert BLANK_PAGE_ERROR not in str(data.get("error") or "")


def test_pick_focus_window_skips_adsiz_and_leave_page():
    from app.jarvis.desktop import _pick_focus_window

    adsiz = (11, "Adsız - Google Chrome", "chrome")
    leave = (12, "Bu sayfa Ayrılsın mı?", "chrome")
    mojibake = (13, "Bu sayfa Aevrilsin mi?", "chrome")
    translated = (14, "Çevrildi - Google Chrome", "chrome")
    restore = (15, "Sayfalar geri yüklensin mi?", "chrome")
    translate = (16, "Bu sayfa çevrilsin mi?", "chrome")
    page = (22, "Example Domain - Google Chrome", "chrome")
    assert _pick_focus_window(
        [adsiz, leave, mojibake, translated, restore, translate, page]
    ) == page
    assert _pick_focus_window([adsiz]) == adsiz
    assert _pick_focus_window([leave]) == leave
    assert _pick_focus_window([translated]) == translated
    assert _pick_focus_window([restore]) == restore
    assert _pick_focus_window([translate]) == translate


def test_wait_for_loaded_page_skips_adsiz_and_leave_page_then_accepts_title(ws):
    from app.jarvis.desktop import set_input_backend
    from app.jarvis.tools import _wait_for_loaded_page

    n = {"i": 0}

    def list_windows(app=""):
        n["i"] += 1
        if n["i"] == 1:
            return [(11, "Adsız - Google Chrome", "chrome")]
        if n["i"] == 2:
            return [(11, "Bu sayfa Ayrılsın mı?", "chrome")]
        if n["i"] == 3:
            return [(11, "Leave this page?", "chrome")]
        return [(11, "Example Domain - Google Chrome", "chrome")]

    set_input_backend({"list_windows": list_windows})
    loaded = _wait_for_loaded_page("chrome", timeout_s=2.0)
    assert loaded.get("ok") is True, loaded
    assert loaded.get("page_ready") is True
    assert loaded.get("window") is True
    assert "Example Domain" in (loaded.get("title") or "")
    assert n["i"] >= 4


def test_wait_for_loaded_page_escapes_restore_then_accepts_title(ws):
    from app.jarvis.desktop import set_input_backend
    from app.jarvis.tools import _wait_for_loaded_page

    sent: list[str] = []

    def fake_keys(**kwargs):
        combo = str(kwargs.get("combo") or "")
        sent.append(combo)
        return {"ok": True, "combo": combo}

    def list_windows(app=""):
        if sent:
            return [(11, "Moon - Wikipedia - Google Chrome", "chrome")]
        return [(11, "Sayfalar geri yüklensin mi?", "chrome")]

    set_input_backend({"list_windows": list_windows, "keys": fake_keys})
    loaded = _wait_for_loaded_page("chrome", timeout_s=2.0)
    assert loaded.get("ok") is True, loaded
    assert loaded.get("page_ready") is True
    assert "Moon" in (loaded.get("title") or "")
    assert sent == ["escape"]


def test_wait_for_loaded_page_escapes_translate_then_accepts_title(ws):
    from app.jarvis.desktop import set_input_backend
    from app.jarvis.tools import _wait_for_loaded_page

    sent: list[str] = []

    def fake_keys(**kwargs):
        combo = str(kwargs.get("combo") or "")
        sent.append(combo)
        return {"ok": True, "combo": combo}

    def list_windows(app=""):
        if sent:
            return [(11, "Example Domain - Google Chrome", "chrome")]
        return [(11, "Translate this page?", "chrome")]

    set_input_backend({"list_windows": list_windows, "keys": fake_keys})
    loaded = _wait_for_loaded_page("chrome", timeout_s=2.0)
    assert loaded.get("ok") is True, loaded
    assert loaded.get("page_ready") is True
    assert "Example Domain" in (loaded.get("title") or "")
    assert sent == ["escape"]


def test_wait_for_loaded_page_escape_once_if_restore_stays(ws):
    from app.jarvis.desktop import set_input_backend
    from app.jarvis.tools import _wait_for_loaded_page

    sent: list[str] = []

    def fake_keys(**kwargs):
        sent.append(str(kwargs.get("combo") or ""))
        return {"ok": True, "combo": kwargs.get("combo")}

    set_input_backend(
        {
            "list_windows": lambda app="": [(11, "Restore pages?", "chrome")],
            "keys": fake_keys,
        }
    )
    loaded = _wait_for_loaded_page("chrome", timeout_s=0.6)
    assert loaded.get("ok") is False, loaded
    assert loaded.get("page_ready") is False
    assert "Restore pages" in (loaded.get("title") or "")
    assert sent == ["escape"]


def test_wait_for_loaded_page_does_not_escape_leave_page(ws):
    from app.jarvis.desktop import set_input_backend
    from app.jarvis.tools import _wait_for_loaded_page

    sent: list[str] = []

    def fake_keys(**kwargs):
        sent.append(str(kwargs.get("combo") or ""))
        return {"ok": True, "combo": kwargs.get("combo")}

    set_input_backend(
        {
            "list_windows": lambda app="": [(11, "Bu sayfa Ayrılsın mı?", "chrome")],
            "keys": fake_keys,
        }
    )
    loaded = _wait_for_loaded_page("chrome", timeout_s=0.4)
    assert loaded.get("ok") is False, loaded
    assert sent == []


def test_run_app_url_adsiz_title_timeout_is_not_ok(ws, monkeypatch):
    import app.jarvis.tools as tools
    from app.jarvis.desktop import BLANK_PAGE_ERROR, set_input_backend
    from app.jarvis.tools import _launch_planned, plan_run_app, reset_launch_backend

    reset_launch_backend()
    set_input_backend(
        {"list_windows": lambda app="": [(11, "Adsız - Google Chrome", "chrome")]}
    )
    monkeypatch.setattr(tools, "_real_launch_allowed", lambda: True)
    monkeypatch.setattr(tools.subprocess, "Popen", lambda *a, **k: object())
    monkeypatch.setattr(tools, "_CHROME_WAIT_S", 0.3)

    plan = plan_run_app({"target": EXAMPLE})
    result = _launch_planned(plan, str(ws))
    assert result.get("ok") is False, result
    assert result.get("window") is True
    assert result.get("page_ready") is False
    assert result.get("error") == BLANK_PAGE_ERROR
    assert "Adsız" in (result.get("title") or "")


def test_keys_ctrl_tab_leave_page_dialog_is_not_ok_when_goal_has_url(ws, monkeypatch):
    import app.jarvis.tools as tools
    from app.jarvis.capture import remember_look_target, set_capture_backend
    from app.jarvis.desktop import BLANK_PAGE_ERROR, set_input_backend
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, _keys
    from app.jarvis.workspace import Workspace

    set_input_backend(
        {
            "keys": lambda **kwargs: {
                "ok": True,
                "combo": kwargs.get("combo"),
                "vk": kwargs.get("vk"),
                "events": kwargs.get("events"),
            },
            "list_windows": lambda app="": [(11, "Bu sayfa Ayrılsın mı?", "chrome")],
        }
    )
    set_capture_backend(
        {
            "desktop": lambda: (_ for _ in ()).throw(
                AssertionError("desktop must not substitute for a leave-page dialog")
            ),
            "list_windows": lambda: [(11, "Bu sayfa Ayrılsın mı?", "chrome")],
            "print_window": lambda hwnd: (_ for _ in ()).throw(
                AssertionError("must not print leave-page dialog")
            ),
        }
    )
    remember_look_target(app="chrome", url=EXAMPLE)
    monkeypatch.setattr(tools, "_TAB_SWITCH_WAIT_S", 0.3)

    ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))
    result = _keys(ctx, {"combo": "ctrl+tab", "goal": EXAMPLE})
    assert result.get("ok") is False, result
    assert result.get("page_ready") is False
    assert result.get("error") == BLANK_PAGE_ERROR
    assert "Ayrılsın" in (result.get("title") or "")


def test_keys_ctrl_tab_mojibake_leave_page_and_cevrildi_are_not_ok(ws, monkeypatch):
    import app.jarvis.tools as tools
    from app.jarvis.capture import remember_look_target
    from app.jarvis.desktop import BLANK_PAGE_ERROR, set_input_backend
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, _keys
    from app.jarvis.workspace import Workspace

    remember_look_target(app="chrome", url=EXAMPLE)
    monkeypatch.setattr(tools, "_TAB_SWITCH_WAIT_S", 0.3)
    ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))

    for title in (
        "Bu sayfa Aevrilsin mi?",
        "Bu sayfa AyrÄ±lsÄ±n mÄ±?",
        "Çevrildi - Google Chrome",
    ):
        set_input_backend(
            {
                "keys": lambda **kwargs: {
                    "ok": True,
                    "combo": kwargs.get("combo"),
                    "vk": kwargs.get("vk"),
                    "events": kwargs.get("events"),
                },
                "list_windows": lambda app="", _title=title: [(11, _title, "chrome")],
            }
        )
        result = _keys(ctx, {"combo": "ctrl+tab", "goal": EXAMPLE})
        assert result.get("ok") is False, (title, result)
        assert result.get("page_ready") is False, title
        assert result.get("error") == BLANK_PAGE_ERROR, title


def test_keys_ctrl_tab_restore_dialog_escape_then_real_title(ws, monkeypatch):
    import app.jarvis.tools as tools
    from app.jarvis.desktop import set_input_backend
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, _keys
    from app.jarvis.workspace import Workspace

    sent: list[str] = []

    def fake_keys(**kwargs):
        combo = str(kwargs.get("combo") or "")
        sent.append(combo)
        return {
            "ok": True,
            "combo": combo,
            "vk": kwargs.get("vk"),
            "events": kwargs.get("events"),
        }

    def list_windows(app=""):
        if "escape" in sent:
            return [(11, "Moon - Wikipedia - Google Chrome", "chrome")]
        return [(11, "Sayfalar geri yüklensin mi?", "chrome")]

    set_input_backend({"keys": fake_keys, "list_windows": list_windows})
    monkeypatch.setattr(tools, "_TAB_SWITCH_WAIT_S", 2.0)

    ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))
    result = _keys(ctx, {"combo": "ctrl+tab", "goal": "https://en.wikipedia.org/wiki/Moon"})
    assert result.get("ok") is True, result
    assert result.get("page_ready") is True
    assert "Moon" in (result.get("title") or "")
    assert sent[0] == "ctrl+tab"
    assert sent.count("escape") == 1


def test_keys_ctrl_tab_translate_dialog_stays_is_not_ok(ws, monkeypatch):
    import app.jarvis.tools as tools
    from app.jarvis.capture import remember_look_target
    from app.jarvis.desktop import BLANK_PAGE_ERROR, set_input_backend
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, _keys
    from app.jarvis.workspace import Workspace

    remember_look_target(app="chrome", url=EXAMPLE)
    monkeypatch.setattr(tools, "_TAB_SWITCH_WAIT_S", 0.4)
    sent: list[str] = []

    def fake_keys(**kwargs):
        combo = str(kwargs.get("combo") or "")
        sent.append(combo)
        return {
            "ok": True,
            "combo": combo,
            "vk": kwargs.get("vk"),
            "events": kwargs.get("events"),
        }

    set_input_backend(
        {
            "keys": fake_keys,
            "list_windows": lambda app="": [(11, "Bu sayfa çevrilsin mi?", "chrome")],
        }
    )
    ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))
    result = _keys(ctx, {"combo": "ctrl+2", "goal": EXAMPLE})
    assert result.get("ok") is False, result
    assert result.get("page_ready") is False
    assert result.get("error") == BLANK_PAGE_ERROR
    assert "çevrilsin" in (result.get("title") or "")
    assert sent[0] == "ctrl+2"
    assert sent.count("escape") == 1


def test_run_app_url_restore_dialog_escape_then_real_title(ws, monkeypatch):
    import app.jarvis.tools as tools
    from app.jarvis.desktop import set_input_backend
    from app.jarvis.tools import _launch_planned, plan_run_app, reset_launch_backend

    reset_launch_backend()
    sent: list[str] = []

    def fake_keys(**kwargs):
        combo = str(kwargs.get("combo") or "")
        sent.append(combo)
        return {"ok": True, "combo": combo}

    def list_windows(app=""):
        if sent:
            return [(11, "Example Domain - Google Chrome", "chrome")]
        return [(11, "Restore pages?", "chrome")]

    set_input_backend({"list_windows": list_windows, "keys": fake_keys})
    monkeypatch.setattr(tools, "_real_launch_allowed", lambda: True)
    monkeypatch.setattr(tools.subprocess, "Popen", lambda *a, **k: object())
    monkeypatch.setattr(tools, "_CHROME_WAIT_S", 2.0)

    plan = plan_run_app({"target": EXAMPLE})
    result = _launch_planned(plan, str(ws))
    assert result.get("ok") is True, result
    assert result.get("page_ready") is True
    assert "Example Domain" in (result.get("title") or "")
    assert sent == ["escape"]


def test_wait_for_loaded_page_skips_blank_then_accepts_title(ws):
    from app.jarvis.desktop import set_input_backend
    from app.jarvis.tools import _wait_for_loaded_page

    n = {"i": 0}

    def list_windows(app=""):
        n["i"] += 1
        if n["i"] < 3:
            return [(11, "about:blank - Google Chrome", "chrome")]
        return [(11, "Example Domain - Google Chrome", "chrome")]

    set_input_backend({"list_windows": list_windows})
    loaded = _wait_for_loaded_page("chrome", timeout_s=2.0)
    assert loaded.get("ok") is True, loaded
    assert loaded.get("page_ready") is True
    assert loaded.get("window") is True
    assert "Example Domain" in (loaded.get("title") or "")


def test_run_app_url_blank_title_timeout_is_not_ok(ws, monkeypatch):
    import app.jarvis.tools as tools
    from app.jarvis.desktop import BLANK_PAGE_ERROR, set_input_backend
    from app.jarvis.tools import _launch_planned, plan_run_app, reset_launch_backend

    reset_launch_backend()
    set_input_backend(
        {
            "list_windows": lambda app="": [
                (11, "about:blank - Google Chrome", "chrome")
            ]
        }
    )
    monkeypatch.setattr(tools, "_real_launch_allowed", lambda: True)
    monkeypatch.setattr(tools.subprocess, "Popen", lambda *a, **k: object())
    monkeypatch.setattr(tools, "_CHROME_WAIT_S", 0.3)

    plan = plan_run_app({"target": EXAMPLE})
    result = _launch_planned(plan, str(ws))
    assert result.get("ok") is False, result
    assert result.get("window") is True
    assert result.get("page_ready") is False
    assert result.get("error") == BLANK_PAGE_ERROR
    assert "do not invent page text" in str(result.get("note") or "").lower()
    assert "about:blank" in (result.get("title") or "").lower()


def test_run_app_url_loaded_title_is_ok(ws, monkeypatch):
    import app.jarvis.tools as tools
    from app.jarvis.desktop import set_input_backend
    from app.jarvis.tools import _launch_planned, plan_run_app, reset_launch_backend

    reset_launch_backend()
    set_input_backend(
        {
            "list_windows": lambda app="": [
                (11, "Example Domain - Google Chrome", "chrome")
            ]
        }
    )
    monkeypatch.setattr(tools, "_real_launch_allowed", lambda: True)
    monkeypatch.setattr(tools.subprocess, "Popen", lambda *a, **k: object())

    plan = plan_run_app({"target": "chrome", "url": WIKI})
    result = _launch_planned(plan, str(ws))
    assert result.get("ok") is True, result
    assert result.get("opened") == WIKI
    assert result.get("window") is True
    assert result.get("page_ready") is True
    assert "Example Domain" in (result.get("title") or "")


def test_launch_backend_blank_title_is_not_ok(ws, monkeypatch):
    from app.jarvis.desktop import BLANK_PAGE_ERROR
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, _run_app, set_launch_backend
    from app.jarvis.workspace import Workspace

    def launch(**kwargs):
        return {
            "ok": True,
            "window": True,
            "title": "about:blank - Google Chrome",
            "started": kwargs.get("cmd"),
            "argv": kwargs.get("argv"),
            "opened": kwargs.get("url"),
        }

    set_launch_backend(launch)
    ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))
    result = _run_app(ctx, {"target": EXAMPLE})
    assert result.get("ok") is False, result
    assert result.get("page_ready") is False
    assert result.get("error") == BLANK_PAGE_ERROR


def test_prompts_say_about_blank_is_not_the_page():
    from app.jarvis.agent import SYSTEM_PROMPT
    from app.jarvis.realtime import JARVIS_REALTIME_INSTRUCTIONS
    from app.jarvis.tools import TOOL_SPECS

    for text in (SYSTEM_PROMPT, JARVIS_REALTIME_INSTRUCTIONS):
        low = text.lower()
        assert "about:blank" in low
        assert "wait or run_app" in low
        assert "do not invent page text" in low
        assert "see_screen" in text

    specs = {
        (s.get("function") or {}).get("name"): (s.get("function") or {}).get("description") or ""
        for s in TOOL_SPECS
        if s.get("type") == "function"
    }
    for name in ("run_app", "see_screen", "keys"):
        low = specs[name].lower()
        assert "about:blank" in low, name
        assert "do not invent page text" in low, name


def test_keys_ctrl_tab_waits_then_blank_is_not_ok_when_goal_has_url(ws, monkeypatch):
    """After a tab switch, about:blank is not a successful look when the goal has a URL."""
    import app.jarvis.tools as tools
    from app.jarvis.capture import remember_look_target, set_capture_backend
    from app.jarvis.desktop import BLANK_PAGE_ERROR, set_input_backend
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, _keys
    from app.jarvis.workspace import Workspace

    desktop_hits = {"n": 0}

    def desktop():
        desktop_hits["n"] += 1
        raise AssertionError("desktop must not substitute for about:blank")

    set_input_backend(
        {
            "keys": lambda **kwargs: {
                "ok": True,
                "combo": kwargs.get("combo"),
                "vk": kwargs.get("vk"),
                "events": kwargs.get("events"),
            },
            "list_windows": lambda app="": [
                (11, "about:blank - Google Chrome", "chrome")
            ],
        }
    )
    set_capture_backend(
        {
            "desktop": desktop,
            "list_windows": lambda: [(11, "about:blank - Google Chrome", "chrome")],
            "print_window": lambda hwnd: (_ for _ in ()).throw(
                AssertionError("must not print about:blank")
            ),
        }
    )
    remember_look_target(app="chrome", url=EXAMPLE)
    monkeypatch.setattr(tools, "_TAB_SWITCH_WAIT_S", 0.3)

    ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))
    result = _keys(ctx, {"combo": "ctrl+tab", "goal": EXAMPLE})
    assert result.get("ok") is False, result
    assert result.get("page_ready") is False
    assert result.get("error") == BLANK_PAGE_ERROR
    assert "do not invent page text" in str(result.get("note") or "").lower()
    assert "about:blank" in (result.get("title") or "").lower()
    assert desktop_hits["n"] == 0


def test_keys_ctrl_tab_waits_then_accepts_loaded_title(ws, monkeypatch):
    import app.jarvis.tools as tools
    from app.jarvis.desktop import set_input_backend
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, _keys
    from app.jarvis.workspace import Workspace

    n = {"i": 0}

    def list_windows(app=""):
        n["i"] += 1
        if n["i"] < 3:
            return [(11, "about:blank - Google Chrome", "chrome")]
        return [(11, "Moon - Wikipedia - Google Chrome", "chrome")]

    set_input_backend(
        {
            "keys": lambda **kwargs: {
                "ok": True,
                "combo": kwargs.get("combo"),
                "vk": kwargs.get("vk"),
                "events": kwargs.get("events"),
            },
            "list_windows": list_windows,
        }
    )
    monkeypatch.setattr(tools, "_TAB_SWITCH_WAIT_S", 2.0)

    ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))
    result = _keys(ctx, {"combo": "ctrl+tab", "goal": "https://en.wikipedia.org/wiki/Moon"})
    assert result.get("ok") is True, result
    assert result.get("page_ready") is True
    assert "Moon" in (result.get("title") or "")
    assert n["i"] >= 3


def test_see_screen_after_keys_blank_is_not_ok_and_not_desktop(ws, monkeypatch):
    import app.jarvis.tools as tools
    from app.jarvis.capture import remember_look_target, set_capture_backend
    from app.jarvis.desktop import BLANK_PAGE_ERROR, set_input_backend
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, _keys, run_tool
    from app.jarvis.workspace import Workspace

    set_input_backend(
        {
            "keys": lambda **kwargs: {
                "ok": True,
                "combo": kwargs.get("combo"),
                "vk": kwargs.get("vk"),
                "events": kwargs.get("events"),
            },
            "list_windows": lambda app="": [
                (11, "about:blank - Google Chrome", "chrome")
            ],
        }
    )
    set_capture_backend(
        {
            "desktop": lambda: (_ for _ in ()).throw(
                AssertionError("desktop must not substitute for about:blank")
            ),
            "list_windows": lambda: [(11, "about:blank - Google Chrome", "chrome")],
            "print_window": lambda hwnd: (_ for _ in ()).throw(
                AssertionError("must not print about:blank")
            ),
        }
    )
    remember_look_target(app="chrome", url=WIKI)
    monkeypatch.setattr(tools, "_TAB_SWITCH_WAIT_S", 0.3)

    ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))
    switched = _keys(ctx, {"combo": "ctrl+tab", "goal": WIKI})
    assert switched.get("ok") is False, switched
    assert switched.get("error") == BLANK_PAGE_ERROR

    raw = run_tool(ctx, "see_screen", {"goal": WIKI, "computer": "windows"})
    data = json.loads(raw)
    assert data.get("ok") is False, data
    assert data.get("page_ready") is False
    assert data.get("error") == BLANK_PAGE_ERROR
    assert not data.get("vision_description")
