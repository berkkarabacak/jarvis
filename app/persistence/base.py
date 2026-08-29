from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class DatabaseHealth:
    provider: str
    ok: bool
    latency_ms: int | None = None
    detail: str | None = None
    path_or_dsn: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "ok": self.ok,
            "latency_ms": self.latency_ms,
            "detail": self.detail,
            "path_or_dsn": self.path_or_dsn,
        }


@runtime_checkable
class DatabaseProvider(Protocol):
    """Portable DB handle. SQLite (dev/default); Postgres target (ORCH-69 / D-007)."""

    name: str

    async def connect(self) -> Any: ...

    async def close(self) -> None: ...

    async def ping(self) -> DatabaseHealth: ...

    @property
    def conn(self) -> Any:
        """Low-level connection used by repositories (sqlite Connection for now)."""
        ...
