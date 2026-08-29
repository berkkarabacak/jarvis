# Windows scripts

Two ways to put Jarvis on a PC:

| Path | Who it is for | Output |
|------|----------------|--------|
| `build-installer.ps1` | Family PC (one file) | `dist/Jarvis-Setup.exe` |
| `build-portable.ps1` | Advanced users | `dist/Jarvis-Windows-Portable-GRoK.zip` |

## One-click installer (preferred)

Run **on Windows** (Odin). Linux cannot build this exe.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\build-installer.ps1
```

Needs: Node.js + npm, network (downloads official embeddable CPython + pip).

What the script does:

1. Copies the app tree into `dist/installer-payload/backend`
2. Downloads official Windows embeddable Python and installs `requirements.txt` into it
3. Rewrites `python*._pth` via `embeddable_pth.py` so `../backend` is on `sys.path` (embeddable Python ignores `PYTHONPATH`)
4. Runs electron-builder NSIS (`desktop/electron-builder.installer.yml`)
5. Writes `dist/Jarvis-Setup.exe`

Optional signing on Odin:

```powershell
$env:JARVIS_SIGN_CERT = "Your certificate subject"
powershell -ExecutionPolicy Bypass -File scripts\windows\build-installer.ps1
```

Do not commit the exe.

The installed app lives in `%LOCALAPPDATA%\Jarvis`. Settings go to `%APPDATA%\Jarvis`. The user workspace is `%USERPROFILE%\Documents\Jarvis` (no folder picker).

First run opens Talk. Users never paste a key. Berk sets `JARVIS_OPERATOR_OPENROUTER_KEY` or `JARVIS_HOSTED_TALK_URL` in the private build env (writes `operator.env` into the payload) or on the hosted server. `API_SECRET` and `TOKEN_ENCRYPTION_KEY` are generated in the background.

After Jarvis opens, **Settings** is in the Jarvis menu and as one top-right gear icon on the Talk page. Budget, speed, and quality vs price use the same `/api/jarvis/settings` store as the web page.

## Portable zip (unchanged)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\build-portable.ps1
```

Still requires the user to install Python and run `RUN-JARVIS.bat`.

## Dev launchers

- `start-control-room.ps1` — venv + uvicorn + Edge app window
- `install-desktop-shortcut.ps1` — Desktop shortcut to that script
