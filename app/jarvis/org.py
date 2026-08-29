"""Jarvis company layers — pick_org() (ORCH-346 / epic ORCH-345).

The parent model does not vote the org chart. Depth and per-layer width
come from a rule:

* work tree (pieces + who waits on whom)
* span S=4 (insert a manager if a node has more than 4 independent pieces)
* pay-to-add-a-layer (manager + workers cheaper than parent doing that
  span, or the parent is over span)
* scorecard best depth for this task class, when present
* DEPTH_CEILING=4 (v1 default max), ABSOLUTE_WALL=20 (refuse deeper)
* width still uses pick_child_count() from ORCH-344
* If D < 2 and N < 2: stay solo (depth 0)

v1 first slice is depth 2: parent → managers → workers. Twenty is the
wall, not the default. This module does not spawn the tree (ORCH-350).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.jarvis.children import (
    CHILD_CEILING,
    PARENT_OVERHEAD_USD,
    count_independent_work_items,
    learned_k_from_scorecard as lookup_learned_k,
    pick_child_count,
)

SPAN = 4
DEPTH_CEILING = 4
ABSOLUTE_WALL = 20

_WORD_COUNTS = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twenty": 20,
}
_LAYER_ASK_RE = re.compile(
    r"\b(two|three|four|five|six|seven|eight|nine|ten|twenty|\d+)\s+layers?\b",
    re.I,
)


@dataclass(frozen=True)
class WorkPiece:
    """One piece of work. ``waits_on`` is other piece ids this piece needs."""

    piece_id: str
    waits_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkTree:
    """Pieces + who waits on whom. Depth of WORK is not depth of AGENTS."""

    pieces: tuple[WorkPiece, ...] = ()
    unknown: bool = False

    def independent_count(self) -> int | None:
        """Pieces that do not wait on another piece. None if unknown."""
        if self.unknown:
            return None
        if not self.pieces:
            return 0
        return sum(1 for p in self.pieces if not p.waits_on)

    def work_depth(self) -> int:
        """Longest wait-chain. Not the agent-layer count."""
        if self.unknown or not self.pieces:
            return 0
        by_id = {p.piece_id: p for p in self.pieces}
        memo: dict[str, int] = {}

        def _depth(pid: str, stack: set[str]) -> int:
            if pid in memo:
                return memo[pid]
            if pid in stack:
                return 1
            piece = by_id.get(pid)
            if piece is None or not piece.waits_on:
                memo[pid] = 1
                return 1
            child = [_depth(dep, stack | {pid}) for dep in piece.waits_on if dep in by_id]
            memo[pid] = 1 + (max(child) if child else 0)
            return memo[pid]

        return max((_depth(p.piece_id, set()) for p in self.pieces), default=0)


@dataclass(frozen=True)
class OrgChart:
    """Agent org. ``depth`` 0 is solo; ``widths[i]`` is fan-out at layer i."""

    depth: int
    widths: tuple[int, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"depth": int(self.depth), "widths": [int(w) for w in self.widths]}


SOLO = OrgChart(depth=0, widths=())


def work_tree_from_pieces(
    pieces: Sequence[str | WorkPiece] | int,
    *,
    waits_on: Mapping[str, Sequence[str]] | None = None,
) -> WorkTree:
    """Build a work tree from ids, WorkPiece rows, or a count of independents."""
    if isinstance(pieces, int):
        n = max(0, int(pieces))
        return WorkTree(pieces=tuple(WorkPiece(piece_id=f"p{i}") for i in range(n)))
    rows: list[WorkPiece] = []
    deps = waits_on or {}
    for raw in pieces:
        if isinstance(raw, WorkPiece):
            extra = tuple(str(x) for x in deps.get(raw.piece_id, ()) if str(x))
            waits = tuple(dict.fromkeys((*raw.waits_on, *extra)))
            rows.append(WorkPiece(piece_id=raw.piece_id, waits_on=waits))
            continue
        pid = str(raw or "").strip()
        if not pid:
            continue
        waits = tuple(str(x) for x in deps.get(pid, ()) if str(x))
        rows.append(WorkPiece(piece_id=pid, waits_on=waits))
    return WorkTree(pieces=tuple(rows))


def work_tree_from_goal(goal: str | None) -> WorkTree:
    """Count independent pieces in ``goal``. Unknown must not invent a count of 1."""
    n = count_independent_work_items(goal)
    if n is None:
        return WorkTree(unknown=True)
    return work_tree_from_pieces(n)


def parse_layer_ask(goal: str | None) -> int | None:
    """User/goal wording like '20 layers'. An ask, not a model vote."""
    text = (goal or "").strip()
    if not text:
        return None
    found: list[int] = []
    for raw in (m.group(1) for m in _LAYER_ASK_RE.finditer(text)):
        key = raw.lower()
        if key in _WORD_COUNTS:
            found.append(_WORD_COUNTS[key])
            continue
        try:
            found.append(int(key))
        except ValueError:
            continue
    if not found:
        return None
    return max(found)


def lookup_learned_depth(goal: str, *, repo_root: Any = None) -> int | None:
    """Best agent depth for this task class. 0 = solo. None if unknown."""
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
    by_class = data.get("learned_depth_by_class")
    if isinstance(by_class, dict) and want in by_class:
        try:
            return max(0, int(by_class[want]))
        except (TypeError, ValueError):
            pass
    results = data.get("results")
    if not isinstance(results, list) or not results:
        return None
    best_usd: float | None = None
    best_d: int | None = None
    for row in results:
        if not isinstance(row, dict):
            continue
        task = str(row.get("task") or row.get("goal") or "")
        row_class = row.get("task_class") or (classify_task(task) if task else "")
        if row_class and row_class != want:
            continue
        if "depth" not in row:
            continue
        try:
            depth = max(0, int(row.get("depth")))
        except (TypeError, ValueError):
            continue
        usd = row.get("usd_per_success")
        if usd is None:
            usd = row.get("cost_usd")
        try:
            usd_f = float(usd)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if best_usd is None or usd_f < best_usd:
            best_usd = usd_f
            best_d = depth
    return best_d


learned_depth_from_scorecard = lookup_learned_depth


def _span_depth(n_work: int, span: int, *, wall: int) -> int:
    """Agent layers needed so no node owns more than ``span`` independents."""
    if n_work < 2:
        return 0
    s = max(1, int(span))
    depth = 0
    remaining = int(n_work)
    while remaining > 1:
        depth += 1
        if depth >= wall:
            return wall
        if remaining <= s:
            break
        remaining = math.ceil(remaining / s)
    return depth


def _layer_pays(
    *,
    over_span: bool,
    manager_plus_workers_usd: float | None,
    parent_span_usd: float | None,
) -> bool:
    """Add a manager layer if it is cheaper, or the parent is over span."""
    if over_span:
        return True
    if manager_plus_workers_usd is None or parent_span_usd is None:
        return False
    return float(manager_plus_workers_usd) < float(parent_span_usd)


def _widths_for(*, n_work: int, depth: int, n: int, span: int) -> tuple[int, ...]:
    if depth <= 0 or n < 2 or n_work < 2:
        return ()
    s = max(1, int(span))
    items = int(n_work)
    out: list[int] = []
    for hop in range(depth, 0, -1):
        if hop == 1:
            out.append(min(s, n, items))
            break
        needed = math.ceil(items / s)
        width = min(s, n, needed)
        if width < 2:
            return ()
        out.append(width)
        items = math.ceil(items / width)
    return tuple(out)


def pick_org(
    *,
    goal: str | None = None,
    work_tree: WorkTree | None = None,
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
    span: int = SPAN,
    depth_ceiling: int = DEPTH_CEILING,
    absolute_wall: int = ABSOLUTE_WALL,
) -> OrgChart:
    """Pay-to-add-a-layer org chart. The parent model does not vote depth or N.

    Returns ``OrgChart(depth, widths)``. ``as_dict()`` is ``{depth, widths[]}``.

    Do not pass ``depth`` / ``n`` / ``widths`` — those are outputs. A
    "20 layers" phrase in ``goal`` is an ask that is clamped to the wall;
    it cannot raise the chosen depth above the rule.
    """
    wall = max(0, int(absolute_wall))
    ceiling = max(0, min(int(depth_ceiling), wall))
    s = max(1, int(span))

    tree = work_tree
    if tree is None and independent_work_items is None and goal is not None:
        tree = work_tree_from_goal(goal)

    n_work = independent_work_items
    if n_work is None and tree is not None:
        n_work = tree.independent_count()

    k = learned_k_from_scorecard
    if k is None and goal:
        k = lookup_learned_k(goal, repo_root=repo_root)

    n = pick_child_count(
        independent_work_items=n_work,
        remaining_usd=remaining_usd,
        child_unit_cost=child_unit_cost,
        remaining_seconds=remaining_seconds,
        child_unit_seconds=child_unit_seconds,
        learned_k_from_scorecard=k,
        ceiling=min(CHILD_CEILING, s),
    )

    scored_depth = learned_depth_from_scorecard
    if scored_depth is None and goal:
        scored_depth = lookup_learned_depth(goal, repo_root=repo_root)

    if n_work is None:
        # Unknown pieces: width may still hire (omit from min); depth 1 shop
        # if N >= 2, else solo. Do not invent a manager layer.
        if n < 2:
            return SOLO
        depth_caps = [1, ceiling, wall]
        if scored_depth is not None:
            depth_caps.append(max(0, int(scored_depth)))
        depth = min(depth_caps)
        if depth < 2 and n < 2:
            return SOLO
        if depth < 1:
            return SOLO
        return OrgChart(depth=depth, widths=(n,) if depth >= 1 else ())

    n_work = max(0, int(n_work))
    over_span = n_work > s
    span_depth = _span_depth(n_work, s, wall=wall)

    mgr_unit = manager_unit_cost if manager_unit_cost is not None else child_unit_cost
    layer_usd: float | None = None
    parent_usd = parent_span_usd
    if mgr_unit is not None and child_unit_cost is not None:
        managers = math.ceil(n_work / s) if n_work else 0
        workers = min(n_work, managers * s) if managers else n_work
        layer_usd = (
            PARENT_OVERHEAD_USD
            + max(0, managers) * float(mgr_unit)
            + max(0, workers) * float(child_unit_cost)
        )
        if parent_usd is None:
            parent_usd = PARENT_OVERHEAD_USD + min(n_work, s) * float(child_unit_cost)

    pays = _layer_pays(
        over_span=over_span,
        manager_plus_workers_usd=layer_usd,
        parent_span_usd=parent_usd,
    )
    if span_depth >= 2 and not pays:
        span_depth = 1 if n_work >= 2 else 0
    if span_depth >= 2:
        # One manager is just a more expensive solo parent (same as N=1 → 0).
        if math.ceil(n_work / s) < 2:
            span_depth = 1 if n_work >= 2 else 0

    depth_caps = [span_depth, ceiling, wall]
    if scored_depth is not None:
        depth_caps.append(max(0, int(scored_depth)))
    if remaining_usd is not None and child_unit_cost is not None and float(child_unit_cost) > 0:
        # Budget-fit: if we cannot hire two agents, no company. Extra manager
        # dollars are required only when we actually add a layer.
        if n < 2:
            depth_caps.append(0)
        elif layer_usd is not None and float(remaining_usd) < float(layer_usd) and not over_span:
            depth_caps.append(1)

    # A layer-ask in the goal cannot raise depth (not a vote). It can only
    # be refused past the wall — the rule still chooses.
    ask = parse_layer_ask(goal)
    if ask is not None and ask > wall:
        depth_caps.append(wall)

    depth = min(depth_caps)
    if depth < 0:
        depth = 0

    if depth < 2 and n < 2:
        return SOLO
    if n < 2 or depth < 1 or n_work < 2:
        return SOLO

    widths = _widths_for(n_work=n_work, depth=depth, n=n, span=s)
    if not widths:
        return SOLO
    return OrgChart(depth=depth, widths=widths)
