# Jarvis MCP — GitHub + Slack (read-only) (ORCH-325)

First-class connectors for the **official** remote MCP servers, registered
through the existing Jarvis MCP registry / client / token store (ORCH-323).

## Endpoints

| Preset | Transport | URL | Default max tier |
|--------|-----------|-----|------------------|
| `github` | HTTP | `https://api.githubcopilot.com/mcp/readonly` | L2 (trusted) |
| `slack` | HTTP | `https://mcp.slack.com/mcp` | L2 (trusted) |

GitHub uses the official `/readonly` remote path so write tools are filtered
server-side. Slack scopes are restricted client-side to search/history/read
only — `chat:write` and other write scopes are rejected at registration.

## Register

Settings → Connectors → **Add GitHub (read-only)** / **Add Slack (read-only)**,
or:

```http
POST /api/jarvis/mcp/presets/github
{"token":"<pat-or-oauth>", "refresh": true}

POST /api/jarvis/mcp/presets/slack
{"token":"<xoxp-…>", "scopes": ["search:read.public", "channels:history", "..."]}
```

Catalog (no secrets):

```http
GET /api/jarvis/mcp/presets
```

Tokens are encrypted with `TOKEN_ENCRYPTION_KEY` / `mcp_tokens` and **never**
returned from Settings or connector APIs (`has_token` boolean only).
`granted_scopes` are stored as labels and shown read-only in Settings.

## Recommended scopes

### GitHub (classic PAT)

- `repo` (or `public_repo` for public-only)
- `read:org`
- `read:user`

Prefer a fine-grained PAT with read access to Contents, Pull requests, Issues,
and Metadata. Do not grant `workflow`, `delete_repo`, or admin scopes.

### Slack (user token)

Read/search/history only, for example:

- `search:read.public`, `search:read.private`, `search:read.im`, `search:read.mpim`
- `search:read.files`, `search:read.users`
- `channels:history`, `groups:history`, `im:history`, `mpim:history`
- `channels:read`, `groups:read`, `mpim:read`
- `users:read`, `users:read.email`, `emoji:read`, `canvases:read`, `files:read`

Rejected: `chat:write`, `canvases:write`, `reactions:write`, channel create/write
scopes, etc.

## Voice / prompt behaviour

Realtime + local agent instructions include a short MCP block so questions
like **"what's on my PRs"** / **"what did I miss in Slack"** prefer
`mcp.github.*` / `mcp.slack.*` tools and speak a brief summary.

Helpers (for tools or tests):

- `app.jarvis.mcp_presets.summarize_prs_for_voice`
- `app.jarvis.mcp_presets.summarize_slack_missed_for_voice`
- `app.jarvis.mcp_presets.preset_voice_instructions`

MCP tool **results** are untrusted external content (ORCH-324 taint). Until
that lands, `app.jarvis.taint` exposes `MCP_UNTRUSTED_PREFIX` /
`mcp_untrusted_tool_names()` hooks; gateway results also set
`untrusted_candidate: true`.

## Taint (ORCH-324)

MCP tool results are untrusted: `returns_untrusted("mcp…")` is true for every
`mcp.*` name after ORCH-324. Tests in `tests/test_jarvis_mcp_github_slack.py`
assert full taint behaviour when that landing is present, and still check the
prefix / registry hooks otherwise.
