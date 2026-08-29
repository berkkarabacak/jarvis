from __future__ import annotations

import asyncio
import re
import time
import unicodedata
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

from app.db import Database
from app.public_access.errors import AccountResourceNotFound, UsageQuotaExceeded
from app.public_access.models import (
    AccountPrincipalV1,
    IssuedGuestSession,
    ResourceBinding,
    UsageQuotaSnapshot,
    UsageWindow,
)
from app.public_access.security import (
    PUBLIC_SESSION_TTL_SECONDS,
    generate_session_token,
    hash_session_token,
    valid_session_token,
)

_PSEUDONYMOUS_SUBJECT_RE = re.compile(r"^[A-Za-z0-9:_-]{16,160}$")
_QUOTA_NAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_RESOURCE_TYPE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")


def normalize_display_name(value: str) -> str:
    candidate = " ".join(str(value or "").strip().split())
    if not candidate or len(candidate) > 80:
        raise ValueError("display_name must be 1-80 characters")
    if any(unicodedata.category(ch).startswith("C") for ch in candidate):
        raise ValueError("display_name contains unsupported characters")
    return candidate


def _uuid(value: Any) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


@runtime_checkable
class PublicAccessStore(Protocol):
    """Versioned account boundary consumed by other epics, not SQLite internals."""

    async def resolve_session(
        self, session_token: str | None, *, now: float | None = None
    ) -> AccountPrincipalV1 | None: ...

    async def create_guest_session(
        self,
        *,
        now: float | None = None,
        ttl_seconds: int = PUBLIC_SESSION_TTL_SECONDS,
    ) -> IssuedGuestSession: ...

    async def rename_account(
        self,
        principal: AccountPrincipalV1,
        display_name: str,
        *,
        now: float | None = None,
    ) -> AccountPrincipalV1: ...

    async def revoke_session(
        self, session_token: str | None, *, now: float | None = None
    ) -> bool: ...

    async def bind_resource(
        self,
        *,
        resource_type: str,
        resource_id: str,
        principal: AccountPrincipalV1,
        now: float | None = None,
    ) -> ResourceBinding: ...

    async def require_owned_resource(
        self,
        *,
        resource_type: str,
        resource_id: str,
        principal: AccountPrincipalV1,
    ) -> ResourceBinding: ...

    async def list_resource_bindings(
        self,
        *,
        resource_type: str,
    ) -> list[ResourceBinding]: ...

    async def release_resource_binding(
        self,
        binding: ResourceBinding,
    ) -> bool: ...

    async def consume_quota(
        self,
        *,
        subject_key: str,
        quota_name: str,
        amount: int = 1,
        hourly_limit: int,
        daily_limit: int,
        now: float | None = None,
    ) -> UsageQuotaSnapshot: ...

    async def quota_snapshot(
        self,
        *,
        subject_key: str,
        quota_name: str,
        hourly_limit: int,
        daily_limit: int,
        now: float | None = None,
    ) -> UsageQuotaSnapshot: ...


