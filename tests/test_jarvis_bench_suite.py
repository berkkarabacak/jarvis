"""ORCH-332 / ORCH-347: multi-task bench helpers (no live LLM / Bridge)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app.jarvis.cost_index import unique_artifact_rel

SEED = "20260813T000000Z-abc123"
SEED_ORG = "20260814T080000Z-orch347"


def _load_suite():
    path = Path(__file__).resolve().parents[1] / "scripts" / "benchmarks" / "jarvis_suite_bench.py"
    spec = importlib.util.spec_from_file_location("jarvis_suite_bench", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def suite():
    return _load_suite()


def test_suite_ships_required_tasks(suite):
    assert set(suite.TASKS) >= {
        "tetris",
        "spreadsheet",
        "organize_dry_run",
        "local_fact",
        "fail_then_escalate",
        "cheap_math_1",
        "cheap_math_2",
        "cheap_math_3",
        "windows_service_stub",
        "two_file_split",
    }
    assert suite.TASKS["csv_report"] is suite.TASKS["spreadsheet"]
    assert suite.TASKS["tool_fact"] is suite.TASKS["local_fact"]
    assert suite.TASKS["escalate_billing"] is suite.TASKS["fail_then_escalate"]
    assert suite.TASKS["split_stub_readme"] is suite.TASKS["two_file_split"]
    assert "local_fact" in suite.DEFAULT_TASKS
    assert "fail_then_escalate" in suite.DEFAULT_TASKS
    assert "cheap_math" not in suite.DEFAULT_TASKS
    assert "cheap_math_1" not in suite.DEFAULT_TASKS
    assert suite.TASKS["organize_dry_run"].special == "organize_plan"
    assert "windows_service_stub" in suite.DEFAULT_TASKS
    assert suite.TASKS["windows_service_stub"].special == "windows_service_stub"
    assert "two_file_split" in suite.DEFAULT_TASKS
    assert suite.TASKS["two_file_split"].id == "two-file-split"
    assert suite.TASKS["two_file_split"].special == "two_file_split"


def test_unique_paths_differ_by_model_task_seed():
    a = unique_artifact_rel(task="spreadsheet", model="openai/gpt-4.1-mini", run_id="r1", suffix=".csv")
    b = unique_artifact_rel(task="spreadsheet", model="openai/gpt-4.1", run_id="r1", suffix=".csv")
    c = unique_artifact_rel(task="spreadsheet", model="openai/gpt-4.1-mini", run_id="r2", suffix=".csv")
    d = unique_artifact_rel(task="tetris-html", model="openai/gpt-4.1-mini", run_id="r1", suffix=".html")
    assert len({a, b, c, d}) == 4
    assert "r1" in a and "r1" in Path(a).name


def test_spreadsheet_heuristic_requires_seed(suite, tmp_path: Path):
    p = tmp_path / f"bench-spreadsheet-x-{SEED}.csv"
    p.write_text(
        f"seed,month,revenue_usd,orders\n{SEED},2026-01,1200,14\n{SEED},2026-02,1500,19\n# bench-seed: {SEED}\n",
        encoding="utf-8",
    )
    assert suite._heuristic_spreadsheet(p, SEED) is True
    assert suite._heuristic_spreadsheet(p, "other-seed") is False
    empty = tmp_path / "empty.csv"
    empty.write_text("month\n", encoding="utf-8")
    assert suite._heuristic_spreadsheet(empty, SEED) is False


def _valid_organize_plan(seed: str = SEED) -> str:
    return json.dumps(
        {
            "dry_run": True,
            "seed": seed,
            "moves": [
                {"file": "invoice.pdf", "bucket": "Docs"},
                {"file": "photo.jpg", "bucket": "Images"},
                {"file": "notes.txt", "bucket": "Docs"},
                {"file": "script.py", "bucket": "Scripts"},
                {"file": "archive.zip", "bucket": "Archives"},
                {"file": "random.bin", "bucket": "Other"},
            ],
        }
    )


def test_organize_heuristic_requires_seed(suite, tmp_path: Path):
    p = tmp_path / "plan.json"
    p.write_text(_valid_organize_plan(), encoding="utf-8")
    assert suite._heuristic_organize(p, SEED) is True
    assert suite._heuristic_organize(p, "nope") is False
    bad = tmp_path / "chat.json"
    bad.write_text('{"hello": "world"}', encoding="utf-8")
    assert suite._heuristic_organize(bad, SEED) is False


def test_organize_listing_is_a_fail(suite, tmp_path: Path):
    listing = tmp_path / f"bench-organize-dry-run-x-{SEED}.json"
    listing.write_text(
        json.dumps(
            {
                "seed": SEED,
                "ok": True,
                "root": "Documents",
                "path": "C:/Users/x/Documents",
                "entries": [{"name": "notes.txt", "type": "file"}],
            }
        ),
        encoding="utf-8",
    )
    assert suite._heuristic_organize(listing, SEED) is False
    assert suite.judge_organize(seed=SEED, task_state={"result": {}}, artifact=listing) is False


def test_organize_home_list_tool_is_a_fail(suite, tmp_path: Path):
    p = tmp_path / f"bench-organize-dry-run-x-{SEED}.json"
    p.write_text(_valid_organize_plan(), encoding="utf-8")
    listed = {
        "result": {
            "tools_used": ["home_list"],
            "data": {"ok": True, "root": "Documents", "entries": []},
        }
    }
    assert suite.judge_organize(seed=SEED, task_state=listed, artifact=p) is False
    moved = {"result": {"tools_used": ["organize_folder"]}}
    assert suite.judge_organize(seed=SEED, task_state=moved, artifact=p) is False
    ok_state = {"result": {"tools_used": ["write_file"]}}
    assert suite.judge_organize(seed=SEED, task_state=ok_state, artifact=p) is True


def test_organize_judge_requires_seed_in_filename(suite, tmp_path: Path):
    p = tmp_path / "plan.json"
    p.write_text(_valid_organize_plan(), encoding="utf-8")
    assert suite._heuristic_organize(p, SEED) is True
    assert suite.judge_organize(seed=SEED, task_state={"result": {}}, artifact=p) is False


def test_organize_goal_does_not_trip_bridge_inference(suite):
    from app.jarvis.bridge_routes import _infer_tool_from_goal

    goal = suite._goal_organize("openai/gpt-4.1-mini", "Exports/x.json", SEED)
    assert _infer_tool_from_goal(goal) is None
    assert "home_list" in goal
    assert "organize_folder" in goal
    assert SEED in goal
    assert "WRITE A PLAN FILE" in goal or "write_file" in goal


def test_tetris_heuristic_requires_seed(suite, tmp_path: Path):
    body = (
        f"<!doctype html><html><!-- bench-seed: {SEED} --><body><canvas></canvas>"
        "<script>/* tetris pieces */ window.addEventListener('keydown', function(){})</script>"
        + ("x" * 800)
        + "</body></html>"
    )
    p = tmp_path / "t.html"
    p.write_text(body, encoding="utf-8")
    assert suite._heuristic_tetris(p, SEED) is True
    assert suite._heuristic_tetris(p, "missing-seed") is False


def test_goals_embed_seed_in_body(suite):
    rel = unique_artifact_rel(task="spreadsheet", model="openai/gpt-4.1-mini", run_id=SEED, suffix=".csv")
    assert SEED in rel
    g = suite._goal_spreadsheet("openai/gpt-4.1-mini", rel, SEED)
    assert SEED in g
    assert rel in g
    t = suite._goal_tetris("openai/gpt-4.1-mini", "Exports/x.html", SEED)
    assert f"bench-seed: {SEED}" in t
    o = suite._goal_organize("openai/gpt-4.1-mini", "Exports/x.json", SEED)
    assert f'"seed": "{SEED}"' in o
    assert "invoice.pdf" in o
    assert "WRITE A PLAN FILE" in o or "write_file" in o
    fact = suite._goal_local_fact("openai/gpt-4.1-mini", "Exports/x.json", SEED)
    assert SEED in fact
    assert "get_disk_space" in fact
    assert "home_list" in fact
    esc = suite._goal_escalate("openai/gpt-4.1-mini", "Exports/x.json", SEED)
    assert f'"seed": "{SEED}"' in esc
    assert "fail-then-escalate" in esc
    svc = suite._goal_windows_service("openai/gpt-4.1-mini", "Exports/x.py", SEED)
    assert SEED in svc
    assert "write_file" in svc
    assert "Do not install" in svc or "Do NOT run sc.exe" in svc


def test_local_fact_goal_does_not_trip_bridge_inference(suite):
    from app.jarvis.bridge_routes import _infer_tool_from_goal

    goal = suite._goal_local_fact("openai/gpt-4.1-mini", "Exports/x.json", SEED)
    assert _infer_tool_from_goal(goal) is None


def test_invented_local_fact_fails(suite):
    invented = {
        "status": "done",
        "result": {
            "summary": "You have 500GB free on C:",
            "tools_used": [],
            "data": {"text": "You have 500GB free. Plenty of space."},
        },
    }
    assert suite.judge_local_fact(seed=SEED, task_state=invented, artifact=None) is False


def test_local_fact_requires_real_tool(suite, tmp_path: Path):
    artifact = tmp_path / f"bench-local-fact-x-{SEED}.json"
    artifact.write_text(
        json.dumps(
            {
                "seed": SEED,
                "tool": "get_disk_space",
                "result": {
                    "ok": True,
                    "drives": [{"drive": "C:", "free_bytes": 12_000_000_000, "free": "11.2 GB"}],
                },
            }
        ),
        encoding="utf-8",
    )
    real = {
        "status": "done",
        "tools_used": ["jarvis-local", "get_disk_space"],
        "result": {
            "tools_used": ["jarvis-local", "get_disk_space"],
            "data": {
                "ok": True,
                "drives": [{"drive": "C:", "free_bytes": 12_000_000_000, "free": "11.2 GB"}],
                "tools_called": ["get_disk_space", "write_file"],
            },
        },
    }
    assert suite.judge_local_fact(seed=SEED, task_state=real, artifact=artifact) is True
    # Same file, no tool call → fail
    assert suite.judge_local_fact(seed=SEED, task_state=invented_chat(), artifact=artifact) is False
    # Tool named but payload invented / missing drives
    fake_tool = {
        "status": "done",
        "result": {
            "tools_used": ["get_disk_space"],
            "data": {"text": "about 500GB I think"},
        },
    }
    assert suite.judge_local_fact(seed=SEED, task_state=fake_tool, artifact=None) is False


def invented_chat():
    return {
        "status": "done",
        "result": {"summary": "looks fine", "tools_used": ["jarvis-local"], "data": {"text": "ok"}},
    }


def test_home_list_local_fact_passes(suite):
    state = {
        "status": "done",
        "result": {
            "tools_used": ["home_list"],
            "data": {
                "ok": True,
                "root": "Desktop",
                "path": "C:/Users/x/Desktop",
                "entries": [{"name": "notes.txt", "type": "file"}],
            },
        },
    }
    assert suite.judge_local_fact(seed=SEED, task_state=state, artifact=None) is True


def test_local_fact_artifact_without_seed_fails(suite, tmp_path: Path):
    p = tmp_path / "nofact.json"
    p.write_text(
        json.dumps(
            {
                "tool": "get_disk_space",
                "result": {"ok": True, "drives": [{"drive": "C:", "free_bytes": 1, "free": "1 B"}]},
            }
        ),
        encoding="utf-8",
    )
    state = {
        "result": {
            "tools_used": ["get_disk_space"],
            "data": {"ok": True, "drives": [{"drive": "C:", "free_bytes": 1, "free": "1 B"}]},
        }
    }
    assert suite.judge_local_fact(seed=SEED, task_state=state, artifact=p) is False


def test_escalate_card_heuristic_requires_seed(suite, tmp_path: Path):
    p = tmp_path / f"bench-fail-then-escalate-x-{SEED}.json"
    p.write_text(
        json.dumps(
            {
                "seed": SEED,
                "bench_model": "openai/gpt-4.1-mini",
                "task": "fail-then-escalate",
                "status": "ok",
            }
        ),
        encoding="utf-8",
    )
    assert suite._heuristic_escalate_card(p, SEED) is True
    assert suite._heuristic_escalate_card(p, "other") is False
    bad = tmp_path / "chat.json"
    bad.write_text('{"status": "ok"}', encoding="utf-8")
    assert suite._heuristic_escalate_card(bad, SEED) is False


def test_fail_then_escalate_runner_folds(suite, monkeypatch):
    cheap = suite.BenchRow(
        model="openai/gpt-4.1-mini",
        task="fail-then-escalate",
        ok=False,
        elapsed_sec=8.0,
        status="done",
        artifact=None,
        artifact_bytes=0,
        cost_usd=0.006,
        cost_unknown=False,
        cost_source="openrouter",
        escalate=False,
        summary="missing seed",
        heuristics_pass=False,
        run_id=SEED,
        seed=SEED,
    )
    strong = suite.BenchRow(
        model="openai/gpt-4.1",
        task="fail-then-escalate",
        ok=True,
        elapsed_sec=10.0,
        status="done",
        artifact="Exports/x.json",
        artifact_bytes=80,
        cost_usd=0.024,
        cost_unknown=False,
        cost_source="openrouter",
        escalate=False,
        summary="ok",
        heuristics_pass=True,
        run_id=SEED,
        seed=SEED,
    )
    calls = iter([cheap, strong])
    monkeypatch.setattr(suite, "run_one", lambda *a, **k: next(calls))
    row = suite.run_fail_then_escalate(
        "http://127.0.0.1:8787",
        "openai/gpt-4.1-mini",
        "openai/gpt-4.1",
        suite.TASKS["fail_then_escalate"],
        SEED,
        30,
    )
    assert row["ok"] is True
    assert row["escalate"] is True
    assert row["cost_usd"] == pytest.approx(0.030)
    assert row["model"] == "openai/gpt-4.1-mini"
    assert len(row["attempts"]) == 2
    assert row["attempts"][0]["ok"] is False
    assert row["attempts"][1]["ok"] is True


def test_fail_then_escalate_cheap_success_no_retry(suite, monkeypatch):
    cheap = suite.BenchRow(
        model="openai/gpt-4.1-mini",
        task="fail-then-escalate",
        ok=True,
        elapsed_sec=4.0,
        status="done",
        artifact="Exports/x.json",
        artifact_bytes=40,
        cost_usd=0.006,
        cost_unknown=False,
        cost_source="openrouter",
        escalate=False,
        summary="ok",
        heuristics_pass=True,
        run_id=SEED,
        seed=SEED,
    )
    monkeypatch.setattr(suite, "run_one", lambda *a, **k: cheap)
    row = suite.run_fail_then_escalate(
        "http://x",
        "openai/gpt-4.1-mini",
        "openai/gpt-4.1",
        suite.TASKS["fail_then_escalate"],
        SEED,
        30,
    )
    assert row["escalate"] is False
    assert row["attempt_count"] == 1
    assert row["cost_usd"] == pytest.approx(0.006)


def test_pick_escalate_model(suite):
    assert suite.pick_escalate_model(["openai/gpt-4.1-mini", "openai/gpt-4.1"], "openai/gpt-4.1-mini") == "openai/gpt-4.1"
    assert suite.pick_escalate_model(["openai/gpt-4.1-mini"], "openai/gpt-4.1-mini") == "openai/gpt-4.1"


def test_expand_cheap_math_alias(suite):
    assert suite.expand_task_ids(["cheap_math"]) == [
        "cheap_math_1",
        "cheap_math_2",
        "cheap_math_3",
    ]
    assert suite.expand_task_ids(["tetris", "cheap_math"])[-3:] == list(suite.CHEAP_MATH_IDS)


def test_cheap_math_goals_and_exact_grade(suite, tmp_path: Path):
    answers = {item[0]: item[2] for item in suite.CHEAP_MATH_ITEMS}
    questions = {item[0]: item[1] for item in suite.CHEAP_MATH_ITEMS}
    for tid, expected in answers.items():
        spec = suite.TASKS[tid]
        rel = unique_artifact_rel(task=spec.id, model="openai/gpt-4.1-mini", run_id=SEED, suffix=".json")
        goal = spec.goal("openai/gpt-4.1-mini", rel, SEED)
        assert SEED in goal
        assert questions[tid] in goal
        assert "AIME" not in goal and "IMO" not in goal
        p = tmp_path / f"bench-{spec.id}-x-{SEED}.json"
        p.write_text(json.dumps({"seed": SEED, "answer": expected}), encoding="utf-8")
        assert spec.heuristic(p, SEED) is True
        p.write_text(json.dumps({"seed": SEED, "answer": expected + 1}), encoding="utf-8")
        assert spec.heuristic(p, SEED) is False
        p.write_text(json.dumps({"seed": "other", "answer": expected}), encoding="utf-8")
        assert spec.heuristic(p, SEED) is False


def test_scorecard_footer_is_ascii_lambda(suite):
    text = suite.format_scorecard_footer("successes / (cost_usd + lambda * sec)", 0.0001)
    assert "lambda=" in text
    assert "λ" not in text
    text.encode("cp1252")


def test_windows_service_stub_requires_file_seed_and_marker(suite, tmp_path: Path):
    named = tmp_path / f"bench-windows-service-stub-x-{SEED}.py"
    named.write_text(
        f'# bench-seed: {SEED}\nServiceName = "{SEED}"\n# sc create {SEED} binPath= python.exe\n',
        encoding="utf-8",
    )
    assert suite._heuristic_windows_service(named, SEED) is True
    assert suite.judge_windows_service_stub(seed=SEED, artifact=named) is True
    assert suite.judge_windows_service_stub(seed=SEED, artifact=None) is False
    chat = tmp_path / f"notes-{SEED}.txt"
    chat.write_text(f"I would create a service named {SEED} if you want.\n", encoding="utf-8")
    assert suite._heuristic_windows_service(chat, SEED) is False
    no_name = tmp_path / "stub.py"
    no_name.write_text(
        f'# bench-seed: {SEED}\nServiceName = "{SEED}"\n',
        encoding="utf-8",
    )
    assert suite._heuristic_windows_service(no_name, SEED) is True
    assert suite.judge_windows_service_stub(seed=SEED, artifact=no_name) is False


def test_windows_service_accepts_win32_and_nssm(suite, tmp_path: Path):
    p = tmp_path / f"bench-windows-service-stub-x-{SEED}.py"
    p.write_text(f"import win32service\n# bench-seed: {SEED}\n", encoding="utf-8")
    assert suite._heuristic_windows_service(p, SEED) is True
    p.write_text(f"nssm install {SEED} C:\\app.exe\n# bench-seed: {SEED}\n", encoding="utf-8")
    assert suite._heuristic_windows_service(p, SEED) is True
    p.write_text(f"# bench-seed: {SEED}\nprint('hello')\n", encoding="utf-8")
    assert suite._heuristic_windows_service(p, SEED) is False


def test_windows_service_goal_does_not_trip_bridge_inference(suite):
    from app.jarvis.bridge_routes import _infer_tool_from_goal

    goal = suite._goal_windows_service("openai/gpt-4.1-mini", "Exports/x.py", SEED)
    assert _infer_tool_from_goal(goal) is None


def test_scorecard_table_includes_seconds(suite):
    lines = suite.format_scorecard_table(
        [
            {
                "model": "openai/gpt-4.1-mini",
                "pass_at_1": 0.6667,
                "cost_unknown": False,
                "usd_per_success": 0.01,
                "escalate_pct": 0.0,
                "seconds": 42.5,
                "ours_composite": 10.0,
            }
        ]
    )
    assert lines[0].startswith("| model | pass@1 | $ per success | escalate % | seconds |")
    assert "| 42.5 |" in lines[2]
    assert "0.6667" in lines[2]


def _valid_two_file_pair(tmp_path: Path, suite, *, seed: str = SEED):
    stub_rel, readme_rel = suite.two_file_split_rels("openai/gpt-4.1-mini", seed)
    stub = tmp_path / Path(stub_rel).name
    readme = tmp_path / Path(readme_rel).name
    stub.write_text(f"# bench-seed: {seed}\nprint('stub')\n", encoding="utf-8")
    readme.write_text(f"# README\nbench-seed: {seed}\n", encoding="utf-8")
    return stub, readme


def test_two_file_split_judge_passes_both_seeded_files(suite, tmp_path: Path):
    stub, readme = _valid_two_file_pair(tmp_path, suite)
    assert suite.judge_two_file_split(seed=SEED, stub=stub, readme=readme) is True


def test_two_file_split_judge_fails_only_stub(suite, tmp_path: Path):
    stub, _readme = _valid_two_file_pair(tmp_path, suite)
    assert suite.judge_two_file_split(seed=SEED, stub=stub, readme=None) is False
    missing = tmp_path / f"bench-two-file-split-readme-x-{SEED}.md"
    assert suite.judge_two_file_split(seed=SEED, stub=stub, readme=missing) is False


def test_two_file_split_judge_fails_only_readme(suite, tmp_path: Path):
    _stub, readme = _valid_two_file_pair(tmp_path, suite)
    assert suite.judge_two_file_split(seed=SEED, stub=None, readme=readme) is False
    missing = tmp_path / f"bench-two-file-split-stub-x-{SEED}.py"
    assert suite.judge_two_file_split(seed=SEED, stub=missing, readme=readme) is False


def test_two_file_split_judge_fails_missing_seed_in_name_or_body(suite, tmp_path: Path):
    stub, readme = _valid_two_file_pair(tmp_path, suite)
    unnamed = tmp_path / "stub.py"
    unnamed.write_text(f"# bench-seed: {SEED}\nprint('stub')\n", encoding="utf-8")
    assert suite.judge_two_file_split(seed=SEED, stub=unnamed, readme=readme) is False
    stub_rel, readme_rel = suite.two_file_split_rels("openai/gpt-4.1-mini", SEED)
    no_body = tmp_path / "no-body-stub" / Path(stub_rel).name
    no_body.parent.mkdir()
    no_body.write_text("print('stub without seed')\n", encoding="utf-8")
    assert suite.judge_two_file_split(seed=SEED, stub=no_body, readme=readme) is False
    readme_unnamed = tmp_path / "README.md"
    readme_unnamed.write_text(f"bench-seed: {SEED}\n", encoding="utf-8")
    assert suite.judge_two_file_split(seed=SEED, stub=stub, readme=readme_unnamed) is False
    readme_no_body = tmp_path / "no-body-readme" / Path(readme_rel).name
    readme_no_body.parent.mkdir()
    readme_no_body.write_text("# README with no seed\n", encoding="utf-8")
    assert suite.judge_two_file_split(seed=SEED, stub=stub, readme=readme_no_body) is False


def test_two_file_split_judge_fails_chat_only(suite, tmp_path: Path):
    assert suite.judge_two_file_split(seed=SEED, stub=None, readme=None) is False
    chat = tmp_path / f"notes-{SEED}.txt"
    chat.write_text(f"I would write the stub and readme with seed {SEED}.\n", encoding="utf-8")
    assert suite.judge_two_file_split(seed=SEED, stub=chat, readme=None) is False
    assert suite.judge_two_file_split(seed=SEED, stub=None, readme=chat) is False


def test_two_file_split_judge_passes_solo_empty_tools(suite, tmp_path: Path):
    stub, readme = _valid_two_file_pair(tmp_path, suite)
    assert suite.judge_two_file_split(seed=SEED, stub=stub, readme=readme, task_state=None) is True
    assert suite.judge_two_file_split(seed=SEED, stub=stub, readme=readme, task_state={}) is True
    empty_tools = {"result": {"tools_used": [], "data": {}}}
    assert suite.judge_two_file_split(seed=SEED, stub=stub, readme=readme, task_state=empty_tools) is True
    assert suite._heuristic_two_file_split(stub, SEED) is False


def test_two_file_split_goal_is_two_work_items(suite):
    from app.jarvis.children import count_independent_work_items, pick_child_count

    stub, _readme = suite.two_file_split_rels("openai/gpt-4.1-mini", SEED)
    goal = suite._goal_two_file_split("openai/gpt-4.1-mini", stub, SEED)
    assert count_independent_work_items(goal) == 2
    assert pick_child_count(
        independent_work_items=2,
        remaining_usd=1.0,
        child_unit_cost=0.02,
        remaining_seconds=120,
        child_unit_seconds=5,
    ) == 2


def test_two_file_split_goal_embeds_seed_rels_and_split_wording(suite):
    stub, readme = suite.two_file_split_rels("openai/gpt-4.1-mini", SEED)
    assert SEED in stub and SEED in readme
    assert stub.endswith(".py") and readme.endswith(".md")
    assert "stub" in Path(stub).name and "readme" in Path(readme).name
    spec = suite.TASKS["two_file_split"]
    assert suite.artifact_rels_for(spec, "openai/gpt-4.1-mini", SEED) == [stub, readme]
    goal = suite._goal_two_file_split("openai/gpt-4.1-mini", stub, SEED)
    assert SEED in goal
    assert stub in goal
    assert readme in goal
    low = goal.lower()
    assert "split this" in low
    assert "one child writes the stub" in low
    assert "one writes the readme" in low


def test_two_file_split_goal_does_not_trip_bridge_inference(suite):
    from app.jarvis.bridge_routes import _infer_tool_from_goal

    stub, _readme = suite.two_file_split_rels("openai/gpt-4.1-mini", SEED)
    goal = suite._goal_two_file_split("openai/gpt-4.1-mini", stub, SEED)
    assert _infer_tool_from_goal(goal) is None


def test_two_file_split_solo_orchestration_defaults(suite):
    meta = suite.extract_orchestration_meta(None, model="openai/gpt-4.1-mini", parent_cost=0.01)
    assert meta["parent_cost_usd"] == 0.01
    assert meta["child_cost_usd"] == 0.0
    assert meta["who_did_what"] == "solo parent wrote both"
    assert meta["models_used"] == ["openai/gpt-4.1-mini"]
    assert meta["depth"] == 0
    assert meta["agent_count"] == 1
    empty = suite.extract_orchestration_meta({}, model="openai/gpt-4.1-mini", parent_cost=None)
    assert empty["child_cost_usd"] == 0.0
    assert empty["who_did_what"] == "solo parent wrote both"
    assert empty["parent_cost_usd"] is None
    assert empty["depth"] == 0
    assert empty["agent_count"] == 1
    row = suite._error_row("openai/gpt-4.1-mini", "two-file-split", SEED, RuntimeError("x"))
    assert row.child_cost_usd == 0.0
    assert row.who_did_what == "solo parent wrote both"
    assert row.models_used == ["openai/gpt-4.1-mini"]
    assert row.depth == 0
    assert row.agent_count == 1


def test_two_file_split_child_breakdown(suite):
    state = {
        "result": {
            "data": {
                "children": [
                    {"id": "child-A", "role": "stub", "model": "openai/gpt-4.1-mini", "cost_usd": 0.002},
                    {"id": "child-B", "role": "readme", "model": "openai/gpt-4.1", "cost_usd": 0.004},
                ],
                "child_cost_usd": 0.006,
                "who_did_what": "child-A stub / child-B readme",
                "models_used": ["openai/gpt-4.1-mini", "openai/gpt-4.1"],
            }
        }
    }
    meta = suite.extract_orchestration_meta(state, model="openai/gpt-4.1-mini", parent_cost=0.01)
    assert meta["parent_cost_usd"] == 0.01
    assert meta["child_cost_usd"] == pytest.approx(0.006)
    assert meta["who_did_what"] == "child-A stub / child-B readme"
    assert meta["models_used"] == ["openai/gpt-4.1-mini", "openai/gpt-4.1"]
    derived = suite.extract_orchestration_meta(
        {
            "children": [
                {"id": "child-A", "role": "stub", "model": "openai/gpt-4.1-mini", "cost_usd": 0.002},
                {"id": "child-B", "role": "readme", "model": "openai/gpt-4.1", "cost_usd": 0.004},
            ]
        },
        model="openai/gpt-4.1-mini",
        parent_cost=0.01,
    )
    assert derived["child_cost_usd"] == pytest.approx(0.006)
    assert derived["who_did_what"] == "child-A stub / child-B readme"
    assert derived["depth"] == 1
    assert derived["agent_count"] == 3
    unknown = suite.extract_orchestration_meta(
        {"children": [{"id": "child-A", "role": "stub"}], "child_cost_usd": 0.0},
        model="openai/gpt-4.1-mini",
        parent_cost=0.01,
    )
    assert unknown["child_cost_usd"] is None
    assert unknown["depth"] == 1
    assert unknown["agent_count"] == 2


def _stub_depth_two_org(*, seed: str = SEED_ORG) -> dict:
    """8-piece manager tree (parent -> 2 managers -> 8 workers). Unique seed."""
    workers_a = [
        {"id": f"w{i}", "role": f"piece-{i}", "model": "openai/gpt-4.1-mini", "cost_usd": 0.002}
        for i in range(1, 5)
    ]
    workers_b = [
        {"id": f"w{i}", "role": f"piece-{i}", "model": "openai/gpt-4.1-mini", "cost_usd": 0.002}
        for i in range(5, 9)
    ]
    return {
        "seed": seed,
        "depth": 2,
        "agent_count": 11,
        "children": [
            {
                "id": "mgr-A",
                "role": "manager",
                "model": "openai/gpt-4.1-mini",
                "cost_usd": 0.004,
                "children": workers_a,
            },
            {
                "id": "mgr-B",
                "role": "manager",
                "model": "openai/gpt-4.1",
                "cost_usd": 0.004,
                "children": workers_b,
            },
        ],
        "who_did_what": (
            "mgr-A manager / w1 piece-1 / w2 piece-2 / w3 piece-3 / w4 piece-4 / "
            "mgr-B manager / w5 piece-5 / w6 piece-6 / w7 piece-7 / w8 piece-8"
        ),
        "child_cost_usd": 0.024,
        "models_used": ["openai/gpt-4.1-mini", "openai/gpt-4.1"],
    }


def test_org_shape_solo_is_depth_zero(suite):
    """Tiny solo job must not grow an org (ORCH-347). Unique seed."""
    meta = suite.extract_orchestration_meta(None, model="openai/gpt-4.1-mini", parent_cost=0.01)
    assert meta["depth"] == 0
    assert meta["agent_count"] == 1
    assert meta["parent_cost_usd"] == 0.01
    assert meta["child_cost_usd"] == 0.0
    assert meta["who_did_what"] == "solo parent wrote both"
    stray = suite.extract_orchestration_meta(
        {"depth": 2, "agent_count": 11, "org_depth": 2},
        model="openai/gpt-4.1-mini",
        parent_cost=0.01,
    )
    assert stray["depth"] == 0
    assert stray["agent_count"] == 1
    assert stray["child_cost_usd"] == 0.0
    row = suite.BenchRow(
        model="openai/gpt-4.1-mini",
        task="cheap-math-1",
        ok=True,
        elapsed_sec=1.2,
        status="done",
        artifact=None,
        artifact_bytes=0,
        cost_usd=0.01,
        cost_unknown=False,
        cost_source="openrouter",
        escalate=False,
        summary="ok",
        heuristics_pass=True,
        run_id=SEED_ORG,
        seed=SEED_ORG,
        parent_cost_usd=0.01,
        child_cost_usd=0.0,
        models_used=["openai/gpt-4.1-mini"],
        who_did_what="solo parent wrote both",
        depth=0,
        agent_count=1,
    )
    dumped = suite.asdict(row)
    assert dumped["depth"] == 0
    assert dumped["agent_count"] == 1
    assert dumped["parent_cost_usd"] == 0.01
    assert dumped["child_cost_usd"] == 0.0
    assert dumped["elapsed_sec"] == 1.2
    assert dumped["seed"] == SEED_ORG
    assert dumped["seed"] != SEED


def test_org_shape_stubbed_depth_two_row(suite):
    """Stubbed depth-2 org (managers + workers) records shape without spawn."""
    org = _stub_depth_two_org()
    assert org["seed"] == SEED_ORG
    assert org["seed"] != SEED
    meta = suite.extract_orchestration_meta(
        {"result": {"data": org}},
        model="openai/gpt-4.1-mini",
        parent_cost=0.02,
    )
    assert meta["depth"] == 2
    assert meta["agent_count"] == 11
    assert meta["parent_cost_usd"] == 0.02
    assert meta["child_cost_usd"] == pytest.approx(0.024)
    assert "manager" in meta["who_did_what"]
    assert "mgr-A manager" in meta["who_did_what"]
    assert "mgr-B manager" in meta["who_did_what"]
    assert "w1 piece-1" in meta["who_did_what"]
    assert "w8 piece-8" in meta["who_did_what"]
    assert meta["models_used"] == ["openai/gpt-4.1-mini", "openai/gpt-4.1"]
    derived = suite.extract_orchestration_meta(
        {"children": org["children"]},
        model="openai/gpt-4.1-mini",
        parent_cost=0.02,
    )
    assert derived["depth"] == 2
    assert derived["agent_count"] == 11
    assert derived["child_cost_usd"] == pytest.approx(0.024)
    assert "mgr-A manager" in derived["who_did_what"]
    assert "w4 piece-4" in derived["who_did_what"]
    row = suite.BenchRow(
        model="openai/gpt-4.1-mini",
        task="eight-piece-org",
        ok=True,
        elapsed_sec=12.5,
        status="done",
        artifact=None,
        artifact_bytes=0,
        cost_usd=0.044,
        cost_unknown=False,
        cost_source="openrouter",
        escalate=False,
        summary="ok",
        heuristics_pass=True,
        run_id=SEED_ORG,
        seed=SEED_ORG,
        parent_cost_usd=meta["parent_cost_usd"],
        child_cost_usd=meta["child_cost_usd"],
        models_used=meta["models_used"],
        who_did_what=meta["who_did_what"],
        depth=meta["depth"],
        agent_count=meta["agent_count"],
    )
    dumped = suite.asdict(row)
    assert dumped["depth"] == 2
    assert dumped["agent_count"] == 11
    assert dumped["parent_cost_usd"] == 0.02
    assert dumped["child_cost_usd"] == pytest.approx(0.024)
    assert dumped["elapsed_sec"] == 12.5
    assert "manager" in dumped["who_did_what"]
    assert dumped["seed"] == SEED_ORG
    assert suite.org_depth_from_children(org["children"]) == 2
    assert suite.agent_count_from_children(org["children"]) == 11
    assert suite.org_depth_from_children([]) == 0
    assert suite.agent_count_from_children([]) == 1
