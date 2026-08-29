"""Jarvis child agents (ORCH-339) + who-did-what journal (ORCH-340).

Short-lived Jarvis loops the parent can spawn for one user job. Locked rules:

1. Lifetime child cap is ``pick_child_count()`` (pay-to-spawn), ceiling 4.
   The parent model does not vote N. N < 2 stays solo (N=1 coerced to 0).
2. Cheap model via model_router / scorecard. Escalate only on child failure.
3. Workers cannot spawn (no free swarm). Managers may hire workers for
   their assigned slice only (ORCH-350). ``pick_org()`` (ORCH-346) sets
   allowed depth when present; otherwise the locked fallback: span 4,
   DEPTH_CEILING=4, ABSOLUTE_WALL=20, N<2 and D<2 → solo.
4. Child results and inter-agent messages are tainted (see taint.py).
5. Writes still go through L2 confirm. Children do not skip it.
6. If orchestration would cost more than solo, do it solo.
7. Parent writes one daily-journal line: who did what (ids, models, $).

This is not a second agent runtime. Children reuse ``JarvisLocalAgent`` and
``ToolGateway``. Prime RPC, inbound Slack/GitHub, and infinite swarms are
out of scope (ORCH-342 owns the two-artifact bench task).
"""

from __future__ import annotations

import contextvars
import logging
import math
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

log = logging.getLogger("jarvis.children")

CHILD_CEILING = 4
MAX_CHILDREN = CHILD_CEILING  # hard ceiling; lifetime cap is pick_child_count()
ORG_SPAN = 4
DEPTH_CEILING = 4
ABSOLUTE_WALL = 20
GOAL_MAX_CHARS = 2000
TEXT_MAX_CHARS = 2000
MAX_BUDGET_SECONDS = 600.0
MAX_BUDGET_USD = 2.0
PARENT_OVERHEAD_USD = 0.002
ROLE_MANAGER = "manager"
ROLE_WORKER = "worker"
CHILD_ROLES = frozenset({ROLE_MANAGER, ROLE_WORKER})

_WORD_COUNTS = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
}
_HIRE_N_WORDS = {
    **_WORD_COUNTS,
    "nine": 9,
    "ten": 10,
}
# Create-N games/pages count as pieces even without the word "files".
_N_ITEMS_RE = re.compile(
    r"\b(two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
    r"(?:independent\s+)?(?:work\s+)?"
    r"(?:(?:different|pretty|distinct|unique|new|tetris|html)\s+){0,3}"
    r"(?:files?|pieces?|artifacts?|items?|slots?|games?|pages?|html|"
    r"reports?|variants?|copies|topics?|questions?)\b",
    re.I,
)
_HIRE_N_RE = re.compile(
    r"\b(?:hire\s+)?(\d+|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(?:openrouter\s+)?(?:children|child|helpers?|agents?|workers?)\b",
    re.I,
)
_PATH_RE = re.compile(
    r"(?:Exports|Scripts|Inbox|Documents|Downloads)/[^\s,;:'\"<>]+|"
    r"(?<![/\w])[\w.-]+\.(?:py|md|html|htm|csv|txt|json|xlsx|xls|ps1|js|ts|tsx)\b",
    re.I,
)
_SPLIT_PAIR_RE = re.compile(
    r"\bone\s+child\s+writes\b.+\b(?:one|another)\s+writes\b",
    re.I | re.S,
)
_LABELED_FILE_RE = re.compile(r"\bfiles?\s+[A-Z0-9]\b", re.I)
_LAYER_ASK_RE = re.compile(
    r"\b(\d+|two|three|four|five|six|seven|eight|nine|ten|twenty)\s*-?\s*layers?\b",
    re.I,
)
_LAYER_WORDS = {
    **_WORD_COUNTS,
    "nine": 9,
    "ten": 10,
    "twenty": 20,
}

# Locked error codes (ORCH-338 / PR #26). DEPTH_WALL is ORCH-350 (refuse > 20).
CHILD_LIMIT = "CHILD_LIMIT"
STAY_SOLO = "STAY_SOLO"
CHILD_FORBIDDEN = "CHILD_FORBIDDEN"
INVALID_BUDGET = "INVALID_BUDGET"
GOAL_EMPTY = "GOAL_EMPTY"
GOAL_TOO_LONG = "GOAL_TOO_LONG"
UNKNOWN_CHILD = "UNKNOWN_CHILD"
CHILD_NOT_RUNNING = "CHILD_NOT_RUNNING"
TEXT_EMPTY = "TEXT_EMPTY"
TEXT_TOO_LONG = "TEXT_TOO_LONG"
DEPTH_WALL = "DEPTH_WALL"

# Workers never see spawn tools. Managers may (ORCH-350). Prime / parent
# memory writes stay forbidden for every child.
SPAWN_TOOL_NAMES = frozenset({"spawn_child", "message_child", "wait_child"})
CHILD_MEMORY_TOOLS = frozenset(
    {"remember", "forget_memory", "save_mission_summary"}
)
CHILD_ALWAYS_FORBIDDEN = frozenset({"dispatch_prime"}) | CHILD_MEMORY_TOOLS
# Worker view (default). Gateway uses role, not this set alone.
CHILD_FORBIDDEN_TOOLS = SPAWN_TOOL_NAMES | CHILD_ALWAYS_FORBIDDEN
TERMINAL_STATUSES = frozenset({"done", "failed", "budget_seconds", "budget_usd"})


def err(code: str, message: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "error": code}
    if message:
        out["message"] = message
    return out


def caller_is_child(source: str | None = None) -> bool:
    if current_child_id():
        return True
    src = (source or current_tool_source() or "").strip()
    return src.startswith("child:")


def child_id_from_source(source: str | None = None) -> str | None:
    cid = current_child_id()
    if cid:
        return cid
    src = (source or current_tool_source() or "").strip()
    if src.startswith("child:"):
        return src.split(":", 1)[1].strip() or None
    return None


def resolve_caller_child(source: str | None = None) -> ChildRecord | None:
    cid = child_id_from_source(source)
    if not cid:
        return None
    try:
        return get_supervisor().get_child(cid)
    except Exception:
        return None


def caller_child_role(source: str | None = None) -> str | None:
    rec = resolve_caller_child(source)
    if rec is None:
        return None
    role = (rec.role or "").strip().lower()
    return role if role in CHILD_ROLES else None


def caller_may_use_child_api(
    source: str | None = None, *, spawning: bool = False
) -> bool:
    """Managers may message/wait their slice. Spawn needs remaining_depth."""
    rec = resolve_caller_child(source)
    if rec is None or (rec.role or "").strip().lower() != ROLE_MANAGER:
        return False
    if spawning:
        return int(rec.remaining_depth or 0) > 0
    return True


def caller_may_spawn(source: str | None = None) -> bool:
    if not caller_is_child(source):
        return True
    return caller_may_use_child_api(source, spawning=True)


def artifact_kind(path: str) -> str:
    name = str(path or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." in name:
        ext = name.rsplit(".", 1)[-1].strip().lower()
        if ext:
            return ext
    return "file"

ChildRunner = Callable[["ChildRecord", "ChildSupervisor"], None]

_current_child_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "jarvis_child_id", default=None
)
_current_parent_job: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "jarvis_parent_job", default=None
)
_current_tool_source: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "jarvis_tool_source", default=None
)

_supervisor = None
_supervisor_lock = threading.Lock()


def current_child_id() -> str | None:
    return _current_child_id.get()


def current_parent_job() -> str | None:
    return _current_parent_job.get()


def current_tool_source() -> str | None:
    return _current_tool_source.get()


def set_tool_source(source: str | None) -> contextvars.Token[str | None]:
    return _current_tool_source.set((source or "").strip() or None)


