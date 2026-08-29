import os
import time

import pytest

os.environ.setdefault("API_SECRET", "test-secret")
os.environ.setdefault("TOKEN_PROVIDER", "api_key")
os.environ.setdefault("XAI_API_KEY", "xai-test-key")
os.environ.setdefault("LLM_PROVIDER", "openrouter")
os.environ.setdefault("OPENROUTER_API_KEY", "or-test-key")


def _job(**kwargs):
    from app.store.jobs import Job

    base = dict(
        id="job-1",
        name="daily-briefing",
        prompt_template="hello {{date}}",
        schedule="0 7 * * 1-5",
        model="openrouter/auto",
        memory_doc="",
        memory_version=0,
        enabled=True,
        created_at=1.0,
        updated_at=1.0,
        model_mode="inherit",
        runner="llm",
    )
    base.update(kwargs)
    return Job(**base)


def _run(**kwargs):
    from app.store.jobs import Run

    base = dict(
        id="run-1",
        job_id="job-1",
        status="succeeded",
        started_at=1000.0,
        finished_at=1002.5,
        input_snapshot=None,
        result="ok result body",
        raw_response=None,
        error=None,
        tokens_in=1000,
        tokens_out=500,
        idempotency_key="job-1-2026-08-07",
        llm_provider="openrouter",
        model_requested="openai/gpt-4.1-mini",
        model_effective="openai/gpt-4.1-mini",
    )
    base.update(kwargs)
    return Run(**base)


def test_compatibility_for_job_openrouter():
    from app.schedule.compat import compatibility_for_job

    view = compatibility_for_job(_job(), llm_provider="openrouter", tz_name="UTC")
    assert view.source == "legacy_job"
    assert view.compatibility_mode == "compatibility"
    assert view.provider == "openrouter"
    assert view.cron == "0 7 * * 1-5"
    assert view.paused is False
    assert view.estimated_cost_cents is not None
    assert view.cost_confidence == "estimate"
    assert view.health == "idle"
    joined = " ".join(view.notes).lower()
    assert "legacy" in joined or "compatibility" in joined
    d = view.to_dict()
    assert d["provider"] == "openrouter"
    assert d["compatibility_mode"] == "compatibility"
    assert "run_stats" in d
    assert "health" in d


def test_compatibility_paused_clears_next_run():
    from app.schedule.compat import compatibility_for_job

    view = compatibility_for_job(
        _job(enabled=False), llm_provider="xai", tz_name="Europe/Amsterdam"
    )
    assert view.paused is True
    assert view.provider == "xai"
    assert view.next_run_at is None
    assert view.health == "paused"
    assert view.schedule_human.startswith("Paused")


def test_estimate_metered_from_tokens():
    from app.schedule.compat import estimate_run_cost_cents

    cents, conf = estimate_run_cost_cents(
        provider="openrouter", tokens_in=1000, tokens_out=1000
    )
    assert conf == "metered"
    assert cents == 4  # 2k tokens * 2 cents/1k


def test_normalize_run_status_and_history():
    from app.schedule.compat import (
        compute_run_stats,
        normalize_run,
        normalize_run_status,
    )

    assert normalize_run_status("succeeded") == "succeeded"
    assert normalize_run_status("SUCCESS") == "succeeded"
    assert normalize_run_status("error") == "failed"
    assert normalize_run_status("in_progress") == "running"
    assert normalize_run_status("") == "unknown"

    ok = normalize_run(_run(), schedule_name="daily-briefing")
    assert ok.status == "succeeded"
    assert ok.provider == "openrouter"
    assert ok.duration_ms == 2500
    assert ok.cost_confidence == "metered"
    assert ok.cost_cents == 3  # 1500 tokens * 2 / 1000 = 3
    assert ok.result_summary and "ok result" in ok.result_summary
    assert ok.compatibility_mode == "compatibility"

    fail = normalize_run(
        _run(id="r2", status="failed", tokens_in=None, tokens_out=None, error="boom " * 40),
        schedule_name="daily-briefing",
    )
    assert fail.status == "failed"
    assert fail.error_summary
    assert len(fail.error_summary) <= 281

    stats = compute_run_stats([fail, ok, ok])
    assert stats.total == 3
    assert stats.failed == 1
    assert stats.succeeded == 2
    assert stats.consecutive_failures == 1
    assert stats.success_rate == round(2 / 3, 4)


