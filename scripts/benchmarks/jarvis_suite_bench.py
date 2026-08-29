#!/usr/bin/env python3
"""Jarvis multi-task benchmark suite (ORCH-332 / ORCH-336 / ORCH-334 / ORCH-342 / ORCH-347).

One runner, several cheap local tasks. Unique seed in filename AND artifact body
(when a file is written). Records model, seconds, cost_usd, ok, artifact,
escalate, tools_used. Provider $0 is cost_unknown (not free).

Headline metrics: pass@1, $ per success, escalate %.
$ per success uses known-cost rows only (one unknown row does not wipe the model).

ORCH-336 adds:
  * local_fact — must call get_disk_space or home_list; invented answer = fail
  * fail_then_escalate — cheap fail then stronger retry; both $ stay visible

ORCH-334 adds:
  * organize-dry-run must write a seeded plan file (listing a folder is a fail)
  * optional cheap_math — 3 grade-school integer questions (off by default)
  * windows_service_stub — write (do not install) a seeded Windows service stub

ORCH-342 adds:
  * two_file_split — both a seeded stub and a seeded README must land.
    Ask is "split this: one child writes the stub, one writes the readme."
    A solo parent that writes both files is a pass; children are not required.
    Row records parent $, child $ (0 when solo), wall time, escalate %,
    models used, and who-did-what.

ORCH-347 adds org shape on every row:
  * depth (0 when solo; 2 = parent -> managers -> workers)
  * agent_count (1 when solo; parent + managers + workers)
  * parent $ + child $ (child $ is 0 when solo)
  * wall time (elapsed_sec)
  * who-did-what including managers
  Tiny / solo jobs must not grow an org. Depth-2 spawn may land later;
  rows still accept a stubbed manager tree.

Just the Windows service stub probe:

  python scripts/benchmarks/jarvis_suite_bench.py --tasks windows_service_stub \\
      --models openai/gpt-4.1-mini

Just the two-file split probe (solo parent writing both files is a pass):

  python scripts/benchmarks/jarvis_suite_bench.py --tasks two_file_split \\
      --models openai/gpt-4.1-mini

Usage (Windows Jarvis server already running with BRIDGE_TOKEN):

  python scripts/benchmarks/jarvis_suite_bench.py \\
      --base-url http://127.0.0.1:8787 \\
      --models openai/gpt-4.1-mini,openai/gpt-4.1,google/gemini-2.5-flash

Just the 3 cheap math probes:

  python scripts/benchmarks/jarvis_suite_bench.py --cheap-math-only \\
      --models openai/gpt-4.1-mini

  python scripts/benchmarks/jarvis_suite_bench.py --tasks cheap_math \\
      --models openai/gpt-4.1-mini

Tetris-only (compat): python scripts/benchmarks/jarvis_tetris_bench.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.jarvis.cost_index import (  # noqa: E402
    INDEX_LATEST,
    TIME_PENALTY_USD_PER_SEC,
    fold_attempt_rows,
    index_payload,
    normalize_reported_cost,
    seed_in_text,
    unique_artifact_rel,
)

LOCAL_FACT_TOOLS = ("get_disk_space", "home_list")
ORGANIZE_FORBIDDEN_TOOLS = ("home_list", "organize_folder")
DEFAULT_ESCALATE_MODEL = "openai/gpt-4.1"
CHEAP_MATH_ITEMS: tuple[tuple[str, str, int], ...] = (
    ("cheap_math_1", "What is 17 plus 28?", 45),
    ("cheap_math_2", "What is 9 times 8?", 72),
    ("cheap_math_3", "What is 144 divided by 12?", 12),
)
CHEAP_MATH_IDS = tuple(item[0] for item in CHEAP_MATH_ITEMS)
CHEAP_MATH_ALIASES = {"cheap_math", "cheap_maths"}
SERVICE_STUB_MARKERS = ("servicename", "win32service", "sc create", "nssm")
TWO_FILE_SPLIT_KINDS: tuple[tuple[str, str], ...] = (("stub", ".py"), ("readme", ".md"))
SOLO_WHO_DID_WHAT = "solo parent wrote both"

# Rough OpenRouter list prices USD per 1M tokens (input, output). Update as needed.
BENCH_PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    "openai/gpt-4.1-mini": (0.40, 1.60),
    "openai/gpt-4.1": (2.00, 8.00),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "anthropic/claude-sonnet-4": (3.00, 15.00),
    "anthropic/claude-3.5-sonnet": (3.00, 15.00),
    "google/gemini-2.5-flash": (0.30, 2.50),
    "google/gemini-2.0-flash-001": (0.10, 0.40),
}

TETRIS_FALLBACK_OUT = Path("benchmarks") / "jarvis-tetris-latest.json"


def make_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:6]}"


def _workspace_candidates() -> list[Path]:
    return [
        Path.home() / "Documents" / "Jarvis",
        Path.home() / "Jarvis-Workspace",
    ]


def _heuristic_tetris(path: Path, seed: str, model: str | None = None) -> bool:
    if not path.is_file() or path.stat().st_size < 800:
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not seed_in_text(text, seed):
        return False
    low = text.lower()
    checks = [
        "canvas" in low or "<table" in low or "grid-template" in low,
        "tetris" in low or "tetromino" in low or "piece" in low,
        "keydown" in low or "arrow" in low,
    ]
    return sum(1 for c in checks if c) >= 2


def _heuristic_spreadsheet(path: Path, seed: str, model: str | None = None) -> bool:
    if not path.is_file() or path.stat().st_size < 24:
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not seed_in_text(text, seed):
        return False
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if len(lines) < 3:
        return False
    header = lines[0].lower()
    if "revenue" not in header and "orders" not in header:
        return False
    data_rows = 0
    for ln in lines[1:]:
        if "," in ln:
            data_rows += 1
    return data_rows >= 2


def _looks_like_folder_listing(text: str) -> bool:
    """True when the artifact is a folder dump, not an organize plan."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        tool = str(data.get("tool") or "")
        if tool in ORGANIZE_FORBIDDEN_TOOLS:
            return True
        if isinstance(data.get("entries"), list):
            return True
        if "moves" not in data and "dry_run" not in data:
            if any(k in data for k in ("root", "path", "drives")):
                return True
    return False


