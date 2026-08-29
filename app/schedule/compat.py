from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from app.schedule_util import schedule_info
from app.store.jobs import Job, Run

# Rough USD-cents heuristics for CEO cost badges (not billing).
# OpenRouter/xAI actual cost is recorded later via control-plane ledger.
_TOKEN_CENTS_PER_1K = {
    "openrouter": 2,  # ~$0.02 / 1k tokens blended placeholder
    "xai": 3,
    "grok": 3,
    "herdr": 0,
}

_DEFAULT_PROMPT_TOKENS = 2500
_DEFAULT_COMPLETION_TOKENS = 1200

# Normalized Control Room run statuses (legacy → canonical)
_STATUS_MAP = {
    "succeeded": "succeeded",
    "success": "succeeded",
    "ok": "succeeded",
    "completed": "succeeded",
    "failed": "failed",
    "error": "failed",
    "failure": "failed",
    "running": "running",
    "in_progress": "running",
    "started": "running",
    "pending": "queued",
    "queued": "queued",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "skipped": "skipped",
    "blocked": "blocked",
}


def normalize_run_status(raw: str | None) -> str:
    """Map legacy run status strings to a stable Control Room vocabulary."""
    key = (raw or "").strip().lower()
    if not key:
        return "unknown"
    return _STATUS_MAP.get(key, "unknown")


def _normalize_provider(llm_provider: str | None, runner: str | None = None) -> str:
    r = (runner or "llm").strip().lower()
    if r == "herdr":
        return "herdr"
    p = (llm_provider or "openrouter").strip().lower()
    if p in ("grok", "xai"):
        return "xai"
    if p in ("openrouter", "or"):
        return "openrouter"
    return p or "openrouter"


def provider_for_job(
    job: Job,
    *,
    llm_provider: str | None = None,
) -> str:
    """Resolve display provider for a legacy job without changing execution.

    Prefers runner=herdr, then Grok/xAI model ids (preserves legacy Grok schedules
    even when the process default LLM is OpenRouter), else global llm_provider.
    """
    runner = (job.runner or "llm").strip().lower()
    if runner == "herdr":
        return "herdr"
    model = (job.model or "").strip().lower()
    if (
        model.startswith("grok")
        or model.startswith("xai")
        or model.startswith("x-ai/")
        or "/grok" in model
    ):
        return "xai"
    return _normalize_provider(llm_provider, runner)


def estimate_run_cost_cents(
    *,
    provider: str,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
) -> tuple[int | None, str]:
    """Return (cents, confidence). confidence: none|estimate|metered."""
    prov = _normalize_provider(provider, None)
    rate = _TOKEN_CENTS_PER_1K.get(prov)
    if rate is None:
        return None, "none"
    if prov == "herdr":
        return 0, "estimate"
    tin = tokens_in if tokens_in is not None else _DEFAULT_PROMPT_TOKENS
    tout = tokens_out if tokens_out is not None else _DEFAULT_COMPLETION_TOKENS
    cents = int(round((tin + tout) / 1000.0 * rate))
    confidence = "metered" if tokens_in is not None or tokens_out is not None else "estimate"
    return max(0, cents), confidence


@dataclass(frozen=True)
class ScheduledRunView:
    """Normalized scheduled-run history row (read-only; does not change execution)."""

    id: str
    schedule_id: str
    schedule_name: str
    status: str
    status_raw: str
    provider: str
    model: str | None
    started_at: float
    finished_at: float | None
    duration_ms: int | None
    tokens_in: int | None
    tokens_out: int | None
    cost_cents: int | None
    cost_confidence: str
    idempotency_key: str | None
    error_summary: str | None
    result_summary: str | None
    compatibility_mode: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "schedule_id": self.schedule_id,
            "schedule_name": self.schedule_name,
            "status": self.status,
            "status_raw": self.status_raw,
            "provider": self.provider,
            "model": self.model,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_cents": self.cost_cents,
            "cost_confidence": self.cost_confidence,
            "idempotency_key": self.idempotency_key,
            "error_summary": self.error_summary,
            "result_summary": self.result_summary,
            "compatibility_mode": self.compatibility_mode,
            "source": self.source,
        }


