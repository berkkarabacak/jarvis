# Jarvis — Desktop (Electron)

Native Windows app. The **primary window** is a three-pane Next.js shell
(`desktop-web/`, ElevenLabs UI Conversation) at
`http://127.0.0.1:<port>/desktop-ui` when the export exists. Fallback is
`app/static/desktop.html` at `/desktop`. Dark left rail, light chat, and
Live Computer on the right.

`/ceo` is **not** rewritten. It stays the Realtime / Settings page:

1. Starts local `uvicorn` from the repo
2. Cold start shows the 3-pane window (Assistants / chat / Live Computer)
3. A hidden talk engine still loads `/ceo` so avatar ask, mute, and
   Realtime keep working
4. Close the main window returns to the optional mini avatar. The avatar
   **×** (and tray **Quit Jarvis**) really quits. Mute on the avatar or
   tray stops Realtime output and neural TTS until unmuted. Never Windows SAPI.
5. **Settings** is Jarvis menu (`Ctrl+,`) or the gear on the left footer.
   That opens `/ceo?settings=1` in a Settings window. Model, voice,
   computer, and talk_mode / Computer vs Chat only stay on the same
   `/api/jarvis/settings` store. Settings tabs including talk_mode keep
   working.
6. **Middle pane** is the live You / Jarvis chat thread. Type + send
   posts `/api/jarvis/ask`. The thread loads `/api/jarvis/talk/last`.
   Mic starts listen (browser speech, and the hidden `/ceo` talk engine
   already used by Electron). Voice turns also land here.
7. **Jarvis's screen** is the live localhost noVNC session
   (`http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale`)
   **iframed** into the right pane (`#live-computer`). Hide / collapse
   and Chat only blank that iframe — they do **not** stop
   `jarvis-computer`. BrowserView is not used: it sits above the page
   and cannot collapse with the chrome. **Open Jarvis's screen** still
   opens the existing viewer window.
8. **Left lists** are Search, compose, Chat / Helpers / Plugins /
   Routines, Assistants, Recent chats, and View all chats. Each list
   section opens and closes on its own. Picking a helper or chat
   updates the middle header. Asks still go to Jarvis.
9. Helpers are **Jarvis** (live) plus documented stubs labeled
   **Not connected yet**. Chats come from local talk history
   (`/api/jarvis/talk/last`) when you have one. Group chats stay empty
   until a real group list exists. No invented live teammates.
10. **Routines** sit under Live Computer (Jarvis's screen). The list is
    `/api/jarvis/routines` (real local schedules). Empty says
    **No routines yet.** `+` / Create routine says **Adding a routine comes later.**
    No invented Morning briefing.
11. A **narrow window** (under 900px) hides the left and right panes
    by default. Use the edge arrows, or Hide chats / Hide computer.
    Chat stays in the middle.
12. Stops the backend on quit

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

# Next UI (one-time)
cd desktop-web
npm install

# Live reload: Next + Electron
npm run dev
# other terminal:
cd desktop
npm install
$env:JARVIS_DESKTOP_UI_URL = "http://127.0.0.1:3000"
npm start

# Or let Electron export + load /desktop-ui:
cd desktop
npm start
```

See [desktop-web/README.md](../desktop-web/README.md).

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

## Left list data

| List | Source | Honest empty / stub |
|------|--------|---------------------|
| Helpers / Assistants | Local lead + documented stubs | Only Jarvis is live. Writer / Helper / Finder say **Not connected yet** |
| Recent chats | `/api/jarvis/talk/last` | **No chats yet. Send a message to start.** |
| Group chats | None yet | **No group chats yet. They come later.** |
| Routines | `/api/jarvis/routines` (local JobStore) | **No routines yet.** Create routine is **Adding a routine comes later.** |

## Surfaces

| Surface | UI source |
|---------|-----------|
| This Electron app (main window) | Next `desktop-web` at `/desktop-ui` (HTML `/desktop` fallback) |
| Settings / hidden talk engine | server `app/static/ceo.html` at `/ceo` |
| https://aicontrolroom.nl/ceo | same `/ceo` orb Talk (web later) |

## File editing

Optional Prime Agent: set `PRIME_AGENT_*` in repo `.env` (see `docs/local-windows-app.md`).

## Windows / desktop smoke (#73)

Dev: from `desktop/`, `npm start` — 3-pane window, no key field.

Installer: `Jarvis-Setup.exe` — same chrome. Family path never asks for a key.

Checklist against the Windows mock:

1. Chat is in the middle. Type or use the mic.
2. Jarvis's screen (Live Computer) is the right pane. Routines sit under it (empty until a real schedule exists).
3. Helpers and chats are on the left. Hide chats / Hide computer collapse a side.
4. On a narrow window both sides start hidden. Use the edge arrows to show them.
5. Gear (or Jarvis → Settings) opens Settings. Model, voice, computer, and talk_mode persist. Computer vs Chat only still works.
6. Chat only and Hide screen blank the live PC. They do not stop the computer.

Mom blurb: Chat is in the middle. Jarvis's screen is on the right. Hide chats or Hide computer when you want more room. On a small window the sides hide — click the arrows at the edges.
