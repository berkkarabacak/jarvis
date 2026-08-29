"""ORCH-331: Jarvis scorecard math (no live LLM)."""

from __future__ import annotations

import pytest

from app.jarvis.cost_index import (
    TIME_PENALTY_USD_PER_SEC,
    aggregate_model_index,
    fold_attempt_rows,
    index_payload,
    normalize_reported_cost,
    order_models_from_index,
    preferred_cheap_from_index,
    score_suite,
    score_task,
    seed_in_text,
    unique_artifact_rel,
)


def test_time_penalty_is_small():
    assert TIME_PENALTY_USD_PER_SEC == 0.0001


def test_unique_artifact_includes_model_task_seed():
    rel = unique_artifact_rel(
        task="tetris-html",
        model="openai/gpt-4.1-mini",
        run_id="20260813T000000Z-abc123",
        suffix=".html",
    )
    assert rel.startswith("Exports/bench-tetris-html-")
    assert "openai__gpt-4.1-mini" in rel
    assert "20260813T000000Z-abc123" in rel
    assert rel.endswith(".html")


def test_unique_artifact_kind_inserts_label():
    stub = unique_artifact_rel(
        task="two-file-split",
        model="openai/gpt-4.1-mini",
        run_id="20260813T000000Z-abc123",
        suffix=".py",
        kind="stub",
    )
    readme = unique_artifact_rel(
        task="two-file-split",
        model="openai/gpt-4.1-mini",
        run_id="20260813T000000Z-abc123",
        suffix=".md",
        kind="readme",
    )
    assert stub.startswith("Exports/bench-two-file-split-stub-")
    assert readme.startswith("Exports/bench-two-file-split-readme-")
    assert stub.endswith(".py")
    assert readme.endswith(".md")
    assert "20260813T000000Z-abc123" in stub
    assert "20260813T000000Z-abc123" in readme
    assert stub != readme


def test_seed_in_text():
    assert seed_in_text("<!-- bench-seed: abc -->", "abc") is True
    assert seed_in_text("nope", "abc") is False
    assert seed_in_text("abc", "") is False


def test_reported_zero_is_cost_unknown_not_free():
    n = normalize_reported_cost(0)
    assert n.cost_unknown is True
    assert n.cost_usd is None
    assert n.cost_source == "cost_unknown"


def test_missing_cost_is_unknown():
    n = normalize_reported_cost(None)
    assert n.cost_unknown is True
    assert n.cost_usd is None


def test_positive_cost_is_known():
    n = normalize_reported_cost(0.0065, source="openrouter")
    assert n.cost_unknown is False
    assert n.cost_usd == 0.0065
    assert n.cost_source == "openrouter"


def test_failure_scores_zero_but_keeps_spend():
    scored = score_task({"ok": False, "elapsed_sec": 12, "cost_usd": 0.01, "escalate": False})
    assert scored["ok"] == 0
    assert scored["cost_usd"] == 0.01
    assert scored["cost_unknown"] is False
    assert scored["seconds"] == 12


def test_success_counts_one():
    scored = score_task({"ok": True, "elapsed_sec": 8, "cost_usd": 0.006, "escalate": True})
    assert scored["ok"] == 1
    assert scored["escalate"] == 1


def test_headline_two_successes():
    row = aggregate_model_index(
        "openai/gpt-4.1-mini",
        [
            {"ok": True, "elapsed_sec": 10, "cost_usd": 0.006},
            {"ok": True, "elapsed_sec": 10, "cost_usd": 0.006},
        ],
    )
    assert row.rankable is True
    assert row.ok == 2
    assert row.n == 2
    assert row.pass_at_1 == pytest.approx(1.0)
    assert row.usd_per_success == pytest.approx(0.006)
    assert row.escalate_pct == pytest.approx(0.0)
    assert row.cost_usd == 0.012
    assert row.ours_composite == pytest.approx(2 / 0.014)


def test_headlines_match_docs_worked_example():
    mini = aggregate_model_index(
        "openai/gpt-4.1-mini",
        [
            {"ok": True, "elapsed_sec": 10, "cost_usd": 0.006},
            {"ok": True, "elapsed_sec": 10, "cost_usd": 0.006},
        ],
    )
    full = aggregate_model_index(
        "openai/gpt-4.1",
        [
            {"ok": True, "elapsed_sec": 9, "cost_usd": 0.024},
            {"ok": True, "elapsed_sec": 9, "cost_usd": 0.024},
        ],
    )
    assert mini.pass_at_1 == pytest.approx(1.0)
    assert mini.usd_per_success == pytest.approx(0.012 / 2)
    assert full.usd_per_success == pytest.approx(0.048 / 2)
    assert mini.usd_per_success < full.usd_per_success
    assert mini.ours_composite == pytest.approx(2 / (0.012 + 0.0001 * 20))
    assert full.ours_composite == pytest.approx(2 / (0.048 + 0.0001 * 18))


