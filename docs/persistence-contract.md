# Persistence contract (ORCH-69)

Stable interface for other AI Control Room epics. Import from `app.persistence`.

## Version

See `PERSISTENCE_CONTRACT.version` (`1.3.0` — adds the public account/session
boundary).

## Dialects

| Dialect | Role today |
|---------|------------|
| `sqlite` | Default **app data** (jobs, runs, memory stores) |
| `postgres` | **Platform** target, including TencentDB for PostgreSQL (tenancy, audit, artifacts, events, migrations) |
| `mysql` | Legacy frozen `DATABASE_PROVIDER=tencentdb` MySQL path; do not extend |

## Runtime handles (`app.state`)

| Attribute | Meaning |
|-----------|---------|
| `db_provider` | Platform provider (may be Postgres) |
| `data_provider` | App-data provider (SQLite until repository cutover) |
| `db` | Legacy `Database` / underlying used by JobStore |
| `persistence_contract` | Dict form of `PERSISTENCE_CONTRACT` |
| `platform_dialect` / `app_data_dialect` | `sqlite` \| `postgres` \| `mysql` |

## Configuration

| Env | Purpose |
|-----|---------|
| `DATABASE_PROVIDER` | `sqlite` \| `postgres` \| `tencentdb` |
| `DATABASE_STRICT` | Refuse incomplete postgres/mysql (no silent SQLite fallback) |
| `POSTGRES_*` | Host/port/user/password/database/ssl_mode |
| `POSTGRES_PGVECTOR_REQUIRED` | Fail migrations if vector extension missing |
| `POSTGRES_MIGRATE_ON_STARTUP` | Apply `app/migrations` when platform is Postgres |

Validate without connecting:

```python
from app.persistence import validate_database_settings, build_database

v = validate_database_settings(settings)
assert v.ok or not settings.database_strict
db = build_database(settings)  # platform handle
```

## Migrations

- SQL files: `app/migrations/NNN_name.sql`
- Runner: `apply_postgres_migrations(pool)`
- Bookkeeping: `schema_migrations(version, checksum, applied_at)`
- Safety: Postgres advisory lock, per-version transaction, checksum mismatch refuses edit-in-place, `-- optional: pgvector` statements skip on failure when allowed
- Idempotent: second apply skips applied versions

## HTTP

- `GET /api/settings/database` — config, validation, migration plan, health
- `GET /api/persistence/contract` — contract payload for other agents
- `POST /api/settings/database/test` — connectivity probe

## Tenancy (`app.tenancy`)

| Symbol | Role |
|--------|------|
| `TenancyStore` | organizations / users / memberships on platform Postgres |
| `TenantContext` | `user_id`, `org_id`, `role` + `require(capability)` |
| `TenantNotFound` | map to HTTP 404 (including cross-org) |
| `TenantAccessError` | map to HTTP 403 for insufficient role *inside* org |
| Roles | `owner`, `admin`, `member`, `viewer` |

Bootstrap org slug: `default`.

## Rules for new tables

1. Add DDL only via a new numbered SQL migration (never edit applied files).
2. Every Control Room row includes `org_id` FK → `organizations(id)`.
3. Cross-tenant reads return **404**, not 403.
4. Never log passwords or full DSNs (`dsn_safe` only).
5. Use `TenancyStore.tenant_context` / `require_membership` before org-scoped work.

## Public account/session boundary (`app.public_access`)

`AccountPrincipalV1` is the only identity shape consumed by user-facing CEO
and executive adapters. It contains safe account/organization identifiers,
display labels, role, capabilities, and expiry. It never includes a session
identifier, cookie/token value, token hash, email address, provider credential,
IP address, user-agent, or private runtime data.

The account and organization UUIDs returned by `AccountPrincipalV1.to_dict()`
are intentional tenant identifiers, not bearer credentials. They grant no
access without a valid opaque session cookie and server-side ownership check.

The current production app-data path uses `SqlitePublicAccessStore`; migration
`005_public_access_accounts.sql` publishes the additive PostgreSQL durability
contract for `account_sessions`, `account_resource_bindings`, and
`account_usage_windows`.

- Session tokens contain 256 random bits, stay only in a Secure + HttpOnly +
  SameSite=Lax `__Host-` cookie, and are persisted only as SHA-256 digests.
- Every guest receives a distinct account and organization.
- Resource binding mismatches are leak-safe 404s.
- Hourly and UTC-daily quota updates are atomic and deterministic.
- Cookie-authenticated mutations require a same-origin `Origin` plus the
  `X-AI-Control-Room-Request: browser-v1` custom header.
- Guest bootstrap quotas persist only an HMAC pseudonym. A directly connected
  loopback proxy must overwrite `X-Real-IP`; caller-controlled subject and
  `X-Forwarded-For` headers are ignored.
- The legacy `API_SECRET` router remains reserved for service/admin callers,
  including scheduled work. It is never sent to a browser.

## Executive-safe messages and memory (`app.persistence.safe_memory`)

Migration `004_executive_safe_memory.sql` adds two org-scoped Postgres tables:

For TencentDB, this contract uses a **TencentDB for PostgreSQL** instance through
the existing `DATABASE_PROVIDER=postgres` adapter; it does not extend the legacy
TencentDB-for-MySQL compatibility path.

| Table | Durable purpose |
|-------|-----------------|
| `executive_safe_messages` | Bounded `user` / `assistant` text explicitly safe for executive conversation history |
| `executive_memory_items` | Safe proposals that become consumable memory only after an owner/admin approval |

ORCH-71 should depend on `SafeMemoryRepository`, with
`PostgresSafeMemoryRepository` as the asyncpg-like adapter. The adapter requires
a `TenantContext`, includes `org_id` in every query, and maps cross-org access to
the existing leak-safe `TenantNotFound` contract.

Storage boundaries:

- only bounded user/assistant safe text is accepted;
- obvious private reasoning, prompt/transcript wrappers, command/tool output,
  browser/session artifacts, and private-key material are rejected;
- incidental credential/token values and filesystem paths are deterministically
  redacted before persistence;
- metadata is limited to `mission_id`, `handoff_id`, `evidence_refs`, normalized
  `confidence`, `source`, and `schema_version`;
- idempotency keys cannot silently overwrite a different payload;
- self-improvement is a proposal plus explicit approval. This repository has no
  code-mutation, command-execution, or deployment operation.

Only `list_approved_memory` is the normal memory-consumption path. Pending
proposals are available separately to an owner/admin for review.
