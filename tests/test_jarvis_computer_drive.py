"""ORCH-405 — route look/click/type to Jarvis's one Linux computer."""

from __future__ import annotations

import io

import pytest

from app.jarvis.computer import (
    CLOSE_CHROME_SH,
    JARVIS_COMPUTER,
    WINDOWS,
    activate_desktop_backend,
    bind_desktop_backend,
    bind_job_desktop,
    children_do_not_spawn_computers,
    click_inner_argv,
    close_chrome_inner_argv,
    docker_exec_argv,
    exec_in_computer,
    focus_inner_argv,
    goal_targets_jarvis_computer,
    goal_targets_user_windows,
    keys_inner_argv,
    linux_click,
    linux_close_chrome_windows,
    linux_focus_app,
    linux_keys,
    linux_list_windows,
    linux_run_app,
    linux_scroll,
    linux_type,
    computer_html_file_url,
    is_local_file_url,
    plan_linux_run_app,
    reset_computer_state,
    resolve_desktop_backend,
    screenshot_inner_argv,
    screenshot_png,
    set_computer_exec,
    type_inner_argv,
)


# 1x1 PNG (same idea as other Jarvis vision tests).
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture(autouse=True)
def _reset_computer():
    reset_computer_state()
    yield
    reset_computer_state()


def test_named_user_windows_stays_on_windows():
    assert resolve_desktop_backend(goal="what's on my screen") == WINDOWS
    assert resolve_desktop_backend(goal="look at my Windows PC") == WINDOWS


def test_win32_click_stays_on_windows(monkeypatch):
    import sys

    monkeypatch.setattr(sys, "platform", "win32")
    assert resolve_desktop_backend(goal="click the red button") == WINDOWS


def test_hosted_look_jobs_use_jarvis_computer():
    assert resolve_desktop_backend(goal="what's on your screen") == JARVIS_COMPUTER
    assert resolve_desktop_backend(goal="open chrome and see_screen ntv.com.tr") == JARVIS_COMPUTER
    assert resolve_desktop_backend(
        goal="what's on your screen",
        env={"JARVIS_HOST_OS": "windows"},
    ) == JARVIS_COMPUTER


def test_goal_and_computer_arg_route_to_jarvis_computer():
    assert goal_targets_jarvis_computer("open notepad on your computer")
    assert goal_targets_jarvis_computer("do this on Jarvis's Linux desktop")
    assert goal_targets_user_windows("click on my PC")
    assert resolve_desktop_backend(goal="open chrome on your linux computer") == JARVIS_COMPUTER
    assert resolve_desktop_backend(computer="jarvis") == JARVIS_COMPUTER
    assert resolve_desktop_backend(computer="linux") == JARVIS_COMPUTER
    assert resolve_desktop_backend(computer="windows") == WINDOWS
    assert resolve_desktop_backend(
        goal="open notepad on your computer",
        computer="windows",
    ) == WINDOWS
    assert resolve_desktop_backend(
        goal="click the button",
        env={"JARVIS_DESKTOP_BACKEND": "jarvis-computer"},
    ) == JARVIS_COMPUTER


def test_children_inherit_parent_backend_and_do_not_spawn():
    assert children_do_not_spawn_computers() is True
    bind_job_desktop(goal="type hello on your computer")
    child = resolve_desktop_backend(goal="just type hello", inherit=JARVIS_COMPUTER)
    assert child == JARVIS_COMPUTER
    token = bind_desktop_backend(JARVIS_COMPUTER)
    try:
        assert activate_desktop_backend(goal="type the note") == JARVIS_COMPUTER
    finally:
        from app.jarvis.computer import reset_desktop_backend

        reset_desktop_backend(token)


def test_docker_exec_argv_is_one_named_container_on_display_1():
    argv = docker_exec_argv(["xdotool", "click", "1"])
    assert argv[:2] == ["docker", "exec"]
    assert "run" not in argv
    assert "compose" not in argv
    assert "jarvis-computer" in argv
    assert "DISPLAY=:1" in argv
    assert argv[-3:] == ["xdotool", "click", "1"]
    detached = docker_exec_argv(["mousepad"], detach=True)
    assert "-d" in detached
    assert detached.count("jarvis-computer") == 1


