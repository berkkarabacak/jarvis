#!/usr/bin/env bash
# Linux cannot produce a usable Jarvis-Setup.exe. Build on Windows (Odin).
set -euo pipefail
echo "This installer must be built on a Windows machine."
echo "On Odin run:"
echo "  powershell -ExecutionPolicy Bypass -File scripts\\windows\\build-installer.ps1"
echo "Output: dist\\Jarvis-Setup.exe"
exit 1
