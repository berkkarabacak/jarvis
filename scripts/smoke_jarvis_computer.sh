#!/usr/bin/env bash
# ORCH-401 / ORCH-402 / ORCH-403 / ORCH-404 / ORCH-405 / ORCH-406 / ORCH-410:
# prove the Jarvis computer definition is valid. File + compose-config
# checks only. No GPU, no cloud VM. The ORCH-406 proof script must exist
# and refuse to invent a screen; this smoke does not start the desktop.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/deploy/jarvis-computer"
COMPOSE="$DIR/docker-compose.yml"
DOCKERFILE="$DIR/Dockerfile"
DOCS="$ROOT/docs/jarvis-computer.md"
THEME="$DIR/theme"
PANEL="$THEME/xfce-config/xfce4-panel.xml"
APPS="$DIR/apps"

test -f "$DOCKERFILE"
test -f "$COMPOSE"
test -f "$DIR/entrypoint.sh"
test -f "$DIR/README.md"
test -f "$DOCS"
test -f "$DIR/bin/chrome"
test -f "$DIR/novnc/index.html"

test -f "$THEME/xfwm4/themerc"
test -f "$THEME/gtk-3.0/gtk.css"
test -f "$THEME/wallpaper.png"
test -f "$THEME/icons/index.theme"
test -f "$THEME/icons/32x32/apps/start-here.png"
test -f "$PANEL"
test -f "$THEME/xfce-config/xfwm4.xml"
test -f "$THEME/xfce-config/xsettings.xml"
test -f "$THEME/xfce-config/xfce4-desktop.xml"

for shortcut in chrome.desktop notepad.desktop files.desktop terminal.desktop calculator.desktop image-viewer.desktop
do
  test -f "$APPS/$shortcut"
done

grep -q 'FROM debian:' "$DOCKERFILE"
grep -q 'xvfb' "$DOCKERFILE"
grep -q 'xfce4-session' "$DOCKERFILE"
grep -q 'useradd' "$DOCKERFILE"
grep -q 'JarvisWin' "$DOCKERFILE"
grep -q 'jarvis-windows-theme' "$DOCKERFILE"
grep -q 'chromium' "$DOCKERFILE"
grep -q 'mousepad' "$DOCKERFILE"
grep -q 'thunar' "$DOCKERFILE"
grep -q 'xfce4-terminal' "$DOCKERFILE"
grep -q 'galculator' "$DOCKERFILE"
grep -q 'ristretto' "$DOCKERFILE"
grep -q 'novnc' "$DOCKERFILE"
grep -q 'x11vnc' "$DOCKERFILE"
grep -q 'websockify' "$DOCKERFILE"
grep -q 'xdotool' "$DOCKERFILE"
grep -q 'scrot' "$DOCKERFILE"

grep -q 'container_name: jarvis-computer' "$COMPOSE"
grep -q 'restart: unless-stopped' "$COMPOSE"
grep -q 'jarvis-home:/home/jarvis' "$COMPOSE"
grep -q 'name: jarvis-computer-home' "$COMPOSE"
grep -q '127.0.0.1:6080:6080' "$COMPOSE"
grep -q 'ports:' "$COMPOSE"

grep -q 'applicationsmenu' "$PANEL"
grep -q 'Start' "$PANEL"
grep -q 'tasklist' "$PANEL"
grep -q 'p=11' "$PANEL"
grep -q 'JarvisWin' "$THEME/xfce-config/xfwm4.xml"
grep -q '.jarvis-windows-theme-ready' "$DIR/entrypoint.sh"
grep -q '.jarvis-apps-ready' "$DIR/entrypoint.sh"
grep -q 'exec chromium' "$DIR/bin/chrome"
grep -q 'x11vnc' "$DIR/entrypoint.sh"
grep -q 'websockify' "$DIR/entrypoint.sh"
grep -q '/usr/share/novnc' "$DIR/entrypoint.sh"
grep -q 'autoconnect=1' "$DIR/novnc/index.html"

