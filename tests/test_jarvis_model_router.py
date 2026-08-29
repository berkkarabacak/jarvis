"""ORCH-328 / ORCH-362: Jarvis model router policy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.jarvis.model_router import (
    classify_task,
    load_bench_preferred_cheap,
    load_state,
    record_outcome,
    remember_scorecard_path,
    reset_state_for_tests,
    resolve_hard_pin,
    route_model,
)
from app.jarvis.openrouter_leaders import (
    SNAPSHOT_MODEL_IDS,
    cheap_catalog_ids,
    reset_leaders_cache_for_tests,
    smart_catalog_ids,
    snapshot_leaders,
)

HIGH_IQ_SNAPSHOT = {m.model for m in snapshot_leaders() if m.is_high_iq}
USAGE_RANK_ONE = "deepseek/deepseek-v4-flash-0731"
FREE_SNAPSHOT = {m.model for m in snapshot_leaders() if m.is_free}


@pytest.fixture()
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("JARVIS_WORKSPACE", str(tmp_path))
    # clear pin-ish env
    monkeypatch.delenv("JARVIS_MODEL_PIN", raising=False)
    monkeypatch.delenv("JARVIS_DISABLE_MODEL_ROUTER", raising=False)
    monkeypatch.delenv("JARVIS_MODEL_PREFERENCE", raising=False)
    monkeypatch.delenv("KIMI_CODE_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_OPERATOR_OPENROUTER_KEY", raising=False)
    monkeypatch.setenv("JARVIS_MODEL", "openai/gpt-4.1-mini")
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "0")
    reset_state_for_tests(tmp_path)
    reset_leaders_cache_for_tests()
    # ensure settings store empty
    from app.jarvis import settings_store

    settings_store.reset_cache()
    mem = tmp_path / "Memory"
    mem.mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_classify_routine_build():
    assert classify_task("Build a simple Tetris HTML file under Exports/") == "routine_build"


def test_classify_hard():
    assert classify_task("Please refactor the multi-file codebase architecture") == "hard"


def test_classify_light():
    assert classify_task("How much free disk space do I have?") == "light"


LIVE_ARCH_PLAN = (
    "Explain a careful plan to split a messy 20-file Python app into layers "
    "(api, domain, data) without breaking callers. List risks and the first "
    "5 files to touch. Do not write files."
)


def test_classify_live_architecture_plan_is_hard():
    assert classify_task(LIVE_ARCH_PLAN) == "hard"


def test_list_files_on_desktop_still_light():
    assert classify_task("List files on my desktop") == "light"


def test_live_architecture_plan_routes_to_paid_smart(ws: Path):
    choice = route_model(goal=LIVE_ARCH_PLAN, workspace_root=ws)
    assert choice.task_class == "hard"
    assert choice.escalate is False
    assert choice.model == smart_catalog_ids(snapshot_leaders())[0]
    assert choice.model in HIGH_IQ_SNAPSHOT
    assert choice.model in SNAPSHOT_MODEL_IDS
    assert choice.model not in FREE_SNAPSHOT
    assert choice.model != USAGE_RANK_ONE
    assert not choice.model.endswith(":free")
    assert "high-IQ" in choice.reason


def test_cheap_default_for_routine_build(ws: Path, monkeypatch: pytest.MonkeyPatch):
    choice = route_model(
        goal="Create a playable tetris as one HTML file with write_file",
        workspace_root=ws,
    )
    assert choice.pinned is False
    cheap = cheap_catalog_ids(snapshot_leaders(), allow_free=False)[0]
    assert choice.model == cheap
    assert choice.model in SNAPSHOT_MODEL_IDS
    assert choice.model not in FREE_SNAPSHOT
    assert choice.task_class == "routine_build"
    assert "bench" in choice.reason or "task_class=routine_build" in choice.reason
    assert "catalog=snapshot" in choice.reason


def test_hard_first_pick_is_paid_smart_leader(ws: Path):
    choice = route_model(
        goal="Refactor the multi-file codebase architecture carefully",
        workspace_root=ws,
    )
    assert choice.task_class == "hard"
    assert choice.escalate is False
    assert choice.model == smart_catalog_ids(snapshot_leaders())[0]
    assert choice.model in HIGH_IQ_SNAPSHOT
    assert choice.model in SNAPSHOT_MODEL_IDS
    assert choice.model not in FREE_SNAPSHOT
    assert choice.model != USAGE_RANK_ONE
    assert not choice.model.endswith(":free")
    assert "high-IQ" in choice.reason
    assert "rank=1" not in choice.reason
    assert "#1" not in choice.reason
    assert "usage" not in choice.reason.lower()


def test_light_goal_may_be_cheap_or_free(ws: Path):
    choice = route_model(
        goal="How much free disk space do I have?",
        workspace_root=ws,
    )
    assert choice.task_class == "light"
    assert choice.escalate is False
    assert choice.model in SNAPSHOT_MODEL_IDS
    cheap_free_ok = cheap_catalog_ids(snapshot_leaders(), allow_free=True)
    assert choice.model == cheap_free_ok[0]
    assert choice.model in FREE_SNAPSHOT or choice.model in SNAPSHOT_MODEL_IDS


def test_fail_then_escalate(ws: Path):
    first = route_model(
        goal="Build a tiny HTML game with write_file to Exports/",
        workspace_root=ws,
    )
    record_outcome(
        model=first.model,
        reason="test",
        task_class="routine_build",
        ok=False,
        root=ws,
    )
    choice = route_model(
        goal="Build a tiny HTML game with write_file to Exports/",
        workspace_root=ws,
    )
    assert first.escalate is False
    assert choice.escalate is True
    assert choice.model != first.model
    assert choice.model in SNAPSHOT_MODEL_IDS


def test_hard_fail_escalates_to_another_smart_leader(ws: Path):
    first = route_model(
        goal="Refactor the multi-file codebase architecture carefully",
        workspace_root=ws,
    )
    record_outcome(
        model=first.model,
        reason="test",
        task_class="hard",
        ok=False,
        root=ws,
    )
    choice = route_model(
        goal="Refactor the multi-file codebase architecture carefully",
        workspace_root=ws,
    )
    assert first.model in HIGH_IQ_SNAPSHOT
    assert choice.escalate is True
    assert choice.model != first.model
    assert choice.model not in FREE_SNAPSHOT
    assert choice.model != USAGE_RANK_ONE


def test_explicit_model_is_hard_pin(ws: Path):
    choice = route_model(
        goal="Build tetris",
        explicit_model="openai/gpt-4.1",
        workspace_root=ws,
    )
    assert choice.pinned is True
    assert choice.model == "openai/gpt-4.1"
    assert "hard pin" in choice.reason


def test_settings_model_is_hard_pin(ws: Path, monkeypatch: pytest.MonkeyPatch):
    from app.jarvis import settings_store

    settings_store.save(
        {"model": "anthropic/claude-sonnet-4", "model_lock": True},
        root=ws,
    )
    settings_store.reset_cache()
    assert resolve_hard_pin(root=ws) == "anthropic/claude-sonnet-4"
    choice = route_model(goal="Build tetris HTML", workspace_root=ws)
    assert choice.pinned is True
    assert choice.model == "anthropic/claude-sonnet-4"


def test_unlocked_settings_model_is_default_helper(ws: Path):
    from app.jarvis import settings_store

    helper = "xiaomi/mimo-v2.5"
    settings_store.save({"model": helper, "model_lock": False}, root=ws)
    settings_store.reset_cache()
    assert resolve_hard_pin(root=ws) is None
    light = route_model(goal="How much free disk space do I have?", workspace_root=ws)
    assert light.pinned is False
    assert light.model == helper
    hard = route_model(
        goal="Refactor the multi-file codebase architecture carefully",
        workspace_root=ws,
    )
    assert hard.pinned is False
    assert hard.model != helper
    assert hard.model == smart_catalog_ids(snapshot_leaders())[0]


def test_env_pin_flag(ws: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JARVIS_MODEL_PIN", "true")
    monkeypatch.setenv("JARVIS_MODEL", "openai/gpt-4.1")
    choice = route_model(goal="Build tetris", workspace_root=ws)
    assert choice.pinned is True
    assert choice.model == "openai/gpt-4.1"


def test_bench_json_preferred_cheap(ws: Path, tmp_path: Path):
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir()
    (bench_dir / "jarvis-tetris-latest.json").write_text(
        json.dumps(
            {
                "results": [
                    {"model": "openai/gpt-4.1", "ok": True, "cost_usd": 0.08},
                    {"model": "openai/gpt-4.1-mini", "ok": True, "cost_usd": 0.02},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert load_bench_preferred_cheap(tmp_path) == "openai/gpt-4.1-mini"


def test_index_json_preferred_over_tetris(ws: Path, tmp_path: Path):
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir()
    (bench_dir / "jarvis-tetris-latest.json").write_text(
        json.dumps(
            {
                "results": [
                    {"model": "openai/gpt-4.1", "ok": True, "cost_usd": 0.01},
                ]
            }
        ),
        encoding="utf-8",
    )
    (bench_dir / "jarvis-index-latest.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "model": "openai/gpt-4.1-mini",
                        "ok": True,
                        "elapsed_sec": 20,
                        "cost_usd": 0.012,
                    },
                    {
                        "model": "openai/gpt-4.1",
                        "ok": True,
                        "elapsed_sec": 18,
                        "cost_usd": 0.048,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    assert load_bench_preferred_cheap(tmp_path) == "openai/gpt-4.1-mini"


def test_zero_cost_tetris_row_not_treated_as_free(ws: Path, tmp_path: Path):
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir()
    (bench_dir / "jarvis-tetris-latest.json").write_text(
        json.dumps(
            {
                "results": [
                    {"model": "google/gemini-2.5-flash", "ok": True, "cost_usd": 0.0},
                    {"model": "openai/gpt-4.1-mini", "ok": True, "cost_usd": 0.02},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert load_bench_preferred_cheap(tmp_path) == "openai/gpt-4.1-mini"


def test_scorecard_persists_last_path(ws: Path, tmp_path: Path):
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir()
    index = bench_dir / "jarvis-index-latest.json"
    index.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "model": "openai/gpt-4.1-mini",
                        "ok": True,
                        "elapsed_sec": 10,
                        "cost_usd": 0.012,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    remembered = remember_scorecard_path(repo_root=tmp_path, workspace_root=ws)
    assert remembered == str(index.resolve())
    state = load_state(ws)
    assert state["last_scorecard_path"] == str(index.resolve())


def test_route_model_persists_scorecard_and_orders_ladder(ws: Path, tmp_path: Path):
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir()
    (bench_dir / "jarvis-index-latest.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "model": "openai/gpt-4.1-mini",
                        "ok": True,
                        "elapsed_sec": 10,
                        "cost_usd": 0.02,
                    },
                    {
                        "model": "openai/gpt-4.1-mini",
                        "ok": False,
                        "elapsed_sec": 10,
                        "cost_usd": 0.02,
                    },
                    {
                        "model": "openai/gpt-4.1",
                        "ok": True,
                        "elapsed_sec": 10,
                        "cost_usd": 0.08,
                    },
                    {
                        "model": "openai/gpt-4.1",
                        "ok": False,
                        "elapsed_sec": 10,
                        "cost_usd": 0.08,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    choice = route_model(
        goal="Create a playable tetris as one HTML file with write_file",
        workspace_root=ws,
        repo_root=tmp_path,
    )
    assert choice.pinned is False
    assert choice.model == "openai/gpt-4.1-mini"
    assert choice.metadata["ladder"][0] == "openai/gpt-4.1-mini"
    assert "openai/gpt-4.1" in choice.metadata["ladder"]
    state = load_state(ws)
    assert state["last_scorecard_path"].endswith("jarvis-index-latest.json")


def test_hard_pin_still_wins_over_scorecard(ws: Path, tmp_path: Path):
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir()
    (bench_dir / "jarvis-index-latest.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "model": "openai/gpt-4.1-mini",
                        "ok": True,
                        "elapsed_sec": 10,
                        "cost_usd": 0.012,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    choice = route_model(
        goal="Build tetris",
        explicit_model="anthropic/claude-sonnet-4",
        workspace_root=ws,
        repo_root=tmp_path,
    )
    assert choice.pinned is True
    assert choice.model == "anthropic/claude-sonnet-4"


def test_build_jarvis_agent_surfaces_why(ws: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    from app.jarvis.agent import build_jarvis_agent

    agent = build_jarvis_agent(
        api_key="sk-test",
        goal="Build a Tetris HTML file with write_file",
    )
    assert agent is not None
    assert agent._model == cheap_catalog_ids(snapshot_leaders(), allow_free=False)[0]
    assert agent._model_reason
    assert agent._model_route.get("task_class") == "routine_build"


def test_router_selects_current_board_model(ws: Path):
    choice = route_model(
        goal="Create a playable tetris as one HTML file with write_file",
        workspace_root=ws,
    )
    assert choice.pinned is False
    assert choice.model in SNAPSHOT_MODEL_IDS
    assert choice.metadata["leaderboard_source"] == "snapshot"
    assert choice.metadata["ladder"][0] in SNAPSHOT_MODEL_IDS
    for mid in SNAPSHOT_MODEL_IDS:
        assert mid in choice.metadata["ladder"]


def test_unknown_stale_pin_still_works(ws: Path):
    stale = "openai/gpt-4.1-mini"
    assert stale not in SNAPSHOT_MODEL_IDS
    choice = route_model(
        goal="Build tetris HTML",
        explicit_model=stale,
        workspace_root=ws,
    )
    assert choice.pinned is True
    assert choice.model == stale
    assert "hard pin" in choice.reason


def test_live_fetch_failure_falls_back_to_snapshot_and_scorecard(
    ws: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "1")
    reset_leaders_cache_for_tests()

    def boom(url: str, headers: dict, timeout: float) -> dict:
        raise RuntimeError("simulated leaderboard outage")

    monkeypatch.setattr("app.jarvis.openrouter_leaders._http_get_json", boom)
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir()
    (bench_dir / "jarvis-index-latest.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "model": "openai/gpt-4.1-mini",
                        "ok": True,
                        "elapsed_sec": 10,
                        "cost_usd": 0.012,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    choice = route_model(
        goal="Create a playable tetris as one HTML file with write_file",
        workspace_root=ws,
        repo_root=tmp_path,
    )
    assert choice.pinned is False
    assert choice.model == "openai/gpt-4.1-mini"
    assert choice.metadata["leaderboard_source"] == "snapshot"
    assert "deepseek/deepseek-v4-flash-0731" in choice.metadata["ladder"]
    assert "openai/gpt-4.1-mini" in choice.metadata["ladder"]


def test_live_board_used_when_fetch_works(
    ws: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("JARVIS_LEADERBOARD_LIVE", "1")
    reset_leaders_cache_for_tests()

    def fake_get(url: str, headers: dict, timeout: float) -> dict:
        if "rankings-daily" in url:
            return {
                "data": [
                    {
                        "date": "2026-08-10",
                        "model_permaslug": "openai/gpt-5.6-luna",
                        "total_tokens": "100",
                    },
                    {
                        "date": "2026-08-10",
                        "model_permaslug": "deepseek/deepseek-v4-flash-20260731",
                        "total_tokens": "80",
                    },
                    {
                        "date": "2026-08-10",
                        "model_permaslug": "invented/not-a-real-model",
                        "total_tokens": "999",
                    },
                    {
                        "date": "2026-08-10",
                        "model_permaslug": "other",
                        "total_tokens": "1",
                    },
                ],
                "meta": {"as_of": "2026-08-14T00:00:00Z"},
            }
        if url.rstrip("/").endswith("/models"):
            return {
                "data": [
                    {
                        "id": "openai/gpt-5.6-luna",
                        "canonical_slug": "openai/gpt-5.6-luna-20260709",
                        "name": "OpenAI: GPT-5.6 Luna",
                        "pricing": {"prompt": "0.0000001", "completion": "0.0000006"},
                        "supported_parameters": ["tools"],
                    },
                    {
                        "id": "deepseek/deepseek-v4-flash-0731",
                        "canonical_slug": "deepseek/deepseek-v4-flash-20260731",
                        "name": "DeepSeek: DeepSeek V4 Flash 0731",
                        "pricing": {
                            "prompt": "0.00000014",
                            "completion": "0.00000028",
                        },
                        "supported_parameters": ["tools"],
                    },
                ]
            }
        raise AssertionError(url)

    monkeypatch.setattr("app.jarvis.openrouter_leaders._http_get_json", fake_get)
    choice = route_model(
        goal="Create a playable tetris as one HTML file with write_file",
        workspace_root=ws,
    )
    assert choice.pinned is False
    assert choice.metadata["leaderboard_source"] == "live"
    assert choice.model == "deepseek/deepseek-v4-flash-0731"
    assert "openai/gpt-5.6-luna" in choice.metadata["ladder"]
    assert "invented/not-a-real-model" not in choice.metadata["ladder"]
    assert "invented/not-a-real-model" not in choice.metadata["leaderboard_ids"]
    hard = route_model(
        goal="Refactor the multi-file codebase architecture carefully",
        workspace_root=ws,
    )
    assert hard.metadata["leaderboard_source"] == "live"
    assert hard.escalate is False
    assert hard.model == "openai/gpt-5.6-luna"
    assert hard.model != "deepseek/deepseek-v4-flash-0731"
    assert not hard.model.endswith(":free")
