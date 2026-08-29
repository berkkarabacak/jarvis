from __future__ import annotations

"""Tenant-scoped durable safe-memory contract for Executive AI consumers.

This module deliberately depends only on an asyncpg-like pool and ORCH-69's
``TenantContext``. It stores bounded, executive-safe user/assistant text. It is
not a transcript store, prompt store, tool log, code mutation mechanism, or
deployment interface.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

from app.tenancy.errors import TenantNotFound
from app.tenancy.models import require_org_id
from app.tenancy.scope import TenantContext, hide_cross_tenant

SAFE_MEMORY_CONTRACT_VERSION = "1.0.0"
MAX_MESSAGE_CHARS = 8_000
MAX_MEMORY_CHARS = 4_000
MAX_METADATA_BYTES = 4_096
MAX_LIST_LIMIT = 200

SafeRole = Literal["user", "assistant"]
MemoryKind = Literal["preference", "decision", "fact", "lesson"]

SAFE_ROLES: frozenset[str] = frozenset({"user", "assistant"})
MEMORY_KINDS: frozenset[str] = frozenset(
    {"preference", "decision", "fact", "lesson"}
)

_OPAQUE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ALLOWED_METADATA_KEYS = frozenset(
    {
        "mission_id",
        "handoff_id",
        "evidence_refs",
        "confidence",
        "source",
        "schema_version",
    }
)
_ALLOWED_SOURCES = frozenset(
    {"user", "assistant", "executive", "control_plane", "approved_handoff"}
)

# Unsafe artifact markers are rejected rather than partially persisted. These
# patterns target explicit wrappers/labels, not ordinary executive summaries.
_FORBIDDEN_ARTIFACT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?i)\b(?:chain[- ]of[- ]thought|private reasoning|internal reasoning|scratchpad)\b"
        ),
        "private reasoning",
    ),
    (re.compile(r"(?i)</?(?:think|thinking)>"), "private reasoning"),
    (
        re.compile(r"(?i)\b(?:system|developer)\s+(?:message|prompt)\b"),
        "prompt material",
    ),
    (
        re.compile(r"(?i)\braw\s+(?:prime\s+|model\s+)?transcript\b"),
        "raw transcript",
    ),
    (
        re.compile(
            r"(?im)^\s*(?:command|shell command|tool[_ -]?(?:call|input|output|result)|"
            r"function[_ -]?call|stdout|stderr|prompt)\s*[:=]"
        ),
        "tool or command output",
    ),
    (
        re.compile(r"(?im)^\s*(?:system|developer|tool|prime|assistant|user)\s*:"),
        "raw transcript",
    ),
    (
        re.compile(r"(?is)```(?:bash|sh|shell|powershell|cmd|console)\b"),
        "command block",
    ),
    (re.compile(r"(?im)^\s*\$\s+\S+"), "shell command"),
    (
        re.compile(
            r"(?i)\b(?:browser profile|browser session|session storage|localstorage|set-cookie)\b"
        ),
        "browser or session data",
    ),
    (
        re.compile(r"(?i)-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "private key",
    ),
)

_SECRET_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
        "Bearer [REDACTED_TOKEN]",
    ),
    (
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
        ),
        "[REDACTED_TOKEN]",
    ),
    (
        re.compile(
            r"(?i)\b(?:sk|xox[baprs]|gh[pousr]|AIza)[-_A-Za-z0-9]{12,}\b"
        ),
        "[REDACTED_TOKEN]",
    ),
    (
        re.compile(
            r"(?i)\b(password|passwd|credential(?:s)?|secret|token|api[_-]?key|"
            r"access[_-]?token|refresh[_-]?token|authorization|cookie|"
            r"session(?:id|_id)?)['\"]?\s*[:=]\s*['\"]?([^\s,;'\"]+)"
        ),
        r"\1=[REDACTED]",
    ),
    (
        re.compile(r"(?i)https?://[^/\s:@]+:[^@\s/]+@[^\s]+"),
        "[REDACTED_URL]",
    ),
)

_PATH_REDACTIONS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bfile://[^\s,;]+"),
    re.compile(r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/][^\s,;]+"),
    re.compile(r"(?<![A-Za-z0-9])\\\\[^\s,;]+"),
    re.compile(
        r"(?i)(?<![A-Za-z0-9])/(?:home|users|root|etc|var|tmp|opt|srv|mnt|"
        r"workspace|app|usr|run|data|dev|proc|sys|bin|sbin)/[^\s,;]+"
    ),
    re.compile(r"(?<![A-Za-z0-9])~/[^\s,;]+"),
    re.compile(r"(?<![A-Za-z0-9])\.\.?[\\/][^\s,;]+"),
)


class SafeMemoryError(ValueError):
    """Base contract error; messages never echo rejected content."""


class UnsafeMemoryContent(SafeMemoryError):
    """Input is a forbidden artifact rather than executive-safe text."""


class SafeMemoryConflict(SafeMemoryError):
    """An idempotency key was reused with a different safe payload."""


@dataclass(frozen=True)
class SafeConversationMessage:
    id: UUID
    org_id: UUID
    conversation_id: str
    idempotency_key: str
    role: SafeRole
    safe_text: str
    metadata: dict[str, Any]
    created_by_user_id: UUID | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "org_id": str(self.org_id),
            "conversation_id": self.conversation_id,
            "idempotency_key": self.idempotency_key,
            "role": self.role,
            "safe_text": self.safe_text,
            "metadata": dict(self.metadata),
            "created_by_user_id": (
                str(self.created_by_user_id) if self.created_by_user_id else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass(frozen=True)
class SafeMemoryItem:
    id: UUID
    org_id: UUID
    proposal_key: str
    kind: MemoryKind
    proposed_role: SafeRole
    safe_text: str
    metadata: dict[str, Any]
    status: str
    proposed_by_user_id: UUID | None = None
    approved_by_user_id: UUID | None = None
    proposed_at: datetime | None = None
    approved_at: datetime | None = None

    @property
    def approved(self) -> bool:
        return self.status == "approved"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "org_id": str(self.org_id),
            "proposal_key": self.proposal_key,
            "kind": self.kind,
            "proposed_role": self.proposed_role,
            "safe_text": self.safe_text,
            "metadata": dict(self.metadata),
            "status": self.status,
            "proposed_by_user_id": (
                str(self.proposed_by_user_id) if self.proposed_by_user_id else None
            ),
            "approved_by_user_id": (
                str(self.approved_by_user_id) if self.approved_by_user_id else None
            ),
            "proposed_at": self.proposed_at.isoformat() if self.proposed_at else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
        }


def _safe_role(role: str) -> SafeRole:
    normalized = (role or "").strip().lower()
    if normalized not in SAFE_ROLES:
        raise UnsafeMemoryContent("only bounded user/assistant safe text is allowed")
    return normalized  # type: ignore[return-value]


def _memory_kind(kind: str) -> MemoryKind:
    normalized = (kind or "").strip().lower()
    if normalized not in MEMORY_KINDS:
        raise SafeMemoryError(
            "memory kind must be preference, decision, fact, or lesson; "
            "code/deployment actions are not memory"
        )
    return normalized  # type: ignore[return-value]


def _opaque_ref(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not _OPAQUE_REF_RE.fullmatch(normalized):
        raise SafeMemoryError(f"{field} must be a bounded opaque identifier")
    return normalized


def sanitize_safe_text(text: str, *, max_chars: int) -> str:
    """Reject unsafe artifacts and redact incidental secrets/paths.

    Rejection is intentionally conservative. Redaction is deterministic, and
    callers receive only the safe text that is eligible for persistence.
    """

    if not isinstance(text, str):
        raise UnsafeMemoryContent("safe text must be a string")
    if len(text) > max_chars:
        raise UnsafeMemoryContent(f"safe text exceeds {max_chars} characters")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in text):
        raise UnsafeMemoryContent("safe text contains control characters")

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise UnsafeMemoryContent("safe text is required")

    for pattern, category in _FORBIDDEN_ARTIFACT_PATTERNS:
        if pattern.search(normalized):
            raise UnsafeMemoryContent(f"{category} cannot be stored")

    safe = normalized
    for pattern, replacement in _SECRET_REDACTIONS:
        safe = pattern.sub(replacement, safe)
    for pattern in _PATH_REDACTIONS:
        safe = pattern.sub("[REDACTED_PATH]", safe)

    safe = safe.strip()
    if not safe or not re.search(r"[A-Za-z0-9]", safe):
        raise UnsafeMemoryContent("safe text has no persistable content")
    if len(safe) > max_chars:
        raise UnsafeMemoryContent(f"safe text exceeds {max_chars} characters")
    return safe


def sanitize_operational_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Return bounded allowlisted metadata or reject the payload."""

    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise SafeMemoryError("metadata must be an object")
    unknown = {str(key) for key in metadata} - _ALLOWED_METADATA_KEYS
    if unknown:
        raise SafeMemoryError("metadata contains non-allowlisted keys")

    out: dict[str, Any] = {}
    for key, value in metadata.items():
        if key in {"mission_id", "handoff_id"}:
            out[key] = _opaque_ref(value, field=key)
        elif key == "evidence_refs":
            if not isinstance(value, (list, tuple)) or len(value) > 16:
                raise SafeMemoryError("evidence_refs must contain at most 16 identifiers")
            out[key] = [
                _opaque_ref(item, field="evidence_ref") for item in value
            ]
        elif key == "confidence":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SafeMemoryError("confidence must be a number from 0 to 1")
            confidence = float(value)
            if not 0.0 <= confidence <= 1.0:
                raise SafeMemoryError("confidence must be a number from 0 to 1")
            out[key] = confidence
        elif key == "source":
            source = str(value or "").strip().lower()
            if source not in _ALLOWED_SOURCES:
                raise SafeMemoryError("metadata source is not allowlisted")
            out[key] = source
        elif key == "schema_version":
            if isinstance(value, bool) or value != 1:
                raise SafeMemoryError("metadata schema_version must be 1")
            out[key] = 1

    encoded = json.dumps(out, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_METADATA_BYTES:
        raise SafeMemoryError("metadata exceeds the safe storage bound")
    return out


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return default


def _uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _optional_uuid(value: Any) -> UUID | None:
    return _uuid(value) if value else None


def _metadata_from_row(row: Any) -> dict[str, Any]:
    value = _row_get(row, "metadata_json", {}) or {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = {}
    return sanitize_operational_metadata(value if isinstance(value, dict) else {})


def _message_from_row(row: Any) -> SafeConversationMessage:
    return SafeConversationMessage(
        id=_uuid(_row_get(row, "id")),
        org_id=_uuid(_row_get(row, "org_id")),
        conversation_id=str(_row_get(row, "conversation_id") or ""),
        idempotency_key=str(_row_get(row, "idempotency_key") or ""),
        role=_safe_role(str(_row_get(row, "role") or "")),
        safe_text=sanitize_safe_text(
            str(_row_get(row, "safe_text") or ""), max_chars=MAX_MESSAGE_CHARS
        ),
        metadata=_metadata_from_row(row),
        created_by_user_id=_optional_uuid(_row_get(row, "created_by_user_id")),
        created_at=_row_get(row, "created_at"),
    )


def _memory_from_row(row: Any) -> SafeMemoryItem:
    return SafeMemoryItem(
        id=_uuid(_row_get(row, "id")),
        org_id=_uuid(_row_get(row, "org_id")),
        proposal_key=str(_row_get(row, "proposal_key") or ""),
        kind=_memory_kind(str(_row_get(row, "kind") or "")),
        proposed_role=_safe_role(str(_row_get(row, "proposed_role") or "")),
        safe_text=sanitize_safe_text(
            str(_row_get(row, "safe_text") or ""), max_chars=MAX_MEMORY_CHARS
        ),
        metadata=_metadata_from_row(row),
        status=str(_row_get(row, "status") or "proposed"),
        proposed_by_user_id=_optional_uuid(_row_get(row, "proposed_by_user_id")),
        approved_by_user_id=_optional_uuid(_row_get(row, "approved_by_user_id")),
        proposed_at=_row_get(row, "proposed_at"),
        approved_at=_row_get(row, "approved_at"),
    )


@runtime_checkable
class SafeMemoryRepository(Protocol):
    """Port ORCH-71 can consume without importing a database driver."""

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
    ) -> SafeConversationMessage: ...

    async def list_messages(
        self,
        *,
        org_id: UUID | str,
        actor: TenantContext,
        conversation_id: str,
        limit: int = 100,
    ) -> list[SafeConversationMessage]: ...

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
    ) -> SafeMemoryItem: ...

    async def approve_memory(
        self,
        *,
        org_id: UUID | str,
        actor: TenantContext,
        memory_id: UUID | str,
    ) -> SafeMemoryItem: ...

    async def list_memory_proposals(
        self,
        *,
        org_id: UUID | str,
        actor: TenantContext,
        limit: int = 100,
    ) -> list[SafeMemoryItem]: ...

    async def list_approved_memory(
        self,
        *,
        org_id: UUID | str,
        actor: TenantContext,
        limit: int = 100,
    ) -> list[SafeMemoryItem]: ...