def test_failures_stay_in_dollar_denominator():
    mixed = aggregate_model_index(
        "openai/gpt-4.1-mini",
        [
            {"ok": True, "elapsed_sec": 10, "cost_usd": 0.006},
            {"ok": False, "elapsed_sec": 20, "cost_usd": 0.010},
        ],
    )
    assert mixed.ok == 1
    assert mixed.pass_at_1 == pytest.approx(0.5)
    assert mixed.cost_usd == pytest.approx(0.016)
    assert mixed.usd_per_success == pytest.approx(0.016)  # not 0.006
    assert mixed.ours_composite == pytest.approx(1 / (0.016 + 0.0001 * 30))


def test_zero_successes_has_no_usd_per_success():
    row = aggregate_model_index(
        "x",
        [{"ok": False, "elapsed_sec": 5, "cost_usd": 0.01}],
    )
    assert row.pass_at_1 == pytest.approx(0.0)
    assert row.usd_per_success is None
    assert row.cost_usd == pytest.approx(0.01)


def test_escalate_pct():
    row = aggregate_model_index(
        "x",
        [
            {"ok": True, "elapsed_sec": 1, "cost_usd": 0.01, "escalate": False},
            {"ok": True, "elapsed_sec": 1, "cost_usd": 0.01, "escalate": True},
        ],
    )
    assert row.escalate == 1
    assert row.escalate_pct == pytest.approx(50.0)


def test_unknown_cost_is_not_rankable():
    row = aggregate_model_index(
        "google/gemini-2.5-flash",
        [
            {"ok": True, "elapsed_sec": 10, "cost_usd": 0.0},
            {"ok": True, "elapsed_sec": 9, "cost_usd": 0.0},
        ],
    )
    assert row.cost_unknown is True
    assert row.rankable is False
    assert row.usd_per_success is None
    assert row.ours_composite is None
    assert row.pass_at_1 == pytest.approx(1.0)


def test_explicit_cost_unknown_flag():
    row = aggregate_model_index(
        "x",
        [{"ok": True, "elapsed_sec": 5, "cost_usd": 0.01, "cost_unknown": True}],
    )
    assert row.rankable is False
    assert row.usd_per_success is None


def test_score_suite_orders_by_usd_per_success():
    rows = score_suite(
        [
            {"model": "openai/gpt-4.1", "ok": True, "elapsed_sec": 18, "cost_usd": 0.048},
            {"model": "openai/gpt-4.1-mini", "ok": True, "elapsed_sec": 20, "cost_usd": 0.012},
            {"model": "google/gemini-2.5-flash", "ok": True, "elapsed_sec": 8, "cost_usd": 0.0},
        ]
    )
    assert rows[0].model == "openai/gpt-4.1-mini"
    assert rows[-1].model == "google/gemini-2.5-flash"
    assert rows[-1].rankable is False


def test_preferred_cheap_skips_unknown_and_picks_lowest_usd_per_success():
    payload = index_payload(
        results=[
            {"model": "openai/gpt-4.1", "ok": True, "elapsed_sec": 18, "cost_usd": 0.048},
            {"model": "openai/gpt-4.1-mini", "ok": True, "elapsed_sec": 20, "cost_usd": 0.012},
            {"model": "google/gemini-2.5-flash", "ok": True, "elapsed_sec": 8, "cost_usd": 0.0},
        ],
        run_id="test",
        created_at=0.0,
    )
    assert payload["headline_metrics"] == ["pass_at_1", "usd_per_success", "escalate_pct"]
    assert "Artificial Analysis" in payload["note"]
    assert "Quality" in payload["note"]
    assert preferred_cheap_from_index(payload) == "openai/gpt-4.1-mini"


def test_preferred_cheap_ignores_all_fail():
    payload = index_payload(
        results=[{"model": "openai/gpt-4.1-mini", "ok": False, "elapsed_sec": 5, "cost_usd": 0.01}],
        run_id="test",
        created_at=0.0,
    )
    assert preferred_cheap_from_index(payload) is None


def test_payload_does_not_claim_aa_quality_over_price():
    payload = index_payload(results=[], run_id="s", created_at=0.0)
    note = payload["note"].lower()
    assert "does not officially rank" in note
    assert "quality" in note
    assert payload["index_version"] == 3


