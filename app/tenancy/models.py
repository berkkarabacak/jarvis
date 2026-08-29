from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

MemberRole = Literal["owner", "admin", "member", "viewer"]
MEMBER_ROLES: frozenset[str] = frozenset({"owner", "admin", "member", "viewer"})

# Capability matrix for Control Room foundation (ORCH-69).
ROLE_CAPS: dict[str, frozenset[str]] = {
    "owner": frozenset(
        {
            "org.manage",
            "members.manage",
            "keys.manage",
            "budget.manage",
            "mission.run",
            "mission.read",
            "audit.read",
        }
    ),
    "admin": frozenset(
        {
            "org.manage",
            "members.manage",
            "keys.manage",
            "budget.manage",
            "mission.run",
            "mission.read",
            "audit.read",
        }
    ),
    "member": frozenset({"mission.run", "mission.read"}),
    "viewer": frozenset({"mission.read"}),
}

BOOTSTRAP_ORG_ID = UUID("00000000-0000-4000-8000-000000000001")
BOOTSTRAP_ORG_SLUG = "default"


def role_allows(role: str, capability: str) -> bool:
    return capability in ROLE_CAPS.get((role or "").strip().lower(), frozenset())


@dataclass(frozen=True)
class Organization:
    id: UUID
    name: str
    slug: str
    plan: str = "standard"
    status: str = "active"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "slug": self.slug,
            "plan": self.plan,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass(frozen=True)
class User:
    id: UUID
    email: str
    display_name: str = ""
    status: str = "active"
    external_subject: str | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "email": self.email,
            "display_name": self.display_name,
            "status": self.status,
            "external_subject": self.external_subject,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass(frozen=True)
class Membership:
    user_id: UUID
    org_id: UUID
    role: MemberRole
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": str(self.user_id),
            "org_id": str(self.org_id),
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def require_org_id(org_id: UUID | str | None) -> UUID:
    """Guard used by repositories: missing org_id is a programming error."""
    if org_id is None or org_id == "":
        raise ValueError("org_id is required for tenant-scoped queries")
    if isinstance(org_id, UUID):
        return org_id
    return UUID(str(org_id))


@dataclass(frozen=True)
class OrgApiKey:
    """Public metadata only — never includes plaintext or key_hash."""

    id: UUID
    org_id: UUID
    name: str
    key_prefix: str
    scopes: tuple[str, ...]
    status: str
    created_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "org_id": str(self.org_id),
            "name": self.name,
            "key_prefix": self.key_prefix,
            "scopes": list(self.scopes),
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
        }


@dataclass(frozen=True)
class AuditEvent:
    id: UUID
    org_id: UUID
    event_type: str
    actor_type: str
    resource_type: str = ""
    resource_id: str = ""
    detail: dict[str, Any] | None = None
    actor_user_id: UUID | None = None
    actor_key_id: UUID | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "org_id": str(self.org_id),
            "event_type": self.event_type,
            "actor_type": self.actor_type,
            "actor_user_id": str(self.actor_user_id) if self.actor_user_id else None,
            "actor_key_id": str(self.actor_key_id) if self.actor_key_id else None,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "detail": dict(self.detail or {}),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