def _heuristic_organize(path: Path, seed: str, model: str | None = None) -> bool:
    if not path.is_file() or path.stat().st_size < 40:
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not seed_in_text(text, seed):
        return False
    if _looks_like_folder_listing(text):
        return False
    low = text.lower()
    if "dry_run" not in low and "dry-run" not in low:
        return False
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    if data.get("dry_run") not in {True, "true", "True", 1}:
        return False
    moves = data.get("moves")
    if not isinstance(moves, list) or len(moves) < 5:
        return False
    files_ok = sum(
        1
        for name in ("invoice.pdf", "photo.jpg", "notes.txt", "script.py", "archive.zip")
        if name in low
    )
    bucket_hits = 0
    if "images" in low:
        bucket_hits += 1
    if "scripts" in low:
        bucket_hits += 1
    if "archives" in low:
        bucket_hits += 1
    if "docs" in low:
        bucket_hits += 1
    return files_ok >= 4 and bucket_hits >= 3


def judge_organize(
    *,
    seed: str,
    task_state: dict[str, Any] | None,
    artifact: Path | None = None,
) -> bool:
    """Pass only with a written seeded plan. Listing a folder is a fail."""
    if artifact is None or not Path(artifact).is_file():
        return False
    path = Path(artifact)
    if not seed_in_text(path.name, seed):
        return False
    tools = extract_tools_used(task_state)
    if any(_norm_tool(t) in ORGANIZE_FORBIDDEN_TOOLS for t in tools):
        return False
    return _heuristic_organize(path, seed)


def _heuristic_escalate_card(path: Path, seed: str, model: str | None = None) -> bool:
    if not path.is_file() or path.stat().st_size < 24:
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not seed_in_text(text, seed):
        return False
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    if str(data.get("seed") or "") != seed:
        return False
    if str(data.get("task") or "").strip().lower() not in {
        "fail-then-escalate",
        "fail_then_escalate",
    }:
        return False
    return str(data.get("status") or "").strip().lower() == "ok"


def _heuristic_local_fact(path: Path, seed: str, model: str | None = None) -> bool:
    """Artifact-only check: seed + tool-shaped payload. Prefer judge_local_fact."""
    if not path.is_file() or path.stat().st_size < 16:
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not seed_in_text(text, seed):
        return False
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    result = data.get("result") if isinstance(data.get("result"), dict) else data
    tool = str(data.get("tool") or "")
    return real_local_tool_payload(result, [tool] if tool else list(LOCAL_FACT_TOOLS))


def _norm_tool(name: str) -> str:
    n = (name or "").strip()
    if n in {"disk_space", "diskSpace", "free_space", "get_disk_space"}:
        return "get_disk_space"
    return n


def extract_tools_used(task_state: dict[str, Any] | None) -> list[str]:
    """Collect tool names from a Bridge task payload (any nesting)."""
    found: list[str] = []

    def _add(xs: Any) -> None:
        if isinstance(xs, str) and xs.strip():
            found.append(xs.strip())
            return
        if isinstance(xs, list):
            for item in xs:
                if isinstance(item, str) and item.strip():
                    found.append(item.strip())

    if not isinstance(task_state, dict):
        return []
    _add(task_state.get("tools_used"))
    result = task_state.get("result")
    if isinstance(result, dict):
        _add(result.get("tools_used"))
        data = result.get("data")
        if isinstance(data, dict):
            _add(data.get("tools_used"))
            _add(data.get("tools_called"))
    data_top = task_state.get("data")
    if isinstance(data_top, dict):
        _add(data_top.get("tools_used"))
        _add(data_top.get("tools_called"))
    out: list[str] = []
    seen: set[str] = set()
    for name in found:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def real_local_tool_payload(data: Any, tools: list[str]) -> bool:
    """True when payload looks like a real get_disk_space / home_list result."""
    if not isinstance(data, dict):
        return False
    blobs: list[dict[str, Any]] = [data]
    nested = data.get("data")
    if isinstance(nested, dict):
        blobs.append(nested)
    result = data.get("result")
    if isinstance(result, dict):
        blobs.append(result)
    normalized = {_norm_tool(t) for t in tools} if tools else {"get_disk_space", "home_list"}
    for blob in blobs:
        if "get_disk_space" in normalized:
            drives = blob.get("drives")
            if isinstance(drives, list) and drives:
                first = drives[0]
                if isinstance(first, dict) and (
                    first.get("free_bytes") is not None or first.get("free")
                ):
                    return True
        if "home_list" in normalized:
            entries = blob.get("entries")
            if isinstance(entries, list) and (
                blob.get("ok") is True or "root" in blob or "path" in blob
            ):
                return True
    return False


