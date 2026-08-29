# Local Windows app (Option A) — ==GRoK==

Run **AI Control Room on your PC** as a desktop-style app: local backend + CEO window that can (optionally) edit files in a folder you choose.

The cloud site (`aicontrolroom.nl`) cannot see your Windows disk. This local pack can.

## What you get

| Piece | Behavior |
|-------|----------|
| Backend | FastAPI / uvicorn on `127.0.0.1:8787` |
| UI | CEO page in an Edge/Chrome **app window** (`--app=`) |
| Jarvis's screen | Menu **Open Jarvis's screen** opens the live localhost desktop (ORCH-410) |
| Chat brain | OpenRouter (`OPENROUTER_API_KEY`) by default |
| File edits | Optional **Prime Agent** RPC with `PRIME_AGENT_WORKDIR` |

```
[Desktop shortcut]
       │
       ▼
start-control-room.ps1 ──► uvicorn (local)
       │                        │
       └─ Edge --app=/ceo       ├─ OpenRouter  (talk)
                                └─ prime-agent (edit files, if enabled)
```

## One-click installer

For a family PC, build and send `Jarvis-Setup.exe` instead of this clone+venv path:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\build-installer.ps1
```

That bundle includes Python. First run is a key window. See [windows-installer.md](windows-installer.md)
and [START-HERE-WINDOWS.txt](START-HERE-WINDOWS.txt).

## Requirements (clone / zip path)

- Windows 10/11
- Python 3.10+ on `PATH` (`python --version`)
- OpenRouter API key (or another provider if you only use Prime)
- Optional: [Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent) for tool/file use

## Quick start

### A) Electron desktop app (recommended — real window, same UI)

```powershell
cd path\to\agent-orchestrator
powershell -ExecutionPolicy Bypass -File scripts\windows\start-control-room.ps1 -SetupOnly
# edit .env → set OPENROUTER_API_KEY
cd desktop
npm install
npm start
```

The window loads **the same** `/ceo` page as the website (no separate UI).

Build a portable/NSIS binary: `npm run dist` inside `desktop/` (see `desktop/README.md`).

### B) Script + Edge/Chrome app mode

From a clone of this repo:

```powershell
cd path\to\agent-orchestrator
powershell -ExecutionPolicy Bypass -File scripts\windows\start-control-room.ps1
```

First run:

1. Creates `.venv` and installs `requirements.txt`
2. Copies `deploy/local-windows.env.example` → `.env` and generates `API_SECRET` + `TOKEN_ENCRYPTION_KEY`
3. Starts the server and opens `http://127.0.0.1:8787/ceo`

**Before live chat works**, edit `.env` and set:

```env
OPENROUTER_API_KEY=sk-or-v1-...
```

Then restart the script.

### Desktop shortcut

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install-desktop-shortcut.ps1
```

Creates **AI Control Room** on your Desktop.

### Flags

```powershell
# Setup venv + .env only
.\scripts\windows\start-control-room.ps1 -SetupOnly

# Don't open a browser window
.\scripts\windows\start-control-room.ps1 -NoBrowser

# Enable Prime env vars (file editing path)
.\scripts\windows\start-control-room.ps1 -Prime

# Custom port
.\scripts\windows\start-control-room.ps1 -Port 8790
```

## Enable local file editing (Prime)

Prime runs **on this machine** and can modify files under a workdir you set. Treat that folder as the only place it may touch.

1. Install Prime Agent (see upstream docs). Prefer a user-local binary path on Windows, or run Prime under **WSL2** and point `PRIME_AGENT_BIN` at `wsl.exe` + a wrapper if a native Windows build is unavailable.
2. Create a dedicated workspace, e.g. `%USERPROFILE%\AI-Control-Room-Workspace`.
3. In `.env`:

```env
PRIME_AGENT_ENABLED=true
PRIME_AGENT_BIN=C:\path\to\prime-agent.exe
PRIME_AGENT_WORKDIR=C:\Users\YOU\AI-Control-Room-Workspace
# optional hard pin:
# EXECUTIVE_PRIME_ADAPTER=rpc
OPENROUTER_API_KEY=sk-or-v1-...
```

4. Start with:

```powershell
.\scripts\windows\start-control-room.ps1 -Prime
```

5. Confirm logs show `executive runtime adapter: prime-rpc` (not only `openrouter`).

### Safety rules

- **Never** set `PRIME_AGENT_WORKDIR` to `C:\` or your whole user profile.
- Keep `HOST=127.0.0.1` so the app is not reachable from the LAN.
- Do not reuse the public guest cloud deployment’s secrets on a Prime-enabled desktop without understanding risk.
- Review git diffs in the workspace after agent runs.

## OpenRouter vs Prime (local)

| Goal | Config |
|------|--------|
| Talk only (voice/text CEO) | `OPENROUTER_API_KEY` only, `PRIME_AGENT_ENABLED=false` |
| Talk + edit files | Prime enabled + `OPENROUTER_API_KEY` (Prime uses it as the model provider) |
| Prime without OpenRouter | Prime + `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / etc. (see Prime providers docs) |

You always need **some** LLM provider. OpenRouter is the default for this app’s in-process chat path.

## Cloud vs local

| | Cloud `aicontrolroom.nl` | Local Windows app |
|--|--------------------------|-------------------|
| Voice CEO UI | Yes | Yes (same `/ceo`) |
| Edit files on this PC | No | Yes (with Prime + workdir) |
| Always on | VM systemd | While the script/window is running |

They are complementary: cloud for remote access; local app for desktop + disk.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Browser opens but chat fails | Set `OPENROUTER_API_KEY` in `.env`, restart |
| `python` not found | Install Python 3.10+ and tick “Add to PATH” |
| Port in use | `-Port 8790` or change `PORT` in `.env` |
| Prime not found | Set full path in `PRIME_AGENT_BIN` |
| Want only setup | `-SetupOnly` then edit `.env` manually |

## Layout added by this pack

```
scripts/windows/
  start-control-room.ps1      # main launcher
  start-control-room.bat      # double-click entry
  install-desktop-shortcut.ps1
deploy/local-windows.env.example
docs/local-windows-app.md     # this file
```
