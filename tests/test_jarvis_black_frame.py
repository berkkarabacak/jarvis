"""ORCH-378: screenshot/see_screen must not treat a black frame as a look."""

from __future__ import annotations

import io
import json

import pytest
from PIL import Image


def _png_bytes(color: tuple[int, int, int], size: tuple[int, int] = (32, 24)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _black_png() -> bytes:
    return _png_bytes((0, 0, 0), (64, 40))


def _color_png() -> bytes:
    return _png_bytes((200, 40, 40), (64, 40))


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

    from app.jarvis.capture import reset_capture_backend

    reset_capture_backend()
    yield root
    reset_capture_backend()


def test_all_black_png_fixture_is_flagged(tmp_path):
    from app.jarvis.capture import is_near_black

    path = tmp_path / "black.png"
    raw = _black_png()
    path.write_bytes(raw)
    assert is_near_black(raw) is True
    assert is_near_black(path) is True
    assert is_near_black(_image((0, 0, 0))) is True


def test_unreadable_bytes_are_not_a_black_frame():
    from app.jarvis.capture import is_near_black

    assert is_near_black(None) is False
    assert is_near_black(b"hello") is False
    assert is_near_black(b"") is False


def test_non_black_png_fixture_is_not_flagged(tmp_path):
    from app.jarvis.capture import is_near_black

    path = tmp_path / "red.png"
    raw = _color_png()
    path.write_bytes(raw)
    assert is_near_black(raw) is False
    assert is_near_black(path) is False
    assert is_near_black(_image((200, 40, 40))) is False
    assert is_near_black(_image((255, 255, 255))) is False


def test_near_black_allows_a_few_dark_pixels_but_flags_solid_black():
    from app.jarvis.capture import is_near_black

    almost = Image.new("RGB", (64, 64), (0, 0, 0))
    almost.putpixel((0, 0), (12, 12, 12))
    assert is_near_black(almost) is True
    page = Image.new("RGB", (64, 64), (0, 0, 0))
    for x in range(64):
        page.putpixel((x, 8), (240, 240, 240))
    assert is_near_black(page) is False


def test_screenshot_retries_window_when_desktop_is_black(ws):
    from app.jarvis.capture import set_capture_backend
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, _screenshot
    from app.jarvis.workspace import Workspace

    calls: list[str] = []

    def desktop():
        calls.append("desktop")
        return _image((0, 0, 0), (80, 50))

    def window():
        calls.append("window")
        return _image((30, 160, 80), (80, 50))

    set_capture_backend({"desktop": desktop, "window": window})
    ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))
    result = _screenshot(ctx, {})
    assert result.get("ok") is True, result
    assert result.get("capture") == "window"
    assert calls == ["desktop", "window"]
    saved = ws / result["path"]
    assert saved.is_file()
    from app.jarvis.capture import is_near_black

    assert is_near_black(saved) is False


def test_screenshot_black_desktop_and_window_is_ok_false(ws):
    from app.jarvis.capture import BLACK_FRAME_ERROR, set_capture_backend
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, _screenshot
    from app.jarvis.workspace import Workspace

    set_capture_backend(
        {
            "desktop": lambda: _image((0, 0, 0)),
            "window": lambda: _image((0, 0, 0)),
        }
    )
    ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))
    result = _screenshot(ctx, {})
    assert result.get("ok") is False
    assert result.get("black_frame") is True
    assert result.get("error") == BLACK_FRAME_ERROR
    assert "invent headlines" in result["error"]
    assert not result.get("png_base64_full")
    assert not result.get("path")


def test_screenshot_uses_desktop_when_it_has_pixels(ws):
    from app.jarvis.capture import set_capture_backend
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, _screenshot
    from app.jarvis.workspace import Workspace

    calls: list[str] = []

    def desktop():
        calls.append("desktop")
        return _image((10, 80, 200))

    def window():
        calls.append("window")
        raise AssertionError("window grab must not run when desktop has pixels")

    set_capture_backend({"desktop": desktop, "window": window})
    ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))
    result = _screenshot(ctx, {})
    assert result.get("ok") is True, result
    assert result.get("capture") == "desktop"
    assert calls == ["desktop"]


def test_screenshot_does_not_grab_real_screen_during_pytest(ws, monkeypatch):
    from app.jarvis import capture as cap
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, _screenshot
    from app.jarvis.workspace import Workspace

    cap.reset_capture_backend()

    def boom(*_a, **_k):
        raise AssertionError("OS screen grab must not run in tests")

    monkeypatch.setattr(cap, "_os_grab_desktop", boom)
    monkeypatch.setattr(cap, "_os_grab_window", boom)
    ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))
    result = _screenshot(ctx, {})
    assert result.get("ok") is False
    assert result.get("black_frame") is True
    assert "invent headlines" in (result.get("error") or "")


@pytest.mark.asyncio
async def test_run_see_screen_rejects_black_png_without_vision(ws):
    from app.jarvis.capture import BLACK_FRAME_ERROR
    from app.jarvis.screen_loop import run_see_screen

    path = ws / "Exports" / "screenshots" / "black.png"
    path.parent.mkdir(parents=True)
    raw = _black_png()
    path.write_bytes(raw)

    async def boom():
        raise AssertionError("vision must not run on a black frame")

    result = await run_see_screen(
        {"ok": True, "path": "Exports/screenshots/black.png", "bytes": len(raw)},
        workspace_root=ws,
        user_goal="name the ntv headlines",
        http_post=boom,
    )
    assert result.get("ok") is False
    assert result.get("black_frame") is True
    assert result.get("error") == BLACK_FRAME_ERROR
    assert not result.get("vision_description")
    assert "invent headlines" in result["error"]


def test_see_screen_tool_returns_error_on_black_capture(ws, monkeypatch):
    from app.jarvis.capture import BLACK_FRAME_ERROR, set_capture_backend
    from app.jarvis.memory import JarvisMemory
    from app.jarvis.tools import ToolContext, run_tool
    from app.jarvis.workspace import Workspace
    import app.jarvis.screen_loop as sl

    set_capture_backend(
        {
            "desktop": lambda: _image((0, 0, 0)),
            "window": lambda: _image((0, 0, 0)),
        }
    )

    async def boom(png_bytes, *, user_goal="", http_post=None):
        raise AssertionError("vision must not run on a black frame")

    monkeypatch.setattr(sl, "vision_describe_png", boom)
    ctx = ToolContext(Workspace(ws), JarvisMemory(ws / "Memory" / "j.db"))
    raw = run_tool(ctx, "see_screen", {"goal": "name headlines"})
    data = json.loads(raw)
    assert data.get("ok") is False, data
    assert data.get("black_frame") is True
    assert data.get("error") == BLACK_FRAME_ERROR
    assert not data.get("vision_description")


def test_prompts_say_do_not_invent_headlines_on_black_frame():
    from app.jarvis.agent import SYSTEM_PROMPT
    from app.jarvis.realtime import JARVIS_REALTIME_INSTRUCTIONS

    for text in (SYSTEM_PROMPT, JARVIS_REALTIME_INSTRUCTIONS):
        low = text.lower()
        assert "black_frame" in low
        assert "do not invent headlines" in low
