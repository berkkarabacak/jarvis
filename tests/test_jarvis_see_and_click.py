"""ORCH-365 / 366 / 367 / 368 — look speed, click/type/scroll, look-act loop."""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient


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
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.delenv("PUBLIC_GUEST_PROFILE", raising=False)
    monkeypatch.delenv("JARVIS_PUBLIC_CLOUD", raising=False)
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1:8787")
    monkeypatch.delenv("JARVIS_LOOK_SPEED", raising=False)

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


def _fake_input(log):
    from app.jarvis.desktop import set_input_backend

    def click(**kwargs):
        log.append(("click", kwargs))
        return {"ok": True, "x": kwargs["x"], "y": kwargs["y"], "button": kwargs.get("button", "left")}

    def type_text(**kwargs):
        log.append(("type", kwargs))
        return {"ok": True, "typed": len(kwargs.get("text") or ""), "chars": len(kwargs.get("text") or "")}

    def scroll(**kwargs):
        log.append(("scroll", kwargs))
        return {"ok": True, "dx": kwargs.get("dx", 0), "dy": kwargs.get("dy", 0)}

    set_input_backend({"click": click, "type": type_text, "scroll": scroll})


# ---------------------------------------------------------------- ORCH-366


def test_look_speed_defaults_off(jarvis_env):
    from app.jarvis import settings_store

    assert settings_store.get_look_speed() == "off"
    assert settings_store.look_speed_interval_seconds() is None
    view = settings_store.public_view()
    assert view["look_speed"] == "off"
    ids = [s["id"] for s in view["look_speeds"]]
    assert ids == ["off", "30s", "10s", "1s"]
    assert all(s.get("label") and s.get("allows") for s in view["look_speeds"])


def test_look_speed_persists_across_reload(jarvis_env):
    from app.jarvis import settings_store

    settings_store.save({"look_speed": "1s"})
    settings_store.reset_cache()
    assert settings_store.get_look_speed() == "1s"
    assert settings_store.look_speed_interval_seconds() == 1.0
    raw = json.loads(settings_store.settings_path().read_text(encoding="utf-8"))
    assert raw["look_speed"] == "1s"

    settings_store.save({"look_speed": "30s"})
    settings_store.reset_cache()
    assert settings_store.get_look_speed() == "30s"
    assert settings_store.look_speed_interval_seconds() == 30.0

    settings_store.save({"look_speed": "off"})
    settings_store.reset_cache()
    assert settings_store.get_look_speed() == "off"


def test_look_speed_rejects_unknown(jarvis_env):
    from app.jarvis import settings_store

    with pytest.raises(ValueError):
        settings_store.validate_update({"look_speed": "turbo"})


@pytest.mark.asyncio
async def test_look_speed_http_roundtrip(client, jarvis_env):
    from app.jarvis import settings_store

    r = await client.get("/api/jarvis/settings")
    assert r.status_code == 200
    assert r.json()["look_speed"] == "off"

    r = await client.put("/api/jarvis/settings", json={"look_speed": "10s"})
    assert r.status_code == 200, r.text
    assert r.json()["look_speed"] == "10s"
    settings_store.reset_cache()
    assert settings_store.get_look_speed() == "10s"

    r = await client.put("/api/jarvis/settings", json={"look_speed": "nope"})
    assert r.status_code == 400


# ---------------------------------------------------------------- ORCH-368


def test_click_type_scroll_no_needs_confirm(jarvis_env):
    from app.jarvis.gateway import ToolGateway
    from app.jarvis.permissions import requires_confirm, skips_confirm
    from app.jarvis.permissions import Tier

    log = []
    _fake_input(log)
    g = ToolGateway()

    for name in ("click", "type", "scroll"):
        assert skips_confirm(name)
        assert requires_confirm(name, max_auto=Tier.L0) is False
        assert requires_confirm(name, max_auto=Tier.L2) is False

    click = g.run("click", {"x": 40, "y": 80}, source="test")
    typed = g.run("type", {"text": "hello"}, source="test")
    scrolled = g.run("scroll", {"dy": -3}, source="test")

    for result, tool in ((click, "click"), (typed, "type"), (scrolled, "scroll")):
        assert result.get("ok") is True, result
        assert result.get("needs_confirm") in (None, False)
        assert "confirm_id" not in result
        assert "nonce_code" not in result
        assert "nonce_prompt" not in result
        assert result.get("tool", tool)

    assert log[0][0] == "click" and log[0][1]["x"] == 40
    assert log[1][0] == "type" and log[1][1]["text"] == "hello"
    assert log[2][0] == "scroll" and log[2][1]["dy"] == -3


