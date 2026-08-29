# Database schema

## Current default: SQLite (`DATABASE_PROVIDER=sqlite`)

Implemented in `app/db.py` via `SqliteDatabaseProvider`. Used for local dev and the live scheduler until Control Room repositories cut over.

| Table | Purpose |
|-------|---------|
| `auth_tokens` | Encrypted xAI OAuth tokens (legacy path) |
| `jobs` | Scheduled tasks + short memory + model_mode |
| `memory_versions` | Versioned short memory snapshots |
| `memory_log` | Append-only task log entries |
| `runs` | Execution history + LLM metadata |
| `oauth_pending` | PKCE pending states |
| `app_settings` | Key/value settings (future durable secrets) |
| `public_accounts`, `public_organizations`, `public_memberships` | Isolated zero-friction guest accounts |
| `public_account_sessions` | Opaque browser sessions (digest only) |
| `public_resource_bindings` | Leak-safe account ownership for executive resources |
| `public_usage_quotas` | Single-row atomic hourly / UTC-daily quota counters |

### `runs` LLM columns
- `llm_provider` — e.g. `openrouter`, `xai`
- `model_requested` — what we asked for (`openrouter/auto`, …)
- `model_effective` — what the provider reported

## Target: PostgreSQL + pgvector (`DATABASE_PROVIDER=postgres`) — ORCH-69 / D-007

Durable Control Room store. Migrations live in `app/migrations/` and are recorded in `schema_migrations`.

### Connection

| Env | Meaning |
|-----|---------|
| `DATABASE_PROVIDER` | `sqlite` \| `postgres` \| `tencentdb` (MySQL legacy) |
| `POSTGRES_HOST` | Hostname |
| `POSTGRES_PORT` | Default `5432` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | Credentials |
| `POSTGRES_DATABASE` | Database name |
| `POSTGRES_SSL_MODE` | `disable` \| `require` \| `verify-full` … |
| `POSTGRES_PGVECTOR_REQUIRED` | If `true`, treat missing `vector` extension as failure |

### Foundation migration `001_foundation_extensions.sql`

- `pgcrypto` extension
- `vector` (pgvector) extension when the host supports it
- `schema_migrations` created by the migrator on first apply

### Tenancy migration `002_tenancy_organizations.sql`

| Table | Purpose |
|-------|---------|
| `organizations` | Tenant boundary (`id`, `name`, `slug`, `plan`, `status`) |
| `users` | People (`email` unique ci, optional `external_subject`, `password_hash`) |
| `memberships` | `(user_id, org_id)` + role `owner\|admin\|member\|viewer` |

Bootstrap org: slug `default`, fixed id `00000000-0000-4000-8000-000000000001` (scheduler cutover anchor).

Python API: `app.tenancy.TenancyStore` (platform Postgres pool). Cross-org → `TenantNotFound` (404).

### Planned Control Room tables (subsequent ORCH-69 slices)

All tenant tables carry `org_id`. Exact DDL lands in numbered SQL migrations.

| Area | Tables (planned) |
|------|------------------|
| Auth | identity-provider links and registered-account recovery |
| Company / mission baseline | `missions`, `mission_tasks`, `agent_instances`, `evidence`, `mission_events` |
| Artifacts | `artifacts` (metadata + storage key) |
| Audit | `audit_events` |
| Semantic memory | embeddings via pgvector when available |

Illegal cross-org access must return **404** (not 403).

### Public access migration `005_public_access_accounts.sql`

| Table | Purpose |
|-------|---------|
| `account_sessions` | Hash-only opaque browser sessions tied to user + organization |
| `account_resource_bindings` | Account ownership checks for mission/session identifiers |
| `account_usage_windows` | Atomic hourly and UTC-daily usage/quota windows |

The SQLite compatibility tables above are the current production adapter. The
PostgreSQL tables are the durable target and reference migration 002's
`users`/`organizations` records.

## Legacy: TencentDB MySQL (`DATABASE_PROVIDER=tencentdb`) — frozen

MySQL-compatible provider remains for experimental/legacy scheduler dual-run only. **Do not** add AI Control Room mission/tenancy schema here (D-007). Historical design notes from ORCH-36 live in git history; Postgres is the forward path.

### Access rules (shared agent memory — existing SQLite/MySQL path)

- `shared` memories: readable by all agents in project unless ACL denies
- `private` memories: only `owner_agent_id` (or admin) may read/write