def reset_tool_source(token: contextvars.Token[str | None]) -> None:
    _current_tool_source.reset(token)


def child_tool_specs(
    specs: list[dict[str, Any]] | None = None,
    *,
    role: str | None = None,
    remaining_depth: int = 0,
) -> list[dict[str, Any]]:
    """TOOL_SPECS minus Prime / parent-memory writes.

    Workers omit spawn tools. Managers keep them when they still have
    remaining_depth (ORCH-350). Default role is worker (safe).
    """
    if specs is None:
        from app.jarvis.tools import TOOL_SPECS

        specs = TOOL_SPECS
    allow_spawn = (
        (role or ROLE_WORKER).strip().lower() == ROLE_MANAGER
        and int(remaining_depth or 0) > 0
    )
    out: list[dict[str, Any]] = []
    for spec in specs:
        fn = spec.get("function") if isinstance(spec, dict) else None
        name = str((fn or {}).get("name") or "")
        if name in CHILD_ALWAYS_FORBIDDEN:
            continue
        if name in SPAWN_TOOL_NAMES and not allow_spawn:
            continue
        out.append(spec)
    return out


def is_spawn_tool(name: str) -> bool:
    return (name or "").strip() in SPAWN_TOOL_NAMES


def is_child_forbidden_tool(
    name: str,
    *,
    role: str | None = None,
    remaining_depth: int = 0,
    source: str | None = None,
) -> bool:
    """True when this child must not run ``name``.

    Workers: spawn + Prime + memory. Managers: Prime + memory; spawn
    tools only if remaining_depth is 0. Gateway prefers ``source``.
    """
    tool = (name or "").strip()
    if tool in CHILD_ALWAYS_FORBIDDEN:
        return True
    if tool not in SPAWN_TOOL_NAMES:
        return False
    if source is not None or role is None:
        rec = resolve_caller_child(source)
        if rec is not None:
            role = rec.role
            remaining_depth = rec.remaining_depth
    if (role or "").strip().lower() == ROLE_MANAGER and int(remaining_depth or 0) > 0:
        return False
    return True


def child_must_block_tool(tool: str, source: str | None = None) -> bool:
    """Gateway entry: CHILD_FORBIDDEN when a child must not run this tool."""
    if not caller_is_child(source):
        return False
    return is_child_forbidden_tool(tool, source=source)


def isolated_child_memory() -> Any:
    """Throwaway SQLite memory so child prose cannot land in the parent store."""
    import tempfile
    from pathlib import Path

    from app.jarvis.memory import JarvisMemory

    root = Path(tempfile.mkdtemp(prefix="jarvis-child-mem-"))
    return JarvisMemory(root / "child.db")


def pick_child_model(
    goal: str,
    *,
    prior_failures: int = 0,
    workspace_root: Any = None,
    repo_root: Any = None,
) -> Any:
    """Default helper from Settings, else cheap scorecard. Escalate once.

    Honors a stored Settings helper (the Talk page pick). ``JARVIS_MODEL_PIN``
    env still does not steal the child onto an expensive model (ORCH-338).
    A locked helper is a hard pin and does not escalate.
    """
    from app.jarvis.model_router import ModelRouteChoice, _ladder, classify_task
    from app.jarvis.settings_store import get_model_lock, load

    stored = load(workspace_root).get("model")
    helper = stored.strip() if isinstance(stored, str) and stored.strip() else ""
    if helper and "auto" in helper.lower():
        helper = ""
    locked = bool(helper) and get_model_lock(workspace_root)
    if locked:
        return ModelRouteChoice(
            model=helper,
            reason="child hard pin (settings helper)",
            task_class=classify_task(goal or ""),
            preference="cheap_fast",
            pinned=True,
            escalate=False,
            metadata={"ladder": [helper], "prior_failures": int(prior_failures or 0)},
        )

    ladder = _ladder(repo_root)
    if helper:
        ladder = [helper] + [m for m in ladder if m != helper]
    if not ladder:
        ladder = ["openai/gpt-4.1-mini"]
    escalate = False
    idx = 0
    if max(0, int(prior_failures)) > 0 and len(ladder) > 1:
        idx = 1
        escalate = True
    model = ladder[idx]
    reason = f"child cheap_fast; ladder_idx={idx}"
    if helper and idx == 0:
        reason += "; default helper"
    if escalate:
        reason += "; escalate_after_failures=1"
    return ModelRouteChoice(
        model=model,
        reason=reason,
        task_class=classify_task(goal or ""),
        preference="cheap_fast",
        pinned=False,
        escalate=escalate,
        metadata={"ladder": list(ladder), "prior_failures": int(prior_failures or 0)},
    )


def lookup_usd_per_success(model: str, *, repo_root: Any = None) -> float | None:
    try:
        from app.jarvis.cost_index import load_index_data, _rows_from_index, _has_usd_per_success

        rows = _rows_from_index(load_index_data(repo_root))
    except Exception:
        return None
    for row in rows:
        if row.model == model and _has_usd_per_success(row):
            try:
                return float(row.usd_per_success)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None
    return None


def estimate_solo_usd(
    goal: str,
    *,
    override: float | None = None,
    workspace_root: Any = None,
    repo_root: Any = None,
) -> float | None:
    """Known solo USD from scorecard, or an explicit override. None if unknown."""
    if override is not None:
        return max(0.0, float(override))
    from app.jarvis.model_router import route_model

    choice = route_model(goal=goal or "", workspace_root=workspace_root, repo_root=repo_root)
    return lookup_usd_per_success(choice.model, repo_root=repo_root)


def estimate_child_expected_usd(
    budget_usd: float,
    *,
    model: str | None = None,
    repo_root: Any = None,
) -> float | None:
    """Known child spend from scorecard, capped by budget. None if unknown."""
    if not model:
        return None
    priced = lookup_usd_per_success(model, repo_root=repo_root)
    if priced is None:
        return None
    cap = max(0.0, float(budget_usd))
    return min(cap, priced) if cap > 0 else priced


def orchestration_would_cost_more(
    *,
    goal: str,
    new_budget_usd: float,
    existing_expected_usd: float = 0.0,
    new_model: str | None = None,
    solo_override: float | None = None,
    split_override: float | None = None,
    workspace_root: Any = None,
    repo_root: Any = None,
) -> tuple[bool, float | None, float | None]:
    """STAY_SOLO only when split is *known* to cost more than solo (ORCH-338)."""
    solo = estimate_solo_usd(
        goal, override=solo_override, workspace_root=workspace_root, repo_root=repo_root
    )
    if split_override is not None:
        split: float | None = max(0.0, float(split_override))
    else:
        child_exp = estimate_child_expected_usd(
            new_budget_usd, model=new_model, repo_root=repo_root
        )
        if child_exp is None:
            split = None
        else:
            split = PARENT_OVERHEAD_USD + max(0.0, float(existing_expected_usd)) + child_exp
    if solo is None or split is None:
        return False, split, solo
    return split > solo, split, solo


