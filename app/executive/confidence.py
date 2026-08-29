from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceItem:
    """One auditable evidence contribution toward mission confidence (0–100)."""

    kind: str
    weight: float
    passed: bool | None = None
    summary: str = ""
    artifact_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "weight": self.weight,
            "passed": self.passed,
            "summary": self.summary,
            "artifact_id": self.artifact_id,
        }


@dataclass
class MissionConfidence:
    score: int  # 0–100 inclusive
    target: int
    reached: bool
    explanation: str
    components: list[dict[str, Any]] = field(default_factory=list)
    unresolved_risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "target": self.target,
            "reached": self.reached,
            "explanation": self.explanation,
            "components": list(self.components),
            "unresolved_risks": list(self.unresolved_risks),
        }


_DEFAULT_WEIGHTS = {
    "requirement": 1.0,
    "automated_test": 1.2,
    "ui_test": 1.3,
    "screenshot": 0.6,
    "visual_review": 0.9,
    "independent_review": 1.1,
    "artifact": 0.8,
    "handoff": 0.5,
}


def _clamp_weight(w: float) -> float:
    if w < 0:
        return 0.0
    if w > 5:
        return 5.0
    return float(w)


def score_mission_confidence(
    evidence: list[EvidenceItem],
    *,
    target: int = 80,
    unresolved_risks: list[str] | None = None,
    risk_penalty_per_item: float = 4.0,
    max_risk_penalty: float = 30.0,
) -> MissionConfidence:
    """Evidence-backed mission confidence.

    - Only items with passed is True/False contribute to the weighted score.
    - passed=None is ignored in the average (recorded as pending).
    - Unresolved risks apply a bounded penalty after the weighted average.
    - Result is integer 0–100; reached <=> score >= target.
    """
    if target < 0 or target > 100:
        raise ValueError("target must be 0–100")

    risks = [r.strip() for r in (unresolved_risks or []) if (r or "").strip()]
    components: list[dict[str, Any]] = []
    weighted_sum = 0.0
    weight_total = 0.0

    for item in evidence:
        kind = (item.kind or "artifact").strip().lower() or "artifact"
        base = item.weight if item.weight is not None else _DEFAULT_WEIGHTS.get(kind, 1.0)
        w = _clamp_weight(float(base))
        entry = {
            "kind": kind,
            "weight": w,
            "passed": item.passed,
            "summary": (item.summary or "")[:500],
            "contribution": None,
        }
        if item.passed is True:
            weighted_sum += 100.0 * w
            weight_total += w
            entry["contribution"] = 100.0
        elif item.passed is False:
            weighted_sum += 0.0
            weight_total += w
            entry["contribution"] = 0.0
        else:
            entry["contribution"] = None  # pending — excluded
        components.append(entry)

    if weight_total <= 0:
        raw = 0.0
        basis = "no passed/failed evidence yet"
    else:
        raw = weighted_sum / weight_total
        basis = f"weighted average over {weight_total:.2f} evidence weight"

    penalty = min(max_risk_penalty, risk_penalty_per_item * len(risks))
    score_f = max(0.0, min(100.0, raw - penalty))
    score = int(round(score_f))

    parts = [f"score={score}/100 ({basis})"]
    if penalty:
        parts.append(f"risk penalty=-{penalty:.1f} ({len(risks)} unresolved)")
    parts.append(f"target={target}")
    explanation = "; ".join(parts)

    return MissionConfidence(
        score=score,
        target=int(target),
        reached=score >= int(target),
        explanation=explanation,
        components=components,
        unresolved_risks=risks,
    )