def test_one_unknown_cost_row_does_not_wipe_model_usd():
    """Live 2026-08-13 shape: organize unknown must not blank $ per success."""
    row = aggregate_model_index(
        "openai/gpt-4.1-mini",
        [
            {"ok": True, "elapsed_sec": 10, "cost_usd": 0.006},
            {"ok": True, "elapsed_sec": 8, "cost_usd": 0.007},
            {"ok": False, "elapsed_sec": 5, "cost_usd": None, "cost_unknown": True},
        ],
    )
    assert row.pass_at_1 == pytest.approx(2 / 3)
    assert row.cost_unknown is False
    assert row.known_n == 2
    assert row.cost_usd == pytest.approx(0.013)
    assert row.usd_per_success == pytest.approx(0.013 / 2)
    assert row.rankable is True
    assert row.ours_composite == pytest.approx(2 / (0.013 + 0.0001 * 18))


def test_known_cost_failures_still_sit_in_dollar_sum():
    row = aggregate_model_index(
        "x",
        [
            {"ok": True, "elapsed_sec": 10, "cost_usd": 0.006},
            {"ok": False, "elapsed_sec": 20, "cost_usd": 0.010},
            {"ok": False, "elapsed_sec": 3, "cost_usd": None, "cost_unknown": True},
        ],
    )
    assert row.pass_at_1 == pytest.approx(1 / 3)
    assert row.usd_per_success == pytest.approx(0.016)  # known fail stays in $
    assert row.cost_unknown is False
    assert row.known_n == 2


def test_all_unknown_costs_stay_cost_unknown():
    row = aggregate_model_index(
        "google/gemini-2.5-flash",
        [
            {"ok": True, "elapsed_sec": 4, "cost_usd": 0.0},
            {"ok": False, "elapsed_sec": 4, "cost_usd": None},
        ],
    )
    assert row.cost_unknown is True
    assert row.usd_per_success is None
    assert row.rankable is False
    assert row.known_n == 0


def test_preferred_cheap_requires_pass_at_least_current():
    payload = index_payload(
        results=[
            {"model": "openai/gpt-4.1-mini", "ok": True, "elapsed_sec": 10, "cost_usd": 0.05},
            {"model": "openai/gpt-4.1-mini", "ok": True, "elapsed_sec": 10, "cost_usd": 0.05},
            {"model": "openai/gpt-4.1", "ok": True, "elapsed_sec": 10, "cost_usd": 0.01},
            {"model": "openai/gpt-4.1", "ok": False, "elapsed_sec": 10, "cost_usd": 0.01},
        ],
        run_id="t",
        created_at=0.0,
    )
    # mini pass@1=1.0; full=0.5 and cheaper. Must not drop quality below current cheap.
    assert preferred_cheap_from_index(payload, current_cheap="openai/gpt-4.1-mini") == "openai/gpt-4.1-mini"


def test_preferred_cheap_picks_lowest_usd_at_same_pass():
    payload = index_payload(
        results=[
            {"model": "openai/gpt-4.1-mini", "ok": True, "elapsed_sec": 10, "cost_usd": 0.02},
            {"model": "openai/gpt-4.1-mini", "ok": False, "elapsed_sec": 10, "cost_usd": 0.02},
            {"model": "openai/gpt-4.1", "ok": True, "elapsed_sec": 10, "cost_usd": 0.08},
            {"model": "openai/gpt-4.1", "ok": False, "elapsed_sec": 10, "cost_usd": 0.08},
        ],
        run_id="t",
        created_at=0.0,
    )
    assert preferred_cheap_from_index(payload, current_cheap="openai/gpt-4.1-mini") == "openai/gpt-4.1-mini"


def test_preferred_cheap_fallback_best_pass_then_cheapest():
    payload = index_payload(
        results=[
            {"model": "openai/gpt-4.1-mini", "ok": True, "elapsed_sec": 10, "cost_usd": 0.01},
            {"model": "openai/gpt-4.1-mini", "ok": False, "elapsed_sec": 10, "cost_usd": 0.01},
            {"model": "openai/gpt-4.1", "ok": True, "elapsed_sec": 10, "cost_usd": 0.04},
            {"model": "openai/gpt-4.1", "ok": True, "elapsed_sec": 10, "cost_usd": 0.04},
        ],
        run_id="t",
        created_at=0.0,
    )
    # current cheap not in scorecard → best pass@1 (full 1.0) then cheapest
    assert preferred_cheap_from_index(payload, current_cheap="anthropic/claude-sonnet-4") == "openai/gpt-4.1"