def pick_child_count(
    *,
    independent_work_items: int | None = None,
    remaining_usd: float | None = None,
    child_unit_cost: float | None = None,
    remaining_seconds: float | None = None,
    child_unit_seconds: float | None = None,
    learned_k_from_scorecard: int | None = None,
    ceiling: int = CHILD_CEILING,
) -> int:
    """Pay-to-spawn N. The parent model does not vote this number.

    N = min(
      independent_work_items,
      floor(remaining_usd / child_unit_cost),
      floor(remaining_seconds / child_unit_seconds),
      learned_k_from_scorecard,
      CEILING,  # 4
    )
    Unknown inputs are omitted (they do not constrain). N < 2 becomes 0
    (one child is just a more expensive solo).
    """
    caps = [max(0, int(ceiling))]
    if independent_work_items is not None:
        caps.append(max(0, int(independent_work_items)))
    if (
        remaining_usd is not None
        and child_unit_cost is not None
        and float(child_unit_cost) > 0
    ):
        caps.append(int(math.floor(float(remaining_usd) / float(child_unit_cost))))
    if (
        remaining_seconds is not None
        and child_unit_seconds is not None
        and float(child_unit_seconds) > 0
    ):
        caps.append(int(math.floor(float(remaining_seconds) / float(child_unit_seconds))))
    if learned_k_from_scorecard is not None:
        caps.append(max(0, int(learned_k_from_scorecard)))
    n = min(caps) if caps else 0
    if n < 2:
        return 0
    return n


def count_independent_work_items(goal: str | None) -> int | None:
    """Pieces in ``goal`` that do not wait on each other. None if unknown.

    Unknown must be omitted from ``pick_child_count`` (do not invent a
    count of 1). Only an explicit light-task pattern is a known solo job.
    ``classify_task``'s default-light fallback is not a count.
    """
    text = (goal or "").strip()
    if not text:
        return None
    from app.jarvis.model_router import _LIGHT_PATTERNS

    if any(pat.search(text) for pat in _LIGHT_PATTERNS):
        return 1
    counts: list[int] = []
    words = [m.group(1) for m in _N_ITEMS_RE.finditer(text)]
    for raw in words:
        key = raw.lower()
        if key in _HIRE_N_WORDS:
            counts.append(_HIRE_N_WORDS[key])
        else:
            try:
                counts.append(int(key))
            except ValueError:
                pass
    for match in _HIRE_N_RE.finditer(text):
        raw = match.group(1).lower()
        if raw in _HIRE_N_WORDS:
            counts.append(_HIRE_N_WORDS[raw])
            continue
        try:
            counts.append(int(raw))
        except ValueError:
            pass
    paths = {
        m.group(0).rstrip(").,;\"'")
        for m in _PATH_RE.finditer(text)
        if m.group(0).rstrip(").,;\"'")
    }
    # Directory-only hits like "Exports/" are not a piece.
    files = {p for p in paths if "/" not in p or p.rsplit("/", 1)[-1]}
    files = {p for p in files if not p.endswith("/")}
    if files:
        counts.append(len(files))
    labeled = {m.group(0).lower() for m in _LABELED_FILE_RE.finditer(text)}
    if labeled:
        counts.append(len(labeled))
    if _SPLIT_PAIR_RE.search(text):
        counts.append(2)
    if not counts:
        return None
    return max(counts)


def count_requested_layers(goal: str | None) -> int | None:
    """User/goal text asking for N layers. Caps the plan; does not vote D up."""
    text = (goal or "").strip()
    if not text:
        return None
    hits: list[int] = []
    for match in _LAYER_ASK_RE.finditer(text):
        raw = match.group(1).lower()
        if raw in _LAYER_WORDS:
            hits.append(_LAYER_WORDS[raw])
            continue
        try:
            hits.append(int(raw))
        except ValueError:
            pass
    return max(hits) if hits else None


@dataclass
class OrgPlan:
    """Allowed org chart. ``pick_org()`` (ORCH-346) is the source when present."""

    depth: int
    widths: list[int] = field(default_factory=list)
    n: int = 0
    wall_refused: bool = False
    source: str = "fallback"


_PICK_ORG_KW = frozenset(
    {
        "goal",
        "work_tree",
        "independent_work_items",
        "remaining_usd",
        "child_unit_cost",
        "remaining_seconds",
        "child_unit_seconds",
        "learned_k_from_scorecard",
        "learned_depth_from_scorecard",
        "parent_span_usd",
        "manager_unit_cost",
        "repo_root",
        "span",
        "depth_ceiling",
        "absolute_wall",
    }
)


def _coerce_org_plan(raw: Any) -> OrgPlan | None:
    """Accept OrgChart (as_dict), OrgPlan, or {depth, widths[]}."""
    if raw is None:
        return None
    if isinstance(raw, OrgPlan):
        return raw
    as_dict = getattr(raw, "as_dict", None)
    if callable(as_dict):
        try:
            raw = as_dict()
        except Exception:
            raw = None
    if raw is not None and not isinstance(raw, dict):
        if hasattr(raw, "depth") and hasattr(raw, "widths"):
            raw = {"depth": getattr(raw, "depth"), "widths": getattr(raw, "widths")}
        else:
            return None
    if not isinstance(raw, dict):
        return None
    try:
        depth = int(raw.get("depth") or 0)
    except (TypeError, ValueError):
        return None
    widths_raw = raw.get("widths") or []
    widths: list[int] = []
    if isinstance(widths_raw, (list, tuple)):
        for item in widths_raw:
            try:
                widths.append(max(0, int(item)))
            except (TypeError, ValueError):
                continue
    try:
        n = int(raw.get("n") if raw.get("n") is not None else (widths[0] if widths else 0))
    except (TypeError, ValueError):
        n = widths[0] if widths else 0
    return OrgPlan(
        depth=max(0, depth),
        widths=widths,
        n=max(0, n),
        wall_refused=bool(raw.get("wall_refused")),
        source=str(raw.get("source") or "pick_org"),
    )


def _clamp_org_plan(plan: OrgPlan, *, apply_ceiling: bool = True) -> OrgPlan:
    depth = max(0, int(plan.depth))
    wall = False
    if depth > ABSOLUTE_WALL:
        wall = True
        depth = ABSOLUTE_WALL
    if apply_ceiling:
        depth = min(depth, DEPTH_CEILING)
    return OrgPlan(
        depth=depth,
        widths=list(plan.widths),
        n=max(0, int(plan.n)),
        wall_refused=bool(plan.wall_refused or wall),
        source=plan.source,
    )


def _call_pick_org(**kwargs: Any) -> OrgPlan | None:
    """Call ``app.jarvis.org.pick_org`` with the kwargs it actually accepts.

    Do not pass ``ceiling`` / ``requested_depth`` / ``learned_d_from_scorecard``.
    ``OrgChart`` is coerced via ``as_dict()``.
    """
    try:
        from app.jarvis.org import pick_org as fn
    except ImportError:
        fn = globals().get("pick_org")
    if not callable(fn):
        return None
    accepted = {k: v for k, v in kwargs.items() if k in _PICK_ORG_KW}
    try:
        raw = fn(**accepted)
    except Exception:
        log.debug("pick_org() raised; using locked fallback", exc_info=True)
        return None
    plan = _coerce_org_plan(raw)
    if plan is None:
        return None
    plan.source = "pick_org"
    return _clamp_org_plan(plan, apply_ceiling=True)


def _work_agent_depth(
    items: int | None,
    n: int,
    *,
    span: int = ORG_SPAN,
    ceiling: int = DEPTH_CEILING,
) -> int:
    """Agent hops from the work tree. Over-span inserts a manager layer."""
    span = max(2, int(span))
    ceiling = max(0, int(ceiling))
    if items is not None and items <= 1:
        return 0
    if n < 2 and (items is None or items <= span):
        return 0
    if items is None:
        return 1 if n >= 2 else 0
    if items <= span:
        return 1 if n >= 2 else 0
    depth = 0
    remaining = int(items)
    while remaining > 1:
        depth += 1
        remaining = int(math.ceil(remaining / span))
        if depth >= ceiling:
            break
    return depth