def test_click_type_scroll_no_confirm_after_screenshot_taint(jarvis_env):
    from app.jarvis.gateway import ToolGateway

    log = []
    _fake_input(log)
    g = ToolGateway()
    g._tracker("test").observe("screenshot")
    assert g._tracker("test").tainted is True

    r = g.run("click", {"x": 1, "y": 2}, source="test")
    assert r.get("ok") is True, r
    assert r.get("needs_confirm") in (None, False)
    assert "confirm_id" not in r
    assert "nonce_code" not in r


def test_click_type_scroll_in_tool_specs():
    from app.jarvis.tools import TOOL_SPECS
    from app.jarvis.realtime import tools_for_realtime

    names = {
        (spec.get("function") or {}).get("name")
        for spec in TOOL_SPECS
        if spec.get("type") == "function"
    }
    assert {"click", "type", "scroll"} <= names
    rt = {t["name"] for t in tools_for_realtime()}
    assert {"click", "type", "scroll"} <= rt
    click = next(t for t in tools_for_realtime() if t["name"] == "click")
    low = str(click.get("description") or "").lower()
    assert "not that the page changed" in low
    assert "serp" in low
    assert "run_app" in low
    assert "clicks" in low
    assert "between every click" in low or "without see_screen" in low


# ---------------------------------------------------------------- ORCH-367


def test_look_loop_off_vs_1s():
    from app.jarvis.screen_loop import LookLoop, look_decision

    clock = {"t": 0.0}

    off = LookLoop("off", clock=lambda: clock["t"])
    assert look_decision(off, "list_dir") is False
    assert off.desktop is False
    assert look_decision(off, "click") is True
    off.mark_looked()
    clock["t"] = 5.0
    assert look_decision(off, "run_app") is False
    assert look_decision(off, "type") is False
    assert look_decision(off, "click") is False
    assert look_decision(off, "keys") is False
    assert look_decision(off, "screenshot") is False

    clock["t"] = 0.0
    one = LookLoop("1s", clock=lambda: clock["t"])
    assert look_decision(one, "run_app") is True
    one.mark_looked()
    clock["t"] = 0.4
    assert look_decision(one, "click") is False
    clock["t"] = 1.0
    assert look_decision(one, "click") is True
    one.mark_looked()
    clock["t"] = 1.5
    assert one.should_look(next_action_needs_shot=False) is False
    clock["t"] = 2.0
    assert one.should_look(next_action_needs_shot=False) is True


def test_click_batch_does_not_look_between_points(jarvis_env):
    from app.jarvis.desktop import click, reset_input_backend
    from app.jarvis.tools import ToolContext, _click
    from app.jarvis.workspace import Workspace, default_workspace

    log: list[tuple] = []
    _fake_input(log)
    result = click(clicks=[{"x": 10, "y": 20}, {"x": 30, "y": 40}, {"x": 50, "y": 60}])
    assert result.get("ok") is True
    assert result.get("n") == 3
    assert [item[1]["x"] for item in log] == [10, 30, 50]
    reset_input_backend()
    log.clear()
    _fake_input(log)
    ctx = ToolContext(Workspace(default_workspace()), None)
    tool = _click(
        ctx,
        {
            "clicks": [{"x": 8, "y": 9}, {"x": 11, "y": 12}],
            "skip_serp_leave": True,
        },
    )
    assert tool.get("ok") is True
    assert tool.get("n") == 2
    assert len(log) == 2
    reset_input_backend()


def test_look_loop_from_settings(jarvis_env):
    from app.jarvis import settings_store
    from app.jarvis.screen_loop import look_loop_from_settings

    loop = look_loop_from_settings()
    assert loop.speed == "off"
    assert loop.interval is None

    settings_store.save({"look_speed": "1s"})
    settings_store.reset_cache()
    loop = look_loop_from_settings()
    assert loop.speed == "1s"
    assert loop.interval == 1.0
