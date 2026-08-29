from __future__ import annotations

from typing import Any

from app.executive.session import ExecutiveSession, ExecutiveSessionError
from app.executive.store import HandoffStore, InMemoryHandoffStore
from app.memory.sanitize import sanitize_text


class ExecutiveSessionRegistry:
    """Process-local registry of open executive sessions (ORCH-71).

    Durable mission ownership stays with the control plane (ORCH-70). This
    registry only tracks live in-process session objects for the API surface.
    """

    def __init__(self, handoff_store: HandoffStore | None = None) -> None:
        self._handoff_store: HandoffStore = handoff_store or InMemoryHandoffStore()
        self._sessions: dict[str, ExecutiveSession] = {}

    @property
    def handoff_store(self) -> HandoffStore:
        return self._handoff_store

    def open_session(
        self,
        *,
        mission_id: str,
        brief: str = "",
        confidence_target: int = 80,
        session_id: str | None = None,
    ) -> ExecutiveSession:
        session = ExecutiveSession.open(
            mission_id=mission_id,
            brief=brief,
            confidence_target=confidence_target,
            handoff_store=self._handoff_store,
            session_id=session_id,
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> ExecutiveSession | None:
        return self._sessions.get(session_id)

    def require(self, session_id: str) -> ExecutiveSession:
        sid = sanitize_text((session_id or "").strip(), max_chars=120)
        session = self._sessions.get(sid)
        if session is None:
            raise ExecutiveSessionError(f"unknown session: {sid}")
        return session

    def list_sessions(self, *, mission_id: str | None = None) -> list[ExecutiveSession]:
        rows = list(self._sessions.values())
        if mission_id is not None:
            mid = sanitize_text(mission_id.strip(), max_chars=120)
            rows = [s for s in rows if s.mission_id == mid]
        rows.sort(key=lambda s: s.created_at, reverse=True)
        return rows

    def drop(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def snapshot_all(self, *, mission_id: str | None = None) -> list[dict[str, Any]]:
        return [s.snapshot() for s in self.list_sessions(mission_id=mission_id)]
