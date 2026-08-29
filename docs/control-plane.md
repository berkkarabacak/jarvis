# Control plane (ORCH-70)

Deterministic mission control independent of agent reasoning and legacy job runners.

## Public interfaces

### Python service

`app.control_plane.service.ControlPlaneService` (factory: `build_control_plane(db)`)

| Method | Purpose |
|--------|---------|
| `create_mission(title, brief, org_id, budget_limit_cents, deadline_at)` | Create `draft` mission |
| `queue_mission` / `start_mission` | Lifecycle forward |
| `complete_mission` / `fail_mission` / `kill_mission` | Terminal transitions; tear down workers |
| `reserve_budget` / `commit_budget` / `release_budget` | Integer-cent ledger; **hard deny** on overspend |
| `list_audit` / `list_ledger` / `mission_detail` | Read models |
| `list_workers` | Worker boundary records |

Errors: `ControlPlaneError`, `TransitionError`, `BudgetError` (with `denial` payload).

### HTTP API (requires `X-Api-Key`)

| Method | Path |
|--------|------|
| GET | `/api/control-plane/status` |
| POST | `/api/control-plane/missions` |
| GET | `/api/control-plane/missions` |
| GET | `/api/control-plane/missions/{id}` |
| POST | `.../queue` · `.../start` · `.../complete` · `.../fail` · `.../kill` |
| POST | `.../budget/reserve` · `.../commit` · `.../release` |
| GET | `.../audit` · `/api/control-plane/audit` |

Budget deny → **HTTP 409** with `{ error: budget_denied, denial: {...} }`.  
Invalid transition → **HTTP 409** `invalid_transition`.  
Missing mission → **HTTP 404**.

### Persistence (SQLite tables)

- `cp_missions` — lifecycle + budget counters (cents)
- `cp_ledger` — append-only reserve/commit/release/refund
- `cp_audit_events` — append-only control-plane audit
- `cp_workers` — isolation boundary records (`logical` mode in this slice)

Separate from legacy `jobs` / `runs`. No provider credentials stored.

## Guarantees

| Capability | Behavior |
|------------|----------|
| Mission lifecycle | `draft → queued → running → succeeded\|failed\|killed` (+ `blocked`) |
| Hard budgets | Agents cannot bypass deny; reservation required path enforced in service |
| Audit events | Every lifecycle/budget/worker mutation audited |
| Worker boundaries | Created on start; terminated on complete/fail/kill |

## Boundary / dependency decisions

1. **Not a security sandbox yet** — `isolation_mode=logical` only; real container/microVM is a later slice.
2. **No secret broker** in this branch — credentials stay outside control-plane tables.
3. **No LLM execution** — does not call Grok/OpenRouter or legacy `JobRunner`.
4. **Org field present** (`org_id`) but full tenancy enforcement depends on ORCH-69 platform store when merged.
5. **Independent of unmerged branches** — ships against `main` + this branch only.

## Non-goals (deferred)

- Real container/microVM isolation + orphan recovery after process crash
- Secret brokering / per-mission credential injection
- OpenRouter/Prime dispatch inside missions (ORCH-71)
- Native schedule dispatcher (ORCH-73)

## Tests

`tests/test_control_plane.py` — lifecycle, hard budget deny, transitions, audit, worker tear-down.

The versioned authorization-aware integration boundary is documented in
[`control-plane-events-v1.md`](control-plane-events-v1.md). It provides
mission-scoped history and resumable SSE without exposing raw audit detail.
