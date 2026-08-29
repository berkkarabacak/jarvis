# Jarvis model benchmarks

Small, repeatable tasks so we can compare **speed**, **cost**, and **effectiveness** as Jarvis improves.

## Scorecard (ORCH-331)

Jarvis should win **successful work per dollar**, not vibes and not a fake IQ/$. Headline metrics (publish all three) are documented in [`docs/jarvis-index.md`](jarvis-index.md):

- **pass@1**
- **$ per success** (failed known-cost runs stay in the $ denominator; one `cost_unknown` row does not wipe the model)
- **escalate %**

Artificial Analysis plots **Intelligence vs Cost per Task**; they do **not** officially rank Quality÷Price. We do not invent their numbers. An optional `ours_composite` may rank *our* table only.

Provider `$0` is `cost_unknown`, not free.

## Multi-task suite (ORCH-332 / ORCH-336)

Harness: `scripts/benchmarks/jarvis_suite_bench.py`

One runner, unique **seed** in the prompt and, when a file is written, in the artifact **filename and body**:

| task | what |
|---|---|
| `tetris` | Tetris HTML write (existing v1 task) |
| `spreadsheet` | seeded CSV spreadsheet write |
| `organize_dry_run` | write a seeded organize **plan** file (seed in filename and body). Listing a folder / calling `home_list` or `organize_folder` is a fail |
| `cheap_math` | optional — 3 grade-school integer questions, exact-number grade (off by default) |
| `local_fact` | tool-mandatory local fact — `get_disk_space` or `home_list` must fire; invented/hallucinated answer = fail |
| `fail_then_escalate` | cheap model first; on fail, stronger retry. Both attempts stay visible; `$` and escalate % include the failed cheap attempt |
| `windows_service_stub` | **one** extra probe: write (do not install) a small Windows service stub under `Exports/`. Seed in filename and body. Must look like a service (`ServiceName` / `win32service` / `sc create` / `nssm`). Chat-only is a fail. Timed via wall-clock `elapsed_sec`. |

`fail_then_escalate` is billed to the starting (cheap) model. Nested `attempts` are not hidden. Provider `$0` is `cost_unknown`, not free.

Metrics per row: **model**, **ok**, **seconds**, **cost_usd**, **artifact**, **escalate**, **seed**, **tools_used**. ORCH-347 also records org shape: **depth** (0 when solo), **agent_count** (1 when solo), **parent_cost_usd**, **child_cost_usd** (0 when solo), wall-clock **elapsed_sec**, and **who_did_what** including managers. A tiny solo job must not grow an org. Results + rollup land in `benchmarks/jarvis-index-latest.json`.

### Run

```bash
export BRIDGE_TOKEN=...
python scripts/benchmarks/jarvis_suite_bench.py \
  --models openai/gpt-4.1-mini,openai/gpt-4.1,google/gemini-2.5-flash
```

Just the 3 cheap math probes (cents; not AIME/IMO):

```bash
python scripts/benchmarks/jarvis_suite_bench.py --cheap-math-only \
  --models openai/gpt-4.1-mini

# equivalent:
python scripts/benchmarks/jarvis_suite_bench.py --tasks cheap_math \
  --models openai/gpt-4.1-mini

# append them to the default suite:
python scripts/benchmarks/jarvis_suite_bench.py --include-cheap-math \
  --models openai/gpt-4.1-mini
```

Just the Windows service stub (one task, not a 10-item suite):

```bash
python scripts/benchmarks/jarvis_suite_bench.py --tasks windows_service_stub \
  --models openai/gpt-4.1-mini
```

Time is wall-clock E2E (`elapsed_sec` on the row; the printed table `seconds` column is that value summed per model). Headline remains pass@1, $ per success, escalate %. Do not invent live numbers.

Tetris-only (compat): `python scripts/benchmarks/jarvis_tetris_bench.py`

## v1 task — Tetris HTML

Ask Jarvis (via Bridge) to write `Exports/bench-tetris-html-<model>-<seed>.html` — a single-file Tetris game. The seed must also appear in the HTML body.

Metrics:
- **ok** — task `done` + file heuristics (size, canvas/keys, **seed in body**)
- **elapsed_sec** — wall clock
- **cost_usd** — from OpenRouter usage when available and **> 0**; otherwise `cost_unknown`
- Reference list prices in the harness (`BENCH_PRICE_PER_MTOK`) for planning

## Improving over time

1. Keep goal text stable so runs stay comparable.
2. Add tasks in the same suite runner (not one-off scripts) when the scorecard needs more signal. Tool-mandatory and fail-then-escalate billing live in this runner (ORCH-336).
3. Track regressions: a model that chats instead of writing a file is a fail.
4. Do not publish headline numbers in docs unless that JSON came from a real run. The 2026-08-13 live run (both models 2/3; organize-dry-run listed Documents instead of a plan) is labeled in [`docs/jarvis-index.md`](jarvis-index.md) — no invented extra numbers.

## Model router (ORCH-328 / ORCH-362)

Jarvis selects an execution model per task via `app/jarvis/model_router.py`:

- **live OpenRouter weekly board as a catalog** at route time (ORCH-362). Slugs must exist in `/api/v1/models`. Live-fetch failure falls back to the 2026-08-14 This Week snapshot plus scorecard JSON. Usage rank is membership only — not “always pick #1.”
- **cheap+fast** for light / routine builds — free is OK only for actually-light jobs; routine builds prefer a cheap capable paid catalog or scorecard model.
- **hard / high-IQ first pick** is a smarter paid catalog model (not free, not the usage-rank #1 flash tip). Fail-then-escalate still steps that pool.
- last scorecard path is persisted on `Memory/jarvis_model_route.json`
- **hard pin wins**: Settings `model`, `JARVIS_MODEL_PIN`, explicit bridge `context.model`, or `JARVIS_DISABLE_MODEL_ROUTER`

Why-model is surfaced on the agent (`model_reason` / `model_route`) and bridge task events/results.
