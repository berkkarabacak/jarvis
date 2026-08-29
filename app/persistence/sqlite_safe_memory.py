from __future__ import annotations

"""SQLite implementation of the approved-safe memory repository contract.

The schema is created explicitly by ``ensure_schema``. Importing this module
or running the application with the preview disabled has no database effect.
"""

import asyncio
import json
import re
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.db import Database
from app.persistence.safe_memory import (
    MAX_LIST_LIMIT,
    MAX_MEMORY_CHARS,
    MAX_MESSAGE_CHARS,
    MEMORY_KINDS,
    SAFE_ROLES,
    SafeConversationMessage,
    SafeMemoryConflict,
    SafeMemoryError,
    SafeMemoryItem,
    sanitize_operational_metadata,
    sanitize_safe_text,
)
from app.tenancy.errors import TenantNotFound
from app.tenancy.models import require_org_id
from app.tenancy.scope import TenantContext, hide_cross_tenant

_OPAQUE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

_SQLITE_SAFE_MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS executive_safe_messages (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    safe_text TEXT NOT NULL CHECK (length(safe_text) BETWEEN 1 AND 8000),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_by_user_id TEXT,
    created_at REAL NOT NULL,
    UNIQUE (org_id, conversation_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS ix_sqlite_safe_messages_org_conversation
    ON executive_safe_messages (org_id, conversation_id, created_at, id);

CREATE TABLE IF NOT EXISTS executive_memory_items (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    proposal_key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('preference', 'decision', 'fact', 'lesson')),
    proposed_role TEXT NOT NULL CHECK (proposed_role IN ('user', 'assistant')),
    safe_text TEXT NOT NULL CHECK (length(safe_text) BETWEEN 1 AND 4000),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'proposed'
        CHECK (status IN ('proposed', 'approved')),
    proposed_by_user_id TEXT,
    approved_by_user_id TEXT,
    proposed_at REAL NOT NULL,
    approved_at REAL,
    CHECK (
        (status = 'proposed' AND approved_by_user_id IS NULL AND approved_at IS NULL)
        OR
        (status = 'approved' AND approved_by_user_id IS NOT NULL AND approved_at IS NOT NULL)
    ),
    UNIQUE (org_id, proposal_key)
);

CREATE INDEX IF NOT EXISTS ix_sqlite_memory_items_org_status
    ON executive_memory_items (org_id, status, proposed_at DESC, id);
"""


def _opaque_ref(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not _OPAQUE_REF_RE.fullmatch(normalized):
        raise SafeMemoryError(f"{field} must be a bounded opaque identifier")
    return normalized


def _safe_role(value: str) -> str:
    role = str(value or "").strip().lower()
    if role not in SAFE_ROLES:
        raise SafeMemoryError("only bounded user/assistant safe text is allowed")
    return role


def _memory_kind(value: str) -> str:
    kind = str(value or "").strip().lower()
    if kind not in MEMORY_KINDS:
        raise SafeMemoryError(
            "memory kind must be preference, decision, fact, or lesson; "
            "code/deployment actions are not memory"
        )
    return kind


def _uuid(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _optional_uuid(value: Any) -> UUID | None:
    return UUID(str(value)) if value else None


def _timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


def _metadata(value: Any) -> dict[str, Any]:
    try:
        decoded = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        decoded = {}
    return sanitize_operational_metadata(decoded if isinstance(decoded, dict) else {})


def _message_from_row(row: Any) -> SafeConversationMessage:
    return SafeConversationMessage(
        id=UUID(str(row["id"])),
        org_id=UUID(str(row["org_id"])),
        conversation_id=str(row["conversation_id"]),
        idempotency_key=str(row["idempotency_key"]),
        role=_safe_role(str(row["role"])),  # type: ignore[arg-type]
        safe_text=sanitize_safe_text(
            str(row["safe_text"]), max_chars=MAX_MESSAGE_CHARS
        ),
        metadata=_metadata(row["metadata_json"]),
        created_by_user_id=_optional_uuid(row["created_by_user_id"]),
        created_at=_timestamp(row["created_at"]),
    )


def _memory_from_row(row: Any) -> SafeMemoryItem:
    return SafeMemoryItem(
        id=UUID(str(row["id"])),
        org_id=UUID(str(row["org_id"])),
        proposal_key=str(row["proposal_key"]),
        kind=_memory_kind(str(row["kind"])),  # type: ignore[arg-type]
        proposed_role=_safe_role(str(row["proposed_role"])),  # type: ignore[arg-type]
        safe_text=sanitize_safe_text(str(row["safe_text"]), max_chars=MAX_MEMORY_CHARS),
        metadata=_metadata(row["metadata_json"]),
        status=str(row["status"]),
        proposed_by_user_id=_optional_uuid(row["proposed_by_user_id"]),
        approved_by_user_id=_optional_uuid(row["approved_by_user_id"]),
        proposed_at=_timestamp(row["proposed_at"]),
        approved_at=_timestamp(row["approved_at"]),
    )


class SqliteSafeMemoryRepository:
    """Tenant-authorized SQLite adapter matching ``SafeMemoryRepository``."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        async with self._lock:
            await self._db.conn.executescript(_SQLITE_SAFE_MEMORY_SCHEMA)
            await self._db.conn.commit()

    @staticmethod
    def _authorize(org_id: UUID | str, actor: TenantContext, capability: str) -> UUID:
        oid = require_org_id(org_id)
        if actor.org_id != oid:
            raise hide_cross_tenant()
        actor.require(capability)
        return oid

    @staticmethod
    def _limit(limit: int) -> int:
        if isinstance(limit, bool) or not 1 <= int(limit) <= MAX_LIST_LIMIT:
            raise SafeMemoryError(f"limit must be between 1 and {MAX_LIST_LIMIT}")
        return int(limit)

    async def append_message(
        self,
        *,
        org_id: UUID | str,
        actor: TenantContext,
        conversation_id: str,
        idempotency_key: str,
        role: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> SafeConversationMessage:
        oid = self._authorize(org_id, actor, "mission.run")
        conversation = _opaque_ref(conversation_id, field="conversation_id")
        idem = _opaque_ref(idempotency_key, field="idempotency_key")
        safe_role = _safe_role(role)
        safe_text = sanitize_safe_text(text, max_chars=MAX_MESSAGE_CHARS)
        safe_metadata = sanitize_operational_metadata(metadata)
        encoded = json.dumps(safe_metadata, sort_keys=True, separators=(",", ":"))
        row_id = str(uuid4())
        now = time.time()

        async with self._lock:
            await self._db.conn.execute(
                """
                INSERT OR IGNORE INTO executive_safe_messages (
                    id, org_id, conversation_id, idempotency_key, role, safe_text,
                    metadata_json, created_by_user_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row_id,
                    str(oid),
                    conversation,
                    idem,
                    safe_role,
                    safe_text,
                    encoded,
                    str(actor.user_id),
                    now,
                ),
            )
            await self._db.conn.commit()
            cur = await self._db.conn.execute(
                """
                SELECT id, org_id, conversation_id, idempotency_key, role,
                       safe_text, metadata_json, created_by_user_id, created_at
                FROM executive_safe_messages
                WHERE org_id = ? AND conversation_id = ? AND idempotency_key = ?
                """,
                (str(oid), conversation, idem),
            )
            row = await cur.fetchone()
        if row is None:
            raise SafeMemoryConflict("safe message idempotency conflict")
        existing = _message_from_row(row)
        if (
            existing.role != safe_role
            or existing.safe_text != safe_text
            or existing.metadata != safe_metadata
        ):
            raise SafeMemoryConflict(
                "idempotency key already belongs to a different safe message"
            )
        return existing

    async def list_messages(
        self,
        *,
        org_id: UUID | str,
        actor: TenantContext,
        conversation_id: str,
        limit: int = 100,
    ) -> list[SafeConversationMessage]:
        oid = self._authorize(org_id, actor, "mission.read")
        conversation = _opaque_ref(conversation_id, field="conversation_id")
        bounded = self._limit(limit)
        cur = await self._db.conn.execute(
            """
            SELECT id, org_id, conversation_id, idempotency_key, role,
                   safe_text, metadata_json, created_by_user_id, created_at
            FROM executive_safe_messages
            WHERE org_id = ? AND conversation_id = ?
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (str(oid), conversation, bounded),
        )
        return [_message_from_row(row) for row in await cur.fetchall()]

    async def propose_memory(
        self,
        *,
        org_id: UUID | str,
        actor: TenantContext,
        proposal_key: str,
        kind: str,
        proposed_role: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> SafeMemoryItem:
        oid = self._authorize(org_id, actor, "mission.run")
        key = _opaque_ref(proposal_key, field="proposal_key")
        safe_kind = _memory_kind(kind)
        safe_role = _safe_role(proposed_role)
        safe_text = sanitize_safe_text(text, max_chars=MAX_MEMORY_CHARS)
        safe_metadata = sanitize_operational_metadata(metadata)
        encoded = json.dumps(safe_metadata, sort_keys=True, separators=(",", ":"))
        row_id = str(uuid4())
        now = time.time()

        async with self._lock:
            await self._db.conn.execute(
                """
                INSERT OR IGNORE INTO executive_memory_items (
                    id, org_id, proposal_key, kind, proposed_role, safe_text,
                    metadata_json, status, proposed_by_user_id, proposed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?)
                """,
                (
                    row_id,
                    str(oid),
                    key,
                    safe_kind,
                    safe_role,
                    safe_text,
                    encoded,
                    str(actor.user_id),
                    now,
                ),
            )
            await self._db.conn.commit()
            cur = await self._db.conn.execute(
                """
                SELECT id, org_id, proposal_key, kind, proposed_role, safe_text,
                       metadata_json, status, proposed_by_user_id,
                       approved_by_user_id, proposed_at, approved_at
                FROM executive_memory_items
                WHERE org_id = ? AND proposal_key = ?
                """,
                (str(oid), key),
            )
            row = await cur.fetchone()
        if row is None:
            raise SafeMemoryConflict("memory proposal idempotency conflict")
        existing = _memory_from_row(row)
        if (
            existing.kind != safe_kind
            or existing.proposed_role != safe_role
            or existing.safe_text != safe_text
            or existing.metadata != safe_metadata
        ):
            raise SafeMemoryConflict(
                "proposal key already belongs to a different safe memory item"
            )
        return existing

    async def approve_memory(
        self,
        *,
        org_id: UUID | str,
        actor: TenantContext,
        memory_id: UUID | str,
    ) -> SafeMemoryItem:
        oid = self._authorize(org_id, actor, "org.manage")
        mid = _uuid(memory_id)
        now = time.time()
        async with self._lock:
            await self._db.conn.execute(
                """
                UPDATE executive_memory_items
                SET status = 'approved', approved_by_user_id = ?, approved_at = ?
                WHERE id = ? AND org_id = ? AND status = 'proposed'
                """,
                (str(actor.user_id), now, str(mid), str(oid)),
            )
            await self._db.conn.commit()
            cur = await self._db.conn.execute(
                """
                SELECT id, org_id, proposal_key, kind, proposed_role, safe_text,
                       metadata_json, status, proposed_by_user_id,
                       approved_by_user_id, proposed_at, approved_at
                FROM executive_memory_items
                WHERE id = ? AND org_id = ?
                """,
                (str(mid), str(oid)),
            )
            row = await cur.fetchone()
        if row is None:
            raise hide_cross_tenant()
        existing = _memory_from_row(row)
        if existing.approved:
            return existing
        raise TenantNotFound("not found")

    async def list_memory_proposals(
        self,
        *,
        org_id: UUID | str,
        actor: TenantContext,
        limit: int = 100,
    ) -> list[SafeMemoryItem]:
        oid = self._authorize(org_id, actor, "org.manage")
        return await self._list_memory(oid=oid, status="proposed", limit=limit)

    async def list_approved_memory(
        self,
        *,
        org_id: UUID | str,
        actor: TenantContext,
        limit: int = 100,
    ) -> list[SafeMemoryItem]:
        oid = self._authorize(org_id, actor, "mission.read")
        return await self._list_memory(oid=oid, status="approved", limit=limit)

    async def _list_memory(
        self, *, oid: UUID, status: str, limit: int
    ) -> list[SafeMemoryItem]:
        bounded = self._limit(limit)
        cur = await self._db.conn.execute(
            """
            SELECT id, org_id, proposal_key, kind, proposed_role, safe_text,
                   metadata_json, status, proposed_by_user_id,
                   approved_by_user_id, proposed_at, approved_at
            FROM executive_memory_items
            WHERE org_id = ? AND status = ?
            ORDER BY proposed_at DESC, id DESC
            LIMIT ?
            """,
            (str(oid), status, bounded),
        )
        return [_memory_from_row(row) for row in await cur.fetchall()]