def _fallback_org(
    *,
    goal: str = "",
    independent_work_items: int | None = None,
    remaining_usd: float | None = None,
    child_unit_cost: float | None = None,
    remaining_seconds: float | None = None,
    child_unit_seconds: float | None = None,
    learned_k_from_scorecard: int | None = None,
    learned_depth_from_scorecard: int | None = None,
    span: int = ORG_SPAN,
    depth_ceiling: int = DEPTH_CEILING,
    absolute_wall: int = ABSOLUTE_WALL,
    **_ignored: Any,
) -> OrgPlan:
    """Locked ORCH-345 rules if pick_org cannot be imported."""
    items = independent_work_items
    if items is None and goal:
        items = count_independent_work_items(goal)
    n = pick_child_count(
        independent_work_items=items,
        remaining_usd=remaining_usd,
        child_unit_cost=child_unit_cost,
        remaining_seconds=remaining_seconds,
        child_unit_seconds=child_unit_seconds,
        learned_k_from_scorecard=learned_k_from_scorecard,
        ceiling=CHILD_CEILING,
    )
    asked = count_requested_layers(goal) if goal else None
    wall = asked is not None and int(asked) > int(absolute_wall)
    work_d = _work_agent_depth(items, n, span=span, ceiling=depth_ceiling)
    caps = [work_d, max(0, int(depth_ceiling)), max(0, int(absolute_wall))]
    if learned_depth_from_scorecard is not None:
        caps.append(max(0, int(learned_depth_from_scorecard)))
    depth = min(caps) if caps else 0
    if depth < 2 and n < 2:
        depth = 0
        n = 0
    widths: list[int] = []
    if depth >= 1:
        if items is not None and items > span and depth >= 2:
            managers = min(n, int(math.ceil(items / span))) if n else 0
            widths.append(max(0, managers))
            per = int(math.ceil(items / max(1, managers))) if managers else 0
            widths.append(min(CHILD_CEILING, span, per))
        else:
            widths.append(n)
    return _clamp_org_plan(
        OrgPlan(
            depth=max(0, int(depth)),
            widths=widths,
            n=n,
            wall_refused=wall,
            source="fallback",
        ),
        apply_ceiling=True,
    )


def resolve_org(
    *,
    goal: str = "",
    independent_work_items: int | None = None,
    remaining_usd: float | None = None,
    child_unit_cost: float | None = None,
    remaining_seconds: float | None = None,
    child_unit_seconds: float | None = None,
    learned_k_from_scorecard: int | None = None,
    learned_depth_from_scorecard: int | None = None,
    parent_span_usd: float | None = None,
    manager_unit_cost: float | None = None,
    repo_root: Any = None,
    span: int = ORG_SPAN,
    depth_ceiling: int = DEPTH_CEILING,
    absolute_wall: int = ABSOLUTE_WALL,
) -> OrgPlan:
    """Allowed depth/widths from ``pick_org()`` (ORCH-346), then clamp.

    Passes only kwargs ``pick_org`` accepts: ``depth_ceiling``,
    ``learned_depth_from_scorecard`` — not ``ceiling`` / ``requested_depth``
    / ``learned_d_from_scorecard``.
    """
    kwargs = {
        "goal": goal or None,
        "independent_work_items": independent_work_items,
        "remaining_usd": remaining_usd,
        "child_unit_cost": child_unit_cost,
        "remaining_seconds": remaining_seconds,
        "child_unit_seconds": child_unit_seconds,
        "learned_k_from_scorecard": learned_k_from_scorecard,
        "learned_depth_from_scorecard": learned_depth_from_scorecard,
        "parent_span_usd": parent_span_usd,
        "manager_unit_cost": manager_unit_cost,
        "repo_root": repo_root,
        "span": span,
        "depth_ceiling": depth_ceiling,
        "absolute_wall": absolute_wall,
    }
    picked = _call_pick_org(**kwargs)
    if picked is not None:
        return picked
    return _fallback_org(**kwargs)


def lookup_seconds_per_success(model: str, *, repo_root: Any = None) -> float | None:
    try:
        from app.jarvis.cost_index import load_index_data, _rows_from_index

        rows = _rows_from_index(load_index_data(repo_root))
    except Exception:
        return None
    for row in rows:
        if row.model != model:
            continue
        try:
            ok = int(row.ok or 0)
            seconds = float(row.seconds or 0.0)
        except (TypeError, ValueError):
            return None
        if ok > 0 and seconds > 0:
            return seconds / ok
    return None


def resolve_child_unit_cost(
    *,
    model: str | None = None,
    budget_usd: float | None = None,
    repo_root: Any = None,
) -> float | None:
    if model:
        priced = lookup_usd_per_success(model, repo_root=repo_root)
        if priced is not None and priced > 0:
            return priced
    try:
        usd = float(budget_usd) if budget_usd is not None else None
    except (TypeError, ValueError):
        usd = None
    if usd is not None and usd > 0:
        return usd
    return None


def resolve_child_unit_seconds(
    *,
    model: str | None = None,
    budget_seconds: float | None = None,
    repo_root: Any = None,
) -> float | None:
    if model:
        priced = lookup_seconds_per_success(model, repo_root=repo_root)
        if priced is not None and priced > 0:
            return priced
    try:
        seconds = float(budget_seconds) if budget_seconds is not None else None
    except (TypeError, ValueError):
        seconds = None
    if seconds is not None and seconds > 0:
        return seconds
    return None


def learned_k_from_scorecard(goal: str, *, repo_root: Any = None) -> int | None:
    """Best child count for this task class from the scorecard. 0 = solo.

    None when the scorecard has no signal (unknown must not force solo).
    """
    try:
        from app.jarvis.cost_index import load_index_data
        from app.jarvis.model_router import classify_task
    except Exception:
        return None
    try:
        data = load_index_data(repo_root)
    except Exception:
        return None
    if not isinstance(data, dict) or not data:
        return None
    want = classify_task(goal or "")
    by_class = data.get("learned_k_by_class")
    if isinstance(by_class, dict) and want in by_class:
        try:
            return max(0, int(by_class[want]))
        except (TypeError, ValueError):
            pass
    results = data.get("results")
    if not isinstance(results, list) or not results:
        return None
    best_usd: float | None = None
    best_k: int | None = None
    for row in results:
        if not isinstance(row, dict):
            continue
        task = str(row.get("task") or row.get("goal") or "")
        row_class = row.get("task_class") or (classify_task(task) if task else "")
        if row_class and row_class != want:
            continue
        usd = row.get("usd_per_success")
        if usd is None:
            usd = row.get("cost_usd")
        try:
            usd_f = float(usd)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        children = row.get("children")
        who = str(row.get("who_did_what") or "")
        if isinstance(children, list) and children:
            k = len(children)
        elif "solo" in who.lower():
            k = 0
        else:
            continue
        if best_usd is None or usd_f < best_usd:
            best_usd = usd_f
            best_k = k
    return best_k


def format_who_did_what(
    job_id: str,
    children: list[ChildRecord] | list[dict[str, Any]],
    *,
    parent_note: str = "parent merged",
) -> str:
    """One journal line: child ids, models, $. Never child prose (untrusted).

    Example: ``children: c_a1b2c3d4 (openai/gpt-4.1-mini, $0.004, stub.md);
    parent merged``.
    """
    bits: list[str] = []
    for raw in children:
        if isinstance(raw, ChildRecord):
            cid = raw.child_id
            model = raw.model
            spent = raw.spent_usd
            paths = list(raw.artifacts)
        else:
            cid = str(raw.get("child_id") or raw.get("id") or "")
            model = str(raw.get("model") or "")
            try:
                spent = float(raw.get("spent_usd") or raw.get("cost_usd") or 0.0)
            except (TypeError, ValueError):
                spent = 0.0
            raw_arts = raw.get("artifacts") or []
            paths = []
            for item in raw_arts:
                if isinstance(item, dict):
                    paths.append(str(item.get("path") or ""))
                else:
                    paths.append(str(item or ""))
        if not cid:
            continue
        names = [p.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] for p in paths if p]
        extra = f", {', '.join(names)}" if names else ""
        bits.append(f"{cid} ({model or 'unknown'}, ${spent:.3f}{extra})")
    joined = "; ".join(bits) if bits else "(no children)"
    note = (parent_note or "parent merged").strip() or "parent merged"
    return f"children: {joined}; {note}"


