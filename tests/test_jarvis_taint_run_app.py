"""ORCH-376: a look must not block opening a URL the user already asked for."""

from __future__ import annotations

import base64

import pytest

from app.jarvis.taint import (
    ALLOW,
    BLOCK,
    UNTRUSTED_TOOLS,
    gate,
    url_in_user_goal,
)


NTV = "https://www.ntv.com.tr"
EVIL = "https://evil.example"
NTV_GOAL = f"Open Chrome and read headlines on {NTV}"
FAKE_CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

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


def _assert_look_did_not_taint_block(result, log, expected_url):
    """see_screen must not freeze the next run_app of the user's URL."""
    assert result.get("blocked") is not True, result
    assert result.get("needs_confirm") in (None, False), result
    assert "untrusted" not in (result.get("error") or "").lower(), result
    if result.get("ok"):
        assert result.get("opened") == expected_url
        if log:
            assert expected_url in str(log[0])
        return
    err = (result.get("error") or "").lower()
    assert "exec is off" in err or "jarvis-computer" in err, result


def _forbid_real_launch(monkeypatch):
    """Fail the test if Popen or startfile would open a real browser."""
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


def _capture_launch(log):
    from app.jarvis.tools import set_launch_backend

    def launch(**kwargs):
        log.append(kwargs)
        out = {
            "ok": True,
            "started": kwargs.get("cmd"),
            "argv": kwargs.get("argv"),
        }
        if kwargs.get("url"):
            out["opened"] = kwargs["url"]
        return out

    set_launch_backend(launch)


def _install_fake_look(monkeypatch):
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
        shot["vision_description"] = f"A page that also mentions {EVIL}"
        return shot

    monkeypatch.setitem(tools._DISPATCH, "screenshot", fake_screenshot)
    monkeypatch.setitem(tools._DISPATCH, "see_screen", fake_see_screen)
    monkeypatch.setattr(tools, "_screenshot", fake_screenshot)
    monkeypatch.setattr(tools, "_see_screen", fake_see_screen)


def _look_then(g, source="test"):
    shot = g.run("screenshot", {}, source=source)
    assert shot.get("ok") is True, shot
    assert g._tracker(source).tainted is True
    assert g._tracker(source).source == "screenshot"
    return shot


# -------------------------------------------------------------- URL matching


def test_goal_url_matches_same_page_and_www():
    assert url_in_user_goal(NTV, NTV_GOAL) is True
    assert url_in_user_goal(NTV + "/", NTV_GOAL) is True
    assert url_in_user_goal("https://ntv.com.tr", NTV_GOAL) is True
    assert url_in_user_goal(NTV, "please open ntv.com.tr") is True


def test_stranger_url_is_not_in_the_goal():
    assert url_in_user_goal(EVIL, NTV_GOAL) is False
    assert url_in_user_goal(EVIL, "") is False
    assert url_in_user_goal(NTV, "") is False
    # Request URL containing the goal URL as a query must not count.
    assert url_in_user_goal(f"{EVIL}?next={NTV}", NTV_GOAL) is False


WIKI_MOON = "https://en.wikipedia.org/wiki/Moon"
WIKI_MARS = "https://en.wikipedia.org/wiki/Mars"
WIKI_MOON_GOAL = "look at the Wikipedia Moon page"


def test_wikipedia_moon_page_goal_matches_moon_url_not_stranger():
    """Follow-up phrasing without the full URL still names that page (ORCH-376)."""
    assert url_in_user_goal(WIKI_MOON, WIKI_MOON_GOAL) is True
    assert url_in_user_goal(WIKI_MOON + "/", WIKI_MOON_GOAL) is True
    assert url_in_user_goal(WIKI_MARS, WIKI_MOON_GOAL) is False
    assert url_in_user_goal(EVIL, WIKI_MOON_GOAL) is False
    assert url_in_user_goal(NTV, WIKI_MOON_GOAL) is False


# -------------------------------------------------------------- gate policy