def test_health_failing_on_streak():
    from app.schedule.compat import compatibility_for_job

    fails = [
        _run(id=f"f{i}", status="failed", tokens_in=10, tokens_out=10) for i in range(3)
    ]
    view = compatibility_for_job(
        _job(),
        llm_provider="openrouter",
        recent_runs=fails,
    )
    assert view.health == "failing"
    assert view.run_stats["consecutive_failures"] == 3
    assert view.last_run_status_normalized == "failed"
    assert len(view.recent_runs) == 3


def test_list_scheduled_work_sorts():
    from app.schedule.compat import list_scheduled_work

    jobs = [
        _job(id="b", name="zebra", schedule="0 9 * * *"),
        _job(id="a", name="alpha", schedule="0 8 * * *"),
    ]
    views = list_scheduled_work(jobs, llm_provider="openrouter", tz_name="UTC")
    assert [v.name for v in views] == ["alpha", "zebra"]


def test_due_state_overdue_and_filters():
    from app.schedule.compat import (
        evaluate_due_state,
        filter_schedule_views,
        list_scheduled_work,
        approx_period_seconds,
    )

    assert approx_period_seconds("0 7 * * *") == 86400
    assert approx_period_seconds("*/15 * * * *") == 15 * 60

    due, overdue = evaluate_due_state(
        paused=False,
        has_cron=True,
        cron="0 7 * * *",
        last_run_started_at=time.time() - 3 * 86400,
    )
    assert due == "overdue"
    assert overdue is not None and overdue > 0

    assert evaluate_due_state(
        paused=True, has_cron=True, cron="0 7 * * *", last_run_started_at=1.0
    )[0] == "paused"
    assert evaluate_due_state(
        paused=False, has_cron=True, cron="0 7 * * *", last_run_started_at=None
    )[0] == "never_run"

    old = _run(id="old", started_at=time.time() - 4 * 86400, finished_at=time.time() - 4 * 86400)
    views = list_scheduled_work(
        [_job(id="job-1", schedule="0 7 * * *")],
        llm_provider="openrouter",
        last_runs={"job-1": old},
        runs_by_job={"job-1": [old]},
    )
    assert views[0].due_state == "overdue"
    assert views[0].health in ("degraded", "failing", "healthy")
    filtered = filter_schedule_views(views, due_state="overdue", provider="openrouter")
    assert len(filtered) == 1


