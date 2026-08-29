# DESIGN: Jarvis company layers (ORCH-345 / ORCH-346)

**Status:** `pick_org()` implemented (ORCH-346). ORCH-350 consumes
`OrgChart.as_dict()` and enforces `widths[layer]` at spawn.
**Width:** still `pick_child_count()` from ORCH-344 (see
[jarvis-children.md](jarvis-children.md)).
**Code:** `app/jarvis/org.py`.

Jarvis must act like a company: layers exist, and a **rule** picks depth.
The parent model does not vote the org chart. Twenty is the wall, not the
default. v1 first slice is depth 2: parent → managers → workers.

## Locked rules

| # | Rule |
|---|------|
| 1 | `pick_org()` returns `{depth, widths[]}` from the work tree, span, pay-to-add-a-layer, scorecard, and ceilings. Not from a model argument. |
| 2 | **Work tree** = pieces + who waits on whom. Depth of *work* (the wait-chain) is not depth of *agents*. |
| 3 | **Span S = 4.** If a node has more than 4 independent pieces, insert a manager layer to own a subset. One manager is refused (same as N=1 → 0). |
| 4 | **Pay-to-add-a-layer.** Add a manager layer only if expected $ of (manager + workers) < expected $ of the parent doing that span, **or** the parent is over span. Unknown $ does not add a discretionary layer. |
| 5 | **D** = min(span-needed depth, budget-fit when known, scorecard best depth for this task class, `DEPTH_CEILING`). |
| 6 | `DEPTH_CEILING = 4` (v1 default max). `ABSOLUTE_WALL = 20` — refuse deeper. A "use 20 layers" ask is clamped; it cannot raise D. |
| 7 | **Width** at each node is `pick_child_count()` (ceiling 4). `widths[i]` is that fan-out at layer *i* below the parent. |
| 8 | If **D < 2 and N < 2**: stay solo (`depth=0`, `widths=[]`). |

## What the numbers mean

```
depth 0  solo — parent does the job
depth 1  shop — parent → workers          widths = [N]
depth 2  company (v1) — parent → managers → workers
         widths = [managers, workers_per_manager]
```

Examples:

* Tiny / light job, or N < 2: **depth 0**.
* Two independent files + budget: **depth 0 or 1** (pay-to-spawn). No manager.
* Eight independent pieces: parent is over span (8 > 4) → **depth 2**,
  `widths = [2, 4]` (two managers, each up to four workers).
* "Use 20 layers": rule still chooses; result is **≤ 20** and for v1 **≤ 4**.
  Twenty is the wall, not the default.

## What `pick_org` accepts (evidence, not a vote)

Same budget / scorecard knobs as `pick_child_count()`: independent pieces
(or a `WorkTree` / goal), remaining `$` / seconds, unit costs, learned K,
learned depth. There is **no** `depth` / `n` / `widths` argument. `spawn_child`
still has no count or depth parameter.

## Non-goals (this ticket)

* Hiring the tree (managers spawning workers) — ORCH-350
* Unbounded swarms, model-voted org charts, Prime / control-room
