# Jarvis local memory (SQLite) ==GRoK== (ORCH-255)

Desktop **source of truth**. No TencentDB on this path.

## Location

```
%USERPROFILE%\Documents\Jarvis\Memory\jarvis.db
%USERPROFILE%\Documents\Jarvis\Memory\summaries\*.md
%USERPROFILE%\Documents\Jarvis\Memory\backups\jarvis-*.db
%USERPROFILE%\Documents\Jarvis\Memory\tool_audit.db   # gateway audit (separate)
```

## Schema (v2)

| Table | Purpose |
|-------|---------|
| `meta` | `schema_version`, `pruned_at`, `created_at` |
| `facts` | Durable facts; soft-delete via `tombstoned_at` |
| `turns` | Per-session conversation turns |
| `mission_summaries` | End-of-mission digests (+ optional `prime_session_id`) |
| `tool_audit_idx` | Light index of notable tool events |

Existing v1 DBs migrate in place (`ALTER TABLE` adds columns).

## Env

| Var | Default | Meaning |
|-----|---------|---------|
| `JARVIS_MEMORY_RETENTION_DAYS` | `90` | Prune turns/summaries older than N days |
| `JARVIS_MEMORY_TZ` | `Europe/Berlin` | Local day boundaries for daily journals |

## API (`JarvisMemory`)

- `add_fact` / `search_facts` / `forget_fact` / `forget_matching`
- `find_fact_by_tag` / `upsert_fact_by_tag` / `turns_between` (ORCH-329)
- `add_turn` / `recent_turns` / `global_recent_turns`
- `add_mission_summary` / `recent_summaries` (also writes `summaries/*.md`)
- `context_blob(max_chars=1800)` â€” inject into Realtime / Prime (C2)
- `prune()` / `export_backup()`

## Consumers

1. **Realtime tools** â€” `remember` / `recall_memories` via ToolGateway  
2. **Session mint (C2)** â€” prepend `context_blob()` to instructions  
3. **Prime (B3)** â€” inject facts + last summaries on mission start; write summary on end

## Daily journals (ORCH-329)

Lightweight **day digests** (not full chat dumps), stored as facts:

| Piece | Detail |
|-------|--------|
| Key | `day:YYYY-MM-DD` tag plus `daily-journal` |
| TZ | `JARVIS_MEMORY_TZ` (default `Europe/Berlin`) |
| Content | topics, decisions, artifacts, open threads, `agents_created` (integer; 0 if none — field is never omitted) |
| Write | Rolling update after substantive Voice/agent/Bridge turns (`note_session_activity`); increment `agents_created` on successful `spawn_child`. Realtime gets journals via `context_blob` |
| Read | `recall_memories` with "yesterday" / "2 days ago" / `day:2026-08-12` / "last 6 days"; also injected in `context_blob`. Last-N recap returns stored days only (0 on empty stored days; does not invent missing days) |
| Privacy | Uses `sanitize_text` redaction; skips trivial hi/thanks sessions; no raw audio |

Module: `app/jarvis/daily_journal.py`. Explicit decisions may also auto-`remember` with tag `auto-decision`.

