"""ORCH-346 pick_org — company layers by rule, not a model vote."""

from __future__ import annotations

import inspect

import pytest

from app.jarvis.children import count_independent_work_items, pick_child_count
from app.jarvis.org import (
    ABSOLUTE_WALL,
    DEPTH_CEILING,
    SPAN,
    OrgChart,
    WorkPiece,
    learned_depth_from_scorecard,
    parse_layer_ask,
    pick_org,
    work_tree_from_goal,
    work_tree_from_pieces,
)

LIGHT_GOAL = "how much disk free space do I have"
SINGLE_FILE_GOAL = "Create a report with write_file to Exports/report.md"
TWO_FILE_GOAL = (
    "split this: one child writes the stub, one writes the readme.\n"
    "WRITE TWO FILES.\n"
    "write_file the Python stub to: Exports/stub.py\n"
    "write_file the markdown README to: Exports/readme.md\n"
)
EIGHT_FILE_GOAL = (
    "WRITE EIGHT independent pieces.\n"
    + "\n".join(f"write_file Exports/{name}.py" for name in "abcdefgh")
    + "\n"
)
TWENTY_LAYER_ASK = (
    "use 20 layers to handle eight independent pieces.\n" + EIGHT_FILE_GOAL
)

_BUDGET = dict(
    remaining_usd=10.0,
    child_unit_cost=0.01,
    remaining_seconds=600,
    child_unit_seconds=5,
)


def test_tiny_job_is_depth_zero():
    assert count_independent_work_items(LIGHT_GOAL) == 1
    org = pick_org(goal=LIGHT_GOAL, **_BUDGET)
    assert org.depth == 0
    assert org.widths == ()
    assert org.as_dict() == {"depth": 0, "widths": []}
    assert pick_org(independent_work_items=1, **_BUDGET).depth == 0
    assert pick_org(goal=SINGLE_FILE_GOAL, **_BUDGET).depth == 0


def test_two_files_is_depth_zero_or_one():
    assert count_independent_work_items(TWO_FILE_GOAL) == 2
    org = pick_org(goal=TWO_FILE_GOAL, **_BUDGET)
    assert org.depth in (0, 1)
    if org.depth == 1:
        assert org.widths == (2,)
    cheap = pick_org(
        independent_work_items=2,
        remaining_usd=0.10,
        child_unit_cost=0.02,
        remaining_seconds=60,
        child_unit_seconds=5,
    )
    assert cheap.depth in (0, 1)
    solo = pick_org(
        independent_work_items=2,
        remaining_usd=0.10,
        child_unit_cost=0.02,
        learned_k_from_scorecard=0,
    )
    assert solo.depth == 0
    assert solo.widths == ()


def test_eight_independent_pieces_is_depth_two():
    assert count_independent_work_items(EIGHT_FILE_GOAL) >= 8
    org = pick_org(goal=EIGHT_FILE_GOAL, **_BUDGET)
    assert org.depth == 2
    assert org.widths == (2, 4)
    assert org.as_dict() == {"depth": 2, "widths": [2, 4]}
    counted = pick_org(independent_work_items=8, **_BUDGET)
    assert counted.depth == 2
    assert counted.widths == (2, 4)
    tree = work_tree_from_pieces(8)
    assert tree.independent_count() == 8
    assert pick_org(work_tree=tree, **_BUDGET).depth == 2


def test_twenty_layer_ask_capped_at_wall():
    assert parse_layer_ask(TWENTY_LAYER_ASK) == 20
    org = pick_org(goal=TWENTY_LAYER_ASK, **_BUDGET)
    assert org.depth <= ABSOLUTE_WALL
    assert org.depth <= DEPTH_CEILING
    assert org.depth == 2
    assert org.depth != 20

    huge = pick_org(independent_work_items=4**21, **_BUDGET)
    assert huge.depth <= DEPTH_CEILING
    assert huge.depth <= ABSOLUTE_WALL

    wall = pick_org(
        independent_work_items=4**21,
        depth_ceiling=30,
        absolute_wall=ABSOLUTE_WALL,
        **_BUDGET,
    )
    assert wall.depth <= ABSOLUTE_WALL
    assert wall.depth != 21