def test_screenshot_and_see_screen_still_untrusted():
    assert "screenshot" in UNTRUSTED_TOOLS
    assert "see_screen" in UNTRUSTED_TOOLS


def test_gate_allows_goal_url_while_tainted():
    decision, reason = gate(
        "run_app",
        True,
        args={"target": "chrome", "url": NTV},
        user_goal=NTV_GOAL,
    )
    assert decision == ALLOW
    assert reason == ""


def test_gate_allows_news_tell_publisher_while_tainted():
    bbc = "https://www.bbc.com/news/world/europe"
    decision, reason = gate(
        "run_app",
        True,
        args={"target": "chrome", "url": bbc},
        user_goal="latest news in Europe",
    )
    assert decision == ALLOW
    assert reason == ""
    reuters, _ = gate(
        "run_app",
        True,
        args={"target": "chrome", "url": "https://www.reuters.com/"},
        user_goal="tell me the news",
    )
    assert reuters == ALLOW


def test_gate_allows_wikipedia_moon_page_goal_while_tainted():
    decision, reason = gate(
        "run_app",
        True,
        args={"target": "chrome", "url": WIKI_MOON},
        user_goal=WIKI_MOON_GOAL,
    )
    assert decision == ALLOW
    assert reason == ""
    assert (
        gate(
            "run_app",
            True,
            args={"target": "chrome", "url": EVIL},
            user_goal=WIKI_MOON_GOAL,
        )[0]
        == BLOCK
    )


def test_gate_blocks_stranger_url_while_tainted():
    decision, reason = gate(
        "run_app",
        True,
        args={"target": "chrome", "url": EVIL},
        user_goal=NTV_GOAL,
    )
    assert decision == BLOCK
    assert "untrusted" in reason


def test_gate_blocks_powershell_while_tainted():
    decision, reason = gate("run_powershell", True, args={"command": "Get-Process"})
    assert decision == BLOCK
    assert "untrusted" in reason


def test_gate_does_not_skip_every_http_url():
    """Any URL is allowlisted; a blanket skip would open evil.com."""
    decision, _ = gate(
        "run_app",
        True,
        args={"target": EVIL},
        user_goal=NTV_GOAL,
    )
    assert decision == BLOCK
    # Missing goal must fail closed — do not treat every http(s) as user intent.
    assert gate("run_app", True, args={"target": "chrome", "url": NTV})[0] == BLOCK


def test_gate_allows_allowlisted_app_without_url():
    assert gate("run_app", True, args={"target": "chrome"}, user_goal=NTV_GOAL)[0] == ALLOW
    assert gate("run_app", True, args={"target": "notepad"})[0] == ALLOW


def test_gate_blocks_unknown_app_while_tainted():
    assert (
        gate("run_app", True, args={"target": "totally-unknown-app-xyz"}, user_goal=NTV_GOAL)[0]
        == BLOCK
    )


# ---------------------------------------------------------- gateway + look


def test_look_then_open_wikipedia_moon_page_runs(jarvis_env, monkeypatch):
    """see_screen must not taint-block run_app of the Wikipedia Moon URL."""
    from app.jarvis.gateway import ToolGateway

    _forbid_real_launch(monkeypatch)
    _install_fake_look(monkeypatch)
    log: list[dict] = []
    _capture_launch(log)

    g = ToolGateway()
    g.set_user_goal("test", WIKI_MOON_GOAL)
    g.run("see_screen", {"goal": "what's on the tab"}, source="test")
    assert g._tracker("test").tainted is True
    assert g._tracker("test").source == "see_screen"

    result = g.run("run_app", {"target": "chrome", "url": WIKI_MOON}, source="test")
    _assert_look_did_not_taint_block(result, log, WIKI_MOON)


def test_look_then_open_goal_url_runs(jarvis_env, monkeypatch):
    from app.jarvis.gateway import ToolGateway

    _forbid_real_launch(monkeypatch)
    _install_fake_look(monkeypatch)
    log: list[dict] = []
    _capture_launch(log)

    g = ToolGateway()
    g.set_user_goal("test", NTV_GOAL)
    _look_then(g)

    result = g.run("run_app", {"target": "chrome", "url": NTV}, source="test")
    assert "confirm_id" not in result
    _assert_look_did_not_taint_block(result, log, NTV)


