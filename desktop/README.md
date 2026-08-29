# AI Control Room — Desktop (Electron) ==GRoK==

Native Windows window that loads the **exact same** CEO UI as the web app
(`app/static/ceo.html` via `http://127.0.0.1:<port>/ceo`).

No duplicate frontend. The Electron shell only:

1. Starts local `uvicorn` from the repo
2. Cold start shows only the small always-on-top talking avatar
3. Expand on the avatar opens the full `/ceo` Talk window
4. Close or minimize Talk returns to the avatar. The avatar **×** (and
   taskbar /    tray **Quit Jarvis**) really quits. Mute on the avatar or
   tray stops Realtime output and neural TTS until unmuted. Never Windows SAPI.
5. Exposes **Settings** in the Jarvis menu (`Ctrl+,`) and as one top-right
   gear icon on Talk (`/ceo?settings=1`)
6. Opens **Jarvis's screen** (ORCH-410) — a viewer window for the live
   localhost noVNC desktop at `http://127.0.0.1:6080`
7. Stops the backend on quit

The mini avatar (ORCH-397 / ORCH-398) is a tiny draggable robot overlay, not a
second main window. Cold start is the circular avatar only — not the 248×172
talk bubble. Click opens a talk bubble, starts listening, and accepts a short
typed question. Replies show on the bubble. The expand control opens the full
Talk window. Close or minimize Talk returns to the avatar. The always-visible
× quits the app; the speaker icon mutes him. Jarvis stays on the Windows
taskbar and in the tray so Quit / Mute are a right-click away.

Settings (budget, speed, quality vs price) are the same `/api/jarvis/settings` contract as the web page.

## Run (dev)

From repo root (Python venv recommended first):

```powershell
# one-time backend setup
powershell -ExecutionPolicy Bypass -File scripts\windows\start-control-room.ps1 -SetupOnly

# Talk uses a local .env key if you already have one, otherwise
# JARVIS_OPERATOR_OPENROUTER_KEY or JARVIS_HOSTED_TALK_URL.
# Packaged users never see a key field.

cd desktop
npm install
npm start
```

## Operator talk key (Berk only)

Family users must not type a key. Berk sets one of:

1. The key on the hosted talk server (`https://aicontrolroom.nl/jarvis`, or `JARVIS_HOSTED_TALK_URL`; `https://berkkarabacak.com/jarvis` is an alias)
2. `JARVIS_OPERATOR_OPENROUTER_KEY` or `OPENROUTER_API_KEY` in the **private** installer build env on Odin — `build-installer.ps1` writes `operator.env` into extraResources. That file is gitignored. Do not commit it. Do not put a placeholder in source.

Users never see the secret. If talk cannot run, the app says "Can't talk right now".

## Build the one-click installer (Windows machine)

This is the family-PC path. It bundles Python and the app tree.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\build-installer.ps1
```

Output: `dist\Jarvis-Setup.exe`. First run opens Talk. No key window.  
See [docs/windows-installer.md](../docs/windows-installer.md).

## Build shell-only installer / portable exe

```powershell
cd desktop
npm install
npm run dist
```

Artifacts under `desktop/dist/`. This **shell-only** pack still needs the
**repo + `.venv`** nearby, or `CONTROL_ROOM_ROOT`. Prefer `build-installer.ps1`
when you want a real one-file install.

## Same UI guarantee

| Surface | UI source |
|---------|-----------|
| https://aicontrolroom.nl/ceo | server `app/static/ceo.html` |
| Local browser / Edge `--app` | same |
| This Electron app | same URL on loopback |

## File editing

Optional Prime Agent: set `PRIME_AGENT_*` in repo `.env` (see `docs/local-windows-app.md`).
