# OpenAI Agents API (PR0 spike)

**Status:** spike only — thin HTTP client + tests. **Not wired** into Talk,
gateway, ChildSupervisor, or settings. **No public default.**

Tracks [issue #26](https://github.com/berkkarabacak/jarvis/issues/26).

## What this is

`app/jarvis/agents_api.py` calls OpenAI’s Agents API
(`POST /v1/agents/sessions` with `OpenAI-Beta: agents=v1`) so we can prove
create → stream/consume events → delete.

Locked spike choices (do not reopen here):

| Choice | Value |
|---|---|
| Environment | `{ "type": "none" }` only |
| Multi-agent | `agent.multi_agent.enabled: true` |
| Concurrency | `max_concurrent_subagents` default **4**, capped at 4 |
| Child path | `spawn_child` / `message_child` / `wait_child` unchanged |
| Taint | PR1 should reuse `taint_source="child"` (`CHILD_TAINT_SOURCE`) |

The repo does not depend on the official `openai` Python SDK, so the client
uses `httpx` plus the beta header. Official docs:
[Agents API overview](https://developers.openai.com/api/docs/guides/agents-api/overview),
[multi-agent](https://developers.openai.com/api/docs/guides/agents-api/multi-agent).

## What this is not

- Not a Live Talk / Realtime / deploy change
- Not enabled in settings or on aicontrolroom.nl
- Not a replacement for the home-grown child loop
- Hybrid B+C (Talk + wrap children) is later — this PR does not hook
  ChildSupervisor

## Tests

Mocked request-shape tests in `tests/test_jarvis_agents_api.py` always run.

Optional live proof (skipped in CI when the key or flag is missing):

```bash
# Operator machine only. Do not commit keys.
export JARVIS_AGENTS_API_LIVE=1
export OPENAI_API_KEY=...   # your key; never paste a real key into docs or fixtures
pytest tests/test_jarvis_agents_api.py -q -m agents_api
```

## Next (not this PR)

PR1: adapter behind a flag, taint + confirm still hold, no public default
until proved. See issue #26.
