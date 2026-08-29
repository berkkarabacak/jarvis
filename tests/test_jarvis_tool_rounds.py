"""Look-act-look jobs get a higher tool-round cap; chat stays cheap."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.jarvis.agent import (
    CHAT_TOOL_ROUNDS,
    LOOK_JOB_STOP_PROMPT,
    LOOK_JOB_TOOL_ROUNDS,
    MAX_TOOL_ROUNDS_CAP,
    JarvisLocalAgent,
    build_jarvis_agent,
    clamp_tool_rounds,
    is_desktop_look_job,
    resolve_tool_rounds,
    tool_round_budget,
)

# Live failure shape: two-tab summary dies after 16 rounds (tsk_* on XPS13).
TWO_TAB_SEE_KEYS_GOAL = (
    "Open https://www.ntv.com.tr with run_app. focus_app chrome. "
    "see_screen. keys ctrl+tab. see_screen. Summarize both pages."
)

CHAT_GOAL = "What is 2 plus 2?"


@pytest.fixture
def jarvis_env(tmp_path, monkeypatch):
    ws = tmp_path / "Jarvis"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE", str(ws))
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PERMISSION_PROFILE", "personal")
    monkeypatch.setenv("BRIDGE_ENABLED", "true")
    monkeypatch.setenv("BRIDGE_TOKEN", "test-bridge-token-secret")
    monkeypatch.setenv("BRIDGE_MAX_TIER_AUTO", "L1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key-not-real")
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    import app.jarvis.bridge_routes as br
    import app.jarvis.gateway as gw
    from app.jarvis import settings_store

    gw._gateway = None
    br._store = None
    settings_store.reset_cache()
    yield ws
    gw._gateway = None
    br._store = None
    settings_store.reset_cache()


def test_see_screen_keys_job_is_look_job():
    assert is_desktop_look_job(TWO_TAB_SEE_KEYS_GOAL) is True
    assert is_desktop_look_job("see_screen and name headlines") is True
    assert is_desktop_look_job("keys ctrl+tab then look") is True
    assert is_desktop_look_job("run_app chrome then look") is True
    assert is_desktop_look_job("focus_app chrome") is True


def test_chat_and_api_keys_are_not_look_jobs():
    assert is_desktop_look_job(CHAT_GOAL) is False
    assert is_desktop_look_job("Hello Jarvis") is False
    assert is_desktop_look_job("Never expose API keys") is False
    assert is_desktop_look_job("What's on my screen?") is False


def test_see_screen_keys_job_gets_higher_round_budget():
    assert tool_round_budget(TWO_TAB_SEE_KEYS_GOAL) == LOOK_JOB_TOOL_ROUNDS
    assert LOOK_JOB_TOOL_ROUNDS == 32
    assert resolve_tool_rounds(TWO_TAB_SEE_KEYS_GOAL) == 32


def test_chat_goal_keeps_cheap_round_budget():
    assert tool_round_budget(CHAT_GOAL) == CHAT_TOOL_ROUNDS
    assert CHAT_TOOL_ROUNDS == 16
    assert resolve_tool_rounds(CHAT_GOAL) == 16
    assert resolve_tool_rounds("Never expose API keys") == 16
    assert resolve_tool_rounds("What's on my screen?") == 16


def test_explicit_override_wins_and_stays_capped():
    assert resolve_tool_rounds(TWO_TAB_SEE_KEYS_GOAL, 12) == 12
    assert resolve_tool_rounds(CHAT_GOAL, 8) == 8
    assert resolve_tool_rounds(CHAT_GOAL, 99) == MAX_TOOL_ROUNDS_CAP
    assert clamp_tool_rounds(99) == 32
    assert MAX_TOOL_ROUNDS_CAP == 32


def test_agent_accepts_look_job_cap_not_old_24():
    agent = JarvisLocalAgent(api_key="sk-test", max_tool_rounds=LOOK_JOB_TOOL_ROUNDS)
    assert agent._max_rounds == 32
    capped = JarvisLocalAgent(api_key="sk-test", max_tool_rounds=99)
    assert capped._max_rounds == 32
    chat = JarvisLocalAgent(api_key="sk-test", max_tool_rounds=CHAT_TOOL_ROUNDS)
    assert chat._max_rounds == 16


def test_build_jarvis_agent_picks_look_vs_chat_budget(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    look = build_jarvis_agent(api_key="sk-test", goal=TWO_TAB_SEE_KEYS_GOAL)
    chat = build_jarvis_agent(api_key="sk-test", goal=CHAT_GOAL)
    assert look is not None and chat is not None
    assert look._max_rounds == 32
    assert chat._max_rounds == 16


def test_prompts_say_stop_after_real_words():
    from app.jarvis.agent import SYSTEM_PROMPT
    from app.jarvis.realtime import JARVIS_REALTIME_INSTRUCTIONS

    needle = "after you have real words from the requested pages"
    for text in (SYSTEM_PROMPT, JARVIS_REALTIME_INSTRUCTIONS, LOOK_JOB_STOP_PROMPT):
        low = text.lower()
        assert needle in low
        assert "do not keep switching tabs" in low


@pytest.mark.asyncio
async def test_bridge_passes_look_budget_for_see_screen_keys_job(jarvis_env, monkeypatch):
    captured: dict = {}

    class FakeAgent:
        _model = "openai/gpt-4.1-mini"
        _model_route = {}
        _tools_called: list[str] = []

        async def start_session(self, role_name="bridge"):
            return SimpleNamespace(session_id="sess_look")

        async def send_message(self, session_id, *, message):
            captured["bridged_goal"] = message
            return SimpleNamespace(text="Combined summary of both pages.", generation=None)

        async def stop_session(self, session_id, *, reason=""):
            return None

    def fake_build(**kwargs):
        captured["kwargs"] = kwargs
        return FakeAgent()

    monkeypatch.setattr("app.jarvis.agent.build_jarvis_agent", fake_build)

    import app.jarvis.bridge_routes as br

    store = br._store_get()
    task = store.create_task(goal=TWO_TAB_SEE_KEYS_GOAL, source="test")
    await br._execute_task(task["task_id"])

    assert captured["kwargs"]["max_tool_rounds"] == 32
    assert captured["kwargs"]["max_auto"] == 1  # bridge L1 — permission, not rounds
    assert LOOK_JOB_STOP_PROMPT in captured["bridged_goal"]
    assert "Do not keep switching tabs" in captured["bridged_goal"]


@pytest.mark.asyncio
async def test_bridge_keeps_chat_budget_and_no_look_policy(jarvis_env, monkeypatch):
    captured: dict = {}

    class FakeAgent:
        _model = "openai/gpt-4.1-mini"
        _model_route = {}
        _tools_called: list[str] = []

        async def start_session(self, role_name="bridge"):
            return SimpleNamespace(session_id="sess_chat")

        async def send_message(self, session_id, *, message):
            captured["bridged_goal"] = message
            return SimpleNamespace(text="4", generation=None)

        async def stop_session(self, session_id, *, reason=""):
            return None

    def fake_build(**kwargs):
        captured["kwargs"] = kwargs
        return FakeAgent()

    monkeypatch.setattr("app.jarvis.agent.build_jarvis_agent", fake_build)

    import app.jarvis.bridge_routes as br

    store = br._store_get()
    task = store.create_task(goal=CHAT_GOAL, source="test")
    await br._execute_task(task["task_id"])

    assert captured["kwargs"]["max_tool_rounds"] == 16
    assert captured["kwargs"]["max_auto"] == 1
    assert LOOK_JOB_STOP_PROMPT not in captured["bridged_goal"]
