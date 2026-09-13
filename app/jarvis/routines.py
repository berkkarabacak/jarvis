"""Read-only local schedules for the Windows Routines list (issue #72).

Uses the existing JobStore / cron helper. Does not invent sample routines
and does not create jobs — ``+`` stays an honest coming-soon.
"""

from __future__ import annotations

from typing import Any

from app.schedule_util import schedule_info

EMPTY_LABEL = "No routines yet."
ADD_SOON = "Adding a routine comes later."
SOURCE = "local-schedules"


def routine_from_job(job: Any, *, tz_name: str = "UTC") -> dict[str, Any] | None:
    """Mom-friendly row for one real local schedule. Skip nameless jobs."""
    name = str(getattr(job, "name", "") or "").strip()
    job_id = str(getattr(job, "id", "") or "").strip()
    if not name or not job_id:
        return None
    enabled = bool(getattr(job, "enabled", False))
    info = schedule_info(getattr(job, "schedule", None), tz_name=tz_name or "UTC")
    when = str(info.get("human") or "Not scheduled")
    if not enabled:
        when = f"Off · {when}" if getattr(job, "schedule", None) else "Off"
    return {
        "id": job_id,
        "name": name,
        "when": when,
        "enabled": enabled,
        "source": SOURCE,
        "live": True,
        "read_only": True,
    }


def routines_from_jobs(jobs: list[Any] | None, *, tz_name: str = "UTC") -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for job in jobs or []:
        row = routine_from_job(job, tz_name=tz_name)
        if row:
            items.append(row)
    return items


async def routines_payload(job_store: Any, *, tz_name: str = "UTC") -> dict[str, Any]:
    rows: list[Any] = []
    if job_store is not None and hasattr(job_store, "list_jobs"):
        try:
            rows = await job_store.list_jobs()
        except Exception:
            rows = []
    items = routines_from_jobs(rows, tz_name=tz_name)
    return {
        "routines": items,
        "empty": len(items) == 0,
        "can_create": False,
        "add_soon": ADD_SOON,
        "empty_label": EMPTY_LABEL,
        "source": SOURCE,
        "note": "Real local schedules only. This list does not invent routines.",
    }
