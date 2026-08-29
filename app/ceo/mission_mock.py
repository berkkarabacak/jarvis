from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from app.memory.sanitize import sanitize_text

MissionStatus = Literal["active", "paused", "stopped", "completed"]


@dataclass
class MockMission:
    mission_id: str
    brief: str
    status: MissionStatus = "active"
    avatar_state: str = "working"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    events: list[dict[str, Any]] = field(default_factory=list)
    preview: dict[str, Any] | None = None
    confidence: int = 12
    budget_consumed_usd: float = 0.0
    budget_cap_usd: float = 25.0

    def touch(self) -> None:
        self.updated_at = time.time()

    def add_event(self, kind: str, message: str) -> None:
        self.events.append(
            {
                "at": time.time(),
                "kind": kind,
                "message": sanitize_text(message, max_chars=400),
            }
        )
        if len(self.events) > 50:
            self.events = self.events[-50:]
        self.touch()


class MockMissionStore:
    """In-process mock missions for ORCH-72 CEO shell (no live execution)."""

    def __init__(self) -> None:
        self._missions: dict[str, MockMission] = {}
        self._active_id: str | None = None

    @property
    def active_id(self) -> str | None:
        return self._active_id

    def get(self, mission_id: str) -> MockMission | None:
        return self._missions.get(mission_id)

    def active(self) -> MockMission | None:
        if self._active_id:
            return self._missions.get(self._active_id)
        return None

    def start(self, brief: str, *, mission_id: str | None = None) -> MockMission:
        text = sanitize_text((brief or "").strip(), max_chars=4000)
        if not text:
            raise ValueError("mission brief is required")
        # Stop previous active mock mission
        if self._active_id and self._active_id in self._missions:
            prev = self._missions[self._active_id]
            if prev.status == "active":
                prev.status = "stopped"
                prev.avatar_state = "completed"
                prev.add_event("stopped", "Superseded by new mission")
        mid = mission_id or str(uuid.uuid4())
        m = MockMission(mission_id=mid, brief=text, status="active", avatar_state="working")
        m.add_event("started", "Mission accepted (mock)")
        m.add_event("progress", "Executive is coordinating specialists (mock)")
        m.preview = {
            "kind": "placeholder",
            "title": "Preview placeholder",
            "summary": "Live artifact previews arrive when ORCH-71/74 wire evidence.",
            "url": None,
            "ready": False,
        }
        m.confidence = 18
        m.budget_consumed_usd = 0.12
        self._missions[mid] = m
        self._active_id = mid
        return m

    def pause(self, mission_id: str | None = None) -> MockMission:
        m = self._require(mission_id)
        if m.status not in ("active", "paused"):
            raise RuntimeError(f"cannot pause mission in status {m.status}")
        m.status = "paused"
        m.avatar_state = "awaiting_ceo"
        m.add_event("paused", "Paused by CEO")
        return m

    def resume(self, mission_id: str | None = None) -> MockMission:
        m = self._require(mission_id)
        if m.status != "paused":
            raise RuntimeError(f"cannot resume mission in status {m.status}")
        m.status = "active"
        m.avatar_state = "working"
        m.add_event("resumed", "Resumed by CEO")
        return m

    def stop(self, mission_id: str | None = None, *, reason: str = "ceo_stopped") -> MockMission:
        m = self._require(mission_id)
        if m.status in ("stopped", "completed"):
            return m
        m.status = "stopped"
        m.avatar_state = "completed"
        m.add_event("stopped", reason or "ceo_stopped")
        return m

    def progress_drawer(self, mission_id: str | None = None) -> dict[str, Any]:
        m = self.active() if mission_id is None else self.get(mission_id)
        if m is None:
            return {
                "mission_id": None,
                "status": "idle",
                "confidence": None,
                "budget": {"consumed_usd": None, "cap_usd": None, "currency": "USD"},
                "teams_active": 0,
                "work": {"completed": 0, "active": 0, "blocked": 0},
                "events": [],
                "blockers": [],
                "preview_ready": False,
            }
        blocked = 1 if m.status == "paused" else 0
        active = 1 if m.status == "active" else 0
        return {
            "mission_id": m.mission_id,
            "status": m.status,
            "brief": m.brief,
            "confidence": m.confidence,
            "budget": {
                "consumed_usd": m.budget_consumed_usd,
                "cap_usd": m.budget_cap_usd,
                "currency": "USD",
            },
            "teams_active": active,
            "work": {
                "completed": 0 if m.status == "active" else 1,
                "active": active,
                "blocked": blocked,
            },
            "events": list(m.events)[-12:],
            "blockers": ["Awaiting CEO"] if m.status == "paused" else [],
            "preview_ready": bool(m.preview),
            "updated_at": m.updated_at,
        }

    def preview(self, mission_id: str | None = None) -> dict[str, Any]:
        m = self.active() if mission_id is None else self.get(mission_id)
        if m is None or not m.preview:
            return {
                "ready": False,
                "kind": "placeholder",
                "title": "No preview yet",
                "summary": "Start a mock mission to see the preview placeholder.",
                "url": None,
            }
        return dict(m.preview)

    def _require(self, mission_id: str | None) -> MockMission:
        mid = mission_id or self._active_id
        if not mid or mid not in self._missions:
            raise KeyError("no active mock mission")
        return self._missions[mid]


# Process singleton used by CEO routes (tests can replace app.state)
_STORE = MockMissionStore()


def get_mock_mission_store() -> MockMissionStore:
    return _STORE


def reset_mock_mission_store() -> MockMissionStore:
    global _STORE
    _STORE = MockMissionStore()
    return _STORE