def write_parent_journal_line(
    memory: Any,
    job_id: str,
    children: list[ChildRecord] | list[dict[str, Any]],
    *,
    source: str = "child-orch",
) -> str | None:
    """Parent writes one daily-journal line. Child text is not stored as fact."""
    from app.jarvis.daily_journal import day_key, upsert_day_journal

    line = format_who_did_what(job_id, children)
    artifacts: list[str] = []
    for raw in children:
        if isinstance(raw, ChildRecord):
            paths = list(raw.artifacts)
        else:
            paths = []
            for item in raw.get("artifacts") or []:
                if isinstance(item, dict):
                    paths.append(str(item.get("path") or ""))
                else:
                    paths.append(str(item or ""))
        for p in paths:
            s = str(p or "").strip()
            if s and s not in artifacts:
                artifacts.append(s)
    digest = {
        "topics": ["child-orch"],
        "notes": [line],
        "artifacts": artifacts[:8],
    }
    return upsert_day_journal(memory, day_key(), digest, source=source or "child-orch")


def merge_child_artifacts(
    children: list[ChildRecord],
) -> dict[str, Any]:
    """Parent merge: one result, unique artifact paths, per-child metadata."""
    artifacts: list[str] = []
    rows: list[dict[str, Any]] = []
    for child in children:
        for p in child.artifacts:
            if p and p not in artifacts:
                artifacts.append(p)
        rows.append(child.public_dict(include_result=True))
    return {
        "ok": True,
        "merged": True,
        "artifacts": artifacts,
        "children": rows,
    }