@dataclass(frozen=True)
class RunStats:
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    other: int = 0
    success_rate: float | None = None
    consecutive_failures: int = 0
    last_status: str | None = None
    avg_cost_cents: float | None = None
    last_cost_cents: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "other": self.other,
            "success_rate": self.success_rate,
            "consecutive_failures": self.consecutive_failures,
            "last_status": self.last_status,
            "avg_cost_cents": self.avg_cost_cents,
            "last_cost_cents": self.last_cost_cents,
        }


@dataclass(frozen=True)
class ScheduledWorkView:
    """Control-Room facing view of a legacy scheduled job (ORCH-73 adapter)."""

    id: str
    name: str
    source: str  # legacy_job
    compatibility_mode: str  # compatibility | native
    provider: str
    runner: str
    model: str
    model_mode: str
    enabled: bool
    paused: bool
    health: str  # healthy | degraded | failing | paused | idle | unknown
    due_state: str  # on_track | overdue | never_run | paused | unscheduled | unknown
    seconds_overdue: int | None
    cron: str | None
    timezone: str
    schedule_human: str
    next_run_at: str | None
    next_run_ts: float | None
    estimated_cost_cents: int | None
    cost_confidence: str  # none | estimate | metered
    last_run_status: str | None
    last_run_status_normalized: str | None
    last_run_id: str | None
    last_run_provider: str | None
    last_run_model: str | None
    last_run_started_at: float | None = None
    run_stats: dict[str, Any] = field(default_factory=dict)
    recent_runs: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "compatibility_mode": self.compatibility_mode,
            "provider": self.provider,
            "runner": self.runner,
            "model": self.model,
            "model_mode": self.model_mode,
            "enabled": self.enabled,
            "paused": self.paused,
            "health": self.health,
            "due_state": self.due_state,
            "seconds_overdue": self.seconds_overdue,
            "cron": self.cron,
            "timezone": self.timezone,
            "schedule_human": self.schedule_human,
            "next_run_at": self.next_run_at,
            "next_run_ts": self.next_run_ts,
            "estimated_cost_cents": self.estimated_cost_cents,
            "cost_confidence": self.cost_confidence,
            "last_run_status": self.last_run_status,
            "last_run_status_normalized": self.last_run_status_normalized,
            "last_run_id": self.last_run_id,
            "last_run_provider": self.last_run_provider,
            "last_run_model": self.last_run_model,
            "last_run_started_at": self.last_run_started_at,
            "run_stats": dict(self.run_stats or {}),
            "recent_runs": list(self.recent_runs or []),
            "notes": list(self.notes),
        }


def _summarize_text(text: str | None, *, limit: int = 240) -> str | None:
    if not text:
        return None
    cleaned = " ".join(str(text).split())
    if not cleaned:
        return None
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def normalize_run(
    run: Run,
    *,
    schedule_name: str = "",
    default_provider: str = "openrouter",
) -> ScheduledRunView:
    """Normalize a legacy Run into Control Room scheduled-run history."""
    status_raw = run.status or ""
    status = normalize_run_status(status_raw)
    provider = _normalize_provider(run.llm_provider or default_provider, None)
    has_tokens = run.tokens_in is not None or run.tokens_out is not None
    if has_tokens:
        cost_cents, cost_conf = estimate_run_cost_cents(
            provider=provider,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
        )
    elif status == "succeeded":
        cost_cents, cost_conf = estimate_run_cost_cents(provider=provider)
    else:
        cost_cents, cost_conf = None, "none"

    duration_ms = None
    if run.finished_at is not None and run.started_at is not None:
        try:
            duration_ms = max(0, int(round((float(run.finished_at) - float(run.started_at)) * 1000)))
        except (TypeError, ValueError):
            duration_ms = None

    model = run.model_effective or run.model_requested

    return ScheduledRunView(
        id=run.id,
        schedule_id=run.job_id,
        schedule_name=schedule_name or run.job_id[:8],
        status=status,
        status_raw=status_raw,
        provider=provider,
        model=model,
        started_at=float(run.started_at),
        finished_at=float(run.finished_at) if run.finished_at is not None else None,
        duration_ms=duration_ms,
        tokens_in=run.tokens_in,
        tokens_out=run.tokens_out,
        cost_cents=cost_cents,
        cost_confidence=cost_conf,
        idempotency_key=run.idempotency_key,
        error_summary=_summarize_text(run.error, limit=280),
        result_summary=_summarize_text(run.result, limit=280),
        compatibility_mode="compatibility",
        source="legacy_run",
    )


