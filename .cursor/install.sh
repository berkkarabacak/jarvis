#!/usr/bin/env bash
# Idempotent bootstrap for the Agent Orchestrator dev environment.
# Runs from the repository root after the source tree is checked out.
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The base image ships Python 3.12 but not the stdlib venv/ensurepip bits,
# which are required to create the project virtualenv.
if ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y --no-install-recommends python3.12-venv
fi

# Project virtualenv keeps dependencies isolated from the system interpreter.
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi

.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# SQLite is the default persistence provider; ensure its data dir exists.
mkdir -p data
