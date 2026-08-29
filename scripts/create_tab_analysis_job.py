#!/usr/bin/env python3
"""Create the ORCH-393 tab-analysis job against a running orchestrator.

Uses the existing jobs API only (cron + POST /api/jobs/{id}/run).
The job definition carries the look+keys combined-analysis goal.

Usage:
  set ORCH_URL=http://127.0.0.1:8787
  set ORCH_API_KEY=...
  python scripts/create_tab_analysis_job.py
  python scripts/create_tab_analysis_job.py --schedule "* * * * *"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.jobs.tab_analysis import SHORT_DELAY_CRON, tab_analysis_job_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Create tab-analysis scheduled job")
    parser.add_argument(
        "--schedule",
        default="",
        help="5-field cron (empty = one-shot; use '* * * * *' for short-delay)",
    )
    parser.add_argument("--name", default="", help="Override job name")
    args = parser.parse_args()

    base = (os.environ.get("ORCH_URL") or "http://127.0.0.1:8787").rstrip("/")
    key = os.environ.get("ORCH_API_KEY") or os.environ.get("API_SECRET") or ""
    if not key:
        print("Set ORCH_API_KEY (or API_SECRET)", file=sys.stderr)
        return 2

    schedule = args.schedule.strip() or None
    if schedule == "short":
        schedule = SHORT_DELAY_CRON
    body = tab_analysis_job_payload(schedule=schedule, name=args.name or None)
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
    print(
        f"Run (same clock): curl -X POST {base}/api/jobs/{job.get('id')}/run "
        f"-H \"X-Api-Key: $ORCH_API_KEY\""
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
