#!/usr/bin/env python3
"""Create the herdr-smoke sample job against a running orchestrator.

Usage:
  set ORCH_URL=https://berkkarabacak.com/agent-orchestrator
  set ORCH_API_KEY=...
  python scripts/create_herdr_sample_job.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.error
import urllib.request


def main() -> int:
    base = (os.environ.get("ORCH_URL") or "http://127.0.0.1:8787").rstrip("/")
    key = os.environ.get("ORCH_API_KEY") or os.environ.get("API_SECRET") or ""
    if not key:
        print("Set ORCH_API_KEY (or API_SECRET)", file=sys.stderr)
        return 2

    cwd = os.environ.get("HERDR_SMOKE_CWD") or tempfile.mkdtemp(prefix="herdr-smoke-")
    body = {
        "name": "herdr-smoke",
        "prompt_template": (
            "You are a smoke test. Reply with exactly one short paragraph confirming "
            "Herdr ran this job and include the date token: {{date}}. No tools needed."
        ),
        "runner": "herdr",
        "herdr_agent_kind": os.environ.get("HERDR_DEFAULT_KIND") or "opencode",
        "herdr_agent_name": "orch-smoke",
        "herdr_cwd": cwd,
        "herdr_workspace_label": "orch-smoke",
        "enabled": True,
        "slack_on_failure": False,
    }
    req = urllib.request.Request(
        f"{base}/api/jobs",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Api-Key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8", errors="replace"), file=sys.stderr)
        return 1

    job = data.get("job") or {}
    print(json.dumps(job, indent=2))
    print()
    print(f"Created job id={job.get('id')}")
    print(f"cwd={cwd}")
    print(f"Run: curl -X POST {base}/api/jobs/{job.get('id')}/run -H \"X-Api-Key: $ORCH_API_KEY\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
