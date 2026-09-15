# Jarvis handover for the next AI model

**Owner:** Berk K. (berkly)  
**Repo:** https://github.com/berkkarabacak/jarvis  
**Date of handover:** 2026-09-14 (Europe/Istanbul)  
**Main SHA at handover:** `8cfb1cd934f03e87eaa867e3a80b1a0cf1f896e2` (merge of PR #90)  
**Live public Talk:** https://aicontrolroom.nl/ (GCP; separate from Windows shell)

This document is meant to be pasted or attached to another AI so it can continue without prior chat context. Do **not** invent secrets; never print API keys.

---

## 1. What Berk wants (product north star)

Jarvis is an app where you talk to **one lead AI** that manages other models/agents for you.

Berk’s **10 must-dos** (product spine epic **#75**):

1. One main assistant manages other AI models and agents  
2. Choose/switch lead and workers across providers (OpenAI, Grok, Kimi, …)  
3. Lead breaks requests into tasks, assigns workers, coordinates  
4. Shared task board: ownership, progress, blockers, done  
5. Agents exchange messages/findings (no manual relay)  
6. Schedule work, follow up on stalls, alert when attention needed  
7. Clear ownership + separate working areas; a review agent checks results  
8. Spending limits + usage tracking  
9. v1 targets software founders/small teams; **official APIs first**; consumer subs / browser automation are separate access methods  
10. Business: subscription for **coordination**; **AI usage billed separately**; win = measurable time saved  

**UI north star:** Windows app should look like the **Grok Bot desktop app** (3 panes):

| Pane | Contents |
|------|----------|
| Left (collapsible) | Search · Agents/Helpers · Chats · Group chats · Plugins/profile |
| Middle | Active chat · composer (+ / mic / send) |
| Right (collapsible) | Live computer · Routines |

Reference: Berk provided a Grok Bot screenshot (Buyra session) as the visual target.

---

## 2. Priority order (explicit)

1. **Windows Electron app first** (`desktop/`, installer `Jarvis-Setup.exe`)  
2. Public web Talk (`aicontrolroom.nl`) **later** for the new chrome (or share the same UI bundle)  
3. Product spine (#75) builds **on** the Windows shell  
4. OpenAI-compatible **provider** API (#49) is a parallel track (Jarvis as `base_url` + API key for Claude Code / OpenAI clients)

---

## 3. Done recently (do not redo)

### 3.1 Windows Grok Bot–like chrome — epic **#66 CLOSED**

Merged PRs on `main`:

| PR | What |
|----|------|
| [#86](https://github.com/berkkarabacak/jarvis/pull/86) | Electron primary window = `/desktop` 3-pane shell (not avatar-only as main UX) |
| [#87](https://github.com/berkkarabacak/jarvis/pull/87) | Right pane embeds live noVNC (`127.0.0.1:6080`); hide/Chat only blanks iframe; does **not** stop jarvis-computer |
| [#88](https://github.com/berkkarabacak/jarvis/pull/88) | Middle pane You/Jarvis chat: `/api/jarvis/ask`, history, mic bridge |
| [#89](https://github.com/berkkarabacak/jarvis/pull/89) | Left Helpers/Chats/Group chats; honest stubs; chats from talk history |
| [#90](https://github.com/berkkarabacak/jarvis/pull/90) | Routines under PC (`GET /api/jarvis/routines`); Settings gear; narrow collapse |

Closed issues: **#66–#74** (except any still open elsewhere — #66–#74 UI set closed).

**Key files:**

- `app/static/desktop.html` — 3-pane UI  
- `desktop/main.js`, `desktop/app-shell.js`, `desktop/preload.js` — Electron host  
- `tests/test_desktop_app_shell.py`, `desktop/app-shell.test.js`  
- Docs: `desktop/README.md`, `docs/local-windows-app.md`, `docs/windows-installer.md`, `docs/START-HERE-WINDOWS.txt`

**Behavior notes:**

- Cold start: main window loads **`/desktop`**. Hidden `/ceo` talk window still supports Realtime/avatar/mute.  
- Settings: gear → `/ceo?settings=1`  
- `talk_mode`: `computer` | `terminal` (UI often labels terminal as **Chat only**)  
- Helpers stubs: only **Jarvis** is live; Writer/Helper/Finder say **Not connected yet** — do not fake live teammates  

### 3.2 Talk Terminal mode + closable PC (web Talk) — mostly done

| PR | What |
|----|------|
| [#64](https://github.com/berkkarabacak/jarvis/pull/64) | Closable `#pc` + `talk_mode` setting (deployed live) |
| [#65](https://github.com/berkkarabacak/jarvis/pull/65) | Server enforcement via `app/jarvis/talk_mode.py` (deployed live) |

Still open: **#63** docs/smoke checklist; epic **#59** may still be open for docs wrap-up.

### 3.3 Other live Talk context (background)

- GPT-Live-1 / `openai_live` on aicontrolroom.nl  
- Default helper often DeepSeek V4.1 Flash via OpenRouter  
- `JARVIS_AGENTS_API=1` was enabled on live for research/coding child fan-out; screen/desktop stays local OpenRouter path  
- Long iterative work improved computer use (hotels, shopping, cookies, etc.) — still imperfect; “make computer actually reliable” remains ongoing  

---

## 4. Open work (pick up from here)

### A. Product spine (highest product value after UI chrome)

Epic: https://github.com/berkkarabacak/jarvis/issues/75  

Children:

| Issue | Topic |
|-------|--------|
| [#76](https://github.com/berkkarabacak/jarvis/issues/76) | One lead manages agents |
| [#77](https://github.com/berkkarabacak/jarvis/issues/77) | Switch lead/workers across providers |
| [#78](https://github.com/berkkarabacak/jarvis/issues/78) | Break down, assign, coordinate |
| [#79](https://github.com/berkkarabacak/jarvis/issues/79) | Shared task board |
| [#80](https://github.com/berkkarabacak/jarvis/issues/80) | Agent-to-agent exchange |
| [#81](https://github.com/berkkarabacak/jarvis/issues/81) | Schedule, stalls, alerts |
| [#82](https://github.com/berkkarabacak/jarvis/issues/82) | Ownership, workspaces, review agent |
| [#83](https://github.com/berkkarabacak/jarvis/issues/83) | Spend limits + usage UI |
| [#84](https://github.com/berkkarabacak/jarvis/issues/84) | Audience + official APIs first |
| [#85](https://github.com/berkkarabacak/jarvis/issues/85) | Coord subscription + separate usage billing |

Suggested build order: **#76 → #77 → #78 → #79** (board), then #80–#83, then #84–#85 packaging.

### B. OpenAI-compatible API (Jarvis as provider)

Epic: https://github.com/berkkarabacak/jarvis/issues/49  
Children **#50–#58** (auth, models, chat, stream, tools, images, errors, docs, tests).  
**No implementation yet** (plan-only). Goal: Claude Code / OpenAI SDK → `base_url` + Jarvis API key.

### C. Agents API integration

Issue **#26** still open; thin client + adapter existed behind flags; live had `JARVIS_AGENTS_API=1` at one point — verify current env before assuming.

### D. Polish / leftovers

- **#63** Terminal mode docs/smoke  
- Windows: real multi-agent Helpers (replace stubs) when product #76–#78 land  
- Routines `+` create flow still “comes later”  
- Computer-use reliability on live Talk (ongoing)  

---

## 5. How to run (Windows)

From repo docs (`desktop/README.md`):

```powershell
# one-time backend setup
powershell -ExecutionPolicy Bypass -File scripts\windows\start-control-room.ps1 -SetupOnly

cd desktop
npm install
npm start
```

Installer (family PC):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\build-installer.ps1
```

Output: `dist\Jarvis-Setup.exe`. Family users must **not** be asked for an API key in the UI. Operator keys live in env / hosted talk / private installer resources — never commit secrets.

Live computer viewer expects jarvis-computer / noVNC on `http://127.0.0.1:6080` when Computer mode is on.

---

## 6. Architecture cheat sheet

| Area | Location |
|------|----------|
| Public Talk / Realtime | `app/jarvis/realtime.py`, `voice_ask.py`, `public_routes.py`, `deploy/jarvis-public/` |
| Desktop UI | `app/static/desktop.html` + Electron `desktop/` |
| Settings / talk_mode | `app/jarvis/settings_store.py`, `settings_routes.py`, `talk_mode.py` |
| Computer / overlay | `app/jarvis/computer.py`, `virtual_pc.py`, `overlay.py`, `deploy/jarvis-computer/` |
| Children / Agents API | `app/jarvis/children.py`, `agents_api.py`, `agents_child.py` |
| LLM providers | `app/llm/` (OpenRouter, xAI) |
| Org API keys schema | `app/migrations/003_org_api_keys_audit.sql` (for future OpenAI-compat auth) |

GitHub user: **berkkarabacak**. Company/dev name: **berkly**. Main domain: **aicontrolroom.nl**.

---

## 7. Berk preferences (important)

- Short answers; simple English; little jargon  
- Do **not** surface ugly error dumps to him  
- Mom is a non-technical tester — UX must stay simple  
- Windows app is family-installable; no key prompts for end users  
- Prefer free/cheap workers for lifting when that playbook applies; don’t burn expensive tokens needlessly  
- He authorized managing `berkkarabacak/jarvis` (merge finished work, delete stale branches)  
- Examples (CNN, hotels, bol.com) are **benchmarks**, not allowlists — Jarvis should do any computer job  
- “Do not checkout” means don’t pay — not abort the cart job  

---

## 8. Suggested first tasks for the next model

1. Confirm `main` at/after `8cfb1cd` and skim `app/static/desktop.html` + `desktop/main.js`.  
2. Ask Berk whether next is **product spine #75** (board/workers) or **OpenAI-compat #49** or **Windows installer smoke on a real PC**.  
3. If product: start **#76/#78/#79** inside the Windows middle/left chrome (don’t rebuild the 3-pane shell).  
4. Keep Helpers stubs honest until real agents exist.  
5. Never commit keys; never claim BrowserView if iframe is the chosen live-PC path unless you intentionally change it.

---

## 9. Links quick list

- Repo: https://github.com/berkkarabacak/jarvis  
- Windows UI epic (done): https://github.com/berkkarabacak/jarvis/issues/66  
- Product spine (open): https://github.com/berkkarabacak/jarvis/issues/75  
- OpenAI-compat (open): https://github.com/berkkarabacak/jarvis/issues/49  
- Agents API: https://github.com/berkkarabacak/jarvis/issues/26  
- Live Talk: https://aicontrolroom.nl/  

---

*End of handover. Written for cold-start continuity; update this file when major epics close.*
