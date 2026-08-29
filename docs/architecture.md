# Agent Orchestrator — Architecture

**Jira:** [ORCH](https://berk-claude.atlassian.net/browse/ORCH) · **Repo:** https://github.com/berkkarabacak/agent-orchestrator  
**Foundation epic:** [ORCH-69](https://berk-claude.atlassian.net/browse/ORCH-69) · Master vision: [ORCH-58](https://berk-claude.atlassian.net/browse/ORCH-58)

## Product

1. **Today:** Scheduled multi-provider agent runner (OpenRouter default, optional xAI / Herdr) with durable job memory and operator UI.
2. **Target (AI Control Room):** Hosted SaaS where the CEO runs an autonomous AI company; deterministic **control plane** + **Prime Agent** workers + Postgres durability.

Formerly **Grok Automater** (xAI-only + SQLite).

## Control Room layering (target)

```
CEO UI (ORCH-72)
        │
        ▼
FastAPI control plane  ── auth, orgs, budgets, audit, artifacts, events (ORCH-69/70)
        │
        ├─► repositories (org-scoped) ──► PostgreSQL + pgvector (D-007)
        │
        └─► PrimeAgentClient (RPC JSONL) ──► sandboxed prime-agent worker (D-006)
                                              └─ OpenRouter models
```

Prime Agent is **not** a security boundary. The control plane approves/denies side effects.

## Current runtime layering (scheduler)

```
static/ (dashboard, history, settings)
        │  bridge: X-Api-Key
        ▼
app/api/routes.py          HTTP surface
        │
        ├─► JobRunner ──┬──────────► LlmProvider (runner=llm)
        │               │              ├─ OpenRouterLlmProvider (default)
        │               │              └─ XaiLlmProvider (legacy optional)
        │               ├─ look+keys goal ─► Jarvis desktop (same /run clock; ORCH-393)
        │               └──────────► HerdrClient CLI (runner=herdr)
        │
        ├─► JobStore / AuthStore ──► DatabaseProvider
        │                              ├─ sqlite (default)
        │                              ├─ postgres (ORCH-69; health + migrations first)
        │                              └─ tencentdb MySQL (legacy frozen)
        │
        └─► Memory helpers ────────► short memory + memory_log (per job)
                                     └─ shared/private agent memory
```

See also [docs/herdr.md](./herdr.md) and [docs/decisions.md](./decisions.md).

## Provider interfaces

| Interface | Responsibility | Default impl |
|-----------|----------------|--------------|
| `LlmProvider` | chat, list_models, status, test_connection | `OpenRouterLlmProvider` |
| `TokenProvider` | xAI OAuth/API-key tokens (legacy path) | oauth / api_key |
| Repositories | jobs, runs, memories | `JobStore` on SQLite |
| `DatabaseProvider` | portable persistence + health | sqlite → **postgres** (target) |

### Dependency rule

Domain/runner code must not import `httpx` URLs for a specific vendor except inside `app/llm/*` or `app/auth/*` adapters.

## Model resolution

1. Job `model_mode`: `inherit` | `auto` | `fixed`
2. If inherit → global `LLM_MODEL_MODE`
3. `auto` + OpenRouter → `openrouter/auto` (Auto Beta router)
4. `fixed` → job.model or `DEFAULT_MODEL`

Each run stores `llm_provider`, `model_requested`, `model_effective`.

## Config (env)

| Var | Meaning |
|-----|---------|
| `LLM_PROVIDER` | `openrouter` (default) or `xai` |
| `LLM_MODEL_MODE` | `auto` or `fixed` |
| `OPENROUTER_API_KEY` | OpenRouter secret |
| `DEFAULT_MODEL` | Fixed default / fallback |
| `API_SECRET` | Protects `/api/*` (legacy single secret; multi-tenant keys are ORCH-69 follow-on) |
| `DATABASE_PATH` | SQLite path |
| `DATABASE_PROVIDER` | `sqlite` \| `postgres` \| `tencentdb` |
| `POSTGRES_*` | Host/port/user/password/database/ssl_mode |
| `PUBLIC_BASE_URL` | Public URL for links/Slack |
| `HERDR_ENABLED` | Opt-in terminal agent runner (non-core for Control Room) |

Runtime PUT `/api/settings/llm` updates process memory until restart; durable config is `.env`.

## Two computers (do not mix)

| Machine | Ticket | Role |
|---------|--------|------|
| User Windows / Android app | ORCH-381 | The user's PC or phone |
| Jarvis Linux desktop container | ORCH-401 / ORCH-402 / ORCH-403 / ORCH-404 / ORCH-405 / ORCH-406 / ORCH-410 | Jarvis's own computer (`deploy/jarvis-computer/`), Windows-like XFCE + Chrome/notepad, localhost noVNC at http://127.0.0.1:6080, on-demand **Open Jarvis's screen** viewer, look/click/type via docker exec, live notepad proof script |

One Jarvis computer, not one per sub-agent. Home persists on volume `jarvis-computer-home`. See [jarvis-computer.md](./jarvis-computer.md).

## Deploy

- Process: uvicorn on `127.0.0.1:8895`
- Nginx: `/agent-orchestrator/` (legacy `/grok-automater/` redirects)
- systemd: `agent-orchestrator.service`

## Roadmap

| Epic | Focus |
|------|--------|
| **ORCH-69** | Foundation & platform (tenancy, Postgres, artifacts, events, audit) |
| ORCH-70 | Control plane guardrails & isolated workers |
| ORCH-71 | Executive AI, dynamic teams, memory |
| ORCH-72 | CEO experience |
| ORCH-73 | Work management & schedules |
| ORCH-74 | Quality engineering |
| ORCH-75 | CI/CD & GCP staging |
