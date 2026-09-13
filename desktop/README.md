# Jarvis — Desktop (Electron)

Native Windows app. The **primary window** is a Grok Bot–like three-pane
shell (`app/static/desktop.html` via `http://127.0.0.1:<port>/desktop`).

`/ceo` is **not** rewritten. It stays the Realtime / Settings page:

1. Starts local `uvicorn` from the repo
2. Cold start shows the 3-pane window (Helpers / chat / Jarvis's screen)
3. A hidden talk engine still loads `/ceo` so avatar ask, mute, and
   Realtime keep working
4. Close the main window returns to the optional mini avatar. The avatar
   **×** (and tray **Quit Jarvis**) really quits. Mute on the avatar or
   tray stops Realtime output and neural TTS until unmuted. Never Windows SAPI.
5. **Settings** is Jarvis menu (`Ctrl+,`) or the gear on the 3-pane header.
   That opens `/ceo?settings=1` in a Settings window (talk_mode /
   Computer vs Chat only stay on the same `/api/jarvis/settings` store)
6. **Jarvis's screen** is the live localhost noVNC session
   (`http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale`)
   **iframed** into the right pane (`#live-computer`). Hide / collapse
   and Chat only blank that iframe — they do **not** stop
   `jarvis-computer`. BrowserView is not used: it sits above the page
   and cannot collapse with the chrome. **Open Jarvis's screen** still
   opens the existing viewer window.
7. Stops the backend on quit

Why a new `/desktop` route: `/ceo` is the orb Talk surface used by
existing voice tests and Settings. Rewriting it in place would mix two
layouts. The 3-pane chrome is the Windows product window; `/ceo` remains
the talk engine.

The mini avatar is an optional always-on-top helper, not the main
product surface. Click opens a talk bubble. Expand opens the 3-pane
window. Jarvis stays on the Windows taskbar and in the tray so Quit /
Mute are a right-click away.

Family installer path never asks for a key.

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

1. The key on the hosted talk server (`https://aicontrolroom.nl`, or `JARVIS_HOSTED_TALK_URL`; `https://berkkarabacak.com/jarvis` is an alias)
2. `JARVIS_OPERATOR_OPENROUTER_KEY` or `OPENROUTER_API_KEY` in the **private** installer build env on Odin — `build-installer.ps1` writes `operator.env` into extraResources. That file is gitignored. Do not commit it. Do not put a placeholder in source.

Users never see the secret. If talk cannot run, the app says "Can't talk right now".

## Build the one-click installer (Windows machine)

This is the family-PC path. It bundles Python and the app tree.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\build-installer.ps1
```

Output: `dist\Jarvis-Setup.exe`. First run opens the 3-pane window. No key window.
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

## Surfaces

| Surface | UI source |
|---------|-----------|
| This Electron app (main window) | server `app/static/desktop.html` at `/desktop` |
| Settings / hidden talk engine | server `app/static/ceo.html` at `/ceo` |
| https://aicontrolroom.nl/ceo | same `/ceo` orb Talk (web later) |

## File editing

Optional Prime Agent: set `PRIME_AGENT_*` in repo `.env` (see `docs/local-windows-app.md`).