svc_count="$(awk '
  /^services:[[:space:]]*$/ { s=1; next }
  s && /^[a-zA-Z]/ { exit }
  s && /^  [a-zA-Z0-9_-]+:[[:space:]]*$/ { c++ }
  END { print c+0 }
' "$COMPOSE")"
if [ "$svc_count" != "1" ]; then
  echo "expected exactly one compose service, got $svc_count" >&2
  exit 1
fi

if grep -Eiq 'kasmvnc|kasmweb|webtop' "$DOCKERFILE" "$COMPOSE" "$DIR/entrypoint.sh"; then
  echo "Kasm/webtop is rejected; use noVNC + x11vnc on this desktop" >&2
  exit 1
fi

if grep -Fq '0.0.0.0' "$COMPOSE"; then
  echo "compose must not bind 0.0.0.0; remote view is localhost only" >&2
  exit 1
fi

if ! grep -q '127.0.0.1:6080:6080' "$COMPOSE"; then
  echo "compose must publish noVNC on 127.0.0.1:6080" >&2
  exit 1
fi

for needle in \
  "docker compose up" \
  "docker compose stop" \
  "one computer" \
  "ORCH-402" \
  "ORCH-403" \
  "ORCH-404" \
  "ORCH-405" \
  "ORCH-406" \
  "ORCH-410" \
  "Open Jarvis's screen" \
  "Windows-like" \
  "chromium" \
  "mousepad" \
  "http://127.0.0.1:6080" \
  "noVNC" \
  "proof_jarvis_computer_notepad" \
  "refuses to invent"
do
  if ! grep -Fiq "$needle" "$DOCS"; then
    echo "docs/jarvis-computer.md missing: $needle" >&2
    exit 1
  fi
done

later="$(awk '/^## Later tickets/{p=1; next} p && /^## /{exit} p' "$DOCS")"
if printf '%s\n' "$later" | grep -q 'ORCH-403'; then
  echo "ORCH-403 must not remain in Later tickets" >&2
  exit 1
fi
if printf '%s\n' "$later" | grep -q 'ORCH-404'; then
  echo "ORCH-404 must not remain in Later tickets" >&2
  exit 1
fi
if printf '%s\n' "$later" | grep -q 'ORCH-405'; then
  echo "ORCH-405 must not remain in Later tickets" >&2
  exit 1
fi
if printf '%s\n' "$later" | grep -q 'ORCH-406'; then
  echo "ORCH-406 must not remain in Later tickets" >&2
  exit 1
fi
if printf '%s\n' "$later" | grep -q 'ORCH-410'; then
  echo "ORCH-410 must not remain in Later tickets" >&2
  exit 1
fi
if ! grep -q 'ORCH-405' "$DOCS"; then
  echo "docs must say ORCH-405 landed" >&2
  exit 1
fi
if ! grep -q 'ORCH-406' "$DOCS"; then
  echo "docs must say ORCH-406 landed" >&2
  exit 1
fi
if ! grep -q 'ORCH-410' "$DOCS"; then
  echo "docs must say ORCH-410 landed" >&2
  exit 1
fi
if ! grep -q "Open Jarvis's screen" "$DOCS"; then
  echo "docs must describe the ORCH-410 on-demand viewer" >&2
  exit 1
fi
if ! grep -q 'proof_jarvis_computer_notepad' "$DOCS"; then
  echo "docs must describe the ORCH-406 proof script" >&2
  exit 1
fi
PROOF="$ROOT/scripts/proof_jarvis_computer_notepad.py"
if [ ! -f "$PROOF" ]; then
  echo "scripts/proof_jarvis_computer_notepad.py missing (ORCH-406)" >&2
  exit 1
fi
if ! grep -q 'refusing to invent a screenshot' "$PROOF"; then
  echo "proof script must refuse to invent a screen" >&2
  exit 1
fi
if ! grep -q 'plan_linux_run_app' "$PROOF"; then
  echo "proof script must use ORCH-405 helpers" >&2
  exit 1
fi
if grep -Eq '\[.docker., .run.\]' "$PROOF"; then
  echo "proof script must not docker run a second computer" >&2
  exit 1
