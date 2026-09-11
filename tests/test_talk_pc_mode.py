"""Talk closable PC view (#60) + Terminal vs Computer mode (#61 / #62)."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "deploy" / "jarvis-public" / "index.html"
SECRET = "test-secret-at-least-32-chars-long!!"


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _js() -> str:
    return _page().split("<script>")[-1].rsplit("</script>", 1)[0]


def _html() -> str:
    return _page().split("<script src=", 1)[0]


@pytest.fixture
def jarvis_env(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("API_SECRET", SECRET)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_TALK_MODE", raising=False)
    import app.jarvis.gateway as gw
    from app.jarvis import settings_store

    gw._gateway = None
    settings_store.reset_cache()
    yield ws
    gw._gateway = None
    settings_store.reset_cache()


@pytest.fixture
async def public_client(jarvis_env):
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, client=("203.0.113.10", 443))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()


def test_talk_mode_defaults_to_computer(jarvis_env):
    from app.jarvis.settings_store import (
        DEFAULT_TALK_MODE,
        get_talk_mode,
        public_view,
        validate_update,
    )

    assert DEFAULT_TALK_MODE == "computer"
    assert get_talk_mode() == "computer"
    view = public_view()
    assert view["talk_mode"] == "computer"
    ids = [row["id"] for row in view["talk_modes"]]
    assert ids == ["computer", "terminal"]
    with pytest.raises(ValueError):
        validate_update({"talk_mode": "voice"})
    with pytest.raises(ValueError):
        validate_update({"talk_mode": "cli-only"})


def test_talk_mode_aliases_and_persist(jarvis_env):
    from app.jarvis.settings_store import get_talk_mode, public_view, save, validate_update

    assert validate_update({"talk_mode": "CLI"}) == {"talk_mode": "terminal"}
    assert validate_update({"talk_mode": "pc"}) == {"talk_mode": "computer"}
    save({"talk_mode": "terminal"})
    assert get_talk_mode() == "terminal"
    assert public_view()["talk_mode"] == "terminal"
    save({"talk_mode": "computer"})
    assert get_talk_mode() == "computer"


def test_talk_html_has_closable_pc_and_mode_picks():
    html = _html()
    js = _js()
    assert 'id="pc"' in html
    assert 'id="pc-hide"' in html
    assert 'id="pc-show"' in html
    assert 'aria-label="Hide screen"' in html
    assert 'aria-label="Show screen"' in html
    assert 'data-talk-mode="computer"' in html
    assert 'data-talk-mode="terminal"' in html
    assert "Uses the screen when he needs it." in html
    assert "Chat only. No PC." in html
    assert 'id="talk-mode-picks"' in html
    assert "function setPcVisible" in js
    assert "function applyTalkMode" in js
    assert "function applyPcView" in js
    assert "function clearPcFrame" in js
    assert 'sessionStorage.setItem(PC_SESSION_KEY' in js
    assert 'prefs.pcVisible' in js
    assert "if (next === \"terminal\") prefs.pcVisible = false" in js
    assert "if (next === \"computer\") prefs.pcVisible = true" not in js
    assert 'setAttribute("src", "about:blank")' in js
    assert "if (!pcShouldShow()) return" in js
    assert "saveTalkSettings({ talk_mode: next })" in js
    assert "setPcVisible(false)" in js
    assert "setPcVisible(true)" in js
    assert "pcEl.hidden = !show" in js


@pytest.mark.asyncio
async def test_public_talk_mode_put_get_health(public_client, jarvis_env):
    from app.jarvis import settings_store

    first = await public_client.get("/api/jarvis/settings")
    assert first.status_code == 200
    assert first.json()["talk_mode"] == "computer"

    saved = await public_client.put("/api/jarvis/settings", json={"talk_mode": "terminal"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["talk_mode"] == "terminal"

    got = await public_client.get("/api/jarvis/settings")
    assert got.json()["talk_mode"] == "terminal"

    health = await public_client.get("/api/jarvis/health")
    assert health.status_code == 200
    assert health.json()["talk_mode"] == "terminal"

    lite = await public_client.get("/api/jarvis/health?lite=1")
    assert lite.status_code == 200
    assert lite.json()["talk_mode"] == "terminal"

    settings_store.reset_cache()
    assert settings_store.get_talk_mode() == "terminal"

    back = await public_client.put("/api/jarvis/settings", json={"talk_mode": "computer"})
    assert back.status_code == 200
    assert back.json()["talk_mode"] == "computer"


class _AskGateway:
    memory = None

    def __init__(self):
        self.runs: list[tuple[str, dict]] = []

    def clear_taint(self, *args, **kwargs):
        return None

    def run(self, tool, args=None, **kwargs):
        payload = dict(args or {})
        self.runs.append((tool, payload))
        if tool in {
            "see_screen",
            "screenshot",
            "click",
            "type",
            "keys",
            "run_app",
            "scroll",
            "focus_app",
        }:
            raise AssertionError(f"gateway must not run computer tool {tool}")
        return {"ok": True, "id": "child-1"}


def _boom_computer(monkeypatch):
    """Fail if ask/realtime touches desktop drivers."""
    from app.jarvis import computer as computer_mod
    from app.jarvis.talk_mode import TERMINAL_SCREEN_REPLY

    def boom(name):
        def _inner(*_a, **_k):
            raise AssertionError(f"{name} must not run in Terminal mode")

        return _inner

    monkeypatch.setattr(computer_mod, "linux_run_app", boom("linux_run_app"))
    monkeypatch.setattr(computer_mod, "linux_install_package", boom("linux_install_package"))
    monkeypatch.setattr(computer_mod, "activate_desktop_backend", boom("activate_desktop_backend"))
    monkeypatch.setattr(
        "app.jarvis.screen_viewer.start_computer", boom("start_computer"), raising=False
    )
    monkeypatch.setattr("app.jarvis.tools._see_screen", boom("_see_screen"))
    monkeypatch.setattr("app.jarvis.tools._click", boom("_click"))
    monkeypatch.setattr("app.jarvis.tools._type_text", boom("_type"))
    monkeypatch.setattr("app.jarvis.tools._keys", boom("_keys"))
    monkeypatch.setattr(
        "app.jarvis.agent.build_jarvis_agent",
        boom("build_jarvis_agent"),
        raising=False,
    )
    return TERMINAL_SCREEN_REPLY


def test_gateway_terminal_blocks_computer_tools(jarvis_env, monkeypatch):
    from app.jarvis.gateway import ToolGateway
    from app.jarvis.settings_store import save
    from app.jarvis.talk_mode import TERMINAL_SCREEN_REPLY

    save({"talk_mode": "terminal"})
    activated: list[str] = []
    monkeypatch.setattr(
        "app.jarvis.computer.activate_desktop_backend",
        lambda **k: activated.append("activate") or "jarvis-computer",
    )
    monkeypatch.setattr(
        "app.jarvis.tools.run_tool",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("run_tool must not execute computer tools")
        ),
    )
    g = ToolGateway()
    for tool, args in (
        ("run_app", {"target": "chrome", "url": "https://cnn.com"}),
        ("see_screen", {"goal": "what's on the screen"}),
        ("click", {"x": 10, "y": 20}),
        ("type", {"text": "hello"}),
        ("keys", {"combo": "ctrl+w"}),
    ):
        dec = g.authorize(tool, args, source="ask")
        assert dec.allowed is False, tool
        assert dec.needs_confirm is False, tool
        assert dec.reason == TERMINAL_SCREEN_REPLY, tool
        out = g.run(tool, args, source="ask")
        assert out.get("ok") is False, tool
        assert out.get("blocked") is True, tool
        assert out.get("error") == TERMINAL_SCREEN_REPLY, tool
    assert activated == []

    helper = g.authorize("spawn_child", {"goal": "research hotels in rome"}, source="ask")
    assert helper.allowed is True
    assert helper.needs_confirm is False
    recall = g.authorize("recall_memories", {"query": "yesterday"}, source="ask")
    assert recall.allowed is True


def test_gateway_computer_mode_still_authorizes_desktop(jarvis_env):
    from app.jarvis.gateway import ToolGateway
    from app.jarvis.settings_store import save
    from app.jarvis.talk_mode import TERMINAL_SCREEN_REPLY

    save({"talk_mode": "computer"})
    g = ToolGateway()
    dec = g.authorize("run_app", {"target": "chrome"}, source="ask")
    assert TERMINAL_SCREEN_REPLY not in (dec.reason or "")
    assert dec.allowed is True or dec.needs_confirm is True
    look = g.authorize("see_screen", {"goal": "what's on the screen"}, source="ask")
    assert look.allowed is True
    assert look.needs_confirm is False


def test_prepare_realtime_terminal_refuses_before_bind(jarvis_env, monkeypatch):
    from app.jarvis.realtime import prepare_realtime_tool_call
    from app.jarvis.settings_store import save
    from app.jarvis.talk_mode import TERMINAL_SCREEN_REPLY

    save({"talk_mode": "terminal"})
    monkeypatch.setattr(
        "app.jarvis.computer.bind_job_desktop",
        lambda **k: (_ for _ in ()).throw(
            AssertionError("bind_job_desktop must not run in Terminal mode")
        ),
    )
    name, args, early = prepare_realtime_tool_call(
        "run_app",
        {"target": "chrome"},
        user_goal="open chrome",
    )
    assert name == "run_app"
    assert early is not None
    assert early.get("ok") is False
    assert early.get("blocked") is True
    assert early.get("error") == TERMINAL_SCREEN_REPLY
    assert not args.get("computer")

    name, args, early = prepare_realtime_tool_call(
        "see_screen",
        {"goal": "what's on your screen"},
        user_goal="what's on your screen",
    )
    assert early is not None
    assert early.get("blocked") is True
    assert early.get("error") == TERMINAL_SCREEN_REPLY


def test_prepare_realtime_computer_mode_still_binds(jarvis_env, monkeypatch):
    from app.jarvis.computer import JARVIS_COMPUTER
    from app.jarvis.realtime import prepare_realtime_tool_call
    from app.jarvis.settings_store import save

    save({"talk_mode": "computer"})
    bound: list[str] = []

    def capture_bind(*, goal="", computer=""):
        bound.append(computer or "bound")
        return JARVIS_COMPUTER

    monkeypatch.setattr("app.jarvis.computer.bind_job_desktop", capture_bind)
    name, args, early = prepare_realtime_tool_call(
        "run_app",
        {"target": "chrome"},
        user_goal="open chrome",
    )
    assert early is None
    assert name == "run_app"
    assert args.get("computer") == JARVIS_COMPUTER
    assert bound


@pytest.mark.asyncio
async def test_terminal_ask_open_chrome_does_not_touch_computer(jarvis_env, monkeypatch):
    import sys

    from app.jarvis.settings_store import save
    from app.jarvis.talk_mode import TERMINAL_SCREEN_REPLY
    from app.jarvis.voice_ask import run_voice_ask

    save({"talk_mode": "terminal"})
    gw = _AskGateway()
    monkeypatch.setattr("app.jarvis.voice_ask.get_gateway", lambda: gw)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    _boom_computer(monkeypatch)

    body = await run_voice_ask("show cnn.com")
    assert body["ok"] is False
    assert body["reply"] == TERMINAL_SCREEN_REPLY
    assert body["tools_used"] == []
    assert gw.runs == []

    look = await run_voice_ask("what's on your screen")
    assert look["ok"] is False
    assert look["reply"] == TERMINAL_SCREEN_REPLY
    assert look["tools_used"] == []


@pytest.mark.asyncio
async def test_terminal_simple_talk_and_spawn_child_still_ok(jarvis_env, monkeypatch):
    import sys

    from app.jarvis.settings_store import save
    from app.jarvis.voice_ask import run_voice_ask

    save({"talk_mode": "terminal"})
    gw = _AskGateway()
    monkeypatch.setattr("app.jarvis.voice_ask.get_gateway", lambda: gw)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    _boom_computer(monkeypatch)

    hello = await run_voice_ask("hello")
    assert hello["ok"] is True
    assert hello["reply"]
    assert "Switch to Computer mode" not in hello["reply"]
    assert gw.runs == []

    spawned = gw.run("spawn_child", {"goal": "research the capital of France"})
    assert spawned.get("ok") is True
    assert gw.runs == [("spawn_child", {"goal": "research the capital of France"})]


@pytest.mark.asyncio
async def test_computer_mode_ask_still_opens_chrome(jarvis_env, monkeypatch):
    import sys

    from app.jarvis import computer as computer_mod
    from app.jarvis.settings_store import save
    from app.jarvis.voice_ask import run_voice_ask

    save({"talk_mode": "computer"})
    planned: list[dict] = []
    launched: list[dict] = []
    real_plan = computer_mod.plan_linux_run_app

    def capture_plan(args):
        planned.append(dict(args or {}))
        return real_plan(args)

    def capture_run(plan):
        launched.append(plan)
        return {"ok": True, "started": "chrome", "url": plan.get("url"), "window": True}

    monkeypatch.setattr("app.jarvis.voice_ask.get_gateway", lambda: _AskGateway())
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("JARVIS_HOST_OS", "windows")
    monkeypatch.setattr("app.jarvis.virtual_pc.host_is_windows", lambda env=None: True)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_HOSTED_TALK_URL", raising=False)
    monkeypatch.setattr(computer_mod, "plan_linux_run_app", capture_plan)
    monkeypatch.setattr(computer_mod, "linux_run_app", capture_run)
    monkeypatch.setattr(
        "app.jarvis.screen_viewer.start_computer",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("start_computer must not block the open-site path")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "app.jarvis.agent.build_jarvis_agent",
        lambda **k: (_ for _ in ()).throw(
            AssertionError("OpenRouter agent must not start on the open-site path")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "app.jarvis.tools._see_screen",
        lambda ctx, args: {
            "ok": True,
            "title": "CNN",
            "vision_description": "The page is open. Headlines and a logo are visible.",
        },
    )
    monkeypatch.setattr(
        "app.jarvis.desktop.close_windows",
        lambda *, app="chrome": {"ok": True, "app": app},
    )
    monkeypatch.setattr(
        "app.jarvis.desktop.focus_app",
        lambda *, app="", title="": {"ok": True, "app": app or title},
    )

    body = await run_voice_ask("show cnn.com")
    assert body["ok"] is True
    assert "run_app" in body["tools_used"]
    assert planned == [{"target": "chrome", "url": "https://cnn.com"}]
    assert launched
    assert launched[0]["url"] == "https://cnn.com"


@pytest.mark.asyncio
async def test_public_ask_and_tools_run_honor_terminal(public_client, jarvis_env, monkeypatch):
    from app.jarvis import settings_store
    from app.jarvis.talk_mode import TERMINAL_SCREEN_REPLY

    saved = await public_client.put("/api/jarvis/settings", json={"talk_mode": "terminal"})
    assert saved.status_code == 200
    settings_store.reset_cache()
    assert settings_store.get_talk_mode() == "terminal"
    _boom_computer(monkeypatch)

    ask = await public_client.post("/api/jarvis/ask", json={"text": "open chrome"})
    assert ask.status_code == 200
    body = ask.json()
    assert body["reply"] == TERMINAL_SCREEN_REPLY
    assert body["tools_used"] == []
    assert body.get("ok") is False

    tools = await public_client.post(
        "/api/jarvis/tools/run",
        json={"name": "see_screen", "arguments": {"goal": "what's on your screen"}},
    )
    assert tools.status_code == 200
    result = tools.json()["result"]
    assert result.get("ok") is False
    assert result.get("blocked") is True
    assert result.get("error") == TERMINAL_SCREEN_REPLY
