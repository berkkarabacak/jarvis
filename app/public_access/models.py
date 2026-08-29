from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.public_access.errors import AccountAccessDenied
from app.tenancy.scope import TenantContext

ACCOUNT_PRINCIPAL_SCHEMA_VERSION = 1
PUBLIC_ACCOUNT_CAPABILITIES = frozenset(
    {
        "account.rename",
        "mission.read",
        "mission.run",
    }
)


def _utc_iso(timestamp: float) -> str:
    return (
        datetime.fromtimestamp(float(timestamp), timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True)
class AccountPrincipalV1:
    """Safe account identity supplied to user-facing Control Room adapters."""

    user_id: UUID
    org_id: UUID
    display_name: str
    organization_name: str
    role: str
    account_kind: str
    expires_at: float
    capabilities: frozenset[str] = PUBLIC_ACCOUNT_CAPABILITIES

    def require(self, capability: str) -> None:
        if capability not in self.capabilities:
            raise AccountAccessDenied()

    def tenant_context(self) -> TenantContext:
        return TenantContext(user_id=self.user_id, org_id=self.org_id, role=self.role)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the safe browser contract without bearer material.

        Account and organization UUIDs are intentional tenant identifiers;
        they are not credentials and grant no access without the opaque cookie.
        """

        return {
            "schema_version": ACCOUNT_PRINCIPAL_SCHEMA_VERSION,
            "authenticated": True,
            "account": {
                "id": str(self.user_id),
                "kind": self.account_kind,
                "display_name": self.display_name,
            },
            "organization": {
                "id": str(self.org_id),
                "name": self.organization_name,
                "role": self.role,
            },
            "capabilities": sorted(self.capabilities),
            "session": {"expires_at": _utc_iso(self.expires_at)},
        }


@dataclass(frozen=True)
class IssuedGuestSession:
    principal: AccountPrincipalV1
    session_token: str = field(repr=False)


@dataclass(frozen=True)
class ResourceBinding:
    resource_type: str
    resource_id: str
    org_id: UUID
    owner_user_id: UUID
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "org_id": str(self.org_id),
            "owner_user_id": str(self.owner_user_id),
            "created_at": _utc_iso(self.created_at),
        }


@dataclass(frozen=True)
class UsageWindow:
    kind: str
    used: int
    limit: int
    resets_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "used": self.used,
            "limit": self.limit,
            "remaining": max(0, self.limit - self.used),
            "resets_at": _utc_iso(self.resets_at),
        }


@dataclass(frozen=True)
class UsageQuotaSnapshot:
    quota_name: str
    hourly: UsageWindow
    daily: UsageWindow

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "quota_name": self.quota_name,
            "hourly": self.hourly.to_dict(),
            "daily": self.daily.to_dict(),
        }
