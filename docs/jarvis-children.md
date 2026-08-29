# DESIGN: Jarvis child-agent API v1 (ORCH-338)

**Status:** implemented — child loop (ORCH-339), taint/journal (ORCH-340),
pay-to-spawn count (ORCH-344), `pick_org()` (ORCH-346), managers hire
workers (ORCH-350).
**Implements in:** ORCH-339 (Child Loop), ORCH-340 (taint / journal),
ORCH-344 (dynamic child count), ORCH-346 (`pick_org`), ORCH-350 (manager
depth 2).
**Bench:** ORCH-342 (two-file split).
**Company layers:** [jarvis-company.md](jarvis-company.md).

Three tools, not one `orchestrate`: a single `orchestrate` with two slots would
force a fork-join in one call and hide mid-flight `message_child`, so the parent
loop stays in control with spawn / message / wait.

Related: `docs/jarvis.md`, `docs/jarvis-permissions.md`, `docs/jarvis-index.md`,
`docs/jarvis-company.md`, `app/jarvis/taint.py`, `app/jarvis/model_router.py`,
`app/jarvis/daily_journal.py`.

## Locked rules

| # | Rule |
|---|------|
| 1 | Lifetime child cap is **`pick_child_count()`** (pay-to-spawn), not a hardcoded 2 and not a model vote. Hard **ceiling 4**. If N < 2, stay solo (N=1 is coerced to 0 — one child is just a more expensive solo). |
| 2 | Children start on the **cheap** model via the existing router / scorecard. Escalate **once** only if cheap fails. No model override arg in v1. |
| 3 | **No free swarm.** Workers cannot spawn (gateway `CHILD_FORBIDDEN`). A child may spawn only as a **manager of its slice**. v1 company is parent → managers → workers (2 hops). `pick_org()` (ORCH-346) sets allowed depth when present; otherwise span 4, `DEPTH_CEILING=4`, `ABSOLUTE_WALL=20` (refuse deeper). N<2 and D<2 → solo. |
| 4 | Inter-agent messages are short, audited, and **tainted** like connector / MCP results. |
| 5 | **L2 confirm still applies** to writes. A child does not skip it. Same allowlist / confirm path as the parent. |
| 6 | If a split would cost more than solo, stay solo. `spawn_child` **refuses** with `STAY_SOLO` rather than start the child. |

## Why not Prime / one orchestrate

Prime RPC specialists (`dispatch_prime`, D-006) are out of v1. This is a second
short-lived **Jarvis** loop under the same `ToolGateway`, not a Control Room
swarm.

## Tools

Register in `app/jarvis/tools.py` (`TOOL_SPECS` + `run_tool`) and
`app/jarvis/permissions.py` (`TOOL_TIERS`). Dispatch only through
`ToolGateway.run` in `app/jarvis/gateway.py` — never around the gateway.

Tier: **L0** for all three (orchestration, not a write). After a child result
taints the parent, L0 still `ALLOW`s so the parent can `message_child` /
`wait_child` / spawn the second slot. The **child's** `write_file` / `home_write`
/ `run_powershell` still use normal L1–L3 + confirm.

Error shape matches existing tools: `{"ok": false, "error": "<CODE>"}`.
`error` is the stable code (exact strings below). Optional `message` may explain;
Child Loop must not invent new codes.

### `spawn_child`

```
spawn_child(goal: string, budget_seconds: number, budget_usd: number) ->
  { ok: true, id: string, status: "running", model: string }
```

| Arg | Rule |
|-----|------|
| `goal` | required, non-empty after strip, max **2000** chars |
| `budget_seconds` | required, **> 0** |
| `budget_usd` | required, **> 0** |

- `id` is opaque, scoped to the parent job: `c_` + 8 hex (same style as
  `cnf_` in `gateway.py`). Parent uses it for `message_child` / `wait_child`.
- Router picks the cheap model; record it on the child. **Do not** accept a
  `model` argument. **Do not** accept a count / `n` argument — N is computed.
- Before starting: estimate split vs solo. If split (parent + this child + any
  already-running sibling) would cost more than the parent doing the work
  alone, refuse with `STAY_SOLO`. Do not spawn.
- Live + historical **direct reports of this hirer** cannot exceed
  `pick_org().widths[layer]` (parent uses `widths[0]`; a manager uses
  `widths[hirer.depth]`, never a re-run of the parent `pick_child_count`).
  `CHILD_LIMIT` fires when a spawn would exceed that slice cap.

### Pay-to-spawn N (ORCH-344)

