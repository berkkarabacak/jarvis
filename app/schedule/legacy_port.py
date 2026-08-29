"""Legacy jobs/runs implementation of ScheduledWorkPort (ORCH-73).

Read-only. Does not execute jobs, touch credentials, or alter Grok behavior.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.schedule.compat import (
    build_upcoming_fires,
    compatibility_for_job,
    filter_run_views,
    filter_schedule_views,
    list_normalized_runs,
    list_scheduled_work,
    summarize_schedule_views,
)
from app.store.jobs import JobStore

ADAPTER_ID = "legacy_job_v1"


class LegacyJobScheduledWorkPort:
    """Adapt existing JobStore jobs/runs into Control Room schedule views."""

    adapter_id: str = ADAPTER_ID

    def __init__(self, jobs: JobStore, settings: Settings) -> None:
        self._jobs = jobs
        self._settings = settings

    def _tz(self) -> str:
        return self._settings.tz or "UTC"

    def _llm_provider(self) -> str:
        return (self._settings.llm_provider or "openrouter").strip().lower()

    async def _load_views(
        self, *, run_history_limit: int = 8
    ) -> tuple[list[Any], dict[str, str]]:
        items = await self._jobs.list_jobs()
        last_runs: dict[str, Any] = {}
        runs_by_job: dict[str, list[Any]] = {}
        for j in items:
            hist = await self._jobs.list_runs(j.id, limit=run_history_limit)
            if hist:
                runs_by_job[j.id] = hist
                last_runs[j.id] = hist[0]
        views = list_scheduled_work(
            items,
            llm_provider=self._llm_provider(),
            tz_name=self._tz(),
            last_runs=last_runs,
            runs_by_job=runs_by_job,
        )
        names = {j.id: j.name for j in items}
        return views, names

    async def list_schedules(
        self,
        *,
        run_history_limit: int = 8,
        health: str | None = None,
        provider: str | None = None,
        due_state: str | None = None,
        enabled: bool | None = None,
        paused: bool | None = None,
        runner: str | None = None,
    ) -> dict[str, Any]:
        views, names = await self._load_views(run_history_limit=run_history_limit)
        filtered = filter_schedule_views(
            views,
            health=health,
            provider=provider,
            due_state=due_state,
            enabled=enabled,
            paused=paused,
            runner=runner,
        )
        recent_raw = await self._jobs.recent_runs(limit=40)
        recent_norm = list_normalized_runs(
            recent_raw,
            job_names=names,
            default_provider=self._llm_provider(),
        )
        return {
            "adapter": self.adapter_id,
            "timezone": self._tz(),
            "llm_provider": self._llm_provider(),
            "summary": summarize_schedule_views(views),
            "filtered_count": len(filtered),
            "schedules": [v.to_dict() for v in filtered],
            "recent_runs": [r.to_dict() for r in recent_norm],
            "note": (
                "Legacy jobs/runs exposed as scheduled work for AI Control Room. "
                "compatibility_mode=compatibility until native schedule model lands. "
                "Read-only adapter — does not change job execution or credentials."
            ),
        }

    async def get_schedule(
        self,
        schedule_id: str,
        *,
        run_history_limit: int = 20,
    ) -> dict[str, Any] | None:
        job = await self._jobs.get_job(schedule_id)
        if job is None:
            return None
        hist = await self._jobs.list_runs(schedule_id, limit=run_history_limit)
        lr = hist[0] if hist else None
        view = compatibility_for_job(
            job,
            llm_provider=self._llm_provider(),
            tz_name=self._tz(),
            last_run=lr,
            recent_runs=hist,
        )
        runs = list_normalized_runs(
            hist,
            job_names={schedule_id: job.name},
            default_provider=self._llm_provider(),
        )
        return {
            "adapter": self.adapter_id,
            "timezone": self._tz(),
            "llm_provider": self._llm_provider(),
            "schedule": view.to_dict(),
            "runs": [r.to_dict() for r in runs],
        }

    async def list_runs(
        self,
        *,
        limit: int = 50,
        schedule_id: str | None = None,
        status: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        names = await self._jobs.list_job_names()
        if schedule_id:
            job = await self._jobs.get_job(schedule_id)
            if job is None:
                return {
                    "adapter": self.adapter_id,
                    "llm_provider": self._llm_provider(),
                    "count": 0,
                    "runs": [],
                    "not_found": True,
                }
            raw = await self._jobs.list_runs(schedule_id, limit=limit)
        else:
            raw = await self._jobs.recent_runs(limit=limit)
        normalized = list_normalized_runs(
            raw, job_names=names, default_provider=self._llm_provider()
        )
        filtered = filter_run_views(
            normalized,
            status=status,
            provider=provider,
            schedule_id=schedule_id,
        )
        return {
            "adapter": self.adapter_id,
            "llm_provider": self._llm_provider(),
            "count": len(filtered),
            "runs": [r.to_dict() for r in filtered],
        }

    async def list_upcoming(
        self,
        *,
        days: int = 7,
        limit: int = 100,
        provider: str | None = None,
        health: str | None = None,
    ) -> dict[str, Any]:
        views, _ = await self._load_views(run_history_limit=1)
        filtered = filter_schedule_views(views, provider=provider, health=health)
        fires = build_upcoming_fires(
            filtered,
            days=float(days),
            limit=limit,
        )
        return {
            "adapter": self.adapter_id,
            "timezone": self._tz(),
            "llm_provider": self._llm_provider(),
            "days": days,
            "count": len(fires),
            "upcoming": fires,
            "note": "Projected fires only — does not dispatch or alter Cloud Scheduler.",
        }

    async def summary(self) -> dict[str, Any]:
        views, _ = await self._load_views(run_history_limit=1)
        data = summarize_schedule_views(views)
        data["adapter"] = self.adapter_id
        data["timezone"] = self._tz()
        data["llm_provider"] = self._llm_provider()
        return data


def build_scheduled_work_port(jobs: JobStore, settings: Settings) -> LegacyJobScheduledWorkPort:
    """Factory for the active scheduled-work port (legacy only for now)."""
    return LegacyJobScheduledWorkPort(jobs, settings)