def test_model_cannot_pass_n_or_depth_as_a_vote():
    sig = inspect.signature(pick_org)
    for banned in (
        "depth",
        "n",
        "widths",
        "child_count",
        "num_children",
        "requested_depth",
    ):
        assert banned not in sig.parameters

    with pytest.raises(TypeError):
        pick_org(depth=20, independent_work_items=8, **_BUDGET)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        pick_org(n=8, independent_work_items=8, **_BUDGET)  # type: ignore[call-arg]

    from app.jarvis.tools import TOOL_SPECS

    spec = next(
        s for s in TOOL_SPECS if (s.get("function") or {}).get("name") == "spawn_child"
    )
    props = (spec.get("function") or {}).get("parameters", {}).get("properties") or {}
    for banned in ("n", "count", "child_count", "num_children", "depth", "widths"):
        assert banned not in props


def test_scorecard_best_depth_when_present(tmp_path):
    from app.jarvis.cost_index import INDEX_LATEST

    idx = tmp_path / INDEX_LATEST
    idx.parent.mkdir(parents=True, exist_ok=True)
    idx.write_text(
        '{"learned_depth_by_class": {"routine_build": 1}, "results": []}',
        encoding="utf-8",
    )
    assert learned_depth_from_scorecard(TWO_FILE_GOAL, repo_root=tmp_path) == 1
    org = pick_org(
        independent_work_items=8,
        learned_depth_from_scorecard=1,
        **_BUDGET,
    )
    assert org.depth == 1
    assert org.widths == (4,)
    solo = pick_org(
        independent_work_items=8,
        learned_depth_from_scorecard=0,
        **_BUDGET,
    )
    assert solo.depth == 0


def test_d_lt_2_and_n_lt_2_stays_solo():
    org = pick_org(independent_work_items=1, remaining_usd=1.0, child_unit_cost=0.02)
    assert org.depth == 0
    assert pick_child_count(independent_work_items=1) == 0
    broke = pick_org(independent_work_items=8, remaining_usd=0.01, child_unit_cost=0.02)
    assert broke.depth == 0


def test_over_span_adds_layer_even_when_layer_costs_more():
    org = pick_org(
        independent_work_items=8,
        remaining_usd=10.0,
        child_unit_cost=0.01,
        manager_unit_cost=5.0,
        parent_span_usd=0.04,
    )
    assert org.depth == 2
    assert org.widths[0] == 2


def test_layer_not_added_when_under_span_and_more_expensive():
    org = pick_org(
        independent_work_items=3,
        remaining_usd=10.0,
        child_unit_cost=0.01,
        manager_unit_cost=1.0,
        parent_span_usd=0.03,
    )
    assert org.depth == 1
    assert org.widths == (3,)


def test_chain_is_not_eight_independent_pieces():
    tree = work_tree_from_pieces(
        [WorkPiece("p0")]
        + [WorkPiece(f"p{i}", waits_on=(f"p{i-1}",)) for i in range(1, 8)]
    )
    assert tree.independent_count() == 1
    assert tree.work_depth() == 8
    org = pick_org(work_tree=tree, **_BUDGET)
    assert org.depth == 0


def test_width_still_uses_pick_child_count():
    n = pick_child_count(independent_work_items=8, **_BUDGET)
    assert n == SPAN
    org = pick_org(independent_work_items=8, **_BUDGET)
    assert max(org.widths) <= n
    assert max(org.widths) <= SPAN


def test_work_tree_from_goal_unknown_does_not_invent_one():
    tree = work_tree_from_goal("please handle this request carefully and finish it")
    assert tree.unknown is True
    assert tree.independent_count() is None