The parent model does **not** vote how many children to hire. N is:

```
N = min(
  independent_work_items,                 # pieces that do not wait on each other
  floor(remaining_usd / child_unit_cost),
  floor(remaining_seconds / child_unit_seconds),
  learned_k_from_scorecard,               # best $ per success for this task class; 0 = solo
  CEILING                                 # 4
)
```

- Unknown inputs are omitted (they do not constrain). Unknown must not force solo.
- If N < 2: stay solo. Coerce N=1 to 0.
- If `expected_split_usd > expected_solo_usd` (both known): `STAY_SOLO`.
- `independent_work_items` comes from the **parent job goal** (not the child
  piece goal, and not a model argument). Explicit light-task patterns
  (disk / screenshot / …) count as 1. If pieces cannot be counted, the
  term is omitted — unknown must not force solo. The original job goal is
  bound once; later parent turns do not overwrite it.
- `child_unit_cost` / `child_unit_seconds` prefer scorecard `$ per success` /
  seconds per success for the cheap child model, else the spawn budget.
- `remaining_usd` / `remaining_seconds` are the parent job's remaining budgets
  when known (parent `JarvisLocalAgent` caps).
- `learned_k_from_scorecard` is 0 when the scorecard's best `$ per success`
  for this task class is solo.

### Company depth (ORCH-346)

Width is this file. **Depth** is `pick_org()` in `app/jarvis/org.py` —
[jarvis-company.md](jarvis-company.md). Span 4, pay-to-add-a-layer,
`DEPTH_CEILING=4`, `ABSOLUTE_WALL=20`. The model does not vote depth.
v1 first slice is parent → managers → workers. Hiring that tree is
ORCH-350; children still cannot spawn in this loop.

Errors:

| Code | When |
|------|------|
| `CHILD_LIMIT` | spawn would exceed computed N for this parent job |
| `CHILD_FORBIDDEN` | caller is a worker (or a child with no remaining depth) |
| `DEPTH_WALL` | spawn would exceed `ABSOLUTE_WALL` (20) |
| `STAY_SOLO` | estimated split cost > solo, or computed N < 2 |
| `INVALID_BUDGET` | missing, zero, or negative `budget_seconds` / `budget_usd` |
| `GOAL_EMPTY` | missing / blank `goal` |
| `GOAL_TOO_LONG` | `goal` longer than 2000 chars |

### `message_child`

```
message_child(id: string, text: string) ->
  { ok: true, id: string, delivered: true }
```

| Arg | Rule |
|-----|------|
| `id` | child id from `spawn_child` on **this** parent job |
| `text` | required, non-empty after strip, max **2000** chars |

- Delivered into the child's inbox; child sees it on its next turn.
- Audited (`ToolGateway._audit` / `app/jarvis/audit.py` JSONL).
- The text is tainted when it lands in **either** agent's context
  (`taint_source: "child"`), same as a connector result.

Errors:

| Code | When |
|------|------|
| `UNKNOWN_CHILD` | `id` not on this parent job |
| `CHILD_NOT_RUNNING` | child already terminal (`done` / `failed` / budget) |
| `TEXT_EMPTY` | missing / blank `text` |
| `TEXT_TOO_LONG` | `text` longer than 2000 chars |
| `CHILD_FORBIDDEN` | caller is a worker |

### `wait_child`

```
wait_child(id: string) ->
  { ok: true, id: string,
    status: "done" | "failed" | "budget_seconds" | "budget_usd",
    result: string,
    artifacts: [{ path: string, kind: string }],
    usage: { seconds: number, usd: number, model: string, escalated: boolean },
    tainted: true,
    taint_source: "child" }
```

- Blocks until the child is terminal. If already terminal, return immediately.
- `result` and any artifact contents are untrusted. Parent must `observe()`
  them like MCP / connector bytes. Taint does **not** clear until a fresh user
  utterance (`TaintTracker.clear` / `ToolGateway.clear_taint`).
- Budget hit: child is killed, `status` is `budget_seconds` or `budget_usd`,
  `ok` is still **true** (wait succeeded; the child did not). Include partial
  `result` / `usage` if any.
- Cheap-model failure may escalate **once** via the router;
  `usage.escalated` records that. Escalation still counts against the same
  `$` / seconds budget.

Errors:

| Code | When |
|------|------|
| `UNKNOWN_CHILD` | `id` not on this parent job |
| `CHILD_FORBIDDEN` | caller is a worker |

## Company layers (ORCH-345 / ORCH-350)