def judge_local_fact(
    *,
    seed: str,
    task_state: dict[str, Any] | None,
    artifact: Path | None = None,
) -> bool:
    """Pass only when a real local tool fired. Invented answers fail.

    Seed must appear in any written artifact. Prompt always carries the seed.
    """
    tools = extract_tools_used(task_state)
    if not any(_norm_tool(t) in {"get_disk_space", "home_list"} for t in tools):
        return False
    result: dict[str, Any] = {}
    if isinstance(task_state, dict):
        raw = task_state.get("result")
        if isinstance(raw, dict):
            result = raw
    data = result.get("data") if isinstance(result.get("data"), dict) else None
    if data is None and isinstance(task_state, dict) and isinstance(task_state.get("data"), dict):
        data = task_state["data"]
    if not real_local_tool_payload(data or result, tools):
        return False
    if artifact is not None and Path(artifact).is_file():
        text = Path(artifact).read_text(encoding="utf-8", errors="ignore")
        if not seed_in_text(text, seed):
            return False
        # Hallucinated file that merely names the tool still needs real payload.
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            body = None
        if isinstance(body, dict) and not real_local_tool_payload(body, tools):
            return False
    return True


@dataclass(frozen=True)
class BenchTask:
    id: str
    suffix: str
    goal: Callable[[str, str, str], str]  # model, relpath, seed
    heuristic: Callable[[Path, str, str | None], bool]
    timeout_sec: int = 300
    max_tokens: int = 8192
    max_tool_rounds: int = 16
    must_call: tuple[str, ...] = ()
    requires_artifact: bool = True
    special: str = ""
    # Optional (kind, suffix) pairs so one task can name two seeded files.
    artifact_kinds: tuple[tuple[str, str], ...] = ()


def _goal_tetris(model: str, rel: str, seed: str) -> str:
    return f"""Build a simple playable Tetris as ONE HTML file with inline CSS+JS.

Save with write_file to: {rel}

Requirements: 10x20 board, 7 tetrominoes, arrow keys move/rotate, Space hard drop,
score + lines + level. No questions. Finish the file.
Put this HTML comment near the top (seed must appear in the file body):
<!-- bench-seed: {seed} bench-model: {model} -->
"""


def _goal_spreadsheet(model: str, rel: str, seed: str) -> str:
    return f"""Write a small seeded CSV spreadsheet with write_file (not xlsx).

Save to: {rel}

Headers: seed,month,revenue_usd,orders
Rows (first column is the seed, must match exactly):
{seed},2026-01,1200,14
{seed},2026-02,1500,19
{seed},2026-03,1100,11

Last line: # bench-seed: {seed} bench-model: {model}
No questions. Finish the file. The seed must appear in the filename and the file body.
"""


def _goal_organize(model: str, rel: str, seed: str) -> str:
    # Avoid Bridge inference triggers ("document"+"list/files/show") that
    # short-circuit to home_list on Documents — that was the 2026-08-13 miss.
    return f"""WRITE A PLAN FILE. This is not a request to inspect any folder.

Do NOT call home_list. Do NOT call organize_folder. Do NOT move or delete anything.
Dumping a folder inventory is a FAIL.
The only allowed write is write_file of the plan JSON below.

Fictional Inbox names (already complete — do not look on disk):
- invoice.pdf
- photo.jpg
- notes.txt
- script.py
- archive.zip
- random.bin

write_file the JSON plan to: {rel}

Required shape:
{{"dry_run": true, "seed": "{seed}", "bench_model": "{model}", "moves": [
  {{"file": "invoice.pdf", "bucket": "Docs"}}
]}}

Buckets: Docs, Images, Scripts, Archives, Other.
Put every name above into exactly one bucket.
The seed must appear in the filename AND the JSON body (seed field).
No questions. Finish the file.
bench-seed: {seed}
"""


def _as_int_answer(val: Any) -> int | None:
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float) and val.is_integer():
        return int(val)
    if isinstance(val, str):
        s = val.strip()
        if s.lstrip("-").isdigit():
            return int(s)
    return None


def _goal_cheap_math(model: str, rel: str, seed: str, question: str) -> str:
    return f"""Grade-school integer question. Unique seed: {seed}

Question: {question}

write_file JSON to: {rel}
{{"seed": "{seed}", "bench_model": "{model}", "answer": <integer>}}

Put the exact integer in "answer". No words in that field. No questions.
The seed must appear in the filename and the JSON body.
bench-seed: {seed}
"""


def _heuristic_cheap_math(path: Path, seed: str, expected: int, model: str | None = None) -> bool:
    if not path.is_file() or path.stat().st_size < 8:
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not seed_in_text(text, seed):
        return False
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    return _as_int_answer(data.get("answer")) == expected


def _make_cheap_math_task(task_id: str, question: str, expected: int) -> BenchTask:
    def goal(model: str, rel: str, seed: str) -> str:
        return _goal_cheap_math(model, rel, seed, question)

    def heuristic(path: Path, seed: str, model: str | None = None) -> bool:
        return _heuristic_cheap_math(path, seed, expected, model)

    return BenchTask(
        task_id.replace("_", "-"),
        ".json",
        goal,
        heuristic,
        timeout_sec=90,
        max_tokens=512,
        max_tool_rounds=4,
    )


def _goal_local_fact(model: str, rel: str, seed: str) -> str:
    # Avoid inference trigger phrases ("free space", "disk space", "list desktop")
    # so the agent path must actually call the tool (ORCH-336).
    return f"""Call a real local tool: get_disk_space or home_list. Do not invent facts.

Hallucinated numbers or filenames without a tool call are a fail.
After the tool returns, write_file the JSON to: {rel}

Shape:
{{"seed": "{seed}", "bench_model": "{model}", "tool": "get_disk_space", "result": {{...tool JSON...}}}}

The seed must appear in the filename and the JSON body.
bench-seed: {seed}
No questions. Finish the file.
"""