@dataclass
class ChildRecord:
    child_id: str
    parent_job_id: str
    goal: str
    model: str
    model_reason: str = ""
    budget_seconds: float = 30.0
    budget_usd: float = 0.02
    spent_usd: float = 0.0
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    status: str = "pending"  # pending|running|done|failed|budget_seconds|budget_usd
    result_text: str = ""
    error: str = ""
    artifacts: list[str] = field(default_factory=list)
    inbox: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    escalate: bool = False
    stop_reason: str = ""
    killed: bool = False
    role: str = ROLE_WORKER  # manager | worker (ORCH-350)
    remaining_depth: int = 0
    depth: int = 1
    parent_child_id: str | None = None
    desktop_backend: str = ""
    thread: threading.Thread | None = field(default=None, repr=False)
    done: threading.Event = field(default_factory=threading.Event, repr=False)
    stop: threading.Event = field(default_factory=threading.Event, repr=False)

    def elapsed_seconds(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return max(0.0, end - self.started_at)

    def budget_hit(self) -> str:
        """Return 'seconds', 'usd', or '' if still inside both caps."""
        if self.elapsed_seconds() >= self.budget_seconds:
            return "seconds"
        if self.spent_usd >= self.budget_usd:
            return "usd"
        return ""

    def wait_status(self) -> str:
        if self.status in TERMINAL_STATUSES:
            return self.status
        if self.stop_reason in {"seconds", "usd"}:
            return f"budget_{self.stop_reason}"
        if self.status == "running":
            return "running"
        return "done"

    def artifact_rows(self) -> list[dict[str, str]]:
        return [{"path": p, "kind": artifact_kind(p)} for p in self.artifacts if p]

    def wait_payload(self) -> dict[str, Any]:
        from app.jarvis.taint import CHILD_TAINT_SOURCE

        return {
            "ok": True,
            "id": self.child_id,
            "status": self.wait_status(),
            "result": self.result_text,
            "artifacts": self.artifact_rows(),
            "usage": {
                "seconds": round(self.elapsed_seconds(), 3),
                "usd": round(self.spent_usd, 6),
                "model": self.model,
                "escalated": bool(self.escalate),
            },
            "tainted": True,
            "taint_source": CHILD_TAINT_SOURCE,
        }

    def public_dict(self, *, include_result: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.child_id,
            "child_id": self.child_id,
            "parent_job_id": self.parent_job_id,
            "status": self.wait_status(),
            "model": self.model,
            "model_reason": self.model_reason,
            "spent_usd": round(self.spent_usd, 6),
            "budget_usd": self.budget_usd,
            "budget_seconds": self.budget_seconds,
            "elapsed_seconds": round(self.elapsed_seconds(), 3),
            "artifacts": self.artifact_rows(),
            "escalate": self.escalate,
            "stop_reason": self.stop_reason,
            "role": self.role,
            "remaining_depth": self.remaining_depth,
            "depth": self.depth,
            "parent_child_id": self.parent_child_id,
        }
        if include_result:
            out["result"] = self.result_text
            out["error"] = self.error
        return out


@dataclass
class JobState:
    job_id: str
    source: str
    children: list[ChildRecord] = field(default_factory=list)
    journaled: bool = False
    failed_count: int = 0
    expected_usd: float = 0.0
    goal: str = ""
    desktop_backend: str = ""
    remaining_usd: float | None = None
    remaining_seconds: float | None = None
    org_depth: int | None = None
    org_plan: OrgPlan | None = None


class ChildSupervisor:
    """Per-process registry: pay-to-spawn cap, role-gated tree, audit, journal."""

    def __init__(self, runner: ChildRunner | None = None) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, JobState] = {}
        self._open_jobs: dict[str, str] = {}
        self._by_id: dict[str, ChildRecord] = {}
        self.runner: ChildRunner = runner or default_child_runner
        self.audit_events: list[dict[str, Any]] = []
        self.solo_override: float | None = None
        self.split_override: float | None = None
        self.learned_k_override: int | None = None
        self.org_depth_override: int | None = None

    def reset(self) -> None:
        with self._lock:
            self._jobs.clear()
            self._open_jobs.clear()
            self._by_id.clear()
            self.audit_events.clear()
            self.solo_override = None
            self.split_override = None
            self.learned_k_override = None
            self.org_depth_override = None

    @contextmanager
    def parent_scope(self, job_id: str) -> Iterator[None]:
        token = _current_parent_job.set(job_id)
        try:
            yield
        finally:
            _current_parent_job.reset(token)

    @contextmanager
    def child_scope(self, child_id: str, job_id: str) -> Iterator[None]:
        t_child = _current_child_id.set(child_id)
        t_job = _current_parent_job.set(job_id)
        from app.jarvis.computer import bind_desktop_backend, reset_desktop_backend

        child = self._by_id.get(child_id)
        job = self._jobs.get(job_id)
        backend = (
            (child.desktop_backend if child else "")
            or (job.desktop_backend if job else "")
        )
        t_desk = bind_desktop_backend(backend or None)
        try:
            yield
        finally:
            reset_desktop_backend(t_desk)
            _current_child_id.reset(t_child)
            _current_parent_job.reset(t_job)

    def begin_job(
        self,
        source: str,
        *,
        goal: str | None = None,
        remaining_usd: float | None = None,
        remaining_seconds: float | None = None,
    ) -> str:
        """Lifetime job for a session / Bridge task / source. Reuses if open."""
        jid = self.job_id_for(source)
        self.bind_job(
            jid,
            goal=goal,
            remaining_usd=remaining_usd,
            remaining_seconds=remaining_seconds,
        )
        return jid

    def bind_job(
        self,
        job_id: str,
        *,
        goal: str | None = None,
        remaining_usd: float | None = None,
        remaining_seconds: float | None = None,
    ) -> None:
        """Attach parent goal / remaining budgets used by pick_child_count()."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                job = JobState(job_id=job_id, source="local")
                self._jobs[job_id] = job
            # Lifetime cap is computed from the original job goal. A later
            # parent turn must not overwrite it (that would reset N).
            if goal is not None and not job.goal:
                job.goal = (goal or "").strip()
                from app.jarvis.computer import resolve_desktop_backend

                job.desktop_backend = resolve_desktop_backend(
                    goal=job.goal,
                    inherit=job.desktop_backend or None,
                )
            if remaining_usd is not None:
                job.remaining_usd = max(0.0, float(remaining_usd))
            if remaining_seconds is not None:
                job.remaining_seconds = max(0.0, float(remaining_seconds))

    def job_id_for(self, source: str) -> str:
        src = (source or "local").strip() or "local"
        with self._lock:
            existing = self._open_jobs.get(src)
            if existing and existing in self._jobs:
                return existing
            jid = f"job_{uuid.uuid4().hex[:10]}"
            self._open_jobs[src] = jid
            self._jobs[jid] = JobState(job_id=jid, source=src)
            return jid

    def rotate_job(self, source: str, memory: Any | None = None) -> None:
        """Write the journal line if ready. Does not reset the lifetime cap."""
        src = (source or "local").strip() or "local"
        with self._lock:
            old = self._open_jobs.get(src)
        if old:
            self.finalize_job(old, memory=memory)

    def get_job(self, job_id: str) -> JobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_child(self, child_id: str) -> ChildRecord | None:
        with self._lock:
            return self._by_id.get(child_id)

    def children_for(self, job_id: str) -> list[ChildRecord]:
        with self._lock:
            job = self._jobs.get(job_id)
            return list(job.children) if job else []

    def children_of(
        self, job_id: str, parent_child_id: str | None = None
    ) -> list[ChildRecord]:
        """Direct reports of one hirer (root parent when parent_child_id is None)."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return []
            return [c for c in job.children if c.parent_child_id == parent_child_id]

    def _root_org_plan(
        self,
        job: JobState,
        *,
        budget_usd: float,
        budget_seconds: float,
        model: str | None = None,
        repo_root: Any = None,
    ) -> OrgPlan:
        """Root pick_org() for this parent job. Bound once. Not a model vote."""
        if self.org_depth_override is not None:
            d = max(0, int(self.org_depth_override))
            plan = OrgPlan(depth=d, widths=[CHILD_CEILING] * d if d else [], n=CHILD_CEILING, source="override")
            job.org_plan = plan
            job.org_depth = d
            return plan
        if job.org_plan is not None:
            return job.org_plan
        if self.learned_k_override is not None:
            learned_k: int | None = int(self.learned_k_override)
        elif job.goal:
            learned_k = learned_k_from_scorecard(job.goal, repo_root=repo_root)
        else:
            learned_k = None
        plan = resolve_org(
            goal=job.goal,
            remaining_usd=job.remaining_usd,
            child_unit_cost=resolve_child_unit_cost(
                model=model, budget_usd=budget_usd, repo_root=repo_root
            ),
            remaining_seconds=job.remaining_seconds,
            child_unit_seconds=resolve_child_unit_seconds(
                model=model, budget_seconds=budget_seconds, repo_root=repo_root
            ),
            learned_k_from_scorecard=learned_k,
            depth_ceiling=DEPTH_CEILING,
            absolute_wall=ABSOLUTE_WALL,
            span=ORG_SPAN,
            repo_root=repo_root,
        )
        job.org_plan = plan
        job.org_depth = plan.depth
        return plan

    def cap_for_job(
        self,
        job: JobState,
        *,
        budget_usd: float,
        budget_seconds: float,
        model: str | None = None,
        repo_root: Any = None,
        hirer: ChildRecord | None = None,
    ) -> int:
        """Per-hirer width. Parent uses ``plan.widths[0]``; managers do not
        re-run the parent ``pick_child_count``. A manager slice with unknown
        or <2 countable pieces is 0 (STAY_SOLO — not a free swarm).
        """
        plan = self._root_org_plan(
            job,
            budget_usd=budget_usd,
            budget_seconds=budget_seconds,
            model=model,
            repo_root=repo_root,
        )
        layer = 0 if hirer is None else max(0, int(hirer.depth or 0))
        if layer >= len(plan.widths):
            return 0
        width_cap = max(0, int(plan.widths[layer]))
        if hirer is None:
            return width_cap
        items = count_independent_work_items(hirer.goal)
        if items is None or items < 2:
            return 0
        rem_usd = max(0.0, float(hirer.budget_usd) - float(hirer.spent_usd))
        rem_s = max(0.0, float(hirer.budget_seconds) - float(hirer.elapsed_seconds()))
        if self.learned_k_override is not None:
            learned: int | None = int(self.learned_k_override)
        else:
            learned = learned_k_from_scorecard(hirer.goal, repo_root=repo_root)
        n = pick_child_count(
            independent_work_items=items,
            remaining_usd=rem_usd,
            child_unit_cost=resolve_child_unit_cost(
                model=model, budget_usd=budget_usd, repo_root=repo_root
            ),
            remaining_seconds=rem_s,
            child_unit_seconds=resolve_child_unit_seconds(
                model=model, budget_seconds=budget_seconds, repo_root=repo_root
            ),
            learned_k_from_scorecard=learned,
        )
        return min(n, width_cap)

    def org_for_job(
        self,
        job: JobState,
        *,
        budget_usd: float,
        budget_seconds: float,
        model: str | None = None,
        repo_root: Any = None,
        hirer: ChildRecord | None = None,
    ) -> OrgPlan:
        return self._root_org_plan(
            job,
            budget_usd=budget_usd,
            budget_seconds=budget_seconds,
            model=model,
            repo_root=repo_root,
        )

    def audit(self, kind: str, record: ChildRecord | None, **extra: Any) -> dict[str, Any]:
        event = {
            "event": f"child.{kind}",
            "kind": kind,
            "child_id": record.child_id if record else extra.get("child_id"),
            "parent_job_id": record.parent_job_id if record else extra.get("parent_job_id"),
            "model": record.model if record else extra.get("model"),
            "status": record.status if record else extra.get("status"),
            "spent_usd": record.spent_usd if record else extra.get("spent_usd"),
            "ts": time.time(),
            **{k: v for k, v in extra.items() if k not in {"child_id", "parent_job_id"}},
        }
        # Inter-agent text is audited but must not be treated as trusted fact.
        if "text" in event and isinstance(event["text"], str):
            event["text"] = event["text"][:400]
            event["untrusted"] = True
        with self._lock:
            self.audit_events.append(event)
            if record is not None:
                record.events.append({"kind": kind, "ts": event["ts"]})
        try:
            from app.jarvis.gateway import get_gateway

            get_gateway()._audit_log.append(event)
        except Exception:
            log.debug("child audit jsonl skipped", exc_info=True)
        return event

    def spawn(
        self,
        goal: str,
        *,
        budget_seconds: float | None = None,
        budget_usd: float | None = None,
        parent_job_id: str | None = None,
        source: str | None = None,
        start: bool = True,
        memory: Any = None,
    ) -> dict[str, Any]:
        hirer = resolve_caller_child(source)
        if caller_is_child(source):
            if (
                hirer is None
                or (hirer.role or "").strip().lower() != ROLE_MANAGER
                or int(hirer.remaining_depth or 0) <= 0
            ):
                return err(CHILD_FORBIDDEN)
        goal_text = (goal or "").strip()
        if not goal_text:
            return err(GOAL_EMPTY)
        if len(goal_text) > GOAL_MAX_CHARS:
            return err(GOAL_TOO_LONG)

        if budget_seconds is None or budget_usd is None:
            return err(INVALID_BUDGET)
        try:
            seconds = float(budget_seconds)
            usd = float(budget_usd)
        except (TypeError, ValueError):
            return err(INVALID_BUDGET)
        if seconds <= 0 or usd <= 0:
            return err(INVALID_BUDGET)
        seconds = min(seconds, MAX_BUDGET_SECONDS)
        usd = min(usd, MAX_BUDGET_USD)

        job_id = (
            (parent_job_id or "").strip()
            or current_parent_job()
            or self.job_id_for(source or current_tool_source() or "local")
        )
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                job = JobState(job_id=job_id, source=source or "local")
                self._jobs[job_id] = job
            expected = job.expected_usd

        # Escalate is same-child only. A sibling's failure must not upgrade this spawn.
        choice = pick_child_model(goal_text, prior_failures=0)
        do_solo, orch, solo = orchestration_would_cost_more(
            goal=goal_text,
            new_budget_usd=usd,
            existing_expected_usd=expected,
            new_model=choice.model,
            solo_override=self.solo_override,
            split_override=self.split_override,
        )
        if do_solo:
            self.audit(
                "spawn",
                None,
                parent_job_id=job_id,
                status="solo",
                orch_usd=orch,
                solo_usd=solo,
            )
            return err(STAY_SOLO)

        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                job = JobState(job_id=job_id, source=source or "local")
                self._jobs[job_id] = job
            plan = self.org_for_job(
                job,
                budget_usd=usd,
                budget_seconds=seconds,
                model=choice.model,
                hirer=hirer,
            )
            n = self.cap_for_job(
                job,
                budget_usd=usd,
                budget_seconds=seconds,
                model=choice.model,
                hirer=hirer,
            )
            if hirer is None:
                depth_allowed = plan.depth
                if job.org_depth is None:
                    job.org_depth = depth_allowed
                child_depth = 1
                child_remaining = max(0, depth_allowed - 1)
                child_role = ROLE_MANAGER if child_remaining > 0 else ROLE_WORKER
                parent_child_id = None
            else:
                child_depth = int(hirer.depth or 0) + 1
                child_remaining = max(0, int(hirer.remaining_depth or 0) - 1)
                child_role = ROLE_MANAGER if child_remaining > 0 else ROLE_WORKER
                parent_child_id = hirer.child_id
                depth_allowed = int(hirer.remaining_depth or 0)
            if child_depth > ABSOLUTE_WALL:
                self.audit(
                    "spawn",
                    None,
                    parent_job_id=job_id,
                    status="rejected",
                    reason="depth_wall",
                    depth=child_depth,
                )
                return err(DEPTH_WALL)
            if hirer is None and depth_allowed < 1:
                self.audit(
                    "spawn",
                    None,
                    parent_job_id=job_id,
                    status="solo",
                    reason="depth_lt_1",
                    n=n,
                    depth=depth_allowed,
                )
                return err(STAY_SOLO)
            if hirer is None and depth_allowed < 2 and n < 2:
                self.audit(
                    "spawn",
                    None,
                    parent_job_id=job_id,
                    status="solo",
                    reason="n_lt_2",
                    n=n,
                    depth=depth_allowed,
                )
                return err(STAY_SOLO)
            if n < 2 and not self.children_of(job_id, parent_child_id):
                self.audit(
                    "spawn",
                    None,
                    parent_job_id=job_id,
                    status="solo",
                    reason="n_lt_2",
                    n=n,
                )
                return err(STAY_SOLO)
            direct = [c for c in job.children if c.parent_child_id == parent_child_id]
            if len(direct) >= n:
                self.audit(
                    "spawn",
                    None,
                    parent_job_id=job_id,
                    status="rejected",
                    reason="child_limit",
                    n=n,
                )
                return err(CHILD_LIMIT)
            from app.jarvis.computer import current_desktop_backend, resolve_desktop_backend

            if not job.desktop_backend:
                job.desktop_backend = resolve_desktop_backend(
                    goal=job.goal or goal_text,
                    inherit=current_desktop_backend(),
                )
            child = ChildRecord(
                child_id=f"c_{uuid.uuid4().hex[:8]}",
                parent_job_id=job_id,
                goal=goal_text,
                model=choice.model,
                model_reason=choice.reason,
                budget_seconds=seconds,
                budget_usd=usd,
                escalate=False,
                status="pending",
                role=child_role,
                remaining_depth=child_remaining,
                depth=child_depth,
                parent_child_id=parent_child_id,
                desktop_backend=job.desktop_backend,
            )
            job.children.append(child)
            known = estimate_child_expected_usd(usd, model=choice.model)
            if known is not None:
                job.expected_usd += known
            self._by_id[child.child_id] = child
        self.audit("spawn", child, goal=goal_text[:200])
        if start:
            self._start(child)
        self._note_agent_created(memory)
        return {
            "ok": True,
            "id": child.child_id,
            "status": "running",
            "model": child.model,
            "role": child.role,
            "remaining_depth": child.remaining_depth,
            "depth": child.depth,
        }

    def _note_agent_created(self, memory: Any = None) -> None:
        """Increment today's journal spawn count. Never fail the spawn."""
        mem = memory
        if mem is None:
            try:
                from app.jarvis import gateway as gw

                if gw._gateway is not None:
                    mem = gw._gateway.memory
            except Exception:
                mem = None
        if mem is None:
            return
        try:
            from app.jarvis.daily_journal import increment_agents_created

            increment_agents_created(mem, 1, source="child-orch")
        except Exception:
            log.debug("agents_created journal increment failed", exc_info=True)

    def request_stop(self, child: ChildRecord, *, reason: str = "") -> None:
        """Live-kill: signal the runner to stop spend, then join the thread."""
        child.stop.set()
        child.killed = True
        if reason in {"seconds", "usd"}:
            child.status = f"budget_{reason}"
            child.stop_reason = reason
            if not child.result_text:
                child.result_text = f"Stopped: {reason} budget exhausted."
        elif reason and not child.stop_reason:
            child.stop_reason = reason
        if child.finished_at is None:
            child.finished_at = time.monotonic()
        thread = child.thread
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=1.5)
        child.done.set()

    def _start(self, child: ChildRecord) -> None:
        child.status = "running"
        child.started_at = time.monotonic()
        child.stop.clear()
        child.killed = False

        def _target() -> None:
            try:
                if child.stop.is_set():
                    return
                with self.child_scope(child.child_id, child.parent_job_id):
                    self.runner(child, self)
            except Exception as exc:
                child.status = "failed"
                child.error = str(exc)[:300]
                log.exception("child runner crashed")
            finally:
                self._finish(child)

        def _watch() -> None:
            while not child.done.wait(0.05):
                if child.stop.is_set():
                    return
                hit = child.budget_hit()
                if hit:
                    self.request_stop(child, reason=hit)
                    return

        t = threading.Thread(
            target=_target, name=f"jarvis-child-{child.child_id}", daemon=True
        )
        child.thread = t
        t.start()
        threading.Thread(
            target=_watch,
            name=f"jarvis-child-watch-{child.child_id}",
            daemon=True,
        ).start()

    def _finish(self, child: ChildRecord) -> None:
        child.stop.set()
        if child.finished_at is None:
            child.finished_at = time.monotonic()
        if child.stop_reason in {"seconds", "usd"}:
            child.status = f"budget_{child.stop_reason}"
        else:
            hit = child.budget_hit()
            if hit and child.status in {"running", "done"}:
                child.status = f"budget_{hit}"
                child.stop_reason = hit
        if child.status == "running":
            child.status = "done"
        if child.status == "failed":
            job = self.get_job(child.parent_job_id)
            if job:
                job.failed_count += 1
            try:
                from app.jarvis.model_router import classify_task, record_outcome

                record_outcome(
                    model=child.model,
                    reason="child failed",
                    task_class=classify_task(child.goal),
                    ok=False,
                )
            except Exception:
                pass
        child.done.set()
        self.audit("result", child, include_result=False)

    def message(
        self, child_id: str, text: str, *, from_child: bool = False
    ) -> dict[str, Any]:
        if caller_is_child() and not from_child and not caller_may_use_child_api():
            return err(CHILD_FORBIDDEN)
        body = (text or "").strip()
        if not body:
            return err(TEXT_EMPTY)
        if len(body) > TEXT_MAX_CHARS:
            return err(TEXT_TOO_LONG)
        child = self._child_on_this_job(child_id)
        if child is None:
            return err(UNKNOWN_CHILD)
        if child.status in TERMINAL_STATUSES:
            return err(CHILD_NOT_RUNNING)
        child.inbox.append(body)
        self.audit("message", child, text=body)
        return {"ok": True, "id": child_id, "delivered": True}

    def _child_on_this_job(self, child_id: str) -> ChildRecord | None:
        child = self.get_child(child_id)
        if child is None:
            return None
        scoped = current_parent_job()
        if scoped and child.parent_job_id != scoped:
            return None
        hirer_id = current_child_id()
        if hirer_id and child.parent_child_id != hirer_id:
            return None
        return child

    def wait(self, child_id: str, *, timeout: float | None = None) -> dict[str, Any]:
        if caller_is_child() and not caller_may_use_child_api():
            return err(CHILD_FORBIDDEN)
        child = self._child_on_this_job(child_id)
        if child is None:
            return err(UNKNOWN_CHILD)
        remaining = child.budget_seconds - child.elapsed_seconds()
        join_for = timeout if timeout is not None else max(0.05, remaining + 1.0)
        if child.thread is not None and child.thread.is_alive():
            child.done.wait(timeout=join_for)
        elif child.status == "pending":
            self._start(child)
            child.done.wait(timeout=join_for)
        if child.thread is not None and child.thread.is_alive() and not child.done.is_set():
            self.request_stop(child, reason=child.budget_hit() or "seconds")
        self.audit("wait", child)
        return child.wait_payload()

    def finalize_job(self, job_id: str, memory: Any | None = None) -> str | None:
        job = self.get_job(job_id)
        if job is None or job.journaled or not job.children:
            return None
        if any(c.wait_status() not in TERMINAL_STATUSES for c in job.children):
            return None
        mem = memory
        if mem is None:
            try:
                from app.jarvis.gateway import get_gateway

                mem = get_gateway().memory
            except Exception:
                return None
        try:
            fid = write_parent_journal_line(mem, job.job_id, job.children)
        except Exception:
            log.debug("child journal write failed", exc_info=True)
            return None
        job.journaled = True
        return fid