def approx_period_seconds(cron: str | None) -> int | None:
    """Best-effort period length for common 5-field crons (for overdue detection)."""
    raw = (cron or "").strip()
    parts = raw.split()
    if len(parts) != 5:
        return None
    minute, hour, dom, month, dow = parts
    if minute.startswith("*/") and hour == "*" and dom == "*" and month == "*" and dow == "*":
        try:
            n = int(minute.split("/", 1)[1])
            return max(60, n * 60)
        except ValueError:
            return None
    if hour.startswith("*/") and dom == "*" and month == "*" and dow == "*":
        try:
            n = int(hour.split("/", 1)[1])
            return max(3600, n * 3600)
        except ValueError:
            return None
    if hour == "*" and dom == "*" and month == "*" and dow == "*":
        return 3600  # hourly-ish
    if dom == "*" and month == "*" and dow == "*":
        return 86400  # daily
    if dom == "*" and month == "*" and dow in ("1-5", "MON-FRI", "mon-fri"):
        return 86400  # weekdays ~ daily
    if dom == "*" and month == "*" and dow not in ("*",):
        return 7 * 86400  # weekly
    return 86400


def evaluate_due_state(
    *,
    paused: bool,
    has_cron: bool,
    cron: str | None,
    last_run_started_at: float | None,
    now: float | None = None,
    grace_ratio: float = 1.5,
) -> tuple[str, int | None]:
    """Return (due_state, seconds_overdue).

    due_state: on_track | overdue | never_run | paused | unscheduled | unknown
    """
    ts = float(now if now is not None else time.time())
    if paused:
        return "paused", None
    if not has_cron:
        return "unscheduled", None
    if last_run_started_at is None:
        return "never_run", None
    period = approx_period_seconds(cron)
    if period is None:
        return "unknown", None
    age = ts - float(last_run_started_at)
    threshold = period * grace_ratio
    if age > threshold:
        return "overdue", int(age - period)
    return "on_track", None


def compute_run_stats(runs_newest_first: Iterable[ScheduledRunView]) -> RunStats:
    rows = list(runs_newest_first)
    if not rows:
        return RunStats()
    succeeded = sum(1 for r in rows if r.status == "succeeded")
    failed = sum(1 for r in rows if r.status == "failed")
    other = len(rows) - succeeded - failed
    rate = round(succeeded / len(rows), 4) if rows else None
    consec = 0
    for r in rows:
        if r.status == "failed":
            consec += 1
        else:
            break
    costs = [r.cost_cents for r in rows if r.cost_cents is not None]
    avg = round(sum(costs) / len(costs), 2) if costs else None
    last_cost = rows[0].cost_cents if rows else None
    return RunStats(
        total=len(rows),
        succeeded=succeeded,
        failed=failed,
        other=other,
        success_rate=rate,
        consecutive_failures=consec,
        last_status=rows[0].status if rows else None,
        avg_cost_cents=avg,
        last_cost_cents=last_cost,
    )


def derive_health(
    *,
    paused: bool,
    stats: RunStats,
    has_cron: bool,
    due_state: str | None = None,
) -> str:
    if paused:
        return "paused"
    if due_state == "overdue":
        # Overdue without recent success is at least degraded
        if stats.consecutive_failures >= 3 or stats.last_status == "failed":
            return "failing"
        return "degraded"
    if stats.total == 0:
        return "idle" if has_cron else "unknown"
    if stats.consecutive_failures >= 3:
        return "failing"
    if stats.consecutive_failures >= 1:
        return "degraded"
    if stats.last_status == "succeeded":
        return "healthy"
    if stats.last_status == "running":
        return "healthy"
    return "unknown"


