# Jarvis bench scorecard

Jarvis may not win raw IQ. The goal is to be the **most cost-efficient** colleague: successful local work per dollar, without inventing a single fake IQ/$.

Epic: ORCH-330. Scorecard: ORCH-331. Suite: ORCH-332 / ORCH-336. Follow-up: ORCH-334.

## What Artificial Analysis actually does

[Artificial Analysis](https://artificialanalysis.ai/methodology) publishes an **Intelligence Index** (a weighted quality score) and **Cost per Task**. They **plot Intelligence vs Cost per Task**. They do **not** officially rank a Quality÷Price (IQ/$) number.

This repo is *inspired by* that two-axis view. We do **not** copy, invent, or publish Artificial Analysis numbers, and we do **not** claim an official AA Quality÷Price rank.

## Headline metrics (publish all three)

Per model, over one suite run (each task once → **pass@1**):

| metric | formula |
|---|---|
| **pass@1** | `successes / n` |
| **$ per success** | `sum(known cost_usd) / known-cost successes` — **failed known-cost runs stay in the $ denominator** |
| **escalate %** | `100 × escalate_count / n` |
| **seconds** (table) | wall-clock E2E: sum of `elapsed_sec` per model |

A failed task contributes **0** to successes and still adds any known USD to the $ per success denominator. Zero successes → `$ per success` is undefined (`—`), not free.

One `cost_unknown` task does **not** wipe the model: `$ per success` is computed from **known-cost rows only** (those rows' failures still sit in the $ sum). If *every* row is `cost_unknown`, the model stays `cost_unknown`.

**Fail-then-escalate (ORCH-336):** if the cheap model fails and a stronger model retries, both attempts stay on the row under `attempts` (retries are not hidden). `$ per success` and `escalate %` include the failed cheap attempt plus the extra escalate $. The starting (cheap) model owns that row.

### Honest cost

If the provider reports `$0` or omits cost, the **task** row is `cost_unknown`. That is **not** free. Skip that row when rolling up `$ per success`; do not treat it as $0. If all rows are unknown, `$ per success` and our optional composite are omitted. Earlier Gemini Flash `$0.00` reporting was treated as suspect for this reason.

## Optional composite (ours only)

For ranking **our** table we may use:

```
ours_composite = successes / (cost_usd + λ × elapsed_sec)
```

λ = `0.0001` USD/sec (`TIME_PENALTY_USD_PER_SEC` in `app/jarvis/cost_index.py`) — small; ~10s ≈ $0.001.

This is **our** ranking key. It is **not** an Artificial Analysis IQ/$ number.

## Raw table

Each run stores per-task rows (`model`, `ok`, `seconds`, `cost_usd`, `escalate`, `artifact`, `seed`, plus ORCH-347 org shape: `depth`, `agent_count`, `parent_cost_usd`, `child_cost_usd`, `who_did_what`) and a per-model rollup of the three headlines plus optional `ours_composite`.

## Worked example (synthetic — unit tests, not a live run)

Two tasks each. λ = 0.0001.

| model | pass@1 | $ per success | escalate % | seconds | ours_composite |
|---|---:|---:|---:|---:|---:|
| openai/gpt-4.1-mini | 2/2 = 1.0 | 0.012 / 2 = **0.006** | 0 | 20 | 2 / (0.012 + 0.0001×20) ≈ 142.86 |
| openai/gpt-4.1 | 2/2 = 1.0 | 0.048 / 2 = **0.024** | 0 | 18 | 2 / (0.048 + 0.0001×18) ≈ 40.16 |
| google/gemini-2.5-flash | 1.0 | cost_unknown | 0 | — | not rankable on $ |

Failure still bills: 1 success + 1 fail, $0.006 + $0.010 → **$ per success = 0.016** (not 0.006). pass@1 = 0.5. ours_composite = `1 / (0.016 + 0.0001×30) ≈ 52.63`.

See `tests/test_jarvis_cost_index.py`.

## Historical note — 2026-08-13 live run (not a new scorecard)

First live suite on Windows Jarvis: `openai/gpt-4.1-mini` and `openai/gpt-4.1`, three tasks.

Both models **pass@1 = 0.6667 (2/3)**. `organize-dry-run` failed: Jarvis listed Documents items instead of writing a seeded organize *plan* file. That row had `cost_usd` null / `cost_unknown`, which made the printed model `$ per success` = `cost_unknown` even though Tetris and spreadsheet had real OpenRouter costs. Escalate % printed `0.0`. The script then crashed on Windows cp1252 printing `λ`.

No other live dollar figures from that run are published here. The harness now grades organize as a written plan (listing a folder is a fail), rolls `$ per success` from known-cost rows only, prints `lambda=`, and the router reads the scorecard as described below.

## Historical Tetris-only notes (not a scorecard)

Earlier Tetris harness runs (not this suite, not a new live scorecard):

- `openai/gpt-4.1-mini` ~8–27s / ~$0.006–0.007
- `openai/gpt-4.1` similar wall time, about 4× cost
- `google/gemini-2.5-flash` `$0.00` reporting was suspect

Do not treat those as published headlines until `scripts/benchmarks/jarvis_suite_bench.py` is actually run.

## Run

```bash
export BRIDGE_TOKEN=...
python scripts/benchmarks/jarvis_suite_bench.py \
  --models openai/gpt-4.1-mini,openai/gpt-4.1,google/gemini-2.5-flash
```

Writes `benchmarks/jarvis-index-latest.json`. Unique **seed** is in the prompt and, when a file is written, in the artifact filename **and** the file body.

The model router (`app/jarvis/model_router.py`) treats the OpenRouter weekly board as a **catalog**, not a “pick #1 / pick free” ranking. Light jobs may use a cheap or free catalog model. Routine builds prefer a cheap capable paid model (scorecard `$ per success` when present). Hard jobs start on a paid high-IQ catalog model. Fail-then-escalate still steps the same pool. Last scorecard path is persisted on the route state. A hard pin still wins.

Suite tasks include Tetris, seeded CSV, organize dry-run (plan file required), **tool-mandatory local fact**, **fail-then-escalate** billing, **windows_service_stub** (write a seeded service stub; do not install), and optional **cheap_math** (3 grade-school integer questions; off by default). See [`docs/jarvis-benchmarks.md`](jarvis-benchmarks.md).