def test_order_models_threshold_then_pass_then_price():
    payload = index_payload(
        results=[
            {"model": "openai/gpt-4.1-mini", "ok": True, "elapsed_sec": 10, "cost_usd": 0.02},
            {"model": "openai/gpt-4.1-mini", "ok": True, "elapsed_sec": 10, "cost_usd": 0.02},
            {"model": "openai/gpt-4.1", "ok": True, "elapsed_sec": 10, "cost_usd": 0.08},
            {"model": "openai/gpt-4.1", "ok": True, "elapsed_sec": 10, "cost_usd": 0.08},
            {"model": "anthropic/claude-sonnet-4", "ok": True, "elapsed_sec": 10, "cost_usd": 0.20},
            {"model": "anthropic/claude-sonnet-4", "ok": False, "elapsed_sec": 10, "cost_usd": 0.20},
        ],
        run_id="t",
        created_at=0.0,
    )
    ordered = order_models_from_index(payload, current_cheap="openai/gpt-4.1-mini")
    assert ordered[0] == "openai/gpt-4.1-mini"
    assert ordered[1] == "openai/gpt-4.1"
    assert "anthropic/claude-sonnet-4" in ordered


def test_fail_then_escalate_bills_both_attempts():
    folded = fold_attempt_rows(
        [
            {
                "model": "openai/gpt-4.1-mini",
                "ok": False,
                "elapsed_sec": 8,
                "cost_usd": 0.006,
                "escalate": False,
            },
            {
                "model": "openai/gpt-4.1",
                "ok": True,
                "elapsed_sec": 10,
                "cost_usd": 0.024,
                "escalate": True,
            },
        ],
        model="openai/gpt-4.1-mini",
        task="fail-then-escalate",
    )
    assert folded["ok"] is True
    assert folded["escalate"] is True
    assert folded["cost_usd"] == pytest.approx(0.030)
    assert folded["cost_unknown"] is False
    assert folded["attempt_count"] == 2
    assert len(folded["attempts"]) == 2
    assert folded["attempts"][0]["ok"] is False
    assert folded["attempts"][1]["ok"] is True
    assert folded["escalated_to"] == "openai/gpt-4.1"
    scored = score_task(folded)
    assert scored["ok"] == 1
    assert scored["cost_usd"] == pytest.approx(0.030)
    assert scored["escalate"] == 1
    row = aggregate_model_index("openai/gpt-4.1-mini", [folded])
    assert row.usd_per_success == pytest.approx(0.030)
    assert row.escalate_pct == pytest.approx(100.0)
    assert row.pass_at_1 == pytest.approx(1.0)


def test_fail_then_escalate_does_not_hide_retries_in_payload():
    folded = fold_attempt_rows(
        [
            {"ok": False, "elapsed_sec": 5, "cost_usd": 0.006, "model": "mini"},
            {"ok": True, "elapsed_sec": 7, "cost_usd": 0.024, "model": "full"},
        ],
        model="mini",
        task="fail-then-escalate",
    )
    payload = index_payload(results=[folded], run_id="s", created_at=0.0)
    stored = payload["results"][0]
    assert stored["attempts"][0]["cost_usd"] == 0.006
    assert stored["attempts"][1]["cost_usd"] == 0.024
    assert stored["cost_usd"] == pytest.approx(0.030)


def test_fold_attempt_rows_keeps_org_shape():
    folded = fold_attempt_rows(
        [
            {
                "ok": True,
                "elapsed_sec": 4,
                "cost_usd": 0.006,
                "model": "mini",
                "escalate": False,
                "parent_cost_usd": 0.006,
                "child_cost_usd": 0.0,
                "who_did_what": "solo parent wrote both",
                "depth": 0,
                "agent_count": 1,
                "models_used": ["mini"],
            }
        ],
        model="mini",
        task="cheap-math-1",
    )
    assert folded["depth"] == 0
    assert folded["agent_count"] == 1
    assert folded["parent_cost_usd"] == 0.006
    assert folded["child_cost_usd"] == 0.0
    assert folded["who_did_what"] == "solo parent wrote both"


def test_cheap_success_does_not_force_escalate():
    folded = fold_attempt_rows(
        [{"ok": True, "elapsed_sec": 4, "cost_usd": 0.006, "model": "mini", "escalate": False}],
        model="mini",
        task="fail-then-escalate",
    )
    assert folded["ok"] is True
    assert folded["escalate"] is False
    assert folded["cost_usd"] == pytest.approx(0.006)
    assert folded["attempt_count"] == 1
    assert folded["escalated_to"] is None


def test_escalate_unknown_cheap_cost_is_not_free():
    folded = fold_attempt_rows(
        [
            {"ok": False, "elapsed_sec": 5, "cost_usd": 0.0, "model": "flash"},
            {"ok": True, "elapsed_sec": 7, "cost_usd": 0.024, "model": "full"},
        ],
        model="flash",
        task="fail-then-escalate",
    )
    assert folded["cost_unknown"] is True
    assert folded["cost_usd"] is None
    assert folded["escalate"] is True
    assert len(folded["attempts"]) == 2