def compatibility_for_job(
    job: Job,
    *,
    llm_provider: str,
    tz_name: str = "UTC",
    last_run: Run | None = None,
    recent_runs: list[Run] | None = None,
) -> ScheduledWorkView:
    """Adapt a legacy Job row into a Control Room scheduled-work descriptor."""
    provider = provider_for_job(job, llm_provider=llm_provider)
    runner = (job.runner or "llm").strip().lower() or "llm"
    sched = schedule_info(job.schedule, tz_name=tz_name or "UTC")
    paused = not bool(job.enabled)
    next_at = None if paused else sched.get("next_run_at")
    next_ts = None if paused else sched.get("next_run_ts")
    human = sched.get("human") or "Not scheduled"
    if paused:
        human = f"Paused · {human}" if job.schedule else "Paused"

    notes: list[str] = [
        "Served via legacy jobs/runs compatibility adapter (ORCH-73).",
        "Cron on the job is informational; unattended fire still requires "
        "Cloud Scheduler (or a future control-plane dispatcher).",
    ]
    if provider == "xai":
        notes.append(
            "xAI/Grok path is legacy-compatible; validate ToS and tier before multi-tenant SaaS use."
        )
    if runner == "herdr":
        notes.append(
            "Herdr runner is outside AI Control Room core scope; shown for visibility only."
        )

    run_list = list(recent_runs or [])
    if not run_list and last_run is not None:
        run_list = [last_run]

    normalized = [
        normalize_run(r, schedule_name=job.name, default_provider=provider) for r in run_list
    ]
    stats = compute_run_stats(normalized)
    has_cron = bool((job.schedule or "").strip())
    last_started = (
        normalized[0].started_at
        if normalized
        else (float(last_run.started_at) if last_run is not None else None)
    )
    due_state, seconds_overdue = evaluate_due_state(
        paused=paused,
        has_cron=has_cron,
        cron=sched.get("cron"),
        last_run_started_at=last_started,
    )
    health = derive_health(
        paused=paused, stats=stats, has_cron=has_cron, due_state=due_state
    )
    if due_state == "overdue":
        notes.append(
            "Schedule appears overdue relative to cron period and last run "
            "(informational — Cloud Scheduler may still be source of truth)."
        )

    # Cost badge: prefer last metered run, else estimate
    if normalized and normalized[0].cost_cents is not None:
        cost_cents = normalized[0].cost_cents
        cost_conf = normalized[0].cost_confidence
    else:
        cost_cents, cost_conf = estimate_run_cost_cents(provider=provider)

    lr = normalized[0] if normalized else None

    return ScheduledWorkView(
        id=job.id,
        name=job.name,
        source="legacy_job",
        compatibility_mode="compatibility",
        provider=provider,
        runner=runner,
        model=job.model or "",
        model_mode=(job.model_mode or "inherit"),
        enabled=bool(job.enabled),
        paused=paused,
        health=health,
        due_state=due_state,
        seconds_overdue=seconds_overdue,
        cron=sched.get("cron"),
        timezone=str(sched.get("timezone") or tz_name or "UTC"),
        schedule_human=str(human),
        next_run_at=next_at if isinstance(next_at, str) or next_at is None else str(next_at),
        next_run_ts=float(next_ts) if next_ts is not None else None,
        estimated_cost_cents=cost_cents,
        cost_confidence=cost_conf,
        last_run_status=lr.status_raw if lr else (last_run.status if last_run else None),
        last_run_status_normalized=lr.status if lr else (
            normalize_run_status(last_run.status) if last_run else None
        ),
        last_run_id=lr.id if lr else (last_run.id if last_run else None),
        last_run_provider=lr.provider if lr else (last_run.llm_provider if last_run else None),
        last_run_model=lr.model if lr else (
            (last_run.model_effective or last_run.model_requested) if last_run else None
        ),
        last_run_started_at=last_started,
        run_stats=stats.to_dict(),
        recent_runs=[r.to_dict() for r in normalized[:10]],
        notes=notes,
    )


def list_scheduled_work(
    jobs: Iterable[Job],
    *,
    llm_provider: str,
    tz_name: str = "UTC",
    last_runs: dict[str, Run] | None = None,
    runs_by_job: dict[str, list[Run]] | None = None,
) -> list[ScheduledWorkView]:
    """Build schedule views for jobs (legacy compatibility surface)."""
    last_runs = last_runs or {}
    runs_by_job = runs_by_job or {}
    out: list[ScheduledWorkView] = []
    for job in jobs:
        lr = last_runs.get(job.id)
        recent = runs_by_job.get(job.id) or ([lr] if lr else [])
        has_cron = bool((job.schedule or "").strip())
        if not has_cron and lr is None and not job.enabled:
            continue
        out.append(
            compatibility_for_job(
                job,
                llm_provider=llm_provider,
                tz_name=tz_name,
                last_run=lr,
                recent_runs=recent,
            )
        )

    def _key(v: ScheduledWorkView) -> tuple:
        return (v.next_run_ts is None, v.next_run_ts or 0.0, v.name.lower())

    return sorted(out, key=_key)