def _goal_windows_service(model: str, rel: str, seed: str) -> str:
    return f"""WRITE a small Windows service STUB. Do not install anything.

Do NOT run sc.exe, nssm, New-Service, or run_powershell to register a real service.
Chatting without write_file is a fail.

write_file to: {rel}

The stub must name the service exactly: {seed}
Include at least one of: ServiceName, win32service, sc create, nssm
(example: ServiceName = "{seed}" or a commented sc create {seed} line).
Python or a .cmd-style script is fine. This file is the artifact — do not execute it.

The seed must appear in the filename AND the file body.
bench-seed: {seed} bench-model: {model}
No questions. Finish the file.
"""


def _heuristic_windows_service(path: Path, seed: str, model: str | None = None) -> bool:
    if not path.is_file() or path.stat().st_size < 24:
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not seed_in_text(text, seed):
        return False
    low = text.lower()
    return any(marker in low for marker in SERVICE_STUB_MARKERS)


def judge_windows_service_stub(
    *,
    seed: str,
    artifact: Path | None = None,
) -> bool:
    """Pass only with a written seeded stub. Chat-only is a fail."""
    if artifact is None or not Path(artifact).is_file():
        return False
    path = Path(artifact)
    if not seed_in_text(path.name, seed):
        return False
    return _heuristic_windows_service(path, seed)


def two_file_split_rels(model: str, seed: str) -> tuple[str, str]:
    """Seeded stub + README relative paths (unique_artifact_rel + kind)."""
    stub = unique_artifact_rel(
        task="two-file-split", model=model, run_id=seed, suffix=".py", kind="stub"
    )
    readme = unique_artifact_rel(
        task="two-file-split", model=model, run_id=seed, suffix=".md", kind="readme"
    )
    return stub, readme


def artifact_rels_for(task: BenchTask, model: str, run_id: str) -> list[str]:
    """One or more unique seeded rels for a task (two_file_split yields a pair)."""
    kinds = task.artifact_kinds
    if kinds:
        return [
            unique_artifact_rel(
                task=task.id, model=model, run_id=run_id, suffix=suf, kind=kind
            )
            for kind, suf in kinds
        ]
    return [unique_artifact_rel(task=task.id, model=model, run_id=run_id, suffix=task.suffix)]


def _goal_two_file_split(model: str, rel: str, seed: str) -> str:
    # Avoid Bridge inference triggers (disk space / list desktop|download|document).
    stub_rel, readme_rel = two_file_split_rels(model, seed)
    _ = rel  # primary rel is unused; both paths are computed and named below
    return f"""split this: one child writes the stub, one writes the readme.

WRITE TWO FILES. A parent that writes both itself is fine.
Chatting without write_file is a fail. Do not install or run anything.

write_file the Python stub to: {stub_rel}
write_file the markdown README to: {readme_rel}

Stub body must include this exact seed: {seed}
Example stub line: # bench-seed: {seed} bench-model: {model}

README body must include this exact seed: {seed}
Example README line: bench-seed: {seed} bench-model: {model}

The seed must appear in EACH filename AND EACH file body.
No questions. Finish both files.
bench-seed: {seed}
"""


def _seeded_named_file(path: Path | None, seed: str, *, min_bytes: int = 8) -> bool:
    if path is None or not Path(path).is_file():
        return False
    p = Path(path)
    if p.stat().st_size < min_bytes:
        return False
    if not seed_in_text(p.name, seed):
        return False
    text = p.read_text(encoding="utf-8", errors="ignore")
    return seed_in_text(text, seed)


def _heuristic_two_file_split(path: Path, seed: str, model: str | None = None) -> bool:
    """Single-path heuristic is never enough; use judge_two_file_split."""
    return False


def judge_two_file_split(
    *,
    seed: str,
    stub: Path | None = None,
    readme: Path | None = None,
    task_state: dict[str, Any] | None = None,
) -> bool:
    """Pass only when BOTH seeded files exist. Children are not required.

    Missing either file, missing seed in a name or body, or chat-only = fail.
    """
    _ = task_state  # orchestration is recorded on the row; grader is files-only
    return _seeded_named_file(stub, seed) and _seeded_named_file(readme, seed)


def _first_present(blobs: list[dict[str, Any]], key: str) -> Any:
    for blob in blobs:
        if key in blob and blob.get(key) is not None:
            return blob.get(key)
    return None


