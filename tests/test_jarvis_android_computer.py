"""ORCH-461 — Linux is the default box; Android is a real selectable machine."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.jarvis.android_computer import (
    ANDROID_CONTAINER,
    JARVIS_ANDROID,
    android_click,
    android_run_app,
    android_screenshot_png,
    android_type,
    docker_exec_argv,
    exec_in_android,
    is_play_store_client,
    plan_android_run_app,
    reset_android_state,
    set_android_exec,
    tap_inner_argv,
)
from app.jarvis.computer import (
    JARVIS_COMPUTER,
    WINDOWS,
    activate_desktop_backend,
    bind_desktop_backend,
    bind_job_desktop,
    docker_exec_argv as linux_docker_exec_argv,
    reset_computer_state,
    resolve_desktop_backend,
    selected_jarvis_box,
    uses_jarvis_android,
    uses_jarvis_computer,
)

ROOT = Path(__file__).resolve().parents[1]
ANDROID_DIR = ROOT / "deploy" / "jarvis-android"
COMPOSE = ANDROID_DIR / "docker-compose.yml"
WATCH = ANDROID_DIR / "watch" / "server.py"
PUBLIC = ROOT / "deploy" / "jarvis-public" / "index.html"
PLAY_STORE_APP = ROOT / "android"
SECRET = "test-secret-at-least-32-chars-long!!"

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture(autouse=True)
def _reset():
    reset_computer_state()
    reset_android_state()
    yield
    reset_computer_state()
    reset_android_state()


@pytest.fixture
def jarvis_env(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("API_SECRET", SECRET)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("JARVIS_COMPUTER_KIND", raising=False)
    monkeypatch.delenv("JARVIS_DESKTOP_BACKEND", raising=False)
    from app.jarvis import settings_store

    settings_store.reset_cache()
    yield ws
    settings_store.reset_cache()


@pytest.fixture
async def client(jarvis_env):
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()


def test_linux_is_default_computer_kind(jarvis_env):
    from app.jarvis.settings_store import (
        DEFAULT_COMPUTER_KIND,
        get_computer_kind,
        public_view,
    )

    assert DEFAULT_COMPUTER_KIND == "linux"
    assert get_computer_kind() == "linux"
    view = public_view()
    assert view["computer_kind"] == "linux"
    ids = [row["id"] for row in view["computer_kinds"]]
    assert ids == ["linux", "android"]
    assert selected_jarvis_box() == JARVIS_COMPUTER
    assert resolve_desktop_backend(computer="linux") == JARVIS_COMPUTER
    assert resolve_desktop_backend(goal="what's on your screen") == JARVIS_COMPUTER


def test_android_is_a_real_machine_class_not_play_store():
    assert JARVIS_ANDROID == "jarvis-android"
    assert JARVIS_ANDROID != JARVIS_COMPUTER
    assert is_play_store_client() is False
    assert PLAY_STORE_APP.is_dir()
    android_py = (ROOT / "app" / "jarvis" / "android_computer.py").read_text(
        encoding="utf-8"
    )
    assert "Play Store" in android_py
    assert "android/" in android_py
    assert 'ANDROID_CONTAINER = "jarvis-android"' in android_py
    assert "jarvis-computer" in android_py
    compose = COMPOSE.read_text(encoding="utf-8")
    assert "container_name: jarvis-android" in compose
    assert "container_name: jarvis-computer" not in compose
    assert "127.0.0.1:6081:6081" in compose
    assert "Play Store" in (ANDROID_DIR / "README.md").read_text(encoding="utf-8")


def test_settings_can_pick_android(jarvis_env):
    from app.jarvis.settings_store import get_computer_kind, save, validate_update

    save({"computer_kind": "android"})
    assert get_computer_kind() == "android"
    assert selected_jarvis_box() == JARVIS_ANDROID
    assert resolve_desktop_backend(goal="what's on your screen") == JARVIS_ANDROID
    assert resolve_desktop_backend(goal="open chrome") == JARVIS_ANDROID
    with pytest.raises(ValueError):
        validate_update({"computer_kind": "windows"})
    with pytest.raises(ValueError):
        validate_update({"computer_kind": "play-store"})


def test_explicit_linux_still_wins_when_settings_say_android(jarvis_env):
    from app.jarvis.settings_store import save

    save({"computer_kind": "android"})
    assert resolve_desktop_backend(computer="linux") == JARVIS_COMPUTER
    assert resolve_desktop_backend(computer="windows") == WINDOWS
    assert resolve_desktop_backend(computer="android") == JARVIS_ANDROID
    assert resolve_desktop_backend(goal="on your android") == JARVIS_ANDROID
    assert resolve_desktop_backend(goal="click on my Windows laptop") == WINDOWS


def test_android_exec_never_names_linux_container():
    argv = docker_exec_argv(["screencap", "-p"])
    assert argv[:2] == ["docker", "exec"]
    assert ANDROID_CONTAINER in argv
    assert "jarvis-computer" not in argv
    assert "run" not in argv
    linux = linux_docker_exec_argv(["scrot", "-o", "/tmp/x.png"])
    assert "jarvis-computer" in linux
    assert "jarvis-android" not in linux


def test_android_tool_job_does_not_exec_linux_container(tmp_path):
    from app.jarvis.tools import ToolContext, run_tool
    from app.jarvis.workspace import Workspace

    linux_log: list[list[str]] = []
    android_log: list[list[str]] = []

    def linux_fake(inner, **kwargs):
        linux_log.append(list(inner))
        return {"ok": True, "stdout": ""}

    def android_fake(inner, **kwargs):
        android_log.append(list(kwargs.get("argv") or []))
        if inner[:1] == ["screencap"]:
            return {"ok": True, "stdout": _PNG}
        return {"ok": True, "stdout": ""}

    from app.jarvis.computer import set_computer_exec

    set_computer_exec(linux_fake)
    set_android_exec(android_fake)
    bind_desktop_backend(JARVIS_ANDROID)
    ws = Workspace(tmp_path / "Jarvis")
    ctx = ToolContext(ws, memory=None)
    clicked = json.loads(run_tool(ctx, "click", {"x": 40, "y": 80, "computer": "android"}))
    typed = json.loads(run_tool(ctx, "type", {"text": "hi", "computer": "android"}))
    launched = json.loads(
        run_tool(ctx, "run_app", {"target": "chrome", "url": "https://example.com", "computer": "android"})
    )
    assert clicked["ok"] is True
    assert clicked["computer"] == JARVIS_ANDROID
    assert typed["ok"] is True
    assert typed["computer"] == JARVIS_ANDROID
    assert launched["ok"] is True
    assert launched["computer"] == JARVIS_ANDROID
    assert linux_log == []
    assert android_log
    blob = " ".join(" ".join(row) for row in android_log)
    assert "jarvis-android" in blob
    assert "jarvis-computer" not in blob
    assert uses_jarvis_android(computer="android") is True
    assert uses_jarvis_computer(computer="android") is False


def test_android_helpers_use_toolbox_not_xdotool():
    assert tap_inner_argv(x=10, y=20) == ["input", "tap", "10", "20"]
    plan = plan_android_run_app({"target": "chrome", "url": "https://example.com"})
    assert plan["ok"] is True
    assert plan["computer"] == JARVIS_ANDROID
    assert plan["argv"][0] == "am"
    assert "https://example.com" in plan["argv"]
    unknown = plan_android_run_app({"target": "diskpart"})
    assert unknown["ok"] is False

    seen: list[list[str]] = []

    def fake(inner, **_kwargs):
        seen.append(list(inner))
        if inner[:1] == ["screencap"]:
            return {"ok": True, "stdout": _PNG}
        return {"ok": True}

    set_android_exec(fake)
    assert android_click(x=3, y=4)["computer"] == JARVIS_ANDROID
    assert android_type(text="hello")["ok"] is True
    shot = android_screenshot_png()
    assert shot["ok"] is True
    assert shot["png"][:8] == b"\x89PNG\r\n\x1a\n"
    assert android_run_app(plan)["computer"] == JARVIS_ANDROID
    assert any(row[0] == "input" for row in seen)
    assert any(row[0] == "screencap" for row in seen)
    assert any(row[0] == "am" for row in seen)
    assert all("xdotool" not in row and "scrot" not in row for row in seen)


def test_android_exec_refuses_linux_or_spawn():
    result = exec_in_android(["true"])
    assert result["ok"] is False
    assert "tests" in str(result.get("error") or "").lower()
    assert result["computer"] == JARVIS_ANDROID


def test_settings_ui_picks_linux_and_android():
    page = PUBLIC.read_text(encoding="utf-8")
    assert 'data-computer="linux"' in page
    assert 'data-computer="android"' in page
    assert "Which computer he uses" in page
    assert "saveTalkSettings({ computer_kind: kind })" in page
    assert "Not the phone app" in page or "not the phone app" in page
    assert "Play Store" not in page.split("<script>", 1)[0]
    ceo = (ROOT / "app" / "static" / "ceo.html").read_text(encoding="utf-8")
    assert "Which computer Jarvis uses" in ceo
    assert "persistJarvis({ computer_kind: selectedComputer })" in ceo
    assert "computer_kind: selectedComputer" in ceo


@pytest.mark.asyncio
async def test_health_reports_which_computer_is_live(client, jarvis_env):
    from app.jarvis import settings_store

    health = await client.get("/api/jarvis/health")
    assert health.status_code == 200
    body = health.json()
    assert body["computer_kind"] == "linux"
    assert body["computer"]["kind"] == "linux"
    assert body["computer"]["label"] == "Linux"
    assert body["computer"]["play_store_client"] is False
    assert "live" in body["computer"]
    lite = await client.get("/api/jarvis/health?lite=1")
    assert lite.json()["computer_kind"] == "linux"
    assert lite.json()["computer"]["kind"] == "linux"

    saved = await client.put(
        "/api/jarvis/settings",
        headers={"X-Api-Key": SECRET},
        json={"computer_kind": "android"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["computer_kind"] == "android"
    settings_store.reset_cache()
    again = await client.get("/api/jarvis/health")
    assert again.json()["computer_kind"] == "android"
    assert again.json()["computer"]["kind"] == "android"
    assert again.json()["computer"]["label"] == "Android"
    assert again.json()["computer"]["container"] == "jarvis-android"
    assert again.json()["computer"]["play_store_client"] is False


def test_watch_path_is_localhost_equivalent_of_novnc():
    compose = COMPOSE.read_text(encoding="utf-8")
    assert "127.0.0.1:6081:6081" in compose
    assert re.search(r"0\.0\.0\.0:", compose) is None
    nginx = (ROOT / "deploy" / "nginx-jarvis-public.fragment").read_text(encoding="utf-8")
    assert "location ^~ /jarvis/android/" in nginx
    assert "proxy_pass http://127.0.0.1:6081/" in nginx
    assert "location ^~ /jarvis/novnc/" in nginx
    watch = WATCH.read_text(encoding="utf-8")
    assert "Jarvis's screen" in watch
    assert "play_store_client" in watch
    assert 'src="/stream.mjpeg"' not in watch
    assert 'src="stream.mjpeg"' in watch
    linux_compose = (ROOT / "deploy" / "jarvis-computer" / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    assert "127.0.0.1:6080:6080" in linux_compose
    assert linux_compose.count("container_name:") == 1


def test_children_inherit_android_and_do_not_spawn():
    bind_job_desktop(goal="type hello on your android")
    child = resolve_desktop_backend(goal="just tap it", inherit=JARVIS_ANDROID)
    assert child == JARVIS_ANDROID
    token = bind_desktop_backend(JARVIS_ANDROID)
    try:
        assert activate_desktop_backend(goal="tap the icon") == JARVIS_ANDROID
    finally:
        from app.jarvis.computer import reset_desktop_backend

        reset_desktop_backend(token)
    children = (ROOT / "app" / "jarvis" / "children.py").read_text(encoding="utf-8")
    assert "docker run" not in children
    assert "docker compose" not in children
