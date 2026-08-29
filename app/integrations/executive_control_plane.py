from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.control_plane.events import (
    CONTRACT_NAME,
    CONTRACT_VERSION,
    EventAccess,
    EventValidationError,
    sanitize_publish_data,
)
from app.control_plane.models import TERMINAL_MISSION_STATUSES, Mission
from app.control_plane.service import ControlPlaneService
from app.executive.safety import require_public_identifier, sanitize_public_text
from app.tenancy.scope import TenantContext


class ExecutiveControlPlaneIntegrationError(ValueError):
    """Safe integration error with no vendor, prompt, or credential detail."""


@dataclass
class ExecutiveControlPlaneAdapter:
    """Bind ORCH-71 safe turns to ORCH-70 history and stream semantics.

    The existing operator API secret is adapted to an owner constrained to the
    integration's fixed default organization. A tenant principal can replace it
    without changing the executive runtime or Prime adapter.
    """

    control_plane: ControlPlaneService
    org_id: str = "default"
    access: EventAccess = field(default_factory=lambda: EventAccess.owner("default"))
    actor: str = "executive_control_plane_adapter"

    def __post_init__(self) -> None:
        self.org_id = require_public_identifier(str(self.org_id or "").strip())
        if not self.access.global_owner and self.access.org_id != self.org_id:
            raise ExecutiveControlPlaneIntegrationError(
                "Control-plane access does not match the mission organization"
            )

    @classmethod
    def for_tenant(
        cls,
        control_plane: ControlPlaneService,
        tenant: TenantContext,
    ) -> ExecutiveControlPlaneAdapter:
        """Build a host-trusted adapter from a request-scoped tenant context."""

        tenant.require("mission.run")
        org_id = require_public_identifier(str(tenant.org_id))
        return cls(
            control_plane=control_plane,
            org_id=org_id,
            access=EventAccess.owner(org_id),
            actor="public_executive_adapter",
        )

    async def start_mission(self) -> Mission:
        # The control plane owns the authoritative UUID. Keep the CEO brief out
        # of its durable mission and audit records.
        mission = await self.control_plane.create_mission(
            title="Executive AI session",
            brief="",
            org_id=self.org_id,
            actor=self.actor,
        )
        try:
            return await self.control_plane.start_mission(
                mission.id,
                actor=self.actor,
            )
        except Exception:
            await self.rollback_created_mission(mission.id, created=True)
            raise

    async def rollback_created_mission(self, mission_id: str, *, created: bool) -> None:
        if not created:
            return
        try:
            await self.control_plane.kill_mission(
                require_public_identifier(mission_id),
                actor=self.actor,
                reason="executive_open_failed",
            )
        except Exception:  # noqa: BLE001,S110 - preserve the original open failure
            pass

    async def publish_turn(
        self,
        batch: Any,
        *,
        expected_mission_id: str,
        expected_message_id: str,
        expected_final_text: str,
    ) -> dict[str, Any]:
        mission_id = require_public_identifier(expected_mission_id)
        message_id = require_public_identifier(expected_message_id)
        safe_final_text, filtered = sanitize_public_text(expected_final_text)
        if filtered or safe_final_text != expected_final_text.strip():
            raise ExecutiveControlPlaneIntegrationError(
                "Executive final message failed the public safety contract"
            )
        if not isinstance(batch, Mapping):
            raise ExecutiveControlPlaneIntegrationError("Event batch must be an object")
        if set(batch) != {
            "target_contract",
            "target_contract_version",
            "mission_id",
            "events",
            "authorization",
        }:
            raise ExecutiveControlPlaneIntegrationError(
                "Event batch fields are invalid"
            )
        if batch.get("target_contract") != CONTRACT_NAME:
            raise ExecutiveControlPlaneIntegrationError("Event contract is unsupported")
        if batch.get("target_contract_version") != CONTRACT_VERSION:
            raise ExecutiveControlPlaneIntegrationError(
                "Event contract version is unsupported"
            )
        if batch.get("mission_id") != mission_id:
            raise ExecutiveControlPlaneIntegrationError(
                "Event mission does not match session"
            )
        if batch.get("authorization") != "required_at_orch70_publish_adapter":
            raise ExecutiveControlPlaneIntegrationError(
                "Event authorization marker is invalid"
            )
        events = batch.get("events")
        if not isinstance(events, list) or [
            event.get("type") for event in events if isinstance(event, Mapping)
        ] != [
            "executive_message",
            "evidence",
            "confidence",
        ]:
            raise ExecutiveControlPlaneIntegrationError(
                "Final event sequence is invalid"
            )

        # Validate and scrub every item before the first durable write. This
        # prevents a later invalid item from creating a partially accepted batch.
        prepared: list[tuple[str, dict[str, Any]]] = []
        for event in events:
            if not isinstance(event, Mapping) or set(event) != {"type", "data"}:
                raise ExecutiveControlPlaneIntegrationError(
                    "Event request does not match the adapter contract"
                )
            event_type = event.get("type")
            if not isinstance(event_type, str):
                raise ExecutiveControlPlaneIntegrationError("Event type is invalid")
            try:
                safe_data = sanitize_publish_data(event_type, event.get("data"))
            except EventValidationError as exc:
                raise ExecutiveControlPlaneIntegrationError(
                    "Event request failed the public safety contract"
                ) from exc
            prepared.append((event_type, safe_data))

        if prepared[0][1]["summary"] != safe_final_text:
            raise ExecutiveControlPlaneIntegrationError(
                "Executive event does not match the final message"
            )
        if prepared[1][1]["evidence_id"] != message_id:
            raise ExecutiveControlPlaneIntegrationError(
                "Evidence event does not match the final message"
            )
        confidence = prepared[2][1]
        if (
            confidence["subject_type"] != "mission"
            or confidence["subject_id"] != mission_id
        ):
            raise ExecutiveControlPlaneIntegrationError(
                "Confidence event does not match the mission"
            )

        published = []
        for event_type, safe_data in prepared:
            published.append(
                await self.control_plane.events.publish(
                    access=self.access,
                    mission_id=mission_id,
                    event_type=event_type,
                    data=safe_data,
                )
            )
        return {
            "contract": CONTRACT_NAME,
            "contract_version": CONTRACT_VERSION,
            "mission_id": mission_id,
            "persisted": True,
            "events": published,
        }

    async def end_mission(
        self,
        mission_id: str,
        *,
        status: str,
        reason: str,
    ) -> Mission | None:
        public_mission_id = require_public_identifier(mission_id)
        mission = await self.control_plane.get_mission(public_mission_id)
        if mission is not None and mission.org_id != self.org_id:
            raise ExecutiveControlPlaneIntegrationError(
                "Control-plane mission is not available"
            )
        if mission is None or mission.status in TERMINAL_MISSION_STATUSES:
            return mission
        if status == "completed":
            return await self.control_plane.complete_mission(
                public_mission_id,
                actor=self.actor,
                note="executive_completed",
            )
        if status == "failed":
            return await self.control_plane.fail_mission(
                public_mission_id,
                actor=self.actor,
                reason=reason or "executive_failed",
            )
        return await self.control_plane.kill_mission(
            public_mission_id,
            actor=self.actor,
            reason=reason or "executive_stopped",
        )
