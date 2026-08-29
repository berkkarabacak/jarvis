from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from app.executive.confidence import (
    EvidenceItem,
    MissionConfidence,
    score_mission_confidence,
)
from app.executive.handoff import HandoffPacket, HandoffValidationError, parse_handoff
from app.executive.scopes import normalize_memory_scope
from app.executive.store import HandoffStore, InMemoryHandoffStore, StoredHandoff
from app.memory.sanitize import sanitize_text

SessionStatus = Literal["active", "paused", "completed", "failed", "stopped"]

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "active": frozenset({"paused", "completed", "failed", "stopped"}),
    "paused": frozenset({"active", "completed", "failed", "stopped"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "stopped": frozenset(),
}


class ExecutiveSessionError(RuntimeError):
    pass


@dataclass
class SpecialistRef:
    """Runtime specialist slot — free-text role, no fixed hierarchy."""

    instance_id: str
    role_name: str
    status: str = "active"
    parent_instance_id: str | None = None
    spawned_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "role_name": self.role_name,
            "status": self.status,
            "parent_instance_id": self.parent_instance_id,
            "spawned_at": self.spawned_at,
        }


@dataclass
class ExecutiveSession:
    """In-process executive session boundary (ORCH-71).

    Owns mission-scoped handoffs, evidence, specialists, and confidence.
    Deliberately dependency-light: no Prime Agent RPC, no LLM provider, no
    API keys. Control plane and Prime wiring attach later behind ports.
    """

    mission_id: str
    session_id: str
    brief: str = ""
    confidence_target: int = 80
    status: SessionStatus = "active"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    ended_reason: str | None = None
    handoff_store: HandoffStore = field(default_factory=InMemoryHandoffStore)
    evidence: list[EvidenceItem] = field(default_factory=list)
    unresolved_risks: list[str] = field(default_factory=list)
    specialists: dict[str, SpecialistRef] = field(default_factory=dict)
    # Scoped memory buffer: scope -> list of {title, body, from_role, handoff_id}
    scoped_memory: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    _closed: bool = field(default=False, repr=False)

    @classmethod
    def open(
        cls,
        *,
        mission_id: str,
        brief: str = "",
        confidence_target: int = 80,
        handoff_store: HandoffStore | None = None,
        session_id: str | None = None,
    ) -> ExecutiveSession:
        mid = sanitize_text((mission_id or "").strip(), max_chars=120)
        if not mid:
            raise ValueError("mission_id is required")
        if confidence_target < 0 or confidence_target > 100:
            raise ValueError("confidence_target must be 0–100")
        return cls(
            mission_id=mid,
            session_id=session_id or str(uuid.uuid4()),
            brief=sanitize_text(brief, max_chars=8000),
            confidence_target=int(confidence_target),
            handoff_store=handoff_store or InMemoryHandoffStore(),
        )

    def _touch(self) -> None:
        self.updated_at = time.time()

    def _require_open(self) -> None:
        if self._closed or self.status in ("completed", "failed", "stopped"):
            raise ExecutiveSessionError(
                f"session {self.session_id} is closed (status={self.status})"
            )

    def transition(self, new_status: SessionStatus, *, reason: str | None = None) -> None:
        allowed = _ALLOWED_TRANSITIONS.get(self.status, frozenset())
        if new_status == self.status:
            return
        if new_status not in allowed:
            raise ExecutiveSessionError(
                f"illegal session transition {self.status!r} -> {new_status!r}"
            )
        self.status = new_status
        self._touch()
        if new_status in ("completed", "failed", "stopped"):
            self._closed = True
            self.ended_at = time.time()
            self.ended_reason = sanitize_text(reason or new_status, max_chars=500) or new_status

    def spawn_specialist(
        self,
        role_name: str,
        *,
        parent_instance_id: str | None = None,
        instance_id: str | None = None,
    ) -> SpecialistRef:
        self._require_open()
        role = sanitize_text((role_name or "").strip(), max_chars=120)
        if not role:
            raise ValueError("role_name is required")
        # Free-text roles (ORCH-66) — charset guard only.
        if not all(ch.isalnum() or ch in ("-", "_", " ", ".", "/") for ch in role):
            raise ValueError("role_name has unsafe characters")
        if parent_instance_id and parent_instance_id not in self.specialists:
            raise ExecutiveSessionError(f"unknown parent specialist: {parent_instance_id}")
        ref = SpecialistRef(
            instance_id=instance_id or str(uuid.uuid4()),
            role_name=role,
            parent_instance_id=parent_instance_id,
        )
        self.specialists[ref.instance_id] = ref
        self._touch()
        return ref

    def stop_specialist(self, instance_id: str, *, status: str = "stopped") -> None:
        self._require_open()
        ref = self.specialists.get(instance_id)
        if ref is None:
            raise ExecutiveSessionError(f"unknown specialist: {instance_id}")
        ref.status = sanitize_text(status, max_chars=32) or "stopped"
        self._touch()

    async def record_handoff(
        self,
        packet: HandoffPacket | dict[str, Any] | str,
        *,
        memory_scope: str = "team",
    ) -> StoredHandoff:
        self._require_open()
        scope = normalize_memory_scope(memory_scope)
        row = await self.handoff_store.append(
            mission_id=self.mission_id,
            session_id=self.session_id,
            packet=packet,
            memory_scope=scope,
        )
        # Promote handoff confidence + risks into session evidence stream.
        pkt = row.packet
        self.evidence.append(
            EvidenceItem(
                kind="handoff",
                weight=0.5,
                passed=pkt.confidence >= 0.7,
                summary=sanitize_text(
                    f"{pkt.from_role}->{pkt.to_role}: {pkt.outcome}",
                    max_chars=500,
                ),
                artifact_id=row.id,
            )
        )
        for risk in pkt.risks:
            r = (risk or "").strip()
            if r and r not in self.unresolved_risks:
                self.unresolved_risks.append(r)
        # Apply structured memory_updates into scoped session buffer (not durable company DB).
        for mu in pkt.memory_updates:
            bucket = self.scoped_memory.setdefault(mu.scope, [])
            bucket.append(
                {
                    "title": mu.title,
                    "body": mu.body,
                    "from_role": pkt.from_role,
                    "handoff_id": row.id,
                    "memory_scope": mu.scope,
                }
            )
            # Cap per-scope buffer to keep sessions light.
            if len(bucket) > 100:
                del bucket[:-100]
        self._touch()
        return row

    def record_evidence(self, item: EvidenceItem) -> EvidenceItem:
        self._require_open()
        kind = sanitize_text((item.kind or "artifact").strip().lower(), max_chars=64) or "artifact"
        summary = sanitize_text(item.summary, max_chars=500)
        clean = EvidenceItem(
            kind=kind,
            weight=float(item.weight),
            passed=item.passed,
            summary=summary,
            artifact_id=item.artifact_id,
        )
        self.evidence.append(clean)
        self._touch()
        return clean

    def add_risk(self, risk: str) -> None:
        self._require_open()
        r = sanitize_text((risk or "").strip(), max_chars=500)
        if r and r not in self.unresolved_risks:
            self.unresolved_risks.append(r)
            self._touch()

    def resolve_risk(self, risk: str) -> None:
        r = (risk or "").strip()
        if r in self.unresolved_risks:
            self.unresolved_risks = [x for x in self.unresolved_risks if x != r]
            self._touch()

    def confidence(self) -> MissionConfidence:
        """Aggregate mission confidence from recorded evidence (incl. handoffs)."""
        return score_mission_confidence(
            list(self.evidence),
            target=self.confidence_target,
            unresolved_risks=list(self.unresolved_risks),
        )

    async def handoffs(
        self,
        *,
        memory_scope: str | None = None,
        limit: int = 200,
    ) -> list[StoredHandoff]:
        return await self.handoff_store.list_for_mission(
            self.mission_id,
            memory_scope=memory_scope,
            session_id=self.session_id,
            limit=limit,
        )

    def memory_for_scope(self, scope: str) -> list[dict[str, Any]]:
        key = normalize_memory_scope(scope)
        return list(self.scoped_memory.get(key) or [])

    def snapshot(self) -> dict[str, Any]:
        conf = self.confidence()
        mem_counts = {k: len(v) for k, v in self.scoped_memory.items()}
        return {
            "mission_id": self.mission_id,
            "session_id": self.session_id,
            "brief": self.brief,
            "status": self.status,
            "confidence_target": self.confidence_target,
            "confidence": conf.to_dict(),
            "evidence_count": len(self.evidence),
            "unresolved_risks": list(self.unresolved_risks),
            "specialists": [s.to_dict() for s in self.specialists.values()],
            "scoped_memory_counts": mem_counts,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "ended_at": self.ended_at,
            "ended_reason": self.ended_reason,
            # Explicit non-wiring markers for operators / tests
            "runtime": {
                "prime_agent": False,
                "llm_provider": None,
                "boundary": "executive_session_v1",
            },
        }


def handoff_from_specialist_outcome(
    *,
    from_role: str,
    to_role: str = "executive",
    objective: str,
    attempted_work: str,
    outcome: str,
    confidence: float,
    evidence_refs: list[str] | None = None,
    risks: list[str] | None = None,
    recommendation: str = "",
) -> HandoffPacket:
    """Helper to build a validated handoff without raw JSON assembly."""
    try:
        return parse_handoff(
            {
                "from_role": from_role,
                "to_role": to_role,
                "objective": objective,
                "attempted_work": attempted_work,
                "outcome": outcome,
                "confidence": confidence,
                "evidence_refs": evidence_refs or [],
                "risks": risks or [],
                "recommendation": recommendation,
            }
        )
    except HandoffValidationError:
        raise