class PostgresSafeMemoryRepository:
    """Asyncpg-like adapter for the ORCH-69 safe-memory schema."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def _conn(self) -> tuple[Any, bool]:
        acquire = getattr(self._pool, "acquire", None)
        if acquire is not None:
            return await acquire(), True
        return self._pool, False

    async def _release(self, conn: Any, owned: bool) -> None:
        if owned:
            release = getattr(self._pool, "release", None)
            if release is not None:
                await release(conn)

    @staticmethod
    def _authorize(
        org_id: UUID | str, actor: TenantContext, capability: str
    ) -> UUID:
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
        encoded_metadata = json.dumps(safe_metadata, sort_keys=True, separators=(",", ":"))

        conn, owned = await self._conn()
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO executive_safe_messages (
                    org_id, conversation_id, idempotency_key, role, safe_text,
                    metadata_json, created_by_user_id
                ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                ON CONFLICT (org_id, conversation_id, idempotency_key) DO NOTHING
                RETURNING id, org_id, conversation_id, idempotency_key, role,
                          safe_text, metadata_json, created_by_user_id, created_at
                """,
                oid,
                conversation,
                idem,
                safe_role,
                safe_text,
                encoded_metadata,
                actor.user_id,
            )
            if row is None:
                row = await conn.fetchrow(
                    """
                    SELECT id, org_id, conversation_id, idempotency_key, role,
                           safe_text, metadata_json, created_by_user_id, created_at
                    FROM executive_safe_messages
                    WHERE org_id = $1 AND conversation_id = $2 AND idempotency_key = $3
                    """,
                    oid,
                    conversation,
                    idem,
                )
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
            return _message_from_row(row)
        finally:
            await self._release(conn, owned)

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
        bounded_limit = self._limit(limit)
        conn, owned = await self._conn()
        try:
            rows = await conn.fetch(
                """
                SELECT id, org_id, conversation_id, idempotency_key, role,
                       safe_text, metadata_json, created_by_user_id, created_at
                FROM executive_safe_messages
                WHERE org_id = $1 AND conversation_id = $2
                ORDER BY created_at ASC, id ASC
                LIMIT $3
                """,
                oid,
                conversation,
                bounded_limit,
            )
            return [_message_from_row(row) for row in rows]
        finally:
            await self._release(conn, owned)

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
        encoded_metadata = json.dumps(safe_metadata, sort_keys=True, separators=(",", ":"))

        conn, owned = await self._conn()
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO executive_memory_items (
                    org_id, proposal_key, kind, proposed_role, safe_text,
                    metadata_json, status, proposed_by_user_id
                ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, 'proposed', $7)
                ON CONFLICT (org_id, proposal_key) DO NOTHING
                RETURNING id, org_id, proposal_key, kind, proposed_role, safe_text,
                          metadata_json, status, proposed_by_user_id,
                          approved_by_user_id, proposed_at, approved_at
                """,
                oid,
                key,
                safe_kind,
                safe_role,
                safe_text,
                encoded_metadata,
                actor.user_id,
            )
            if row is None:
                row = await conn.fetchrow(
                    """
                    SELECT id, org_id, proposal_key, kind, proposed_role, safe_text,
                           metadata_json, status, proposed_by_user_id,
                           approved_by_user_id, proposed_at, approved_at
                    FROM executive_memory_items
                    WHERE org_id = $1 AND proposal_key = $2
                    """,
                    oid,
                    key,
                )
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
            return _memory_from_row(row)
        finally:
            await self._release(conn, owned)

    async def approve_memory(
        self,
        *,
        org_id: UUID | str,
        actor: TenantContext,
        memory_id: UUID | str,
    ) -> SafeMemoryItem:
        oid = self._authorize(org_id, actor, "org.manage")
        mid = _uuid(memory_id)
        conn, owned = await self._conn()
        try:
            row = await conn.fetchrow(
                """
                UPDATE executive_memory_items
                SET status = 'approved', approved_by_user_id = $3, approved_at = NOW()
                WHERE id = $1 AND org_id = $2 AND status = 'proposed'
                RETURNING id, org_id, proposal_key, kind, proposed_role, safe_text,
                          metadata_json, status, proposed_by_user_id,
                          approved_by_user_id, proposed_at, approved_at
                """,
                mid,
                oid,
                actor.user_id,
            )
            if row is None:
                row = await conn.fetchrow(
                    """
                    SELECT id, org_id, proposal_key, kind, proposed_role, safe_text,
                           metadata_json, status, proposed_by_user_id,
                           approved_by_user_id, proposed_at, approved_at
                    FROM executive_memory_items
                    WHERE id = $1 AND org_id = $2
                    """,
                    mid,
                    oid,
                )
                if row is None:
                    raise hide_cross_tenant()
                existing = _memory_from_row(row)
                if existing.approved:
                    return existing
                raise TenantNotFound("not found")
            return _memory_from_row(row)
        finally:
            await self._release(conn, owned)

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
        bounded_limit = self._limit(limit)
        conn, owned = await self._conn()
        try:
            rows = await conn.fetch(
                """
                SELECT id, org_id, proposal_key, kind, proposed_role, safe_text,
                       metadata_json, status, proposed_by_user_id,
                       approved_by_user_id, proposed_at, approved_at
                FROM executive_memory_items
                WHERE org_id = $1 AND status = $2
                ORDER BY proposed_at DESC, id DESC
                LIMIT $3
                """,
                oid,
                status,
                bounded_limit,
            )
            return [_memory_from_row(row) for row in rows]
        finally:
            await self._release(conn, owned)
