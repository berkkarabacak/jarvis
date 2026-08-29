from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.tenancy.errors import TenantAccessError, TenantNotFound
from app.tenancy.models import role_allows


@dataclass(frozen=True)
class TenantContext:
    """Request-scoped tenancy identity for Control Room APIs."""

    user_id: UUID
    org_id: UUID
    role: str

    def require(self, capability: str) -> None:
        if not role_allows(self.role, capability):
            raise TenantAccessError(f"role {self.role!r} lacks {capability}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": str(self.user_id),
            "org_id": str(self.org_id),
            "role": self.role,
        }


def hide_cross_tenant(_exc: Exception | None = None) -> TenantNotFound:
    """Map cross-org denial to leak-safe 404 (persistence contract)."""
    return TenantNotFound("not found")
