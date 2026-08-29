"""Control-plane interfaces for scheduled work (ORCH-73).

These protocols define the **read-only** surface the AI Control Room and a
future deterministic control plane can depend on. They deliberately omit:

- job execution / dispatch
- credential or secret access
- pause/resume/delete mutations (those stay on existing job APIs for now)

Legacy jobs/runs are adapted via ``LegacyJobScheduledWorkPort`` without changing
Grok or OpenRouter run paths.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ScheduledWorkPort(Protocol):
    """Read-only scheduled-work catalog + run history for Control Room.

    Implementations must not execute jobs or read raw provider credentials.
    """

    adapter_id: str
    """Stable adapter id, e.g. ``legacy_job_v1``."""

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
        """Return schedules, summary, and recent normalized runs."""
        ...

    async def get_schedule(
        self,
        schedule_id: str,
        *,
        run_history_limit: int = 20,
    ) -> dict[str, Any] | None:
        """Return one schedule + recent runs, or None if missing."""
        ...

    async def list_runs(
        self,
        *,
        limit: int = 50,
        schedule_id: str | None = None,
        status: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        """Return normalized run history (newest first)."""
        ...

    async def list_upcoming(
        self,
        *,
        days: int = 7,
        limit: int = 100,
        provider: str | None = None,
        health: str | None = None,
    ) -> dict[str, Any]:
        """Return projected fire calendar (does not dispatch)."""
        ...

    async def summary(self) -> dict[str, Any]:
        """Compact counts for /api/status and health widgets."""
        ...
