from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.executive.adapters.prime import PrimeMessageResult
from app.executive.safety import require_public_identifier, sanitize_public_text

CONTROL_PLANE_CONTRACT = "orch.control-plane.event"
CONTROL_PLANE_CONTRACT_VERSION = "1.0"

PublishableEventType = Literal["executive_message", "evidence", "confidence"]
TurnEvidenceSource = Literal["prime", "approved_memory"]


@dataclass(frozen=True)
class ControlPlaneEventRequest:
    """A publish request, not an ORCH-70 history/stream envelope.

    ORCH-70 remains responsible for authorization, persistence, IDs, cursors,
    timestamps, tenant ownership, and the final V1 envelope.
    """

    type: PublishableEventType
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "data": dict(self.data)}


def build_safe_turn_event_requests(
    *,
    mission_id: str,
    result: PrimeMessageResult,
    confidence_score: int,
    source: TurnEvidenceSource = "prime",
) -> dict[str, Any]:
    """Project one safe chat result to exact ORCH-70 V1 publish shapes."""

    public_mission_id = require_public_identifier(mission_id)
    public_message_id = require_public_identifier(result.message_id)
    score = max(0, min(100, int(confidence_score)))
    summary, filtered = sanitize_public_text(result.text)
    severity = "warning" if result.safety_filtered or filtered else "info"
    if source == "approved_memory":
        reference_id = f"memory-turn:{public_message_id}"
        evidence_label = "Approved memory saved locally"
    else:
        reference_id = f"prime-turn:{public_message_id}"
        evidence_label = "Prime executive RPC turn completed"
    events = [
        ControlPlaneEventRequest(
            type="executive_message",
            data={
                "summary": summary,
                "severity": severity,
                "action_required": severity == "warning",
            },
        ),
        ControlPlaneEventRequest(
            type="evidence",
            data={
                "evidence_id": public_message_id,
                "kind": "trace",
                "reference_id": reference_id,
                "label": evidence_label,
                # This verifies transport completion only, not mission correctness.
                "verification_status": "verified",
            },
        ),
        ControlPlaneEventRequest(
            type="confidence",
            data={
                "subject_type": "mission",
                "subject_id": public_mission_id,
                "score": score,
                "basis": ["status", "evidence"],
            },
        ),
    ]
    return {
        "target_contract": CONTROL_PLANE_CONTRACT,
        "target_contract_version": CONTROL_PLANE_CONTRACT_VERSION,
        "mission_id": public_mission_id,
        "events": [event.to_dict() for event in events],
        "authorization": "required_at_orch70_publish_adapter",
    }
