from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.memory.sanitize import sanitize_text, summarize_for_log

if TYPE_CHECKING:
    from app.config import Settings
    from app.store.jobs import JobStore, Run


def _fmt_ts(ts: float | None) -> str:
    if ts is None:
        return "?"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


async def build_memory_context(
    jobs: "JobStore",
    settings: "Settings",
    *,
    job_id: str,
    short_memory: str,
) -> str:
    """Task-scoped context: short memory + append-only log + prior run summaries.

    Jobs are isolated by job_id. Secrets are redacted. Survives restarts (DB).
    Past runs are the source of truth for the prior-work section.
    """
    short = sanitize_text(short_memory or "", max_chars=settings.memory_max_chars)
    log_keep = max(1, int(settings.memory_log_keep))
    prior_n = max(0, int(settings.memory_prior_runs))
    prior_chars = max(200, int(settings.memory_prior_run_chars))

    log_entries = await jobs.list_memory_log(job_id, limit=log_keep)
    prior_runs = await jobs.list_runs(job_id, limit=prior_n + 1)
    # Exclude an in-flight "running" row if present at top
    prior_runs = [r for r in prior_runs if r.status in ("succeeded", "failed")][:prior_n]

    parts: list[str] = []
    parts.append("## Working memory (short, durable)")
    parts.append(short.strip() or "(empty — initialize thoughtfully)")
    parts.append("")
    parts.append("## Append-only memory log (this job only, newest first)")
    if not log_entries:
        parts.append("(no log entries yet)")
    else:
        for e in log_entries:
            parts.append(f"### {e['created_label']} — {e['kind']}")
            parts.append(e["body"])
            parts.append("")
    parts.append("## Prior run results (source of truth, this job only)")
    if not prior_runs:
        parts.append("(no prior runs)")
    else:
        for r in prior_runs:
            parts.append(
                f"### Run {_fmt_ts(r.started_at)} · {r.status} · id={r.id[:8]}…"
            )
            if r.status == "failed":
                parts.append(sanitize_text(r.error or "failed", max_chars=prior_chars))
            else:
                parts.append(summarize_for_log(r.result, max_chars=prior_chars))
            parts.append("")
    parts.append(
        "Rules: Use only this job's memory. Do not invent other jobs' history. "
        "Never store API keys, tokens, passwords, or Authorization headers in memory. "
        "Update working memory with durable decisions/open threads; keep it concise."
    )
    text = "\n".join(parts)
    # Hard bound overall injection size
    max_total = max(4000, int(settings.memory_context_max_chars))
    return sanitize_text(text, max_chars=max_total)


def make_log_entry_from_run(run: "Run") -> tuple[str, str]:
    """Return (kind, body) for append-only log."""
    ts = _fmt_ts(run.finished_at or run.started_at)
    if run.status == "succeeded":
        body = summarize_for_log(run.result, max_chars=1200)
        return "run_success", f"{ts}\n{body}"
    body = sanitize_text(run.error or "failed", max_chars=600)
    return "run_failed", f"{ts}\n{body}"
