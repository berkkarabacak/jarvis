# Executive approved-memory preview

This integration keeps the existing SQLite application database authoritative and
uses Tencent Agent Memory only as an optional approved-memory mirror. It is off by
default and adds no database tables, prompt context, response fields, or network
calls while disabled.

## Preview boundary

- Capture is limited to an authenticated CEO request whose trimmed text is exactly
  `/remember <safe text>`.
- The command proposes and immediately owner-approves one safe item locally before
  any mirror attempt. Repeating the same safe command is idempotent.
- Normal chat, transcripts, prompts, tool input/output, private reasoning, code,
  commands, deployment actions, credentials, browser/session data, and paths are
  never captured automatically. Unsafe artifacts are rejected; incidental secrets
  and paths are deterministically redacted before persistence.
- Later turns receive a bounded, delimited set of locally approved items as
  background context only. Remote content cannot add, reorder, or remove prompt
  context.
- Tencent write/read failure never blocks local approval or executive chat. Health
  and turn responses expose only `ready`, `fallback`, or `disabled`; they never
  expose endpoints, keys, upstream errors, or stored text.

This is explicitly a single-tenant preview. Authentication remains the existing
application API secret, and the bridge always uses its host-configured owner actor;
requests cannot select an organization, user, or role. The default IDs are:

- organization: `00000000-0000-4000-8000-000000000001`
- user: `00000000-0000-4000-8000-000000000071`

They may be replaced with deployment-specific UUIDs, but this does not claim
multi-tenant identity support.

## Module-local environment

Enable the local preview with:

```text
EXECUTIVE_MEMORY_PREVIEW_ENABLED=true
EXECUTIVE_MEMORY_PREVIEW_ORG_ID=<uuid>       # optional
EXECUTIVE_MEMORY_PREVIEW_USER_ID=<uuid>      # optional
```

The optional Tencent mirror reuses the existing pinned adapter variables:

```text
TENCENT_AGENT_MEMORY_ENABLED=true
TENCENT_AGENT_MEMORY_ENDPOINT=<https base URL>
TENCENT_AGENT_MEMORY_API_KEY=<host secret>
TENCENT_AGENT_MEMORY_SERVICE_ID=<opaque service id>
TENCENT_AGENT_MEMORY_TIMEOUT_SECONDS=5       # optional
```

Secrets must remain in the host secret environment. Do not place them in source,
Jira, logs, browser automation, or Nginx configuration. This slice adds no public
route and requires no Nginx change; it uses the existing authenticated executive
message and runtime-health routes.

## Demo

1. Start an executive mission through the existing authenticated API/UI.
2. Send `/remember Prefer concise executive summaries.`
3. Confirm the safe acknowledgement says local approved memory is active and the
   turn publishes executive-message, local evidence, and confidence events.
4. Send a normal question. The executive runtime supplies only the bounded local
   approved context to Prime Agent.
5. Stop Tencent Agent Memory and repeat steps 2-4. Local save and recall continue,
   while the safe status reports `fallback`.
