# Jarvis desktop UI (Next.js + ElevenLabs UI)

Windows product chrome for the Electron app. Middle pane is
[ElevenLabs UI Conversation](https://ui.elevenlabs.io/docs/components/conversation)
wired to existing Jarvis APIs (`POST /api/jarvis/ask`, `GET /api/jarvis/talk/last`).
Left and right panes match the designer mock. Voice brain stays on Jarvis
(`/ceo` talk engine). This is not the ElevenLabs Agents SDK.

Vanilla `app/static/desktop.html` at `/desktop` stays as a fallback.

## Layout

| Pane | Role |
|------|------|
| Left (`#1A1D23`) | Search, Chat / Helpers / Plugins / Routines, Assistants (only Jarvis live), recent chats |
| Middle (`#F8F9FB`) | ElevenLabs Conversation + Message / Orb / Response. Type + send → `/api/jarvis/ask` |
| Right | Live Computer (noVNC iframe) + Routines. Computer / Chat only. Hide blanks the iframe and does **not** stop `jarvis-computer` |

## Run (dev)

Need the FastAPI backend on `127.0.0.1:8787` (same as today).

```powershell
# repo root — backend
powershell -ExecutionPolicy Bypass -File scripts\windows\start-control-room.ps1 -SetupOnly
# then start uvicorn, or just use Electron which starts it

# Next UI with live reload
cd desktop-web
npm install
npm run dev
```

In another terminal, point Electron at the Next dev server:

```powershell
cd desktop
$env:JARVIS_DESKTOP_UI_URL = "http://127.0.0.1:3000"
npm start
```

Next rewrites `/api/*` and `/ceo` to `http://127.0.0.1:8787` so asks stay same-origin from the browser’s point of view.

## Run (Electron loads the export)

`desktop` `npm start` builds `desktop-web/out` if it is missing, then opens
`http://127.0.0.1:<port>/desktop-ui` when that export exists. Otherwise it
loads the HTML `/desktop` shell.

```powershell
cd desktop-web
npm install
npm run export

cd ..\desktop
npm start
```

## Scripts

| Script | What it does |
|--------|----------------|
| `npm run dev` | Next dev server on port 3000 |
| `npm run build` | Next production build (no static export) |
| `npm run export` | Static export with `basePath=/desktop-ui` → `out/` |
| `npm test` | Helper contract tests |

## Installer

`scripts/windows/build-installer.ps1` runs `npm run export` and copies `out/`
into the packaged backend at `app/static/desktop-ui`. Family no-key path is
unchanged.

## Tests

```powershell
cd desktop-web
npm test
```

From repo root: `pytest tests/test_desktop_web.py tests/test_desktop_app_shell.py -q`
