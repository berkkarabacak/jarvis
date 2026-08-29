from __future__ import annotations

import time
from typing import Any

from app.control_plane.events import ControlPlaneEvents
from app.control_plane.models import (
    ALLOWED_TRANSITIONS,
    TERMINAL_MISSION_STATUSES,
    BudgetDenial,
    BudgetError,
    ControlPlaneError,
    Mission,
    TransitionError,
    WorkerBoundary,
)
from app.control_plane.store import ControlPlaneStore
from app.db import Database


class ControlPlaneService:
    """Deterministic mission control plane (ORCH-70).

    Enforces lifecycle, hard budgets, audit, and worker boundaries.
    Does not run LLM jobs or hold provider credentials.
    """

    def __init__(self, store: ControlPlaneStore) -> None:
        self.store = store
        self.events = ControlPlaneEvents(store)

    async def ensure_ready(self) -> None:
        await self.store.ensure_schema()

    # --- missions ---

    async def create_mission(
        self,
        *,
        title: str,
        brief: str = "",
        org_id: str = "default",
        budget_limit_cents: int = 0,
        deadline_at: float | None = None,
        actor: str = "api",
    ) -> Mission:
        title = (title or "").strip()
        if not title:
            raise ControlPlaneError("title is required", code="validation_error")
        if int(budget_limit_cents) < 0:
            raise ControlPlaneError("budget_limit_cents must be >= 0", code="validation_error")
        mission = await self.store.create_mission(
            title=title,
            brief=brief or "",
            org_id=org_id or "default",
            budget_limit_cents=int(budget_limit_cents),
            deadline_at=deadline_at,
        )
        await self.store.append_audit(
            event_type="mission.created",
            actor=actor,
            mission_id=mission.id,
            detail={
                "title": mission.title,
                "budget_limit_cents": mission.budget_limit_cents,
                "org_id": mission.org_id,
            },
        )
        return mission

    async def get_mission(self, mission_id: str) -> Mission | None:
        return await self.store.get_mission(mission_id)

    async def list_missions(
        self, *, org_id: str | None = None, limit: int = 50
    ) -> list[Mission]:
        return await self.store.list_missions(org_id=org_id, limit=limit)

    def _assert_transition(self, current: str, target: str) -> None:
        allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
        if target not in allowed:
            raise TransitionError(
                f"Cannot transition mission from {current!r} to {target!r}"
            )

    async def queue_mission(self, mission_id: str, *, actor: str = "api") -> Mission:
        mission = await self._require(mission_id)
        previous_status = mission.status
        self._assert_transition(mission.status, "queued")
        mission = await self.store.update_mission_fields(mission_id, status="queued")
        await self.store.append_audit(
            event_type="mission.queued",
            actor=actor,
            mission_id=mission_id,
            detail={"from": previous_status, "to": "queued"},
        )
        return mission

    async def start_mission(self, mission_id: str, *, actor: str = "api") -> Mission:
        """Start mission: allocate worker boundary, move to running."""
        mission = await self._require(mission_id)
        if mission.status == "draft":
            mission = await self.queue_mission(mission_id, actor=actor)
        self._assert_transition(mission.status, "running")

        # Deadline hard check before start
        if mission.deadline_at is not None and time.time() > float(mission.deadline_at):
            await self.store.append_audit(
                event_type="mission.deadline_blocked",
                actor=actor,
                mission_id=mission_id,
                detail={"deadline_at": mission.deadline_at},
            )
            mission = await self.store.update_mission_fields(
                mission_id,
                status="failed",
                ended_reason="deadline_exceeded",
                ended_at=time.time(),
            )
            raise ControlPlaneError(
                "Mission deadline already exceeded", code="deadline_exceeded"
            )

        worker = await self.store.create_worker(
            mission_id=mission_id,
            isolation_mode="logical",
            host_hint="local-logical",
            metadata={"boundary": "control_plane_owned", "no_host_credentials": True},
        )
        worker = await self.store.update_worker(worker.id, status="active")
        mission = await self.store.update_mission_fields(
            mission_id,
            status="running",
            worker_id=worker.id,
            started_at=time.time(),
        )
        await self.store.append_audit(
            event_type="mission.started",
            actor=actor,
            mission_id=mission_id,
            detail={"worker_id": worker.id, "isolation_mode": worker.isolation_mode},
        )
        await self.store.append_audit(
            event_type="worker.activated",
            actor=actor,
            mission_id=mission_id,
            detail={"worker_id": worker.id, "status": worker.status},
        )
        return mission

    async def complete_mission(
        self,
        mission_id: str,
        *,
        actor: str = "api",
        commit_cents: int = 0,
        note: str = "",
    ) -> Mission:
        mission = await self._require(mission_id)
        self._assert_transition(mission.status, "succeeded")
        if commit_cents:
            await self.commit_budget(
                mission_id, amount_cents=commit_cents, actor=actor, note=note or "complete"
            )
        # Release any leftover reservation
        mission = await self._require(mission_id)
        if mission.reserved_cents > 0:
            await self.release_budget(
                mission_id,
                amount_cents=mission.reserved_cents,
                actor=actor,
                note="release_on_success",
            )
        await self._teardown_worker(mission_id, actor=actor, reason="mission_succeeded")
        mission = await self.store.update_mission_fields(
            mission_id,
            status="succeeded",
            ended_reason="completed",
            ended_at=time.time(),
            worker_id=None,
        )
        await self.store.append_audit(
            event_type="mission.succeeded",
            actor=actor,
            mission_id=mission_id,
            detail={"commit_cents": int(commit_cents or 0)},
        )
        return mission

    async def fail_mission(
        self,
        mission_id: str,
        *,
        actor: str = "api",
        reason: str = "failed",
        release_reservation: bool = True,
    ) -> Mission:
        mission = await self._require(mission_id)
        if mission.status in TERMINAL_MISSION_STATUSES:
            raise TransitionError(f"Mission already terminal: {mission.status}")
        self._assert_transition(mission.status, "failed")
        if release_reservation and mission.reserved_cents > 0:
            await self.release_budget(
                mission_id,
                amount_cents=mission.reserved_cents,
                actor=actor,
                note="release_on_fail",
            )
        await self._teardown_worker(mission_id, actor=actor, reason=reason or "failed")
        mission = await self.store.update_mission_fields(
            mission_id,
            status="failed",
            ended_reason=(reason or "failed")[:500],
            ended_at=time.time(),
            worker_id=None,
        )
        await self.store.append_audit(
            event_type="mission.failed",
            actor=actor,
            mission_id=mission_id,
            detail={"reason": reason or "failed"},
        )
        return mission

    async def kill_mission(
        self,
        mission_id: str,
        *,
        actor: str = "api",
        reason: str = "killed",
    ) -> Mission:
        """Hard stop — agents cannot prevent this."""
        mission = await self._require(mission_id)
        if mission.status in TERMINAL_MISSION_STATUSES:
            return mission
        # kill allowed from non-terminal only
        if "killed" not in ALLOWED_TRANSITIONS.get(mission.status, frozenset()):
            raise TransitionError(f"Cannot kill mission in status {mission.status!r}")
        if mission.reserved_cents > 0:
            await self.release_budget(
                mission_id,
                amount_cents=mission.reserved_cents,
                actor=actor,
                note="release_on_kill",
            )
        await self._teardown_worker(mission_id, actor=actor, reason=reason or "killed")
        mission = await self.store.update_mission_fields(
            mission_id,
            status="killed",
            ended_reason=(reason or "killed")[:500],
            ended_at=time.time(),
            worker_id=None,
        )
        await self.store.append_audit(
            event_type="mission.killed",
            actor=actor,
            mission_id=mission_id,
            detail={"reason": reason or "killed"},
        )
        return mission

    # --- budget (hard checks) ---

    async def reserve_budget(
        self,
        mission_id: str,
        *,
        amount_cents: int,
        actor: str = "api",
        note: str = "",
    ) -> Mission:
        """Reserve estimated cost before dispatch. Hard deny if insufficient."""
        amount = int(amount_cents)
        if amount <= 0:
            raise ControlPlaneError("amount_cents must be > 0", code="validation_error")
        mission = await self._require(mission_id)
        if mission.status in TERMINAL_MISSION_STATUSES:
            raise BudgetError("Cannot reserve on terminal mission")
        available = mission.budget_limit_cents - mission.spend_cents - mission.reserved_cents
        if amount > available:
            denial = BudgetDenial(
                reason="insufficient_budget",
                requested_cents=amount,
                available_cents=max(0, available),
                limit_cents=mission.budget_limit_cents,
                spend_cents=mission.spend_cents,
                reserved_cents=mission.reserved_cents,
            )
            await self.store.append_audit(
                event_type="budget.denied",
                actor=actor,
                mission_id=mission_id,
                detail=denial.to_dict(),
            )
            raise BudgetError("Budget reservation denied", denial=denial)

        await self.store.add_ledger_entry(
            mission_id=mission_id,
            kind="reserve",
            amount_cents=amount,
            note=note or "reserve",
        )
        mission = await self.store.update_mission_fields(
            mission_id, reserved_cents=mission.reserved_cents + amount
        )
        await self.store.append_audit(
            event_type="budget.reserved",
            actor=actor,
            mission_id=mission_id,
            detail={"amount_cents": amount, "reserved_cents": mission.reserved_cents},
        )
        return mission

    async def commit_budget(
        self,
        mission_id: str,
        *,
        amount_cents: int,
        actor: str = "api",
        note: str = "",
    ) -> Mission:
        """Commit actual spend against reservation (or available budget)."""
        amount = int(amount_cents)
        if amount < 0:
            raise ControlPlaneError("amount_cents must be >= 0", code="validation_error")
        if amount == 0:
            return await self._require(mission_id)
        mission = await self._require(mission_id)

        # Prefer consuming reservation first
        from_reserve = min(amount, mission.reserved_cents)
        from_available = amount - from_reserve
        available = mission.budget_limit_cents - mission.spend_cents - mission.reserved_cents
        if from_available > available:
            denial = BudgetDenial(
                reason="insufficient_budget_on_commit",
                requested_cents=amount,
                available_cents=max(0, available) + mission.reserved_cents,
                limit_cents=mission.budget_limit_cents,
                spend_cents=mission.spend_cents,
                reserved_cents=mission.reserved_cents,
            )
            await self.store.append_audit(
                event_type="budget.denied",
                actor=actor,
                mission_id=mission_id,
                detail=denial.to_dict(),
            )
            raise BudgetError("Budget commit denied", denial=denial)

        await self.store.add_ledger_entry(
            mission_id=mission_id,
            kind="commit",
            amount_cents=amount,
            note=note or "commit",
        )
        mission = await self.store.update_mission_fields(
            mission_id,
            spend_cents=mission.spend_cents + amount,
            reserved_cents=mission.reserved_cents - from_reserve,
        )
        await self.store.append_audit(
            event_type="budget.committed",
            actor=actor,
            mission_id=mission_id,
            detail={
                "amount_cents": amount,
                "from_reserve": from_reserve,
                "spend_cents": mission.spend_cents,
            },
        )
        return mission

    async def release_budget(
        self,
        mission_id: str,
        *,
        amount_cents: int | None = None,
        actor: str = "api",
        note: str = "",
    ) -> Mission:
        mission = await self._require(mission_id)
        amount = int(amount_cents) if amount_cents is not None else mission.reserved_cents
        if amount <= 0:
            return mission
        amount = min(amount, mission.reserved_cents)
        await self.store.add_ledger_entry(
            mission_id=mission_id,
            kind="release",
            amount_cents=amount,
            note=note or "release",
        )
        mission = await self.store.update_mission_fields(
            mission_id, reserved_cents=mission.reserved_cents - amount
        )
        await self.store.append_audit(
            event_type="budget.released",
            actor=actor,
            mission_id=mission_id,
            detail={"amount_cents": amount, "reserved_cents": mission.reserved_cents},
        )
        return mission

    # --- workers ---

    async def get_worker(self, worker_id: str) -> WorkerBoundary | None:
        return await self.store.get_worker(worker_id)

    async def list_workers(self, mission_id: str) -> list[WorkerBoundary]:
        return await self.store.list_workers_for_mission(mission_id)

    async def _teardown_worker(
        self, mission_id: str, *, actor: str, reason: str
    ) -> None:
        workers = await self.store.list_workers_for_mission(mission_id)
        now = time.time()
        for w in workers:
            if w.status == "terminated":
                continue
            await self.store.update_worker(w.id, status="tearing_down")
            await self.store.update_worker(
                w.id, status="terminated", terminated_at=now
            )
            await self.store.append_audit(
                event_type="worker.terminated",
                actor=actor,
                mission_id=mission_id,
                detail={"worker_id": w.id, "reason": reason},
            )

    # --- audit / ledger reads ---

    async def list_audit(
        self, *, mission_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        events = await self.store.list_audit(mission_id=mission_id, limit=limit)
        return [e.to_dict() for e in events]

    async def list_ledger(self, mission_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        entries = await self.store.list_ledger(mission_id, limit=limit)
        return [e.to_dict() for e in entries]

    async def mission_detail(self, mission_id: str) -> dict[str, Any] | None:
        mission = await self.store.get_mission(mission_id)
        if mission is None:
            return None
        workers = await self.list_workers(mission_id)
        return {
            "mission": mission.to_dict(),
            "workers": [w.to_dict() for w in workers],
            "ledger": await self.list_ledger(mission_id, limit=50),
            "audit": await self.list_audit(mission_id=mission_id, limit=50),
        }

    async def _require(self, mission_id: str) -> Mission:
        mission = await self.store.get_mission(mission_id)
        if mission is None:
            raise ControlPlaneError("Mission not found", code="not_found")
        return mission


def build_control_plane(db: Database) -> ControlPlaneService:
    return ControlPlaneService(ControlPlaneStore(db))