def get_supervisor() -> ChildSupervisor:
    global _supervisor
    with _supervisor_lock:
        if _supervisor is None:
            _supervisor = ChildSupervisor()
        return _supervisor


def reset_supervisor_for_tests(runner: ChildRunner | None = None) -> ChildSupervisor:
    global _supervisor
    with _supervisor_lock:
        _supervisor = ChildSupervisor(runner=runner)
        return _supervisor


def default_child_runner(record: ChildRecord, supervisor: ChildSupervisor) -> None:
    """Short-lived JarvisLocalAgent loop with seconds/$ caps. No spawn tools.

    Cheap failure escalates once via the router; spend still counts against
    the same budgets (ORCH-338).
    """
    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        record.status = "failed"
        record.error = "OPENROUTER_API_KEY missing"
        return

    from app.jarvis.agent import JarvisLocalAgent
    from app.jarvis.gateway import get_gateway
    from app.jarvis.model_router import classify_task, record_outcome
    from app.jarvis.permissions import Tier

    if record.stop.is_set():
        return

    gw = get_gateway()
    remaining_s = max(0.05, record.budget_seconds - record.elapsed_seconds())
    remaining_usd = max(0.0, record.budget_usd - record.spent_usd)

    def _attempt(model: str, reason: str) -> tuple[Any, Any]:
        agent = JarvisLocalAgent(
            api_key=key,
            model=model,
            model_reason=reason,
            tool_specs=child_tool_specs(
                role=record.role, remaining_depth=record.remaining_depth
            ),
            is_child=True,
            child_role=record.role,
            remaining_depth=record.remaining_depth,
            budget_seconds=remaining_s,
            budget_usd=remaining_usd,
            max_auto=Tier.L1,
            timeout_seconds=min(remaining_s + 15.0, 600.0),
            max_tool_rounds=8,
            tool_source=f"child:{record.child_id}",
            workspace=gw.ws,
            stop_event=record.stop,
        )
        agent._gateway = gw
        agent._inbox = record.inbox

        async def _run() -> Any:
            sess = await agent.start_session(
                role_name="jarvis-child",
                parent_session_id=record.parent_job_id,
                metadata={"child_id": record.child_id},
            )
            try:
                return await agent.send_message(sess.session_id, message=record.goal)
            finally:
                await agent.stop_session(sess.session_id, reason="child_done")

        import asyncio

        return asyncio.run(_run()), agent

    try:
        result, agent = _attempt(record.model, record.model_reason)
    except Exception as exc:
        try:
            record_outcome(
                model=record.model,
                reason="child failed",
                task_class=classify_task(record.goal),
                ok=False,
            )
        except Exception:
            pass
        hotter = pick_child_model(record.goal, prior_failures=1)
        record.model = hotter.model
        record.model_reason = hotter.reason
        record.escalate = True
        remaining_s = max(0.05, record.budget_seconds - record.elapsed_seconds())
        remaining_usd = max(0.0, record.budget_usd - record.spent_usd)
        if remaining_s <= 0 or remaining_usd <= 0 or record.stop.is_set():
            record.status = "failed"
            record.error = str(exc)[:300]
            return
        try:
            result, agent = _attempt(hotter.model, hotter.reason)
        except Exception as exc2:
            record.status = "failed"
            record.error = str(exc2)[:300]
            return

    try:
        record.spent_usd += float(result.generation.actual_cost_usd or 0.0)
    except Exception:
        record.spent_usd += float(getattr(agent, "_spent_usd", 0.0) or 0.0)
    record.result_text = str(getattr(result, "text", "") or "")
    record.artifacts = list(getattr(agent, "_artifacts", []) or [])
    stop = getattr(agent, "_budget_stop", "") or ""
    if stop in {"seconds", "usd"}:
        record.status = f"budget_{stop}"
        record.stop_reason = stop
        if not record.result_text:
            record.result_text = f"Stopped: {stop} budget exhausted."
    else:
        record.status = "done"


def spawn_child(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    job_id = str((args or {}).get("parent_job_id") or "").strip()
    return get_supervisor().spawn(
        str(args.get("goal") or ""),
        budget_seconds=args.get("budget_seconds"),
        budget_usd=args.get("budget_usd"),
        parent_job_id=job_id or getattr(ctx, "parent_job_id", None),
        source=getattr(ctx, "tool_source", None) or current_tool_source(),
        memory=getattr(ctx, "memory", None),
    )


def message_child(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    return get_supervisor().message(str(args.get("id") or ""), str(args.get("text") or ""))


def wait_child(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    return get_supervisor().wait(str(args.get("id") or ""))
