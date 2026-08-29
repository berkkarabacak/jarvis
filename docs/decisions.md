# Decisions

## D-001 — Rename to Agent Orchestrator (ORCH-28)

**Decision:** Product name is Agent Orchestrator; public path `/agent-orchestrator/`; keep temporary redirects from `/grok-automater/`.

**Why:** Scope is multi-provider agents, not Grok-only. Jira project was already ORCH / Agent Orchestrator.

## D-002 — OpenRouter as default LLM (ORCH-31)

**Decision:** Default `LLM_PROVIDER=openrouter` with Auto Beta model id `openrouter/auto`.

**Why:** One API key unlocks many models; auto routing matches product requirement. xAI remains optional adapter.

## D-003 — LlmProvider interface (ORCH-30)

**Decision:** `JobRunner` depends only on `LlmProvider`; xAI OAuth stays behind `TokenProvider` used only by `XaiLlmProvider`.

**Why:** Decouples runner from vendor auth. Future providers (Anthropic direct, Azure, etc.) plug in without runner changes.

## D-004 — SQLite first, TencentDB next (ORCH-35/36)

**Decision:** Keep SQLite as working store; introduce repository boundary before TencentDB MySQL.

**Why:** Ship OpenRouter + rename without blocking on cloud DB credentials. Migration is ORCH-43.

## D-005 — Settings PUT is process-local (ORCH-32)

**Decision:** `/api/settings/llm` mutates in-memory `Settings` + rebuilds provider; document that `.env` is durable source of truth.

**Why:** Avoid writing secrets to disk from the web process without a proper secrets vault. Host env remains authoritative for production.

## D-006 — Prime Agent (RPC) as specialist runtime (ORCH-58 / ORCH-69)