v1 org is **parent → managers → workers** (2 hops). The model does not vote
the chart.

- `resolve_org()` consumes `pick_org()` (`OrgChart.as_dict()`). Spawn
  enforces `widths[layer]`. A manager slice with unknown or &lt;2 countable
  pieces is `STAY_SOLO` (unknown must not fill N from parent `$`).
- `ChildRecord.role` is `manager` or `worker`. `remaining_depth` comes from
  the **root** plan, decremented per hop — not from re-running `pick_org`
  on a restated parent goal. Hop 3 only when the work tree is over span.
- A manager may `spawn_child` / `message_child` / `wait_child` **only for
  its slice** (direct reports). Workers get `CHILD_FORBIDDEN`.
- Spawn that would land past hop 20 returns `DEPTH_WALL`.
- Same taint, L2 confirm, cheap model, isolated memory, no nonce leak.
  `remember` / `forget_memory` / `save_mission_summary` stay forbidden for
  every child, including managers.

## Child runtime (ORCH-339)

A child is a short-lived `JarvisLocalAgent` loop (`app/jarvis/agent.py`) with
the same L0–L2 (and confirm-gated L3) tools as the parent. Workers omit the
child-API tools. Managers keep `spawn_child` / `message_child` / `wait_child`
while `remaining_depth > 0`. Prime and parent-memory writes stay omitted.

- Tool list: parent `TOOL_SPECS` plus discovered `mcp.*`. Workers **omit**
  `spawn_child` / `message_child` / `wait_child`. Managers keep those three
  while they have remaining depth. Every child omits `dispatch_prime` and
  parent-memory writes (`remember` / `forget_memory` / `save_mission_summary`).
- Every child tool call goes through `ToolGateway.run`. Writes use the same
  `authorize()` / `gate()` / allowlist (`app/jarvis/allowlist.py`) as the
  parent. Personal profile still auto-allows L2 when **untainted**; tainted
  L1–L2 still `CONFIRM`; L3+ still confirm or deny. **No silent auto-confirm.**
- Child confirmations use the same pending map + spoken nonce
  (`app/jarvis/nonce.py` `ConfirmBook`) and the same user path:
  `POST /api/jarvis/tools/confirm`, voice nonce, or Bridge
  `POST /tasks/{id}/confirm`. Gateway already refuses a model tool call that
  tries to approve (`"a tool call cannot approve"`).
- Gateway `source` for the child: `child:{id}` so it gets its own
  `TaintTracker` (parent `source` stays `jarvis-agent` / `realtime` /
  `bridge:…`).
- Detect `CHILD_FORBIDDEN` from that `source` prefix **and the child's role**.
  Workers (and managers with no remaining depth) cannot spawn. Do not rely
  on the model to omit the tools.
- Parent job id: one Bridge task (`tsk_…` in `bridge_store`) **or** one
  `JarvisLocalAgent` `session_id` **or** one Realtime session. The
  `pick_child_count()` cap is lifetime on that job, including finished
  children. The parent turn binds the user goal + remaining budgets onto
  that job so N is not a model vote.
- Parent merges child artifacts and returns **one** user-facing result.
- Inbox: `message_child` enqueues `text`; the child loop prepends it on the
  next turn, then `observe()`s taint (`taint_source: "child"`) without
  treating the text as a trusted user utterance (`clear_taint` is owner-only).

### Cheap model + escalate

Start the child on the cheap rung. Do **not** pass `explicit_model` and do
**not** honor Settings / `JARVIS_MODEL_PIN` for children (a parent pin must
not steal the child onto the expensive model).

Use `app/jarvis/model_router.py`:

- cheap start: scorecard order from `_ladder()` index 0 /
  `load_bench_preferred_cheap()` / `cheap_default_model()` — same cheap
  default as `docs/jarvis-index.md` (lowest `$ per success` among models
  whose pass@1 is at least as good as the current cheap, else best pass@1
  then cheapest).
- on cheap failure: `record_outcome(..., ok=False)` then `route_model(...,
  prior_failures=1)` **once**. `usage.escalated = true`. Same budgets.

### Stay-solo estimate

Before spawn, compare:

- **solo** — estimated USD for the parent finishing the whole goal alone
- **split** — parent + this child + already-running siblings

Prefer scorecard `$ per success` / known USD from
`app/jarvis/cost_index.py` (`usd_per_success` on the model rollup). If the
estimate is unknown, do **not** refuse (`STAY_SOLO` only when split is
**known** to cost more). If `split_usd > solo_usd`, return `STAY_SOLO` and
do not start the child.

