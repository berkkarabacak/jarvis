# Jarvis permission tiers ==GRoK== (ORCH-245 / ORCH-247)

| Tier | Name | Examples | Default personal auto |
|------|------|----------|------------------------|
| L0 | Read facts | get_disk_space, list_github_repos, system_info, recall_memories, confirm_action | Yes |
| L1 | Workspace R/W | list/read/write workspace, excel, screenshot, remember | Yes |
| L2 | User folders | home_list/read/write Desktop/Documents/Downloads | Yes |
| L3 | Apps / shell | run_powershell, run_app, open_path | Confirm unless allowlisted / power profile |
| L4 | UI automation | (future) | Confirm |
| L5 | Destructive | unknown tools / blocked patterns | Deny |

## Profiles

| Profile | Max auto tier |
|---------|----------------|
| locked | L0 |
| personal | L2 |
| power | L3 |

Env: `JARVIS_PERMISSION_PROFILE=personal`  
Bridge: `BRIDGE_MAX_TIER_AUTO=L1`

All execution paths (Realtime tools, Jarvis agent, Bridge) must call `ToolGateway.run`.

## A3 confirm protocol (ORCH-247)

When a tool exceeds the auto max tier:

1. Gateway returns `needs_confirm: true` with `confirm_id`, `action_summary`, `user_prompt`.
2. Voice/agent reads `user_prompt` and waits.
3. User says confirm/yes → call `confirm_action` (or `POST /api/jarvis/tools/confirm`).
4. User says cancel/no → same with `decision=cancel`.
5. Bridge: task status `needs_confirm`; caller `POST /api/bridge/v1/tasks/{id}/confirm`.
6. Approve wait (ORCH-411): the Allow prompt shows a countdown (default **10 seconds**, set in Settings). If nobody taps, Jarvis accepts and continues. Allow or Cancel before then wins. Bridge and child tasks use the same wait so they do not sit forever when no screen is up. Env fallback: `JARVIS_APPROVE_COUNTDOWN_SEC`.

### App allowlist (auto L3 without confirm)

Default basenames: notepad, calc, explorer, code, excel, winword, msedge, chrome, firefox, mspaint, wt, …

- Env CSV: `JARVIS_APP_ALLOWLIST=spotify,slack`
- Optional JSON file: `JARVIS_APP_ALLOWLIST_FILE`
- URLs (`http://` / `https://`) are allowlisted for `run_app`
- Hard-blocked patterns (format, diskpart, encoded powershell, shutdown, …) always deny

### Endpoints

| Path | Purpose |
|------|---------|
| `POST /api/jarvis/tools/run` | Run tool (Realtime client) |
| `POST /api/jarvis/tools/confirm` | Approve/deny pending |
| `GET /api/jarvis/tools/pending` | List pending confirms |

## Settings surface (ORCH-322 / ORCH-380)

Durable overrides live in `{JARVIS_WORKSPACE}/Memory/jarvis_settings.json`
(see `app.jarvis.settings_store`). This is the **one** shared config object
web, Windows, and Android read. They override env for permission profile,
provider/model, look-speed, Fast/Balanced/Smart, spend caps, and approve wait
(seconds). API keys
are never stored there. The optional model-lock PIN is stored hashed.

| Path | Purpose |
|------|---------|
| `GET /api/jarvis/settings` | Read settings + secret configured flags (no secret values) |
| `PUT /api/jarvis/settings` | Persist overrides; audits profile/model changes |
| `GET /api/jarvis/audit/recent?n=20` | Tail of `AuditLog` |
| `POST /api/jarvis/audit/verify` | Tamper check (`verify_across_rotation` / `verify`) |

User-facing controls: spending limit (monthly + daily, with spend so far),
how Jarvis thinks (Fast / Balanced / Smart), how often I look at the screen
(Off / 30s / 10s / 1s — separate from Fast/Balanced/Smart), approve wait
(seconds; default 10; Allow happens on its own when the timer hits zero),
always-use-the-same-model
lock + optional PIN, permission profile, connectors, and an Advanced section
for provider/model/voice/keys.

Profiles in the UI show plain-language “what this allows” blurbs for
locked / personal / power. Connectors section is an empty state (“None yet”).