**Decision:** Adopt [PrimeIntellect-ai/prime-agent](https://github.com/PrimeIntellect-ai/prime-agent) (MIT) as the headless agent execution runtime for AI Control Room. The FastAPI **control plane** drives it via `prime-agent --mode rpc` (JSONL over stdin/stdout). We do **not** build our own agent loop, tool-calling layer, or subagent runtime.

**Supplies:** executive root session, dynamic specialist children (`rlm`), agent-to-agent messaging, session cost/token stats, per-session model selection (OpenRouter first-class), lifecycle controls, and a `tool_call` extension hook the control plane can use to **block** tools.

**Does not supply (stays ours):** security sandboxing, multi-tenancy/authz, authoritative budget/deadline enforcement, audit log, artifact storage, semantic retrieval, CEO UI.

**Constraints:** Node ≥ 22.8 alongside Python; pin an exact prime-agent release; RPC framing is strict JSONL LF-only (Python clients split on `\n` only).

**Rejected alternative:** Build an in-house agent loop.

## D-007 — PostgreSQL + pgvector supersedes TencentDB MySQL (ORCH-69)

**Decision:** **PostgreSQL + pgvector** is the durable store for Control Room state (orgs, missions, memory metadata, audit, artifacts refs, events). **SQLite** remains the local-dev and default runtime provider until repositories cut over. The **MySQL / TencentDB-MySQL** provider (`app/persistence/mysql_provider.py`) is **frozen legacy** for the existing scheduler path and is **not** extended with mission/agent/tenancy tables.

**Supersedes:** D-004’s “TencentDB MySQL next” target for new Control Room work.

**Provider selection:** `DATABASE_PROVIDER=sqlite|postgres|tencentdb` (`tencentdb` = MySQL legacy).

**Postgres env:** `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DATABASE`, `POSTGRES_SSL_MODE`.

**Migrations:** plain SQL files under `app/migrations/` applied via `app/persistence/migrate.py` + `schema_migrations` table (not ad-hoc `CREATE TABLE` growth in `app/db.py` for new Control Room tables).

**pgvector:** verify on target TencentDB PostgreSQL (or compatible). If unavailable, set `POSTGRES_PGVECTOR_REQUIRED=false` and use non-vector retrieval until an approved fallback is chosen; do not block tenancy/auth schema on vector.

**Driver:** `asyncpg` (optional dependency until Postgres is the active app store).

## D-008 — Executive handoff, confidence, and memory-scope contracts (ORCH-71)

**Decision:** Land pure-Python contracts in `app/executive/` before Prime RPC wiring:

- Structured `HandoffPacket` JSON only (schema_version=1); freeform prose handoffs rejected.
- Mission confidence is evidence-weighted 0–100 with bounded unresolved-risk penalty; `reached` iff `score >= target`.
- Memory scopes: `run` | `specialist` | `team` | `company` plus legacy `shared` | `private`. Role names remain free text (no allowlist).

**Why:** ORCH-71 success criteria require auditable handoffs and explained confidence. Contracts are low-conflict and usable by control-plane persistence and CEO UI once ORCH-69/70 land. D-006/D-007 reserved for Prime Agent RPC and Postgres+pgvector ADRs (ORCH-59/60).

**Rejected:** Encoding handoffs as markdown blobs; hard-coded specialist role enums.

## D-009 — Executive session boundary without Prime wiring (ORCH-71)

**Decision:** Add a dependency-light `ExecutiveSession` runtime over the D-008 contracts:

- `HandoffStore` protocol + `InMemoryHandoffStore` for scoped handoff persistence (mission/session/memory_scope/seq).
- Session owns evidence list, unresolved risks, free-text specialists, and `confidence()` aggregation via `score_mission_confidence`.
- Explicit snapshot marker: `runtime.prime_agent=false`, `runtime.llm_provider=null` until control plane + Prime RPC land.
- Illegal session transitions raise; terminal states reject further handoffs/evidence.

**Why:** ORCH-71 needs a usable executive boundary for tests and later CP/CEO integration without hard-wiring Prime Agent or provider credentials (blocked on ORCH-69/70).

**Rejected:** Calling OpenRouter/Prime from `app/executive/`; embedding API keys in session state.

## D-010 — SQLite handoff durability + executive HTTP surface (ORCH-71)

**Decision:**

- `SqliteHandoffStore` persists handoffs in `executive_handoffs` (mission_id, session_id, memory_scope, seq, packet_json).
- `ExecutiveSessionRegistry` tracks live sessions in-process; API under `/api/executive/*` (API-secret protected).
- Handoff `memory_updates` land in a session-scoped memory buffer (not company durable memory) until control-plane review path exists.

**Why:** Operators and CEO UI (ORCH-72) need a callable boundary before Prime RPC. SQLite matches current app data path; Postgres cutover follows ORCH-69/70.

**Rejected:** Writing handoff memory_updates straight into legacy `memories` shared/private tables without review.

## D-011 — Prime Agent + OpenRouter behind adapters (ORCH-71)

**Decision:**

- `PrimeAgentRuntime` port with default `NullPrimeAgent` (no binary/RPC).
- `ModelRouter` port with `HeuristicModelRouter` (plan-only) and `NullModelRouter`.
- `ExecutiveRuntime` composes session registry + adapters; HTTP under `/api/executive/runtime/*`.
- No unmerged-branch imports; no live OpenRouter keys required for executive path.

**Why:** ORCH-71 must progress without waiting for ORCH-69/70 merge or Prime pin. Live adapters plug in later without rewriting session/handoff contracts.

**Rejected:** Importing Prime SDK or calling OpenRouter from `session.py` / handoff store.

## D-012 — One cheap persistent Linux computer for Jarvis (ORCH-401)

**Decision:** Jarvis owns **one** Linux desktop container (`deploy/jarvis-computer/`), not a Windows VM and not one box per sub-agent. Debian + Xvfb + a small XFCE session, `restart: unless-stopped`, named volume `jarvis-computer-home` at `/home/jarvis`. Compose/Dockerfile only — no custom orchestrator.

**Why:** Product (Berk, 2026-08-16) wants a cheap machine that stays up so files, apps, and logins persist across jobs. Linux is cheaper than Windows. The user's Windows/Android app (ORCH-381) is a different computer.

**Deferred:** Chrome/notepad (ORCH-403, now landed), user watch (ORCH-404, now landed), see-and-click wiring (ORCH-405, now landed), live notepad proof (ORCH-406, now landed as a proof script).

**Rejected:** Windows VM; webtop/Kasm/noVNC in this slice; a per-child container fleet.

## D-013 — Windows-like XFCE theme on Jarvis's Linux computer (ORCH-402)

**Decision:** Theme the existing `jarvis-computer` Debian + XFCE image with a small checked-in theme pack (`deploy/jarvis-computer/theme/`, installed as `JarvisWin`). Bottom xfce4-panel taskbar, applications-menu Start button, xfwm/GTK navy-and-silver chrome, Windows-like icons, teal wallpaper. Same container, same volume `jarvis-computer-home`. Applied on first start (and once on an ORCH-401 home via `.jarvis-windows-theme-ready`).

**Why:** Product (Berk, 2026-08-16) wants cheap Linux underneath and a familiar Windows look on top. Do not ship a raw Linux desktop as v1. A custom XFCE pack is enough; Chicago95-scale extras (sounds, Plymouth, KDE) are not required.

**Deferred:** Chrome/notepad (ORCH-403, now landed), noVNC/user watch (ORCH-404, now landed), see-and-click (ORCH-405, now landed), live notepad proof (ORCH-406, now landed as a proof script).

**Rejected:** Replacing the box with a Windows VM; Kasm/webtop; adding Chrome, noVNC, or published ports in this slice.

## D-014 — Debian Chromium and basic utilities in the image (ORCH-403)

**Decision:** Install cheap Debian bookworm packages in `jarvis-computer`: `chromium` (not Google Chrome's extra apt repo), `mousepad`, `thunar`, `xfce4-terminal`, `galculator`, `ristretto`. A small `chrome` wrapper execs Chromium. Desktop / Start-menu `.desktop` files make them findable. Same container, same volume `jarvis-computer-home`. Entrypoint seeds shortcuts; it does not launch the apps.

**Why:** Product (Berk, 2026-08-16) wants Chrome, notepad, and the usual utilities in the image so Jarvis can open them without installing first. Debian Chromium avoids a huge extra repo. Google Chrome's repo is more expensive and more brittle.

**Deferred:** noVNC/user watch (ORCH-404, now landed), see-and-click (ORCH-405, now landed), live notepad proof (ORCH-406, now landed as a proof script).

**Rejected:** Google Chrome apt repo; launching apps from the entrypoint; replacing Linux with a Windows VM.

## D-015 — Localhost noVNC of Jarvis's one desktop (ORCH-404)

**Decision:** Attach `x11vnc` to the existing Xvfb `DISPLAY=:1` and serve Debian `novnc` + `websockify` on container port 6080. Compose publishes **`127.0.0.1:6080:6080` only** (http://127.0.0.1:6080). Same container, same volume, same XFCE session — a live view the user can type and click on, not a recording and not a second machine.

**Why:** Product (Berk, 2026-08-16) wants to open Jarvis's computer the way you open a Grok Bot computer. noVNC is cheap. Binding the host port to localhost keeps the desktop off the LAN. x11vnc reuses the display we already run; TigerVNC's own X server or a Kasm/webtop stack would be a second desktop or a heavier image.

**Deferred:** see-and-click wiring (ORCH-405, now landed), live notepad proof (ORCH-406, now landed as a proof script).

**Rejected:** Kasm/webtop; a Windows VM; publishing `0.0.0.0`; wiring `see_screen` / click to this container in this slice.

## D-016 — Jarvis drives his one Linux computer (ORCH-405)

**Decision:** Add a desktop backend switch (`windows` vs `jarvis-computer`) in `app/jarvis/computer.py`. When a job targets Jarvis's machine (explicit `computer=`, `JARVIS_DESKTOP_BACKEND`, goal text, or an inherited child pin), `see_screen` / `screenshot` / `click` / `type` / `keys` / `scroll` / `focus_app` / `run_app` `docker exec` into the existing `jarvis-computer` container with `DISPLAY=:1` (scrot + xdotool). The Windows see-and-click path (ORCH-365) stays. Children inherit the parent backend and do not spawn containers. No extra compose service. No extra published ports.

**Why:** Product (Berk, 2026-08-16) wants Jarvis to do computer work on *his* Linux desktop, with helpers working through him on that same box. A second container or a live notepad demo belongs to later tickets.

**Deferred:** live "open notepad and write X" proof (ORCH-406, now landed as a proof script).

**Rejected:** one container per child; deleting the Windows path; publishing another port; inventing a live screenshot.

## D-017 — Live notepad proof on Jarvis's computer (ORCH-406)

**Decision:** Add `scripts/proof_jarvis_computer_notepad.py`. It pins `JARVIS_DESKTOP_BACKEND=jarvis-computer`, opens notepad (mousepad) on the existing container via the ORCH-405 helpers, types a unique string that includes the date and ORCH-406, saves the buffer, reads the file back, and writes a `DISPLAY=:1` screenshot only when scrot returns a real PNG. If the container is down it exits and **refuses to invent a screenshot**. One container. No extra ports. Windows see-and-click stays.

**Why:** Product (Berk, 2026-08-16) wants one real "open notepad and write X" task, with the user able to open http://127.0.0.1:6080 and see the same text. A fake PNG would close the ticket without proof.

**Deferred:** on-demand Grok-style viewer (ORCH-410, now landed).

**Rejected:** inventing a live screenshot; a second computer; extra published ports.

## D-018 — Open Jarvis's screen on demand (ORCH-410)

**Decision:** Add an **Open Jarvis's screen** control on the Jarvis Windows app menu and the CEO gear menu. It opens a real viewer window titled **Jarvis's screen** that embeds the existing localhost noVNC session (`http://127.0.0.1:6080`). If that session is down, the viewer says so in plain English and starts the one existing computer: `docker compose up -d` when compose works, otherwise `docker start jarvis-computer` or `docker run` of `jarvis-computer:local` with the same localhost:6080 and `jarvis-computer-home` flags. No second desktop. No public bind. No invented screenshot.

**Why:** Product (Berk, 2026-08-17) wants to open Jarvis's live desktop the way you open a Grok Bot computer — on demand, not only a URL to remember.

**Deferred:** none in this computer stack.

**Rejected:** a second desktop; publishing `0.0.0.0`; a fake screenshot; changing Windows click/type routing.