def test_look_then_open_stranger_url_blocks(jarvis_env, monkeypatch):
    from app.jarvis.gateway import ToolGateway

    _forbid_real_launch(monkeypatch)
    _install_fake_look(monkeypatch)
    log: list[dict] = []
    _capture_launch(log)

    g = ToolGateway()
    g.set_user_goal("test", NTV_GOAL)
    _look_then(g)

    blocked = g.run("run_app", {"target": "chrome", "url": EVIL}, source="test")
    assert blocked.get("ok") is False
    assert blocked.get("blocked") is True
    assert blocked.get("tainted") is True
    assert "untrusted" in (blocked.get("error") or "").lower()
    assert blocked.get("needs_confirm") is not True
    assert log == []


def test_look_then_powershell_blocks(jarvis_env, monkeypatch):
    from app.jarvis.gateway import ToolGateway

    _forbid_real_launch(monkeypatch)
    _install_fake_look(monkeypatch)

    g = ToolGateway()
    g.set_user_goal("test", NTV_GOAL)
    _look_then(g)

    blocked = g.run(
        "run_powershell",
        {"command": "Write-Output pwned"},
        source="test",
        confirmed=True,
    )
    assert blocked.get("ok") is False
    assert blocked.get("blocked") is True
    assert blocked.get("tainted") is True
    assert "untrusted" in (blocked.get("error") or "").lower()
    assert "exit_code" not in blocked


def test_look_then_unknown_app_blocks(jarvis_env, monkeypatch):
    from app.jarvis.gateway import ToolGateway

    _forbid_real_launch(monkeypatch)
    _install_fake_look(monkeypatch)
    log: list[dict] = []
    _capture_launch(log)

    g = ToolGateway()
    g.set_user_goal("test", NTV_GOAL)
    _look_then(g)

    blocked = g.run("run_app", {"target": "totally-unknown-app-xyz"}, source="test")
    assert blocked.get("ok") is False
    assert blocked.get("blocked") is True
    assert log == []


def test_look_then_url_as_target_still_opens_goal(jarvis_env, monkeypatch):
    from app.jarvis.gateway import ToolGateway

    _forbid_real_launch(monkeypatch)
    _install_fake_look(monkeypatch)
    log: list[dict] = []
    _capture_launch(log)

    g = ToolGateway()
    g.set_user_goal("test", NTV_GOAL)
    g.run("see_screen", {"goal": "name headlines"}, source="test")
    assert g._tracker("test").tainted is True

    result = g.run("run_app", {"target": NTV}, source="test")
    _assert_look_did_not_taint_block(result, log, NTV)


def test_taint_clear_with_goal_aliases_realtime(jarvis_env):
    from app.jarvis.gateway import ToolGateway

    g = ToolGateway()
    g._tracker("realtime-model").observe("screenshot")
    assert g._tracker("realtime-model").tainted is True

    g.clear_taint("realtime", goal=NTV_GOAL)
    assert g._tracker("realtime").tainted is False
    assert g._tracker("realtime-model").tainted is False
    assert g._tracker("realtime").user_goal == NTV_GOAL
    assert g._tracker("realtime-model").user_goal == NTV_GOAL


def test_prompts_say_open_url_first_then_look_and_summarize():
    from app.jarvis.agent import SYSTEM_PROMPT
    from app.jarvis.realtime import JARVIS_REALTIME_INSTRUCTIONS

    for text in (SYSTEM_PROMPT, JARVIS_REALTIME_INSTRUCTIONS):
        low = text.lower()
        assert "open the url with run_app first" in low
        assert "then look" in low
        assert "do not ask the user to confirm after a look" in low
        assert "summarize" in low or "one short line" in low
        assert "never ask the user to confirm a look" in low
        assert "retry run_app" in low
        assert "do not ask the user to click chrome" in low