### Budgets

Child Loop kills the child when wall-clock exceeds `budget_seconds` or
accrued OpenRouter USD exceeds `budget_usd`. `wait_child` then returns the
matching status. Escalation tokens still count against `budget_usd`.

## Taint (ORCH-340)

Verified against `app/jarvis/taint.py` (do not invent a second tracker):

- Built-in untrusted names live in `UNTRUSTED_TOOLS`.
- MCP uses a **sibling** set/prefix (`MCP_UNTRUSTED_PREFIX = "mcp."` +
  `mcp_untrusted_tool_names()`), unioned in `returns_untrusted()`.
- Child tools are three static names, same confused-deputy path as MCP.
  They belong in sibling `CHILD_UNTRUSTED` (not `UNTRUSTED_TOOLS`: those
  comments mean bytes from disk/network, not another agent). `returns_untrusted()`
  must return true for them. Gateway already calls `observe()` after every
  tool and `_mark_untrusted()` when `returns_untrusted(tool)`.

Locked names (also in `taint.py`):

```
CHILD_UNTRUSTED = frozenset({"spawn_child", "message_child", "wait_child"})
CHILD_TAINT_SOURCE = "child"
```

ORCH-340: when these tools (or the child's inbox `result`) taint a turn,
`taint_source` on the payload is `"child"` (not the tool name).
`TaintTracker.observe()` today stores the tool name; override for this set.
Fence `result` / artifact text like MCP (`<<<UNTRUSTED_TOOL_OUTPUT ...>>>`).
Taint clears only on a fresh owner utterance.

`wait_child` always returns `tainted: true` and `taint_source: "child"` even
when `status` is `done`.

## Daily journal (ORCH-329 is on `dev`)

Do **not** reimplement the journal. When the **parent job** ends, write one
line via `app/jarvis/daily_journal.py`:

- `upsert_day_journal(memory, day_key(), digest, source=…)` with child ids,
  models, USD, and who did what in `digest["notes"]` (and artifact paths in
  `digest["artifacts"]`). Successful `spawn_child` also increments
  `agents_created` on that day's digest (0 when none; field is never omitted).
- `redact_for_journal` / `sanitize_text` still apply.
- `note_session_activity` already rolls Voice/agent/Bridge turns into today's
  fact; the child line is an extra `notes` entry on that same `day:YYYY-MM-DD`
  + `daily-journal` fact, not a new store.

Example note: `children: c_a1b2c3d4 (openai/gpt-4.1-mini, $0.004, stub.md);
parent merged readme`.

## Acceptance job (ORCH-342 — do not add here)

One parent job that needs **two artifacts** (stub + readme, or CSV + HTML).
`pick_child_count()` yields N=2 when budget and scorecard allow; merge into
one user-facing result. A tiny solo job must not spawn. Stay-solo must still
refuse when the estimate says split is more expensive, and the hard ceiling
stays 4.

## Non-goals

- Prime RPC / Control Room specialists
- Trees, swarms, children talking to Slack/GitHub **inbound**
- Implementing the loop, router changes, or journal wiring (this ticket)
- A fourth tool or a single `orchestrate`

## Implementer map

| Piece | Path |
|-------|------|
| Tool specs + `run_tool` | `app/jarvis/tools.py` |
| Tiers | `app/jarvis/permissions.py` `TOOL_TIERS` |
| Gateway / confirm / audit | `app/jarvis/gateway.py` |
| Spoken nonce | `app/jarvis/nonce.py` |
| Allowlist | `app/jarvis/allowlist.py` |
| Parent / child loop | `app/jarvis/agent.py` `JarvisLocalAgent` |
| Taint | `app/jarvis/taint.py` `observe` / `gate` / `returns_untrusted` |
| Cheap / escalate | `app/jarvis/model_router.py` `route_model` `record_outcome` |
| Scorecard $ | `app/jarvis/cost_index.py`, `docs/jarvis-index.md` |
| Company depth | `app/jarvis/org.py` `pick_org` — [jarvis-company.md](jarvis-company.md) |
| Journal | `app/jarvis/daily_journal.py` `upsert_day_journal` |
| Audit JSONL | `app/jarvis/audit.py` |
| Bridge task id | `app/jarvis/bridge_store.py` |

## Out of scope for ORCH-338

- Child process / inbox / wait implementation
- Gateway dispatch for the three tools (beyond the taint name lock)
- Tests for a real child loop
- Bench task (ORCH-342)