def test_helper_argv_use_xdotool_and_scrot():
    assert click_inner_argv(x=10, y=20, button="left")[:2] == ["xdotool", "mousemove"]
    assert "click" in click_inner_argv(x=10, y=20, button="right")
    assert type_inner_argv(text="hi")[:2] == ["xdotool", "type"]
    keys = keys_inner_argv(combo="ctrl+tab")
    assert keys[:2] == ["xdotool", "key"]
    assert "ctrl+Tab" in keys[-1]
    assert focus_inner_argv(app="mousepad")[0] == "xdotool"
    shot = screenshot_inner_argv()
    assert "scrot" in " ".join(shot)
    assert "jarvis-screen.png" in " ".join(shot)
    close_argv = close_chrome_inner_argv()
    assert close_argv[0] == "sh"
    joined = " ".join(close_argv)
    assert "wmctrl" in joined or "windowclose" in joined or "pkill" in joined
    assert "ctrl+w" not in joined
    assert "Escape" not in joined
    assert "chromium" in CLOSE_CHROME_SH.lower() or "chrome" in CLOSE_CHROME_SH.lower()
    assert "Xvfb" not in CLOSE_CHROME_SH
    assert "xfce" not in CLOSE_CHROME_SH.lower()


def test_exec_seam_drives_click_type_keys_without_docker():
    log: list[list[str]] = []

    def fake(inner, **_kwargs):
        log.append(list(inner))
        return {"ok": True, "stdout": ""}

    set_computer_exec(fake)
    bind_desktop_backend(JARVIS_COMPUTER)
    assert linux_click(x=4, y=8, button="left")["ok"] is True
    typed = linux_type(text="hello")
    assert typed["ok"] is True
    assert typed["typed"] == 5
    assert typed["computer"] == JARVIS_COMPUTER
    keys = linux_keys(combo="ctrl+l")
    assert keys["ok"] is True
    scrolled = linux_scroll(dy=-2)
    assert scrolled["ok"] is True
    focused = linux_focus_app(app="mousepad")
    assert focused["ok"] is True
    assert focused["focused"] is True
    closed = linux_close_chrome_windows()
    assert closed["ok"] is True
    assert closed["method"] == "close-all"
    assert log
    assert any("windowclose" in " ".join(row) or row == ["sh", "-c", CLOSE_CHROME_SH] for row in log)
    assert all(row[0] in {"xdotool", "sh"} for row in log)


def test_screenshot_helper_returns_png_bytes_from_exec_seam():
    def fake(inner, **kwargs):
        assert "scrot" in " ".join(inner)
        return {"ok": True, "stdout": _PNG}

    set_computer_exec(fake)
    grabbed = screenshot_png()
    assert grabbed["ok"] is True
    assert grabbed["png"][:8] == b"\x89PNG\r\n\x1a\n"
    assert grabbed["display"] == ":1"


def test_plan_linux_run_app_maps_chrome_and_notepad():
    chrome = plan_linux_run_app({"target": "chrome", "url": "https://example.com"})
    assert chrome["ok"] is True
    assert chrome["argv"][0] == "/usr/local/bin/chrome"
    assert chrome["argv"][-1] == "https://example.com"
    assert chrome["computer"] == JARVIS_COMPUTER
    local = plan_linux_run_app(
        {"target": "chrome", "url": "file:///home/jarvis/Exports/tetris_03.html"}
    )
    assert local["ok"] is True
    assert local["url"] == "file:///home/jarvis/Exports/tetris_03.html"
    assert local["argv"][-1] == "file:///home/jarvis/Exports/tetris_03.html"
    assert plan_linux_run_app({"target": "chrome", "url": "exports/tetris_03.html"})["ok"] is False
    assert plan_linux_run_app(
        {"target": "chrome", "url": "file://exports/tetris_03.html"}
    )["ok"] is False
    note = plan_linux_run_app({"target": "notepad"})
    assert note["ok"] is True
    assert note["argv"] == ["mousepad"]
    win_chrome = plan_linux_run_app(
        {"target": r"C:\Program Files\Google\Chrome\Application\chrome.exe", "url": "https://x.test"}
    )
    assert win_chrome["argv"][0] == "/usr/local/bin/chrome"
    unknown = plan_linux_run_app({"target": "diskpart"})
    assert unknown["ok"] is False


def test_computer_html_file_url_is_absolute_file_uri():
    url = computer_html_file_url("Exports/tetris_03.html")
    assert url == "file:///home/jarvis/Exports/tetris_03.html"
    assert is_local_file_url(url) is True
    assert is_local_file_url("exports/tetris_03.html") is False
    assert is_local_file_url("file://exports/tetris_03.html") is False


