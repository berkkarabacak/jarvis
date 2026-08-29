#!/usr/bin/env python3
"""Jarvis Tetris HTML bench — thin wrapper around the multi-task suite (ORCH-332).

Prefer `scripts/benchmarks/jarvis_suite_bench.py` for the full index suite.
This entry still writes `benchmarks/jarvis-tetris-latest.json`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from jarvis_suite_bench import main as suite_main  # noqa: E402


def main() -> int:
    argv = sys.argv[1:]
    extra: list[str] = []
    if not any(a == "--tasks" or a.startswith("--tasks=") for a in argv):
        extra.extend(["--tasks", "tetris"])
    if not any(a == "--out" or a.startswith("--out=") for a in argv):
        extra.extend(["--out", "benchmarks/jarvis-tetris-latest.json"])
    return suite_main([*extra, *argv])


if __name__ == "__main__":
    raise SystemExit(main())
