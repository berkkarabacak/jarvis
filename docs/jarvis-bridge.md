# Jarvis Agent Bridge API ==GRoK==

Authenticated **localhost** API so OpenCode and other authorized AI agents can
task Jarvis safely.

## Enable

```env
BRIDGE_ENABLED=true
BRIDGE_TOKEN=long-random-secret
BRIDGE_MAX_TIER_AUTO=L1
```

Server must bind loopback (`HOST=127.0.0.1`).

## Auth

```http
X-Jarvis-Bridge-Token: <BRIDGE_TOKEN>
```

Missing/invalid → **401**. Bridge disabled (no token) → **403**.

## Endpoints

Base: `http://127.0.0.1:8787/api/bridge/v1`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/status` | Health + adapters + permission snapshot |
| GET | `/capabilities` | Tools and tiers |
| POST | `/tasks` | Create task |
| GET | `/tasks/{id}` | Poll status/result |
| POST | `/tasks/{id}/confirm` | approve/deny |
| POST | `/tasks/{id}/cancel` | Cancel |
| POST | `/messages` | Convenience ask |
| GET | `/events?task_id=` | SSE progress |

## Example (OpenCode / curl)

```bash
export BRIDGE=http://127.0.0.1:8787/api/bridge/v1
export TOK=long-random-secret

curl -s -H "X-Jarvis-Bridge-Token: $TOK" $BRIDGE/status

curl -s -X POST -H "X-Jarvis-Bridge-Token: $TOK" -H "Content-Type: application/json" \
  -d '{"goal":"How much free disk space do I have?","source":"opencode"}' \
  $BRIDGE/tasks

# poll
curl -s -H "X-Jarvis-Bridge-Token: $TOK" $BRIDGE/tasks/tsk_...
```

## Security

- Same ToolGateway tiers as voice/Realtime tools
- Default auto tier for bridge: **L1** (disk/system/workspace)
- L3+ returns `needs_confirm` with `confirm_id` + `action_summary` (unless app allowlisted)
- Confirm: `POST /tasks/{id}/confirm` body `{"confirm_id":"...","decision":"approve"|"deny"}`
- If nobody confirms, the same approve-wait as the on-screen prompt accepts for you (default 10 seconds; Settings or `JARVIS_APPROVE_COUNTDOWN_SEC`). An earlier deny still wins.
- Allowlisted apps auto-run at L3 without confirm (see `docs/jarvis-permissions.md`)
- Audit rows in workspace `Memory/tool_audit.db`
- Tasks in `Memory/bridge_tasks.db`
- Do not expose this port on the public internet

## Tests (ORCH-244 / ORCH-314)

Loopback, token-gated pytest only. Remaining ORCH-314 cases live in
`tests/test_jarvis_bridge_orch244.py` (disabled/missing configured token → 403,
create→cancel, optional SSE smoke). Status/capabilities, wrong-token 401,
disk-task happy path, and confirm/ORCH-298/ORCH-301 stay in
`tests/test_jarvis_gateway_bridge.py`. Plan comment on
[ORCH-244](https://berk-claude.atlassian.net/browse/ORCH-244) (2026-08-11);
ticket [ORCH-314](https://berk-claude.atlassian.net/browse/ORCH-314).

## Threat model (summary)

| Threat | Mitigation |
|--------|------------|
| Local malware calls bridge | Token required; rotate token |
| Privilege escalation via tools | Tier gateway + path sandbox |
| Secret exfiltration in results | Redaction in audit/previews |
| Runaway agents | Rate limit + timeouts |