def test_linux_run_app_uses_detached_exec():
    seen: dict[str, object] = {}

    def fake(inner, **kwargs):
        seen["inner"] = list(inner)
        seen["detach"] = kwargs.get("detach")
        return {"ok": True}

    set_computer_exec(fake)
    plan = plan_linux_run_app({"target": "notepad"})
    result = linux_run_app(plan)
    assert result["ok"] is True
    assert result["computer"] == JARVIS_COMPUTER
    assert seen["detach"] is True
    assert seen["inner"] == ["mousepad"]


def test_tools_route_click_and_run_app_to_jarvis_computer(tmp_path, monkeypatch):
    from app.jarvis.tools import ToolContext, run_tool
    from app.jarvis.workspace import Workspace

    log: list[tuple[str, object]] = []

    def fake(inner, **kwargs):
        log.append((tuple(inner), kwargs.get("detach")))
        if "scrot" in " ".join(inner):
            return {"ok": True, "stdout": _PNG}
        if inner[:3] == ["xdotool", "search", "--onlyvisible"]:
            return {"ok": True, "stdout": "123\tMousepad\n"}
        return {"ok": True, "stdout": ""}

    set_computer_exec(fake)
    ws = Workspace(tmp_path / "Jarvis")
    ctx = ToolContext(ws, memory=None)
    click = run_tool(
        ctx,
        "click",
        {"x": 11, "y": 22, "computer": "jarvis-computer"},
    )
    import json

    click_out = json.loads(click)
    assert click_out["ok"] is True
    assert click_out["computer"] == JARVIS_COMPUTER
    typed = json.loads(
        run_tool(ctx, "type", {"text": "hi", "computer": "jarvis"})
    )
    assert typed["ok"] is True
    launched = json.loads(
        run_tool(ctx, "run_app", {"target": "notepad", "computer": "linux"})
    )
    assert launched["ok"] is True
    assert launched["computer"] == JARVIS_COMPUTER
    assert any(row[0][0] == "mousepad" for row in log)


def test_windows_path_still_used_when_backend_is_windows(tmp_path):
    from app.jarvis.desktop import reset_input_backend, set_input_backend
    from app.jarvis.tools import ToolContext, run_tool
    from app.jarvis.workspace import Workspace

    log: list[tuple[str, dict]] = []

    def win_click(**kwargs):
        log.append(("win-click", kwargs))
        return {"ok": True, "x": kwargs["x"], "y": kwargs["y"], "button": "left"}

    set_input_backend({"click": win_click})
    try:
        bind_job_desktop(goal="click on my Windows laptop")
        ws = Workspace(tmp_path / "Jarvis")
        ctx = ToolContext(ws, memory=None)
        import json

        out = json.loads(run_tool(ctx, "click", {"x": 3, "y": 4, "computer": "windows"}))
        assert out["ok"] is True
        assert log == [("win-click", {"x": 3, "y": 4, "button": "left"})]
        assert "computer" not in out or out.get("computer") != JARVIS_COMPUTER
    finally:
        reset_input_backend()


def test_see_screen_on_jarvis_computer_uses_display_grab(tmp_path, monkeypatch):
    from PIL import Image

    from app.jarvis.capture import capture_screen
    from app.jarvis.computer import bind_desktop_backend

    def fake(inner, **_kwargs):
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (20, 40, 80)).save(buf, "PNG")
        return {"ok": True, "stdout": buf.getvalue()}

    set_computer_exec(fake)
    bind_desktop_backend(JARVIS_COMPUTER)
    grabbed = capture_screen(goal="what's on your computer")
    assert grabbed.ok is True
    assert grabbed.method == "jarvis-computer"
    assert grabbed.image is not None


def test_spawn_child_does_not_start_a_container():
    from pathlib import Path

    children = Path("app/jarvis/children.py").read_text(encoding="utf-8")
    computer = Path("app/jarvis/computer.py").read_text(encoding="utf-8")
    assert "docker run" not in children
    assert "docker compose" not in children
    assert '["docker", "run"]' not in computer
    assert linux_list_windows.__name__
    # inherit pin is the only "computer" children get
    assert "desktop_backend" in children


def test_exec_refuses_spawn_argv():
    result = exec_in_computer(["true"])
    # During pytest without a seam this must not call Docker.
    assert result["ok"] is False
    assert "tests" in str(result.get("error") or "").lower()
    argv = docker_exec_argv(["xdotool", "click", "1"])
    assert argv[0] == "docker" and argv[1] == "exec"
