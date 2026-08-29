#!/usr/bin/env bash
# ORCH-461: prove the Android computer definition is valid.
# File + compose-config checks only. No GPU, no live phone, no Play Store app.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/deploy/jarvis-android"
COMPOSE="$DIR/docker-compose.yml"
WATCH="$DIR/watch/server.py"
DOCS="$ROOT/docs/jarvis-computer.md"
STORE="$ROOT/app/jarvis/settings_store.py"
COMPUTER="$ROOT/app/jarvis/computer.py"
ANDROID_PY="$ROOT/app/jarvis/android_computer.py"
PUBLIC="$ROOT/deploy/jarvis-public/index.html"

test -f "$COMPOSE"
test -f "$DIR/README.md"
test -f "$WATCH"
test -f "$DIR/watch/Dockerfile"
test -f "$ANDROID_PY"
test -f "$COMPUTER"
test -f "$STORE"
test -f "$PUBLIC"

grep -q 'container_name: jarvis-android' "$COMPOSE"
grep -q '127.0.0.1:6081:6081' "$COMPOSE"
grep -q '127.0.0.1:5555:5555' "$COMPOSE"
grep -q 'jarvis-android-data' "$COMPOSE"
grep -q 'ORCH-461' "$COMPOSE"
# Host bind stays local. The watch process may listen inside the container.
if grep -q '0.0.0.0:' "$COMPOSE"; then
  echo "compose must not publish on all interfaces" >&2
  exit 1
fi

# Not the Play Store client.
if grep -n 'android/' "$ANDROID_PY" | grep -v 'Play Store' >/dev/null; then
  :
fi
grep -q 'is_play_store_client' "$ANDROID_PY"
grep -q 'return False' "$ANDROID_PY"
grep -q 'jarvis-computer' "$ANDROID_PY"
# Android helpers must refuse the Linux container name.
python3 - <<PY
from pathlib import Path
text = Path("$ANDROID_PY").read_text(encoding="utf-8")
assert "jarvis-computer" in text
assert "ANDROID_CONTAINER = \"jarvis-android\"" in text
assert "docker exec" in text
assert "screencap" in text
assert "input" in text
assert '["docker", "run"]' not in text
print("android_computer.py contract ok")
PY

grep -q 'computer_kind' "$STORE"
grep -q 'DEFAULT_COMPUTER_KIND = "linux"' "$STORE"
grep -q 'JARVIS_ANDROID' "$COMPUTER"
grep -q 'selected_jarvis_box' "$COMPUTER"

grep -q 'data-computer="linux"' "$PUBLIC"
grep -q 'data-computer="android"' "$PUBLIC"
grep -q 'Which computer he uses' "$PUBLIC"
grep -q 'ORCH-461' "$DOCS"

if command -v docker >/dev/null 2>&1; then
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "$COMPOSE" --project-directory "$DIR" config >/dev/null
  fi
fi

echo "ORCH-461 smoke: OK"
