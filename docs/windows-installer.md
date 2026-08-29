# Jarvis Windows installer

One `.exe` for a non-technical user. Built on a Windows machine. Not produced by Linux CI.

## What the user does

See [START-HERE-WINDOWS.txt](START-HERE-WINDOWS.txt).

1. Download `Jarvis-Setup.exe`
2. Double-click
3. Jarvis opens Talk. Free talks now.
4. Click the **gear icon** (the one top-right control, or Jarvis → Settings) to pick a plan (Free / $3 / $8), budget, speed, and quality vs price. Those choices persist in `Documents\Jarvis\Memory\jarvis_settings.json` — the same store as the web Settings page.

Workspace is always `%USERPROFILE%\Documents\Jarvis`. The installer does not ask for a folder.

## What the builder does (Odin)

```powershell
git checkout dev
powershell -ExecutionPolicy Bypass -File scripts\windows\build-installer.ps1
```

Artifact: `dist\Jarvis-Setup.exe`

Upload that file as the public Download button. Keep the portable zip as an advanced link only.

Details and signing: [scripts/windows/README.md](../scripts/windows/README.md).

## Layout after install

| Place | Role |
|-------|------|
| `%LOCALAPPDATA%\Jarvis` | App + bundled Python + backend |
| `%LOCALAPPDATA%\Jarvis\resources\python` | Embeddable CPython (`python*._pth` includes `../backend`) |
| `%LOCALAPPDATA%\Jarvis\resources\backend` | Packaged `app` tree (`app/first_run_env.py`, uvicorn) |
| `%APPDATA%\Jarvis\.env` | Secrets (key + generated `API_SECRET` / `TOKEN_ENCRYPTION_KEY`) |
| `%APPDATA%\Jarvis\data` | Local SQLite |
| `%USERPROFILE%\Documents\Jarvis` | User workspace |

Upgrades replace the app folder. They do not wipe `%APPDATA%\Jarvis` or Documents.

## First-run (no user key)

`app/first_run_env.py` writes `.env` (workspace + generated `API_SECRET` / `TOKEN_ENCRYPTION_KEY`). Electron runs that file by path (not `-m app.first_run_env`) so embeddable CPython can start even though a `._pth` file ignores `PYTHONPATH`. The same `._pth` lists `../backend` so `uvicorn app.main:app` still resolves.

Packaged start **skips** any key window. Berk sets the talk secret on the hosted server (`JARVIS_HOSTED_TALK_URL`, default `https://aicontrolroom.nl`; `https://berkkarabacak.com/jarvis` is an alias) or injects `JARVIS_OPERATOR_OPENROUTER_KEY` in the private build env. Users never see it. No notepad, no console paste.

## Related paths that stay

- Portable zip: `scripts/windows/build-portable.ps1`
- Dev script + Edge: `scripts/windows/start-control-room.ps1`
- `RUN-JARVIS.bat` for the zip