class SqlitePublicAccessStore:
    """Current production adapter for public accounts and opaque sessions.

    Raw session tokens enter only lookup/create methods. They are never stored,
    returned in public dictionaries, or included in object representations.
    """

    def __init__(self, db: Database) -> None:
        self.db = db
        self._write_lock = asyncio.Lock()

    @staticmethod
    def _principal_from_row(row: Any) -> AccountPrincipalV1:
        return AccountPrincipalV1(
            user_id=_uuid(row["user_id"]),
            org_id=_uuid(row["org_id"]),
            display_name=str(row["display_name"]),
            organization_name=str(row["organization_name"]),
            role=str(row["role"]),
            account_kind=str(row["account_kind"]),
            expires_at=float(row["expires_at"]),
        )

    async def _fetch_principal(
        self,
        token_hash: str,
        *,
        now: float,
    ) -> tuple[AccountPrincipalV1, float] | None:
        cur = await self.db.conn.execute(
            """
            SELECT s.user_id, s.org_id, s.expires_at, s.last_seen_at,
                   a.display_name, a.account_kind,
                   o.name AS organization_name, m.role
            FROM public_account_sessions s
            JOIN public_accounts a ON a.id = s.user_id
            JOIN public_organizations o ON o.id = s.org_id
            JOIN public_memberships m
              ON m.user_id = s.user_id AND m.org_id = s.org_id
            WHERE s.token_hash = ?
              AND s.revoked_at IS NULL
              AND s.expires_at > ?
              AND a.status = 'active'
              AND o.status = 'active'
            """,
            (token_hash, now),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return self._principal_from_row(row), float(row["last_seen_at"])

    async def resolve_session(
        self,
        session_token: str | None,
        *,
        now: float | None = None,
    ) -> AccountPrincipalV1 | None:
        if not valid_session_token(session_token):
            return None
        checked_at = time.time() if now is None else float(now)
        digest = hash_session_token(str(session_token))
        async with self._write_lock:
            result = await self._fetch_principal(digest, now=checked_at)
            if result is None:
                return None
            principal, last_seen_at = result
            if checked_at - last_seen_at >= 60:
                await self.db.conn.execute(
                    "UPDATE public_account_sessions SET last_seen_at = ? "
                    "WHERE token_hash = ? AND revoked_at IS NULL",
                    (checked_at, digest),
                )
                await self.db.conn.commit()
            return principal

    async def create_guest_session(
        self,
        *,
        now: float | None = None,
        ttl_seconds: int = PUBLIC_SESSION_TTL_SECONDS,
    ) -> IssuedGuestSession:
        created_at = time.time() if now is None else float(now)
        ttl = int(ttl_seconds)
        if ttl < 60:
            raise ValueError("session ttl must be at least 60 seconds")
        expires_at = created_at + ttl
        user_id = uuid4()
        org_id = uuid4()
        session_id = uuid4()
        token = generate_session_token()
        digest = hash_session_token(token)
        display_name = "Guest"
        organization_name = "Personal workspace"

        async with self._write_lock:
            await self.db.conn.execute("BEGIN IMMEDIATE")
            try:
                await self.db.conn.execute(
                    """
                    INSERT INTO public_accounts (
                        id, display_name, account_kind, status, created_at, updated_at
                    ) VALUES (?, ?, 'guest', 'active', ?, ?)
                    """,
                    (str(user_id), display_name, created_at, created_at),
                )
                await self.db.conn.execute(
                    """
                    INSERT INTO public_organizations (
                        id, name, status, created_at, updated_at
                    ) VALUES (?, ?, 'active', ?, ?)
                    """,
                    (str(org_id), organization_name, created_at, created_at),
                )
                await self.db.conn.execute(
                    """
                    INSERT INTO public_memberships (user_id, org_id, role, created_at)
                    VALUES (?, ?, 'owner', ?)
                    """,
                    (str(user_id), str(org_id), created_at),
                )
                await self.db.conn.execute(
                    """
                    INSERT INTO public_account_sessions (
                        id, token_hash, user_id, org_id, created_at,
                        expires_at, last_seen_at, revoked_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        str(session_id),
                        digest,
                        str(user_id),
                        str(org_id),
                        created_at,
                        expires_at,
                        created_at,
                    ),
                )
                await self.db.conn.execute("COMMIT")
            except Exception:
                await self.db.conn.execute("ROLLBACK")
                raise

        return IssuedGuestSession(
            principal=AccountPrincipalV1(
                user_id=user_id,
                org_id=org_id,
                display_name=display_name,
                organization_name=organization_name,
                role="owner",
                account_kind="guest",
                expires_at=expires_at,
            ),
            session_token=token,
        )

    async def rename_account(
        self,
        principal: AccountPrincipalV1,
        display_name: str,
        *,
        now: float | None = None,
    ) -> AccountPrincipalV1:
        principal.require("account.rename")
        safe_name = normalize_display_name(display_name)
        updated_at = time.time() if now is None else float(now)
        async with self._write_lock:
            cur = await self.db.conn.execute(
                """
                UPDATE public_accounts
                SET display_name = ?, updated_at = ?
                WHERE id = ? AND status = 'active'
                  AND EXISTS (
                    SELECT 1 FROM public_memberships
                    WHERE user_id = ? AND org_id = ?
                  )
                """,
                (
                    safe_name,
                    updated_at,
                    str(principal.user_id),
                    str(principal.user_id),
                    str(principal.org_id),
                ),
            )
            if cur.rowcount != 1:
                raise AccountResourceNotFound()
            await self.db.conn.commit()
        return AccountPrincipalV1(
            user_id=principal.user_id,
            org_id=principal.org_id,
            display_name=safe_name,
            organization_name=principal.organization_name,
            role=principal.role,
            account_kind=principal.account_kind,
            expires_at=principal.expires_at,
            capabilities=principal.capabilities,
        )

    async def revoke_session(
        self,
        session_token: str | None,
        *,
        now: float | None = None,
    ) -> bool:
        if not valid_session_token(session_token):
            return False
        revoked_at = time.time() if now is None else float(now)
        digest = hash_session_token(str(session_token))
        async with self._write_lock:
            cur = await self.db.conn.execute(
                """
                UPDATE public_account_sessions
                SET revoked_at = ?
                WHERE token_hash = ? AND revoked_at IS NULL
                """,
                (revoked_at, digest),
            )
            await self.db.conn.commit()
            return cur.rowcount == 1

    @staticmethod
    def _validate_resource(resource_type: str, resource_id: str) -> tuple[str, str]:
        kind = str(resource_type or "").strip().lower()
        identifier = str(resource_id or "").strip()
        if not _RESOURCE_TYPE_RE.fullmatch(kind):
            raise ValueError("invalid resource_type")
        if not _RESOURCE_ID_RE.fullmatch(identifier):
            raise ValueError("invalid resource_id")
        return kind, identifier

    async def bind_resource(
        self,
        *,
        resource_type: str,
        resource_id: str,
        principal: AccountPrincipalV1,
        now: float | None = None,
    ) -> ResourceBinding:
        kind, identifier = self._validate_resource(resource_type, resource_id)
        created_at = time.time() if now is None else float(now)
        async with self._write_lock:
            await self.db.conn.execute("BEGIN IMMEDIATE")
            try:
                cur = await self.db.conn.execute(
                    """
                    SELECT resource_type, resource_id, org_id, owner_user_id, created_at
                    FROM public_resource_bindings
                    WHERE resource_type = ? AND resource_id = ?
                    """,
                    (kind, identifier),
                )
                row = await cur.fetchone()
                if row is None:
                    await self.db.conn.execute(
                        """
                        INSERT INTO public_resource_bindings (
                            resource_type, resource_id, org_id, owner_user_id, created_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            kind,
                            identifier,
                            str(principal.org_id),
                            str(principal.user_id),
                            created_at,
                        ),
                    )
                    binding = ResourceBinding(
                        resource_type=kind,
                        resource_id=identifier,
                        org_id=principal.org_id,
                        owner_user_id=principal.user_id,
                        created_at=created_at,
                    )
                else:
                    if str(row["org_id"]) != str(principal.org_id) or str(
                        row["owner_user_id"]
                    ) != str(principal.user_id):
                        raise AccountResourceNotFound()
                    binding = ResourceBinding(
                        resource_type=str(row["resource_type"]),
                        resource_id=str(row["resource_id"]),
                        org_id=_uuid(row["org_id"]),
                        owner_user_id=_uuid(row["owner_user_id"]),
                        created_at=float(row["created_at"]),
                    )
                await self.db.conn.execute("COMMIT")
                return binding
            except Exception:
                await self.db.conn.execute("ROLLBACK")
                raise

    async def require_owned_resource(
        self,
        *,
        resource_type: str,
        resource_id: str,
        principal: AccountPrincipalV1,
    ) -> ResourceBinding:
        kind, identifier = self._validate_resource(resource_type, resource_id)
        cur = await self.db.conn.execute(
            """
            SELECT resource_type, resource_id, org_id, owner_user_id, created_at
            FROM public_resource_bindings
            WHERE resource_type = ? AND resource_id = ?
              AND org_id = ? AND owner_user_id = ?
            """,
            (kind, identifier, str(principal.org_id), str(principal.user_id)),
        )
        row = await cur.fetchone()
        if row is None:
            raise AccountResourceNotFound()
        return ResourceBinding(
            resource_type=str(row["resource_type"]),
            resource_id=str(row["resource_id"]),
            org_id=_uuid(row["org_id"]),
            owner_user_id=_uuid(row["owner_user_id"]),
            created_at=float(row["created_at"]),
        )

    async def list_resource_bindings(
        self,
        *,
        resource_type: str,
    ) -> list[ResourceBinding]:
        kind, _identifier = self._validate_resource(resource_type, "placeholder")
        cur = await self.db.conn.execute(
            """
            SELECT resource_type, resource_id, org_id, owner_user_id, created_at
            FROM public_resource_bindings
            WHERE resource_type = ?
            ORDER BY created_at ASC, resource_id ASC
            """,
            (kind,),
        )
        rows = await cur.fetchall()
        return [
            ResourceBinding(
                resource_type=str(row["resource_type"]),
                resource_id=str(row["resource_id"]),
                org_id=_uuid(row["org_id"]),
                owner_user_id=_uuid(row["owner_user_id"]),
                created_at=float(row["created_at"]),
            )
            for row in rows
        ]

    async def release_resource_binding(self, binding: ResourceBinding) -> bool:
        if not isinstance(binding, ResourceBinding):
            raise TypeError("binding must be a ResourceBinding")
        kind, identifier = self._validate_resource(
            binding.resource_type,
            binding.resource_id,
        )
        async with self._write_lock:
            cur = await self.db.conn.execute(
                """
                DELETE FROM public_resource_bindings
                WHERE resource_type = ? AND resource_id = ?
                  AND org_id = ? AND owner_user_id = ?
                """,
                (
                    kind,
                    identifier,
                    str(binding.org_id),
                    str(binding.owner_user_id),
                ),
            )
            await self.db.conn.commit()
        return cur.rowcount == 1

    @staticmethod
    def _validate_quota(
        subject_key: str,
        quota_name: str,
        amount: int,
        hourly_limit: int,
        daily_limit: int,
    ) -> tuple[str, str, int, int, int]:
        subject = str(subject_key or "").strip()
        name = str(quota_name or "").strip().lower()
        units = int(amount)
        hourly = int(hourly_limit)
        daily = int(daily_limit)
        if not _PSEUDONYMOUS_SUBJECT_RE.fullmatch(subject):
            raise ValueError("pseudonymous subject_key is required")
        if not _QUOTA_NAME_RE.fullmatch(name):
            raise ValueError("invalid quota_name")
        if units < 1 or hourly < 1 or daily < 1:
            raise ValueError("quota amount and limits must be positive")
        return subject, name, units, hourly, daily

    async def consume_quota(
        self,
        *,
        subject_key: str,
        quota_name: str,
        amount: int = 1,
        hourly_limit: int,
        daily_limit: int,
        now: float | None = None,
    ) -> UsageQuotaSnapshot:
        subject, name, units, hourly, daily = self._validate_quota(
            subject_key, quota_name, amount, hourly_limit, daily_limit
        )
        checked_at = time.time() if now is None else float(now)
        hour_start = int(checked_at // 3600) * 3600
        day_start = int(checked_at // 86400) * 86400

        async with self._write_lock:
            # Both windows live in one row so this single UPSERT either advances
            # both counters or neither. It is atomic even across SQLite clients.
            cur = await self.db.conn.execute(
                """
                INSERT INTO public_usage_quotas (
                    subject_key, quota_name, hour_start, hour_used,
                    day_start, day_used, hourly_limit, daily_limit, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(subject_key, quota_name) DO UPDATE SET
                    hour_start = excluded.hour_start,
                    hour_used = CASE
                        WHEN public_usage_quotas.hour_start = excluded.hour_start
                        THEN public_usage_quotas.hour_used + excluded.hour_used
                        ELSE excluded.hour_used
                    END,
                    day_start = excluded.day_start,
                    day_used = CASE
                        WHEN public_usage_quotas.day_start = excluded.day_start
                        THEN public_usage_quotas.day_used + excluded.day_used
                        ELSE excluded.day_used
                    END,
                    hourly_limit = excluded.hourly_limit,
                    daily_limit = excluded.daily_limit,
                    updated_at = excluded.updated_at
                WHERE
                    (CASE
                        WHEN public_usage_quotas.hour_start = excluded.hour_start
                        THEN public_usage_quotas.hour_used + excluded.hour_used
                        ELSE excluded.hour_used
                    END) <= excluded.hourly_limit
                    AND
                    (CASE
                        WHEN public_usage_quotas.day_start = excluded.day_start
                        THEN public_usage_quotas.day_used + excluded.day_used
                        ELSE excluded.day_used
                    END) <= excluded.daily_limit
                """,
                (
                    subject,
                    name,
                    hour_start,
                    units,
                    day_start,
                    units,
                    hourly,
                    daily,
                    checked_at,
                ),
            )
            accepted = cur.rowcount == 1
            await self.db.conn.commit()
            cur = await self.db.conn.execute(
                """
                SELECT hour_start, hour_used, day_start, day_used
                FROM public_usage_quotas
                WHERE subject_key = ? AND quota_name = ?
                """,
                (subject, name),
            )
            row = await cur.fetchone()
            if row is None:
                raise RuntimeError("quota state unavailable")
            hour_used = (
                int(row["hour_used"]) if int(row["hour_start"]) == hour_start else 0
            )
            day_used = int(row["day_used"]) if int(row["day_start"]) == day_start else 0
            if not accepted:
                if hour_used + units > hourly:
                    raise UsageQuotaExceeded(
                        window="hour",
                        limit=hourly,
                        used=hour_used,
                        retry_after_seconds=max(1, int(hour_start + 3600 - checked_at)),
                    )
                raise UsageQuotaExceeded(
                    window="day",
                    limit=daily,
                    used=day_used,
                    retry_after_seconds=max(1, int(day_start + 86400 - checked_at)),
                )

        return UsageQuotaSnapshot(
            quota_name=name,
            hourly=UsageWindow("hour", hour_used, hourly, hour_start + 3600),
            daily=UsageWindow("day", day_used, daily, day_start + 86400),
        )

    async def quota_snapshot(
        self,
        *,
        subject_key: str,
        quota_name: str,
        hourly_limit: int,
        daily_limit: int,
        now: float | None = None,
    ) -> UsageQuotaSnapshot:
        subject, name, _units, hourly, daily = self._validate_quota(
            subject_key, quota_name, 1, hourly_limit, daily_limit
        )
        checked_at = time.time() if now is None else float(now)
        hour_start = int(checked_at // 3600) * 3600
        day_start = int(checked_at // 86400) * 86400
        async with self._write_lock:
            cur = await self.db.conn.execute(
                """
                SELECT hour_start, hour_used, day_start, day_used
                FROM public_usage_quotas
                WHERE subject_key = ? AND quota_name = ?
                """,
                (subject, name),
            )
            row = await cur.fetchone()
        hour_used = (
            int(row["hour_used"])
            if row is not None and int(row["hour_start"]) == hour_start
            else 0
        )
        day_used = (
            int(row["day_used"])
            if row is not None and int(row["day_start"]) == day_start
            else 0
        )
        return UsageQuotaSnapshot(
            quota_name=name,
            hourly=UsageWindow("hour", hour_used, hourly, hour_start + 3600),
            daily=UsageWindow("day", day_used, daily, day_start + 86400),
        )
