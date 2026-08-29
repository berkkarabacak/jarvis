@echo off
title Jarvis
cd /d "%~dp0"
echo.
echo  === Jarvis ==GRoK== ===
echo  Starting your AI colleague...
echo.

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python environment...
  python -m venv .venv
  if errorlevel 1 (
    echo Python 3.10+ is required. Install from https://www.python.org/downloads/
    pause
    exit /b 1
  )
  .venv\Scripts\pip install -q -r requirements.txt
)

if not exist ".env" (
  copy /Y deploy\local-windows.env.example .env >nul
  .venv\Scripts\python -c "import secrets;from pathlib import Path;from cryptography.fernet import Fernet;p=Path('.env');t=p.read_text(encoding='utf-8');t=t.replace('API_SECRET=change-me-to-a-long-random-string','API_SECRET='+secrets.token_urlsafe(48));t=t.replace('TOKEN_ENCRYPTION_KEY=','TOKEN_ENCRYPTION_KEY='+Fernet.generate_key().decode() if 'TOKEN_ENCRYPTION_KEY=\n' in t or t.rstrip().endswith('TOKEN_ENCRYPTION_KEY=') else t);p.write_text(t,encoding='utf-8');print('Wrote .env — add OPENROUTER_API_KEY (OpenAI Realtime is optional)')"
  echo.
  echo Edit .env and set:
  echo   OPENROUTER_API_KEY=sk-or-...   ^(required to talk^)
  echo   OPENAI_API_KEY=sk-...          ^(optional Realtime upgrade^)
  echo   BRIDGE_TOKEN=...               ^(optional agent bridge^)
  notepad .env
  pause
  exit /b 0
)

findstr /I "JARVIS_ENABLED=true" .env >nul || (
  echo JARVIS_ENABLED=true>>.env
  echo EXECUTIVE_PRIME_ADAPTER=jarvis>>.env
)

set HOST=127.0.0.1
set PORT=8787
set PUBLIC_BASE_URL=http://127.0.0.1:8787

start "Jarvis-backend" /MIN cmd /c "cd /d "%~dp0" && .venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --proxy-headers --forwarded-allow-ips=127.0.0.1"

timeout /t 4 /nobreak >nul

start "" "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" --app=http://127.0.0.1:8787/ceo?autolisten=1^&handsfree=1
if errorlevel 1 start "" "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" --app=http://127.0.0.1:8787/ceo?autolisten=1^&handsfree=1
if errorlevel 1 start http://127.0.0.1:8787/ceo?autolisten=1^&handsfree=1

echo.
echo Jarvis is running at http://127.0.0.1:8787/ceo
echo Workspace: %%USERPROFILE%%\Documents\Jarvis
echo Say: Jarvis, organize my documents
echo Close this window to keep backend running minimized.
echo.
pause