fi
if ! grep -Eq 'docker exec|xdotool' "$DOCS"; then
  echo "docs must describe ORCH-405 docker exec / xdotool wiring" >&2
  exit 1
fi
if [ ! -f "$ROOT/app/jarvis/computer.py" ]; then
  echo "app/jarvis/computer.py missing (ORCH-405 routing helpers)" >&2
  exit 1
fi
if grep -Eq '\[.docker., .run.\]|docker compose up -d|docker-compose up -d' "$ROOT/app/jarvis/computer.py"; then
  echo "computer.py must not spawn containers" >&2
  exit 1
fi

VIEWER="$ROOT/app/static/jarvis-screen.html"
CEO="$ROOT/app/static/ceo.html"
MAIN_JS="$ROOT/desktop/main.js"
SCREEN_PY="$ROOT/app/jarvis/screen_viewer.py"
if [ ! -f "$VIEWER" ]; then
  echo "app/static/jarvis-screen.html missing (ORCH-410)" >&2
  exit 1
fi
if [ ! -f "$SCREEN_PY" ]; then
  echo "app/jarvis/screen_viewer.py missing (ORCH-410)" >&2
  exit 1
fi
if ! grep -q "Jarvis's screen" "$VIEWER"; then
  echo "viewer page must be captioned Jarvis's screen" >&2
  exit 1
fi
if ! grep -q '127.0.0.1:6080' "$VIEWER"; then
  echo "viewer must embed the existing localhost:6080 session" >&2
  exit 1
fi
if ! grep -q "Jarvis's computer is not running" "$VIEWER"; then
  echo "viewer must say when the computer is down" >&2
  exit 1
fi
if grep -q '0.0.0.0' "$VIEWER" "$SCREEN_PY"; then
  echo "viewer must not publish the desktop on all interfaces" >&2
  exit 1
fi
if ! grep -q "Open Jarvis's screen" "$CEO"; then
  echo "CEO page must have Open Jarvis's screen" >&2
  exit 1
fi
if ! grep -q "Open Jarvis's screen" "$MAIN_JS"; then
  echo "Electron menu must have Open Jarvis's screen" >&2
  exit 1
fi
if ! grep -q "Jarvis's screen" "$MAIN_JS"; then
  echo "Electron viewer window must be titled Jarvis's screen" >&2
  exit 1
fi
if ! grep -q '127.0.0.1:6080' "$MAIN_JS"; then
  echo "Electron viewer must point at the existing 6080 session" >&2
  exit 1
fi
if ! grep -q 'docker start' "$SCREEN_PY"; then
  echo "screen viewer must fall back to docker start when compose is missing" >&2
  exit 1
fi
if ! grep -q '127.0.0.1:6080:6080' "$SCREEN_PY"; then
  echo "docker run fallback must bind localhost 6080 only" >&2
  exit 1
fi
if ! grep -q 'jarvis-computer-home' "$SCREEN_PY"; then
  echo "docker run fallback must use named volume jarvis-computer-home" >&2
  exit 1
fi
if grep -q '0.0.0.0' "$SCREEN_PY"; then
  echo "viewer must not publish the desktop on all interfaces" >&2
  exit 1
fi
if grep -q -- '--build' "$SCREEN_PY"; then
  echo "viewer must not docker compose up --build" >&2
  exit 1
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  docker compose -f "$COMPOSE" --project-directory "$DIR" config >/tmp/jarvis-computer-compose.yml
  grep -q 'jarvis-computer' /tmp/jarvis-computer-compose.yml
  grep -q 'jarvis-computer-home' /tmp/jarvis-computer-compose.yml
  grep -q '6080' /tmp/jarvis-computer-compose.yml
  echo "docker compose config: OK"
else
  echo "docker compose not available; file checks only (OK for CI)"
fi

echo "ORCH-401 smoke: OK"
echo "ORCH-402 theme files: OK"
echo "ORCH-403 apps: OK"
echo "ORCH-404 remote view: OK"
echo "ORCH-405 drive helpers: OK"
echo "ORCH-406 notepad proof script: OK"
echo "ORCH-410 on-demand viewer: OK"
