"""ORCH-393: tab analysis is a first-class job on the existing scheduler clock."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.jobs.tab_analysis import (
    SHORT_DELAY_CRON,
    TAB_ANALYSIS_GOAL,
    TAB_ANALYSIS_JOB_NAME,
    invoke_desktop_look_goal,
    is_look_keys_combined_analysis,
    tab_analysis_job_payload,
)
from app.jarvis.agent import LOOK_JOB_STOP_PROMPT, is_desktop_look_job


HEADERS = {"X-Api-Key": "test-secret"}

COMBINED_FAKE = (
    "Combined analysis of the pages actually seen: example.com domain page "
    "and the next Chrome tab."
)


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "tab.db"))
    monkeypatch.setenv("API_SECRET", "test-secret")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("LLM_MODEL_MODE", "fixed")
    monkeypatch.setenv("DEFAULT_MODEL", "openai/gpt-4.1-mini")
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path / "Jarvis"))

    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, app
    get_settings.cache_clear()


def test_canonical_goal_is_look_keys_combined_analysis():
    payload = tab_analysis_job_payload()
    goal = payload["prompt_template"]
    assert goal == TAB_ANALYSIS_GOAL
    assert payload["name"] == TAB_ANALYSIS_JOB_NAME
    assert payload["runner"] == "llm"
    assert "schedule" not in payload
    assert is_desktop_look_job(goal) is True
    assert is_look_keys_combined_analysis(goal) is True
    low = goal.lower()
    assert "run_app" in low
    assert "focus_app" in low
    assert "keys" in low
    assert "ctrl+tab" in low
    assert "see_screen" in low
    assert "combined analysis" in low
    assert "actually saw" in low


def test_short_delay_payload_keeps_same_goal_and_clock():
    payload = tab_analysis_job_payload(schedule=SHORT_DELAY_CRON)
    assert payload["schedule"] == "* * * * *"
    assert payload["prompt_template"] == TAB_ANALYSIS_GOAL
    assert is_look_keys_combined_analysis(payload["prompt_template"]) is True


def test_chat_goals_are_not_tab_analysis():
    assert is_look_keys_combined_analysis("What is 2 plus 2?") is False
    assert is_look_keys_combined_analysis("Never expose API keys") is False
    assert is_look_keys_combined_analysis("Hello Jarvis") is False
    assert is_look_keys_combined_analysis("see_screen and name headlines") is False


@pytest.mark.asyncio
async def test_create_oneshot_job_via_jobs_api(client):
    ac, _app = client
    r = await ac.post("/api/jobs", headers=HEADERS, json=tab_analysis_job_payload())
    assert r.status_code == 200
    job = r.json()["job"]
    assert job["name"] == TAB_ANALYSIS_JOB_NAME
    assert job["prompt_template"] == TAB_ANALYSIS_GOAL
    assert job["schedule"] in (None, "")
    assert job["enabled"] is True
    assert is_look_keys_combined_analysis(job["prompt_template"]) is True


@pytest.mark.asyncio
async def test_scheduler_run_invokes_tab_analysis_goal(client, monkeypatch):
    ac, app = client
    captured: dict = {}

    async def fake_invoke(goal, **kwargs):
        captured["goal"] = goal
        captured["kwargs"] = kwargs
        return {
            "text": COMBINED_FAKE,
            "tools_called": ["run_app", "focus_app", "see_screen", "keys"],
            "model": "openai/gpt-4.1-mini",
        }

    monkeypatch.setattr("app.runner.runner.invoke_desktop_look_goal", fake_invoke)

    created = await ac.post(
        "/api/jobs", headers=HEADERS, json=tab_analysis_job_payload()
    )
    assert created.status_code == 200
    job = created.json()["job"]

    # Empty POST body — the job definition carries the goal (no human analysis text).
    ran = await ac.post(f"/api/jobs/{job['id']}/run", headers=HEADERS)
    assert ran.status_code == 200
    run = ran.json()["run"]
    assert run["status"] == "succeeded"
    assert run["result"] == COMBINED_FAKE
    assert captured["goal"] == TAB_ANALYSIS_GOAL
    assert is_look_keys_combined_analysis(captured["goal"]) is True
    snap = run.get("input_snapshot") or ""
    if snap:
        import json

        body = json.loads(snap)
        assert body.get("path") == "desktop_look"
        assert body.get("goal") == TAB_ANALYSIS_GOAL


@pytest.mark.asyncio
async def test_short_delay_job_uses_same_run_clock(client, monkeypatch):
    ac, _app = client
    invoked = AsyncMock(
        return_value={
            "text": COMBINED_FAKE,
            "tools_called": ["keys", "see_screen"],
            "model": "openai/gpt-4.1-mini",
        }
    )
    monkeypatch.setattr("app.runner.runner.invoke_desktop_look_goal", invoked)

    created = await ac.post(
        "/api/jobs",
        headers=HEADERS,
        json=tab_analysis_job_payload(schedule=SHORT_DELAY_CRON),
    )
    job = created.json()["job"]
    assert job["schedule"] == SHORT_DELAY_CRON

    ran = await ac.post(f"/api/jobs/{job['id']}/run", headers=HEADERS)
    assert ran.status_code == 200
    assert ran.json()["run"]["status"] == "succeeded"
    invoked.assert_awaited_once()
    goal = invoked.await_args.args[0]
    assert is_look_keys_combined_analysis(goal) is True
    assert goal == TAB_ANALYSIS_GOAL


@pytest.mark.asyncio
async def test_plain_llm_job_does_not_take_desktop_path(client, monkeypatch):
    ac, app = client
    invoked = AsyncMock(side_effect=AssertionError("desktop path must not run"))
    monkeypatch.setattr("app.runner.runner.invoke_desktop_look_goal", invoked)

    async def fake_chat(*, model, messages, temperature=0.2):
        from app.llm.base import ChatResult

        return ChatResult(
            content='{"result":"brief ok","memory":""}',
            raw={},
            tokens_in=1,
            tokens_out=1,
            model=model,
            provider="openrouter",
        )

    monkeypatch.setattr(app.state.runner.llm, "chat", fake_chat)

    created = await ac.post(
        "/api/jobs",
        headers=HEADERS,
        json={"name": "daily-brief", "prompt_template": "Summarize open threads"},
    )
    job = created.json()["job"]
    ran = await ac.post(f"/api/jobs/{job['id']}/run", headers=HEADERS)
    assert ran.status_code == 200
    assert ran.json()["run"]["status"] == "succeeded"
    assert ran.json()["run"]["result"] == "brief ok"
    invoked.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_jarvis_fails_without_inventing_pages(client):
    ac, _app = client
    created = await ac.post(
        "/api/jobs", headers=HEADERS, json=tab_analysis_job_payload()
    )
    job = created.json()["job"]
    ran = await ac.post(f"/api/jobs/{job['id']}/run", headers=HEADERS)
    assert ran.status_code == 200
    run = ran.json()["run"]
    assert run["status"] == "failed"
    err = (run["error"] or "").lower()
    assert "jarvis" in err
    assert "invent" not in (run["result"] or "").lower()


@pytest.mark.asyncio
async def test_invoke_helper_starts_jarvis_with_look_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path / "Jarvis"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key-not-real")
    captured: dict = {}

    class FakeAgent:
        _model = "openai/gpt-4.1-mini"
        _tools_called = ["run_app", "keys", "see_screen"]

        async def start_session(self, role_name="job-scheduler"):
            captured["role"] = role_name
            return SimpleNamespace(session_id="sess_tab")

        async def send_message(self, session_id, *, message):
            captured["message"] = message
            return SimpleNamespace(text=COMBINED_FAKE, generation=None)

        async def stop_session(self, session_id, *, reason=""):
            captured["stop"] = reason
            return None

    def fake_build(**kwargs):
        captured["kwargs"] = kwargs
        return FakeAgent()

    monkeypatch.setattr("app.jarvis.agent.build_jarvis_agent", fake_build)

    out = await invoke_desktop_look_goal(TAB_ANALYSIS_GOAL, api_key="sk-test")
    assert out["text"] == COMBINED_FAKE
    assert captured["role"] == "job-scheduler"
    assert captured["kwargs"]["goal"] == TAB_ANALYSIS_GOAL
    assert captured["kwargs"]["max_tool_rounds"] == 32
    assert captured["kwargs"]["tool_source"] == "job-scheduler"
    assert LOOK_JOB_STOP_PROMPT in captured["message"]
    assert TAB_ANALYSIS_GOAL in captured["message"]
