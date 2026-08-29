# Jarvis security + public cloud guardrails ==GRoK== (ORCH-259)

## Local desktop (owner)

- Loopback bind: `HOST=127.0.0.1`
- ToolGateway L0–L5 + confirm for L3+
- PowerShell denylist (ORCH-295)
- App allowlist for auto L3 `run_app`
- Bridge token required (`BRIDGE_TOKEN`)
- Audit: `Memory/tool_audit.db`

## Public cloud (aicontrolroom.nl / guest)

`app/jarvis/guardrails.py` runs at app create:

| Control | Forced value |
|---------|----------------|
| `JARVIS_ENABLED` | false |
| `JARVIS_REALTIME` | false |
| `PRIME_AGENT_ENABLED` | false |
| `BRIDGE_ENABLED` | false |
| `BRIDGE_TOKEN` | cleared |
| `EXECUTIVE_PRIME_ADAPTER` | openrouter |

Triggers when:

- `PUBLIC_GUEST_PROFILE=true`, or
- `JARVIS_PUBLIC_CLOUD=true`, or
- `PUBLIC_BASE_URL` contains `aicontrolroom.nl`

Gateway also hard-denies laptop tools if somehow called on a public host.

## Never on public guest

- Prime RPC / local binary
- PowerShell, run_app, home_* writes
- Realtime local tool mint against the laptop
- Bridge agent API
