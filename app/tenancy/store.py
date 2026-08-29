from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from app.tenancy.errors import TenantNotFound
from app.tenancy.keys import generate_api_key, hash_api_key, sanitize_scopes, verify_api_key
from app.tenancy.models import (
    BOOTSTRAP_ORG_ID,
    BOOTSTRAP_ORG_SLUG,
    MEMBER_ROLES,
    AuditEvent,
    Membership,
    OrgApiKey,
    Organization,
    User,
    require_org_id,
)
from app.tenancy.scope import TenantContext, hide_cross_tenant

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _as_uuid(value: Any) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _rg(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except Exception:
        return default


def _org_from_row(row: Any) -> Organization:
    return Organization(
        id=_as_uuid(_rg(row, "id")),
        name=str(_rg(row, "name")),
        slug=str(_rg(row, "slug")),
        plan=str(_rg(row, "plan") or "standard"),
        status=str(_rg(row, "status") or "active"),
        created_at=_rg(row, "created_at"),
        updated_at=_rg(row, "updated_at"),
    )


def _user_from_row(row: Any) -> User:
    ext = _rg(row, "external_subject")
    return User(
        id=_as_uuid(_rg(row, "id")),
        email=str(_rg(row, "email")),
        display_name=str(_rg(row, "display_name") or ""),
        status=str(_rg(row, "status") or "active"),
        external_subject=str(ext) if ext else None,
        created_at=_rg(row, "created_at"),
    )


def _mem_from_row(row: Any) -> Membership:
    return Membership(
        user_id=_as_uuid(_rg(row, "user_id")),
        org_id=_as_uuid(_rg(row, "org_id")),
        role=str(_rg(row, "role")),  # type: ignore[arg-type]
        created_at=_rg(row, "created_at"),
    )


class TenancyStore:
    """Org-scoped tenancy repository for the Postgres platform database.

    Uses an asyncpg-like connection or pool.acquire() compatible object.
    Cross-tenant misses raise TenantNotFound (HTTP 404), never 403.
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def _conn(self):
        acquire = getattr(self._pool, "acquire", None)
        if acquire is not None:
            return await acquire(), True
        return self._pool, False

    async def _release(self, conn: Any, owned: bool) -> None:
        if owned:
            release = getattr(self._pool, "release", None)
            if release is not None:
                await release(conn)

    async def get_bootstrap_org(self) -> Organization:
        org = await self.get_organization_by_slug(BOOTSTRAP_ORG_SLUG)
        if org is None:
            # migration seed may use fixed id
            org = await self.get_organization(BOOTSTRAP_ORG_ID)
        if org is None:
            raise TenantNotFound("bootstrap organization missing; run migrations")
        return org

    async def get_organization(self, org_id: UUID | str) -> Organization | None:
        oid = require_org_id(org_id)
        conn, owned = await self._conn()
        try:
            row = await conn.fetchrow(
                "SELECT id, name, slug, plan, status, created_at, updated_at "
                "FROM organizations WHERE id = $1 AND status <> 'deleted'",
                oid,
            )
            return _org_from_row(row) if row else None
        finally:
            await self._release(conn, owned)

    async def get_organization_by_slug(self, slug: str) -> Organization | None:
        slug_n = (slug or "").strip().lower()
        conn, owned = await self._conn()
        try:
            row = await conn.fetchrow(
                "SELECT id, name, slug, plan, status, created_at, updated_at "
                "FROM organizations WHERE slug = $1 AND status <> 'deleted'",
                slug_n,
            )
            return _org_from_row(row) if row else None
        finally:
            await self._release(conn, owned)

    async def require_organization(self, org_id: UUID | str) -> Organization:
        org = await self.get_organization(org_id)
        if org is None:
            raise hide_cross_tenant()
        return org

    async def create_organization(self, *, name: str, slug: str, plan: str = "standard") -> Organization:
        name_n = (name or "").strip()
        slug_n = (slug or "").strip().lower()
        if not name_n:
            raise ValueError("organization name is required")
        if not _SLUG_RE.match(slug_n):
            raise ValueError("slug must be 3-64 chars: lowercase alphanumeric and hyphens")
        conn, owned = await self._conn()
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO organizations (name, slug, plan, status)
                VALUES ($1, $2, $3, 'active')
                RETURNING id, name, slug, plan, status, created_at, updated_at
                """,
                name_n,
                slug_n,
                (plan or "standard").strip() or "standard",
            )
            return _org_from_row(row)
        finally:
            await self._release(conn, owned)

    async def create_user(
        self,
        *,
        email: str,
        display_name: str = "",
        password_hash: str = "",
        external_subject: str | None = None,
    ) -> User:
        email_n = (email or "").strip().lower()
        if not _EMAIL_RE.match(email_n):
            raise ValueError("valid email is required")
        conn, owned = await self._conn()
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO users (email, display_name, password_hash, external_subject, status)
                VALUES ($1, $2, $3, $4, 'active')
                RETURNING id, email, display_name, status, external_subject, created_at
                """,
                email_n,
                (display_name or "").strip(),
                password_hash or "",
                (external_subject or None),
            )
            return _user_from_row(row)
        finally:
            await self._release(conn, owned)

    async def get_user(self, user_id: UUID | str) -> User | None:
        uid = _as_uuid(user_id)
        conn, owned = await self._conn()
        try:
            row = await conn.fetchrow(
                "SELECT id, email, display_name, status, external_subject, created_at "
                "FROM users WHERE id = $1 AND status <> 'deleted'",
                uid,
            )
            return _user_from_row(row) if row else None
        finally:
            await self._release(conn, owned)

    async def get_user_by_email(self, email: str) -> User | None:
        email_n = (email or "").strip().lower()
        conn, owned = await self._conn()
        try:
            row = await conn.fetchrow(
                "SELECT id, email, display_name, status, external_subject, created_at "
                "FROM users WHERE lower(email) = $1 AND status <> 'deleted'",
                email_n,
            )
            return _user_from_row(row) if row else None
        finally:
            await self._release(conn, owned)

    async def add_membership(
        self,
        *,
        user_id: UUID | str,
        org_id: UUID | str,
        role: str = "member",
    ) -> Membership:
        uid = _as_uuid(user_id)
        oid = require_org_id(org_id)
        role_n = (role or "member").strip().lower()
        if role_n not in MEMBER_ROLES:
            raise ValueError(f"role must be one of {sorted(MEMBER_ROLES)}")
        # ensure org exists (404 if not)
        await self.require_organization(oid)
        conn, owned = await self._conn()
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO memberships (user_id, org_id, role)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id, org_id) DO UPDATE SET role = EXCLUDED.role
                RETURNING user_id, org_id, role, created_at
                """,
                uid,
                oid,
                role_n,
            )
            return _mem_from_row(row)
        finally:
            await self._release(conn, owned)

    async def get_membership(self, user_id: UUID | str, org_id: UUID | str) -> Membership | None:
        uid = _as_uuid(user_id)
        oid = require_org_id(org_id)
        conn, owned = await self._conn()
        try:
            row = await conn.fetchrow(
                "SELECT user_id, org_id, role, created_at FROM memberships "
                "WHERE user_id = $1 AND org_id = $2",
                uid,
                oid,
            )
            return _mem_from_row(row) if row else None
        finally:
            await self._release(conn, owned)

    async def require_membership(self, user_id: UUID | str, org_id: UUID | str) -> Membership:
        mem = await self.get_membership(user_id, org_id)
        if mem is None:
            raise hide_cross_tenant()
        return mem

    async def tenant_context(self, user_id: UUID | str, org_id: UUID | str) -> TenantContext:
        mem = await self.require_membership(user_id, org_id)
        return TenantContext(user_id=mem.user_id, org_id=mem.org_id, role=mem.role)

    async def list_org_members(self, org_id: UUID | str, *, actor: TenantContext) -> list[dict[str, Any]]:
        """List members of org_id; actor must belong to the same org."""
        oid = require_org_id(org_id)
        if actor.org_id != oid:
            raise hide_cross_tenant()
        actor.require("mission.read")
        conn, owned = await self._conn()
        try:
            rows = await conn.fetch(
                """
                SELECT u.id AS user_id, u.email, u.display_name, m.role, m.created_at
                FROM memberships m
                JOIN users u ON u.id = m.user_id
                WHERE m.org_id = $1 AND u.status <> 'deleted'
                ORDER BY u.email
                """,
                oid,
            )
            out = []
            for r in rows:
                out.append(
                    {
                        "user_id": str(r["user_id"]),
                        "email": str(r["email"]),
                        "display_name": str(r["display_name"] or ""),
                        "role": str(r["role"]),
                        "created_at": r["created_at"].isoformat()
                        if getattr(r["created_at"], "isoformat", None)
                        else r["created_at"],
                    }
                )
            return out
        finally:
            await self._release(conn, owned)

    async def org_scoped_get(
        self,
        *,
        table: str,
        row_id: UUID | str,
        org_id: UUID | str,
        id_column: str = "id",
        org_column: str = "org_id",
    ) -> dict[str, Any] | None:
        """Generic leak-safe fetch: wrong org => None (caller maps to 404)."""
        # Only allow simple identifiers to prevent SQL injection via table/column names.
        for ident in (table, id_column, org_column):
            if not re.match(r"^[a-z_][a-z0-9_]*$", ident):
                raise ValueError(f"invalid identifier: {ident}")
        oid = require_org_id(org_id)
        rid = _as_uuid(row_id)
        conn, owned = await self._conn()
        try:
            row = await conn.fetchrow(
                f"SELECT * FROM {table} WHERE {id_column} = $1 AND {org_column} = $2",
                rid,
                oid,
            )
            if row is None:
                return None
            if hasattr(row, "keys"):
                return {k: row[k] for k in row.keys()}
            return dict(row)
        finally:
            await self._release(conn, owned)

    # --- org API keys (hash-only) ---

    @staticmethod
    def _key_from_row(row: Any) -> OrgApiKey:
        scopes = _rg(row, "scopes") or []
        if isinstance(scopes, str):
            scopes = [scopes]
        return OrgApiKey(
            id=_as_uuid(_rg(row, "id")),
            org_id=_as_uuid(_rg(row, "org_id")),
            name=str(_rg(row, "name") or ""),
            key_prefix=str(_rg(row, "key_prefix") or ""),
            scopes=tuple(str(s) for s in scopes),
            status=str(_rg(row, "status") or "active"),
            created_at=_rg(row, "created_at"),
            last_used_at=_rg(row, "last_used_at"),
            revoked_at=_rg(row, "revoked_at"),
        )

    async def create_org_api_key(
        self,
        *,
        org_id: UUID | str,
        actor: TenantContext,
        name: str = "",
        scopes: list[str] | None = None,
    ) -> tuple[OrgApiKey, str]:
        """Create key. Returns (metadata, plaintext_once). Plaintext never stored."""
        oid = require_org_id(org_id)
        if actor.org_id != oid:
            raise hide_cross_tenant()
        actor.require("keys.manage")
        plaintext, prefix, key_hash = generate_api_key()
        scope_list = sanitize_scopes(scopes)
        conn, owned = await self._conn()
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO org_api_keys (
                    org_id, name, key_prefix, key_hash, scopes, created_by, status
                ) VALUES ($1, $2, $3, $4, $5, $6, 'active')
                RETURNING id, org_id, name, key_prefix, scopes, status,
                          created_at, last_used_at, revoked_at
                """,
                oid,
                (name or "").strip()[:120],
                prefix,
                key_hash,
                scope_list,
                actor.user_id,
            )
            meta = self._key_from_row(row)
        finally:
            await self._release(conn, owned)
        await self.append_audit(
            org_id=oid,
            actor=actor,
            event_type="api_key.created",
            resource_type="org_api_key",
            resource_id=str(meta.id),
            detail={"key_prefix": prefix, "scopes": scope_list, "name": meta.name},
        )
        return meta, plaintext

    async def list_org_api_keys(
        self, org_id: UUID | str, *, actor: TenantContext
    ) -> list[OrgApiKey]:
        oid = require_org_id(org_id)
        if actor.org_id != oid:
            raise hide_cross_tenant()
        actor.require("keys.manage")
        conn, owned = await self._conn()
        try:
            rows = await conn.fetch(
                """
                SELECT id, org_id, name, key_prefix, scopes, status,
                       created_at, last_used_at, revoked_at
                FROM org_api_keys
                WHERE org_id = $1
                ORDER BY created_at DESC
                """,
                oid,
            )
            return [self._key_from_row(r) for r in rows]
        finally:
            await self._release(conn, owned)

    async def revoke_org_api_key(
        self, org_id: UUID | str, key_id: UUID | str, *, actor: TenantContext
    ) -> OrgApiKey:
        oid = require_org_id(org_id)
        if actor.org_id != oid:
            raise hide_cross_tenant()
        actor.require("keys.manage")
        kid = _as_uuid(key_id)
        conn, owned = await self._conn()
        try:
            row = await conn.fetchrow(
                """
                UPDATE org_api_keys
                SET status = 'revoked', revoked_at = NOW()
                WHERE id = $1 AND org_id = $2 AND status = 'active'
                RETURNING id, org_id, name, key_prefix, scopes, status,
                          created_at, last_used_at, revoked_at
                """,
                kid,
                oid,
            )
            if row is None:
                raise hide_cross_tenant()
            meta = self._key_from_row(row)
        finally:
            await self._release(conn, owned)
        await self.append_audit(
            org_id=oid,
            actor=actor,
            event_type="api_key.revoked",
            resource_type="org_api_key",
            resource_id=str(meta.id),
            detail={"key_prefix": meta.key_prefix},
        )
        return meta

    async def authenticate_org_api_key(
        self, plaintext: str
    ) -> tuple[OrgApiKey, UUID] | None:
        """Validate key. Returns (metadata, org_id) or None. Never logs plaintext."""
        raw = (plaintext or "").strip()
        if not raw.startswith("ao_") or len(raw) < 20:
            return None
        digest = hash_api_key(raw)
        conn, owned = await self._conn()
        try:
            row = await conn.fetchrow(
                """
                SELECT id, org_id, name, key_prefix, key_hash, scopes, status,
                       created_at, last_used_at, revoked_at
                FROM org_api_keys
                WHERE key_hash = $1 AND status = 'active'
                """,
                digest,
            )
            if row is None:
                return None
            stored_hash = str(_rg(row, "key_hash") or "")
            if not verify_api_key(raw, stored_hash):
                return None
            await conn.execute(
                "UPDATE org_api_keys SET last_used_at = NOW() WHERE id = $1",
                _as_uuid(_rg(row, "id")),
            )
            return self._key_from_row(row), _as_uuid(_rg(row, "org_id"))
        finally:
            await self._release(conn, owned)

    # --- audit events (org-scoped, append-only) ---

    async def append_audit(
        self,
        *,
        org_id: UUID | str,
        event_type: str,
        actor: TenantContext | None = None,
        actor_type: str = "user",
        actor_key_id: UUID | str | None = None,
        resource_type: str = "",
        resource_id: str = "",
        detail: dict[str, Any] | None = None,
    ) -> AuditEvent:
        oid = require_org_id(org_id)
        if actor is not None and actor.org_id != oid:
            raise hide_cross_tenant()
        # Strip any accidental secret-like fields from detail
        safe_detail: dict[str, Any] = {}
        for k, v in (detail or {}).items():
            lk = str(k).lower()
            if any(x in lk for x in ("password", "secret", "token", "api_key", "key_hash")):
                continue
            safe_detail[str(k)] = v
        et = (event_type or "").strip()[:120] or "unknown"
        conn, owned = await self._conn()
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO audit_events (
                    org_id, actor_user_id, actor_key_id, actor_type,
                    event_type, resource_type, resource_id, detail_json
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                RETURNING id, org_id, actor_user_id, actor_key_id, actor_type,
                          event_type, resource_type, resource_id, detail_json, created_at
                """,
                oid,
                actor.user_id if actor else None,
                _as_uuid(actor_key_id) if actor_key_id else None,
                actor_type if actor is None else "user",
                et,
                (resource_type or "")[:80],
                (resource_id or "")[:120],
                json.dumps(safe_detail, default=str),
            )
            return self._audit_from_row(row)
        finally:
            await self._release(conn, owned)

    @staticmethod
    def _audit_from_row(row: Any) -> AuditEvent:
        detail = _rg(row, "detail_json") or {}
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except Exception:
                detail = {}
        if not isinstance(detail, dict):
            detail = {}
        uid = _rg(row, "actor_user_id")
        kid = _rg(row, "actor_key_id")
        return AuditEvent(
            id=_as_uuid(_rg(row, "id")),
            org_id=_as_uuid(_rg(row, "org_id")),
            event_type=str(_rg(row, "event_type")),
            actor_type=str(_rg(row, "actor_type") or "system"),
            resource_type=str(_rg(row, "resource_type") or ""),
            resource_id=str(_rg(row, "resource_id") or ""),
            detail=detail,
            actor_user_id=_as_uuid(uid) if uid else None,
            actor_key_id=_as_uuid(kid) if kid else None,
            created_at=_rg(row, "created_at"),
        )

    async def list_audit_events(
        self,
        org_id: UUID | str,
        *,
        actor: TenantContext,
        limit: int = 50,
    ) -> list[AuditEvent]:
        oid = require_org_id(org_id)
        if actor.org_id != oid:
            raise hide_cross_tenant()
        actor.require("audit.read")
        limit = max(1, min(int(limit), 200))
        conn, owned = await self._conn()
        try:
            rows = await conn.fetch(
                """
                SELECT id, org_id, actor_user_id, actor_key_id, actor_type,
                       event_type, resource_type, resource_id, detail_json, created_at
                FROM audit_events
                WHERE org_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                oid,
                limit,
            )
            return [self._audit_from_row(r) for r in rows]
        finally:
            await self._release(conn, owned)
