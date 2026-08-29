# Prime Agent local setup (Windows / WSL) ==GRoK==

Prime Agent is the **heavy worker** for long coding jobs. Fast laptop facts use
Jarvis tools; fluent voice uses OpenAI Realtime.

## When to enable

| Work | Engine |
|------|--------|
| Free space, list files, Excel, quick scripts | Jarvis tools |
| Multi-file coding, long autonomous tasks | **Prime Agent RPC** |

**Never** enable Prime for public cloud guest CEO.

## Install options

### A) Official installer (Linux/macOS; WSL2 on Windows)

```bash
curl -fsSL https://app.primeintellect.ai/prime-agent/install.sh | sh
which prime-agent
```

On Windows, prefer **WSL2 Ubuntu**, then set:

```env
PRIME_AGENT_ENABLED=true
PRIME_AGENT_BIN=wsl
# or full path inside WSL via wsl -e
PRIME_AGENT_WORKDIR=C:\Users\YOU\Documents\Jarvis\PrimeWork
EXECUTIVE_PRIME_ADAPTER=rpc
```

### B) From source (Node ≥ 22.8)

```bash
git clone https://github.com/PrimeIntellect-ai/prime-agent
cd prime-agent && npm ci
# use ./prime-agent.sh as PRIME_AGENT_BIN
```

## Env (local owner only)

```env
PRIME_AGENT_ENABLED=true
PRIME_AGENT_BIN=C:\path\to\prime-agent.exe
PRIME_AGENT_WORKDIR=%USERPROFILE%\Documents\Jarvis\PrimeWork
# Keep JARVIS tools for L0-L2; pin rpc only when exercising Prime:
# EXECUTIVE_PRIME_ADAPTER=rpc
```

Create an **isolated** workdir (not your whole profile).

## Durable memory (with Jarvis)

1. **Prime harness memory** inside `PRIME_AGENT_WORKDIR` (trajectory of work).
2. **Jarvis SQLite** (`Documents\Jarvis\Memory\jarvis.db`) for user/project facts.
3. On mission start: inject top facts + last summaries.
4. On mission end: write `Memory/summaries/<id>.md` + SQLite row.

No TencentDB on the desktop path.

## Smoke check

```bash
# with venv active and env set
python -c "from app.executive.adapters.factory import build_executive_prime_agent; from app.config import get_settings; a=build_executive_prime_agent(get_settings()); print(a.name)"
```

Expect `prime-rpc` when enabled and binary works; otherwise `jarvis-local` / `openrouter-prime`.

## Factory order

1. `jarvis` if `EXECUTIVE_PRIME_ADAPTER=jarvis` or `JARVIS_ENABLED=true`
2. `prime-rpc` if `PRIME_AGENT_ENABLED=true`
3. `openrouter-prime` if OpenRouter key set
4. `null`

## B2 dispatch (ORCH-252)

| Path | Behavior |
|------|----------|
| Bridge `POST /tasks` | Classifier picks `jarvis` vs `prime`; override with `"engine":"prime"` |
| Tool `dispatch_prime` | Explicit heavy handoff from voice/agent |
| Prime down | Returns `degraded=true`; Jarvis tools continue (Realtime stays up) |

Classifier heuristics: disk/files/screenshot → jarvis; multi-file refactor / “use prime” → prime.

Mission results store `mission_id` + `prime_session_id` in `mission_summaries` (C1 schema).
