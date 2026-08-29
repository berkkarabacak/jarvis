# Scheduled work compatibility adapter (ORCH-73)

Control Room slice for **Company Work Management & Scheduled Work**.

## Purpose

Preserve existing Grok / OpenRouter / legacy `jobs` + Cloud Scheduler behavior while presenting a uniform scheduled-work view for the AI Control Room:

- `provider` — `openrouter` | `xai` | `herdr`
- `compatibility_mode` — currently always `compatibility` for legacy jobs
- `health` — `healthy` | `degraded` | `failing` | `paused` | `idle` | `unknown`
- `estimated_cost_cents` + `cost_confidence` — metered from tokens when present, else estimate
- `run_stats` — totals, success rate, consecutive failures
- `recent_runs` — normalized history (`status`, provider, cost, duration, summaries)
- schedule fields via existing `schedule_util.schedule_info`

**Read-only:** does not change job execution paths or credentials.

## API

### `GET /api/schedules`

Query filters (optional): `health`, `provider`, `due_state`, `enabled`, `paused`, `runner`,
`include_upcoming`, `upcoming_days`, `run_history_limit`.

Returns schedules, recent_runs, optional `upcoming` projected fires, and summary counts.

Each schedule includes `due_state` (`on_track|overdue|never_run|paused|unscheduled|unknown`) and `seconds_overdue`.

### `GET /api/schedules/upcoming?days=&limit=&provider=&health=`

Read-only projected fire calendar (does not dispatch).

### `GET /api/schedules/runs?limit=&job_id=&status=&provider=`

Normalized run history only.

### `GET /api/schedules/{id}`

Single schedule descriptor + recent normalized runs.

### Provider labeling

- `runner=herdr` → `herdr`
- Job model id `grok*` / `xai*` / `x-ai/*` → `xai` (legacy Grok preserved when default LLM is OpenRouter)
- Else process `LLM_PROVIDER`

### `GET /api/status`

Includes compact `schedules` summary counts (ORCH-73).

### Dashboard / History

- `GET /api/dashboard/overview` includes `schedules`, `schedule_runs`, `schedule_upcoming`, and per-job `scheduled_work`.
- UI panel **Control Room · scheduled work** is read-only (provider, health, due, cost, upcoming, history).
- History page enriches cards with provider/cost from normalized runs (read-only).

## Non-goals (this slice)

- Native control-plane dispatcher (still GCP Cloud Scheduler)
- Project/issue work graph
- Mutating runs, secrets, or provider credentials
- Changing job execution paths

## Control-plane port (read-only)

`ScheduledWorkPort` + `LegacyJobScheduledWorkPort` expose list/get/runs/upcoming/summary without execution or credentials.

