"""B4: rate-limited Prime progress events for Realtime narration ==GRoK== (ORCH-254)."""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProgressEvent:
    id: str
    mission_id: str
    message: str
    ts: float = field(default_factory=time.time)
    level: str = "info"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "mission_id": self.mission_id,
            "message": self.message,
            "ts": self.ts,
            "level": self.level,
        }


class PrimeProgressBus:
    def __init__(self, *, max_events: int = 50) -> None:
        self._events: deque[ProgressEvent] = deque(maxlen=max_events)
        self._lock = threading.Lock()
        self._last_emit = 0.0
        self._silenced_until = 0.0

    def silence(self, seconds: float = 300.0) -> None:
        with self._lock:
            self._silenced_until = time.time() + max(0.0, seconds)

    def is_silenced(self) -> bool:
        return time.time() < self._silenced_until

    def min_interval_sec(self) -> float:
        raw = (os.environ.get("JARVIS_PRIME_NARRATE_INTERVAL_SEC") or "12").strip()
        try:
            return max(3.0, min(120.0, float(raw)))
        except ValueError:
            return 12.0

    def narration_enabled(self) -> bool:
        if str(os.environ.get("JARVIS_PRIME_NARRATE", "true")).lower() in {
            "0",
            "false",
            "off",
            "no",
        }:
            return False
        return not self.is_silenced()

    def emit(self, mission_id: str, message: str, *, level: str = "info") -> ProgressEvent | None:
        if not self.narration_enabled():
            return None
        now = time.time()
        with self._lock:
            if now - self._last_emit < self.min_interval_sec():
                return None
            self._last_emit = now
            ev = ProgressEvent(
                id="pe_" + uuid.uuid4().hex[:10],
                mission_id=mission_id,
                message=(message or "")[:240],
                level=level,
            )
            self._events.append(ev)
            return ev

    def recent(self, *, since_ts: float = 0.0, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            items = [e for e in self._events if e.ts > since_ts]
        return [e.to_dict() for e in list(items)[-limit:]]


_bus: PrimeProgressBus | None = None


def get_progress_bus() -> PrimeProgressBus:
    global _bus
    if _bus is None:
        _bus = PrimeProgressBus()
    return _bus
