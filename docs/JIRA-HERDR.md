# Jira tickets — Herdr integration (ORCH)

**Project:** [ORCH](https://berk-claude.atlassian.net/browse/ORCH)  
**Create on:** https://berk-claude.atlassian.net  

Paste into Jira if REST create failed. Link stories under the epic.

---

## Epic — Herdr terminal agent runner

| Field | Value |
|--------|--------|
| **Type** | Epic |
| **Summary** | Herdr integration: optional terminal-agent job runner |
| **Description** | Add `runner=herdr` path so scheduled jobs can drive Herdr CLI agents (workspace → agent start → prompt → read). Keep default LLM/OpenRouter path. Document env, dashboard fields, smoke script, and optional plugin skeleton. |
| **Acceptance** | Jobs with runner=herdr execute via CLI; disabled/missing binary fails cleanly; status + settings endpoints; docs + tests; dashboard can create herdr jobs |
| **Labels** | `herdr`, `runner` |

---

## Stories

### 1 — Herdr CLI client wrapper

| Field | Value |
|--------|--------|
| **Summary** | Implement `app/integrations/herdr.py` async CLI client |
| **AC** | workspace create parses `.result.root_pane.pane_id`; agent start/prompt/wait/read match CLI 0.8; name sanitize; timeouts via `--timeout`; unit tests with mocks |

### 2 — Job schema + store fields

| Field | Value |
|--------|--------|
| **Summary** | Persist herdr_* columns on jobs + runner field |
| **AC** | DB migrate columns; create/update/list expose `job.herdr`; default runner=llm |

### 3 — JobRunner herdr path

| Field | Value |
|--------|--------|
| **Summary** | `_run_herdr_job` branch in JobRunner |
| **AC** | HERDR_ENABLED gate; full flow; memory/messages best-effort; run metadata `llm_provider=herdr` |

### 4 — Settings + status API

| Field | Value |
|--------|--------|
| **Summary** | GET/POST herdr settings + herdr block on `/api/status` |
| **AC** | `/api/settings/herdr`, `/test`; status includes enabled/available |

### 5 — Dashboard UI

| Field | Value |
|--------|--------|
| **Summary** | Runner select + herdr kind/cwd on task form |
| **AC** | Create/edit herdr jobs; list shows runner |

### 6 — Docs, sample job, plugin skeleton

| Field | Value |
|--------|--------|
| **Summary** | docs/herdr.md, README, sample script, plugin stub |
| **AC** | Operator can enable env and smoke-test without reading source |

---

## Out of scope (follow-ups)

- Full Herdr plugin marketplace publish
- Multi-pane fan-out / agent-to-agent graphs
- Windows-only path without Herdr server
