# Herdr runner integration

Optional second job runner path: drive a [Herdr](https://herdr.dev/docs/) terminal coding agent from Agent Orchestrator schedules and the dashboard.

## When to use

| Runner | Use for |
|--------|---------|
| `llm` (default) | OpenRouter / xAI chat completions — fast, no local terminal |
| `herdr` | Full coding agents in a Herdr pane (`opencode`, `claude`, `codex`, …) |

Herdr is **opt-in**. Default jobs stay on the LLM path.

## Env

```bash
HERDR_ENABLED=true
HERDR_BIN=herdr
# Windows: HERDR_BIN=C:\Users\you\AppData\Local\herdr\herdr.exe
HERDR_SESSION=          # optional named session
HERDR_TIMEOUT_MS=120000
HERDR_DEFAULT_KIND=opencode
```

Requires a running Herdr server/session the CLI can reach (same machine or remote session config). See [install](https://herdr.dev/docs/install/) and [Windows beta](https://herdr.dev/docs/windows-beta/).

## Job fields

| Field | Meaning |
|-------|---------|
| `runner` | `"herdr"` |
| `herdr_agent_kind` | Agent kind (`opencode`, `claude`, `codex`, …) |
| `herdr_agent_name` | Live agent alias (`[a-z][a-z0-9_-]{0,31}`) — sanitized if needed |
| `herdr_cwd` | Workspace cwd (temp dir if empty) |
| `herdr_workspace_label` | Label for `workspace create` |
| `herdr_extra_args` | JSON list passed after `--` to `agent start` |
| `prompt_template` | Expanded (`{{date}}`, Jira placeholders, …) then sent via `agent prompt` |

## Execution flow

1. `herdr workspace create --cwd … --label … --no-focus` → `.result.root_pane.pane_id`
2. `herdr agent start <name> --kind <kind> --pane <id> [-- <extra>]`
3. `herdr agent prompt <name> <text> --wait --until idle --until done --until blocked --timeout <ms>`
4. `herdr agent read <name> --source recent-unwrapped --lines 200`
5. Persist result on the run; append short memory + message log when available

Implementation: `app/integrations/herdr.py`, `JobRunner._run_herdr_job` in `app/runner/runner.py`.

## API

| Method | Path | Notes |
|--------|------|--------|
| GET | `/api/status` | Includes `herdr: { enabled, available, bin, … }` |
| GET | `/api/settings/herdr` | Config + live CLI status |
| POST | `/api/settings/herdr/test` | `{ ok, available, … }` |
| POST | `/api/jobs` | Set `"runner": "herdr"` + herdr_* fields |
| POST | `/api/jobs/{id}/run` | Manual trigger |

## Smoke test

```bash
# server must be running with HERDR_ENABLED=true and herdr on PATH
python scripts/create_herdr_sample_job.py
# then POST /api/jobs/{id}/run with X-Api-Key
```

## Plugin skeleton

`deploy/herdr-plugin-agent-orchestrator/` — optional future Herdr plugin surface; not required for CLI runner jobs.

## Failure modes

| Symptom | Likely cause |
|---------|----------------|
| `HERDR_ENABLED is false` | Env not set / process not restarted |
| `herdr binary not found` | `HERDR_BIN` path wrong |
| `workspace create: missing pane id` | Herdr server not running / CLI version mismatch |
| `agent_prompt_stalled` | Agent never left idle (install/integration missing) |
| Empty result | Agent still working; increase `HERDR_TIMEOUT_MS` or ask agent to write a file |

## Docs upstream

- https://herdr.dev/docs/agent-automation/
- https://herdr.dev/docs/cli-reference/
