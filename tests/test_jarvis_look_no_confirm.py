"""ORCH-373: looking at the screen must not ask for confirm."""

from __future__ import annotations

import base64

import pytest

from app.jarvis.model_router import classify_task
from app.jarvis.permissions import NO_CONFIRM_TOOLS, Tier, requires_confirm, skips_confirm
from app.jarvis.taint import ALLOW, UNTRUSTED_TOOLS, gate

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

NTV_GOAL = (
    "Open Chrome with run_app chrome. Then focus_app chrome. "
    "Type https://www.ntv.com.tr. see_screen and name headlines."
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

    import app.jarvis.gateway as gw
    from app.jarvis import settings_store

    gw._gateway = None
    settings_store.reset_cache()
    yield ws
    gw._gateway = None
    settings_store.reset_cache()


def _install_fake_look(monkeypatch):
    """Stub screenshot/see_screen so tests never grab a real display."""
    import app.jarvis.tools as tools

    def fake_screenshot(ctx, args):
        out_dir = ctx.ws.root / "Exports" / "screenshots"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "screen_fake.png"
        out.write_bytes(_PNG)
        return {
            "ok": True,
            "path": ctx.ws.rel(out),
            "bytes": len(_PNG),
            "note": "fake screenshot for tests",
        }

    def fake_see_screen(ctx, args):
        shot = fake_screenshot(ctx, args or {})
        shot["vision_description"] = "NTV homepage headlines."
        return shot

    monkeypatch.setitem(tools._DISPATCH, "screenshot", fake_screenshot)
    monkeypatch.setitem(tools._DISPATCH, "see_screen", fake_see_screen)
    monkeypatch.setattr(tools, "_screenshot", fake_screenshot)
    monkeypatch.setattr(tools, "_see_screen", fake_see_screen)


def _assert_no_confirm(result, *, tool):
    assert result.get("ok") is True, result
    assert result.get("needs_confirm") in (None, False)
    assert "confirm_id" not in result
    assert "nonce_code" not in result
    assert "nonce_prompt" not in result
    assert result.get("tool", tool)


def test_screenshot_and_see_screen_skip_confirm():
    for name in ("screenshot", "see_screen"):
        assert name in NO_CONFIRM_TOOLS
        assert skips_confirm(name)
        assert requires_confirm(name, max_auto=Tier.L0) is False
        assert requires_confirm(name, max_auto=Tier.L2) is False


def test_look_tools_still_taint_but_gate_allows():
    assert "screenshot" in UNTRUSTED_TOOLS
    assert "see_screen" in UNTRUSTED_TOOLS
    assert gate("screenshot", tainted=True) == (ALLOW, "")
    assert gate("see_screen", tainted=True) == (ALLOW, "")
    assert gate("write_file", tainted=True)[0] != ALLOW


def test_look_after_screenshot_taint_has_no_confirm(jarvis_env, monkeypatch):
    from app.jarvis.gateway import ToolGateway

    _install_fake_look(monkeypatch)
    g = ToolGateway()
    g._tracker("test").observe("screenshot")
    assert g._tracker("test").tainted is True

    shot = g.run("screenshot", {}, source="test")
    _assert_no_confirm(shot, tool="screenshot")

    look = g.run("see_screen", {"goal": "name headlines"}, source="test")
    _assert_no_confirm(look, tool="see_screen")


def test_classify_chrome_see_screen_site_is_not_light():
    klass = classify_task(NTV_GOAL)
    assert klass != "light"
    assert klass in {"routine_build", "hard"}


def test_classify_whats_on_my_screen_still_light():
    assert classify_task("What's on my screen?") == "light"
    assert classify_task("screenshot") == "light"


def test_prompts_never_ask_to_confirm_a_look():
    from app.jarvis.agent import SYSTEM_PROMPT
    from app.jarvis.realtime import JARVIS_REALTIME_INSTRUCTIONS

    for text in (SYSTEM_PROMPT, JARVIS_REALTIME_INSTRUCTIONS):
        low = text.lower()
        assert "never ask the user to confirm a look" in low
        assert "see_screen" in text
        assert "need no confirm" in low or "needs no confirm" in low
        assert "confirm seven zero" in low