def list_normalized_runs(
    runs: Iterable[Run],
    *,
    job_names: dict[str, str] | None = None,
    default_provider: str = "openrouter",
) -> list[ScheduledRunView]:
    """Normalize a mixed list of legacy runs (newest-first preserved)."""
    names = job_names or {}
    return [
        normalize_run(
            r,
            schedule_name=names.get(r.job_id) or r.job_id[:8],
            default_provider=default_provider,
        )
        for r in runs
    ]


def _provider_match(value: str | None, wanted: str | None) -> bool:
    if not wanted:
        return True
    v = (value or "").strip().lower()
    w = wanted.strip().lower()
    if w in ("xai", "grok"):
        return v in ("xai", "grok")
    return v == w


def filter_schedule_views(
    views: Iterable[ScheduledWorkView],
    *,
    health: str | None = None,
    provider: str | None = None,
    due_state: str | None = None,
    enabled: bool | None = None,
    paused: bool | None = None,
    runner: str | None = None,
) -> list[ScheduledWorkView]:
    out: list[ScheduledWorkView] = []
    health_l = (health or "").strip().lower() or None
    due_l = (due_state or "").strip().lower() or None
    runner_l = (runner or "").strip().lower() or None
    for v in views:
        if health_l and v.health != health_l:
            continue
        if not _provider_match(v.provider, provider):
            continue
        if due_l and v.due_state != due_l:
            continue
        if enabled is not None and bool(v.enabled) != bool(enabled):
            continue
        if paused is not None and bool(v.paused) != bool(paused):
            continue
        if runner_l and (v.runner or "").lower() != runner_l:
            continue
        out.append(v)
    return out


def filter_run_views(
    runs: Iterable[ScheduledRunView],
    *,
    status: str | None = None,
    provider: str | None = None,
    schedule_id: str | None = None,
) -> list[ScheduledRunView]:
    status_l = (status or "").strip().lower() or None
    sid = (schedule_id or "").strip() or None
    out: list[ScheduledRunView] = []
    for r in runs:
        if status_l and r.status != status_l:
            continue
        if not _provider_match(r.provider, provider):
            continue
        if sid and r.schedule_id != sid:
            continue
        out.append(r)
    return out


def summarize_schedule_views(views: Iterable[ScheduledWorkView]) -> dict[str, Any]:
    rows = list(views)
    return {
        "schedule_count": len(rows),
        "active": sum(1 for v in rows if v.enabled and not v.paused),
        "paused": sum(1 for v in rows if v.paused),
        "failing": sum(1 for v in rows if v.health == "failing"),
        "degraded": sum(1 for v in rows if v.health == "degraded"),
        "healthy": sum(1 for v in rows if v.health == "healthy"),
        "overdue": sum(1 for v in rows if v.due_state == "overdue"),
        "never_run": sum(1 for v in rows if v.due_state == "never_run"),
        "providers": sorted({v.provider for v in rows}),
    }


def build_upcoming_fires(
    views: Iterable[ScheduledWorkView],
    *,
    days: float = 7.0,
    limit: int = 50,
    per_schedule: int = 8,
) -> list[dict[str, Any]]:
    """Expand cron schedules into an upcoming fire calendar (read-only).

    Skips paused schedules. Uses the same cron engine as next_run estimation.
    Does not dispatch work.
    """
    from app.schedule_util import next_cron_fires

    days = max(0.0, float(days))
    limit = max(0, min(int(limit), 200))
    per_schedule = max(1, min(int(per_schedule), 40))
    hours = days * 24.0
    events: list[dict[str, Any]] = []
    for v in views:
        if v.paused or not v.enabled:
            continue
        if not v.cron:
            continue
        fires = next_cron_fires(
            v.cron,
            tz_name=v.timezone or "UTC",
            limit=per_schedule,
            within_hours=hours if days > 0 else None,
        )
        for dt in fires:
            events.append(
                {
                    "schedule_id": v.id,
                    "schedule_name": v.name,
                    "provider": v.provider,
                    "runner": v.runner,
                    "model": v.model,
                    "health": v.health,
                    "due_state": v.due_state,
                    "cron": v.cron,
                    "timezone": v.timezone,
                    "fire_at": dt.isoformat(),
                    "fire_ts": dt.timestamp(),
                    "compatibility_mode": v.compatibility_mode,
                    "source": v.source,
                    "estimated_cost_cents": v.estimated_cost_cents,
                    "cost_confidence": v.cost_confidence,
                }
            )
    events.sort(key=lambda e: float(e.get("fire_ts") or 0.0))
    return events[:limit]
