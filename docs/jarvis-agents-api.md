# OpenAI Agents API (PR1 adapter)

**Status:** thin client (PR0) plus a **flagged** child-runner adapter (PR1).
**Not** a Live Talk / Realtime / deploy change. **No public default** on
aicontrolroom. Default remains the existing OpenRouter `JarvisLocalAgent`
child loop.

Tracks [issue #26](https://github.com/berkkarabacak/jarvis/issues/26).

## What this is

`app/jarvis/agents_api.py` calls OpenAI’s Agents API
(`POST /v1/agents/sessions` with `OpenAI-Beta: agents=v1`).

`app/jarvis/agents_child.py` is the PR1 adapter: when the operator flag is
on, `ChildSupervisor` / `default_child_runner` may swap the **child
harness** for an Agents session. Parent tools stay
`spawn_child` / `message_child` / `wait_child` through `ToolGateway`.

Locked choices (do not reopen here):

| Choice | Value |
|---|---|
| Environment | `{ "type": "none" }` only |
| Multi-agent | `agent.multi_agent.enabled: true` |
| Concurrency | `max_concurrent_subagents` default **4**, capped at 4 |
| Tool surface | unchanged (`spawn_child` / `message_child` / `wait_child`) |
| Taint | `tainted: true`, `taint_source: "child"` (`CHILD_TAINT_SOURCE`) |
| Flag | `JARVIS_AGENTS_API` default **off** |

The repo does not depend on the official `openai` Python SDK, so the client
uses `httpx` plus the beta header. Official docs:
[Agents API overview](https://developers.openai.com/api/docs/guides/agents-api/overview),
[multi-agent](https://developers.openai.com/api/docs/guides/agents-api/multi-agent),
[sessions](https://developers.openai.com/api/docs/guides/agents-api/sessions).

## Feature flag

`JARVIS_AGENTS_API` is env-only (no Settings UI, no Talk deploy pin).

The Agents child runner is used only when **both** are true:

1. `JARVIS_AGENTS_API` is `1` / `true` / `on` / `yes`
2. An OpenAI key is available (`OPENAI_API_KEY` or `HOSTED_OPENAI_KEY`)

Otherwise today’s OpenRouter `JarvisLocalAgent` path runs. Function-tool-heavy
child work still works locally when the flag is off.

## Soft router

When the flag is on:

- **Local** for UI / desktop / function-tool goals (`write_file`, `click`,
  `see_screen`, `run_powershell`, Chrome/notepad, …). Agents subagents cannot
  use Jarvis function tools; `environment.none` has no hosted desktop.
- **Agents** for research / coding-ish goals (research, summarize, compare,
  analyze, refactor, …).
- **Ambiguous** → Agents (v1).

## Mapping

| Jarvis tool | Agents API |
|---|---|
| `spawn_child` | `POST /v1/agents/sessions` (`multi_agent` on, cap 4, env none). Session / subagent ids stored on `ChildRecord`. |
| `message_child` | `agent.session.input.message`. Active turn = steer; idle session = new turn. `agent.session.idle` is **not** success. |
| `wait_child` | Wait for coordinator `turn.completed` / `failed` / `cancelled`. Same payload as today, including `tainted: true` and `taint_source: "child"`. Artifacts / USD are best-effort from the stream — never invented. |
| Budgets | Existing seconds / USD watch calls Agents `agent.session.input.cancel`. |

Gateway authorize, confirm, and the parent daily journal stay outside the
harness. Do not bypass `ToolGateway` for parent tools.

## What this is not

- Not a Live Talk / Realtime / deploy change
- Not enabled in settings or on aicontrolroom.nl
- Not a replacement for the home-grown child loop when the flag is off
- Children that need Jarvis function tools still use the local loop

## Local smoke (operator machine only)

Do not commit keys. Do not paste a real key into docs or fixtures.

```bash
# Off by default. Enable only on a machine that already has OPENAI_API_KEY.
export JARVIS_AGENTS_API=1
export OPENAI_API_KEY=...   # your key; never commit it
pytest tests/test_jarvis_agents_child.py tests/test_jarvis_children.py tests/test_jarvis_agents_api.py -q
```

Optional live client proof (still skipped in CI without the live flag):

```bash
export JARVIS_AGENTS_API_LIVE=1
export OPENAI_API_KEY=...
pytest tests/test_jarvis_agents_api.py -q -m agents_api
```

## Tests

- `tests/test_jarvis_agents_api.py` — mocked client request shape (PR0)
- `tests/test_jarvis_agents_child.py` — flag off keeps local; flag on +
  mocked client maps spawn / message / wait
- `tests/test_jarvis_children.py` — existing contract; must still pass
