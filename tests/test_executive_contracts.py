import json

import pytest

from app.executive.confidence import EvidenceItem, score_mission_confidence
from app.executive.handoff import HandoffValidationError, parse_handoff
from app.executive.scopes import normalize_memory_scope


def test_normalize_scopes_and_aliases():
    assert normalize_memory_scope("Team") == "team"
    assert normalize_memory_scope("agent") == "specialist"
    assert normalize_memory_scope("shared") == "shared"
    with pytest.raises(ValueError):
        normalize_memory_scope("galaxy")
    with pytest.raises(ValueError):
        normalize_memory_scope("")


def test_parse_handoff_happy_path_and_redaction():
    raw = {
        "from_role": "playwright-visual-reviewer",
        "to_role": "executive",
        "objective": "Verify landing page",
        "attempted_work": "Ran Playwright suite",
        "outcome": "3/3 passed",
        "confidence": 0.82,
        "evidence_refs": ["artifact:trace-1"],
        "changes": ["updated snapshot"],
        "costs": {"usd": 0.04, "model": "openrouter/auto"},
        "risks": [],
        "recommendation": "accept",
        "memory_updates": [
            {
                "scope": "team",
                "title": "ui",
                "body": "ok token=ghp_ABCDEFGHIJKLMNOPQRSTUV",
            }
        ],
        "open_questions": [],
    }
    pkt = parse_handoff(raw)
    assert pkt.from_role == "playwright-visual-reviewer"
    assert pkt.confidence == 0.82
    assert pkt.memory_updates[0].scope == "team"
    assert "ghp_" not in pkt.memory_updates[0].body
    assert "[REDACTED]" in pkt.memory_updates[0].body
    # round-trip JSON
    pkt2 = parse_handoff(pkt.to_json())
    assert pkt2.to_dict()["to_role"] == "executive"


def test_parse_handoff_rejects_prose_and_bad_confidence():
    with pytest.raises(HandoffValidationError):
        parse_handoff("we finished the work, trust me")
    with pytest.raises(HandoffValidationError):
        parse_handoff({"from_role": "a", "to_role": "b", "objective": "o",
                       "attempted_work": "w", "outcome": "x", "confidence": 1.5})
    with pytest.raises(HandoffValidationError):
        parse_handoff(
            {
                "from_role": "a",
                "to_role": "b",
                "objective": "o",
                "attempted_work": "w",
                "outcome": "x",
                "confidence": 0.5,
                "memory_updates": [{"scope": "nope", "body": "x"}],
            }
        )


def test_novel_role_names_allowed():
    pkt = parse_handoff(
        {
            "from_role": "cost-optimizer-v2",
            "to_role": "executive",
            "objective": "trim spend",
            "attempted_work": "reviewed routing",
            "outcome": "suggested cheaper model",
            "confidence": 0.4,
        }
    )
    assert pkt.from_role == "cost-optimizer-v2"


def test_confidence_weighted_and_risk_penalty():
    evidence = [
        EvidenceItem(kind="automated_test", weight=1.2, passed=True, summary="unit ok"),
        EvidenceItem(kind="ui_test", weight=1.3, passed=True, summary="e2e ok"),
        EvidenceItem(kind="requirement", weight=1.0, passed=False, summary="a11y gap"),
        EvidenceItem(kind="screenshot", weight=0.6, passed=None, summary="pending"),
    ]
    result = score_mission_confidence(
        evidence, target=80, unresolved_risks=["a11y contrast"]
    )
    assert 0 <= result.score <= 100
    assert result.score < 100  # failed requirement + risk
    assert result.reached is (result.score >= 80)
    assert "a11y contrast" in result.unresolved_risks
    pending = [c for c in result.components if c["passed"] is None]
    assert len(pending) == 1
    d = result.to_dict()
    assert d["score"] == result.score
    assert json.loads(json.dumps(d))["target"] == 80


def test_confidence_empty_evidence_is_zero():
    r = score_mission_confidence([], target=80)
    assert r.score == 0
    assert r.reached is False
