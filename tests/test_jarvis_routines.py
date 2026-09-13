"""Windows Routines list — issue #72. Real local schedules or honest empty."""

from __future__ import annotations

import os

os.environ.setdefault("API_SECRET", "test-secret-at-least-32-chars-long!!")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "")
os.environ.setdefault("TOKEN_PROVIDER", "api_key")
os.environ.setdefault("XAI_API_KEY", "xai-test-key")
os.environ.setdefault("LLM_PROVIDER", "openrouter")
os.environ.setdefault("OPENROUTER_API_KEY", "or-test-key")
os.environ.setdefault("LLM_MODEL_MODE", "fixed")
os.environ.setdefault("DEFAULT_MODEL", "openai/gpt-4.1-mini")

import pytest
from httpx import ASGITransport, AsyncClient

from app.jarvis.routines import (
    ADD_SOON,
    EMPTY_LABEL,
    routine_from_job,
    routines_from_jobs,
    routines_payload,
)


class _Job:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", "")
        self.name = kwargs.get("name", "")
        self.schedule = kwargs.get("schedule")
        self.enabled = kwargs.get("enabled", True)


def test_routine_from_job_is_mom_friendly_and_skips_blanks():
    row = routine_from_job(_Job(id="j1", name="Inbox sort", schedule="0 7 * * *", enabled=True))
    assert row is not None
    assert row["id"] == "j1"
    assert row["name"] == "Inbox sort"
    assert row["enabled"] is True
    assert row["source"] == "local-schedules"
    assert row["read_only"] is True
    assert row["when"]
    assert "Morning briefing" not in row["name"]
    assert routine_from_job(_Job(id="", name="Ghost")) is None
    assert routine_from_job(_Job(id="x", name="")) is None
    off = routine_from_job(_Job(id="j2", name="Paused", schedule="0 8 * * *", enabled=False))
    assert off["enabled"] is False
    assert off["when"].startswith("Off")


def test_routines_from_jobs_does_not_invent_samples():
    assert routines_from_jobs([]) == []
    assert routines_from_jobs(None) == []
    items = routines_from_jobs([_Job(id="a", name="Weekly wrap", schedule="0 9 * * 1")])
    assert [row["name"] for row in items] == ["Weekly wrap"]
    assert not any("Morning briefing" in row["name"] or "Evening wrap" in row["name"] for row in items)


@pytest.mark.asyncio
async def test_routines_payload_empty_and_real():
    empty = await routines_payload(None)
    assert empty["empty"] is True
    assert empty["routines"] == []
    assert empty["can_create"] is False
    assert empty["empty_label"] == EMPTY_LABEL
    assert empty["add_soon"] == ADD_SOON

    class _Store:
        async def list_jobs(self):
            return [_Job(id="job-1", name="Inbox sort", schedule="0 7 * * *", enabled=True)]

    filled = await routines_payload(_Store())
    assert filled["empty"] is False
    assert filled["routines"][0]["name"] == "Inbox sort"
    assert filled["can_create"] is False


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("API_SECRET", "test-secret-at-least-32-chars-long!!")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("LLM_MODEL_MODE", "fixed")
    monkeypatch.setenv("DEFAULT_MODEL", "openai/gpt-4.1-mini")
    monkeypatch.setenv("JARVIS_ENABLED", "true")
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


@pytest.mark.asyncio
async def test_jarvis_routines_empty_without_api_key(client):
    ac, _app = client
    r = await ac.get("/api/jarvis/routines")
    assert r.status_code == 200
    body = r.json()
    assert body["routines"] == []
    assert body["empty"] is True
    assert body["can_create"] is False
    assert body["empty_label"] == "No routines yet."
    assert "Morning briefing" not in r.text
    assert "or-test-key" not in r.text
    assert "API_SECRET" not in r.text


@pytest.mark.asyncio
async def test_jarvis_routines_lists_real_local_job(client):
    ac, app = client
    job = await app.state.job_store.create_job(
        name="Inbox sort",
        prompt_template="Sort the inbox.",
        model="openai/gpt-4.1-mini",
        schedule="0 7 * * *",
        enabled=True,
    )
    r = await ac.get("/api/jarvis/routines")
    assert r.status_code == 200
    body = r.json()
    assert body["empty"] is False
    assert body["can_create"] is False
    names = [row["name"] for row in body["routines"]]
    assert "Inbox sort" in names
    assert job.id in {row["id"] for row in body["routines"]}
    assert all(row["source"] == "local-schedules" for row in body["routines"])
    assert "Sort the inbox." not in r.text
    assert "or-test-key" not in r.text
