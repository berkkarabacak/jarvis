from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Mission lifecycle (deterministic control plane — ORCH-70)
MISSION_STATUSES = frozenset(
    {
        "draft",
        "queued",
        "running",
        "succeeded",
        "failed",
        "killed",
        "blocked",
    }
)
TERMINAL_MISSION_STATUSES = frozenset({"succeeded", "failed", "killed"})

# Budget ledger kinds (integer cents only)
LEDGER_KINDS = frozenset({"reserve", "commit", "release", "refund"})

# Worker boundary lifecycle (logical isolation stub until real sandbox)
WORKER_STATUSES = frozenset({"pending", "active", "tearing_down", "terminated"})

# Allowed mission transitions (from -> to)
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"queued", "killed"}),
    "queued": frozenset({"running", "blocked", "killed", "failed"}),
    "running": frozenset({"succeeded", "failed", "killed", "blocked"}),
    "blocked": frozenset({"queued", "running", "killed", "failed"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "killed": frozenset(),
}


@dataclass(frozen=True)
class Mission:
    id: str
    org_id: str
    title: str
    brief: str
    status: str
    budget_limit_cents: int
    spend_cents: int
    reserved_cents: int
    deadline_at: float | None
    ended_reason: str | None
    worker_id: str | None
    created_at: float
    updated_at: float
    started_at: float | None = None
    ended_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "org_id": self.org_id,
            "title": self.title,
            "brief": self.brief,
            "status": self.status,
            "budget_limit_cents": self.budget_limit_cents,
            "spend_cents": self.spend_cents,
            "reserved_cents": self.reserved_cents,
            "available_cents": max(
                0, self.budget_limit_cents - self.spend_cents - self.reserved_cents
            ),
            "deadline_at": self.deadline_at,
            "ended_reason": self.ended_reason,
            "worker_id": self.worker_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "terminal": self.status in TERMINAL_MISSION_STATUSES,
        }


@dataclass(frozen=True)
class BudgetDenial:
    """Hard deny — agents cannot bypass."""

    reason: str
    requested_cents: int
    available_cents: int
    limit_cents: int
    spend_cents: int
    reserved_cents: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "denied": True,
            "reason": self.reason,
            "requested_cents": self.requested_cents,
            "available_cents": self.available_cents,
            "limit_cents": self.limit_cents,
            "spend_cents": self.spend_cents,
            "reserved_cents": self.reserved_cents,
        }


@dataclass(frozen=True)
class LedgerEntry:
    id: str
    mission_id: str
    kind: str
    amount_cents: int
    note: str
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "mission_id": self.mission_id,
            "kind": self.kind,
            "amount_cents": self.amount_cents,
            "note": self.note,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class AuditEvent:
    id: str
    mission_id: str | None
    event_type: str
    actor: str
    detail: dict[str, Any]
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "mission_id": self.mission_id,
            "event_type": self.event_type,
            "actor": self.actor,
            "detail": dict(self.detail or {}),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class WorkerBoundary:
    """Isolation boundary record — not a security sandbox by itself."""

    id: str
    mission_id: str
    status: str
    isolation_mode: str  # logical | container | microvm (logical only in this slice)
    host_hint: str
    created_at: float
    updated_at: float
    terminated_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "mission_id": self.mission_id,
            "status": self.status,
            "isolation_mode": self.isolation_mode,
            "host_hint": self.host_hint,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "terminated_at": self.terminated_at,
            "metadata": dict(self.metadata or {}),
            "note": (
                "Worker boundary is control-plane owned. Agents cannot widen "
                "isolation or keep workers after mission end."
            ),
        }


class ControlPlaneError(Exception):
    def __init__(self, message: str, *, code: str = "control_plane_error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.code, "detail": self.message}


class TransitionError(ControlPlaneError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="invalid_transition")


class BudgetError(ControlPlaneError):
    def __init__(self, message: str, denial: BudgetDenial | None = None) -> None:
        super().__init__(message, code="budget_denied")
        self.denial = denial

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        if self.denial:
            base["denial"] = self.denial.to_dict()
        return base
