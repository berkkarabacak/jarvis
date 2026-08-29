# Grok Automater — JIRA Tickets

**Live project created on Jira Cloud**

| Field | Value |
|--------|--------|
| **Name** | Grok Automater |
| **Key** | `GAUT` |
| **Type** | Company-managed Software (Scrum) |
| **Site** | https://berk-claude.atlassian.net |
| **Board / browse** | https://berk-claude.atlassian.net/browse/GAUT |
| **Epic** | [GAUT-1](https://berk-claude.atlassian.net/browse/GAUT-1) |

Target: GCP VM (alongside existing web apps) · Auth: SuperGrok OAuth (no XAI_API_KEY)

### Created issues

| Key | Type | Summary |
|-----|------|---------|
| [GAUT-1](https://berk-claude.atlassian.net/browse/GAUT-1) | Epic | Subscription-Authenticated Grok Task Runner |
| [GAUT-2](https://berk-claude.atlassian.net/browse/GAUT-2) | Story | Capture real xAI OAuth constants from known sources |
| [GAUT-3](https://berk-claude.atlassian.net/browse/GAUT-3) | Story | Project scaffold and app skeleton |
| [GAUT-4](https://berk-claude.atlassian.net/browse/GAUT-4) | Story | TokenProvider interface (OAuth + API-key swap) |
| [GAUT-5](https://berk-claude.atlassian.net/browse/GAUT-5) | Story | Local PKCE one-time login (loopback) |
| [GAUT-6](https://berk-claude.atlassian.net/browse/GAUT-6) | Story | Import tokens into server store |
| [GAUT-7](https://berk-claude.atlassian.net/browse/GAUT-7) | Story | Silent refresh loop with lock and rotation |
| [GAUT-8](https://berk-claude.atlassian.net/browse/GAUT-8) | Story | Persist auth tokens encrypted at rest |
| [GAUT-9](https://berk-claude.atlassian.net/browse/GAUT-9) | Story | Auth status + needs_reauth surface (GET /api/status) |
| [GAUT-10](https://berk-claude.atlassian.net/browse/GAUT-10) | Story | Database schema: jobs, memory versions, runs |
| [GAUT-11](https://berk-claude.atlassian.net/browse/GAUT-11) | Story | Jobs API CRUD |
| [GAUT-12](https://berk-claude.atlassian.net/browse/GAUT-12) | Story | Memory read/write with parse-safe update |
| [GAUT-13](https://berk-claude.atlassian.net/browse/GAUT-13) | Story | Versioned memory (last N) |
| [GAUT-14](https://berk-claude.atlassian.net/browse/GAUT-14) | Story | Grok chat client (Bearer to api.x.ai only) |
| [GAUT-15](https://berk-claude.atlassian.net/browse/GAUT-15) | Story | Job runner: prompt compose + JSON memory round-trip |
| [GAUT-16](https://berk-claude.atlassian.net/browse/GAUT-16) | Story | Run history API |
| [GAUT-17](https://berk-claude.atlassian.net/browse/GAUT-17) | Story | Idempotent runs for Scheduler retries |
| [GAUT-18](https://berk-claude.atlassian.net/browse/GAUT-18) | Story | Protect /api/* with shared secret header |
| [GAUT-19](https://berk-claude.atlassian.net/browse/GAUT-19) | Story | systemd service on existing GCP VM |
| [GAUT-20](https://berk-claude.atlassian.net/browse/GAUT-20) | Story | Cloud Scheduler daily job |
| [GAUT-21](https://berk-claude.atlassian.net/browse/GAUT-21) | Story | Memory size cap + compaction |
| [GAUT-22](https://berk-claude.atlassian.net/browse/GAUT-22) | Story | Operator runbook (login, import, reauth, failover) |
| [GAUT-23](https://berk-claude.atlassian.net/browse/GAUT-23) | Story | End-to-end verification checklist |
| [GAUT-24](https://berk-claude.atlassian.net/browse/GAUT-24) | Story | [Optional] Email or webhook alert on needs_reauth |
| [GAUT-25](https://berk-claude.atlassian.net/browse/GAUT-25) | Story | [Optional] Device-code OAuth alternative for headless bootstrap |
| [GAUT-26](https://berk-claude.atlassian.net/browse/GAUT-26) | Story | [Optional] Postgres store backend |

---

## Original ticket specs (detail)

---

## EPIC

### GROK-1 — Subscription-Authenticated Grok Task Runner

| Field | Value |
|--------|--------|
| **Type** | Epic |
| **Summary** | Always-on Grok task runner with subscription OAuth, durable memory, and unattended daily runs |
| **Description** | Build a small server-side web service that runs Grok on recurring jobs using the owner's SuperGrok/X Premium+ subscription via OAuth PKCE (not a metered API key). Memory and tokens live in a database. One-time human login only; thereafter silent refresh + Cloud Scheduler. Borrow OAuth client values from opencode-grok-auth / Hermes; do not invent endpoints. |
| **Acceptance criteria** | • Owner logs in once; server refreshes tokens unattended<br>• Jobs run on schedule with memory surviving restarts<br>• Auth failure sets `needs_reauth` and stops silent retry loops<br>• Token provider is swappable to API key without rewrite<br>• No OpenCode runtime dependency |
| **Labels** | `grok-runner`, `oauth`, `gcp` |
| **Priority** | Highest |

---

## PHASE 0 — Discovery & foundations

### GROK-2 — Capture real xAI OAuth constants from known sources

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Add config module with discovered OAuth/API values and source comments |
| **Description** | Do not guess client ID, URLs, scopes, or models. Record values from: (1) https://github.com/ysnock404/opencode-grok-auth (2) https://auth.x.ai/.well-known/openid-configuration (3) Hermes xAI OAuth guide. Each constant must cite its source in a comment. |
| **Known values (implement these)** | See technical notes below |
| **Acceptance criteria** | • `client_id`, authorize, token, discovery, scope, redirect, models, API base all present<br>• Source comment on every value<br>• No invented endpoint strings<br>• Endpoint host pin: HTTPS + `x.ai` / `*.x.ai` only |
| **Technical notes** | **client_id:** `b1a00492-073a-47ea-816f-4c329264a828`<br>**discovery:** `https://auth.x.ai/.well-known/openid-configuration`<br>**authorize:** `https://auth.x.ai/oauth2/authorize`<br>**token:** `https://auth.x.ai/oauth2/token`<br>**scope:** `openid profile email offline_access grok-cli:access api:access`<br>**redirect:** `http://127.0.0.1:56121/callback`<br>**API base:** `https://api.x.ai/v1`<br>**models:** `grok-4.3`, `grok-4.20-0309-reasoning`, `grok-4.20-0309-non-reasoning`, `grok-4.20-multi-agent-0309`<br>**Auth extras:** `plan=generic`, `referrer=hermes-agent`, `nonce`, `state`<br>**Exchange quirk:** body must include `code_verifier` AND `code_challenge` + `code_challenge_method=S256` |
| **Labels** | `grok-runner`, `auth`, `discovery` |
| **Priority** | Highest |
| **Estimate** | S |

### GROK-3 — Project scaffold and app skeleton

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Scaffold service (runtime, layout, config, health) |
| **Description** | Create greenfield project structure for the Grok runner. Prefer Python 3.11+ FastAPI unless VM stack is already Node. Include env-based config (`API_SECRET`, DB path, encryption key, timezone), logging, and a minimal process entrypoint suitable for systemd later. |
| **Acceptance criteria** | • App starts and serves a basic health/ping route<br>• Config loaded from env / `.env.example` documented<br>• `.gitignore` excludes secrets, DB, tokens<br>• README stub with run instructions |
| **Depends on** | GROK-2 (can parallelize lightly) |
| **Labels** | `grok-runner`, `scaffold` |
| **Priority** | High |
| **Estimate** | S |

### GROK-4 — TokenProvider interface (OAuth + API-key swap)

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Define swappable TokenProvider interface |
| **Description** | Auth must be swappable: OAuth subscription is default; `XAI_API_KEY` is the sanctioned fallback if OAuth client breaks or returns tier 403. One interface, two implementations; runner depends only on the interface. |
| **Acceptance criteria** | • `get_access_token() -> str`<br>• `status() -> { healthy, needs_reauth, expires_at, provider_type }`<br>• `OAuthTokenProvider` stub + `ApiKeyTokenProvider` stub<br>• Selecting provider is config/one-file change |
| **Depends on** | GROK-3 |
| **Labels** | `grok-runner`, `auth` |
| **Priority** | High |
| **Estimate** | S |

---

## PHASE 1 — Auth (ship before jobs)

### GROK-5 — Local PKCE one-time login (loopback)

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Implement local PKCE login matching Hermes/opencode-grok-auth flow |
| **Description** | Borrowed OAuth client only allows `http://127.0.0.1:56121/callback`. Implement laptop/local CLI (or local server mode): generate PKCE, open authorize URL, receive code on loopback, exchange for tokens. This is the only human step in the system lifetime. Do not require a public domain callback for first login. |
| **Acceptance criteria** | • PKCE S256 (verifier 43–128 chars / 48 random bytes base64url)<br>• Authorize URL includes client_id, redirect_uri, scope, code_challenge, S256, state, nonce, plan=generic, referrer=hermes-agent<br>• Callback verifies state<br>• Token exchange sends code_verifier + code_challenge + method (Hermes quirk)<br>• Persists access_token, refresh_token, expires_at, token_endpoint, redirect_uri used<br>• Documents SSH port-forward if login run remotely |
| **Depends on** | GROK-2, GROK-3 |
| **Labels** | `grok-runner`, `auth`, `pkce` |
| **Priority** | Highest |
| **Estimate** | M |

### GROK-6 — Import tokens into server store

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Add secure token import path for server bootstrap |
| **Description** | After local login, owner transfers tokens to the GCP service. Provide `POST /oauth/import` (API secret) and/or CLI that writes the singleton auth row. Primary production bootstrap path. |
| **Acceptance criteria** | • Import accepts access, refresh, expires_at, and metadata<br>• Protected by shared API secret<br>• Overwrites prior tokens cleanly<br>• Sets `needs_reauth=false` on success<br>• No tokens logged |
| **Depends on** | GROK-5, GROK-8 |
| **Labels** | `grok-runner`, `auth` |
| **Priority** | Highest |
| **Estimate** | S |

### GROK-7 — Silent refresh loop with lock and rotation

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Implement get_token() refresh-early, lock, persist-before-use, rotation |
| **Description** | Most OAuth bugs live here. Refresh when `expires_at - now < 5 minutes` (not at exact expiry). Take DB lock so concurrent runs cannot double-refresh. Persist new tokens (including rotated refresh_token) before returning access token. On terminal failure mark auth dead. |
| **Acceptance criteria** | • 5-minute safety margin<br>• Row/advisory lock around refresh<br>• Persist before return<br>• Store new refresh_token if present; never discard silently<br>• `invalid_grant` / terminal 4xx → `needs_reauth=true`, stop thrashing<br>• Forced near-expiry test proves refresh works<br>• Crash mid-refresh does not orphan usable refresh token |
| **Depends on** | GROK-4, GROK-6, GROK-8 |
| **Labels** | `grok-runner`, `auth`, `critical` |
| **Priority** | Highest |
| **Estimate** | M |

### GROK-8 — Persist auth tokens encrypted at rest

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Store OAuth tokens encrypted in DB (not plaintext file/repo) |
| **Description** | Singleton auth record in store. Encrypt access/refresh (and related secrets) with key from env or GCP Secret Manager. Never commit tokens. |
| **Acceptance criteria** | • DB table/row for auth tokens<br>• Encryption at rest for token fields<br>• Key from env/Secret Manager only<br>• Load/save helpers used by import + refresh |
| **Depends on** | GROK-3 |
| **Labels** | `grok-runner`, `security`, `store` |
| **Priority** | Highest |
| **Estimate** | S |

### GROK-9 — Auth status + needs_reauth alerting surface

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Expose GET /api/status for auth health and reauth flag |
| **Description** | Single place owner/monitoring checks. Must never fail silently when subscription auth dies. |
| **Acceptance criteria** | • `GET /api/status` returns: auth healthy, needs_reauth, expires_at (no raw tokens), provider type, last successful refresh/run summary if available<br>• Protected by API secret<br>• When needs_reauth, response is explicit<br>• Optional: webhook/email hook stub documented as follow-up |
| **Depends on** | GROK-7 |
| **Labels** | `grok-runner`, `auth`, `ops` |
| **Priority** | High |
| **Estimate** | S |

---

## PHASE 2 — Store, jobs, memory

### GROK-10 — Database schema: jobs, memory versions, runs

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Implement durable store schema for jobs, memory, run history |
| **Description** | SQLite+WAL acceptable for single-user; design so Postgres swap is possible later. Memory is a document owned by the job, not process RAM. |
| **Acceptance criteria** | • Tables: `auth_tokens`, `jobs`, `memory_versions`, `runs`<br>• Job fields: id, name, prompt_template, schedule (info), model, memory_doc, memory_version, enabled, timestamps<br>• Runs: status, timestamps, input snapshot, result, raw/error, token usage, idempotency_key<br>• Migrations or schema init on startup<br>• Process restart leaves all data intact |
| **Depends on** | GROK-3 |
| **Labels** | `grok-runner`, `store` |
| **Priority** | Highest |
| **Estimate** | M |

### GROK-11 — Jobs API CRUD

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Implement jobs list/create/detail API |
| **Description** | | 
| **API** | `GET /api/jobs` · `POST /api/jobs` · `GET /api/jobs/{id}` (include current memory) |
| **Acceptance criteria** | • Create job with name, prompt_template, model, optional initial memory<br>• List and detail work<br>• Detail returns current memory_doc + version<br>• All routes require API secret<br>• Validation on required fields / allowed models |
| **Depends on** | GROK-10 |
| **Labels** | `grok-runner`, `api` |
| **Priority** | High |
| **Estimate** | S |

### GROK-12 — Memory read/write with parse-safe update

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Memory load/save helpers that never wipe on failed parse |
| **Description** | Runner will ask model for JSON `{"result":..., "memory":...}`. Only overwrite memory_doc when parse succeeds. |
| **Acceptance criteria** | • Load memory for job<br>• Save memory only on explicit success path<br>• Failed parse leaves previous memory unchanged<br>• Unit/integration test covers both paths |
| **Depends on** | GROK-10 |
| **Labels** | `grok-runner`, `memory` |
| **Priority** | Highest |
| **Estimate** | S |

### GROK-13 — Versioned memory (last N)

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Keep last N memory versions per job for recovery |
| **Description** | On each successful memory write, insert version row; prune older than N (default 20). |
| **Acceptance criteria** | • Version bumped on successful write<br>• Last N retained<br>• Can read prior version for manual recovery (API or DB)<br>• Does not run until basic memory R/W works (after GROK-12) |
| **Depends on** | GROK-12 |
| **Labels** | `grok-runner`, `memory` |
| **Priority** | Medium |
| **Estimate** | S |
| **Phase** | 7 / hardening (can slip after runner) |

---

## PHASE 3 — Task runner

### GROK-14 — Grok chat client (Bearer → api.x.ai only)

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | HTTP client for POST /v1/chat/completions with OAuth bearer |
| **Description** | Call `https://api.x.ai/v1/chat/completions` using TokenProvider. Refuse to send bearer to any other host. Configurable timeout for long generations. |
| **Acceptance criteria** | • Uses get_access_token() from provider<br>• Host pin to api.x.ai<br>• Timeout configurable (default ≥ 10 min)<br>• Surfaces 401 to auth layer / reauth path<br>• Returns content + usage |
| **Depends on** | GROK-7 |
| **Labels** | `grok-runner`, `grok-api` |
| **Priority** | Highest |
| **Estimate** | S |

### GROK-15 — Job runner: prompt compose + JSON memory round-trip

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Execute single job: memory in → Grok → result + memory out |
| **Description** | Stateless worker. Load job + memory; compose system + memory + today's instruction; require JSON-only response; strip code fences defensively; write run log; update memory only if parse OK. |
| **Acceptance criteria** | • System prompt instructs: JSON only, shape `{"result":..., "memory":...}`, no prose/fences<br>• Defensive fence strip before parse<br>• Success: run row + memory update<br>• Parse fail: run failed, memory unchanged<br>• If needs_reauth: do not call Grok; fail clearly<br>• Manual `POST /api/jobs/{id}/run` works end-to-end |
| **Depends on** | GROK-11, GROK-12, GROK-14 |
| **Labels** | `grok-runner`, `runner`, `critical` |
| **Priority** | Highest |
| **Estimate** | M |

### GROK-16 — Run history API

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | GET /api/jobs/{id}/runs history |
| **Description** | Paginated or limited list of past runs for debugging and audit. |
| **Acceptance criteria** | • Returns timestamp, status, result summary, errors, token usage<br>• API secret required<br>• Newest first |
| **Depends on** | GROK-15 |
| **Labels** | `grok-runner`, `api` |
| **Priority** | Medium |
| **Estimate** | S |

### GROK-17 — Idempotent runs for Scheduler retries

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Make POST /run idempotent via Idempotency-Key |
| **Description** | Cloud Scheduler retries. Duplicate delivery must not double-apply memory. |
| **Acceptance criteria** | • Accept `Idempotency-Key` header (e.g. `jobId-YYYY-MM-DD`)<br>• Same key within window returns prior run result<br>• Does not overwrite memory twice for same key<br>• Document recommended key format for Scheduler |
| **Depends on** | GROK-15 |
| **Labels** | `grok-runner`, `runner`, `scheduler` |
| **Priority** | High |
| **Estimate** | S |

---

## PHASE 4 — API security & ops surface

### GROK-18 — Protect /api/* with shared secret header

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Middleware: reject API requests without shared secret |
| **Description** | Endpoints execute billable subscription work. Cloud Scheduler supports custom headers. |
| **Acceptance criteria** | • Configurable header (e.g. `X-Api-Key` or `Authorization: Bearer`)<br>• Missing/wrong secret → 401<br>• `/api/*` and token import covered<br>• Secret from env/Secret Manager only |
| **Depends on** | GROK-3 |
| **Labels** | `grok-runner`, `security` |
| **Priority** | Highest |
| **Estimate** | S |

---

## PHASE 5 — Deploy & schedule

### GROK-19 — systemd service on existing GCP VM

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Package and run as systemd service behind existing reverse proxy |
| **Description** | Simplest deploy given other apps already on the VM. Unit file, env file path, restart policy, working directory, user. |
| **Acceptance criteria** | • systemd unit starts on boot<br>• Logs via journald<br>• Reverse proxy path to app (domain TBD)<br>• Deploy notes in README |
| **Depends on** | GROK-15, GROK-18 |
| **Labels** | `grok-runner`, `deploy`, `gcp` |
| **Priority** | High |
| **Estimate** | M |

### GROK-20 — Cloud Scheduler daily job

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Wire Cloud Scheduler → POST /api/jobs/{id}/run |
| **Description** | Prefer Cloud Scheduler over crontab: survives VM issues, retries built-in. Owner timezone. |
| **Acceptance criteria** | • Scheduler job defined (cron + TZ)<br>• HTTPS POST with auth header + optional Idempotency-Key<br>• Document gcloud commands / console steps<br>• One successful scheduled (or test) invocation recorded in runs |
| **Depends on** | GROK-17, GROK-19 |
| **Labels** | `grok-runner`, `scheduler`, `gcp` |
| **Priority** | High |
| **Estimate** | S |

---

## PHASE 6 — Memory hardening

### GROK-21 — Memory size cap + compaction

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Cap memory growth; compact via model when over threshold |
| **Description** | Unbounded memory will break context limits. When over threshold, ask model to compact: keep decisions and open threads; drop resolved detail. Only replace memory if compaction parse succeeds. |
| **Acceptance criteria** | • Configurable max size (chars/tokens)<br>• Compaction prompt + JSON safety same as runner<br>• Failed compaction keeps old memory<br>• Logged as special run or event |
| **Depends on** | GROK-15, GROK-13 |
| **Labels** | `grok-runner`, `memory` |
| **Priority** | Medium |
| **Estimate** | M |

---

## PHASE 7 — Docs, risks, verification

### GROK-22 — Operator runbook (login, import, reauth, failover)

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Write operator runbook for bootstrap and failure modes |
| **Description** | Document local login → import → status check → create job → manual run → Scheduler. Document needs_reauth recovery. Document API-key failover. Note OAuth client grey-area / client-break risk. |
| **Acceptance criteria** | • Step-by-step bootstrap<br>• Reauth procedure<br>• Failover to XAI_API_KEY<br>• Risk section (borrowed client, possible 403 tier gate)<br>• No secrets in docs |
| **Depends on** | GROK-20 |
| **Labels** | `grok-runner`, `docs` |
| **Priority** | Medium |
| **Estimate** | S |

### GROK-23 — End-to-end verification checklist

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | E2E test checklist and automated tests for critical paths |
| **Description** | Cover auth refresh, memory safety, idempotency, API auth. |
| **Acceptance criteria** | • Tests or scripted checklist for: login/import, forced refresh, run success, bad JSON memory safety, 401 without secret, needs_reauth blocks run, idempotent double run<br>• Critical paths automated where feasible without live xAI (mock HTTP) |
| **Depends on** | GROK-15, GROK-17, GROK-7 |
| **Labels** | `grok-runner`, `qa` |
| **Priority** | High |
| **Estimate** | M |

---

## Optional / later

### GROK-24 — Email or webhook alert on needs_reauth

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Notify owner when OAuth dies and human reauth required |
| **Description** | Status flag is minimum; push notification is better for unattended systems. |
| **Acceptance criteria** | • On transition to needs_reauth, send one alert (email/webhook)<br>• No alert spam loop<br>• Configurable endpoint/recipient |
| **Depends on** | GROK-9 |
| **Labels** | `grok-runner`, `ops` |
| **Priority** | Low |
| **Estimate** | S |

### GROK-25 — Device-code OAuth alternative for headless bootstrap

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Optional device-code login using auth.x.ai device endpoint |
| **Description** | OIDC discovery exposes `device_authorization_endpoint`. Hermes uses device code for remote hosts. Optional alternative if loopback PKCE bootstrap is painful. Not required for v1 if local PKCE + import works. |
| **Acceptance criteria** | • Device-code flow works against discovered endpoint with same client_id/scopes (if xAI allows this client)<br>• Tokens land in same store shape<br>• Documented as alternate bootstrap |
| **Depends on** | GROK-7 |
| **Labels** | `grok-runner`, `auth`, `optional` |
| **Priority** | Low |
| **Estimate** | M |

### GROK-26 — Postgres store backend

| Field | Value |
|--------|--------|
| **Type** | Story |
| **Epic** | GROK-1 |
| **Summary** | Optional Postgres backend if SQLite becomes insufficient |
| **Description** | Same schema; connection string config. Only if multi-process or backup needs demand it. |
| **Acceptance criteria** | • Feature-flag or URL-based backend select<br>• Migrations work on Postgres<br>• Lock semantics equivalent for refresh |
| **Depends on** | GROK-10 |
| **Labels** | `grok-runner`, `store`, `optional` |
| **Priority** | Low |
| **Estimate** | M |

---

## Suggested JIRA structure

| JIRA issue | Summary |
|------------|---------|
| **Epic GROK-1** | Subscription-Authenticated Grok Task Runner |
| GROK-2 | Capture real xAI OAuth constants |
| GROK-3 | Project scaffold |
| GROK-4 | TokenProvider interface |
| GROK-5 | Local PKCE login |
| GROK-6 | Import tokens to server |
| GROK-7 | Silent refresh loop |
| GROK-8 | Encrypt tokens at rest |
| GROK-9 | /api/status + needs_reauth |
| GROK-10 | DB schema jobs/memory/runs |
| GROK-11 | Jobs API CRUD |
| GROK-12 | Safe memory R/W |
| GROK-13 | Versioned memory (last N) |
| GROK-14 | Grok chat client |
| GROK-15 | Job runner + JSON round-trip |
| GROK-16 | Run history API |
| GROK-17 | Idempotent runs |
| GROK-18 | API shared secret |
| GROK-19 | systemd on GCP VM |
| GROK-20 | Cloud Scheduler daily |
| GROK-21 | Memory compaction |
| GROK-22 | Operator runbook |
| GROK-23 | E2E verification |
| GROK-24 | Reauth webhook/email (optional) |
| GROK-25 | Device-code OAuth (optional) |
| GROK-26 | Postgres backend (optional) |

---

## Recommended sprint / build order

**Sprint A — Auth solid (must ship first)**  
GROK-2, GROK-3, GROK-4, GROK-8, GROK-18, GROK-5, GROK-6, GROK-7, GROK-9  

**Sprint B — Runner + memory**  
GROK-10, GROK-11, GROK-12, GROK-14, GROK-15, GROK-16, GROK-17, GROK-23 (partial)  

**Sprint C — Deploy + harden**  
GROK-19, GROK-20, GROK-13, GROK-21, GROK-22, GROK-23 (complete)  

**Backlog**  
GROK-24, GROK-25, GROK-26  

---

## Dependency graph (text)

```
GROK-2 ──┐
GROK-3 ──┼── GROK-4 ──┐
         ├── GROK-8 ──┼── GROK-5 ── GROK-6 ── GROK-7 ── GROK-9
         ├── GROK-18 ─┘                │         │
         │                             │         ├── GROK-14 ── GROK-15 ── GROK-16
         └── GROK-10 ── GROK-11 ───────┴─────────┤           ├── GROK-17
                      └── GROK-12 ───────────────┘           │
                                                             ├── GROK-19 ── GROK-20
                                                             ├── GROK-13 ── GROK-21
                                                             └── GROK-23
GROK-22 after GROK-20
Optional: GROK-24 ← GROK-9; GROK-25 ← GROK-7; GROK-26 ← GROK-10
```

---

## Definition of Done (all stories)

- [ ] AC met and demoable  
- [ ] No secrets in repo  
- [ ] Source comments on any OAuth constant  
- [ ] Failures that need humans set `needs_reauth` or explicit error (no silent auth death)  
- [ ] Memory never wiped on malformed model output  

---

## Open questions (block deploy tickets until answered)

1. Runtime on VM: Python vs Node?  
2. Public base URL / reverse-proxy path?  
3. Owner timezone for Cloud Scheduler?  
4. First job name + prompt_template?  
5. Default model (`grok-4.3` recommended)?  
6. Alerting: status-only vs email/webhook (GROK-24)?  

---

*Generated for JIRA import. Renumber keys to match your JIRA project prefix (e.g. `PROJ-101`).*