@pytest.mark.asyncio
async def test_api_schedules_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("API_SECRET", "test-secret")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("LLM_MODEL_MODE", "fixed")
    monkeypatch.setenv("DEFAULT_MODEL", "openai/gpt-4.1-mini")

    from app.config import get_settings

    get_settings.cache_clear()
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            h = {"X-Api-Key": "test-secret"}
            created = await ac.post(
                "/api/jobs",
                headers=h,
                json={
                    "name": "sched-compat",
                    "prompt_template": "ping {{date}}",
                    "schedule": "0 7 * * *",
                    "model": "openai/gpt-4.1-mini",
                },
            )
            assert created.status_code == 200, created.text
            job_id = created.json()["job"]["id"]

            # Seed a finished run directly (no LLM execution)
            store = app.state.job_store
            run = await store.create_run(
                job_id=job_id,
                status="running",
                input_snapshot="test",
                idempotency_key=f"seed-{time.time()}",
            )
            await store.finish_run(
                run.id,
                status="succeeded",
                result="hello from seed",
                tokens_in=800,
                tokens_out=200,
                llm_provider="openrouter",
                model_requested="openai/gpt-4.1-mini",
                model_effective="openai/gpt-4.1-mini",
            )

            r = await ac.get("/api/schedules", headers=h)
            assert r.status_code == 200
            body = r.json()
            assert body["adapter"] == "legacy_job_v1"
            assert "summary" in body
            assert len(body["schedules"]) >= 1
            row = next(s for s in body["schedules"] if s["name"] == "sched-compat")
            assert row["compatibility_mode"] == "compatibility"
            assert row["provider"] == "openrouter"
            assert row["cron"] == "0 7 * * *"
            assert "estimated_cost_cents" in row
            assert "health" in row
            assert "run_stats" in row
            assert isinstance(body.get("recent_runs"), list)
            assert isinstance(body.get("upcoming"), list)
            assert any(u.get("schedule_id") == job_id for u in body["upcoming"])

            # Grok model preserved as xai while default LLM is openrouter
            grok = await ac.post(
                "/api/jobs",
                headers=h,
                json={
                    "name": "legacy-grok-daily",
                    "prompt_template": "grok {{date}}",
                    "schedule": "0 8 * * *",
                    "model": "grok-4.3",
                },
            )
            assert grok.status_code == 200, grok.text
            filtered = await ac.get("/api/schedules?provider=xai", headers=h)
            assert filtered.status_code == 200
            fb = filtered.json()
            assert any(
                s["name"] == "legacy-grok-daily" and s["provider"] == "xai"
                for s in fb["schedules"]
            )
            assert all(s["provider"] == "xai" for s in fb["schedules"])

            up = await ac.get("/api/schedules/upcoming?days=3&limit=20", headers=h)
            assert up.status_code == 200
            assert up.json()["read_only"] is True
            assert up.json()["count"] == len(up.json()["upcoming"])

            runs_r = await ac.get("/api/schedules/runs", headers=h)
            assert runs_r.status_code == 200
            runs_body = runs_r.json()
            assert runs_body["adapter"] == "legacy_job_v1"
            assert any(x.get("schedule_id") == job_id for x in runs_body["runs"])

            detail = await ac.get(f"/api/schedules/{job_id}", headers=h)
            assert detail.status_code == 200
            dbody = detail.json()
            assert dbody["schedule"]["id"] == job_id
            assert dbody["schedule"]["due_state"] in (
                "on_track", "overdue", "never_run", "paused", "unscheduled", "unknown"
            )
            assert isinstance(dbody["runs"], list)
            assert dbody["runs"]

            status = await ac.get("/api/status", headers=h)
            assert status.status_code == 200
            assert "schedules" in status.json()
            assert "schedule_count" in status.json()["schedules"]

            overview = await ac.get("/api/dashboard/overview", headers=h)
            assert overview.status_code == 200
            ov = overview.json()
            jobs = ov["jobs"]
            match = next(j for j in jobs if j["name"] == "sched-compat")
            assert "scheduled_work" in match
            assert match["scheduled_work"]["compatibility_mode"] == "compatibility"
            assert "due_state" in match["scheduled_work"]
            assert "schedules" in ov
            assert "schedule_runs" in ov
            assert "schedule_upcoming" in ov
            assert any(s["name"] == "sched-compat" for s in ov["schedules"])
            page = await ac.get("/dashboard")
            assert page.status_code == 200
            assert "Upcoming fires" in page.text or "scheduleUpcoming" in page.text
    get_settings.cache_clear()


def test_grok_provider_preserved_when_default_openrouter():
    from app.schedule.compat import compatibility_for_job, filter_schedule_views

    view = compatibility_for_job(
        _job(name="g", model="grok-4.3", schedule="0 6 * * 1-5"),
        llm_provider="openrouter",
    )
    assert view.provider == "xai"
    joined = " ".join(view.notes)
    assert "Grok" in joined or "xAI" in joined
    assert len(filter_schedule_views([view], provider="grok")) == 1


def test_upcoming_fires_skips_paused_and_orders():
    from app.schedule.compat import build_upcoming_fires, compatibility_for_job

    active = compatibility_for_job(
        _job(id="a", name="active", schedule="0 7 * * *", enabled=True),
        llm_provider="openrouter",
    )
    paused = compatibility_for_job(
        _job(id="b", name="paused", schedule="0 7 * * *", enabled=False),
        llm_provider="openrouter",
    )
    events = build_upcoming_fires([paused, active], days=3, limit=10, per_schedule=3)
    assert events
    assert all(e["schedule_id"] == "a" for e in events)
    ts = [e["fire_ts"] for e in events]
    assert ts == sorted(ts)


def test_next_cron_fires_window():
    from datetime import datetime, timezone

    from app.schedule_util import next_cron_fires

    after = datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc)
    fires = next_cron_fires(
        "0 7 * * *", tz_name="UTC", after=after, limit=5, within_hours=72
    )
    assert len(fires) == 3
    assert fires[0].hour == 7


