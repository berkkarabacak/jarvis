# ORCH-69 TencentDB Agent Memory adapter

This slice integrates the official TencentDB Agent Memory repository as an
optional secondary memory service. It is pinned to release `v2.0.0`, commit
`0aff21a2d9f2b8a0354aaa80a2e586aab4054562`, and uses the strict `/v3/core/*`
isolation API included in that release.

## Safety contract

- The local `SafeMemoryRepository` remains authoritative.
- Only items with explicit `approved` status can leave the application.
- Organization identifiers are converted to stable pseudonymous scope IDs.
- The adapter never accepts raw transcripts, prompts, private reasoning, tool
  input/output, credentials, browser/session data, code changes, or deployment
  instructions.
- Recalled entries are re-sanitized and must match the current local approved
  set byte-for-byte before a caller can consume them.
- Plain HTTP is accepted only on loopback; remote endpoints require HTTPS.
- The API key is environment-only and omitted from repr, health, status, and
  error output.

## Minimal demo path

Run Memory Core on loopback and provide these host environment variables (use
a generated value for the API key; never paste it into source or Jira):

```text
TENCENT_AGENT_MEMORY_ENABLED=true
TENCENT_AGENT_MEMORY_ENDPOINT=http://127.0.0.1:8420
TENCENT_AGENT_MEMORY_API_KEY=<host-managed secret>
TENCENT_AGENT_MEMORY_SERVICE_ID=ai-control-room-preview
```

The Memory Core process must set `V3_STRICT_ISOLATION=true` and
`TDAI_GATEWAY_API_KEY` to the same host-managed bearer value. Keep its gateway
bound to loopback for the preview; do not expose the panel, proxy, or memory
port through Nginx.

After an executive memory proposal is approved by an organization owner/admin:

```python
config = tencent_agent_memory_config_from_env()
gateway = TencentAgentMemoryGateway(config)
mirror = ApprovedMemoryMirror(safe_memory_repository, gateway)

await mirror.sync(org_id=org_id, actor=admin_context)
approved_context = await mirror.recall(
    org_id=org_id,
    actor=executive_context,
    limit=10,
)
```

If the service is unavailable, `recall()` raises the generic
`TencentAgentMemoryUnavailable` error. The application boundary must catch that
error and use `SafeMemoryRepository.list_approved_memory()` as its deterministic
local fallback; no vendor body or credential is returned. A stale remote
snapshot may contain only a subset of still-approved items, so callers should
also use the local approved set when completeness matters.

The adapter does not replace the database, Prime Agent, OpenRouter, or the
existing Grok scheduled-task behavior.
