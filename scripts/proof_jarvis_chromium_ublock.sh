#!/usr/bin/env bash
# Prove Jarvis Chromium lists uBlock Origin without a Chrome Web Store install.
# File contract always. Live chrome://extensions dump when chromium is present.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/deploy/jarvis-computer"
ZIP="$DIR/extensions/ublock/uBOLite_2026.825.1619.chromium.zip"
POLICY="$DIR/policies/managed/ublock.json"
CHROMIUM_D="$DIR/chromium.d/ublock-origin"

test -f "$ZIP"
test -f "$POLICY"
test -f "$CHROMIUM_D"
if grep -Eq 'clients2\.google\.com|ExtensionInstallForcelist|force_installed|update2/crx' "$POLICY"; then
  echo "policy still depends on the Chrome Web Store" >&2
  exit 1
fi
grep -q -- '--load-extension=/usr/share/chromium/extensions/ublock' "$CHROMIUM_D"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
unzip -q "$ZIP" -d "$WORK/ublock"
test -f "$WORK/ublock/manifest.json"
python3 - <<PY
import json
from pathlib import Path
work = Path("$WORK/ublock")
manifest = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
locale = json.loads((work / "_locales" / "en" / "messages.json").read_text(encoding="utf-8"))
name = locale["extName"]["message"]
assert int(manifest["manifest_version"]) == 3, manifest["manifest_version"]
assert "uBlock Origin" in name, name
print("vendored manifest:", name, "mv"+str(manifest["manifest_version"]), manifest["version"])
PY

if ! command -v chromium >/dev/null 2>&1 && ! command -v chromium-browser >/dev/null 2>&1; then
  echo "chromium not installed; file contract only (OK without a desktop)"
  exit 0
fi

BROWSER="$(command -v chromium || command -v chromium-browser)"
PROFILE="$WORK/profile"
mkdir -p "$PROFILE"
# Same load path the image uses: unpacked tree + no store forcelist.
# Headless dump of chrome://extensions is the live listing contract.
set +e
timeout 45s "$BROWSER" \
  --headless=new \
  --disable-gpu \
  --no-sandbox \
  --disable-dev-shm-usage \
  --user-data-dir="$PROFILE" \
  --disable-extensions-except="$WORK/ublock" \
  --load-extension="$WORK/ublock" \
  --disable-features=ExtensionManifestV2Disabled,ExtensionManifestV2Unsupported \
  --dump-dom \
  chrome://extensions \
  >"$WORK/extensions.html" 2>"$WORK/chromium.err"
rc=$?
set -e
if [ "$rc" -ne 0 ]; then
  echo "chromium --dump-dom chrome://extensions failed (exit $rc)" >&2
  tail -n 40 "$WORK/chromium.err" >&2 || true
  exit 1
fi
if ! grep -Fq 'uBlock Origin' "$WORK/extensions.html"; then
  echo "chrome://extensions dump does not list uBlock Origin" >&2
  tail -n 20 "$WORK/chromium.err" >&2 || true
  wc -c "$WORK/extensions.html" >&2
  exit 1
fi
echo "chrome://extensions lists uBlock Origin"
grep -o 'uBlock Origin[^<]*' "$WORK/extensions.html" | head -n 5