def _task_state_blobs(task_state: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(task_state, dict):
        return []
    blobs: list[dict[str, Any]] = [task_state]
    result = task_state.get("result")
    if isinstance(result, dict):
        blobs.append(result)
        data = result.get("data")
        if isinstance(data, dict):
            blobs.append(data)
    data_top = task_state.get("data")
    if isinstance(data_top, dict):
        blobs.append(data_top)
    return blobs


def _has_children(raw: Any) -> bool:
    if isinstance(raw, list):
        return any(isinstance(item, dict) and item for item in raw)
    if isinstance(raw, dict):
        return bool(raw)
    return False


def _child_nodes(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and item]


def _nested_children(item: dict[str, Any]) -> Any:
    return item.get("children") or item.get("workers") or item.get("reports")


def _as_nonneg_int(val: Any) -> int | None:
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val if val >= 0 else None
    if isinstance(val, float) and val.is_integer() and val >= 0:
        return int(val)
    if isinstance(val, str):
        s = val.strip()
        if s.isdigit():
            return int(s)
    return None


def org_depth_from_children(children: Any) -> int:
    """Hops below the parent. Solo / empty = 0. Workers = 1. Managers+workers = 2."""
    items = _child_nodes(children)
    if not items:
        return 0
    below = 0
    for item in items:
        nested = org_depth_from_children(_nested_children(item))
        if nested > below:
            below = nested
    return 1 + below


def agent_count_from_children(children: Any) -> int:
    """Parent plus every manager and worker in the tree. Solo = 1."""
    return 1 + _count_descendants(children)


def _count_descendants(children: Any) -> int:
    n = 0
    for item in _child_nodes(children):
        n += 1
        n += _count_descendants(_nested_children(item))
    return n


def _sum_child_costs(children: Any) -> Any:
    total = 0.0
    any_cost = False
    for item in _child_nodes(children):
        raw = item.get("cost_usd")
        if raw is not None:
            try:
                total += float(raw)
                any_cost = True
            except (TypeError, ValueError):
                pass
        nested = _sum_child_costs(_nested_children(item))
        if nested is not None:
            total += float(nested)
            any_cost = True
    return total if any_cost else None


def _who_from_children(children: Any) -> str:
    items = _child_nodes(children)
    if not items:
        return SOLO_WHO_DID_WHAT
    parts: list[str] = []

    def _walk(nodes: list[dict[str, Any]], fallback_role: str) -> None:
        for i, item in enumerate(nodes):
            nested = _child_nodes(_nested_children(item))
            label = str(item.get("id") or item.get("name") or f"child-{i + 1}").strip()
            inferred = "manager" if nested else fallback_role
            role = str(
                item.get("role") or item.get("wrote") or item.get("artifact") or inferred
            ).strip()
            if label and role:
                parts.append(f"{label} {role}")
            elif label:
                parts.append(label)
            if nested:
                _walk(nested, "worker")

    _walk(items, "")
    return " / ".join(parts) if parts else SOLO_WHO_DID_WHAT


def _collect_models_used(model: str, models_raw: Any, children: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def _add(name: Any) -> None:
        n = str(name or "").strip()
        if n and n not in seen:
            seen.add(n)
            out.append(n)

    def _walk(nodes: Any) -> None:
        for item in _child_nodes(nodes):
            _add(item.get("model"))
            _walk(_nested_children(item))

    _add(model)
    if isinstance(models_raw, str):
        _add(models_raw)
    elif isinstance(models_raw, list):
        for item in models_raw:
            if isinstance(item, str):
                _add(item)
    _walk(children)
    return out


def extract_orchestration_meta(
    task_state: dict[str, Any] | None,
    *,
    model: str,
    parent_cost: float | None,
) -> dict[str, Any]:
    """Read child-loop / org-shape fields; default to solo (depth 0, 1 agent).

    Solo child spend is 0.0 (children never ran — not provider $0 / cost_unknown).
    When children ran and reported $0 / missing, apply cost_unknown (None).
    Tiny / solo jobs stay depth 0 and agent_count 1 — they must not grow an org.
    Depth-2 spawn may be absent; a stubbed manager tree still records shape.
    """
    solo = {
        "parent_cost_usd": parent_cost,
        "child_cost_usd": 0.0,
        "who_did_what": SOLO_WHO_DID_WHAT,
        "models_used": [model] if (model or "").strip() else [],
        "depth": 0,
        "agent_count": 1,
    }
    blobs = _task_state_blobs(task_state)
    if not blobs:
        return solo
    children = _first_present(blobs, "children")
    if not _has_children(children):
        children = _first_present(blobs, "managers")
    who = _first_present(blobs, "who_did_what")
    child_cost_raw = _first_present(blobs, "child_cost_usd")
    models_raw = _first_present(blobs, "models_used")
    depth_raw = _first_present(blobs, "depth")
    if depth_raw is None:
        depth_raw = _first_present(blobs, "org_depth")
    agent_count_raw = _first_present(blobs, "agent_count")
    has_children = _has_children(children)
    if (
        not has_children
        and who is None
        and child_cost_raw is None
        and models_raw is None
        and depth_raw is None
        and agent_count_raw is None
    ):
        return solo
    if has_children:
        raw = child_cost_raw if child_cost_raw is not None else _sum_child_costs(children)
        if raw is None:
            child_cost: float | None = 0.0
        else:
            norm = normalize_reported_cost(raw, source="children")
            child_cost = norm.cost_usd
        who_text = str(who).strip() if who is not None and str(who).strip() else _who_from_children(children)
        depth = _as_nonneg_int(depth_raw)
        if depth is None:
            depth = org_depth_from_children(children)
        agent_count = _as_nonneg_int(agent_count_raw)
        if agent_count is None:
            agent_count = agent_count_from_children(children)
    else:
        # No tree: stay solo even if a stub left stray org fields.
        child_cost = 0.0
        who_text = str(who).strip() if who is not None and str(who).strip() else SOLO_WHO_DID_WHAT
        depth = 0
        agent_count = 1
    return {
        "parent_cost_usd": parent_cost,
        "child_cost_usd": child_cost,
        "who_did_what": who_text,
        "models_used": _collect_models_used(model, models_raw, children),
        "depth": depth,
        "agent_count": agent_count,
    }


def _goal_escalate(model: str, rel: str, seed: str) -> str:
    return f"""Write a JSON cost-card with write_file to: {rel}

Required keys (exact):
{{
  "seed": "{seed}",
  "bench_model": "{model}",
  "task": "fail-then-escalate",
  "status": "ok",
  "notes": "cheap-first then escalate if needed"
}}

The seed must appear in the filename and the JSON body.
No questions. Finish the file.
"""


_SPREADSHEET = BenchTask(
    "spreadsheet",
    ".csv",
    _goal_spreadsheet,
    _heuristic_spreadsheet,
    timeout_sec=180,
    max_tokens=2048,
)

TASKS: dict[str, BenchTask] = {
    "tetris": BenchTask("tetris-html", ".html", _goal_tetris, _heuristic_tetris),
    "spreadsheet": _SPREADSHEET,
    "csv_report": _SPREADSHEET,  # alias
    "organize_dry_run": BenchTask(
        "organize-dry-run",
        ".json",
        _goal_organize,
        _heuristic_organize,
        timeout_sec=180,
        max_tokens=2048,
        special="organize_plan",
    ),
    "local_fact": BenchTask(
        "local-fact",
        ".json",
        _goal_local_fact,
        _heuristic_local_fact,
        timeout_sec=180,
        max_tokens=2048,
        max_tool_rounds=8,
        must_call=LOCAL_FACT_TOOLS,
        requires_artifact=True,
    ),
    "fail_then_escalate": BenchTask(
        "fail-then-escalate",
        ".json",
        _goal_escalate,
        _heuristic_escalate_card,
        timeout_sec=180,
        max_tokens=2048,
        special="fail_then_escalate",
    ),
    "windows_service_stub": BenchTask(
        "windows-service-stub",
        ".py",
        _goal_windows_service,
        _heuristic_windows_service,
        timeout_sec=180,
        max_tokens=2048,
        special="windows_service_stub",
    ),
    "two_file_split": BenchTask(
        "two-file-split",
        ".py",
        _goal_two_file_split,
        _heuristic_two_file_split,
        timeout_sec=180,
        max_tokens=2048,
        special="two_file_split",
        artifact_kinds=TWO_FILE_SPLIT_KINDS,
    ),
}

TASKS["tool_fact"] = TASKS["local_fact"]  # alias
TASKS["escalate_billing"] = TASKS["fail_then_escalate"]  # alias
TASKS["split_stub_readme"] = TASKS["two_file_split"]  # alias
for _math_id, _math_q, _math_ans in CHEAP_MATH_ITEMS:
    TASKS[_math_id] = _make_cheap_math_task(_math_id, _math_q, _math_ans)

DEFAULT_TASKS = (
    "tetris,spreadsheet,organize_dry_run,local_fact,fail_then_escalate,"
    "windows_service_stub,two_file_split"
)


def expand_task_ids(task_ids: list[str]) -> list[str]:
    """Expand aliases such as cheap_math → the 3 integer probes."""
    out: list[str] = []
    seen: set[str] = set()
    for tid in task_ids:
        group = CHEAP_MATH_IDS if tid in CHEAP_MATH_ALIASES else (tid,)
        for item in group:
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


def format_scorecard_footer(formula: str, lam: float) -> str:
    """ASCII-only footer so Windows cp1252 print does not crash on lambda."""
    return f"ours_composite (optional ranking, not AA): {formula}  lambda={lam}"


def format_scorecard_table(by_model: list[dict[str, Any]]) -> list[str]:
    """Headline table plus wall-clock seconds (elapsed_sec rollup)."""
    lines = [
        "| model | pass@1 | $ per success | escalate % | seconds | ours_composite |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for m in by_model:
        p1 = "—" if m.get("pass_at_1") is None else m.get("pass_at_1")
        usd = "cost_unknown" if m.get("cost_unknown") else (
            "—" if m.get("usd_per_success") is None else m.get("usd_per_success")
        )
        ep = "—" if m.get("escalate_pct") is None else m.get("escalate_pct")
        secs = "—" if m.get("seconds") is None else m.get("seconds")
        ours = "—" if m.get("ours_composite") is None else m.get("ours_composite")
        lines.append(f"| {m['model']} | {p1} | {usd} | {ep} | {secs} | {ours} |")
    return lines


@dataclass
class BenchRow:
    model: str
    task: str
    ok: bool
    elapsed_sec: float
    status: str
    artifact: str | None
    artifact_bytes: int
    cost_usd: float | None
    cost_unknown: bool
    cost_source: str
    escalate: bool
    summary: str
    heuristics_pass: bool
    run_id: str
    seed: str
    tools_used: list[str] = field(default_factory=list)
    attempts: list[dict[str, Any]] | None = None
    attempt_count: int = 1
    escalated_to: str | None = None
    parent_cost_usd: float | None = None
    child_cost_usd: float | None = 0.0
    models_used: list[str] = field(default_factory=list)
    who_did_what: str = ""
    depth: int = 0
    agent_count: int = 1
    artifacts: list[str] = field(default_factory=list)


def _token() -> str:
    return (os.environ.get("BRIDGE_TOKEN") or os.environ.get("JARVIS_BRIDGE_TOKEN") or "").strip()


def _req(base: str, method: str, path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Jarvis-Bridge-Token": _token(),
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def _find_artifact(rel: str) -> tuple[str | None, int]:
    name = Path(rel).name
    for root in _workspace_candidates():
        cand = root / rel
        if cand.is_file():
            return str(cand), cand.stat().st_size
        loose = root / "Exports" / name
        if loose.is_file():
            return str(loose), loose.stat().st_size
    return None, 0


def _pick_artifact(arts: list[Any], rel: str, *, fallback_first: bool = False) -> tuple[str | None, int]:
    """Prefer the unique relative path among Bridge artifacts, else disk search.

    ``fallback_first`` matches the old single-file runner (use arts[0] when no
    name match). Two-file tasks must leave this off so one file cannot count
    as both the stub and the README.
    """
    picked = None
    if arts:
        for a in arts:
            if not isinstance(a, dict):
                continue
            ap = str(a.get("path") or "")
            ar = str(a.get("rel") or "")
            if rel.replace("\\", "/") in ar.replace("\\", "/") or Path(ap).name == Path(rel).name:
                picked = a
                break
        if picked is None and fallback_first and isinstance(arts[0], dict):
            picked = arts[0]
    if picked:
        path = picked.get("path")
        nbytes = int(picked.get("bytes") or 0)
        if path:
            return str(path), nbytes
    return _find_artifact(rel)


def run_one(base: str, model: str, task: BenchTask, run_id: str, timeout_sec: int) -> BenchRow:
    rels = artifact_rels_for(task, model, run_id)
    rel = rels[0]
    t0 = time.time()
    created = _req(
        base,
        "POST",
        "/api/bridge/v1/tasks",
        {
            "goal": task.goal(model, rel, run_id),
            "source": "bench",
            "priority": "high",
            "engine": "jarvis",
            "timeout_sec": timeout_sec,
            "confirm_policy": "auto_if_allowed",
            "context": {
                "model": model,
                "timeout_seconds": min(timeout_sec, 240),
                "max_tool_rounds": min(task.max_tool_rounds, 16),
                "max_tokens": task.max_tokens,
            },
        },
    )
    tid = created["task_id"]
    status = "queued"
    task_state: dict = {}
    while time.time() - t0 < timeout_sec:
        task_state = _req(base, "GET", f"/api/bridge/v1/tasks/{tid}")
        status = task_state.get("status") or "unknown"
        if status in {"done", "failed", "error", "cancelled", "canceled"}:
            break
        time.sleep(2)
    elapsed = round(time.time() - t0, 2)
    result = task_state.get("result") or {}
    arts = result.get("artifacts") or []
    multi = len(rels) > 1
    found: list[tuple[str | None, int]] = [
        _pick_artifact(arts, r, fallback_first=not multi) for r in rels
    ]
    artifact = next((p for p, _n in found if p), None)
    nbytes = sum(n for _p, n in found)
    if artifact is None and arts and not multi:
        first = arts[0] if isinstance(arts[0], dict) else {}
        artifact = first.get("path")
        nbytes = int(first.get("bytes") or 0) if artifact else 0
    data = result.get("data") or {}
    raw_cost = data.get("cost_usd")
    norm = normalize_reported_cost(raw_cost, source="openrouter" if raw_cost is not None else "unavailable")
    route = data.get("model_route") if isinstance(data.get("model_route"), dict) else {}
    escalate = bool(route.get("escalate"))
    path_obj = Path(artifact) if artifact else None
    tools_used = extract_tools_used(task_state)
    extra_artifacts = [p for p, _n in found if p]
    if task.special == "organize_plan":
        heuristics = judge_organize(seed=run_id, task_state=task_state, artifact=path_obj)
    elif task.special == "windows_service_stub":
        heuristics = judge_windows_service_stub(seed=run_id, artifact=path_obj)
    elif task.special == "two_file_split":
        stub_path = Path(found[0][0]) if found and found[0][0] else None
        readme_path = Path(found[1][0]) if len(found) > 1 and found[1][0] else None
        heuristics = judge_two_file_split(
            seed=run_id, stub=stub_path, readme=readme_path, task_state=task_state
        )
    elif task.must_call:
        heuristics = judge_local_fact(seed=run_id, task_state=task_state, artifact=path_obj)
        if task.requires_artifact and (path_obj is None or not path_obj.is_file()):
            heuristics = False
    else:
        heuristics = task.heuristic(path_obj, run_id, model) if path_obj else False
    ok = status == "done" and heuristics
    summary = str(result.get("summary") or task_state.get("error") or "")[:400]
    orch = extract_orchestration_meta(task_state, model=model, parent_cost=norm.cost_usd)
    return BenchRow(
        model=model,
        task=task.id,
        ok=ok,
        elapsed_sec=elapsed,
        status=status,
        artifact=artifact,
        artifact_bytes=nbytes,
        cost_usd=norm.cost_usd,
        cost_unknown=norm.cost_unknown,
        cost_source=norm.cost_source,
        escalate=escalate,
        summary=summary,
        heuristics_pass=heuristics,
        run_id=run_id,
        seed=run_id,
        tools_used=tools_used,
        parent_cost_usd=orch["parent_cost_usd"],
        child_cost_usd=orch["child_cost_usd"],
        models_used=orch["models_used"],
        who_did_what=orch["who_did_what"],
        depth=int(orch["depth"]),
        agent_count=int(orch["agent_count"]),
        artifacts=extra_artifacts,
    )


def pick_escalate_model(models: list[str], cheap: str) -> str:
    """Second listed model, else a stronger default that is not the cheap one."""
    for m in models:
        if m and m != cheap:
            return m
    if cheap != DEFAULT_ESCALATE_MODEL:
        return DEFAULT_ESCALATE_MODEL
    return "anthropic/claude-sonnet-4"


def run_fail_then_escalate(
    base: str,
    cheap: str,
    stronger: str,
    task: BenchTask,
    run_id: str,
    timeout_sec: int,
) -> dict[str, Any]:
    """Cheap first; on fail, retry stronger and bill both attempts (ORCH-336)."""
    first = run_one(base, cheap, task, run_id, timeout_sec)
    attempts = [asdict(first)]
    if first.ok:
        return fold_attempt_rows(attempts, model=cheap, task=task.id)
    second = run_one(base, stronger, task, run_id, timeout_sec)
    second.escalate = True
    attempts.append(asdict(second))
    return fold_attempt_rows(attempts, model=cheap, task=task.id)


def _error_row(model: str, task_id: str, run_id: str, exc: BaseException) -> BenchRow:
    return BenchRow(
        model=model,
        task=task_id,
        ok=False,
        elapsed_sec=0.0,
        status="error",
        artifact=None,
        artifact_bytes=0,
        cost_usd=None,
        cost_unknown=True,
        cost_source="error",
        escalate=False,
        summary=str(exc)[:400],
        heuristics_pass=False,
        run_id=run_id,
        seed=run_id,
        parent_cost_usd=None,
        child_cost_usd=0.0,
        models_used=[model] if model else [],
        who_did_what=SOLO_WHO_DID_WHAT,
        depth=0,
        agent_count=1,
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8787")
    ap.add_argument(
        "--models",
        default="openai/gpt-4.1-mini,openai/gpt-4.1,google/gemini-2.5-flash",
    )
    ap.add_argument("--tasks", default=DEFAULT_TASKS, help="Comma-separated task ids (cheap_math expands to 3)")
    ap.add_argument(
        "--include-cheap-math",
        action="store_true",
        help="Append the 3 cheap_math integer probes to --tasks",
    )
    ap.add_argument(
        "--cheap-math-only",
        action="store_true",
        help="Run only the 3 cheap_math integer probes",
    )
    ap.add_argument("--timeout-sec", type=int, default=0, help="Override per-task timeout (0=task default)")
    ap.add_argument("--out", default=str(INDEX_LATEST))
    ap.add_argument("--run-id", default="")
    ap.add_argument(
        "--escalate-model",
        default="",
        help="Stronger model for fail_then_escalate (default: second --models or gpt-4.1)",
    )
    args = ap.parse_args(argv)
    if not _token():
        raise SystemExit("Set BRIDGE_TOKEN")
    run_id = (args.run_id or "").strip() or make_run_id()
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if args.cheap_math_only:
        task_ids = list(CHEAP_MATH_IDS)
    else:
        task_ids = expand_task_ids([t.strip() for t in args.tasks.split(",") if t.strip()])
        if args.include_cheap_math:
            task_ids = expand_task_ids(task_ids + ["cheap_math"])
    unknown = [t for t in task_ids if t not in TASKS]
    if unknown:
        raise SystemExit(f"Unknown tasks {unknown}; known: {sorted(TASKS)}")
    regular_ids = [t for t in task_ids if TASKS[t].special != "fail_then_escalate"]
    escalate_ids = [t for t in task_ids if TASKS[t].special == "fail_then_escalate"]
    rows: list[dict[str, Any]] = []
    for model in models:
        for tid in regular_ids:
            spec = TASKS[tid]
            timeout = args.timeout_sec or spec.timeout_sec
            print(f"==> {model} / {spec.id}")
            try:
                row = run_one(args.base_url, model, spec, run_id, timeout)
            except Exception as exc:
                row = _error_row(model, spec.id, run_id, exc)
            rows.append(asdict(row))
            print(json.dumps(asdict(row), indent=2))
    for tid in escalate_ids:
        spec = TASKS[tid]
        timeout = args.timeout_sec or spec.timeout_sec
        cheap = models[0] if models else "openai/gpt-4.1-mini"
        stronger = (args.escalate_model or "").strip() or pick_escalate_model(models, cheap)
        print(f"==> fail-then-escalate {cheap} -> {stronger} / {spec.id}")
        try:
            folded = run_fail_then_escalate(
                args.base_url, cheap, stronger, spec, run_id, timeout
            )
        except Exception as exc:
            folded = asdict(_error_row(cheap, spec.id, run_id, exc))
        rows.append(folded)
        print(json.dumps(folded, indent=2))
    created_at = time.time()
    payload = index_payload(
        results=rows,
        run_id=run_id,
        created_at=created_at,
        extra={
            "price_table_note": "BENCH_PRICE_PER_MTOK is reference only; prefer cost_usd from OpenRouter",
            "price_per_mtok_usd": BENCH_PRICE_PER_MTOK,
            "tasks": [TASKS[t].id for t in task_ids],
        },
    )
    out = Path(args.out)
    _write_json(out, payload)
    print("wrote", out)
    index_path = INDEX_LATEST
    if out.resolve() != index_path.resolve():
        _write_json(index_path, payload)
        print("wrote", index_path)
    # Keep Tetris JSON so older router paths still work when tetris ran.
    if any(r.get("task") == "tetris-html" for r in rows):
        tetris_rows = [r for r in rows if r.get("task") == "tetris-html"]
        tetris_payload = {
            "task": "tetris-html",
            "created_at": created_at,
            "run_id": run_id,
            "price_table_note": payload["price_table_note"],
            "price_per_mtok_usd": BENCH_PRICE_PER_MTOK,
            "results": tetris_rows,
        }
        _write_json(TETRIS_FALLBACK_OUT, tetris_payload)
        print("wrote", TETRIS_FALLBACK_OUT)

    print()
    for line in format_scorecard_table(payload["by_model"]):
        print(line)
    print("\nheadline: pass@1, $ per success (failures stay in $; known-cost rows only), escalate %")
    print("seconds = wall-clock E2E (elapsed_sec summed per model)")
    print(format_scorecard_footer(payload["ours_composite_formula"], TIME_PENALTY_USD_PER_SEC))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