@pytest.mark.asyncio
async def test_read_only_views_do_not_execute_grok_or_touch_credentials(
    tmp_path, monkeypatch
):
    """Integration gate: compatibility views must stay observational only."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "gate.db"))
    monkeypatch.setenv("API_SECRET", "test-secret")
    monkeypatch.setenv("TOKEN_PROVIDER", "oauth")
    monkeypatch.setenv("LLM_PROVIDER", "xai")
    monkeypatch.setenv("DEFAULT_MODEL", "grok-4.3")

    from app.config import get_settings

    get_settings.cache_clear()
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        headers = {"X-Api-Key": "test-secret"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            created = await ac.post(
                "/api/jobs",
                headers=headers,
                json={
                    "name": "grok-gate",
                    "prompt_template": "never execute",
                    "schedule": "0 9 * * *",
                    "model": "grok-4.3",
                },
            )
            assert created.status_code == 200, created.text
            job_id = created.json()["job"]["id"]

            await app.state.auth_store.save(
                access_token="gate-access-token",
                refresh_token="gate-refresh-token",
                expires_at=time.time() + 3600,
                token_endpoint="https://example.invalid/token",
                redirect_uri="http://localhost/callback",
                provider_type="oauth",
            )

            async def execution_is_forbidden(*args, **kwargs):
                raise AssertionError("read-only compatibility view invoked Grok execution")

            monkeypatch.setattr(app.state.runner, "run_job", execution_is_forbidden)
            before_cur = await app.state.db.conn.execute(
                "SELECT * FROM auth_tokens WHERE id = 1"
            )
            before = await before_cur.fetchone()
            assert before is not None
            before = dict(before)

            responses = [
                await ac.get("/api/schedules?provider=grok", headers=headers),
                await ac.get(f"/api/schedules/{job_id}", headers=headers),
                await ac.get("/api/schedules/runs?provider=xai", headers=headers),
                await ac.get("/api/schedules/upcoming", headers=headers),
                await ac.get("/api/dashboard/overview", headers=headers),
                await ac.get("/history"),
            ]
            assert all(response.status_code == 200 for response in responses)

            schedules = responses[0].json()["schedules"]
            assert len(schedules) == 1
            assert schedules[0]["provider"] == "xai"
            assert "estimated_cost_cents" in schedules[0]
            assert responses[1].json()["schedule"]["compatibility_mode"] == "compatibility"
            assert responses[2].json()["adapter"] == "legacy_job_v1"
            assert "Provider" in responses[5].text
            assert "Cost" in responses[5].text

            after_cur = await app.state.db.conn.execute(
                "SELECT * FROM auth_tokens WHERE id = 1"
            )
            after = await after_cur.fetchone()
            assert after is not None
            assert dict(after) == before
    get_settings.cache_clear()

@pytest.mark.asyncio
async def test_scheduled_work_port_read_only(tmp_path, monkeypatch):
    """Control-plane port is read-only and preserves Grok labeling."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "port.db"))
    monkeypatch.setenv("API_SECRET", "test-secret")
    monkeypatch.setenv("TOKEN_PROVIDER", "api_key")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("DEFAULT_MODEL", "openai/gpt-4.1-mini")

    from app.config import get_settings
    get_settings.cache_clear()
    from app.main import create_app
    from app.schedule.legacy_port import build_scheduled_work_port
    from app.schedule.protocol import ScheduledWorkPort

    app = create_app()
    async with app.router.lifespan_context(app):
        port = build_scheduled_work_port(app.state.job_store, app.state.settings)
        assert isinstance(port, ScheduledWorkPort)
        job = await app.state.job_store.create_job(
            name="grok-daily",
            prompt_template="brief {{date}}",
            model="grok-4.3",
            schedule="0 7 * * *",
        )
        listing = await port.list_schedules()
        assert listing["adapter"] == "legacy_job_v1"
        row = next(s for s in listing["schedules"] if s["id"] == job.id)
        assert row["provider"] == "xai"
        assert row["compatibility_mode"] == "compatibility"
        detail = await port.get_schedule(job.id)
        assert detail is not None
        assert detail["schedule"]["id"] == job.id
        runs = await port.list_runs(limit=10)
        assert "runs" in runs
        upcoming = await port.list_upcoming(days=3, limit=20)
        assert upcoming["count"] >= 1
        summ = await port.summary()
        assert summ["schedule_count"] >= 1
    get_settings.cache_clear()
